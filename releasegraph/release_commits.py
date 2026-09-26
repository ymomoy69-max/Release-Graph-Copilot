"""Commits on a release relative to its baseline."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Commit, Release, ReleaseCommit


def commits_since_baseline(db: Session, release: Release) -> list[dict[str, str]]:
    if not release.baseline_release_id:
        return []
    base_shas = set(
        db.scalars(
            select(Commit.sha)
            .join(ReleaseCommit, ReleaseCommit.commit_id == Commit.id)
            .where(ReleaseCommit.release_id == release.baseline_release_id)
        ).all()
    )
    rows = db.scalars(
        select(Commit)
        .join(ReleaseCommit, ReleaseCommit.commit_id == Commit.id)
        .where(ReleaseCommit.release_id == release.id)
        .order_by(Commit.committed_at.desc())
    ).all()
    out: list[dict[str, str]] = []
    for c in rows:
        if c.sha in base_shas:
            continue
        out.append({"sha": c.sha[:7], "message": c.message, "author": c.author})
    return out
