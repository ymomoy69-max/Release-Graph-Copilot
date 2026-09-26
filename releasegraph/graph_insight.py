"""Project graph + last-ship updates for the UI."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.insight_core import build_insight
from releasegraph.models import (
    Commit,
    Incident,
    IncidentStatus,
    Project,
    Release,
    ReleaseCommit,
    ReleaseService,
    Repository,
    Service,
    ServiceDependency,
)
from releasegraph.workspace_scan import scan_workspace


def _updates(db: Session, project_id: int) -> list[dict[str, Any]]:
    release = db.scalars(
        select(Release).where(Release.project_id == project_id).order_by(Release.created_at.desc())
    ).first()
    if not release:
        return []
    svc_names = db.scalars(
        select(Service.name)
        .join(ReleaseService, ReleaseService.service_id == Service.id)
        .where(ReleaseService.release_id == release.id)
    ).all()
    commits = db.scalars(
        select(Commit)
        .join(ReleaseCommit, ReleaseCommit.commit_id == Commit.id)
        .where(ReleaseCommit.release_id == release.id)
    ).all()
    by_repo: dict[str, list[str]] = {}
    for c in commits:
        repo = db.get(Repository, c.repository_id)
        if not repo:
            continue
        by_repo.setdefault(repo.name, []).append(c.message)
    out = []
    for name in svc_names:
        msgs = by_repo.get(name) or []
        if not msgs:
            continue
        out.append(
            {
                "service": name,
                "version": release.version,
                "functionality": msgs[0],
                "also": msgs[1:3],
            }
        )
    if not out and release.summary:
        out.append(
            {
                "service": svc_names[0] if svc_names else "release",
                "version": release.version,
                "functionality": release.summary,
                "also": [],
            }
        )
    return out


def _incidents(db: Session, project_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Incident).where(
            Incident.project_id == project_id,
            Incident.status != IncidentStatus.RESOLVED,
        )
    ).all()
    out = []
    for inc in rows:
        svc = db.get(Service, inc.service_id) if inc.service_id else None
        out.append({"service": svc.name if svc else None, "title": inc.title, "id": inc.id})
    return out


def build_project_graph(db: Session, project_id: int) -> dict[str, Any]:
    project = db.get(Project, project_id)
    svcs = db.scalars(select(Service).where(Service.project_id == project_id).order_by(Service.name)).all()
    deps = db.scalars(select(ServiceDependency).where(ServiceDependency.project_id == project_id)).all()
    by_id = {s.id: s.name for s in svcs}
    services = [{"name": s.name, "criticality": s.criticality, "source_path": s.source_path} for s in svcs]
    dependencies = [
        {"from": by_id[d.from_service_id], "to": by_id[d.to_service_id]}
        for d in deps
        if d.from_service_id in by_id and d.to_service_id in by_id
    ]
    issues: list[dict[str, Any]] = []
    workspace = (project.workspace_path if project else "") or ""
    if workspace:
        scan = scan_workspace(workspace)
        for raw in scan.get("issues") or []:
            issues.append(
                {
                    "file": raw.get("file"),
                    "line": raw.get("line"),
                    "service": raw.get("service"),
                    "code": raw.get("code"),
                    "severity": "high" if raw.get("code") in {"hardcoded_secret", "sql_fstring"} else "medium",
                    "problem": raw.get("snippet") or raw.get("code"),
                }
            )
    insight = build_insight(
        services=services,
        dependencies=dependencies,
        issues=issues,
        updates=_updates(db, project_id),
        incidents=_incidents(db, project_id),
    )
    insight["workspace"] = workspace or None
    return insight
