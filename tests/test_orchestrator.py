"""Tests for the orchestrator."""
import time
import pytest
from rgc.orchestrator import run_release, run_release_file
from rgc.manifest import Release, Overlay
from rgc.models import CheckResult, E2EScope, Checklist, CHECK_ORDER, CHECK_NAMES


def make_release(overlays=()):
    return Release(
        id="safe",
        question="Is this deploy safe?",
        repos=("gateway",),
        graph_path="fixtures/graph/deploy-graph.yaml",
        ci_dir="fixtures/ci-status/green",
        changed_paths=(
            "gateway/src/routes.py",
            "app-backend/src/api.py",
            "data-pipeline/jobs/consume.yaml",
        ),
        overlays=tuple(overlays),
        workspace_root="fixtures/workspace",
    )


def _pass_checker(release, closure, workspace, catalog):
    return CheckResult(
        id="pipeline_status",
        name=CHECK_NAMES["pipeline_status"],
        status="pass",
        summary="ok",
        findings=(),
    )


def _make_pass_checkers():
    """Five pass checkers (each returning the appropriate check id)."""
    def make_checker(check_id):
        def checker(release, closure, workspace, catalog):
            return CheckResult(
                id=check_id,
                name=CHECK_NAMES[check_id],
                status="pass",
                summary="ok",
                findings=(),
            )
        return checker
    return [make_checker(cid) for cid in CHECK_ORDER]


# ---------------------------------------------------------------------------
# Exception isolation
# ---------------------------------------------------------------------------

def test_one_checker_raises_others_still_pass():
    """One injected checker raises RuntimeError. That check is checker_error, others pass."""
    def raise_checker(release, closure, workspace, catalog):
        raise RuntimeError("boom")

    checkers = _make_pass_checkers()
    checkers[0] = raise_checker  # pipeline_status raises

    cl = run_release(make_release(), checkers=checkers)
    pipeline_check = next(c for c in cl.checks if c.id == "pipeline_status")
    assert pipeline_check.status == "blocked"
    assert any(f.code == "checker_error" for f in pipeline_check.findings)
    assert any("boom" in f.message for f in pipeline_check.findings)

    # Other four should pass
    for check in cl.checks:
        if check.id != "pipeline_status":
            assert check.status == "pass"


# ---------------------------------------------------------------------------
# Parallelism timing
# ---------------------------------------------------------------------------

def test_five_checkers_run_in_parallel():
    """Five injected checkers each sleep 0.3 seconds with timeout 2. Wall time < 1.2s."""
    import time as _time

    def slow_checker(release, closure, workspace, catalog):
        _time.sleep(0.3)
        return CheckResult(
            id="pipeline_status",
            name="Pipeline Status",
            status="pass",
            summary="ok",
            findings=(),
        )

    checkers = []
    for cid in CHECK_ORDER:
        def make(check_id):
            def checker(release, closure, workspace, catalog):
                _time.sleep(0.3)
                return CheckResult(
                    id=check_id,
                    name=CHECK_NAMES[check_id],
                    status="pass",
                    summary="ok",
                    findings=(),
                )
            return checker
        checkers.append(make(cid))

    start = time.monotonic()
    cl = run_release(make_release(), checkers=checkers, timeout_seconds=2.0)
    elapsed = time.monotonic() - start
    assert elapsed < 1.2


def test_one_checker_timeout():
    """One injected checker sleeps 2 seconds with timeout 0.2. That check is checker_timeout, others pass."""
    import time as _time

    def timeout_checker(release, closure, workspace, catalog):
        _time.sleep(2.0)
        return CheckResult(id="pipeline_status", name="Pipeline Status", status="pass", summary="ok", findings=())

    checkers = _make_pass_checkers()
    checkers[0] = timeout_checker

    cl = run_release(make_release(), checkers=checkers, timeout_seconds=0.2)
    pipeline_check = next(c for c in cl.checks if c.id == "pipeline_status")
    assert pipeline_check.status == "blocked"
    assert any(f.code == "checker_timeout" for f in pipeline_check.findings)

    for check in cl.checks:
        if check.id != "pipeline_status":
            assert check.status == "pass"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_two_run_release_calls_produce_equal_dicts():
    """Two run_release calls on safe produce equal dicts."""
    release = make_release()
    d1 = run_release(release).to_dict()
    d2 = run_release(release).to_dict()
    assert d1 == d2


# ---------------------------------------------------------------------------
# Safe scenario end-to-end
# ---------------------------------------------------------------------------

def test_safe_scenario():
    cl = run_release_file("fixtures/releases/safe.json")
    assert cl.verdict == "go"
    assert cl.risk == "LOW"
    assert cl.gate == "pending_approval"
    d = cl.to_dict()
    assert [c["id"] for c in d["checks"]] == list(CHECK_ORDER)
    assert d["e2e"]["folders"] == ["backend", "etl", "gateway"]
    assert d["e2e"]["estimate_seconds"] == 260
    assert d["e2e"]["estimate_display"] == "4m 20s"
    # All five pass summaries
    pass_summaries = {c["id"]: c["summary"] for c in d["checks"]}
    assert pass_summaries["pipeline_status"] == "Pipelines: all green"
    assert pass_summaries["workflow_config"] == "Config diff: safe"
    assert pass_summaries["fc_etl"] == "FC/ETL: clear"
    assert pass_summaries["flyway"] == "Flyway: no unsafe migrations"
    assert pass_summaries["playwright_map"] == "E2E scope: 3 folders"


# ---------------------------------------------------------------------------
# run_release_file validation error
# ---------------------------------------------------------------------------

def test_run_release_file_invalid_manifest():
    cl = run_release_file("fixtures/releases/not-json.txt")
    assert isinstance(cl, Checklist)
    assert cl.verdict == "no_go"
    d = cl.to_dict()
    all_codes = [f["code"] for c in d["checks"] for f in c["findings"]]
    assert all(code == "invalid_manifest" for code in all_codes)
