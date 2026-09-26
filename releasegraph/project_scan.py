"""Projects that stay empty until the user runs Scan workspace on Readiness."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import (
    FixProposal,
    FixProposalStatus,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Project,
    ReleaseService,
    Repository,
    Service,
    ServiceDependency,
)
from releasegraph.proposals import close_junk_fix_proposals
from releasegraph.verify import SCAN_CODES
from releasegraph.workspace_incidents import SCAN_PREFIX

MANUAL_SCAN_SLUGS = frozenset({"ecommerce"})
# OTT demo: map services on the graph only — no scanner tickets or code-scan incidents.
NO_SCAN_TICKETS_SLUGS = frozenset({"streaming"})


def skip_scan_tickets(project: Project | None) -> bool:
    return bool(project and project.slug in NO_SCAN_TICKETS_SLUGS)


def requires_manual_scan(project: Project | None) -> bool:
    return bool(project and project.slug in MANUAL_SCAN_SLUGS)


def workspace_is_live(project: Project | None) -> bool:
    """When false, graph/incidents/dashboard must not show scan-derived data."""
    if not project:
        return False
    if not requires_manual_scan(project):
        return True
    return project.workspace_synced_at is not None


def mark_workspace_synced(project: Project) -> None:
    project.workspace_synced_at = datetime.now(timezone.utc)


def empty_graph_payload(workspace: str | None = None) -> dict:
    return {
        "summary": "Scan a workspace on Readiness to map services and engine findings.",
        "nodes": [],
        "edges": [],
        "broken_links": [],
        "updates": [],
        "broken_services": [],
        "affected_services": [],
        "workspace": workspace,
        "awaiting_scan": True,
    }


def clear_project_workspace_state(db: Session, project: Project) -> None:
    """Remove graph, incidents, and fix tickets so the next scan is a full reset."""
    pid = project.id
    close_junk_fix_proposals(db, pid)
    open_prs = db.scalars(
        select(FixProposal).where(
            FixProposal.project_id == pid,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        )
    ).all()
    for pr in open_prs:
        pr.status = FixProposalStatus.REJECTED

    open_incs = db.scalars(
        select(Incident).where(
            Incident.project_id == pid,
            Incident.status != IncidentStatus.RESOLVED,
        )
    ).all()
    for inc in open_incs:
        inc.status = IncidentStatus.RESOLVED
        db.add(
            IncidentEvent(
                incident_id=inc.id,
                event_type="scan_cleared",
                message="Cleared before workspace scan — run Scan workspace on Readiness to repopulate.",
                actor="workspace-reset",
            )
        )

    svc_ids = [
        s.id for s in db.scalars(select(Service).where(Service.project_id == pid)).all()
    ]
    if svc_ids:
        for rs in db.scalars(select(ReleaseService).where(ReleaseService.service_id.in_(svc_ids))).all():
            db.delete(rs)
        for dep in db.scalars(select(ServiceDependency).where(ServiceDependency.project_id == pid)).all():
            db.delete(dep)
        for svc in db.scalars(select(Service).where(Service.project_id == pid)).all():
            db.delete(svc)
    for repo in db.scalars(select(Repository).where(Repository.project_id == pid)).all():
        db.delete(repo)
    db.flush()
    project.workspace_synced_at = None


def dismiss_scan_tickets(db: Session, project: Project) -> None:
    """Close Fix PRs and code-scan incidents for a project (streaming stays clean)."""
    pid = project.id
    open_prs = db.scalars(
        select(FixProposal).where(
            FixProposal.project_id == pid,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        )
    ).all()
    for pr in open_prs:
        if pr.code in SCAN_CODES or pr.code in {"missing_repo", "unknown_repo"}:
            pr.status = FixProposalStatus.REJECTED
            pr.verify_message = "Streaming platform demo — scanner tickets are disabled for this project."

    open_incs = db.scalars(
        select(Incident).where(
            Incident.project_id == pid,
            Incident.status != IncidentStatus.RESOLVED,
            Incident.title.startswith(SCAN_PREFIX),
        )
    ).all()
    for inc in open_incs:
        inc.status = IncidentStatus.RESOLVED
        db.add(
            IncidentEvent(
                incident_id=inc.id,
                event_type="scan_cleared",
                message="Streaming platform demo does not track code-scan incidents.",
                actor="streaming-clean",
            )
        )


def ensure_streaming_clean(db: Session) -> None:
    project = db.scalar(select(Project).where(Project.slug == "streaming"))
    if not project:
        return
    dismiss_scan_tickets(db, project)


def ensure_ecommerce_awaiting_scan(db: Session) -> None:
    """One-time repair: ecommerce must not show seeded graph data before a user scan."""
    project = db.scalar(select(Project).where(Project.slug == "ecommerce"))
    if not project or workspace_is_live(project):
        return
    has_graph = db.scalar(select(Service.id).where(Service.project_id == project.id).limit(1))
    has_open_inc = db.scalar(
        select(Incident.id).where(
            Incident.project_id == project.id,
            Incident.status != IncidentStatus.RESOLVED,
        ).limit(1)
    )
    has_open_pr = db.scalar(
        select(FixProposal.id).where(
            FixProposal.project_id == project.id,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        ).limit(1)
    )
    if has_graph or has_open_inc or has_open_pr:
        clear_project_workspace_state(db, project)
