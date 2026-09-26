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
from releasegraph.workspace_scan import persist_scan


def apply_workspace_scan(
    db: Session,
    project: Project,
    scan: dict[str, Any],
    *,
    actor: User | None = None,
) -> dict[str, Any]:
    persisted = persist_scan(db, project, scan)
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
