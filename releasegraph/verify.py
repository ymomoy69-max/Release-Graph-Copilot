"""Re-check a Fix PR against the workspace scanner — merge is not a paper stamp."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from releasegraph.models import FixProposal, Project
from releasegraph.workspace_scan import scan_workspace

SCAN_CODES = {"hardcoded_secret", "swallowed_exception", "http_no_timeout", "sql_fstring"}


def files_match(left: str, right: str) -> bool:
    a = left.replace("\\", "/").strip().lstrip("./").lower()
    b = right.replace("\\", "/").strip().lstrip("./").lower()
    if not a or not b:
        return False
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def remaining_scan_hit(issues: list[dict[str, Any]], p: FixProposal) -> dict[str, Any] | None:
    for row in issues:
        if str(row.get("code") or "") != (p.code or ""):
            continue
        if files_match(str(row.get("file") or ""), p.file_path or ""):
            return row
    return None


def verify_fix_ready(db: Session, p: FixProposal) -> dict[str, Any]:
    """Engine must no longer see this scan finding before the ticket can leave the board."""
    code = p.code or ""
    if code not in SCAN_CODES:
        return {
            "ok": True,
            "checked": False,
            "present": False,
            "message": "No file-level scanner code on this ticket; closing it only updates the board.",
        }

    project = db.get(Project, p.project_id)
    root = (project.workspace_path if project else "") or ""
    if not root or not Path(root).is_dir():
        return {
            "ok": False,
            "checked": False,
            "present": True,
            "message": (
                "No scanned workspace on this project. Scan on Readiness first so close can "
                "re-check the file."
            ),
        }

    scan = scan_workspace(root)
    hit = remaining_scan_hit(list(scan.get("issues") or []), p)
    if hit:
        loc = f"{hit.get('file')}:{hit.get('line')}"
        return {
            "ok": False,
            "checked": True,
            "present": True,
            "file": hit.get("file"),
            "line": hit.get("line"),
            "message": (
                f"Engine still finds {code} at {loc}. Change that line in the workspace, then "
                "close again. Closing does not write git — the scanner has to go quiet first."
            ),
        }
    return {
        "ok": True,
        "checked": True,
        "present": False,
        "message": f"Engine no longer finds {code} in {p.file_path}. Ticket leaves the open board.",
    }
