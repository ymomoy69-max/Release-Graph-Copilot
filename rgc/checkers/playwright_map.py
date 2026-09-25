"""
Playwright Map checker.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from rgc.models import Finding, CheckResult, E2EScope

if TYPE_CHECKING:
    from rgc.manifest import Release
    from rgc.workspace import WorkspaceView


# Default paths (overridden by org_config)
_DEFAULT_README = "frontend/tests/README.md"
_DEFAULT_TIMINGS = "frontend/tests/timings.json"
FOLDER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def format_estimate(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs}s"


def _parse_readme(text: str) -> tuple[list[tuple[str, str]], str | None]:
    """Return (prefix_to_folder_list, fallback_folder_or_None)."""
    mappings: list[tuple[str, str]] = []
    fallback: str | None = None

    for line in text.splitlines():
        # prefix mapping
        m = re.fullmatch(r"- prefix: (.+) -> folder: ([A-Za-z0-9_-]+)", line)
        if m:
            prefix = m.group(1)
            folder = m.group(2)
            mappings.append((prefix, folder))
            continue
        # fallback
        m2 = re.fullmatch(r"- fallback folder: ([A-Za-z0-9_-]+)", line)
        if m2:
            fallback = m2.group(1)

    return mappings, fallback


def run(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    catalog: frozenset[str],
    org_config=None,
) -> CheckResult:
    readme_path = org_config.playwright_readme if org_config else _DEFAULT_README
    timings_path = org_config.playwright_timings if org_config else _DEFAULT_TIMINGS

    findings: list[Finding] = []
    changed_paths = release.changed_paths

    if not changed_paths:
        e2e = E2EScope(folders=(), estimate_seconds=0, estimate_display="0s")
        return CheckResult(
            id="playwright_map",
            name="Playwright Map",
            status="pass",
            summary="E2E scope: 0 folders",
            findings=(),
        ), e2e  # type: ignore[return-value]

    # Load README
    try:
        readme_text = workspace.read_text(readme_path)
    except FileNotFoundError:
        findings.append(Finding(
            severity="block",
            code="missing_playwright_map",
            message="Playwright map could not be read.",
            repos=(),
            suggested_fix="Restore the Playwright map README.",
            citation=None,
        ))
        e2e = E2EScope(folders=(), estimate_seconds=None, estimate_display="unknown")
        return CheckResult.from_findings("playwright_map", findings), e2e  # type: ignore[return-value]

    mappings, fallback = _parse_readme(readme_text)

    # Map each changed path
    folders: set[str] = set()
    has_unmapped = False

    for path in changed_paths:
        # Longest matching prefix
        best_prefix_len = -1
        best_folder: str | None = None
        for prefix, folder in mappings:
            if path == prefix or path.startswith(prefix):
                if len(prefix) > best_prefix_len:
                    best_prefix_len = len(prefix)
                    best_folder = folder
        if best_folder is not None:
            folders.add(best_folder)
        else:
            has_unmapped = True

    if has_unmapped:
        if fallback is None:
            findings.append(Finding(
                severity="block",
                code="missing_playwright_map",
                message="Playwright map could not be read.",
                repos=(),
                suggested_fix="Restore the Playwright map README.",
                citation=None,
            ))
            e2e = E2EScope(folders=(), estimate_seconds=None, estimate_display="unknown")
            return CheckResult.from_findings("playwright_map", findings), e2e  # type: ignore[return-value]
        folders.add(fallback)
        findings.append(Finding(
            severity="warning",
            code="unmapped_paths",
            message="Unmapped paths run the smoke folder.",
            repos=(),
            suggested_fix="Add a mapping prefix or accept the smoke folder.",
            citation=None,
        ))

    sorted_folders = tuple(sorted(folders))

    # Estimate
    e2e = _compute_estimate(workspace, sorted_folders, findings, timings_path)

    n_folders = len(sorted_folders)
    cr = CheckResult.from_findings("playwright_map", findings, n_folders=n_folders)
    return cr, e2e  # type: ignore[return-value]


def _compute_estimate(
    workspace: "WorkspaceView",
    folders: tuple[str, ...],
    findings: list[Finding],
    timings_path: str = _DEFAULT_TIMINGS,
) -> E2EScope:
    try:
        timings_text = workspace.read_text(timings_path)
    except FileNotFoundError:
        findings.append(Finding(
            severity="warning",
            code="missing_timings",
            message="E2E estimate is unknown.",
            repos=(),
            suggested_fix="Add integer seconds for each folder in timings.json.",
            citation=None,
        ))
        return E2EScope(folders=folders, estimate_seconds=None, estimate_display="unknown")

    try:
        timings = json.loads(timings_text)
    except json.JSONDecodeError:
        findings.append(Finding(
            severity="warning",
            code="malformed_timings",
            message="E2E estimate is unknown.",
            repos=(),
            suggested_fix="Add integer seconds for each folder in timings.json.",
            citation=None,
        ))
        return E2EScope(folders=folders, estimate_seconds=None, estimate_display="unknown")

    if not isinstance(timings, dict):
        findings.append(Finding(
            severity="warning",
            code="malformed_timings",
            message="E2E estimate is unknown.",
            repos=(),
            suggested_fix="Add integer seconds for each folder in timings.json.",
            citation=None,
        ))
        return E2EScope(folders=folders, estimate_seconds=None, estimate_display="unknown")

    total = 0
    for folder in folders:
        val = timings.get(folder)
        if not isinstance(val, int) or isinstance(val, bool):
            findings.append(Finding(
                severity="warning",
                code="missing_timings",
                message="E2E estimate is unknown.",
                repos=(),
                suggested_fix="Add integer seconds for each folder in timings.json.",
                citation=None,
            ))
            return E2EScope(folders=folders, estimate_seconds=None, estimate_display="unknown")
        total += val

    return E2EScope(
        folders=folders,
        estimate_seconds=total,
        estimate_display=format_estimate(total),
    )
