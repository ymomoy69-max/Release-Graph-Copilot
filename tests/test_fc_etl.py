"""Tests for the fc_etl checker."""
import pytest
from rgc.checkers import fc_etl
from rgc.manifest import Release, Overlay
from rgc.workspace import WorkspaceView


def make_release(repos=("gateway",), overlays=()):
    return Release(
        id="test",
        question="q",
        repos=tuple(repos),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(),
        overlays=tuple(overlays),
        workspace_root="fixtures/workspace",
    )


def make_catalog():
    from rgc.catalog import load_catalog
    return load_catalog("fixtures/catalog/repos.json")


FULL_CLOSURE = frozenset([
    "gateway", "app-backend", "infra",
    "frontend", "rules-engine", "data-pipeline",
])
GATEWAY_ONLY = frozenset(["gateway"])


def run_checker(release, closure):
    ws = WorkspaceView(release)
    cat = make_catalog()
    return fc_etl.run(release, closure, ws, cat)


# ---------------------------------------------------------------------------
# Baseline passes
# ---------------------------------------------------------------------------

def test_baseline_passes():
    release = make_release()
    result = run_checker(release, FULL_CLOSURE)
    assert result.status == "pass"
    assert result.summary == "FC/ETL: clear"


# ---------------------------------------------------------------------------
# ETL without feature-config
# ---------------------------------------------------------------------------

def test_etl_without_feature_config_blocked():
    """published: false → blocked."""
    overlays = [Overlay("app-backend/feature-config/published.yaml", "published: false\n")]
    release = make_release(overlays=overlays)
    result = run_checker(release, FULL_CLOSURE)
    codes = [f.code for f in result.findings]
    assert "etl_without_feature_config" in codes


def test_published_false_ignored_when_etl_not_in_closure():
    """published: false is ignored when ETL repo is outside the closure."""
    overlays = [Overlay("app-backend/feature-config/published.yaml", "published: false\n")]
    release = make_release(overlays=overlays)
    result = run_checker(release, GATEWAY_ONLY)
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# Flag flip to GIT
# ---------------------------------------------------------------------------

def test_git_flag_without_rehydrate_blocked():
    """GIT flag set + no rehydrate step → blocked."""
    overlays = [Overlay("app-backend/config/feature-flags.yaml", "storage: GIT\n")]
    release = make_release(overlays=overlays)
    result = run_checker(release, FULL_CLOSURE)
    codes = [f.code for f in result.findings]
    assert "flag_flip_without_rehydrate" in codes


def test_git_flag_with_rehydrate_passes():
    """GIT flag plus a rehydrate step passes the flag rule."""
    pipeline_content = "steps:\n  - name: build\n  - name: rehydrate\n  - name: deploy\n"
    overlays = [
        Overlay("app-backend/config/feature-flags.yaml", "storage: GIT\n"),
        Overlay("app-backend/pipeline.yaml", pipeline_content),
    ]
    release = make_release(overlays=overlays)
    result = run_checker(release, FULL_CLOSURE)
    flip_findings = [f for f in result.findings if f.code == "flag_flip_without_rehydrate"]
    assert flip_findings == []


def test_non_git_storage_does_not_flip():
    """Quoted storage values that are not the string GIT do not flip."""
    overlays = [Overlay("app-backend/config/feature-flags.yaml", "storage: MYSQL\n")]
    release = make_release(overlays=overlays)
    result = run_checker(release, FULL_CLOSURE)
    flip_findings = [f for f in result.findings if f.code == "flag_flip_without_rehydrate"]
    assert flip_findings == []


def test_git_flip_repos_sorted():
    """Repos in the finding are sorted ascending."""
    overlays = [Overlay("app-backend/config/feature-flags.yaml", "storage: GIT\n")]
    release = make_release(overlays=overlays)
    result = run_checker(release, FULL_CLOSURE)
    flip = next(f for f in result.findings if f.code == "flag_flip_without_rehydrate")
    assert flip.repos == tuple(sorted(flip.repos))
