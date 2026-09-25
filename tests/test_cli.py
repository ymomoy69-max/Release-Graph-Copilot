"""Tests for the CLI (using subprocess)."""
import json
import os
import subprocess
import sys
import pytest


PYTHON = sys.executable


def run_cli(*args, input=None):
    result = subprocess.run(
        [PYTHON, "-m", "rgc"] + list(args),
        capture_output=True,
        text=True,
        input=input,
    )
    return result


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def test_cli_check_safe(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    assert result.returncode == 0
    assert result.stderr == ""
    data = json.loads(result.stdout)
    assert data["verdict"] == "go"
    assert "Traceback" not in result.stdout


def test_cli_check_creates_gate_json(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    assert os.path.isfile(os.path.join(out_dir, "gate.json"))


def test_cli_check_does_not_create_trigger(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


def test_cli_check_no_go_exits_1(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/unsafe-flag-flip.json", "--out", out_dir)
    assert result.returncode == 1
    assert result.stderr == ""
    data = json.loads(result.stdout)
    assert data["verdict"] == "no_go"
    assert "Traceback" not in result.stdout


def test_cli_check_not_json_exits_1_no_traceback(tmp_path):
    out_dir = str(tmp_path / "out")
    result = run_cli("check", "--release", "fixtures/releases/not-json.txt", "--out", out_dir)
    assert result.returncode == 1
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr
    data = json.loads(result.stdout)
    all_codes = [f["code"] for c in data["checks"] for f in c["findings"]]
    assert all(code == "invalid_manifest" for code in all_codes)


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

def test_cli_approve_safe(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    result = run_cli("approve", "--run", out_dir)
    assert result.returncode == 0
    trigger = json.loads(result.stdout)
    assert trigger["approved"] is True
    assert trigger["folders"] == ["backend", "etl", "gateway"]
    assert trigger["estimate_seconds"] == 260
    assert os.path.isfile(os.path.join(out_dir, "e2e-trigger.json"))


def test_cli_approve_no_prior_check(tmp_path):
    out_dir = str(tmp_path / "empty")
    result = run_cli("approve", "--run", out_dir)
    assert result.returncode == 1
    assert "run not found" in result.stderr


def test_cli_approve_no_go_rejected(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/unsafe-flag-flip.json", "--out", out_dir)
    result = run_cli("approve", "--run", out_dir)
    assert result.returncode == 1
    assert "approval rejected" in result.stderr
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

def test_cli_cancel_pending(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    result = run_cli("cancel", "--run", out_dir)
    assert result.returncode == 0
    # CLI stdout is {"cancelled": true}
    data = json.loads(result.stdout)
    assert data["cancelled"] is True
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))


def test_cli_cancel_approved_rejected(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    run_cli("approve", "--run", out_dir)
    result = run_cli("cancel", "--run", out_dir)
    assert result.returncode == 1
    assert "cancel rejected" in result.stderr
    assert os.path.isfile(os.path.join(out_dir, "e2e-trigger.json"))


def test_cli_cancel_already_cancelled(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    run_cli("cancel", "--run", out_dir)
    result = run_cli("cancel", "--run", out_dir)
    assert result.returncode == 0


def test_cli_approve_then_check_resets_trigger(tmp_path):
    out_dir = str(tmp_path / "out")
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    run_cli("approve", "--run", out_dir)
    # Re-run check: trigger is gone
    run_cli("check", "--release", "fixtures/releases/safe.json", "--out", out_dir)
    assert not os.path.exists(os.path.join(out_dir, "e2e-trigger.json"))
    with open(os.path.join(out_dir, "gate.json")) as f:
        g = json.load(f)
    assert g["state"] == "pending_approval"


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

def test_cli_serve_bad_host():
    result = run_cli("serve", "--host", "0.0.0.0")
    assert result.returncode == 1
    assert "host must be loopback" in result.stderr
