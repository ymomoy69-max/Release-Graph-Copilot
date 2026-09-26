"""Pre-deploy blast radius from stored graph dependencies."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Release, ReleaseService, Service, ServiceDependency
from releasegraph.risk_engine import blast_radius


def deploy_blast_radius(db: Session, release: Release) -> dict[str, list[str]]:
    services = db.scalars(
        select(Service)
        .join(ReleaseService, ReleaseService.service_id == Service.id)
        .where(ReleaseService.release_id == release.id)
    ).all()
    if not services:
        return {"release_services": [], "affected_services": []}
    svc_ids = {s.id for s in services}
    pairs = [
        (d.from_service_id, d.to_service_id)
        for d in db.scalars(
            select(ServiceDependency).where(ServiceDependency.project_id == release.project_id)
        ).all()
    ]
    affected_ids = blast_radius(svc_ids, pairs)
    by_id = {s.id: s.name for s in db.scalars(select(Service).where(Service.project_id == release.project_id)).all()}
    release_names = sorted(s.name for s in services)
    affected_names = sorted(by_id[i] for i in affected_ids if i in by_id)
    return {"release_services": release_names, "affected_services": affected_names}
