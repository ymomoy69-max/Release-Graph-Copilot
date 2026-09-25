"""
Secret Scan checker.

Scans the content of every overlay for patterns that look like secrets:
API keys, tokens, passwords, private keys, connection strings.

Uses conservative regex patterns to minimise false positives. Any match
blocks the deploy — secrets must never be committed to source files.

This checker is technology-agnostic: it looks at raw text content, not
at file types or framework conventions.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rgc.models import Finding, CheckResult

if TYPE_CHECKING:
    from rgc.manifest import Release
    from rgc.workspace import WorkspaceView
    from rgc.org_config import OrgConfig


# ---------------------------------------------------------------------------
# Secret patterns
# Each entry is (label, compiled_regex).
# Patterns are conservative: they require a key=value or assignment context
# and a minimum entropy-suggesting length.
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Generic API key assignment: api_key = "abc123..." (20+ alphanum chars)
    ("API key",
     re.compile(
         r"""(?i)(?:api[_\-]?key|apikey)\s*[:=]\s*['"]?([A-Za-z0-9+/=_\-]{20,})['"]?""",
         re.MULTILINE,
     )),
    # Generic secret / token / password assignment
    ("Secret or token",
     re.compile(
         r"""(?i)(?:secret|token|password|passwd|pwd)\s*[:=]\s*['"]([^'"]{8,})['"]""",
         re.MULTILINE,
     )),
    # Private key header
    ("Private key",
     re.compile(
         r"""-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----""",
         re.MULTILINE,
     )),
    # AWS access key id
    ("AWS access key",
     re.compile(
         r"""(?<![A-Z0-9])(AKIA[0-9A-Z]{16})(?![A-Z0-9])""",
         re.MULTILINE,
     )),
    # Generic connection string with password
    ("Connection string with password",
     re.compile(
         r"""(?i)(?:postgres|mysql|mongodb|redis|amqp|jdbc)[a-z+]*://[^:@\s]+:[^@\s]{4,}@""",
         re.MULTILINE,
     )),
    # GitHub / GitLab personal access token
    ("GitHub/GitLab token",
     re.compile(
         r"""(?:ghp|gho|ghu|ghs|ghr|glpat)_[A-Za-z0-9]{20,}""",
         re.MULTILINE,
     )),
]


def _find_secret(content: str) -> tuple[str, int] | None:
    """Return (label, 1-based line number) of the first secret found, or None."""
    lines = content.splitlines()
    for label, pattern in _PATTERNS:
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                return label, i
    return None


def run(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    catalog: frozenset[str],
    org_config: "OrgConfig | None" = None,
) -> CheckResult:
    findings: list[Finding] = []

    for overlay in release.overlays:
        if not overlay.content:
            continue
        result = _find_secret(overlay.content)
        if result is not None:
            label, line_num = result
            findings.append(Finding(
                severity="block",
                code="secret_detected",
                message=f"{label} pattern detected in {overlay.path}.",
                repos=(),
                suggested_fix=(
                    "Remove the secret from the file. Use environment variables or a "
                    "secrets manager instead of committing credentials to source files."
                ),
                citation=None,
                location=f"{overlay.path}:{line_num}",
                # Do NOT include the snippet — never echo potential secret content
                snippet=None,
            ))

    return CheckResult.from_findings("secret_scan", findings)
