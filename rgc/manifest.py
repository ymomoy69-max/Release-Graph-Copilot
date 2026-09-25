"""
Release manifest loader and validation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from rgc.graph import load_graph, detect_cycle, DeployGraph
from rgc.models import CheckResult, DeployScope, Checklist, CHECK_ORDER, CHECK_NAMES, Finding

# Overlay path validation pattern
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")

DEFAULT_WORKSPACE_ROOT = "fixtures/workspace"
DEFAULT_QUESTION = "Is this deploy safe?"


@dataclass(frozen=True)
class Overlay:
    path: str
    content: str


DEFAULT_ORG_CONFIG = "fixtures/org.yaml"


@dataclass(frozen=True)
class Release:
    id: str
    question: str
    repos: tuple[str, ...]
    graph_path: str
    ci_dir: str
    changed_paths: tuple[str, ...]
    overlays: tuple[Overlay, ...]
    workspace_root: str
    config_path: str = DEFAULT_ORG_CONFIG


def _make_validation_checklist(
    release_id: str,
    question: str,
    code: str,
    message: str,
    suggested_fix: str,
) -> Checklist:
    """Build a blocked checklist for a manifest validation error."""
    finding = Finding(
        severity="block",
        code=code,
        message=message,
        repos=(),
        suggested_fix=suggested_fix,
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
        question=question,
        verdict="no_go",
        risk="HIGH",
        gate="blocked",
        gate_prompt=None,
        block_report=None,
        deploy_order=(),
        checks=checks,
        deploy_scope=scope,
        suggested_fixes=(suggested_fix,),
    )


def _validate_and_build(data: Any, path: str) -> Release | Checklist:
    """
    Validate the parsed JSON data and return either a Release or a validation
    Checklist (on error).
    """
    release_id = "unknown"
    question = DEFAULT_QUESTION

    def err(code: str, message: str, fix: str) -> Checklist:
        return _make_validation_checklist(release_id, question, code, message, fix)

    # Basic structure check
    if not isinstance(data, dict):
        return err(
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )

    # question default
    if "question" in data:
        if not isinstance(data["question"], str):
            return err(
                "invalid_manifest",
                "The release manifest is invalid.",
                "Fix the release manifest JSON and re-run the check.",
            )
        question = data["question"]

    # id check
    raw_id = data.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return err(
            "empty_release_id",
            "Set a non-empty release id.",
            "Set a non-empty release id.",
        )
    release_id = raw_id

    # repos check
    raw_repos = data.get("repos")
    if not isinstance(raw_repos, list) or not all(isinstance(r, str) for r in raw_repos):
        return err(
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )
    if len(raw_repos) == 0:
        return err(
            "empty_release",
            "Name at least one repository in the release.",
            "Name at least one repository in the release.",
        )

    # graph and ci_dir are required in file manifests
    raw_graph = data.get("graph")
    raw_ci_dir = data.get("ci_dir")
    if not isinstance(raw_graph, str):
        return err(
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )
    if not isinstance(raw_ci_dir, str):
        return err(
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )

    # changed_paths
    raw_changed = data.get("changed_paths", [])
    if not isinstance(raw_changed, list) or not all(isinstance(p, str) for p in raw_changed):
        return err(
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )

    # overlays
    raw_overlays = data.get("overlays", [])
    if not isinstance(raw_overlays, list):
        return err(
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )

    overlays: list[Overlay] = []
    for item in raw_overlays:
        if not isinstance(item, dict):
            return err(
                "invalid_manifest",
                "The release manifest is invalid.",
                "Fix the release manifest JSON and re-run the check.",
            )
        opath = item.get("path", "")
        ocontent = item.get("content", "")
        if not isinstance(opath, str) or not isinstance(ocontent, str):
            return err(
                "invalid_manifest",
                "The release manifest is invalid.",
                "Fix the release manifest JSON and re-run the check.",
            )
        # Validate overlay path
        if opath.startswith("/") or ".." in opath.split("/") or not _SAFE_PATH_RE.match(opath):
            return err(
                "unsafe_path",
                "Overlay path is not allowed.",
                "Use a relative path inside the workspace.",
            )
        overlays.append(Overlay(path=opath, content=ocontent))

    # Validate graph
    try:
        graph = load_graph(raw_graph)
    except (ValueError, OSError, FileNotFoundError) as exc:
        return err(
            "malformed_graph",
            "The deploy graph could not be read.",
            "Fix the deploy graph YAML and re-run the check.",
        )

    # Cycle detection
    if detect_cycle(graph):
        return err(
            "graph_cycle",
            "The deploy graph contains a cycle.",
            "Remove the cycle in the deploy graph before checking the release.",
        )

    workspace_root = data.get("workspace_root", DEFAULT_WORKSPACE_ROOT)
    if not isinstance(workspace_root, str):
        workspace_root = DEFAULT_WORKSPACE_ROOT

    config_path = data.get("config", DEFAULT_ORG_CONFIG)
    if not isinstance(config_path, str):
        config_path = DEFAULT_ORG_CONFIG

    return Release(
        id=release_id,
        question=question,
        repos=tuple(raw_repos),
        graph_path=raw_graph,
        ci_dir=raw_ci_dir,
        changed_paths=tuple(raw_changed),
        overlays=tuple(overlays),
        workspace_root=workspace_root,
        config_path=config_path,
    )


def load_release(path: str) -> Release | Checklist:
    """
    Load a release manifest from a JSON file.
    Returns a Release on success or a validation Checklist on any error.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return _make_validation_checklist(
            "unknown",
            DEFAULT_QUESTION,
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _make_validation_checklist(
            "unknown",
            DEFAULT_QUESTION,
            "invalid_manifest",
            "The release manifest is invalid.",
            "Fix the release manifest JSON and re-run the check.",
        )

    return _validate_and_build(data, path)
