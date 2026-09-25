"""
Human gate: check, approve, cancel.
"""
from __future__ import annotations

import json
import os
import sys


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def check(checklist_dict: dict, out_dir: str) -> None:
    """Write checklist.json and gate.json. Delete any existing e2e-trigger.json."""
    os.makedirs(out_dir, exist_ok=True)

    checklist_path = os.path.join(out_dir, "checklist.json")
    gate_path = os.path.join(out_dir, "gate.json")
    trigger_path = os.path.join(out_dir, "e2e-trigger.json")

    # Write checklist
    with open(checklist_path, "w", encoding="utf-8") as fh:
        json.dump(checklist_dict, fh, indent=2)
        fh.write("\n")

    # Determine gate state
    state = "blocked" if checklist_dict.get("verdict") == "no_go" else "pending_approval"
    gate_data = {
        "state": state,
        "release_id": checklist_dict.get("release_id", ""),
    }
    _write_json(gate_path, gate_data)

    # Delete any existing trigger
    if os.path.exists(trigger_path):
        os.remove(trigger_path)


def approve(out_dir: str) -> tuple[int, str, str]:
    """
    Attempt to approve the run in out_dir.
    Returns (exit_code, stdout, stderr).
    """
    gate_path = os.path.join(out_dir, "gate.json")
    checklist_path = os.path.join(out_dir, "checklist.json")
    trigger_path = os.path.join(out_dir, "e2e-trigger.json")

    gate = _read_json(gate_path)
    checklist = _read_json(checklist_path)

    if gate is None or checklist is None:
        return 1, "", "run not found\n"

    state = gate.get("state")

    if state == "approved":
        # Already approved — return existing trigger bytes unchanged
        with open(trigger_path, "r", encoding="utf-8") as fh:
            existing = fh.read()
        return 0, existing, ""

    if state == "pending_approval" and checklist.get("verdict") == "go":
        # Approve
        gate["state"] = "approved"
        _write_json(gate_path, gate)

        # Build trigger
        e2e = checklist.get("e2e", {})
        trigger = {
            "release_id": checklist.get("release_id", ""),
            "approved": True,
            "folders": e2e.get("folders", []),
            "estimate_seconds": e2e.get("estimate_seconds"),
            "estimate_display": e2e.get("estimate_display", ""),
        }
        trigger_json = json.dumps(trigger, indent=2) + "\n"
        with open(trigger_path, "w", encoding="utf-8") as fh:
            fh.write(trigger_json)

        return 0, trigger_json, ""

    return 1, "", "approval rejected\n"


def cancel(out_dir: str) -> tuple[int, str, str]:
    """
    Attempt to cancel the run in out_dir.
    Returns (exit_code, stdout, stderr).
    """
    gate_path = os.path.join(out_dir, "gate.json")
    checklist_path = os.path.join(out_dir, "checklist.json")
    trigger_path = os.path.join(out_dir, "e2e-trigger.json")

    gate = _read_json(gate_path)
    checklist = _read_json(checklist_path)

    if gate is None or checklist is None:
        return 1, "", "run not found\n"

    state = gate.get("state")

    if state == "pending_approval":
        gate["state"] = "cancelled"
        _write_json(gate_path, gate)
        return 0, json.dumps({"cancelled": True}, indent=2) + "\n", ""

    if state == "cancelled":
        return 0, json.dumps({"cancelled": True}, indent=2) + "\n", ""

    if state in ("approved", "blocked"):
        return 1, "", "cancel rejected\n"

    return 1, "", "cancel rejected\n"
