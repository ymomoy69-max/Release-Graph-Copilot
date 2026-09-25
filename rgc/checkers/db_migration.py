"""
DB Migration Safety checker — scans SQL migration files for destructive statements.
Checks every repo in the closure for files under {migration_dir}.
Flags DROP TABLE, DROP COLUMN, TRUNCATE, and DELETE without WHERE.
Works with any migration naming convention (Flyway Vn__name.sql, R__name.sql,
plain .sql files, etc.).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rgc.models import Finding, CheckResult

if TYPE_CHECKING:
    from rgc.manifest import Release
    from rgc.workspace import WorkspaceView
    from rgc.org_config import OrgConfig


# Destructive SQL patterns (applied to comment/string-stripped text)
_DROP_TABLE  = re.compile(r"\bDROP\s+TABLE\b",  re.IGNORECASE)
_DROP_COLUMN = re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)
_TRUNCATE    = re.compile(r"\bTRUNCATE\b",       re.IGNORECASE)
_DELETE      = re.compile(r"\bDELETE\b",         re.IGNORECASE)
_WHERE       = re.compile(r"\bWHERE\b",          re.IGNORECASE)

# Versioned migration: V<n>__<name>.sql  (Flyway-style, case-insensitive)
_VERSIONED_RE  = re.compile(r"^V(\d+)__.*\.sql$", re.IGNORECASE)
# Repeatable migration: R__<name>.sql
_REPEATABLE_RE = re.compile(r"^R__.*\.sql$",       re.IGNORECASE)
# Plain .sql
_PLAIN_SQL_RE  = re.compile(r"\.sql$",             re.IGNORECASE)


def _strip_sql(sql: str) -> str:
    """Remove string literals, line comments, and block comments."""
    result, i, n, in_str = [], 0, len(sql), False
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'" and i + 1 < n and sql[i + 1] == "'":
                result.append("  "); i += 2
            elif ch == "'":
                result.append(" "); i += 1; in_str = False
            else:
                result.append(" "); i += 1
        else:
            if ch == "'":
                result.append(" "); i += 1; in_str = True
            elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
                j = i
                while j < n and sql[j] != "\n": j += 1
                result.append(" " * (j - i)); i = j
            elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
                j = i + 2
                while j < n - 1 and not (sql[j] == "*" and sql[j + 1] == "/"): j += 1
                j = j + 2 if j < n - 1 else n
                result.append(" " * (j - i)); i = j
            else:
                result.append(ch); i += 1
    return "".join(result)


def _is_destructive(stripped: str) -> bool:
    if _DROP_TABLE.search(stripped) or _DROP_COLUMN.search(stripped) or _TRUNCATE.search(stripped):
        return True
    for m in _DELETE.finditer(stripped):
        start = m.start()
        semi  = stripped.find(";", start)
        stmt  = stripped[start:semi + 1] if semi != -1 else stripped[start:]
        if not _WHERE.search(stmt):
            return True
    return False


def run(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    catalog: frozenset[str],
    org_config: "OrgConfig | None" = None,
) -> CheckResult:
    migration_dir = org_config.migration_dir if org_config else "db/migrations"
    findings: list[Finding] = []

    for repo in sorted(closure):
        rel_dir = f"{repo}/{migration_dir}"
        try:
            files = workspace.list_files(rel_dir)
        except Exception:
            files = []

        if not files:
            continue

        versions: list[int] = []
        version_files: dict[int, list[str]] = {}

        for fpath in files:
            fname = fpath.rsplit("/", 1)[-1]
            if not _PLAIN_SQL_RE.search(fname):
                continue

            try:
                content = workspace.read_text(fpath)
            except FileNotFoundError:
                continue

            stripped = _strip_sql(content)
            if _is_destructive(stripped):
                lines = content.splitlines()
                bad_line = 1
                for i, ln in enumerate(lines, 1):
                    s = _strip_sql(ln)
                    if (_DROP_TABLE.search(s) or _DROP_COLUMN.search(s) or _TRUNCATE.search(s)
                            or (_DELETE.search(s) and not _WHERE.search(s))):
                        bad_line = i
                        break
                findings.append(Finding(
                    severity="block",
                    code="unsafe_migration",
                    message=f"Destructive SQL statement in {fpath}.",
                    repos=(repo,),
                    suggested_fix=(
                        "Use an expand-and-contract pattern: add the new column/table first, "
                        "migrate data, then remove the old structure in a later release."
                    ),
                    citation=None,
                    location=f"{fpath}:{bad_line}",
                    snippet=workspace.get_snippet(fpath, bad_line),
                ))

            vm = _VERSIONED_RE.match(fname)
            if vm:
                v = int(vm.group(1))
                version_files.setdefault(v, []).append(fpath)
                versions.append(v)

        for v, paths in version_files.items():
            if len(paths) > 1:
                findings.append(Finding(
                    severity="block",
                    code="duplicate_migration_version",
                    message=f"Duplicate migration version {v} in {repo}.",
                    repos=(repo,),
                    suggested_fix="Give each migration a unique version number.",
                    citation=None,
                ))

        unique = sorted(set(versions))
        if unique and unique != list(range(1, max(unique) + 1)):
            findings.append(Finding(
                severity="block",
                code="migration_version_gap",
                message=f"Migration versions in {repo} are not contiguous from 1.",
                repos=(repo,),
                suggested_fix="Number migrations contiguously from V1 with no gaps.",
                citation=None,
            ))

    return CheckResult.from_findings("db_migration", findings)
