"""
Protected Config Change checker.

Any overlay whose path matches a pattern in org_config.protected_paths produces
a WARNING — the change is allowed but needs a human review before deploy.

Protected paths are glob patterns defined in the org YAML, e.g.:
  - "config/**"
  - "*.env"
  - "**/.env*"
  - "secrets/**"
  - "infrastructure/**"

No assumptions about what the files contain — just flags that a sensitive path
is being changed so a reviewer can inspect it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rgc.models import Finding, CheckResult
from rgc.org_config import path_matches_protected

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
    protected = org_config.protected_paths if org_config else ()
    findings: list[Finding] = []

    if not protected:
        return CheckResult.from_findings("config_change", findings)

    for overlay in release.overlays:
        if path_matches_protected(overlay.path, protected):
            # Show first line of the changed content as a snippet
            first_line = overlay.content.splitlines()[0] if overlay.content else None
            findings.append(Finding(
                severity="warning",
                code="protected_path_changed",
                message=f"Protected file changed: {overlay.path}.",
                repos=(),
                suggested_fix=(
                    "Review the change to this protected file before approving the deploy. "
                    "Ensure it is intentional and has been through your change-approval process."
                ),
                citation=None,
                location=f"{overlay.path}:1",
                snippet=first_line,
            ))

    return CheckResult.from_findings("config_change", findings)
