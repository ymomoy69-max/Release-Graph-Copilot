"""Bridge to the rgc release-readiness engine (workspace + org YAML + repos)."""
from __future__ import annotations

import os
from pathlib import Path

from rgc.manifest import Release
from rgc.models import Checklist
from rgc.orchestrator import run_release, run_release_file
from rgc.org_config import load_org_config_for_release

REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(p.resolve())


def run_manifest_check(release_path: str) -> Checklist:
    return run_release_file(_resolve(release_path))


def run_workspace_check(
    workspace: str,
    config: str,
    repos: list[str],
    ci_dir: str | None = None,
    changed_paths: list[str] | None = None,
) -> Checklist:
    workspace = _resolve(workspace)
    config = _resolve(config)
    if not os.path.isdir(workspace):
        from rgc.org_config import _make_invalid_checklist
        return _make_invalid_checklist(
            "scan", "missing_workspace",
            "Workspace directory is missing.",
            "Clone repos into the workspace folder or fix the path.",
        )

    org = load_org_config_for_release(config, "scan")
    if isinstance(org, Checklist):
        return org

    if not repos:
        from releasegraph.workspace_scan import discover_repo_folders
        repos = discover_repo_folders(workspace)

    if not repos:
        from rgc.manifest import _make_validation_checklist
        return _make_validation_checklist(
            "scan", "Is this deploy safe?",
            "empty_release", "Name at least one repository.",
            "Name at least one repository.",
        )

    ci = _resolve(ci_dir) if ci_dir else org.ci_dir
    release_id = org.name + "+" + "+".join(sorted(dict.fromkeys(repos)))

    release = Release(
        id=release_id,
        question="Is this deploy safe?",
        repos=tuple(dict.fromkeys(repos)),
        graph_path=_resolve(org.graph),
        ci_dir=ci,
        changed_paths=tuple(changed_paths or ()),
        overlays=(),
        workspace_root=workspace,
        config_path=config,
    )
    return run_release(release, org_config=org)


# Built-in demo presets (paths relative to repo root)
PRESETS: dict[str, dict] = {
    "safe-go": {
        "label": "Demo: safe release (GO)",
        "kind": "manifest",
        "release_file": "fixtures/releases/safe.json",
    },
    "unsafe-flag-flip": {
        "label": "Demo: unsafe flag flip (NO-GO)",
        "kind": "manifest",
        "release_file": "fixtures/releases/unsafe-flag-flip.json",
    },
    "red-pipeline": {
        "label": "Demo: red pipeline (NO-GO)",
        "kind": "manifest",
        "release_file": "fixtures/releases/red-pipeline.json",
    },
    "workspace-gateway": {
        "label": "Demo: scan workspace (gateway only)",
        "kind": "workspace",
        "workspace": "fixtures/workspace",
        "config": "fixtures/org.yaml",
        "repos": ["gateway"],
        "ci_dir": "fixtures/ci-status/green",
        "changed_paths": [
            "gateway/src/routes.py",
            "app-backend/src/api.py",
            "data-pipeline/jobs/consume.yaml",
        ],
    },
}
