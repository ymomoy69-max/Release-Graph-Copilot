"""tests/test_fixtures.py — verify fixture correctness."""
import json
import os
import yaml
import pytest
from rgc.manifest import load_release, Release


WORKSPACE = "fixtures/workspace"
GRAPH_REPOS = [
    "meridian-gateway",
    "prompt-backend",
    "user-stack-ansible",
    "meridian-ui",
    "workflow-service",
    "nc-enterprise-ai-platform-etl-jobs",
]
RELEASE_SCENARIO_IDS = [
    "safe",
    "unsafe-flag-flip",
    "red-pipeline",
    "unsafe-flyway",
    "broken-workflow-contract",
    "blocked-etl-path",
    "missing-docs",
    "cyclic-graph",
    "unknown-repo",
    "malformed-yaml",
    "empty-release",
]


# ---------------------------------------------------------------------------
# Runbook
# ---------------------------------------------------------------------------

def _read_runbook() -> list[str]:
    path = os.path.join(WORKSPACE, "bitbucket-db-migration", "README.md")
    with open(path) as f:
        return f.readlines()


def test_runbook_quote_appears_on_exactly_one_line():
    lines = _read_runbook()
    quote = "rehydrate must run before flag flip to GIT"
    matching = [i + 1 for i, line in enumerate(lines) if line.rstrip() == quote]
    assert len(matching) == 1, f"Quote found {len(matching)} times"


def test_runbook_heading_appears_before_quote():
    lines = _read_runbook()
    quote = "rehydrate must run before flag flip to GIT"
    quote_line = next(i + 1 for i, line in enumerate(lines) if line.rstrip() == quote)
    # Find heading for section 3.2
    heading_line = None
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if "3.2" in stripped and stripped.startswith("#"):
            heading_line = i + 1
            break
    assert heading_line is not None, "Heading 3.2 not found"
    assert heading_line < quote_line, f"Heading {heading_line} is not before quote {quote_line}"


# ---------------------------------------------------------------------------
# Pipeline files
# ---------------------------------------------------------------------------

def test_all_pipeline_files_exist():
    for repo in GRAPH_REPOS:
        path = os.path.join(WORKSPACE, repo, "pipeline.yaml")
        assert os.path.isfile(path), f"Missing pipeline.yaml for {repo}"


def test_no_rehydrate_step_in_baseline():
    for repo in GRAPH_REPOS:
        path = os.path.join(WORKSPACE, repo, "pipeline.yaml")
        with open(path) as f:
            data = yaml.safe_load(f)
        steps = [s["name"] for s in data.get("steps", [])]
        assert "rehydrate" not in steps, f"{repo} has rehydrate step in baseline"


# ---------------------------------------------------------------------------
# Workflow configs
# ---------------------------------------------------------------------------

def _load_contract():
    path = os.path.join(WORKSPACE, "workflow-service", "contract", "workflow-contract.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def test_workflow_configs_parse_and_match_contract():
    contract = _load_contract()
    required = contract["required"]
    allowed_versions = contract["allowed_versions"]

    for i in range(1, 26):
        fname = f"wf-{i:02d}.yaml"
        path = os.path.join(WORKSPACE, "workflow-configs", fname)
        assert os.path.isfile(path), f"Missing {fname}"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), f"{fname} is not a dict"
        for key in required:
            assert key in data, f"{fname} missing required key {key}"
        assert data["version"] in allowed_versions, f"{fname} bad version"
        stem = os.path.splitext(fname)[0]
        assert data["name"] == stem, f"{fname} name mismatch"


# ---------------------------------------------------------------------------
# Catalog and CI directories
# ---------------------------------------------------------------------------

def test_catalog_entries():
    with open("fixtures/catalog/repos.json") as f:
        repos = json.load(f)
    assert len(repos) == 1130
    assert repos[0] == "meridian-gateway"
    assert repos[6] == "bitbucket-db-migration"
    assert repos[-1] == "repo-1130"


def test_green_ci_directory():
    green_dir = "fixtures/ci-status/green"
    for repo in GRAPH_REPOS:
        path = os.path.join(green_dir, f"{repo}.json")
        assert os.path.isfile(path), f"Missing green CI for {repo}"
        with open(path) as f:
            data = json.load(f)
        assert data["status"] == "success"
    # Special out-of-closure file
    with open(os.path.join(green_dir, "repo-0008.json")) as f:
        data = json.load(f)
    assert data["status"] == "failed"


def test_red_ci_directory():
    red_dir = "fixtures/ci-status/red-pipeline"
    for repo in GRAPH_REPOS:
        path = os.path.join(red_dir, f"{repo}.json")
        assert os.path.isfile(path), f"Missing red-pipeline CI for {repo}"
    with open(os.path.join(red_dir, "prompt-backend.json")) as f:
        data = json.load(f)
    assert data["status"] == "failed"
    # Others should be success
    for repo in GRAPH_REPOS:
        if repo == "prompt-backend":
            continue
        with open(os.path.join(red_dir, f"{repo}.json")) as f:
            data = json.load(f)
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Release manifests
# ---------------------------------------------------------------------------

def test_all_release_files_parse():
    for scenario_id in RELEASE_SCENARIO_IDS:
        path = f"fixtures/releases/{scenario_id}.json"
        result = load_release(path)
        # Most scenarios can be a Release or a validation Checklist
        # Empty-release and cyclic-graph return a Checklist (validation error)
        # But all should parse without exception


def test_not_json_txt_exists():
    assert os.path.isfile("fixtures/releases/not-json.txt")
    with open("fixtures/releases/not-json.txt") as f:
        content = f.read()
    assert "not json" in content.lower() or content.strip() == "this is not json"


def test_safe_release_parses_as_release():
    result = load_release("fixtures/releases/safe.json")
    assert isinstance(result, Release)
    assert result.id == "safe"
    assert "meridian-gateway" in result.repos


def test_cyclic_graph_release_returns_checklist():
    from rgc.models import Checklist
    result = load_release("fixtures/releases/cyclic-graph.json")
    assert isinstance(result, Checklist)
    assert result.verdict == "no_go"
