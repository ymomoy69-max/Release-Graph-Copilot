"""
Scenario tests: end-to-end coverage of all release scenarios from section 20.
"""
import json
import subprocess
import sys
import pytest
from rgc.orchestrator import run_release_file
from rgc.models import Checklist, CHECK_ORDER


PYTHON = sys.executable


def run_cli(*args):
    return subprocess.run(
        [PYTHON, "-m", "rgc"] + list(args),
        capture_output=True,
        text=True,
    )


def get_checklist(scenario_id: str) -> dict:
    cl = run_release_file(f"fixtures/releases/{scenario_id}.json")
    return cl.to_dict()


# ---------------------------------------------------------------------------
# safe
# ---------------------------------------------------------------------------

def test_safe_verdict_and_risk():
    d = get_checklist("safe")
    assert d["verdict"] == "go"
    assert d["risk"] == "LOW"
    assert d["gate"] == "pending_approval"


def test_safe_five_pass_summaries():
    d = get_checklist("safe")
    summaries = {c["id"]: c["summary"] for c in d["checks"]}
    assert summaries["pipeline_status"] == "Pipelines: all green"
    assert summaries["workflow_config"] == "Config diff: safe"
    assert summaries["fc_etl"] == "FC/ETL: clear"
    assert summaries["flyway"] == "Flyway: no unsafe migrations"
    assert summaries["playwright_map"] == "E2E scope: 3 folders"


def test_safe_e2e_scope():
    d = get_checklist("safe")
    assert d["e2e"]["folders"] == ["backend", "etl", "gateway"]
    assert d["e2e"]["estimate_seconds"] == 260
    assert d["e2e"]["estimate_display"] == "4m 20s"


def test_safe_no_trigger_file(tmp_path):
    import os
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    assert result.returncode == 0
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


