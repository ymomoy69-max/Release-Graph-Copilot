"""Discover which service a live checkout exercise should target."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Service, ServiceDependency


def checkout_target_service(db: Session, project_id: int) -> Service | None:
    """Pick the dependency most other services call (typical payment/auth bottleneck)."""
    services = db.scalars(
        select(Service).where(Service.project_id == project_id).order_by(Service.name)
    ).all()
    if not services:
        return None
    inbound: dict[int, int] = {}
    for dep in db.scalars(
        select(ServiceDependency).where(ServiceDependency.project_id == project_id)
    ).all():
        inbound[dep.to_service_id] = inbound.get(dep.to_service_id, 0) + 1
    ranked = sorted(
        services,
        key=lambda s: (
            -inbound.get(s.id, 0),
            0 if s.criticality == "high" else 1,
            s.name,
        ),
    )
    return ranked[0]
