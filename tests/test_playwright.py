"""Tests for the playwright_map checker."""
import json
import pytest
from rgc.checkers import playwright_map
from rgc.manifest import Release, Overlay
from rgc.workspace import WorkspaceView


FULL_CLOSURE = frozenset([
    "gateway", "app-backend", "infra",
    "frontend", "rules-engine", "data-pipeline",
])


def make_release(changed_paths=(), overlays=()):
    return Release(
        id="test",
        question="q",
        repos=("gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=tuple(changed_paths),
        overlays=tuple(overlays),
        workspace_root="fixtures/workspace",
    )


def make_catalog():
    from rgc.catalog import load_catalog
    return load_catalog("fixtures/catalog/repos.json")


def run_checker(release):
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = playwright_map.run(release, FULL_CLOSURE, ws, cat)
    # result is (CheckResult, E2EScope) or just CheckResult if no changed_paths
    return result


def run_and_unpack(release):
    result = run_checker(release)
    if isinstance(result, tuple):
        return result
    return result, None


# ---------------------------------------------------------------------------
# Empty changed_paths
# ---------------------------------------------------------------------------

def test_empty_changed_paths():
    release = make_release(changed_paths=[])
    cr, e2e = run_and_unpack(release)
    assert cr.status == "pass"
    assert cr.summary == "E2E scope: 0 folders"


# ---------------------------------------------------------------------------
# Safe scenario: 3 mapped paths
# ---------------------------------------------------------------------------

def test_safe_scenario_three_folders():
    changed = [
        "gateway/src/routes.py",
        "app-backend/src/api.py",
        "data-pipeline/jobs/consume.yaml",
    ]
    release = make_release(changed_paths=changed)
    cr, e2e = run_and_unpack(release)
    assert cr.status == "pass"
    assert e2e.folders == ("backend", "etl", "gateway")
    assert e2e.estimate_seconds == 260
    assert e2e.estimate_display == "4m 20s"
    assert cr.summary == "E2E scope: 3 folders"


# ---------------------------------------------------------------------------
# Two paths in same folder count once
# ---------------------------------------------------------------------------

def test_two_paths_same_folder_counted_once():
    changed = [
        "gateway/src/routes.py",
        "gateway/src/models.py",
    ]
    release = make_release(changed_paths=changed)
    cr, e2e = run_and_unpack(release)
    assert e2e is not None
    assert "gateway" in e2e.folders
    assert e2e.folders.count("gateway") == 1 if e2e else True


# ---------------------------------------------------------------------------
# Unmapped path → smoke + warning
# ---------------------------------------------------------------------------

def test_unmapped_path_adds_smoke_and_warning():
    """One unmapped path plus one mapped path yields smoke + warning, risk MEDIUM."""
    changed = [
        "gateway/src/routes.py",        # maps to gateway
        "unknown-service/src/api.py",   # unmapped
    ]
    release = make_release(changed_paths=changed)
    cr, e2e = run_and_unpack(release)
    assert cr.status == "warning"
    assert e2e is not None
    assert "smoke" in e2e.folders
    assert "gateway" in e2e.folders
    codes = [f.code for f in cr.findings]
    assert "unmapped_paths" in codes


# ---------------------------------------------------------------------------
# Missing timings
# ---------------------------------------------------------------------------

def test_missing_timings_gives_warning_not_exception():
    # Use an overlay to replace timings.json with missing key
    changed = ["gateway/src/routes.py"]
    overlays = [Overlay("frontend/tests/timings.json", "{}")]  # missing key
    release = make_release(changed_paths=changed, overlays=overlays)
    cr, e2e = run_and_unpack(release)
    assert e2e is not None
    assert e2e.estimate_display == "unknown"
    assert e2e.estimate_seconds is None
    # Folders still set
    assert "gateway" in e2e.folders
    codes = [f.code for f in cr.findings]
    assert "missing_timings" in codes


def test_malformed_timings_json():
    """Timings JSON { → malformed_timings, display unknown, no exception."""
    changed = ["gateway/src/routes.py"]
    overlays = [Overlay("frontend/tests/timings.json", "{")]
    release = make_release(changed_paths=changed, overlays=overlays)
    cr, e2e = run_and_unpack(release)
    assert e2e is not None
    assert e2e.estimate_display == "unknown"
    codes = [f.code for f in cr.findings]
    assert "malformed_timings" in codes


# ---------------------------------------------------------------------------
# Longest prefix wins
# ---------------------------------------------------------------------------

def test_longest_prefix_wins():
    """app-backend/ in README maps to backend folder."""
    changed = ["app-backend/src/api.py"]
    release = make_release(changed_paths=changed)
    cr, e2e = run_and_unpack(release)
    assert e2e is not None
    assert "backend" in e2e.folders
    assert e2e.folders == ("backend",)
