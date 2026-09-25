"""
Changeset Size checker.

Flags releases that touch more repos than the configured threshold.
A large deploy closure increases blast radius — this is a warning, not a block,
so the team can still approve after reviewing.

max_deploy_repos: 0 means unlimited (check always passes).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rgc.models import Finding, CheckResult

if TYPE_CHECKING:
    from rgc.manifest import Release
    from rgc.workspace import WorkspaceView
    from rgc.org_config import OrgConfig


def run(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    catalog: frozenset[str],
    org_config: "OrgConfig | None" = None,
) -> CheckResult:
    max_repos = org_config.max_deploy_repos if org_config else 0
    findings: list[Finding] = []

    count = len(closure)

    if max_repos > 0 and count > max_repos:
        repo_list = ", ".join(sorted(closure))
        findings.append(Finding(
            severity="warning",
            code="large_changeset",
            message=(
                f"This release touches {count} repos "
                f"(limit is {max_repos}): {repo_list}."
            ),
            repos=tuple(sorted(closure)),
            suggested_fix=(
                "Consider splitting this release into smaller batches to reduce "
                "blast radius. If this is intentional, approve after review."
            ),
            citation=None,
        ))

    return CheckResult.from_findings("changeset_size", findings)
