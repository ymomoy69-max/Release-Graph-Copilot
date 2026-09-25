"""
Flyway Scan checker.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rgc.models import Finding, CheckResult

if TYPE_CHECKING:
    from rgc.manifest import Release
    from rgc.workspace import WorkspaceView


# Regex patterns for versioned and repeatable migration filenames
_VERSIONED_RE = re.compile(r"^V(\d+)__.*\.sql$", re.IGNORECASE)
_REPEATABLE_RE = re.compile(r"^R__.*\.sql$", re.IGNORECASE)

# Destructive SQL patterns (applied on stripped text)
_DROP_TABLE = re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)
_DROP_COLUMN = re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)
_TRUNCATE = re.compile(r"\bTRUNCATE\b", re.IGNORECASE)
_DELETE = re.compile(r"\bDELETE\b", re.IGNORECASE)
_WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)


def _strip_comments_and_strings(sql: str) -> str:
    """Strip single-quoted strings, line comments, and block comments."""
    result = []
    i = 0
    n = len(sql)
    in_string = False

    while i < n:
        ch = sql[i]

        if in_string:
            if ch == "'" :
                # Check for escaped quote ''
                if i + 1 < n and sql[i + 1] == "'":
                    result.append("  ")
                    i += 2
                else:
                    result.append(" ")
                    i += 1
                    in_string = False
            else:
                result.append(" ")
                i += 1
        else:
            if ch == "'":
                result.append(" ")
                i += 1
                in_string = True
            elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
                # Line comment: replace through newline
                j = i
                while j < n and sql[j] != "\n":
                    j += 1
                result.append(" " * (j - i))
                i = j
            elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
                # Block comment: replace through */
                j = i + 2
                while j < n - 1 and not (sql[j] == "*" and sql[j + 1] == "/"):
                    j += 1
                if j < n - 1:
                    j += 2  # consume */
                else:
                    j = n  # unclosed block comment runs to end of file
                result.append(" " * (j - i))
                i = j
            else:
                result.append(ch)
                i += 1

    return "".join(result)


def _is_destructive(stripped_sql: str) -> bool:
    """Return True if the stripped SQL contains a destructive statement."""
    if _DROP_TABLE.search(stripped_sql):
        return True
    if _DROP_COLUMN.search(stripped_sql):
        return True
    if _TRUNCATE.search(stripped_sql):
        return True
    # DELETE without WHERE: find each DELETE, scan to next semicolon or end
    for m in _DELETE.finditer(stripped_sql):
        start = m.start()
        semi = stripped_sql.find(";", start)
        if semi == -1:
            stmt = stripped_sql[start:]
        else:
            stmt = stripped_sql[start:semi + 1]
        if not _WHERE.search(stmt):
            return True
    return False


def run(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    catalog: frozenset[str],
    org_config=None,
) -> CheckResult:
    flyway_dir = org_config.flyway_dir if org_config else "db/migration"
    findings: list[Finding] = []

    for repo in sorted(closure):
        migration_dir = f"{repo}/{flyway_dir}"
        try:
            files = workspace.list_files(migration_dir)
        except Exception:
            files = []

        if not files:
            continue

        versions: list[int] = []
        version_files: dict[int, list[str]] = {}

        for fpath in files:
            fname = fpath.rsplit("/", 1)[-1]

            is_versioned = _VERSIONED_RE.match(fname)
            is_repeatable = _REPEATABLE_RE.match(fname)

            if not is_versioned and not is_repeatable:
                continue

            # Read content
            try:
                content = workspace.read_text(fpath)
            except FileNotFoundError:
                continue

            stripped = _strip_comments_and_strings(content)
            if _is_destructive(stripped):
                # Find first destructive line for location
                lines = content.splitlines()
                destructive_line = 1
                for i, ln in enumerate(lines, 1):
                    stripped_line = _strip_comments_and_strings(ln)
                    if (_DROP_TABLE.search(stripped_line) or _DROP_COLUMN.search(stripped_line)
                            or _TRUNCATE.search(stripped_line)
                            or (_DELETE.search(stripped_line) and not _WHERE.search(stripped_line))):
                        destructive_line = i
                        break
                findings.append(Finding(
                    severity="block",
                    code="unsafe_migration",
                    message=f"Unsafe migration statement in {fpath}.",
                    repos=(repo,),
                    suggested_fix="Remove destructive statements or replace them with an expand-and-contract migration.",
                    citation=None,
                    location=f"{fpath}:{destructive_line}",
                    snippet=workspace.get_snippet(fpath, destructive_line),
                ))

            if is_versioned:
                v = int(is_versioned.group(1))
                if v not in version_files:
                    version_files[v] = []
                version_files[v].append(fpath)
                versions.append(v)

        # Duplicate version check
        for v, paths in version_files.items():
            if len(paths) > 1:
                findings.append(Finding(
                    severity="block",
                    code="duplicate_migration_version",
                    message=f"Duplicate Flyway version {v}.",
                    repos=(repo,),
                    suggested_fix="Give each migration a unique version number.",
                    citation=None,
                ))

        # Version gap check
        unique_versions = sorted(set(versions))
        if unique_versions:
            expected = list(range(1, max(unique_versions) + 1))
            if unique_versions != expected:
                findings.append(Finding(
                    severity="block",
                    code="migration_version_gap",
                    message="Flyway versions are not contiguous from 1.",
                    repos=(repo,),
                    suggested_fix="Number migrations contiguously from V1 with no gaps.",
                    citation=None,
                ))

    return CheckResult.from_findings("flyway", findings)
