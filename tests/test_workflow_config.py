"""Tests for the workflow_config checker."""
import pytest
from rgc.checkers import workflow_config
from rgc.manifest import Release, Overlay
from rgc.workspace import WorkspaceView


CLOSURE_GATEWAY = frozenset([
    "meridian-gateway", "prompt-backend", "user-stack-ansible",
    "meridian-ui", "workflow-service", "nc-enterprise-ai-platform-etl-jobs",
])


def make_release(overlays=()):
    return Release(
        id="test",
        question="q",
        repos=("meridian-gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(),
        overlays=tuple(overlays),
        workspace_root="fixtures/workspace",
    )


def make_catalog():
    from rgc.catalog import load_catalog
    return load_catalog("fixtures/catalog/repos.json")


def run(overlays=()):
    release = make_release(overlays)
    ws = WorkspaceView(release)
    cat = make_catalog()
    return workflow_config.run(release, CLOSURE_GATEWAY, ws, cat)


# ---------------------------------------------------------------------------
# No overlay → pass
# ---------------------------------------------------------------------------

def test_no_overlay_passes():
    result = run()
    assert result.status == "pass"
    assert result.summary == "Config diff: safe"


# ---------------------------------------------------------------------------
# Valid overlay
# ---------------------------------------------------------------------------

def test_valid_overlay_passes():
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: 1\nsteps: []\ntimeout_seconds: 30\n")])
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# Malformed YAML
# ---------------------------------------------------------------------------

def test_malformed_yaml_overlay():
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: [unterminated\n")])
    assert result.status == "blocked"
    codes = [f.code for f in result.findings]
    assert "malformed_yaml" in codes
    # Message must not contain the exception text
    msgs = [f.message for f in result.findings]
    assert all("Error" not in m for m in msgs)
    assert all("scanner" not in m.lower() for m in msgs)


# ---------------------------------------------------------------------------
# Missing required keys
# ---------------------------------------------------------------------------

def test_missing_required_steps():
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: 1\n")])
    codes = [f.code for f in result.findings]
    assert "missing_required" in codes
    msgs = [f.message for f in result.findings]
    assert any("steps" in m for m in msgs)


# ---------------------------------------------------------------------------
# Version checks
# ---------------------------------------------------------------------------

def test_unknown_version_int():
    """Version int 2 is unknown_version."""
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: 2\nsteps: []\n")])
    codes = [f.code for f in result.findings]
    assert "unknown_version" in codes


def test_boolean_version_is_type_mismatch():
    """Boolean true version is type_mismatch, not an allowed version."""
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: true\nsteps: []\n")])
    codes = [f.code for f in result.findings]
    assert "type_mismatch" in codes
    assert "unknown_version" not in codes


def test_string_version_is_type_mismatch():
    """String version is type_mismatch."""
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: \"nope\"\nsteps: []\n")])
    codes = [f.code for f in result.findings]
    assert "type_mismatch" in codes
    msgs = [f.message for f in result.findings]
    assert any("version" in m for m in msgs)


# ---------------------------------------------------------------------------
# Extra unknown keys pass
# ---------------------------------------------------------------------------

def test_extra_unknown_key_passes():
    """Keys not listed in fields are allowed."""
    result = run([Overlay("workflow-configs/wf-01.yaml",
                           "name: wf-01\nversion: 1\nsteps: []\nextra_unknown_key: anything\n")])
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# Two overlays on same path — last content wins
# ---------------------------------------------------------------------------

def test_two_overlays_same_path_last_wins():
    """Two overlays on the same path: the last content is the one parsed."""
    overlays = [
        Overlay("workflow-configs/wf-01.yaml", "name: [unterminated\n"),  # bad
        Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: 1\nsteps: []\n"),  # good
    ]
    result = run(overlays)
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# Broken scenario matches spec
# ---------------------------------------------------------------------------

def test_broken_workflow_contract_scenario():
    """broken-workflow-contract overlay: missing_required for steps and type_mismatch for version."""
    result = run([Overlay("workflow-configs/wf-01.yaml", "name: wf-01\nversion: \"nope\"\n")])
    codes = [f.code for f in result.findings]
    assert "missing_required" in codes
    assert "type_mismatch" in codes
    # missing_required for steps
    assert any("steps" in f.message for f in result.findings if f.code == "missing_required")
