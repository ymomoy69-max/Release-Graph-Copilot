"""Tests for the Flyway checker."""
import os
import pytest
from rgc.checkers import flyway
from rgc.manifest import Release, Overlay
from rgc.workspace import WorkspaceView


def make_catalog():
    from rgc.catalog import load_catalog
    return load_catalog("fixtures/catalog/repos.json")


def run_with_overlays(overlays, workspace_root="fixtures/workspace"):
    release = Release(
        id="test",
        question="q",
        repos=("meridian-gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(),
        overlays=tuple(overlays),
        workspace_root=workspace_root,
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    return flyway.run(release, frozenset(["prompt-backend"]), ws, cat)


# ---------------------------------------------------------------------------
# Baseline passes
# ---------------------------------------------------------------------------

def test_baseline_passes():
    result = run_with_overlays([])
    assert result.status == "pass"
    assert result.summary == "Flyway: no unsafe migrations"


# ---------------------------------------------------------------------------
# Destructive SQL tests using tmp_path workspaces
# ---------------------------------------------------------------------------

def _make_migration_release(tmp_path, sql_content, filename="V1__test.sql"):
    repo = "prompt-backend"
    migration_dir = tmp_path / repo / "db" / "migration"
    migration_dir.mkdir(parents=True)
    (migration_dir / filename).write_text(sql_content)

    # Also need a pipeline.yaml
    repo_dir = tmp_path / repo
    (repo_dir / "pipeline.yaml").write_text("steps:\n  - name: build\n")

    release = Release(
        id="test",
        question="q",
        repos=(repo,),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(),
        overlays=(),
        workspace_root=str(tmp_path),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    return flyway.run(release, frozenset([repo]), ws, cat)


def test_drop_table_blocks(tmp_path):
    result = _make_migration_release(tmp_path, "DROP TABLE users;\n")
    assert result.status == "blocked"
    assert any(f.code == "unsafe_migration" for f in result.findings)


def test_drop_column_blocks(tmp_path):
    result = _make_migration_release(tmp_path, "ALTER TABLE users DROP COLUMN email;\n")
    assert result.status == "blocked"
    assert any(f.code == "unsafe_migration" for f in result.findings)


def test_truncate_blocks(tmp_path):
    result = _make_migration_release(tmp_path, "TRUNCATE TABLE users;\n")
    assert result.status == "blocked"
    assert any(f.code == "unsafe_migration" for f in result.findings)


def test_delete_without_where_blocks(tmp_path):
    result = _make_migration_release(tmp_path, "DELETE FROM users;\n")
    assert result.status == "blocked"
    assert any(f.code == "unsafe_migration" for f in result.findings)


def test_delete_with_where_passes(tmp_path):
    result = _make_migration_release(tmp_path, "DELETE FROM users WHERE id = 1;\n")
    assert result.status == "pass"


def test_select_with_drop_in_string_passes(tmp_path):
    """SELECT 'DROP TABLE users'; passes because it's inside a string."""
    result = _make_migration_release(tmp_path, "SELECT 'DROP TABLE users';\n")
    assert result.status == "pass"


def test_line_comment_with_drop_passes(tmp_path):
    """A line comment -- DROP TABLE users passes."""
    result = _make_migration_release(tmp_path, "-- DROP TABLE users\nSELECT 1;\n")
    assert result.status == "pass"


def test_block_comment_with_drop_passes(tmp_path):
    """A block comment around DROP TABLE users passes."""
    result = _make_migration_release(tmp_path, "/* DROP TABLE users */\nSELECT 1;\n")
    assert result.status == "pass"


def test_r_script_truncate_blocks(tmp_path):
    """R__bad.sql containing TRUNCATE blocks."""
    result = _make_migration_release(tmp_path, "TRUNCATE TABLE log;\n", filename="R__bad.sql")
    assert result.status == "blocked"


def test_r_script_safe_passes(tmp_path):
    """R__rebuild.sql with safe SQL does not create a version gap."""
    result = _make_migration_release(tmp_path, "SELECT 1;\n", filename="R__rebuild.sql")
    assert result.status == "pass"


def test_v1_without_double_underscore_ignored(tmp_path):
    """V1.sql without the double underscore is ignored."""
    result = _make_migration_release(tmp_path, "DROP TABLE users;\n", filename="V1.sql")
    assert result.status == "pass"


def test_empty_migration_set_passes(tmp_path):
    """Empty migration set passes."""
    repo = "prompt-backend"
    repo_dir = tmp_path / repo
    repo_dir.mkdir(parents=True)
    migration_dir = repo_dir / "db" / "migration"
    migration_dir.mkdir(parents=True)
    (repo_dir / "pipeline.yaml").write_text("steps:\n  - name: build\n")

    release = Release(
        id="test",
        question="q",
        repos=(repo,),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(),
        overlays=(),
        workspace_root=str(tmp_path),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = flyway.run(release, frozenset([repo]), ws, cat)
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# Version gap and duplicate tests
# ---------------------------------------------------------------------------

def test_duplicate_v2_blocks(tmp_path):
    repo = "prompt-backend"
    migration_dir = tmp_path / repo / "db" / "migration"
    migration_dir.mkdir(parents=True)
    (migration_dir / "V1__init.sql").write_text("SELECT 1;\n")
    (migration_dir / "V2__a.sql").write_text("SELECT 1;\n")
    (migration_dir / "V2__b.sql").write_text("SELECT 1;\n")
    (tmp_path / repo / "pipeline.yaml").write_text("steps:\n  - name: build\n")

    release = Release(
        id="test", question="q", repos=(repo,),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green", changed_paths=(), overlays=(),
        workspace_root=str(tmp_path),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = flyway.run(release, frozenset([repo]), ws, cat)
    assert any(f.code == "duplicate_migration_version" for f in result.findings)


def test_version_gap_1_and_3(tmp_path):
    """Versions 1 and 3 with no 2 block as a gap."""
    repo = "prompt-backend"
    migration_dir = tmp_path / repo / "db" / "migration"
    migration_dir.mkdir(parents=True)
    (migration_dir / "V1__init.sql").write_text("SELECT 1;\n")
    (migration_dir / "V3__skip.sql").write_text("SELECT 1;\n")
    (tmp_path / repo / "pipeline.yaml").write_text("steps:\n  - name: build\n")

    release = Release(
        id="test", question="q", repos=(repo,),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green", changed_paths=(), overlays=(),
        workspace_root=str(tmp_path),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = flyway.run(release, frozenset([repo]), ws, cat)
    assert any(f.code == "migration_version_gap" for f in result.findings)


def test_only_v2_blocks_as_gap(tmp_path):
    """Only V2 blocks as a gap because the sequence must start at 1."""
    repo = "prompt-backend"
    migration_dir = tmp_path / repo / "db" / "migration"
    migration_dir.mkdir(parents=True)
    (migration_dir / "V2__add.sql").write_text("SELECT 1;\n")
    (tmp_path / repo / "pipeline.yaml").write_text("steps:\n  - name: build\n")

    release = Release(
        id="test", question="q", repos=(repo,),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green", changed_paths=(), overlays=(),
        workspace_root=str(tmp_path),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = flyway.run(release, frozenset([repo]), ws, cat)
    assert any(f.code == "migration_version_gap" for f in result.findings)


def test_r_script_does_not_create_version_gap(tmp_path):
    """R__rebuild.sql with safe SQL does not create a version gap."""
    repo = "prompt-backend"
    migration_dir = tmp_path / repo / "db" / "migration"
    migration_dir.mkdir(parents=True)
    (migration_dir / "V1__init.sql").write_text("SELECT 1;\n")
    (migration_dir / "V2__add.sql").write_text("SELECT 1;\n")
    (migration_dir / "R__rebuild.sql").write_text("SELECT 1;\n")
    (tmp_path / repo / "pipeline.yaml").write_text("steps:\n  - name: build\n")

    release = Release(
        id="test", question="q", repos=(repo,),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green", changed_paths=(), overlays=(),
        workspace_root=str(tmp_path),
    )
    ws = WorkspaceView(release)
    cat = make_catalog()
    result = flyway.run(release, frozenset([repo]), ws, cat)
    # No gap or duplicate
    codes = [f.code for f in result.findings]
    assert "migration_version_gap" not in codes
    assert "duplicate_migration_version" not in codes
