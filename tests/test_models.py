"""Tests for rgc/models.py."""
import json
import pytest
from rgc.models import (
    Citation, Finding, CheckResult, E2EScope, Checklist,
    CHECK_ORDER, format_checklist_json,
)


def make_pass_check(check_id: str) -> CheckResult:
    return CheckResult.from_findings(check_id, [])


def make_warning_check(check_id: str) -> CheckResult:
    f = Finding(
        severity="warning",
        code="w001",
        message="Some warning",
        repos=("repo-a",),
        suggested_fix="Fix it.",
        citation=None,
    )
    return CheckResult.from_findings(check_id, [f])


def make_blocked_check(check_id: str) -> CheckResult:
    f = Finding(
        severity="block",
        code="b001",
        message="A block finding",
        repos=("repo-b",),
        suggested_fix="Fix the block.",
        citation=None,
    )
    return CheckResult.from_findings(check_id, [f])


def all_pass_checks() -> tuple[CheckResult, ...]:
    return tuple(make_pass_check(cid) for cid in CHECK_ORDER)


def e2e_empty() -> E2EScope:
    return E2EScope(folders=(), estimate_seconds=0, estimate_display="0s")


# ---------------------------------------------------------------------------
# Check id order
# ---------------------------------------------------------------------------

def test_check_order_preserved():
    checks = all_pass_checks()
    assert tuple(c.id for c in checks) == CHECK_ORDER


def test_go_low_risk():
    """All pass → go, LOW, pending_approval."""
    checks = all_pass_checks()
    cl = Checklist.build("r1", "Is this deploy safe?", checks, (), e2e_empty())
    assert cl.verdict == "go"
    assert cl.risk == "LOW"
    assert cl.gate == "pending_approval"
    assert cl.gate_prompt == "Ready to trigger E2E. Risk: LOW. Approve?"


def test_go_medium_risk():
    """One warning → go, MEDIUM, pending_approval."""
    checks = tuple(
        make_warning_check(cid) if cid == "flyway" else make_pass_check(cid)
        for cid in CHECK_ORDER
    )
    cl = Checklist.build("r2", "Is this deploy safe?", checks, (), e2e_empty())
    assert cl.verdict == "go"
    assert cl.risk == "MEDIUM"
    assert cl.gate == "pending_approval"
    assert cl.gate_prompt == "Ready to trigger E2E. Risk: MEDIUM. Approve?"


def test_no_go_high_risk():
    """One blocked → no_go, HIGH, blocked, no gate_prompt."""
    checks = tuple(
        make_blocked_check(cid) if cid == "pipeline_status" else make_pass_check(cid)
        for cid in CHECK_ORDER
    )
    cl = Checklist.build("r3", "Is this deploy safe?", checks, (), e2e_empty())
    assert cl.verdict == "no_go"
    assert cl.risk == "HIGH"
    assert cl.gate == "blocked"
    assert cl.gate_prompt is None


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------

def test_go_checklist_round_trip():
    checks = all_pass_checks()
    e2e = E2EScope(folders=("backend", "etl", "gateway"), estimate_seconds=260, estimate_display="4m 20s")
    cl = Checklist.build("safe", "Is this deploy safe?", checks, ("gateway",), e2e)
    d = cl.to_dict()

    # No timestamp key
    assert "timestamp" not in d

    # Five checks in order
    assert [c["id"] for c in d["checks"]] == list(CHECK_ORDER)

    # Serialize to JSON
    js = format_checklist_json(cl)
    parsed = json.loads(js)
    assert parsed["verdict"] == "go"
    assert parsed["risk"] == "LOW"
    assert parsed["e2e"]["estimate_display"] == "4m 20s"
    assert parsed["e2e"]["folders"] == ["backend", "etl", "gateway"]
    # Trailing newline
    assert js.endswith("\n")


def test_no_go_checklist_round_trip():
    checks = tuple(
        make_blocked_check(cid) if cid == "fc_etl" else make_pass_check(cid)
        for cid in CHECK_ORDER
    )
    cl = Checklist.build("unsafe", "Is this deploy safe?", checks, (), e2e_empty(), block_report="BLOCKED\n")
    d = cl.to_dict()
    assert d["verdict"] == "no_go"
    assert d["gate"] == "blocked"
    assert d["block_report"] == "BLOCKED\n"
    assert d["gate_prompt"] is None


# ---------------------------------------------------------------------------
# suggested_fixes deduplication and check order
# ---------------------------------------------------------------------------

def test_suggested_fixes_dedup_and_order():
    f1 = Finding(severity="block", code="a001", message="m1", repos=(), suggested_fix="Fix A.", citation=None)
    f2 = Finding(severity="block", code="a002", message="m2", repos=(), suggested_fix="Fix B.", citation=None)
    f3 = Finding(severity="warning", code="w001", message="m3", repos=(), suggested_fix="Fix A.", citation=None)  # dup

    checks = tuple(
        CheckResult.from_findings(cid, [f1, f2] if cid == "pipeline_status" else [f3] if cid == "flyway" else [])
        for cid in CHECK_ORDER
    )
    cl = Checklist.build("x", "q", checks, (), e2e_empty())
    # Fix A once, Fix B once — Fix A from pipeline (first check) comes first; flyway Fix A is a dup
    assert cl.suggested_fixes == ("Fix A.", "Fix B.")


# ---------------------------------------------------------------------------
# FindResult summary
# ---------------------------------------------------------------------------

def test_pass_summary_pipeline():
    cr = make_pass_check("pipeline_status")
    assert cr.summary == "Pipelines: all green"
    assert cr.status == "pass"


def test_pass_summary_playwright():
    """Playwright pass summary uses n_folders parameter."""
    cr = CheckResult.from_findings("playwright_map", [], n_folders=3)
    assert cr.summary == "E2E scope: 3 folders"


def test_blocked_summary_is_first_finding_message():
    f = Finding(severity="block", code="x001", message="Block msg", repos=(), suggested_fix=None, citation=None)
    cr = CheckResult.from_findings("pipeline_status", [f])
    assert cr.status == "blocked"
    assert cr.summary == "Block msg"


# ---------------------------------------------------------------------------
# Citation serialization
# ---------------------------------------------------------------------------

def test_citation_round_trip():
    cit = Citation(
        file="fixtures/workspace/foo/README.md",
        display="foo/README.md",
        section="3.2",
        line=42,
        quote="some quote",
    )
    d = cit.to_dict()
    assert d == {
        "file": "fixtures/workspace/foo/README.md",
        "display": "foo/README.md",
        "section": "3.2",
        "line": 42,
        "quote": "some quote",
    }


def test_finding_with_citation():
    cit = Citation(file="f", display="d", section="1", line=5, quote="q")
    f = Finding(severity="block", code="c1", message="msg", repos=("r",), suggested_fix="fix", citation=cit)
    d = f.to_dict()
    assert d["citation"]["line"] == 5
