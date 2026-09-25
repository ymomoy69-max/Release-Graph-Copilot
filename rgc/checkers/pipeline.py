"""
Pipeline Status checker.
"""
from __future__ import annotations

import json
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
    from rgc.manifest import DEFAULT_ORG_CONFIG
    pipeline_file = org_config.pipeline_file if org_config else "pipeline.yaml"
    ci_dir = release.ci_dir

    findings: list[Finding] = []

    # Named repos not in catalog and not in graph → unknown_repo
    for repo in release.repos:
        if repo not in catalog and repo not in closure:
            findings.append(Finding(
                severity="block",
                code="unknown_repo",
                message=f"Unknown repository: {repo}.",
                repos=(repo,),
                suggested_fix="Add the repository to the catalog before running a check.",
                citation=None,
            ))

    # Check for missing repo folders in the workspace
    for repo in sorted(closure):
        repo_dir = os.path.join(release.workspace_root, repo)
        if not os.path.isdir(repo_dir):
            findings.append(Finding(
                severity="block",
                code="missing_repo",
                message=f"Repository folder is missing: {repo}.",
                repos=(repo,),
                suggested_fix="Clone or copy the repository into the workspace.",
                citation=None,
                location=repo,
                snippet=None,
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        # 1. Load pipeline file
        pipeline_path = f"{repo}/{pipeline_file}"
        try:
            pipeline_text = workspace.read_text(pipeline_path)
        except FileNotFoundError:
            ci_path = os.path.join(ci_dir, f"{repo}.json")
            findings.append(Finding(
                severity="block",
                code="missing_pipeline",
                message=f"Missing pipeline file for {repo}.",
                repos=(repo,),
                suggested_fix="Add a pipeline.yaml with a steps list.",
                citation=None,
                location=pipeline_path,
                snippet=None,
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        # 2. Validate pipeline structure
        try:
            pipeline = yaml.safe_load(pipeline_text)
        except yaml.YAMLError:
            findings.append(Finding(
                severity="block",
                code="missing_pipeline",
                message=f"Pipeline file for {repo} has no steps list.",
                repos=(repo,),
                suggested_fix="Add a pipeline.yaml with a steps list.",
                citation=None,
                location=pipeline_path,
                snippet=workspace.get_snippet(pipeline_path, 1),
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        if not isinstance(pipeline, dict) or not isinstance(pipeline.get("steps"), list):
            findings.append(Finding(
                severity="block",
                code="missing_pipeline",
                message=f"Pipeline file for {repo} has no steps list.",
                repos=(repo,),
                suggested_fix="Add a pipeline.yaml with a steps list.",
                citation=None,
                location=pipeline_path,
                snippet=workspace.get_snippet(pipeline_path, 1),
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        steps = pipeline["steps"]
        if not all(isinstance(s, dict) and isinstance(s.get("name"), str) for s in steps):
            findings.append(Finding(
                severity="block",
                code="missing_pipeline",
                message=f"Pipeline file for {repo} has no steps list.",
                repos=(repo,),
                suggested_fix="Add a pipeline.yaml with a steps list.",
                citation=None,
                location=pipeline_path,
                snippet=workspace.get_snippet(pipeline_path, 1),
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        # 3-5. CI status
        _check_ci_status(ci_dir, repo, findings)

    return CheckResult.from_findings("pipeline_status", findings)


def _check_ci_status(ci_dir: str, repo: str, findings: list[Finding]) -> None:
    ci_path = os.path.join(ci_dir, f"{repo}.json")
    location = f"{ci_dir}/{repo}.json"
    try:
        with open(ci_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        findings.append(Finding(
            severity="block",
            code="missing_status",
            message=f"Missing CI status for {repo}.",
            repos=(repo,),
            suggested_fix="Publish a CI status file before deploy.",
            citation=None,
            location=location,
            snippet=None,
        ))
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        findings.append(Finding(
            severity="block",
            code="malformed_status",
            message=f"CI status for {repo} is malformed.",
            repos=(repo,),
            suggested_fix="Fix the CI status JSON.",
            citation=None,
            location=f"{location}:1",
            snippet=raw.splitlines()[0] if raw.strip() else None,
        ))
        return

    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        findings.append(Finding(
            severity="block",
            code="malformed_status",
            message=f"CI status for {repo} is malformed.",
            repos=(repo,),
            suggested_fix="Fix the CI status JSON.",
            citation=None,
            location=f"{location}:1",
            snippet=None,
        ))
        return

    status = data["status"]
    if status != "success":
        # Find the line number of "status" in the file for location
        lines = raw.splitlines()
        status_line = 1
        for i, ln in enumerate(lines, 1):
            if '"status"' in ln:
                status_line = i
                break
        findings.append(Finding(
            severity="block",
            code="pipeline_not_success",
            message=f"{repo} pipeline status is {status}.",
            repos=(repo,),
            suggested_fix="Wait for a green pipeline or fix the failing build before deploy.",
            citation=None,
            location=f"{location}:{status_line}",
            snippet="\n".join(lines[max(0, status_line-3):min(len(lines), status_line+2)]),
        ))
