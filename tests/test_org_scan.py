"""
Org scan tests — tests/test_org_scan.py
Covers sections 6 and 9 of IBM_BOB_2.0_REAL_ORG_SCAN.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

from rgc.orchestrator import run_release_file

PYTHON = sys.executable


def run_cli(*args):
    return subprocess.run(
        [PYTHON, "-m", "rgc"] + list(args),
        capture_output=True,
        text=True,
    )


def get_checklist(path: str) -> dict:
    cl = run_release_file(path)
    return cl.to_dict()


# ---------------------------------------------------------------------------
# Meridian safe — still GO
# ---------------------------------------------------------------------------

def test_acme_safe_still_go():
    d = get_checklist("fixtures/releases/safe.json")
    assert d["verdict"] == "go"
    assert d["risk"] == "LOW"
    assert d["e2e"]["estimate_display"] == "4m 20s"
    folders = sorted(d["e2e"]["folders"])
    assert folders == ["backend", "etl", "gateway"]


# ---------------------------------------------------------------------------
# Acme unsafe-flag-flip — still cites 3.2
# ---------------------------------------------------------------------------

def test_acme_unsafe_flag_flip_cites_3_2():
    d = get_checklist("fixtures/releases/unsafe-flag-flip.json")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip["citation"]["section"] == "3.2"
    assert "app-backend" in d["block_report"]
    assert "data-pipeline" in d["block_report"]
    assert "Affected: app-backend, data-pipeline" in d["block_report"]


# ---------------------------------------------------------------------------
# Other-org clean — GO, deploy order api/web/jobs
# ---------------------------------------------------------------------------

def test_other_org_clean_is_go():
    d = get_checklist("fixtures/other-org/releases/clean.json")
    assert d["verdict"] == "go"
    assert d["deploy_order"] == ["api", "web", "jobs"]


# ---------------------------------------------------------------------------
# Other-org flag-flip — NO-GO, section 9.1, Affected: api, jobs
# ---------------------------------------------------------------------------

def test_other_org_flag_flip_no_go():
    d = get_checklist("fixtures/other-org/releases/flag-flip.json")
    assert d["verdict"] == "no_go"


def test_other_org_flag_flip_section_9_1():
    d = get_checklist("fixtures/other-org/releases/flag-flip.json")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip["citation"]["section"] == "9.1"


def test_other_org_flag_flip_affected_api_jobs():
    d = get_checklist("fixtures/other-org/releases/flag-flip.json")
    assert "Affected: api, jobs" in d["block_report"]


def test_other_org_flag_flip_no_prompt_backend():
    d = get_checklist("fixtures/other-org/releases/flag-flip.json")
    assert "app-backend" not in json.dumps(d)


def test_other_org_flag_flip_snippet_contains_storage_git():
    d = get_checklist("fixtures/other-org/releases/flag-flip.json")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip["snippet"] is not None
    assert "storage: GIT" in flip["snippet"]


def test_other_org_flag_flip_location_starts_with_feature_flags():
    d = get_checklist("fixtures/other-org/releases/flag-flip.json")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip["location"].startswith("api/config/feature-flags.yaml:")


# ---------------------------------------------------------------------------
# Running Meridian after other-org still cites 3.2, not 9.1
# ---------------------------------------------------------------------------

def test_acme_after_other_org_cites_3_2():
    # Run other-org flag-flip first to load its citation rules
    get_checklist("fixtures/other-org/releases/flag-flip.json")
    # Now run acme — must still cite 3.2
    d = get_checklist("fixtures/releases/unsafe-flag-flip.json")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip["citation"]["section"] == "3.2"
    assert "9.1" not in json.dumps(flip["citation"])


# ---------------------------------------------------------------------------
# Missing org key → invalid_org_config on all five checks, no Traceback
# ---------------------------------------------------------------------------

def test_invalid_org_config_missing_key(tmp_path):
    org_yaml = tmp_path / "bad.yaml"
    org_yaml.write_text("name: test\n# missing other keys\n")
    release_json = tmp_path / "release.json"
    release_json.write_text(json.dumps({
        "id": "test-release",
        "question": "Is this deploy safe?",
        "repos": ["api"],
        "graph": "fixtures/other-org/graph.yaml",
        "ci_dir": "fixtures/other-org/ci",
        "workspace_root": "fixtures/other-org/workspace",
        "config": str(org_yaml),
    }))
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", str(release_json), "--out", out_dir)
    assert result.returncode == 1
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr
    data = json.loads(result.stdout)
    for check in data["checks"]:
        assert check["status"] == "blocked"
        codes = [f["code"] for f in check["findings"]]
        assert "invalid_org_config" in codes


# ---------------------------------------------------------------------------
# CLI direct scan — other-org workspace exits 0, release id other-org+api
# ---------------------------------------------------------------------------

def test_cli_direct_scan_other_org(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", "fixtures/other-org/workspace",
        "--config", "fixtures/other-org/org.yaml",
        "--repos", "api",
        "--ci-dir", "fixtures/other-org/ci",
        "--out", out_dir,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["release_id"] == "other-org+api"


# ---------------------------------------------------------------------------
# --workspace without --config exits 1, stderr "invalid scan arguments"
# ---------------------------------------------------------------------------

def test_workspace_without_config_exits_1(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", "fixtures/other-org/workspace",
        "--repos", "api",
        "--out", out_dir,
    )
    assert result.returncode == 1
    assert "invalid scan arguments" in result.stderr


# ---------------------------------------------------------------------------
# Empty --repos → empty_release
# ---------------------------------------------------------------------------

def test_empty_repos_is_empty_release(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", "fixtures/other-org/workspace",
        "--config", "fixtures/other-org/org.yaml",
        "--repos", "",
        "--out", out_dir,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert all(code == "empty_release" for code in all_codes)


# ---------------------------------------------------------------------------
# Named repo folder not on disk → missing_repo on pipeline_status only
# ---------------------------------------------------------------------------

def test_missing_repo_folder(tmp_path):
    # Create a workspace with no 'api' folder
    ws = tmp_path / "ws"
    ws.mkdir()
    # Need a ci dir with api.json for CI check
    ci = tmp_path / "ci"
    ci.mkdir()
    (ci / "api.json").write_text('{"status": "success"}')

    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", str(ws),
        "--config", "fixtures/other-org/org.yaml",
        "--repos", "api",
        "--ci-dir", str(ci),
        "--out", out_dir,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    pipeline_check = next(c for c in data["checks"] if c["id"] == "pipeline_status")
    codes = [f["code"] for f in pipeline_check["findings"]]
    assert "missing_repo" in codes
    # Other four checks still run (not all blocked by missing_repo)
    other_ids = [c["id"] for c in data["checks"] if c["id"] != "pipeline_status"]
    assert len(other_ids) == 4


# ---------------------------------------------------------------------------
# Overlay path ../secret → unsafe_path
# ---------------------------------------------------------------------------

def test_unsafe_overlay_path(tmp_path):
    overlays_file = tmp_path / "overlays.json"
    overlays_file.write_text(json.dumps([{"path": "../secret", "content": "evil"}]))
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", "fixtures/other-org/workspace",
        "--config", "fixtures/other-org/org.yaml",
        "--repos", "api",
        "--ci-dir", "fixtures/other-org/ci",
        "--overlays", str(overlays_file),
        "--out", out_dir,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert "unsafe_path" in all_codes


# ---------------------------------------------------------------------------
# Runbook quote removed → citation_not_found, quote absent from JSON
# ---------------------------------------------------------------------------

def test_citation_not_found_when_quote_removed(tmp_path):
    # Copy workspace
    import shutil
    ws = tmp_path / "ws"
    shutil.copytree("fixtures/other-org/workspace", str(ws))
    # Remove the quote from the runbook
    runbook = ws / "docs" / "RUNBOOK.md"
    text = runbook.read_text()
    text = text.replace("rehydrate must run before flag flip to GIT", "")
    runbook.write_text(text)

    release_json = tmp_path / "release.json"
    release_json.write_text(json.dumps({
        "id": "test-citation",
        "question": "Is this deploy safe?",
        "repos": ["api", "jobs"],
        "graph": "fixtures/other-org/graph.yaml",
        "ci_dir": "fixtures/other-org/ci",
        "workspace_root": str(ws),
        "config": "fixtures/other-org/org.yaml",
        "overlays": [{"path": "api/config/feature-flags.yaml", "content": "storage: GIT\n"}],
    }))
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", str(release_json), "--out", out_dir)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert "citation_not_found" in all_codes
    assert "rehydrate must run before flag flip to GIT" not in json.dumps(data)


# ---------------------------------------------------------------------------
# Missing workspace directory → missing_workspace
# ---------------------------------------------------------------------------

def test_missing_workspace_directory(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", str(tmp_path / "does_not_exist"),
        "--config", "fixtures/other-org/org.yaml",
        "--repos", "api",
        "--out", out_dir,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert "missing_workspace" in all_codes


# ---------------------------------------------------------------------------
# Duplicate --repos api,api → one repo
# ---------------------------------------------------------------------------

def test_duplicate_repos_collapses(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", "fixtures/other-org/workspace",
        "--config", "fixtures/other-org/org.yaml",
        "--repos", "api,api",
        "--ci-dir", "fixtures/other-org/ci",
        "--out", out_dir,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    # release_id uses sorted unique repos — "other-org+api" not "other-org+api+api"
    assert data["release_id"] == "other-org+api"


# ---------------------------------------------------------------------------
# Cyclic org graph → graph_cycle
# ---------------------------------------------------------------------------

def test_cyclic_org_graph(tmp_path):
    release_json = tmp_path / "release.json"
    release_json.write_text(json.dumps({
        "id": "cyclic-test",
        "question": "Is this deploy safe?",
        "repos": ["api"],
        "graph": "fixtures/graph/cyclic-graph.yaml",
        "ci_dir": "fixtures/other-org/ci",
        "workspace_root": "fixtures/other-org/workspace",
        "config": "fixtures/other-org/org.yaml",
        "overlays": [],
    }))
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", str(release_json), "--out", out_dir)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert "graph_cycle" in all_codes


# ---------------------------------------------------------------------------
# affected_repos in YAML order jobs,api → Affected: jobs, api; finding repos sorted
# ---------------------------------------------------------------------------

def test_affected_repos_yaml_order_preserved_in_block_report(tmp_path):
    # Create org.yaml with affected_repos: jobs then api
    org_yaml = tmp_path / "org.yaml"
    org_yaml.write_text(
        "name: other-org\n"
        "workspace_root: fixtures/other-org/workspace\n"
        "graph: fixtures/other-org/graph.yaml\n"
        "ci_dir: fixtures/other-org/ci\n"
        "catalog: fixtures/other-org/catalog.json\n"
        "citations: fixtures/other-org/citations.yaml\n"
        "pipeline_file: pipeline.yaml\n"
        "flyway_dir: db/migration\n"
        "workflow_config_dir: workflow-configs\n"
        "workflow_contract: rules-service/contract/workflow-contract.yaml\n"
        "feature_flags: api/config/feature-flags.yaml\n"
        "feature_config: api/feature-config/published.yaml\n"
        "etl_job: jobs/jobs/consume.yaml\n"
        "etl_repo: jobs\n"
        "flag_repo: api\n"
        "playwright_readme: web/tests/README.md\n"
        "playwright_timings: web/tests/timings.json\n"
        "affected_repos:\n"
        "  - jobs\n"
        "  - api\n"
    )
    release_json = tmp_path / "release.json"
    release_json.write_text(json.dumps({
        "id": "test-order",
        "question": "Is this deploy safe?",
        "repos": ["api", "jobs"],
        "graph": "fixtures/other-org/graph.yaml",
        "ci_dir": "fixtures/other-org/ci",
        "workspace_root": "fixtures/other-org/workspace",
        "config": str(org_yaml),
        "overlays": [{"path": "api/config/feature-flags.yaml", "content": "storage: GIT\n"}],
    }))
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", str(release_json), "--out", out_dir)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    # block_report uses YAML order: jobs, api
    assert "Affected: jobs, api" in data["block_report"]
    # finding repos are sorted
    fc_check = next(c for c in data["checks"] if c["id"] == "fc_etl")
    flip = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip["repos"] == ["api", "jobs"]


# ---------------------------------------------------------------------------
# pipeline_file: bitbucket-pipelines.yml honored in a temp workspace
# ---------------------------------------------------------------------------

def test_custom_pipeline_filename(tmp_path):
    # Create a temp workspace with bitbucket-pipelines.yml for api, web, jobs
    ws = tmp_path / "ws"
    pipeline_content = "steps:\n  - name: build\n  - name: test\n"
    for repo in ("api", "web", "jobs"):
        repo_dir = ws / repo
        repo_dir.mkdir(parents=True)
        (repo_dir / "bitbucket-pipelines.yml").write_text(pipeline_content)
    # CI dir for all repos in closure
    ci = tmp_path / "ci"
    ci.mkdir()
    for repo in ("api", "web", "jobs"):
        (ci / f"{repo}.json").write_text('{"status": "success"}')
    # Create a simple single-node graph so only api is in closure
    graph_yaml = tmp_path / "graph.yaml"
    graph_yaml.write_text("nodes:\n  - id: api\n    role: backend\nedges: []\n")
    # Create minimal catalog
    catalog_json = tmp_path / "catalog.json"
    catalog_json.write_text('["api", "web", "jobs", "docs"]')
    # Create dummy citations yaml
    citations_yaml = tmp_path / "citations.yaml"
    citations_yaml.write_text("rules: []\n")
    # Create minimal org.yaml using bitbucket-pipelines.yml
    org_yaml = tmp_path / "org.yaml"
    org_yaml.write_text(
        f"name: bb-org\n"
        f"workspace_root: {ws}\n"
        f"graph: {graph_yaml}\n"
        f"ci_dir: {ci}\n"
        f"catalog: {catalog_json}\n"
        f"citations: {citations_yaml}\n"
        f"pipeline_file: bitbucket-pipelines.yml\n"
        f"flyway_dir: db/migration\n"
        f"workflow_config_dir: workflow-configs\n"
        f"workflow_contract: rules-service/contract/workflow-contract.yaml\n"
        f"feature_flags: api/config/feature-flags.yaml\n"
        f"feature_config: api/feature-config/published.yaml\n"
        f"etl_job: jobs/jobs/consume.yaml\n"
        f"etl_repo: jobs\n"
        f"flag_repo: api\n"
        f"playwright_readme: web/tests/README.md\n"
        f"playwright_timings: web/tests/timings.json\n"
        f"affected_repos:\n"
        f"  - api\n"
        f"  - jobs\n"
    )
    out_dir = str(tmp_path / "out")
    result = run_cli(
        "check",
        "--workspace", str(ws),
        "--config", str(org_yaml),
        "--repos", "api",
        "--ci-dir", str(ci),
        "--out", out_dir,
    )
    data = json.loads(result.stdout)
    pipeline_check = next(c for c in data["checks"] if c["id"] == "pipeline_status")
    # Should not have missing_pipeline — bitbucket-pipelines.yml was found
    codes = [f["code"] for f in pipeline_check["findings"]]
    assert "missing_pipeline" not in codes
    assert pipeline_check["status"] == "pass"


# ---------------------------------------------------------------------------
# rgc/ contains neither banned string
# ---------------------------------------------------------------------------

def test_rgc_no_banned_strings():
    """rgc/ must not contain hardcoded org-specific repo names."""
    import pathlib
    rgc_root = pathlib.Path("rgc")
    BANNED = [
        "nc-enterprise-ai-platform-etl-jobs",
        "Affected: prompt-backend",
        "meridian-gateway",
        "meridian-ui",
        "prompt-backend",
        "user-stack-ansible",
    ]
    found = []
    for py_file in rgc_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for banned in BANNED:
            if banned in text:
                found.append(f"{py_file}: contains '{banned}'")
    assert not found, "Banned strings found:\n" + "\n".join(found)
