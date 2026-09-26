"""Run all side effects after a workspace scan is persisted."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from releasegraph.checkout_incidents import sync_checkout_incidents_from_shop
from releasegraph.config import settings
from releasegraph.models import Project, User
from releasegraph.release_train import bootstrap_production_baseline, refresh_project_release_risks_from_scan
from releasegraph.workspace_git import sync_git_commits
from releasegraph.workspace_incidents import sync_incidents_from_scan
from releasegraph.project_scan import (
    clear_project_workspace_state,
    dismiss_scan_tickets,
    mark_workspace_synced,
    requires_manual_scan,
    skip_scan_tickets,
)
from releasegraph.proposals import close_junk_fix_proposals
from releasegraph.workspace_scan import persist_scan


def apply_workspace_scan(
    db: Session,
    project: Project,
    scan: dict[str, Any],
    *,
    actor: User | None = None,
) -> dict[str, Any]:
    if requires_manual_scan(project):
        clear_project_workspace_state(db, project)
    else:
        close_junk_fix_proposals(db, project.id)
    persisted = persist_scan(db, project, scan)
    mark_workspace_synced(project)
    if skip_scan_tickets(project):
        dismiss_scan_tickets(db, project)
        incidents = {"created": 0, "resolved": 0, "active_findings": 0}
    else:
        incidents = sync_incidents_from_scan(db, project.id, scan, actor=actor)
    checkout = sync_checkout_incidents_from_shop(
        db, project.id, settings.shop_gateway_url, actor=actor
    )
    bootstrap_production_baseline(db, project, actor=actor)
    risks_refreshed = refresh_project_release_risks_from_scan(db, project, scan)
    git_commits = sync_git_commits(db, project)
    return {
        **persisted,
        "incidents": incidents,
        "checkout_incidents": checkout,
        "releases_risk_refreshed": risks_refreshed,
        "git_commits_linked": git_commits,
    }
