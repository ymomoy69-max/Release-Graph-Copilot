"""Tests for the gate module."""
import json
import os
import pytest
from rgc import gate


def make_go_checklist(release_id="safe", folders=None, estimate_seconds=260):
    if folders is None:
        folders = ["backend", "etl", "gateway"]
    return {
        "release_id": release_id,
        "question": "Is this deploy safe?",
        "verdict": "go",
        "risk": "LOW",
        "gate": "pending_approval",
        "gate_prompt": "Ready to trigger E2E. Risk: LOW. Approve?",
        "block_report": None,
        "deploy_order": ["gateway"],
        "checks": [],
        "e2e": {
            "folders": folders,
            "estimate_seconds": estimate_seconds,
            "estimate_display": "4m 20s",
        },
        "suggested_fixes": [],
    }


def make_no_go_checklist(release_id="unsafe"):
    return {
        "release_id": release_id,
        "question": "Is this deploy safe?",
        "verdict": "no_go",
        "risk": "HIGH",
        "gate": "blocked",
        "gate_prompt": None,
        "block_report": "BLOCKED\n",
        "deploy_order": [],
        "checks": [],
        "e2e": {"folders": [], "estimate_seconds": 0, "estimate_display": "0s"},
        "suggested_fixes": [],
    }


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

def test_check_writes_files(tmp_path):
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)

    assert os.path.isfile(os.path.join(out_dir, "checklist.json"))
    assert os.path.isfile(os.path.join(out_dir, "gate.json"))
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


def test_check_gate_state_for_go(tmp_path):
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    g = json.loads(open(os.path.join(out_dir, "gate.json")).read())
    assert g["state"] == "pending_approval"


def test_check_gate_state_for_no_go(tmp_path):
    out_dir = str(tmp_path / "out")
    cl = make_no_go_checklist()
    gate.check(cl, out_dir)
    g = json.loads(open(os.path.join(out_dir, "gate.json")).read())
    assert g["state"] == "blocked"


def test_check_deletes_existing_trigger(tmp_path):
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir)
    trigger_path = os.path.join(out_dir, "e2e-trigger.json")
    open(trigger_path, "w").write("{}")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    assert not os.path.exists(trigger_path)


# ---------------------------------------------------------------------------
# approve()
# ---------------------------------------------------------------------------

def test_approve_go(tmp_path):
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    exit_code, stdout, stderr = gate.approve(out_dir)
    assert exit_code == 0
    assert stderr == ""
    trigger = json.loads(stdout)
    assert trigger["approved"] is True
    assert trigger["folders"] == ["backend", "etl", "gateway"]
    assert trigger["estimate_seconds"] == 260
    assert os.path.isfile(os.path.join(out_dir, "e2e-trigger.json"))


def test_approve_idempotent(tmp_path):
    """A second approve exits 0 and file bytes stay identical."""
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    gate.approve(out_dir)

    trigger_path = os.path.join(out_dir, "e2e-trigger.json")
    with open(trigger_path) as f:
        original_bytes = f.read()

    exit_code, stdout, _ = gate.approve(out_dir)
    assert exit_code == 0
    with open(trigger_path) as f:
        new_bytes = f.read()
    assert original_bytes == new_bytes


def test_approve_no_go_rejected(tmp_path):
    out_dir = str(tmp_path / "out")
    cl = make_no_go_checklist()
    gate.check(cl, out_dir)
    exit_code, stdout, stderr = gate.approve(out_dir)
    assert exit_code == 1
    assert "approval rejected" in stderr
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


def test_approve_no_prior_check(tmp_path):
    out_dir = str(tmp_path / "empty")
    exit_code, stdout, stderr = gate.approve(out_dir)
    assert exit_code == 1
    assert "run not found" in stderr


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------

def test_cancel_pending(tmp_path):
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    exit_code, stdout, stderr = gate.cancel(out_dir)
    assert exit_code == 0
    assert json.loads(stdout) == {"cancelled": True}
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


def test_cancel_idempotent(tmp_path):
    """Cancel on already cancelled run exits 0."""
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    gate.cancel(out_dir)
    exit_code, stdout, stderr = gate.cancel(out_dir)
    assert exit_code == 0


def test_cancel_approved_rejected(tmp_path):
    """Cancel on an approved run exits 1, trigger file remains."""
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    gate.approve(out_dir)
    exit_code, _, stderr = gate.cancel(out_dir)
    assert exit_code == 1
    assert "cancel rejected" in stderr
    assert os.path.isfile(os.path.join(out_dir, "e2e-trigger.json"))


def test_cancel_blocked_rejected(tmp_path):
    """Cancel on blocked exits 1."""
    out_dir = str(tmp_path / "out")
    cl = make_no_go_checklist()
    gate.check(cl, out_dir)
    exit_code, _, stderr = gate.cancel(out_dir)
    assert exit_code == 1
    assert "cancel rejected" in stderr


def test_check_then_approve_then_check_resets(tmp_path):
    """Approve, then check the same --out directory: trigger is gone and gate is pending_approval."""
    out_dir = str(tmp_path / "out")
    cl = make_go_checklist()
    gate.check(cl, out_dir)
    gate.approve(out_dir)
    # Re-run check
    gate.check(cl, out_dir)
    trigger_path = os.path.join(out_dir, "e2e-trigger.json")
    assert not os.path.exists(trigger_path)
    g = json.loads(open(os.path.join(out_dir, "gate.json")).read())
    assert g["state"] == "pending_approval"
