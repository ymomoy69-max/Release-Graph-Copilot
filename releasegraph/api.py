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
from releasegraph.rgc_bridge import PRESETS, run_manifest_check, run_workspace_check
from releasegraph.schemas import (
    AnalysisRequest,
    AssignFixPrRequest,
    AuditEventOut,
    ConfirmAction,
    CopilotAskRequest,
    CopilotAskResponse,
    DashboardOut,
    GraphOut,
    IncidentCreate,
    IncidentOut,
    LoginRequest,
    ProjectOut,
    ReadinessCheckRequest,
    ReadinessCheckResponse,
    ReadinessPresetOut,
    ReleaseDetailOut,
    ReleaseOut,
    RollbackRequest,
    SimulateDeployRequest,
    TokenResponse,
    UserOut,
    WorkspaceScanRequest,
)
from releasegraph.workspace_scan import persist_scan, scan_workspace, _slug
from rgc.models import Checklist as RgcChecklist

router = APIRouter(prefix="/api/v1")


def _project_for_user(db: Session, user: User, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p or p.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


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
    return rows


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
        persisted = persist_scan(db, project, scan)
        analysis = analyze_project(db, project.id, workspace=scan["workspace"])
        log_audit(db, user.organization_id, "workspace.scan", "project", project.id, user=user)
        db.commit()
        db.refresh(project)
    return {
        "project": ProjectOut.model_validate(project) if project else None,
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
    _project_for_user(db, user, project_id)
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
        raise HTTPException(status_code=400, detail="Set confirm=true. A person must explicitly approve this demo PR.")
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
        raise HTTPException(status_code=400, detail="Set confirm=true to reject this demo PR.")
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
    p.status = FixProposalStatus.MERGED
    p.merged_at = datetime.now(timezone.utc)
    log_audit(
        db,
        user.organization_id,
        "fix_pr.merge",
        "fix_proposal",
        p.id,
        user=user,
        new_state={"number": p.number, "demo": True, "wrote_git": False},
    )
    db.commit()
    db.refresh(p)
    return serialize_proposal(db, p)


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    _project_for_user(db, user, project_id)
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
    insight_bits = []
    if latest:
        insight_bits.append(f"Latest {latest.version} is {latest.status.value} with {latest.risk_level} risk.")
    insight_bits.append(
        f"{open_prs} demo fix PR(s) waiting on a human."
        if open_prs
        else "No open fix PRs — scan a workspace to create assigned tickets from engine findings."
    )
    insight = " ".join(insight_bits)
    return DashboardOut(
        active_releases=active,
        recent_releases=[
            {"id": r.id, "version": r.version, "status": r.status.value, "risk": r.risk_level}
            for r in recent
        ],
        deployment_status={k.value if hasattr(k, "value") else str(k): v for k, v in dep_counts.items()},
        open_incidents=open_inc,
        failed_builds=failed_builds,
        services_count=svc_count,
        open_fix_prs=open_prs,
        copilot_insight=insight,
    )


@router.get("/releases", response_model=list[ReleaseOut])
def list_releases(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
):
    _project_for_user(db, user, project_id)
    releases = db.scalars(
        select(Release).where(Release.project_id == project_id).order_by(Release.created_at.desc())
    ).all()
    out = []
    for r in releases:
        svcs = db.scalars(
            select(Service.name)
            .join(ReleaseService, ReleaseService.service_id == Service.id)
            .where(ReleaseService.release_id == r.id)
        ).all()
        cc = db.scalar(
            select(func.count(ReleaseCommit.id)).where(ReleaseCommit.release_id == r.id)
        ) or 0
        pc = db.scalar(
            select(func.count(ReleasePullRequest.id)).where(ReleasePullRequest.release_id == r.id)
        ) or 0
        out.append(
            ReleaseOut(
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
            )
        )
    return out


@router.get("/releases/{release_id}", response_model=ReleaseDetailOut)
def get_release(
    release_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    r = db.get(Release, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    _project_for_user(db, user, r.project_id)
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
    return ReleaseDetailOut(
        id=r.id,
        version=r.version,
        status=r.status.value,
        risk_level=r.risk_level,
        risk_score=r.risk_score,
        summary=r.summary,
        created_at=r.created_at,
        rollback_available=r.rollback_available,
        services=list(svcs),
        commits_count=len(commits),
        prs_count=len(prs),
        commits=[{"sha": c.sha[:7], "message": c.message, "author": c.author} for c in commits],
        pull_requests=[{"number": p.number, "title": p.title} for p in prs],
        builds=[{"id": b.id, "status": b.status, "duration_seconds": b.duration_seconds} for b in builds],
        tests=[{"suite": t.suite, "status": t.status, "passed": t.passed, "failed": t.failed} for t in tests],
        artifacts=[{"name": a.name, "version": a.version, "uri": a.uri} for a in artifacts],
        deployments=[{"id": d.id, "status": d.status.value, "started_at": d.started_at.isoformat()} for d in deps],
        risk_factors=[{"factor": f.factor, "weight": f.weight, "detail": f.detail} for f in factors],
        environment=env_name,
    )


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
    _project_for_user(db, user, project_id)
    rows = db.scalars(
        select(Incident).where(Incident.project_id == project_id).order_by(Incident.created_at.desc())
    ).all()
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
    _project_for_user(db, user, r.project_id)
    if not r.rollback_available:
        raise HTTPException(status_code=400, detail="Rollback not available for this release")
    r.status = ReleaseStatus.ROLLED_BACK
    dep = Deployment(
        release_id=r.id,
        environment_id=r.environment_id or 1,
        status=DeploymentStatus.ROLLED_BACK,
        initiated_by_user_id=user.id,
    )
    db.add(dep)
    log_audit(
        db,
        user.organization_id,
        "release.rollback",
        "release",
        r.id,
        user=user,
        previous_state={"status": "DEPLOYED"},
        new_state={"status": "ROLLED_BACK"},
    )
    db.commit()
    return {"ok": True, "release_id": r.id, "status": r.status.value}


@router.post("/simulator/deploy")
def simulate_deploy(
    body: SimulateDeployRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    from releasegraph.simulator import run_simulated_deployment

    r = db.get(Release, body.release_id)
    if not r:
        raise HTTPException(status_code=404, detail="Release not found")
    _project_for_user(db, user, r.project_id)
    result = run_simulated_deployment(db, r, body.environment_slug, user)
    db.commit()
    return result


@router.post("/simulator/payment-failure")
def trigger_payment_failure(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: int = Query(...),
    service_name: str | None = Query(None),
):
    """Demo: create an incident for a real service in this project (not a hardcoded name)."""
    _project_for_user(db, user, project_id)
    svc = None
    if service_name:
        svc = db.scalar(
            select(Service).where(Service.project_id == project_id, Service.name == service_name)
        )
    if svc is None:
        high = db.scalars(
            select(Service)
            .where(Service.project_id == project_id, Service.criticality == "high")
            .order_by(Service.name)
        ).first()
        svc = high or db.scalars(select(Service).where(Service.project_id == project_id).order_by(Service.name)).first()
    if not svc:
        raise HTTPException(status_code=404, detail="No services in this project. Scan a workspace first.")
    latest_release = db.scalars(
        select(Release).where(Release.project_id == project_id).order_by(Release.created_at.desc()).limit(1)
    ).first()
    inc = Incident(
        project_id=project_id,
        title=f"Simulated {svc.name} failure",
        status=IncidentStatus.OPEN,
        severity="critical",
        service_id=svc.id,
        release_id=latest_release.id if latest_release else None,
    )
    db.add(inc)
    db.flush()
    db.add(
        IncidentEvent(
            incident_id=inc.id,
            event_type="simulation",
            message=f"Demo failure mode recorded for {svc.name}",
            actor=user.email,
        )
    )
    log_audit(db, user.organization_id, "simulation.service_failure", "incident", inc.id, user=user)
    db.commit()
    return {"incident_id": inc.id, "service": svc.name, "message": f"Failure scenario recorded for {svc.name} (demo)"}


@router.get("/readiness/presets", response_model=list[ReadinessPresetOut])
def readiness_presets(user: Annotated[User, Depends(get_current_user)]):
    """Demo presets and paths for the rgc engine (repo workspace + org YAML)."""
    return [
        ReadinessPresetOut(id=k, label=v["label"], kind=v["kind"])
        for k, v in PRESETS.items()
    ]


@router.post("/readiness/check", response_model=ReadinessCheckResponse)
def readiness_check(
    body: ReadinessCheckRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Scan a workspace and/or run the rgc GO/NO-GO engine when org YAML is present."""
    result = None
    scan = None
    workspace = body.workspace
    if body.preset:
        spec = PRESETS.get(body.preset)
        if not spec:
            raise HTTPException(status_code=400, detail="Unknown preset")
        workspace = spec.get("workspace") or workspace
        if spec["kind"] == "manifest":
            result = run_manifest_check(spec["release_file"])
        else:
            result = run_workspace_check(
                spec["workspace"],
                spec["config"],
                spec["repos"],
                ci_dir=spec.get("ci_dir"),
                changed_paths=spec.get("changed_paths"),
            )
    elif body.release_file:
        result = run_manifest_check(body.release_file)
    elif body.workspace:
        root = Path(body.workspace).expanduser()
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
        scan = scan_workspace(body.workspace)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide preset, release_file, or workspace path",
        )

    if workspace and scan is None:
        try:
            scan = scan_workspace(workspace)
        except OSError:
            scan = None

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
    if body.persist and body.project_id:
        project = _project_for_user(db, user, body.project_id)
        ws = workspace or body.workspace or (project.workspace_path or None)
        if scan and ws:
            persist_scan(db, project, scan)
        analysis = analyze_project(
            db,
            project.id,
            workspace=ws or None,
            checklist=checklist_dict,
        )
    elif body.persist and workspace:
        project = _project_from_workspace(db, user, workspace, None)
        if scan:
            persist_scan(db, project, scan)
        analysis = analyze_project(
            db,
            project.id,
            workspace=workspace,
            checklist=checklist_dict,
        )

    log_audit(
        db,
        user.organization_id,
        "readiness.check",
        "rgc_checklist",
        checklist_dict.get("release_id", "unknown"),
        user=user,
        new_state={"verdict": checklist_dict.get("verdict"), "preset": body.preset},
    )
    db.commit()
    return ReadinessCheckResponse(
        checklist=checklist_dict,
        ready_to_release=checklist_dict.get("verdict") == "go",
        analysis=analysis,
        scan=scan,
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
