"""
CI Status checker — verifies every repo in the deploy closure has a green build.
Reads {ci_dir}/{repo}.json and expects {"status": "success"}.
Works for any CI system; just drop the JSON file in the ci_dir.
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
    pipeline_file = org_config.pipeline_file if org_config else "pipeline.yaml"
    ci_dir = release.ci_dir
    findings: list[Finding] = []

    # Named repos not in catalog and not in graph closure → unknown_repo
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

    # For every repo in the deploy closure, check its pipeline file and CI status
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

        # Verify pipeline file exists and has a steps list
        pipeline_path = f"{repo}/{pipeline_file}"
        try:
            pipeline_text = workspace.read_text(pipeline_path)
        except FileNotFoundError:
            findings.append(Finding(
                severity="block",
                code="missing_pipeline",
                message=f"Missing pipeline file for {repo}.",
                repos=(repo,),
                suggested_fix=f"Add a {pipeline_file} with a steps list.",
                citation=None,
                location=pipeline_path,
                snippet=None,
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        try:
            pipeline = yaml.safe_load(pipeline_text)
        except yaml.YAMLError:
            findings.append(Finding(
                severity="block",
                code="missing_pipeline",
                message=f"Pipeline file for {repo} could not be parsed.",
                repos=(repo,),
                suggested_fix=f"Fix the YAML syntax in {pipeline_file}.",
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
                suggested_fix=f"Add a steps list to {pipeline_file}.",
                citation=None,
                location=pipeline_path,
                snippet=workspace.get_snippet(pipeline_path, 1),
            ))
            _check_ci_status(ci_dir, repo, findings)
            continue

        _check_ci_status(ci_dir, repo, findings)

    return CheckResult.from_findings("ci_status", findings)


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
            suggested_fix="Publish a CI status JSON file before deploy.",
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
        lines = raw.splitlines()
        status_line = 1
        for i, ln in enumerate(lines, 1):
            if '"status"' in ln:
                status_line = i
                break
        findings.append(Finding(
            severity="block",
            code="ci_not_success",
            message=f"{repo} CI status is {status!r}.",
            repos=(repo,),
            suggested_fix="Wait for a green build before deploying.",
            citation=None,
            location=f"{location}:{status_line}",
            snippet="\n".join(lines[max(0, status_line - 3):min(len(lines), status_line + 2)]),
        ))
