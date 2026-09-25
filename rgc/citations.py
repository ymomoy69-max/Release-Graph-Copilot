"""
Citation engine — attaches runbook citations to findings after checkers run.

Any finding code can have a citation rule in citations.yaml:

  rules:
    - code: unsafe_migration
      file: docs/runbooks/migrations.md
      section: "2.1"
      quote: never drop a column while the old code is still deployed
      suggested_fix: Use expand-and-contract pattern instead.

When a finding's code matches a rule, the engine searches the runbook for the
quoted text under the specified section heading. If found, the citation is
attached to the finding and a block_report is generated.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from rgc.models import Citation, Finding, CheckResult

if TYPE_CHECKING:
    from rgc.workspace import WorkspaceView
    from rgc.org_config import OrgConfig


def _load_rules(path: str) -> list[dict]:
    """Load citation rules from YAML."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data.get("rules", []) if isinstance(data, dict) else []
    except (OSError, yaml.YAMLError):
        return []


def _search_citation(
    workspace: "WorkspaceView",
    rule: dict,
    workspace_root: str,
) -> Citation | None:
    """Search the runbook file for the quoted text under the section heading."""
    file_path = rule["file"]
    section = str(rule["section"])
    quote = rule["quote"]

    # Strip leading workspace_root prefix for display path
    display = file_path
    prefix = workspace_root.rstrip("/") + "/"
    if display.startswith(prefix):
        display = display[len(prefix):]

    try:
        text = workspace.read_text(display)
    except FileNotFoundError:
        return None

    lines = text.splitlines()

    section_re = re.compile(r"^#{1,6}\s+" + re.escape(section) + r"(\s|$)")
    heading_line: int | None = None
    for i, line in enumerate(lines, start=1):
        if section_re.match(line):
            heading_line = i
            break

    if heading_line is None:
        return None

    for i, line in enumerate(lines, start=1):
        if i <= heading_line:
            continue
        if line.rstrip() == quote:
            return Citation(file=file_path, display=display, section=section, line=i, quote=quote)

    return None


def _citation_not_found_finding() -> Finding:
    return Finding(
        severity="block",
        code="citation_not_found",
        message="Cited runbook text was not found. No quotation invented.",
        repos=(),
        suggested_fix="Restore the runbook section and re-run the check.",
        citation=None,
    )


def _build_block_report(finding: Finding) -> str:
    """Build a generic block_report for any finding with a citation."""
    assert finding.citation is not None
    cit = finding.citation
    repos_line = (", ".join(finding.repos)) if finding.repos else "multiple repos"
    return (
        f"BLOCKED — {finding.message}\n"
        f"\n"
        f"Runbook: {cit.display} §{cit.section} line {cit.line} states:\n"
        f'  "{cit.quote}"\n'
        f"\n"
        f"Affected: {repos_line}\n"
        f"\n"
        f"Suggested fix: {finding.suggested_fix}\n"
        f"\n"
    )


def attach_citations(
    checks: list[CheckResult],
    workspace: "WorkspaceView",
    rules: list[dict] | None = None,
    org_config: "OrgConfig | None" = None,
) -> tuple[list[CheckResult], str | None]:
    """
    Walk findings, attach citations, build block_report.
    Returns (updated_checks, block_report_or_None).
    """
    workspace_root = org_config.workspace_root if org_config else "fixtures/workspace"

    # Load citation rules
    if rules is None:
        if org_config is not None and org_config.citations:
            rules = _load_rules(org_config.citations)
        else:
            rules = []

    rule_map: dict[str, dict] = {r["code"]: r for r in rules}
    block_report: str | None = None
    updated_checks: list[CheckResult] = []

    for check in checks:
        updated_findings: list[Finding] = []
        extra_findings: list[Finding] = []

        for finding in check.findings:
            if finding.code not in rule_map:
                updated_findings.append(finding)
                continue

            rule = rule_map[finding.code]
            citation = _search_citation(workspace, rule, workspace_root=workspace_root)

            if citation is None:
                updated_findings.append(finding)
                extra_findings.append(_citation_not_found_finding())
            else:
                suggested_fix = finding.suggested_fix or rule.get("suggested_fix")
                new_finding = Finding(
                    severity=finding.severity,
                    code=finding.code,
                    message=finding.message,
                    repos=finding.repos,
                    suggested_fix=suggested_fix,
                    citation=citation,
                    location=finding.location,
                    snippet=finding.snippet,
                )
                updated_findings.append(new_finding)
                # First blocking cited finding becomes the block_report
                if block_report is None and finding.severity == "block":
                    block_report = _build_block_report(new_finding)

        all_findings = tuple(sorted(
            updated_findings + extra_findings,
            key=lambda f: f.code,
        ))
        new_status = _status_from_findings(all_findings)
        if new_status == check.status and not extra_findings:
            new_summary = check.summary
        else:
            new_summary = _summary_for_check(check.id, all_findings, check.summary)

        updated_checks.append(CheckResult(
            id=check.id,
            name=check.name,
            status=new_status,
            summary=new_summary,
            findings=all_findings,
        ))

    return updated_checks, block_report


def _status_from_findings(findings: tuple[Finding, ...]) -> str:
    for f in findings:
        if f.severity == "block":
            return "blocked"
    for f in findings:
        if f.severity == "warning":
            return "warning"
    return "pass"


def _summary_for_check(check_id: str, findings: tuple[Finding, ...], original_summary: str) -> str:
    from rgc.models import PASS_SUMMARIES, SEVERITY_RANK
    status = _status_from_findings(findings)
    if status == "pass":
        return PASS_SUMMARIES.get(check_id, original_summary)
    if not findings:
        return original_summary
    sorted_f = sorted(findings, key=lambda f: (SEVERITY_RANK.get(f.severity, 99), f.code))
    return sorted_f[0].message
