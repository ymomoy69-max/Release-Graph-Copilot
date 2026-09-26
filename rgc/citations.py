"""
Citation engine: attaches runbook citations to findings after checkers run.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from rgc.models import Citation, Finding, CheckResult

if TYPE_CHECKING:
    from rgc.org_config import OrgConfig
    from rgc.workspace import WorkspaceView

CITATIONS_PATH = "fixtures/rules/citations.yaml"


def _load_rules(path: str = CITATIONS_PATH) -> list[dict]:
    """Load citation rules from YAML."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data.get("rules", [])
    except (OSError, yaml.YAMLError):
        return []


def _search_citation(
    workspace: "WorkspaceView",
    rule: dict,
    workspace_root: str = "fixtures/workspace",
) -> Citation | None:
    """
    Search for the citation in the workspace file.
    Returns Citation on success, None on failure.
    """
    file_path = rule["file"]
    section = str(rule["section"])
    quote = rule["quote"]

    # Strip leading workspace_root prefix for display
    display = file_path
    prefix = workspace_root.rstrip("/") + "/"
    if display.startswith(prefix):
        display = display[len(prefix):]
    # Also strip legacy fixtures/workspace/ prefix
    if display.startswith("fixtures/workspace/"):
        display = display[len("fixtures/workspace/"):]

    # Read the file through the workspace (overlays win)
    try:
        text = workspace.read_text(display)
    except FileNotFoundError:
        return None

    lines = text.splitlines()

    # Find section heading: line matching ^(#{1,6})\s+<section>(\s|$)
    section_pattern = re.compile(
        r"^#{1,6}\s+" + re.escape(section) + r"(\s|$)"
    )
    heading_line: int | None = None
    for i, line in enumerate(lines, start=1):
        if section_pattern.match(line):
            heading_line = i
            break

    if heading_line is None:
        return None

    # Find quote: full line after stripping trailing spaces, line number > heading_line
    for i, line in enumerate(lines, start=1):
        if i <= heading_line:
            continue
        if line.rstrip() == quote:
            return Citation(
                file=file_path,
                display=display,
                section=section,
                line=i,
                quote=quote,
            )

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


def _build_block_report(finding: Finding, affected_ordered: tuple[str, ...]) -> str:
    """Build the block_report for flag_flip_without_rehydrate."""
    assert finding.citation is not None
    cit = finding.citation
    affected_line = ", ".join(affected_ordered)
    return (
        f"BLOCKED — Unsafe flag flip detected\n"
        f"\n"
        f"Reason: {cit.display} §{cit.section} states:\n"
        f'  "{cit.quote}"\n'
        f"\n"
        f"Current pipeline: {finding.message}\n"
        f"Affected: {affected_line}\n"
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
    if org_config is None:
        from rgc.manifest import DEFAULT_ORG_CONFIG
        from rgc.org_config import OrgConfig, load_org_config

        loaded = load_org_config(DEFAULT_ORG_CONFIG)
        if isinstance(loaded, OrgConfig):
            org_config = loaded

    if rules is None:
        if org_config is not None:
            rules = _load_rules(org_config.citations)
        else:
            rules = _load_rules()

    workspace_root = org_config.workspace_root if org_config else "fixtures/workspace"
    affected_ordered = org_config.affected_repos_ordered if org_config else ()

    # Build code → rule map
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
                # Citation not found: keep finding with null citation, add extra finding
                updated_findings.append(finding)
                extra_findings.append(_citation_not_found_finding())
            else:
                # Attach citation; use rule's suggested_fix only if finding's is null
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

                # Build block_report for flag_flip_without_rehydrate
                if finding.code == "flag_flip_without_rehydrate":
                    block_report = _build_block_report(new_finding, affected_ordered)

        # Rebuild check with updated findings (sorted by code)
        all_findings = tuple(sorted(
            updated_findings + extra_findings,
            key=lambda f: f.code,
        ))

        new_status = _status_from_findings(all_findings)

        if new_status == check.status and not extra_findings:
            # Nothing changed — preserve original summary
            new_summary = check.summary
        else:
            new_summary = _summary_for_check(check.id, all_findings, original_summary=check.summary)

        new_check = CheckResult(
            id=check.id,
            name=check.name,
            status=new_status,
            summary=new_summary,
            findings=all_findings,
        )
        updated_checks.append(new_check)

    return updated_checks, block_report


def _status_from_findings(findings: tuple[Finding, ...]) -> str:
    for f in findings:
        if f.severity == "block":
            return "blocked"
    for f in findings:
        if f.severity == "warning":
            return "warning"
    return "pass"


def _summary_for_check(
    check_id: str,
    findings: tuple[Finding, ...],
    original_summary: str = "",
) -> str:
    from rgc.models import PASS_SUMMARIES, SEVERITY_RANK
    status = _status_from_findings(findings)
    if status == "pass":
        if check_id == "playwright_map":
            return original_summary
        return PASS_SUMMARIES.get(check_id, "")
    if not findings:
        return original_summary
    sorted_f = sorted(findings, key=lambda f: (SEVERITY_RANK.get(f.severity, 99), f.code))
    return sorted_f[0].message
