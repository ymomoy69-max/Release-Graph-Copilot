"""Recent audit rows for a project."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import AuditEvent, FixProposal, Incident, Release, User


def recent_project_audit(db: Session, organization_id: int, project_id: int, limit: int = 5) -> list[dict]:
    release_ids = {
        r.id for r in db.scalars(select(Release).where(Release.project_id == project_id)).all()
    }
    incident_ids = {
        i.id for i in db.scalars(select(Incident).where(Incident.project_id == project_id)).all()
    }
    fix_ids = {
        f.id for f in db.scalars(select(FixProposal).where(FixProposal.project_id == project_id)).all()
    }
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.organization_id == organization_id)
        .order_by(AuditEvent.timestamp.desc())
        .limit(80)
    ).all()
    out: list[dict] = []
    for e in rows:
        keep = False
        if e.entity_type == "project" and str(e.entity_id) == str(project_id):
            keep = True
        elif e.entity_type == "release":
            try:
                keep = int(e.entity_id) in release_ids
            except (TypeError, ValueError):
                keep = False
        elif e.entity_type == "incident":
            try:
                keep = int(e.entity_id) in incident_ids
            except (TypeError, ValueError):
                keep = False
        elif e.entity_type == "fix_proposal":
            try:
                keep = int(e.entity_id) in fix_ids
            except (TypeError, ValueError):
                keep = False
        if not keep:
            continue
        user = db.get(User, e.user_id) if e.user_id else None
        out.append(
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else "",
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "ai_generated": e.ai_generated,
                "user_email": user.email if user else None,
            }
        )
        if len(out) >= limit:
            break
    return out
