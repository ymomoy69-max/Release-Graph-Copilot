"""Import git history from the scanned workspace into the production release record."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Commit, Project, ReleaseCommit, Repository, Service
from releasegraph.release_train import bootstrap_production_baseline, get_production_release


def _find_git_root(workspace: str) -> Path | None:
    root = Path(workspace).expanduser().resolve()
    if (root / ".git").is_dir():
        return root
    for parent in [root, *root.parents]:
        if (parent / ".git").is_dir():
            return parent
        if parent == parent.parent:
            break
    return None


def _git_log(root: Path, path: str | None, limit: int) -> list[dict[str, str]]:
    cmd = ["git", "-C", str(root), "log", f"-{limit}", "--format=%H|%an|%s|%aI"]
    if path:
        cmd.extend(["--", path])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    rows: list[dict[str, str]] = []
    for line in out.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        rows.append({"sha": parts[0], "author": parts[1], "message": parts[2], "date": parts[3]})
    return rows


def _parse_git_date(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def sync_git_commits(db: Session, project: Project, *, per_repo: int = 8) -> int:
    """Attach recent git commits from disk to the live production release."""
    workspace = (project.workspace_path or "").strip()
    if not workspace:
        return 0
    git_root = _find_git_root(workspace)
    if not git_root:
        return 0

    bootstrap_production_baseline(db, project)
    release = get_production_release(db, project)
    if not release:
        return 0

    repos = db.scalars(select(Repository).where(Repository.project_id == project.id)).all()
    if not repos:
        return 0

    linked = {
        rc.commit_id
        for rc in db.scalars(select(ReleaseCommit).where(ReleaseCommit.release_id == release.id)).all()
    }
    added = 0
    ws = Path(workspace).resolve()

    for repo in repos:
        svc = db.scalar(select(Service).where(Service.repository_id == repo.id))
        rel_path: str | None = None
        if svc and svc.source_path:
            sp = Path(svc.source_path).resolve()
            try:
                rel_path = str(sp.relative_to(git_root))
            except ValueError:
                try:
                    rel_path = str(sp.relative_to(ws))
                except ValueError:
                    rel_path = None
        entries = _git_log(git_root, rel_path, per_repo)
        if not entries and rel_path:
            entries = _git_log(git_root, None, per_repo)

        for entry in entries:
            sha = entry["sha"][:40]
            existing = db.scalar(
                select(Commit).where(Commit.repository_id == repo.id, Commit.sha == sha)
            )
            if not existing:
                existing = Commit(
                    repository_id=repo.id,
                    sha=sha,
                    author=entry["author"] or "unknown",
                    message=entry["message"] or "",
                    committed_at=_parse_git_date(entry["date"]),
                )
                db.add(existing)
                db.flush()
            if existing.id not in linked:
                db.add(ReleaseCommit(release_id=release.id, commit_id=existing.id))
                linked.add(existing.id)
                added += 1

    if added:
        release.summary = (release.summary or "").split(" · git:")[0]
        release.summary = f"{release.summary} · git: {added} commit(s) from {git_root.name}".strip()
    db.flush()
    return added
