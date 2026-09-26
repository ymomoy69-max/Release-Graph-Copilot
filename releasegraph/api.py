"""FastAPI routes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from releasegraph.analysis import analyze_project
from releasegraph.audit import log_audit
from releasegraph.audit_recent import recent_project_audit
from releasegraph.deploy_gate import deploy_gate_details
from releasegraph.deploy_preview import deploy_blast_radius
from releasegraph.release_commits import commits_since_baseline
from releasegraph.shop_status import shop_status_payload
from releasegraph.checkout_failure import (
    CheckoutDidNotFail,
    ShopUnavailable,
    run_checkout_failure,
)
from releasegraph.checkout_incidents import (
    checkout_incident_title,
    sync_checkout_incidents_from_shop,
)
from releasegraph.checkout_target import checkout_target_service
from releasegraph.config import settings
from releasegraph.auth import create_access_token, get_current_user, require_roles, verify_password
from releasegraph.copilot.agent import answer_question
from releasegraph.copilot.tools import CopilotTools
from releasegraph.database import get_db
from releasegraph.models import (
    Artifact,
    AuditEvent,
    Build,
    Commit,
    Deployment,
    DeploymentStatus,
    Environment,
    FixProposal,
    FixProposalStatus,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Project,
    PullRequest,
    Release,
    ReleaseCommit,
    ReleasePullRequest,
    ReleaseService,
    ReleaseStatus,
    RiskFactor,
    Service,
    TestRun,
    User,
    UserRole,
)
from releasegraph.graph_insight import build_project_graph
from releasegraph.proposals import serialize_proposal
from releasegraph.release_train import (
    ReleaseTrainError,
    bootstrap_production_baseline,
    create_next_release,
    deploy_release,
    get_draft_release,
    get_production_release,
    mark_release_ready,
    refresh_project_release_risks_from_scan,
    release_train_state,
    rollback_to_baseline,
)
from releasegraph.verify import verify_fix_ready
from releasegraph.workspace_sync import apply_workspace_scan
from releasegraph.project_presets import presets_for_project
from releasegraph.rgc_bridge import run_workspace_check
from releasegraph.schemas import (
    AnalysisRequest,
    AssignFixPrRequest,
    AuditEventOut,
    ConfirmAction,
    CopilotAskRequest,
    CopilotAskResponse,
    CreateNextReleaseRequest,
    DeployReleaseRequest,
    GraphOut,
    IncidentCreate,
    IncidentOut,
    LoginRequest,
    ProjectOut,
    ReadinessPresetOut,
    ReadinessCheckRequest,
    ReadinessCheckResponse,
    ReleaseDetailOut,
    ReleaseOut,
    DashboardOut,
    DeployGateOut,
    ShopStatusOut,
    ReleaseTrainOut,
    RollbackRequest,
    TokenResponse,
    UserOut,
    WorkspaceScanRequest,
)
from releasegraph.workspace_scan import scan_workspace, _slug
from rgc.models import Checklist as RgcChecklist

router = APIRouter(prefix="/api/v1")


def _project_out(project: Project) -> ProjectOut:
    presets = presets_for_project(project)
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        description=project.description or "",
        workspace_path=project.workspace_path or "",
        org_config_path=project.org_config_path or "",
        readiness_presets=[ReadinessPresetOut.model_validate(p) for p in presets],
    )


def _project_for_user(db: Session, user: User, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p or p.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


def _train_error(exc: ReleaseTrainError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _release_out(db: Session, project: Project, r: Release) -> ReleaseOut:
    svcs = db.scalars(
        select(Service.name)
        .join(ReleaseService, ReleaseService.service_id == Service.id)
        .where(ReleaseService.release_id == r.id)
    ).all()
    cc = db.scalar(select(func.count(ReleaseCommit.id)).where(ReleaseCommit.release_id == r.id)) or 0
    pc = db.scalar(select(func.count(ReleasePullRequest.id)).where(ReleasePullRequest.release_id == r.id)) or 0
    baseline_version = None
    if r.baseline_release_id:
        base = db.get(Release, r.baseline_release_id)
        baseline_version = base.version if base else None
    is_production = project.production_release_id == r.id
    draft = get_draft_release(db, project.id)
    gate = deploy_gate_details(db, project)
    return ReleaseOut(
        id=r.id,
        version=r.version,
        status=r.status.value,
        risk_level=r.risk_level,
        risk_score=r.risk_score,
        summary=r.summary,
        created_at=r.created_at,
        rollback_available=r.rollback_available,
        services=list(svcs),
        commits_count=cc,
        prs_count=pc,
        baseline_release_id=r.baseline_release_id,
        baseline_version=baseline_version,
        is_production=is_production,
        can_deploy=(
            r.status in {ReleaseStatus.DRAFT, ReleaseStatus.READY}
            and not is_production
            and not gate["blocked"]
        ),
        can_mark_ready=r.status in {ReleaseStatus.DRAFT, ReleaseStatus.BUILDING, ReleaseStatus.TESTING},
        can_start_next=draft is None and is_production,
        can_rollback=is_production and bool(r.baseline_release_id) and r.rollback_available,
        deploy_blocked=bool(gate["blocked"]),
        deploy_block_message=gate.get("message"),
        deploy_gate=DeployGateOut(**gate),
    )


def _project_from_workspace(db: Session, user: User, workspace: str, project_id: int | None) -> Project:
    if project_id:
        return _project_for_user(db, user, project_id)
    root = Path(workspace).expanduser().resolve()
    slug = _slug(root.name)
    existing = db.scalar(
        select(Project).where(Project.organization_id == user.organization_id, Project.slug == slug)
    )
    if existing:
        return existing
    p = Project(
        organization_id=user.organization_id,
        slug=slug,
        name=root.name,
        description=f"Scanned {root}",
        workspace_path=str(root),
    )
    db.add(p)
    db.flush()
    return p


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id, user.email, user.role.value)
    return TokenResponse(access_token=token)


@router.get("/auth/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]):
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role.value)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    rows = db.scalars(
        select(Project).where(Project.organization_id == user.organization_id).order_by(Project.name)
    ).all()
    return [_project_out(p) for p in rows]


@router.get("/services")
def list_services(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    _project_for_user(db, user, project_id)
    rows = db.scalars(select(Service).where(Service.project_id == project_id).order_by(Service.name)).all()
    return [
        {"id": s.id, "name": s.name, "criticality": s.criticality, "source_path": s.source_path}
        for s in rows
    ]


@router.post("/workspaces/scan")
def workspace_scan(
    body: WorkspaceScanRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    scan = scan_workspace(body.workspace)
    if scan.get("error") == "workspace_not_found":
        raise HTTPException(status_code=400, detail=f"Workspace not found: {body.workspace}")
    project = None
    persisted = None
    analysis = None
    if body.persist:
        project = _project_from_workspace(db, user, scan["workspace"], body.project_id)
        persisted = apply_workspace_scan(db, project, scan, actor=user)
        analysis = analyze_project(db, project.id, workspace=scan["workspace"])
        log_audit(db, user.organization_id, "workspace.scan", "project", project.id, user=user)
        db.commit()
        db.refresh(project)
    return {
        "project": _project_out(project) if project else None,
        "scan": scan,
        "persisted": persisted,
        "analysis": analysis,
    }


@router.post("/analysis/errors")
def analysis_errors(
    body: AnalysisRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _project_for_user(db, user, body.project_id)
    result = analyze_project(
        db,
        body.project_id,
        workspace=body.workspace,
        incident_id=body.incident_id,
        checklist=body.checklist,
    )
    log_audit(db, user.organization_id, "analysis.errors", "project", body.project_id, user=user)
    db.commit()
    return result


@router.get("/users", response_model=list[UserOut])
def list_org_users(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]):
    rows = db.scalars(select(User).where(User.organization_id == user.organization_id).order_by(User.full_name)).all()
    return [UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role.value) for u in rows]


def _proposal_for_user(db: Session, user: User, proposal_id: int) -> FixProposal:
    p = db.get(FixProposal, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Fix PR not found")
    _project_for_user(db, user, p.project_id)
    return p


@router.get("/fix-prs")
def list_fix_prs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    from releasegraph.project_scan import workspace_is_live

    from releasegraph.project_scan import skip_scan_tickets

    if skip_scan_tickets(project):
        from releasegraph.project_scan import dismiss_scan_tickets

        dismiss_scan_tickets(db, project)
        db.commit()
        return []
    if not workspace_is_live(project):
        return []
    rows = db.scalars(
        select(FixProposal).where(FixProposal.project_id == project_id).order_by(FixProposal.number.desc())
    ).all()
    return [serialize_proposal(db, p) for p in rows]


@router.get("/fix-prs/{proposal_id}")
def get_fix_pr(
    proposal_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return serialize_proposal(db, _proposal_for_user(db, user, proposal_id))


@router.patch("/fix-prs/{proposal_id}/assign")
def assign_fix_pr(
    proposal_id: int,
    body: AssignFixPrRequest,
    user: Annotated[User, Depends(require_roles(UserRole.RELEASE_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
):
    p = _proposal_for_user(db, user, proposal_id)
    assignee = db.get(User, body.assignee_user_id)
    if not assignee or assignee.organization_id != user.organization_id:
        raise HTTPException(status_code=400, detail="Assignee must be in this organization")
    prev = p.assignee_user_id
    p.assignee_user_id = assignee.id
    log_audit(
        db,
        user.organization_id,
        "fix_pr.assign",
        "fix_proposal",
        p.id,
        user=user,
        previous_state={"assignee_user_id": prev},
        new_state={"assignee_user_id": assignee.id, "email": assignee.email},
    )
    db.commit()
    db.refresh(p)
    return serialize_proposal(db, p)


@router.post("/fix-prs/{proposal_id}/approve")
def approve_fix_pr(
    proposal_id: int,
    body: ConfirmAction,
    user: Annotated[User, Depends(require_roles(UserRole.ENGINEER, UserRole.RELEASE_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true. A person must explicitly approve this fix ticket.")
    p = _proposal_for_user(db, user, proposal_id)
    if p.status in {FixProposalStatus.MERGED, FixProposalStatus.REJECTED}:
        raise HTTPException(status_code=400, detail=f"Cannot approve a {p.status.value} PR")
    if not p.human_required:
        raise HTTPException(status_code=400, detail="Safety gate failed: human_required must stay true")
    p.status = FixProposalStatus.APPROVED
    p.reviewed_by_user_id = user.id
    log_audit(
        db,
        user.organization_id,
        "fix_pr.approve",
        "fix_proposal",
        p.id,
        user=user,
        new_state={"number": p.number, "file": p.file_path},
    )
    db.commit()
    db.refresh(p)
    return serialize_proposal(db, p)


@router.post("/fix-prs/{proposal_id}/reject")
def reject_fix_pr(
    proposal_id: int,
    body: ConfirmAction,
    user: Annotated[User, Depends(require_roles(UserRole.ENGINEER, UserRole.RELEASE_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to reject this fix ticket.")
    p = _proposal_for_user(db, user, proposal_id)
    if p.status == FixProposalStatus.MERGED:
        raise HTTPException(status_code=400, detail="Already marked merged")
    p.status = FixProposalStatus.REJECTED
    p.reviewed_by_user_id = user.id
    log_audit(
        db,
        user.organization_id,
        "fix_pr.reject",
        "fix_proposal",
        p.id,
        user=user,
        new_state={"number": p.number},
    )
    db.commit()
    db.refresh(p)
    return serialize_proposal(db, p)


@router.post("/fix-prs/{proposal_id}/merge")
def merge_fix_pr(
    proposal_id: int,
    body: ConfirmAction,
    user: Annotated[User, Depends(require_roles(UserRole.RELEASE_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true. Merge is a human action; the LLM cannot do this.")
    p = _proposal_for_user(db, user, proposal_id)
    if p.status != FixProposalStatus.APPROVED:
        raise HTTPException(status_code=400, detail="A human must approve this PR before it can be marked merged")
    if not p.human_required:
        raise HTTPException(status_code=400, detail="Safety gate failed: human_required must stay true")
    if user.role != UserRole.ADMIN and p.reviewed_by_user_id == user.id:
        raise HTTPException(
            status_code=400,
            detail="Four-eyes: a second person must mark merged. Sign in as another release manager or admin.",
        )
    check = verify_fix_ready(db, p)
    if not check.get("ok"):
        raise HTTPException(status_code=400, detail=str(check.get("message") or "Engine still finds this issue."))
    p.status = FixProposalStatus.MERGED
    p.merged_at = datetime.now(timezone.utc)
    p.verify_message = str(check.get("message") or "")
    log_audit(
        db,
        user.organization_id,
        "fix_pr.merge",
        "fix_proposal",
        p.id,
        user=user,
        new_state={
            "number": p.number,
            "in_app": True,
            "wrote_git": False,
            "engine_verified_clean": bool(check.get("checked")),
        },
    )
    db.commit()
    db.refresh(p)
    payload = serialize_proposal(db, p)
    payload["verify"] = check.get("message")
    return payload


def _sync_shop_checkout_incidents(
    db: Session,
    project_id: int,
    user: User | None = None,
) -> None:
    out = sync_checkout_incidents_from_shop(
        db, project_id, settings.shop_gateway_url, actor=user
    )
    if out.get("resolved"):
        db.commit()


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    from releasegraph.project_scan import workspace_is_live

    if workspace_is_live(project):
        _sync_shop_checkout_incidents(db, project_id, user)
    active = db.scalar(
        select(func.count(Release.id)).where(
            Release.project_id == project_id,
            Release.status.in_([ReleaseStatus.READY, ReleaseStatus.DEPLOYING, ReleaseStatus.DEPLOYED]),
        )
    ) or 0
    recent = db.scalars(
        select(Release).where(Release.project_id == project_id).order_by(Release.created_at.desc()).limit(5)
    ).all()
    dep_counts = dict(
        db.execute(
            select(Deployment.status, func.count(Deployment.id))
            .join(Release, Release.id == Deployment.release_id)
            .where(Release.project_id == project_id)
            .group_by(Deployment.status)
        ).all()
    )
    open_inc = db.scalar(
        select(func.count(Incident.id)).where(
            Incident.project_id == project_id,
            Incident.status != IncidentStatus.RESOLVED,
        )
    ) or 0
    failed_builds = db.scalar(
        select(func.count(Build.id)).where(Build.project_id == project_id, Build.status == "failed")
    ) or 0
    svc_count = db.scalar(
        select(func.count(Service.id)).where(Service.project_id == project_id)
    ) or 0
    open_prs = db.scalar(
        select(func.count(FixProposal.id)).where(
            FixProposal.project_id == project_id,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        )
    ) or 0
    latest = db.scalars(
        select(Release).where(Release.project_id == project_id).order_by(Release.created_at.desc()).limit(1)
    ).first()
    workspace = (project.workspace_path or "") if project else ""
    scan_issue_count = 0
    scan_high_count = 0
    broken_links = 0
    workspace_label = None
    from releasegraph.project_scan import skip_scan_tickets

    if (
        workspace_is_live(project)
        and not skip_scan_tickets(project)
        and workspace
        and Path(workspace).is_dir()
    ):
        try:
            live = scan_workspace(workspace)
            workspace_label = live.get("workspace") or workspace
            issues = live.get("issues") or []
            scan_issue_count = len(issues)
            scan_high_count = sum(
                1 for i in issues if i.get("code") in {"hardcoded_secret", "sql_fstring"}
            )
            graph = build_project_graph(db, project_id)
            broken_links = len(graph.get("broken_links") or [])
            refresh_project_release_risks_from_scan(db, project, live)
            db.commit()
            recent = db.scalars(
                select(Release)
                .where(Release.project_id == project_id)
                .order_by(Release.created_at.desc())
                .limit(5)
            ).all()
        except OSError:
            pass

    insight_bits = []
    if not workspace_is_live(project):
        insight_bits.append("Scan a workspace on Readiness to populate the graph, incidents, and Fix PRs.")
    elif workspace_label:
        insight_bits.append(
            f"Live scan of {workspace_label}: {scan_issue_count} code issue(s)"
            f"{f', {scan_high_count} high severity' if scan_high_count else ''}."
        )
        if broken_links:
            insight_bits.append(f"{broken_links} breaking dependency link(s) on the graph.")
    elif latest:
        insight_bits.append(f"Latest {latest.version} is {latest.status.value} with {latest.risk_level} risk.")
    insight_bits.append(
        f"{open_prs} fix PR(s) waiting on a human."
        if open_prs
        else "Scan a workspace on Readiness to open assigned tickets from engine findings."
    )
    insight = " ".join(insight_bits)
    train = release_train_state(db, project)
    gate = deploy_gate_details(db, project)
    shop = shop_status_payload()
    prod_risk_level = None
    prod_risk_score = None
    prod_factors: list[dict[str, Any]] = []
    if project.production_release_id:
        prod = db.get(Release, project.production_release_id)
        if prod:
            prod_risk_level = prod.risk_level
            prod_risk_score = prod.risk_score
            prod_factors = [
                {"factor": f.factor, "weight": f.weight, "detail": f.detail}
                for f in db.scalars(
                    select(RiskFactor).where(RiskFactor.release_id == prod.id)
                ).all()
            ]
    audit_rows = recent_project_audit(db, user.organization_id, project_id, limit=5)
    return DashboardOut(
        active_releases=active,
        recent_releases=[
            {
                "id": r.id,
                "version": r.version,
                "status": r.status.value,
                "risk": r.risk_level,
                "is_production": project.production_release_id == r.id,
            }
            for r in recent
        ],
        deployment_status={k.value if hasattr(k, "value") else str(k): v for k, v in dep_counts.items()},
        open_incidents=open_inc,
        failed_builds=failed_builds,
        services_count=svc_count,
        open_fix_prs=open_prs,
        copilot_insight=insight,
        workspace_path=workspace_label or workspace or None,
        scan_issue_count=scan_issue_count,
        scan_high_count=scan_high_count,
        broken_links=broken_links,
        production_version=train.get("production_version"),
        production_release_id=train.get("production_release_id"),
        draft_version=train.get("draft_version"),
        production_risk_level=prod_risk_level,
        production_risk_score=prod_risk_score,
        production_risk_factors=prod_factors,
        deploy_gate=DeployGateOut(**gate),
        shop_status=ShopStatusOut(**shop),
        recent_audit=audit_rows,
    )


@router.get("/releases", response_model=list[ReleaseOut])
def list_releases(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    bootstrap_production_baseline(db, project, actor=user)
    releases = db.scalars(
        select(Release).where(Release.project_id == project_id).order_by(Release.created_at.desc())
    ).all()
    return [_release_out(db, project, r) for r in releases]


@router.get("/release-train", response_model=ReleaseTrainOut)
def get_release_train(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    bootstrap_production_baseline(db, project, actor=user)
    db.commit()
    state = release_train_state(db, project)
    return ReleaseTrainOut(**state)


@router.post("/releases/next", response_model=ReleaseOut)
def start_next_release(
    body: CreateNextReleaseRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    try:
        release = create_next_release(db, project, summary=body.summary, actor=user)
    except ReleaseTrainError as exc:
        raise _train_error(exc) from exc
    log_audit(
        db,
        user.organization_id,
        "release.create_next",
        "release",
        release.id,
        user=user,
        new_state={"version": release.version, "baseline_release_id": release.baseline_release_id},
    )
    db.commit()
    db.refresh(release)
    return _release_out(db, project, release)


@router.post("/releases/{release_id}/mark-ready", response_model=ReleaseOut)
def mark_ready(
    release_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    r = db.get(Release, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    project = _project_for_user(db, user, r.project_id)
    try:
        mark_release_ready(db, r, project)
    except ReleaseTrainError as exc:
        raise _train_error(exc) from exc
    log_audit(
        db,
        user.organization_id,
        "release.mark_ready",
        "release",
        r.id,
        user=user,
        new_state={"version": r.version, "status": r.status.value},
    )
    db.commit()
    return _release_out(db, project, r)


@router.post("/releases/{release_id}/deploy")
def deploy_release_endpoint(
    release_id: int,
    body: DeployReleaseRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required (confirm=true)")
    r = db.get(Release, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    project = _project_for_user(db, user, r.project_id)
    try:
        result = deploy_release(
            db,
            r,
            project,
            environment_slug=body.environment_slug,
            actor=user,
        )
    except ReleaseTrainError as exc:
        raise _train_error(exc) from exc
    log_audit(
        db,
        user.organization_id,
        "release.deploy",
        "release",
        r.id,
        user=user,
        new_state=result,
    )
    db.commit()
    return result


@router.get("/releases/{release_id}", response_model=ReleaseDetailOut)
def get_release(
    release_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    r = db.get(Release, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    project = _project_for_user(db, user, r.project_id)
    commits = db.scalars(
        select(Commit)
        .join(ReleaseCommit, ReleaseCommit.commit_id == Commit.id)
        .where(ReleaseCommit.release_id == r.id)
    ).all()
    prs = db.scalars(
        select(PullRequest)
        .join(ReleasePullRequest, ReleasePullRequest.pull_request_id == PullRequest.id)
        .where(ReleasePullRequest.release_id == r.id)
    ).all()
    builds = db.scalars(select(Build).where(Build.release_id == r.id)).all()
    tests: list[TestRun] = []
    artifacts: list[Artifact] = []
    for b in builds:
        tests.extend(db.scalars(select(TestRun).where(TestRun.build_id == b.id)).all())
        artifacts.extend(db.scalars(select(Artifact).where(Artifact.build_id == b.id)).all())
    deps = db.scalars(select(Deployment).where(Deployment.release_id == r.id)).all()
    factors = db.scalars(select(RiskFactor).where(RiskFactor.release_id == r.id)).all()
    env_name = None
    if r.environment_id:
        env = db.get(Environment, r.environment_id)
        env_name = env.name if env else None
    svcs = db.scalars(
        select(Service.name)
        .join(ReleaseService, ReleaseService.service_id == Service.id)
        .where(ReleaseService.release_id == r.id)
    ).all()
    base = _release_out(db, project, r)
    return ReleaseDetailOut(
        **base.model_dump(),
        commits=[{"sha": c.sha[:7], "message": c.message, "author": c.author} for c in commits],
        commits_since_baseline=commits_since_baseline(db, r),
        pull_requests=[{"number": p.number, "title": p.title} for p in prs],
        builds=[{"id": b.id, "status": b.status, "duration_seconds": b.duration_seconds} for b in builds],
        tests=[{"suite": t.suite, "status": t.status, "passed": t.passed, "failed": t.failed} for t in tests],
        artifacts=[{"name": a.name, "version": a.version, "uri": a.uri} for a in artifacts],
        deployments=[{"id": d.id, "status": d.status.value, "started_at": d.started_at.isoformat()} for d in deps],
        risk_factors=[{"factor": f.factor, "weight": f.weight, "detail": f.detail} for f in factors],
        environment=env_name,
    )


@router.get("/releases/{release_id}/deploy-preview")
def release_deploy_preview(
    release_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    r = db.get(Release, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    _project_for_user(db, user, r.project_id)
    return deploy_blast_radius(db, r)


@router.get("/shop-status", response_model=ShopStatusOut)
def get_shop_status(user: Annotated[User, Depends(get_current_user)]):
    return ShopStatusOut(**shop_status_payload())


@router.post("/incidents/sync-shop")
def sync_shop_incidents(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    from releasegraph.project_scan import workspace_is_live

    if not workspace_is_live(project):
        raise HTTPException(
            status_code=400,
            detail="Scan a workspace on Readiness before syncing shop incidents.",
        )
    _sync_shop_checkout_incidents(db, project_id, user)
    return {"ok": True, **shop_status_payload()}


@router.post("/fix-prs/{proposal_id}/rescan-verify")
def rescan_verify_fix_pr(
    proposal_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    p = _proposal_for_user(db, user, proposal_id)
    project = _project_for_user(db, user, p.project_id)
    check = verify_fix_ready(db, p)
    p.verify_message = str(check.get("message") or "")
    scan_summary = None
    path = (project.workspace_path or "").strip()
    if path:
        try:
            scan = scan_workspace(path)
            apply_workspace_scan(db, project, scan, actor=user)
            scan_summary = {
                "issues": len(scan.get("issues") or []),
                "workspace": scan.get("workspace") or path,
            }
        except OSError as exc:
            scan_summary = {"error": str(exc)}
    log_audit(
        db,
        user.organization_id,
        "fix_pr.rescan_verify",
        "fix_proposal",
        p.id,
        user=user,
        new_state={"verified": bool(check.get("ok")), "scan": scan_summary},
    )
    db.commit()
    db.refresh(p)
    payload = serialize_proposal(db, p)
    payload["verify"] = check.get("message")
    payload["scan"] = scan_summary
    return payload


@router.get("/graph", response_model=GraphOut)
def release_graph(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    _project_for_user(db, user, project_id)
    data = build_project_graph(db, project_id)
    return GraphOut(
        nodes=data.get("nodes") or [],
        edges=data.get("edges") or [],
        summary=data.get("summary") or "",
        broken_links=data.get("broken_links") or [],
        updates=data.get("updates") or [],
        broken_services=data.get("broken_services") or [],
        affected_services=data.get("affected_services") or [],
        workspace=data.get("workspace"),
    )


@router.post("/copilot/ask", response_model=CopilotAskResponse)
def copilot_ask(
    body: CopilotAskRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
):
    _project_for_user(db, user, body.project_id)
    answer, tools_used = answer_question(db, body.project_id, body.question)
    log_audit(
        db,
        user.organization_id,
        "copilot.ask",
        "copilot",
        body.project_id,
        user=user,
        new_state={"question": body.question, "tools": [t["tool"] for t in tools_used]},
        ai_generated=True,
        metadata={"request_id": getattr(request.state, "request_id", None)},
    )
    db.commit()
    return CopilotAskResponse(answer=answer, tool_calls=tools_used)


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    project = _project_for_user(db, user, project_id)
    from releasegraph.project_scan import workspace_is_live

    from releasegraph.project_scan import dismiss_scan_tickets, skip_scan_tickets
    from releasegraph.workspace_incidents import SCAN_PREFIX

    if skip_scan_tickets(project):
        dismiss_scan_tickets(db, project)
        db.commit()
    if not workspace_is_live(project):
        return []
    _sync_shop_checkout_incidents(db, project_id, user)
    rows = db.scalars(
        select(Incident).where(Incident.project_id == project_id).order_by(Incident.created_at.desc())
    ).all()
    if skip_scan_tickets(project):
        rows = [i for i in rows if not i.title.startswith(SCAN_PREFIX)]
    out = []
    for i in rows:
        svc = db.get(Service, i.service_id) if i.service_id else None
        out.append(
            IncidentOut(
                id=i.id,
                title=i.title,
                status=i.status.value,
                severity=i.severity,
                service_name=svc.name if svc else None,
                created_at=i.created_at,
            )
        )
    return out


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    inc = db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    _project_for_user(db, user, inc.project_id)
    _sync_shop_checkout_incidents(db, inc.project_id, user)
    return CopilotTools(db, inc.project_id).get_incidents(incident_id)


@router.post("/incidents", response_model=IncidentOut)
def create_incident(
    body: IncidentCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    _project_for_user(db, user, project_id)
    inc = Incident(
        project_id=project_id,
        title=body.title,
        severity=body.severity,
        service_id=body.service_id,
        status=IncidentStatus.OPEN,
    )
    db.add(inc)
    db.flush()
    db.add(
        IncidentEvent(
            incident_id=inc.id,
            event_type="incident_created",
            message=body.title,
            actor=user.email,
        )
    )
    log_audit(db, user.organization_id, "incident.create", "incident", inc.id, user=user)
    db.commit()
    svc = db.get(Service, inc.service_id) if inc.service_id else None
    return IncidentOut(
        id=inc.id,
        title=inc.title,
        status=inc.status.value,
        severity=inc.severity,
        service_name=svc.name if svc else None,
        created_at=inc.created_at,
    )


@router.post("/releases/{release_id}/rollback")
def rollback_release(
    release_id: int,
    body: RollbackRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required (confirm=true)")
    r = db.get(Release, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    project = _project_for_user(db, user, r.project_id)
    try:
        result = rollback_to_baseline(db, r, project, actor=user)
    except ReleaseTrainError as exc:
        raise _train_error(exc) from exc
    log_audit(
        db,
        user.organization_id,
        "release.rollback",
        "release",
        r.id,
        user=user,
        previous_state={"production": result["rolled_back_version"]},
        new_state={"production": result["production_version"]},
    )
    db.commit()
    return {"ok": True, **result}


def _record_checkout_failure(
    user: User,
    db: Session,
    project_id: int,
):
    """Turn payment failure on, place one order, and store the gateway response."""
    project = _project_for_user(db, user, project_id)
    from releasegraph.project_scan import workspace_is_live

    if not workspace_is_live(project):
        raise HTTPException(
            status_code=400,
            detail="Scan a workspace on Readiness before running a checkout failure demo.",
        )
    svc = checkout_target_service(db, project_id)
    if not svc:
        raise HTTPException(
            status_code=404,
            detail="No services in this project. Scan a workspace first.",
        )
    checkout_title = checkout_incident_title(svc.name)
    try:
        probe = run_checkout_failure(settings.shop_gateway_url, service_name=svc.name)
    except ShopUnavailable as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except CheckoutDidNotFail as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    existing = db.scalar(
        select(Incident)
        .where(
            Incident.project_id == project_id,
            Incident.service_id == svc.id,
            Incident.title == checkout_title,
            Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.INVESTIGATING]),
        )
        .order_by(Incident.created_at.desc())
    )
    if existing:
        for event_type, message in probe.steps:
            db.add(
                IncidentEvent(
                    incident_id=existing.id,
                    event_type=event_type,
                    message=message,
                    actor=user.email,
                )
            )
        log_audit(
            db,
            user.organization_id,
            "incident.checkout_failure",
            "incident",
            existing.id,
            user=user,
            new_state={"http_status": probe.http_status, "detail": probe.detail, "reused": True},
        )
        db.commit()
        return {
            "incident_id": existing.id,
            "service": svc.name,
            "reused": True,
            "http_status": probe.http_status,
            "message": (
                f"Checkout failed again (HTTP {probe.http_status}: {probe.detail}). "
                "Added the shop response to the open incident. Payment failure mode is still on."
            ),
        }

    production = get_production_release(db, project)
    inc = Incident(
        project_id=project_id,
        title=checkout_title,
        status=IncidentStatus.OPEN,
        severity="critical",
        service_id=svc.id,
        release_id=production.id if production else None,
    )
    db.add(inc)
    db.flush()
    for event_type, message in probe.steps:
        db.add(
            IncidentEvent(
                incident_id=inc.id,
                event_type=event_type,
                message=message,
                actor=user.email,
            )
        )
    log_audit(
        db,
        user.organization_id,
        "incident.checkout_failure",
        "incident",
        inc.id,
        user=user,
        new_state={"http_status": probe.http_status, "detail": probe.detail},
    )
    db.commit()
    return {
        "incident_id": inc.id,
        "service": svc.name,
        "reused": False,
        "http_status": probe.http_status,
        "message": (
            f"Checkout failed (HTTP {probe.http_status}: {probe.detail}). "
            "Opened an incident from the live shop response. Payment failure mode is still on."
        ),
    }


@router.post("/incidents/checkout-failure")
def open_checkout_failure(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    return _record_checkout_failure(user, db, project_id)


@router.post("/readiness/check", response_model=ReadinessCheckResponse)
def readiness_check(
    body: ReadinessCheckRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Scan the workspace on disk and run rgc when org.yaml is present under that path."""
    if body.preset or body.release_file:
        raise HTTPException(
            status_code=400,
            detail="Presets and fixture manifests are disabled. Provide workspace with your repo path.",
        )
    if not body.workspace:
        raise HTTPException(status_code=400, detail="workspace path is required")

    workspace = body.workspace
    root = Path(body.workspace).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Workspace not found: {body.workspace}")

    result = None
    cfg = body.config
    if not cfg:
        for cand in (root / "org.yaml", root / "fixtures" / "org.yaml"):
            if cand.is_file():
                cfg = str(cand)
                break
    repos = body.repos
    if cfg:
        result = run_workspace_check(
            body.workspace,
            cfg,
            repos or [],
            ci_dir=body.ci_dir,
            changed_paths=body.changed_paths,
        )
    try:
        scan = scan_workspace(body.workspace)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        issues = (scan or {}).get("issues") or []
        blocked = [i for i in issues if i.get("code") in {"hardcoded_secret", "sql_fstring"}]
        checklist_dict = {
            "release_id": (scan or {}).get("name") or "workspace-scan",
            "verdict": "no_go" if blocked else "go",
            "risk": "HIGH" if blocked else "MEDIUM" if issues else "LOW",
            "gate": "blocked" if blocked else "pending_approval",
            "block_report": None,
            "checks": [],
            "note": "No org.yaml — ran the workspace scanner and AI analysis only.",
        }
    else:
        checklist_dict = result.to_dict() if isinstance(result, RgcChecklist) else result

    analysis = None
    project: Project | None = None
    if body.project_id:
        project = _project_for_user(db, user, body.project_id)
    elif body.persist and workspace:
        project = _project_from_workspace(db, user, workspace, None)

    if project and cfg:
        project.org_config_path = cfg
    elif project and not (project.org_config_path or "").strip():
        for cand in (root / "org.yaml", root / "fixtures" / "org.yaml"):
            if cand.is_file():
                project.org_config_path = str(cand.resolve())
                break

    if body.persist and project and scan:
        ws = workspace or body.workspace or (project.workspace_path or None)
        if ws:
            apply_workspace_scan(db, project, scan, actor=user)
        analysis = analyze_project(
            db,
            project.id,
            workspace=ws or None,
            checklist=checklist_dict,
        )

    log_audit(
        db,
        user.organization_id,
        "readiness.check",
        "rgc_checklist",
        checklist_dict.get("release_id", "unknown"),
        user=user,
        new_state={"verdict": checklist_dict.get("verdict"), "workspace": workspace},
    )
    db.commit()
    gate_out = None
    train_out = None
    org_path = cfg
    if project:
        gate_out = DeployGateOut(**deploy_gate_details(db, project))
        train_out = ReleaseTrainOut(**release_train_state(db, project))
        org_path = project.org_config_path or cfg
    return ReadinessCheckResponse(
        checklist=checklist_dict,
        ready_to_release=checklist_dict.get("verdict") == "go" and not (gate_out and gate_out.blocked),
        analysis=analysis,
        scan=scan,
        deploy_gate=gate_out,
        release_train=train_out,
        org_config_path=org_path,
    )


@router.get("/audit", response_model=list[AuditEventOut])
def audit_log(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, le=200),
):
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.organization_id == user.organization_id)
        .order_by(AuditEvent.timestamp.desc())
        .limit(limit)
    ).all()
    out = []
    for e in rows:
        u = db.get(User, e.user_id) if e.user_id else None
        out.append(
            AuditEventOut(
                id=e.id,
                timestamp=e.timestamp,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                ai_generated=e.ai_generated,
                user_email=u.email if u else None,
            )
        )
    return out
