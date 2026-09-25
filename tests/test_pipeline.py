"""Tests for the pipeline checker."""
import json
import os
import pytest
from rgc.checkers import pipeline
from rgc.manifest import Release, Overlay
from rgc.workspace import WorkspaceView


def make_release(repos, ci_dir="fixtures/ci-status/green", overlays=(), workspace_root="fixtures/workspace"):
    return Release(
        id="test",
        question="Is this deploy safe?",
        repos=tuple(repos),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir=ci_dir,
        changed_paths=(),
        overlays=tuple(overlays),
        workspace_root=workspace_root,
    )


def make_catalog():
    from rgc.catalog import load_catalog
    return load_catalog("fixtures/catalog/repos.json")


CLOSURE_GATEWAY = frozenset([
    "meridian-gateway", "prompt-backend", "user-stack-ansible",
    "meridian-ui", "workflow-service", "nc-enterprise-ai-platform-etl-jobs",
])


def test_all_green():
    release = make_release(["meridian-gateway"])
    ws = WorkspaceView(release)
    catalog = make_catalog()
    result = pipeline.run(release, CLOSURE_GATEWAY, ws, catalog)
    assert result.status == "pass"
    assert result.summary == "Pipelines: all green"


def test_pipeline_not_success_failed():
    release = make_release(["meridian-gateway"], ci_dir="fixtures/ci-status/red-pipeline")
    ws = WorkspaceView(release)
    catalog = make_catalog()
    result = pipeline.run(release, CLOSURE_GATEWAY, ws, catalog)
    assert result.status == "blocked"
    codes = [f.code for f in result.findings]
    assert "pipeline_not_success" in codes
    # Only prompt-backend is failed
    bad = [f for f in result.findings if f.code == "pipeline_not_success"]
    assert any("prompt-backend" in f.repos for f in bad)


def test_running_and_canceled_are_pipeline_not_success(tmp_path):
    """running and canceled statuses produce pipeline_not_success."""
    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    # Write a single repo with running status
    (ci_dir / "meridian-gateway.json").write_text('{"status": "running"}')

    release = Release(
        id="t",
        question="q",
        repos=("meridian-gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir=str(ci_dir),
        changed_paths=(),
        overlays=(),
        workspace_root="fixtures/workspace",
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = pipeline.run(release, frozenset(["meridian-gateway"]), ws, cat)
    assert any(f.code == "pipeline_not_success" and "running" in f.message for f in result.findings)

    (ci_dir / "meridian-gateway.json").write_text('{"status": "canceled"}')
    result2 = pipeline.run(release, frozenset(["meridian-gateway"]), ws, cat)
    assert any(f.code == "pipeline_not_success" and "canceled" in f.message for f in result2.findings)


def test_missing_pipeline_and_missing_status_are_separate_findings(tmp_path):
    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    # No CI file for meridian-gateway either

    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    # Create the repo folder but no pipeline.yaml inside it
    (ws_root / "meridian-gateway").mkdir()

    release = Release(
        id="t",
        question="q",
        repos=("meridian-gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir=str(ci_dir),
        changed_paths=(),
        overlays=(),
        workspace_root=str(ws_root),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = pipeline.run(release, frozenset(["meridian-gateway"]), ws, cat)
    codes = [f.code for f in result.findings]
    assert "missing_pipeline" in codes
    assert "missing_status" in codes


def test_malformed_status_json(tmp_path):
    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    (ci_dir / "meridian-gateway.json").write_text("not valid json {{{")

    release = Release(
        id="t",
        question="q",
        repos=("meridian-gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir=str(ci_dir),
        changed_paths=(),
        overlays=(),
        workspace_root="fixtures/workspace",
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = pipeline.run(release, frozenset(["meridian-gateway"]), ws, cat)
    codes = [f.code for f in result.findings]
    assert "malformed_status" in codes


def test_repo_0008_excluded_from_green_closure():
    """repo-0008 failed status in the green directory does not affect a release whose closure excludes it."""
    release = make_release(["meridian-gateway"])
    ws = WorkspaceView(release)
    catalog = make_catalog()
    # Closure does NOT include repo-0008
    result = pipeline.run(release, CLOSURE_GATEWAY, ws, catalog)
    assert result.status == "pass"
    repo_0008_findings = [f for f in result.findings if "repo-0008" in f.repos]
    assert repo_0008_findings == []


def test_unknown_repo():
    release = make_release(["not-a-real-repo"])
    ws = WorkspaceView(release)
    catalog = make_catalog()
    # not-a-real-repo is not in graph, so closure is empty
    result = pipeline.run(release, frozenset(), ws, catalog)
    codes = [f.code for f in result.findings]
    assert "unknown_repo" in codes
