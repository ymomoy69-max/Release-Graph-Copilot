"""
FC/ETL Path checker.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import yaml

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
    # Paths from org config (or Meridian defaults)
    if org_config:
        etl_repo = org_config.etl_repo
        flag_repo = org_config.flag_repo
        etl_job_path = org_config.etl_job
        feature_config_path = org_config.feature_config
        feature_flags_path = org_config.feature_flags
        pipeline_file = org_config.pipeline_file
        affected_repos = org_config.affected_repos  # sorted ascending
        affected_repos_ordered = org_config.affected_repos_ordered  # YAML order
    else:
        etl_repo = "nc-enterprise-ai-platform-etl-jobs"
        flag_repo = "prompt-backend"
        etl_job_path = "nc-enterprise-ai-platform-etl-jobs/jobs/consume.yaml"
        feature_config_path = "prompt-backend/feature-config/published.yaml"
        feature_flags_path = "prompt-backend/config/feature-flags.yaml"
        pipeline_file = "pipeline.yaml"
        affected_repos = tuple(sorted(["prompt-backend", "nc-enterprise-ai-platform-etl-jobs"]))
        affected_repos_ordered = ("prompt-backend", "nc-enterprise-ai-platform-etl-jobs")

    findings: list[Finding] = []

    _check_etl_feature_config(
        closure, workspace, etl_repo, etl_job_path, feature_config_path, findings
    )
    _check_flag_flip(
        release, closure, workspace, flag_repo, feature_flags_path,
        pipeline_file, affected_repos, findings
    )

    return CheckResult.from_findings("fc_etl", findings)


def _check_etl_feature_config(
    closure: frozenset[str],
    workspace: "WorkspaceView",
    etl_repo: str,
    etl_job_path: str,
    feature_config_path: str,
    findings: list[Finding],
) -> None:
    """Feature-config before ETL check."""
    feature_config_repo = feature_config_path.split("/")[0]

    if etl_repo not in closure:
        return

    # Read ETL consume.yaml
    try:
        consume_text = workspace.read_text(etl_job_path)
        consume = yaml.safe_load(consume_text)
    except (FileNotFoundError, yaml.YAMLError):
        return

    if not isinstance(consume, dict):
        return

    if consume.get("requires_feature_config") is not True:
        return

    # Check feature-config published
    try:
        pub_text = workspace.read_text(feature_config_path)
        pub = yaml.safe_load(pub_text)
        if isinstance(pub, dict) and pub.get("published") is True:
            return
    except (FileNotFoundError, yaml.YAMLError):
        pass

    repos = tuple(sorted([etl_repo, feature_config_repo]))
    findings.append(Finding(
        severity="block",
        code="etl_without_feature_config",
        message="ETL promote path is blocked because feature-config is not published.",
        repos=repos,
        suggested_fix="Publish feature-config before promoting ETL jobs.",
        citation=None,
        location=f"{feature_config_path}:1",
        snippet=None,
    ))


def _check_flag_flip(
    release: "Release",
    closure: frozenset[str],
    workspace: "WorkspaceView",
    flag_repo: str,
    feature_flags_path: str,
    pipeline_file: str,
    affected_repos: tuple[str, ...],
    findings: list[Finding],
) -> None:
    """Flag flip to GIT check."""
    # Read baseline (from disk, ignoring overlays)
    baseline_path = os.path.join(release.workspace_root, feature_flags_path)
    try:
        with open(baseline_path, "r", encoding="utf-8") as fh:
            baseline_text = fh.read()
        baseline = yaml.safe_load(baseline_text)
    except (OSError, yaml.YAMLError):
        return

    if not isinstance(baseline, dict):
        return

    baseline_storage = baseline.get("storage")

    # Read effective (through workspace view — overlays win)
    try:
        effective_text = workspace.read_text(feature_flags_path)
        effective = yaml.safe_load(effective_text)
    except (FileNotFoundError, yaml.YAMLError):
        return

    if not isinstance(effective, dict):
        return

    effective_storage = effective.get("storage")

    # A flip is: baseline != "GIT" and effective == "GIT"
    if baseline_storage == "GIT" or effective_storage != "GIT":
        return

    # Flip detected — find the line with storage: GIT in the effective content
    git_line = 1
    for i, line in enumerate(effective_text.splitlines(), 1):
        if "storage" in line and "GIT" in line:
            git_line = i
            break

    # Find location/snippet for the flag line
    flag_location = f"{feature_flags_path}:{git_line}"
    flag_snippet = workspace.get_snippet(feature_flags_path, git_line)

    # Check for rehydrate step
    pipeline_path = f"{flag_repo}/{pipeline_file}"
    rehydrate_found = False
    try:
        pipeline_text = workspace.read_text(pipeline_path)
        pipeline = yaml.safe_load(pipeline_text)
        if isinstance(pipeline, dict) and isinstance(pipeline.get("steps"), list):
            for step in pipeline["steps"]:
                if isinstance(step, dict) and step.get("name") == "rehydrate":
                    rehydrate_found = True
                    break
    except (FileNotFoundError, yaml.YAMLError):
        pass

    if not rehydrate_found:
        # repos = sorted intersection of closure with affected_repos
        repo_set = frozenset(affected_repos)
        repos_in_closure = tuple(sorted(r for r in repo_set if r in closure))
        if not repos_in_closure:
            repos_in_closure = tuple(sorted(affected_repos))

        findings.append(Finding(
            severity="block",
            code="flag_flip_without_rehydrate",
            message="GIT flag set, no rehydrate step found.",
            repos=repos_in_closure,
            suggested_fix="Add rehydrate step before flag flip.",
            citation=None,
            location=flag_location,
            snippet=flag_snippet,
        ))
