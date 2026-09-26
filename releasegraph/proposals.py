"""In-app fix tickets from workspace scan — assigned to employees, human-approved."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from releasegraph.models import FixProposal, FixProposalStatus, User, UserRole
from releasegraph.verify import SCAN_CODES

# rgc layout/catalog findings are not file-level code fixes — never open Fix PRs for them.
NON_FILE_ISSUE_CODES = frozenset(
    {
        "missing_repo",
        "unknown_repo",
        "empty_release",
        "missing_workspace",
        "invalid_manifest",
    }
)


def issue_qualifies_for_fix_pr(issue: dict[str, Any]) -> bool:
    if issue.get("source") != "workspace_scan":
        return False
    code = str(issue.get("code") or "")
    if code not in SCAN_CODES or code in NON_FILE_ISSUE_CODES:
        return False
    file_path = str(issue.get("file") or "")
    if not file_path or file_path in {"unknown", "runtime", "workspace"}:
        return False
    normalized = file_path.replace("\\", "/")
    return "/" in normalized or normalized.endswith(".py")


def _next_number(db: Session, project_id: int) -> int:
    current = db.scalar(
        select(func.max(FixProposal.number)).where(FixProposal.project_id == project_id)
    )
    return int(current or 0) + 1


def _assignees(db: Session, organization_id: int) -> list[User]:
    rows = db.scalars(
        select(User)
        .where(
            User.organization_id == organization_id,
            User.role.in_([UserRole.ENGINEER, UserRole.RELEASE_MANAGER]),
        )
        .order_by(User.id)
    ).all()
    return list(rows) or db.scalars(select(User).where(User.organization_id == organization_id)).all()


def upsert_from_issues(
    db: Session,
    project_id: int,
    organization_id: int,
    issues: list[dict[str, Any]],
) -> list[FixProposal]:
    staff = _assignees(db, organization_id)
    created: list[FixProposal] = []
    open_rows = db.scalars(
        select(FixProposal).where(
            FixProposal.project_id == project_id,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        )
    ).all()
    existing = {(p.file_path, p.code, p.line): p for p in open_rows}

    ticket_issues = [i for i in issues if issue_qualifies_for_fix_pr(i)]
    for i, issue in enumerate(ticket_issues):
        file_path = str(issue.get("file") or "unknown")
        code = str(issue.get("code") or "issue")
        line = issue.get("line")
        line_n = int(line) if isinstance(line, int) or (isinstance(line, str) and line.isdigit()) else None
        key = (file_path, code, line_n)
        if key in existing:
            pr = existing[key]
            if issue.get("llm_accepted") and issue.get("llm_fix"):
                pr.llm_suggestion = str(issue.get("llm_fix"))
                pr.llm_accepted = True
            continue
        assignee = staff[i % len(staff)] if staff else None
        engine_fix = issue.get("engine_fix") or issue.get("fix") or ""
        llm_fix = issue.get("llm_fix") if issue.get("llm_accepted") else None
        body = (
            f"## Engine finding (source of truth)\n"
            f"- File: `{file_path}`" + (f":{line_n}" if line_n else "") + "\n"
            f"- Service: {issue.get('service') or 'unknown'}\n"
            f"- Code: `{code}`\n"
            f"- Evidence: {issue.get('evidence') or 'n/a'}\n\n"
            f"### What's wrong\n{issue.get('engine_problem') or issue.get('problem')}\n\n"
            f"### Affects\n{', '.join(issue.get('affects') or []) or 'unmapped'}\n\n"
            f"### Consequences\n{issue.get('consequences')}\n\n"
            f"### Engine fix\n{engine_fix}\n"
        )
        if llm_fix:
            body += f"\n### Groq wording (not verified as a new finding)\n{llm_fix}\n"
        body += (
            "\n---\nIn-app review ticket (not GitHub/Jira). "
            "A human must approve before close; close re-scans the workspace. The app does not write to git."
        )
        title = f"Fix {code} in {file_path}"
        if len(title) > 180:
            title = title[:177] + "..."
        pr = FixProposal(
            project_id=project_id,
            number=_next_number(db, project_id),
            title=title,
            body=body,
            status=FixProposalStatus.NEEDS_HUMAN,
            assignee_user_id=assignee.id if assignee else None,
            file_path=file_path,
            line=line_n,
            service_name=issue.get("service"),
            severity=str(issue.get("severity") or "medium"),
            code=code,
            engine_fix=str(engine_fix),
            llm_suggestion=str(llm_fix) if llm_fix else "",
            evidence=str(issue.get("evidence") or ""),
            affects_json=json.dumps(issue.get("affects") or []),
            confidence=str(issue.get("confidence") or "high"),
            llm_accepted=bool(issue.get("llm_accepted")),
            human_required=True,
        )
        db.add(pr)
        db.flush()
        existing[key] = pr
        created.append(pr)
    return created


def close_junk_fix_proposals(db: Session, project_id: int) -> int:
    """Close open tickets that are rgc repo-layout noise or not real file paths."""
    rows = db.scalars(
        select(FixProposal).where(
            FixProposal.project_id == project_id,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        )
    ).all()
    closed = 0
    for pr in rows:
        junk = (pr.code or "") in NON_FILE_ISSUE_CODES
        path = (pr.file_path or "").replace("\\", "/")
        if not junk and ("/" in path or path.endswith(".py")):
            continue
        pr.status = FixProposalStatus.REJECTED
        pr.verify_message = "Closed: not a workspace file finding (stale rgc repo check)."
        closed += 1
    return closed


def prune_stale_fix_proposals(db: Session, project_id: int, issues: list[dict[str, Any]]) -> int:
    """Close open tickets that no longer match a current scanner issue."""
    keep = set()
    for issue in issues:
        if not issue_qualifies_for_fix_pr(issue):
            continue
        file_path = str(issue.get("file") or "unknown")
        code = str(issue.get("code") or "issue")
        line = issue.get("line")
        line_n = int(line) if isinstance(line, int) or (isinstance(line, str) and line.isdigit()) else None
        keep.add((file_path, code, line_n))
    rows = db.scalars(
        select(FixProposal).where(
            FixProposal.project_id == project_id,
            FixProposal.status.in_(
                [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
            ),
        )
    ).all()
    closed = 0
    for pr in rows:
        if (pr.file_path, pr.code, pr.line) in keep:
            continue
        pr.status = FixProposalStatus.REJECTED
        closed += 1
    return closed


def serialize_proposal(db: Session, p: FixProposal) -> dict[str, Any]:
    assignee = db.get(User, p.assignee_user_id) if p.assignee_user_id else None
    reviewer = db.get(User, p.reviewed_by_user_id) if p.reviewed_by_user_id else None
    try:
        affects = json.loads(p.affects_json or "[]")
    except json.JSONDecodeError:
        affects = []
    return {
        "id": p.id,
        "number": p.number,
        "title": p.title,
        "body": p.body,
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
        "assignee": (
            {"id": assignee.id, "email": assignee.email, "full_name": assignee.full_name, "role": assignee.role.value}
            if assignee
            else None
        ),
        "reviewed_by": (
            {"id": reviewer.id, "email": reviewer.email, "full_name": reviewer.full_name}
            if reviewer
            else None
        ),
        "file": p.file_path,
        "line": p.line,
        "service": p.service_name,
        "severity": p.severity,
        "code": p.code,
        "engine_fix": p.engine_fix,
        "llm_suggestion": p.llm_suggestion or None,
        "evidence": p.evidence or None,
        "affects": affects,
        "confidence": p.confidence,
        "llm_accepted": p.llm_accepted,
        "human_required": p.human_required,
        "in_app": True,
        "external": False,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "merged_at": p.merged_at.isoformat() if p.merged_at else None,
        "verify_message": (p.verify_message or "").strip() or None,
    }
