"""
Organization configuration loader.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Any

import yaml

from rgc.models import CheckResult, DeployScope, Checklist, CHECK_ORDER, CHECK_NAMES, Finding


_REQUIRED_KEYS = [
    "name",
    "workspace_root",
    "graph",
    "ci_dir",
    "catalog",
    "pipeline_file",
    "migration_dir",
    "protected_paths",
    "max_deploy_repos",
]

# Keys whose values must be strings
_STRING_KEYS = ["name", "workspace_root", "graph", "ci_dir", "catalog",
                "pipeline_file", "migration_dir"]

# Keys that must point to existing files (relative to cwd)
_FILE_KEYS = ["graph", "catalog"]

# Optional keys with defaults
_OPTIONAL_STRING = {
    "citations": None,  # None means no runbook citations
}


@dataclass(frozen=True)
class OrgConfig:
    name: str
    workspace_root: str
    graph: str
    ci_dir: str
    catalog: str
    pipeline_file: str       # e.g. "pipeline.yaml" or "Jenkinsfile" or ".github/workflows/ci.yml"
    migration_dir: str       # relative dir inside each repo, e.g. "db/migrations"
    protected_paths: tuple[str, ...]  # glob patterns, e.g. ("config/**", "*.env")
    max_deploy_repos: int    # changeset_size limit; 0 = unlimited
    citations: str | None    # optional path to runbook citations YAML


def _make_invalid_checklist(release_id: str, code: str, message: str, fix: str) -> Checklist:
    finding = Finding(
        severity="block",
        code=code,
        message=message,
        repos=(),
        suggested_fix=fix,
        citation=None,
    )
    checks = tuple(
        CheckResult(
            id=cid,
            name=CHECK_NAMES[cid],
            status="blocked",
            summary=message,
            findings=(finding,),
        )
        for cid in CHECK_ORDER
    )
    scope = DeployScope(repos=(), repo_count=0, risk_label="HIGH")
    return Checklist(
        release_id=release_id,
        question="Is this deploy safe?",
        verdict="no_go",
        risk="HIGH",
        gate="blocked",
        gate_prompt=None,
        block_report=None,
        deploy_order=(),
        checks=checks,
        deploy_scope=scope,
        suggested_fixes=(fix,),
    )


def load_org_config(path: str) -> "OrgConfig | Checklist":
    """Load org config from YAML. Returns OrgConfig or a validation Checklist."""
    return _load_and_validate(path, release_id="invalid")


def load_org_config_for_release(path: str, release_id: str) -> "OrgConfig | Checklist":
    """Load org config from YAML, using release_id in error checklists."""
    return _load_and_validate(path, release_id=release_id)


def path_matches_protected(path: str, patterns: tuple[str, ...]) -> bool:
    """Return True if path matches any protected glob pattern."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also match just the filename
        fname = path.rsplit("/", 1)[-1]
        if fnmatch.fnmatch(fname, pattern):
            return True
    return False


def _load_and_validate(path: str, release_id: str) -> "OrgConfig | Checklist":
    CODE = "invalid_org_config"
    MSG = "The organization config is invalid."
    FIX = "Fix the organization YAML and re-run the check."

    def err() -> Checklist:
        return _make_invalid_checklist(release_id, CODE, MSG, FIX)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return err()

    if not isinstance(data, dict):
        return err()

    # Check all required keys present
    for key in _REQUIRED_KEYS:
        if key not in data:
            return err()

    # String keys must be strings
    for key in _STRING_KEYS:
        if not isinstance(data[key], str):
            return err()

    # protected_paths must be list of strings
    pp = data["protected_paths"]
    if not isinstance(pp, list) or not all(isinstance(p, str) for p in pp):
        return err()

    # max_deploy_repos must be int
    mdr = data["max_deploy_repos"]
    if not isinstance(mdr, int) or isinstance(mdr, bool):
        return err()

    # File keys must exist on disk
    for key in _FILE_KEYS:
        if not os.path.isfile(data[key]):
            return err()

    # Optional: citations
    citations = data.get("citations")
    if citations is not None and not isinstance(citations, str):
        return err()

    return OrgConfig(
        name=data["name"],
        workspace_root=data["workspace_root"],
        graph=data["graph"],
        ci_dir=data["ci_dir"],
        catalog=data["catalog"],
        pipeline_file=data["pipeline_file"],
        migration_dir=data["migration_dir"],
        protected_paths=tuple(pp),
        max_deploy_repos=int(mdr),
        citations=citations,
    )
