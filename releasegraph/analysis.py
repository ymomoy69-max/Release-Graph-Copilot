"""Turn scan/readiness/incident evidence into file-level error analysis."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.ai_layer import enrich_issues, llm_enabled
from releasegraph.models import Incident, IncidentStatus, Project, Service, ServiceDependency
from releasegraph.proposals import serialize_proposal, upsert_from_issues
from releasegraph.risk_engine import blast_radius
from releasegraph.safety import apply_safety_gate
from releasegraph.workspace_scan import scan_workspace

ISSUE_COPY: dict[str, dict[str, str]] = {
    "hardcoded_secret": {
        "problem": "A secret appears hardcoded in source instead of coming from the environment.",
        "consequences": "Anyone with repo access can impersonate this service. Rotate the credential after moving it to env/config.",
        "fix": "Load the value from an environment variable or a secret manager. Remove the literal from git history if it was real.",
    },
    "swallowed_exception": {
        "problem": "An exception is caught and ignored (pass/continue), so failures never surface.",
        "consequences": "Outages look like success. Callers keep going with partial state (for example inventory reserved but payment failed).",
        "fix": "Log the error with context and re-raise or return an explicit failure to the caller.",
    },
    "http_no_timeout": {
        "problem": "An outbound HTTP client is created without a timeout.",
        "consequences": "If a dependency hangs, this service’s threads/workers block and the blast radius grows into every caller.",
        "fix": "Set an explicit timeout (connect + read). Fail fast and let the caller retry or degrade.",
    },
    "sql_fstring": {
        "problem": "SQL is built with an f-string, which is a SQL-injection risk.",
        "consequences": "Untrusted input can read or change data in this service’s database.",
        "fix": "Use bound parameters (SQLAlchemy text(':id') / psycopg placeholders), never string interpolation.",
    },
}


def _graph_pairs(db: Session, project_id: int) -> tuple[dict[int, str], list[tuple[int, int]]]:
    svcs = db.scalars(select(Service).where(Service.project_id == project_id)).all()
    by_id = {s.id: s.name for s in svcs}
    deps = db.scalars(
        select(ServiceDependency).where(ServiceDependency.project_id == project_id)
    ).all()
    pairs = [(d.from_service_id, d.to_service_id) for d in deps]
    return by_id, pairs


def _affects(db: Session, project_id: int, service_name: str | None) -> list[str]:
    if not service_name:
        return []
    svcs = db.scalars(select(Service).where(Service.project_id == project_id)).all()
    by_name = {s.name: s.id for s in svcs}
    sid = by_name.get(service_name)
    if sid is None:
        return [service_name]
    by_id, pairs = _graph_pairs(db, project_id)
    ids = blast_radius({sid}, pairs)
    names = [by_id[i] for i in ids if i in by_id]
    return names or [service_name]


def _from_scan_issue(db: Session, project_id: int, raw: dict[str, Any]) -> dict[str, Any]:
    code = raw.get("code") or "scan"
    copy = ISSUE_COPY.get(code, {})
    service = raw.get("service")
    affects = _affects(db, project_id, service)
    problem = copy.get("problem") or raw.get("snippet") or code
    return {
        "file": raw.get("file") or "unknown",
        "line": raw.get("line"),
        "service": service,
        "severity": "high" if code in {"hardcoded_secret", "sql_fstring"} else "medium",
        "problem": problem,
        "affects": affects,
        "consequences": copy.get("consequences")
        or (
            f"Callers of {service or 'this service'} may fail: {', '.join(affects) or 'unknown'}."
        ),
        "fix": copy.get("fix") or "Inspect the snippet and add explicit error handling.",
        "evidence": raw.get("snippet"),
        "source": "workspace_scan",
        "code": code,
    }


def _from_rgc_finding(db: Session, project_id: int, finding: dict[str, Any], check_name: str) -> dict[str, Any]:
    repos = finding.get("repos") or []
    service = repos[0] if repos else None
    loc = finding.get("location") or ""
    file_path = loc.split(":")[0] if loc else (service or "workspace")
    line = None
    if loc and ":" in loc:
        tail = loc.rsplit(":", 1)[-1]
        if tail.isdigit():
            line = int(tail)
    severity = "high" if finding.get("severity") == "block" else finding.get("severity") or "warning"
    affects = []
    for r in repos:
        affects.extend(_affects(db, project_id, r))
    # unique preserve order
    seen: set[str] = set()
    uniq = []
    for a in affects:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    msg = finding.get("message") or check_name
    return {
        "file": file_path,
        "line": line,
        "service": service,
        "severity": "high" if severity in {"block", "high"} else "medium",
        "problem": msg,
        "affects": uniq or list(repos),
        "consequences": (
            f"{check_name} is {finding.get('severity', 'warning')}. "
            f"If you ship anyway, these services can fail: {', '.join(uniq or repos or ['unknown'])}."
        ),
        "fix": finding.get("suggested_fix") or "See the checker finding and apply the suggested change.",
        "evidence": finding.get("snippet"),
        "source": "rgc",
        "code": finding.get("code") or check_name,
    }


def _from_incident(db: Session, project_id: int, incident_id: int) -> dict[str, Any] | None:
    inc = db.get(Incident, incident_id)
    if not inc or inc.project_id != project_id:
        return None
    svc = db.get(Service, inc.service_id) if inc.service_id else None
    name = svc.name if svc else None
    affects = _affects(db, project_id, name)
    return {
        "file": (svc.source_path if svc and getattr(svc, "source_path", None) else None) or "runtime",
        "line": None,
        "service": name,
        "severity": inc.severity or "high",
        "problem": inc.title,
        "affects": affects,
        "consequences": (
            f"This incident is {inc.status.value}. "
            f"Downstream impact: {', '.join(affects) or 'not mapped yet — scan the workspace to build the graph'}."
        ),
        "fix": (
            "Open the related release and confirm rollback if the last deploy caused it. "
            "Use Copilot to pull the stored timeline — it will not invent a cause."
        ),
        "evidence": inc.title,
        "source": "incident",
        "code": f"incident-{incident_id}",
    }


def analyze_project(
    db: Session,
    project_id: int,
    *,
    workspace: str | None = None,
    checklist: dict[str, Any] | None = None,
    incident_id: int | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    root = workspace or (project.workspace_path if project else None) or ""
    issues: list[dict[str, Any]] = []

    scan = None
    if root:
        scan = scan_workspace(root)
        for raw in scan.get("issues") or []:
            issues.append(_from_scan_issue(db, project_id, raw))

    if checklist:
        for check in checklist.get("checks") or []:
            for finding in check.get("findings") or []:
                if not isinstance(finding, dict):
                    continue
                if finding.get("severity") in {"block", "warning"}:
                    issues.append(_from_rgc_finding(db, project_id, finding, check.get("name") or check.get("id") or "check"))

    if incident_id:
        row = _from_incident(db, project_id, incident_id)
        if row:
            issues.append(row)
    else:
        open_incs = db.scalars(
            select(Incident).where(
                Incident.project_id == project_id,
                Incident.status != IncidentStatus.RESOLVED,
            )
        ).all()
        for inc in open_incs:
            row = _from_incident(db, project_id, inc.id)
            if row:
                issues.append(row)

    engine_issues = list(issues)
    llm_issues = None
    groq_on = bool(use_llm and llm_enabled() and engine_issues)
    if groq_on:
        llm_issues = enrich_issues(engine_issues, project_name=project.name if project else None)
        if llm_issues is engine_issues:
            llm_issues = None

    issues, safety = apply_safety_gate(engine_issues, llm_issues)
    safety["llm_enabled"] = llm_enabled()
    safety["llm_attempted"] = groq_on

    created = []
    if project:
        created = upsert_from_issues(db, project.id, project.organization_id, issues)

    high = sum(1 for i in issues if i.get("severity") in {"high", "block", "critical"})
    return {
        "project_id": project_id,
        "workspace": root or None,
        "issue_count": len(issues),
        "high_count": high,
        "services": [s.name for s in db.scalars(select(Service).where(Service.project_id == project_id)).all()],
        "issues": issues,
        "safety": safety,
        "proposals_created": len(created),
        "proposals": [serialize_proposal(db, p) for p in created],
        "scan": (
            {
                "services": scan.get("services"),
                "dependencies": scan.get("dependencies"),
                "repo_folders": scan.get("repo_folders"),
            }
            if scan
            else None
        ),
    }
