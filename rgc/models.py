"""
Data models for Release Graph Copilot.
All dataclasses are frozen (immutable).
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Check display names
# ---------------------------------------------------------------------------

CHECK_NAMES: dict[str, str] = {
    "pipeline_status": "Pipeline Status",
    "workflow_config": "Workflow-Config Diff",
    "fc_etl": "FC/ETL Path",
    "flyway": "Flyway Scan",
    "playwright_map": "Playwright Map",
}

# Fixed check order
CHECK_ORDER = ("pipeline_status", "workflow_config", "fc_etl", "flyway", "playwright_map")

# Pass summaries (used only when status is 'pass')
PASS_SUMMARIES: dict[str, str] = {
    "pipeline_status": "Pipelines: all green",
    "workflow_config": "Config diff: safe",
    "fc_etl": "FC/ETL: clear",
    "flyway": "Flyway: no unsafe migrations",
    # playwright_map uses a template; handled in checker
}

SEVERITY_RANK = {"block": 0, "warning": 1, "info": 2}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    file: str
    display: str
    section: str
    line: int  # 1-based
    quote: str

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "display": self.display,
            "section": self.section,
            "line": self.line,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class Finding:
    severity: str          # block | warning | info
    code: str
    message: str
    repos: tuple[str, ...]  # sorted ascending
    suggested_fix: str | None
    citation: Citation | None
    location: str | None = None   # "{path}:{line}" or just path
    snippet: str | None = None    # source context around the finding

    def to_dict(self) -> dict:
        d: dict = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "repos": list(self.repos),
            "suggested_fix": self.suggested_fix,
            "citation": self.citation.to_dict() if self.citation else None,
            "location": self.location,
            "snippet": self.snippet,
        }
        return d


def _check_status_from_findings(findings: tuple[Finding, ...]) -> str:
    """Derive check status from its findings."""
    for f in findings:
        if f.severity == "block":
            return "blocked"
    for f in findings:
        if f.severity == "warning":
            return "warning"
    return "pass"


def _sort_findings(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Sort findings by code ascending."""
    return tuple(sorted(findings, key=lambda f: f.code))


def _check_summary(check_id: str, status: str, findings: tuple[Finding, ...], n_folders: int = 0) -> str:
    """Return summary string for a check result."""
    if status == "pass":
        if check_id == "playwright_map":
            return f"E2E scope: {n_folders} folders"
        return PASS_SUMMARIES.get(check_id, "")
    # When not pass, summary is the message of the first finding after sorting
    # by severity rank then code
    if not findings:
        return ""
    sorted_f = sorted(findings, key=lambda f: (SEVERITY_RANK.get(f.severity, 99), f.code))
    return sorted_f[0].message


@dataclass(frozen=True)
class CheckResult:
    id: str
    name: str
    status: str   # pass | blocked | warning
    summary: str
    findings: tuple[Finding, ...]  # sorted by code ascending

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }

    @classmethod
    def from_findings(
        cls,
        check_id: str,
        raw_findings: list[Finding],
        n_folders: int = 0,
    ) -> "CheckResult":
        """Build a CheckResult from a list of findings."""
        findings = _sort_findings(tuple(raw_findings))
        status = _check_status_from_findings(findings)
        summary = _check_summary(check_id, status, findings, n_folders=n_folders)
        return cls(
            id=check_id,
            name=CHECK_NAMES[check_id],
            status=status,
            summary=summary,
            findings=findings,
        )


@dataclass(frozen=True)
class E2EScope:
    folders: tuple[str, ...]  # sorted ascending, unique
    estimate_seconds: int | None
    estimate_display: str      # e.g. "4m 20s" or "0s" or "unknown"

    def to_dict(self) -> dict:
        return {
            "folders": list(self.folders),
            "estimate_seconds": self.estimate_seconds,
            "estimate_display": self.estimate_display,
        }


def _derive_verdict_risk_gate(checks: tuple[CheckResult, ...]) -> tuple[str, str, str, str | None]:
    """Return (verdict, risk, gate, gate_prompt)."""
    statuses = {c.status for c in checks}
    if "blocked" in statuses:
        return "no_go", "HIGH", "blocked", None
    if "warning" in statuses:
        prompt = "Ready to trigger E2E. Risk: MEDIUM. Approve?"
        return "go", "MEDIUM", "pending_approval", prompt
    prompt = "Ready to trigger E2E. Risk: LOW. Approve?"
    return "go", "LOW", "pending_approval", prompt


@dataclass(frozen=True)
class Checklist:
    release_id: str
    question: str
    verdict: str       # go | no_go
    risk: str          # LOW | MEDIUM | HIGH
    gate: str          # pending_approval | approved | cancelled | blocked
    gate_prompt: str | None
    block_report: str | None
    deploy_order: tuple[str, ...]
    checks: tuple[CheckResult, ...]  # always 5, fixed order
    e2e: E2EScope
    suggested_fixes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "question": self.question,
            "verdict": self.verdict,
            "risk": self.risk,
            "gate": self.gate,
            "gate_prompt": self.gate_prompt,
            "block_report": self.block_report,
            "deploy_order": list(self.deploy_order),
            "checks": [c.to_dict() for c in self.checks],
            "e2e": self.e2e.to_dict(),
            "suggested_fixes": list(self.suggested_fixes),
        }

    @classmethod
    def build(
        cls,
        release_id: str,
        question: str,
        checks: tuple[CheckResult, ...],
        deploy_order: tuple[str, ...],
        e2e: E2EScope,
        block_report: str | None = None,
    ) -> "Checklist":
        verdict, risk, gate, gate_prompt = _derive_verdict_risk_gate(checks)

        # Collect suggested_fixes: non-null, in check order, skip duplicates
        seen: set[str] = set()
        suggested_fixes: list[str] = []
        for check in checks:
            for finding in check.findings:
                if finding.suggested_fix and finding.suggested_fix not in seen:
                    seen.add(finding.suggested_fix)
                    suggested_fixes.append(finding.suggested_fix)

        return cls(
            release_id=release_id,
            question=question,
            verdict=verdict,
            risk=risk,
            gate=gate,
            gate_prompt=gate_prompt,
            block_report=block_report,
            deploy_order=deploy_order,
            checks=checks,
            e2e=e2e,
            suggested_fixes=tuple(suggested_fixes),
        )


def format_checklist_json(checklist: "Checklist") -> str:
    """Return the checklist as a JSON string with trailing newline."""
    import json
    return json.dumps(checklist.to_dict(), indent=2) + "\n"
