"""Production release train: baseline, next release, deploy, rollback to baseline."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from releasegraph.models import (
    Build,
    Deployment,
    DeploymentStatus,
    Environment,
    Incident,
    IncidentStatus,
    Project,
    Release,
    ReleaseCommit,
    ReleasePullRequest,
    ReleaseService,
    ReleaseStatus,
    RiskFactor,
    Service,
    ServiceDependency,
    User,
)
from releasegraph.risk_engine import calculate_release_risk
from releasegraph.workspace_scan import scan_workspace

_DRAFT_STATUSES = {
    ReleaseStatus.DRAFT,
    ReleaseStatus.READY,
    ReleaseStatus.BUILDING,
    ReleaseStatus.TESTING,
}
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(.*)$", re.IGNORECASE)
_BLOCKING_CODES = frozenset({"hardcoded_secret", "sql_fstring"})


class ReleaseTrainError(Exception):
    """Business rule blocked the release action."""


def ensure_environments(db: Session, project_id: int) -> dict[str, Environment]:
    out: dict[str, Environment] = {}
    for slug, name in (("staging", "Staging"), ("production", "Production")):
        env = db.scalar(
            select(Environment).where(
                Environment.project_id == project_id,
                Environment.slug == slug,
            )
        )
        if not env:
            env = Environment(project_id=project_id, name=name, slug=slug)
            db.add(env)
            db.flush()
        out[slug] = env
    return out


def get_production_release(db: Session, project: Project) -> Release | None:
    if not project.production_release_id:
        return None
    rel = db.get(Release, project.production_release_id)
    if not rel or rel.project_id != project.id:
        return None
    return rel


def get_draft_release(db: Session, project_id: int) -> Release | None:
    return db.scalars(
        select(Release)
        .where(
            Release.project_id == project_id,
            Release.status.in_(_DRAFT_STATUSES),
        )
        .order_by(Release.created_at.desc())
    ).first()


def bump_patch_version(version: str) -> str:
    text = (version or "").strip()
    match = _SEMVER.match(text)
    if match:
        major, minor, patch, suffix = match.groups()
        prefix = "v" if text.lower().startswith("v") else ""
        return f"{prefix}{major}.{minor}.{int(patch) + 1}{suffix or ''}"
    return f"{text}.1" if text else "1.0.1"


def initial_version() -> str:
    return "1.0.0"


def _dependency_depth(db: Session, project_id: int, service_ids: set[int]) -> int:
    if not service_ids:
        return 0
    deps = db.scalars(select(ServiceDependency).where(ServiceDependency.project_id == project_id)).all()
    pairs = [(d.from_service_id, d.to_service_id) for d in deps]
    depth = 0
    frontier = set(service_ids)
    seen = set(service_ids)
    while frontier:
        depth += 1
        nxt: set[int] = set()
        for frm, to in pairs:
            if to in frontier and frm not in seen:
                nxt.add(frm)
                seen.add(frm)
        frontier = nxt
    return max(0, depth - 1)


def _attach_project_services(db: Session, release: Release) -> list[Service]:
    services = db.scalars(
        select(Service).where(Service.project_id == release.project_id).order_by(Service.name)
    ).all()
    existing = {
        rs.service_id
        for rs in db.scalars(
            select(ReleaseService).where(ReleaseService.release_id == release.id)
        ).all()
    }
    for svc in services:
        if svc.id not in existing:
            db.add(ReleaseService(release_id=release.id, service_id=svc.id))
    db.flush()
    return services


def _workspace_scan_summary(project: Project) -> tuple[str, int, int]:
    path = (project.workspace_path or "").strip()
    if not path:
        return ("", 0, 0)
    try:
        scan = scan_workspace(path)
    except OSError:
        return ("", 0, 0)
    issues = scan.get("issues") or []
    label = scan.get("name") or scan.get("workspace") or path
    return (str(label), len(issues), sum(1 for i in issues if i.get("code") in _BLOCKING_CODES))


def _deploy_block_reason(project: Project) -> str | None:
    _, _n, blocking = _workspace_scan_summary(project)
    if blocking:
        return (
            f"Deploy blocked: {blocking} critical scanner finding(s) in the workspace. "
            "Fix them on Readiness before shipping."
        )
    return None


def _refresh_release_risk(
    db: Session,
    release: Release,
    *,
    production: bool,
    scan_issue_count: int | None = None,
    scan_blocking_count: int | None = None,
) -> None:
    services = db.scalars(
        select(Service)
        .join(ReleaseService, ReleaseService.service_id == Service.id)
        .where(ReleaseService.release_id == release.id)
    ).all()
    commit_count = (
        db.scalar(select(func.count(ReleaseCommit.id)).where(ReleaseCommit.release_id == release.id)) or 0
    )
    pr_count = (
        db.scalar(select(func.count(ReleasePullRequest.id)).where(ReleasePullRequest.release_id == release.id))
        or 0
    )
    failed_builds = db.scalar(
        select(func.count(Build.id)).where(Build.release_id == release.id, Build.status == "failed")
    ) or 0
    open_incidents = db.scalar(
        select(func.count(Incident.id)).where(
            Incident.project_id == release.project_id,
            Incident.status != IncidentStatus.RESOLVED,
        )
    ) or 0
    svc_ids = {s.id for s in services}
    depth = _dependency_depth(db, release.project_id, svc_ids)
    if scan_issue_count is None and scan_blocking_count is None:
        project = db.get(Project, release.project_id)
        if project and (project.workspace_path or "").strip():
            _, scan_issue_count, scan_blocking_count = _workspace_scan_summary(project)
        else:
            scan_issue_count = None
            scan_blocking_count = None

    risk = calculate_release_risk(
        release,
        services,
        commit_count=commit_count,
        pr_count=pr_count,
        failed_builds=failed_builds,
        failed_tests=0,
        production=production,
        dependency_depth=depth,
        recent_incidents=open_incidents,
        scan_issue_count=scan_issue_count,
        scan_blocking_count=scan_blocking_count,
    )
    release.risk_level = risk.level
    release.risk_score = risk.score
    for old in db.scalars(select(RiskFactor).where(RiskFactor.release_id == release.id)).all():
        db.delete(old)
    for factor, weight, detail in risk.factors:
        db.add(RiskFactor(release_id=release.id, factor=factor, weight=weight, detail=detail))


def refresh_project_release_risks_from_scan(
    db: Session,
    project: Project,
    scan: dict[str, Any],
) -> int:
    """Re-score every release for this project from a workspace scan snapshot."""
    issues = scan.get("issues") or []
    issue_count = len(issues)
    blocking = sum(1 for i in issues if i.get("code") in _BLOCKING_CODES)
    releases = db.scalars(select(Release).where(Release.project_id == project.id)).all()
    for release in releases:
        is_prod = project.production_release_id == release.id
        _refresh_release_risk(
            db,
            release,
            production=is_prod,
            scan_issue_count=issue_count,
            scan_blocking_count=blocking,
        )
    return len(releases)


def refresh_project_release_risks(db: Session, project: Project) -> int:
    path = (project.workspace_path or "").strip()
    if not path:
        return 0
    try:
        scan = scan_workspace(path)
    except OSError:
        return 0
    return refresh_project_release_risks_from_scan(db, project, scan)


def bootstrap_production_baseline(
    db: Session,
    project: Project,
    *,
    actor: User | None = None,
) -> Release | None:
    """Create the first production release from scanned services when none exists."""
    if get_production_release(db, project):
        return get_production_release(db, project)
    services = db.scalars(
        select(Service).where(Service.project_id == project.id).order_by(Service.name)
    ).all()
    if not services:
        return None
    envs = ensure_environments(db, project.id)
    label, issue_count, _blocking = _workspace_scan_summary(project)
    summary = f"Production baseline"
    if label:
        summary += f" for {label}"
    summary += f" ({len(services)} services"
    if issue_count:
        summary += f", {issue_count} scanner finding(s) on disk"
    summary += ")"

    release = Release(
        project_id=project.id,
        version=initial_version(),
        status=ReleaseStatus.DEPLOYED,
        environment_id=envs["production"].id,
        summary=summary,
        rollback_available=False,
    )
    db.add(release)
    db.flush()
    _attach_project_services(db, release)
    _refresh_release_risk(db, release, production=True)
    dep = Deployment(
        release_id=release.id,
        environment_id=envs["production"].id,
        status=DeploymentStatus.SUCCESS,
        completed_at=datetime.now(timezone.utc),
        duration_seconds=0.0,
        initiated_by_user_id=actor.id if actor else None,
    )
    db.add(dep)
    project.production_release_id = release.id
    db.flush()
    return release


def create_next_release(
    db: Session,
    project: Project,
    *,
    summary: str | None = None,
    actor: User | None = None,
) -> Release:
    bootstrap_production_baseline(db, project, actor=actor)
    baseline = get_production_release(db, project)
    if not baseline:
        raise ReleaseTrainError("Scan a workspace first so services exist, then start the release train.")
    if get_draft_release(db, project.id):
        raise ReleaseTrainError("A release is already in progress. Deploy or discard it before starting another.")
    version = bump_patch_version(baseline.version)
    label, issue_count, _blocking = _workspace_scan_summary(project)
    auto_summary = f"Builds on production {baseline.version}"
    if label:
        auto_summary += f" ({label})"
    if issue_count:
        auto_summary += f" · {issue_count} open scanner finding(s)"
    release = Release(
        project_id=project.id,
        version=version,
        status=ReleaseStatus.DRAFT,
        summary=(summary or auto_summary).strip(),
        baseline_release_id=baseline.id,
        rollback_available=True,
    )
    db.add(release)
    db.flush()
    _attach_project_services(db, release)
    _refresh_release_risk(db, release, production=False)
    return release


def mark_release_ready(db: Session, release: Release, project: Project) -> Release:
    if release.status not in {ReleaseStatus.DRAFT, ReleaseStatus.BUILDING, ReleaseStatus.TESTING}:
        raise ReleaseTrainError(f"Release is {release.status.value}; only in-progress releases can be marked ready.")
    release.status = ReleaseStatus.READY
    _refresh_release_risk(db, release, production=False)
    return release


def deploy_release(
    db: Session,
    release: Release,
    project: Project,
    *,
    environment_slug: str,
    actor: User,
) -> dict[str, Any]:
    if release.status not in {ReleaseStatus.DRAFT, ReleaseStatus.READY}:
        raise ReleaseTrainError(f"Release is {release.status.value}; deploy only from DRAFT or READY.")
    if project.production_release_id == release.id:
        raise ReleaseTrainError("This version is already live in production.")
    reason = _deploy_block_reason(project)
    if reason:
        raise ReleaseTrainError(reason)
    envs = ensure_environments(db, project.id)
    env = envs.get(environment_slug)
    if not env:
        raise ReleaseTrainError(f"Environment '{environment_slug}' is not configured for this project.")

    previous = get_production_release(db, project)
    release.status = ReleaseStatus.DEPLOYING
    db.flush()
    dep = Deployment(
        release_id=release.id,
        environment_id=env.id,
        status=DeploymentStatus.IN_PROGRESS,
        initiated_by_user_id=actor.id,
    )
    db.add(dep)
    db.flush()

    _attach_project_services(db, release)
    _refresh_release_risk(db, release, production=environment_slug == "production")
    if not db.scalars(select(Build).where(Build.release_id == release.id)).first():
        db.add(
            Build(
                project_id=project.id,
                release_id=release.id,
                status="success",
                completed_at=datetime.now(timezone.utc),
                duration_seconds=0.0,
            )
        )

    dep.status = DeploymentStatus.SUCCESS
    dep.completed_at = datetime.now(timezone.utc)
    dep.duration_seconds = dep.duration_seconds or 1.0
    release.status = ReleaseStatus.DEPLOYED
    release.environment_id = env.id
    if environment_slug == "production":
        project.production_release_id = release.id
        if previous and previous.id != release.id:
            previous.rollback_available = True
    db.flush()
    return {
        "deployment_id": dep.id,
        "release_id": release.id,
        "version": release.version,
        "environment": environment_slug,
        "previous_production_version": previous.version if previous and previous.id != release.id else None,
        "status": release.status.value,
    }


def rollback_to_baseline(
    db: Session,
    release: Release,
    project: Project,
    *,
    actor: User,
) -> dict[str, Any]:
    if project.production_release_id != release.id:
        raise ReleaseTrainError("Rollback only applies to the release that is live in production right now.")
    if not release.baseline_release_id:
        raise ReleaseTrainError("This release has no baseline to roll back to (it is the first production version).")
    if not release.rollback_available:
        raise ReleaseTrainError("Rollback is disabled for this release.")
    baseline = db.get(Release, release.baseline_release_id)
    if not baseline or baseline.project_id != project.id:
        raise ReleaseTrainError("Baseline release record is missing.")
    env_id = release.environment_id or baseline.environment_id
    if not env_id:
        envs = ensure_environments(db, project.id)
        env_id = envs["production"].id

    release.status = ReleaseStatus.ROLLED_BACK
    db.add(
        Deployment(
            release_id=release.id,
            environment_id=env_id,
            status=DeploymentStatus.ROLLED_BACK,
            initiated_by_user_id=actor.id,
        )
    )
    baseline.status = ReleaseStatus.DEPLOYED
    baseline.rollback_available = baseline.baseline_release_id is not None
    project.production_release_id = baseline.id
    db.add(
        Deployment(
            release_id=baseline.id,
            environment_id=env_id,
            status=DeploymentStatus.SUCCESS,
            completed_at=datetime.now(timezone.utc),
            initiated_by_user_id=actor.id,
        )
    )
    db.flush()
    return {
        "rolled_back_release_id": release.id,
        "rolled_back_version": release.version,
        "production_release_id": baseline.id,
        "production_version": baseline.version,
        "status": baseline.status.value,
    }


def release_train_state(db: Session, project: Project) -> dict[str, Any]:
    bootstrap_production_baseline(db, project)
    production = get_production_release(db, project)
    draft = get_draft_release(db, project.id)
    baseline_version = None
    if draft and draft.baseline_release_id:
        base = db.get(Release, draft.baseline_release_id)
        baseline_version = base.version if base else None
    return {
        "production_release_id": production.id if production else None,
        "production_version": production.version if production else None,
        "draft_release_id": draft.id if draft else None,
        "draft_version": draft.version if draft else None,
        "draft_status": draft.status.value if draft else None,
        "draft_baseline_version": baseline_version,
        "can_start_next": draft is None and production is not None,
    }