def test_safe_cli_exit_0(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# unsafe-flag-flip
# ---------------------------------------------------------------------------

def test_unsafe_flag_flip_no_go():
    d = get_checklist("unsafe-flag-flip")
    assert d["verdict"] == "no_go"
    assert d["risk"] == "HIGH"
    assert d["gate"] == "blocked"


def test_unsafe_flag_flip_citation():
    d = get_checklist("unsafe-flag-flip")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip_finding = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip_finding["citation"] is not None
    assert flip_finding["citation"]["section"] == "3.2"
    assert flip_finding["citation"]["quote"] == "rehydrate must run before flag flip to GIT"


def test_unsafe_flag_flip_block_report():
    d = get_checklist("unsafe-flag-flip")
    assert d["block_report"] is not None
    assert "BLOCKED — Unsafe flag flip detected" in d["block_report"]
    assert "3.2" in d["block_report"]
    # Citation line matches the actual line in the runbook
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip_finding = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    quote = "rehydrate must run before flag flip to GIT"
    with open("fixtures/workspace/ops-runbooks/README.md") as f:
        lines = f.readlines()
    expected_line = next(i + 1 for i, line in enumerate(lines) if line.rstrip() == quote)
    assert flip_finding["citation"]["line"] == expected_line


def test_unsafe_flag_flip_affected_repos():
    d = get_checklist("unsafe-flag-flip")
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    flip_finding = next(f for f in fc_check["findings"] if f["code"] == "flag_flip_without_rehydrate")
    assert flip_finding["repos"] == ["app-backend", "data-pipeline"]


def test_unsafe_flag_flip_other_four_pass():
    d = get_checklist("unsafe-flag-flip")
    for check in d["checks"]:
        if check["id"] == "fc_etl":
            assert check["status"] == "blocked"
        else:
            assert check["status"] == "pass", f"{check['id']} should pass"


def test_unsafe_flag_flip_cli_exit_1(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/unsafe-flag-flip.json", "--out", out_dir)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["gate"] == "blocked"


def test_unsafe_flag_flip_json_contains_block_report_quote():
    d = get_checklist("unsafe-flag-flip")
    text = json.dumps(d)
    assert "rehydrate must run before flag flip to GIT" in text


# ---------------------------------------------------------------------------
# red-pipeline
# ---------------------------------------------------------------------------

def test_red_pipeline_only_pipeline_blocked():
    d = get_checklist("red-pipeline")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        if check["id"] == "pipeline_status":
            assert check["status"] == "blocked"
            codes = [f["code"] for f in check["findings"]]
            assert "pipeline_not_success" in codes
            repos = [f["repos"] for f in check["findings"] if f["code"] == "pipeline_not_success"]
            assert any("app-backend" in r for r in repos)
        else:
            assert check["status"] == "pass"


# ---------------------------------------------------------------------------
# unsafe-flyway
# ---------------------------------------------------------------------------

def test_unsafe_flyway_only_flyway_blocked():
    d = get_checklist("unsafe-flyway")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        if check["id"] == "flyway":
            assert check["status"] == "blocked"
            codes = [f["code"] for f in check["findings"]]
            assert "unsafe_migration" in codes
        else:
            assert check["status"] == "pass"


# ---------------------------------------------------------------------------
# broken-workflow-contract
# ---------------------------------------------------------------------------

def test_broken_workflow_contract_only_workflow_blocked():
    d = get_checklist("broken-workflow-contract")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        if check["id"] == "workflow_config":
            assert check["status"] == "blocked"
            codes = [f["code"] for f in check["findings"]]
            assert "missing_required" in codes
            assert "type_mismatch" in codes
        else:
            assert check["status"] == "pass"


# ---------------------------------------------------------------------------
# blocked-etl-path
# ---------------------------------------------------------------------------

def test_blocked_etl_path_only_fc_etl_blocked():
    d = get_checklist("blocked-etl-path")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        if check["id"] == "fc_etl":
            assert check["status"] == "blocked"
            codes = [f["code"] for f in check["findings"]]
            assert "etl_without_feature_config" in codes
        else:
            assert check["status"] == "pass"


# ---------------------------------------------------------------------------
# missing-docs
# ---------------------------------------------------------------------------

def test_missing_docs_has_citation_not_found():
    d = get_checklist("missing-docs")
    assert d["verdict"] == "no_go"
    fc_check = next(c for c in d["checks"] if c["id"] == "fc_etl")
    codes = [f["code"] for f in fc_check["findings"]]
    assert "citation_not_found" in codes
    assert d["block_report"] is None


def test_missing_docs_quote_not_in_json():
    """The serialized checklist must not contain the runbook quote."""
    d = get_checklist("missing-docs")
    text = json.dumps(d)
    assert "rehydrate must run before flag flip to GIT" not in text


# ---------------------------------------------------------------------------
# cyclic-graph
# ---------------------------------------------------------------------------

def test_cyclic_graph_all_findings_graph_cycle():
    d = get_checklist("cyclic-graph")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        assert check["status"] == "blocked"
        codes = [f["code"] for f in check["findings"]]
        assert codes == ["graph_cycle"], f"{check['id']} has unexpected codes: {codes}"


# ---------------------------------------------------------------------------
# unknown-repo
# ---------------------------------------------------------------------------

def test_unknown_repo_pipeline_status_unknown_repo():
    d = get_checklist("unknown-repo")
    assert d["verdict"] == "no_go"
    pipeline_check = next(c for c in d["checks"] if c["id"] == "pipeline_status")
    codes = [f["code"] for f in pipeline_check["findings"]]
    assert "unknown_repo" in codes
    # Other four should pass
    for check in d["checks"]:
        if check["id"] != "pipeline_status":
            assert check["status"] == "pass"


# ---------------------------------------------------------------------------
# malformed-yaml
# ---------------------------------------------------------------------------

def test_malformed_yaml_only_workflow_blocked():
    d = get_checklist("malformed-yaml")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        if check["id"] == "workflow_config":
            assert check["status"] == "blocked"
            codes = [f["code"] for f in check["findings"]]
            assert "malformed_yaml" in codes
            msgs = [f["message"] for f in check["findings"]]
            assert all(m == "Invalid workflow YAML." for m in msgs)
        else:
            assert check["status"] == "pass"


# ---------------------------------------------------------------------------
# empty-release
# ---------------------------------------------------------------------------

def test_empty_release_all_findings_empty_release():
    d = get_checklist("empty-release")
    assert d["verdict"] == "no_go"
    for check in d["checks"]:
        assert check["status"] == "blocked"
        codes = [f["code"] for f in check["findings"]]
        assert codes == ["empty_release"]


# ---------------------------------------------------------------------------
# not-json.txt via CLI
# ---------------------------------------------------------------------------

def test_not_json_txt_cli(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/not-json.txt", "--out", out_dir)
    assert result.returncode == 1
    assert "Traceback" not in result.stdout
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert all(code == "invalid_manifest" for code in all_codes)
