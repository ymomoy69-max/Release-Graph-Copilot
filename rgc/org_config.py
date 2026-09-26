"""
Organization configuration loader.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml

from rgc.models import CheckResult, E2EScope, Checklist, CHECK_ORDER, CHECK_NAMES, Finding


_REQUIRED_KEYS = [
    "name",
    "workspace_root",
    "graph",
    "ci_dir",
    "catalog",
    "citations",
    "pipeline_file",
    "flyway_dir",
    "workflow_config_dir",
    "workflow_contract",
    "feature_flags",
    "feature_config",
    "etl_job",
    "etl_repo",
    "flag_repo",
    "playwright_readme",
    "playwright_timings",
    "affected_repos",
]

# Keys whose values must be strings (not affected_repos which is a list)
_STRING_KEYS = [k for k in _REQUIRED_KEYS if k != "affected_repos"]

# Keys that must point to existing files (relative to cwd)
_FILE_KEYS = ["graph", "citations", "catalog"]


@dataclass(frozen=True)
class OrgConfig:
    name: str
    workspace_root: str
    graph: str
    ci_dir: str
    catalog: str
    citations: str
    pipeline_file: str
    flyway_dir: str
    workflow_config_dir: str
    workflow_contract: str
    feature_flags: str
    feature_config: str
    etl_job: str
    etl_repo: str
    flag_repo: str
    playwright_readme: str
    playwright_timings: str
    affected_repos: tuple[str, ...]  # stored sorted ascending; YAML order preserved separately
    affected_repos_ordered: tuple[str, ...]  # YAML order, for block_report


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
    e2e = E2EScope(folders=(), estimate_seconds=0, estimate_display="0s")
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
        e2e=e2e,
        suggested_fixes=(fix,),
    )


def load_org_config(path: str) -> "OrgConfig | Checklist":
    """Load org config from YAML. Returns OrgConfig or a validation Checklist."""
    return _load_and_validate(path, release_id="invalid")


def load_org_config_for_release(path: str, release_id: str) -> "OrgConfig | Checklist":
    """Load org config from YAML, using release_id in error checklists."""
    return _load_and_validate(path, release_id=release_id)


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

    # affected_repos must be list of strings
    ar = data["affected_repos"]
    if not isinstance(ar, list) or not all(isinstance(r, str) for r in ar):
        return err()

    # File keys must exist on disk
    for key in _FILE_KEYS:
        if not os.path.isfile(data[key]):
            return err()

    affected_ordered = tuple(ar)
    affected_sorted = tuple(sorted(ar))

    return OrgConfig(
        name=data["name"],
        workspace_root=data["workspace_root"],
        graph=data["graph"],
        ci_dir=data["ci_dir"],
        catalog=data["catalog"],
        citations=data["citations"],
        pipeline_file=data["pipeline_file"],
        flyway_dir=data["flyway_dir"],
        workflow_config_dir=data["workflow_config_dir"],
        workflow_contract=data["workflow_contract"],
        feature_flags=data["feature_flags"],
        feature_config=data["feature_config"],
        etl_job=data["etl_job"],
        etl_repo=data["etl_repo"],
        flag_repo=data["flag_repo"],
        playwright_readme=data["playwright_readme"],
        playwright_timings=data["playwright_timings"],
        affected_repos=affected_sorted,
        affected_repos_ordered=affected_ordered,
    )
