"""Deploy gate from live workspace scan — no canned blockers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Incident, IncidentStatus, Project, Service
from releasegraph.release_train import _BLOCKING_CODES
from releasegraph.workspace_incidents import SCAN_PREFIX
from releasegraph.workspace_scan import scan_workspace


def _incident_for_finding(
    db: Session,
    project_id: int,
    *,
    title: str,
) -> int | None:
    inc = db.scalar(
        select(Incident).where(
            Incident.project_id == project_id,
            Incident.title == title,
            Incident.status != IncidentStatus.RESOLVED,
        )
    )
    return inc.id if inc else None


def deploy_gate_details(db: Session, project: Project) -> dict[str, Any]:
    """Blocking scanner findings on disk and links to open incidents."""
    path = (project.workspace_path or "").strip()
    if not path:
        return {
            "blocked": False,
            "message": None,
            "blocking_count": 0,
            "issue_count": 0,
            "findings": [],
        }
    try:
        scan = scan_workspace(path)
    except OSError as exc:
        return {
            "blocked": False,
            "message": f"Could not scan workspace: {exc}",
            "blocking_count": 0,
            "issue_count": 0,
            "findings": [],
        }

    issues = list(scan.get("issues") or [])
    findings: list[dict[str, Any]] = []
    blocking_count = 0
    for raw in issues:
        code = str(raw.get("code") or "").strip()
        file = str(raw.get("file") or "").strip()
        svc_name = str(raw.get("service") or "").strip()
        if not code or not file:
            continue
        is_blocking = code in _BLOCKING_CODES
        if is_blocking:
            blocking_count += 1
        title = f"{SCAN_PREFIX} {code} in {file}"
        findings.append(
            {
                "code": code,
                "file": file,
                "line": raw.get("line"),
                "service": svc_name,
                "blocking": is_blocking,
                "incident_id": _incident_for_finding(db, project.id, title=title),
            }
        )

    blocked = blocking_count > 0
    message = None
    if blocked:
        codes = ", ".join(sorted({f["code"] for f in findings if f["blocking"]}))
        message = f"Deploy blocked: {blocking_count} critical scanner finding(s) on disk ({codes})."
    return {
        "blocked": blocked,
        "message": message,
        "blocking_count": blocking_count,
        "issue_count": len(issues),
        "findings": findings,
    }


def open_scan_incidents_by_service(db: Session, project_id: int) -> dict[str, list[dict[str, Any]]]:
    """Map service name → open code-scan incidents (for graph deep links)."""
    rows = db.scalars(
        select(Incident).where(
            Incident.project_id == project_id,
            Incident.title.startswith(SCAN_PREFIX),
            Incident.status != IncidentStatus.RESOLVED,
        )
    ).all()
    out: dict[str, list[dict[str, Any]]] = {}
    for inc in rows:
        svc = db.get(Service, inc.service_id) if inc.service_id else None
        name = svc.name if svc else "unknown"
        rest = inc.title[len(SCAN_PREFIX) :].strip()
        code, file = ("", rest)
        if " in " in rest:
            code, file = rest.split(" in ", 1)
        out.setdefault(name, []).append(
            {
                "incident_id": inc.id,
                "title": inc.title,
                "code": code.strip(),
                "file": file.strip(),
            }
        )
    return out
