"""Open or close incidents from real workspace scan findings — no fabricated outages."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Incident, IncidentEvent, IncidentStatus, Service, User


SCAN_PREFIX = "Code scan:"


def _issue_key(raw: dict[str, Any]) -> tuple[str, str, str] | None:
    svc = str(raw.get("service") or "").strip()
    code = str(raw.get("code") or "").strip()
    file = str(raw.get("file") or "").strip()
    if not svc or not code or not file:
        return None
    return svc, code, file


def sync_incidents_from_scan(
    db: Session,
    project_id: int,
    scan: dict[str, Any],
    *,
    actor: User | None = None,
) -> dict[str, int]:
    """Create incidents for scanner issues on disk; resolve when the finding disappears."""
    issues = list(scan.get("issues") or [])
    services = {
        s.name: s
        for s in db.scalars(select(Service).where(Service.project_id == project_id)).all()
    }
    active_keys: set[tuple[str, str, str]] = set()
    created = 0
    updated = 0

    for raw in issues:
        key = _issue_key(raw)
        if not key:
            continue
        svc_name, code, file = key
        svc = services.get(svc_name)
        if not svc:
            continue
        active_keys.add(key)
        title = f"{SCAN_PREFIX} {code} in {file}"
        inc = db.scalar(
            select(Incident).where(
                Incident.project_id == project_id,
                Incident.title == title,
                Incident.status != IncidentStatus.RESOLVED,
            )
        )
        if inc:
            continue
        inc = Incident(
            project_id=project_id,
            title=title,
            status=IncidentStatus.OPEN,
            severity="high" if code in {"hardcoded_secret", "sql_fstring"} else "medium",
            service_id=svc.id,
        )
        db.add(inc)
        db.flush()
        db.add(
            IncidentEvent(
                incident_id=inc.id,
                event_type="scan_finding",
                message=(raw.get("snippet") or f"{code} at {file}:{raw.get('line') or '?'}").strip()[:500],
                actor=actor.email if actor else "workspace-scanner",
            )
        )
        created += 1

    open_scan = db.scalars(
        select(Incident).where(
            Incident.project_id == project_id,
            Incident.title.startswith(SCAN_PREFIX),
            Incident.status != IncidentStatus.RESOLVED,
        )
    ).all()
    for inc in open_scan:
        svc = db.get(Service, inc.service_id) if inc.service_id else None
        if not svc:
            continue
        # title: Code scan: {code} in {file}
        rest = inc.title[len(SCAN_PREFIX) :].strip()
        if " in " not in rest:
            continue
        code, file = rest.split(" in ", 1)
        key = (svc.name, code.strip(), file.strip())
        if key not in active_keys:
            inc.status = IncidentStatus.RESOLVED
            db.add(
                IncidentEvent(
                    incident_id=inc.id,
                    event_type="scan_cleared",
                    message="Workspace scan no longer reports this finding.",
                    actor=actor.email if actor else "workspace-scanner",
                )
            )
            updated += 1

    return {"created": created, "resolved": updated, "active_findings": len(active_keys)}
