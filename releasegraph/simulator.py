"""CI/CD simulator — writes real rows to the database (labeled demo)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.audit import log_audit
from releasegraph.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    Release,
    ReleaseStatus,
    User,
)


def run_simulated_deployment(
    db: Session,
    release: Release,
    environment_slug: str,
    user: User,
) -> dict:
    env = db.scalar(
        select(Environment).where(
            Environment.project_id == release.project_id,
            Environment.slug == environment_slug,
        )
    )
    if not env:
        raise ValueError(f"Environment {environment_slug} not found")

    release.status = ReleaseStatus.DEPLOYING
    dep = Deployment(
        release_id=release.id,
        environment_id=env.id,
        status=DeploymentStatus.IN_PROGRESS,
        initiated_by_user_id=user.id,
    )
    db.add(dep)
    db.flush()

    # Simulated success (demo)
    dep.status = DeploymentStatus.SUCCESS
    dep.completed_at = datetime.now(timezone.utc)
    dep.duration_seconds = 120.0
    release.status = ReleaseStatus.DEPLOYED
    release.environment_id = env.id

    log_audit(
        db,
        user.organization_id,
        "simulator.deploy",
        "deployment",
        dep.id,
        user=user,
        new_state={"release": release.version, "environment": environment_slug, "simulated": True},
        metadata={"label": "CI/CD Simulator (demo)"},
    )
    return {
        "deployment_id": dep.id,
        "status": dep.status.value,
        "simulated": True,
        "message": "Simulated deployment completed successfully",
    }
