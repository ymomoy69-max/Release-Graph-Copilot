"""Seed auth users and projects; scan workspaces from disk."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from releasegraph.auth import hash_password
from releasegraph.config import settings
from releasegraph.database import SessionLocal, init_db
from releasegraph.models import FixProposal, FixProposalStatus, Organization, Project, ServiceDependency, User, UserRole
from releasegraph.proposals import close_junk_fix_proposals
from releasegraph.project_presets import (
    default_ecommerce_presets,
    default_streaming_presets,
    serialize_presets_json,
)
from releasegraph.workspace_scan import _slug, scan_workspace
from releasegraph.project_scan import ensure_ecommerce_awaiting_scan, ensure_streaming_clean
from releasegraph.workspace_sync import apply_workspace_scan


BOOTSTRAP_USERS = [
    ("admin@acme.demo", "Admin User", UserRole.ADMIN, "admin123!"),
    ("engineer@acme.demo", "Release Engineer", UserRole.RELEASE_MANAGER, "engineer123!"),
    ("priya@acme.demo", "Priya Shah", UserRole.ENGINEER, "engineer123!"),
    ("sam@acme.demo", "Sam Ortiz", UserRole.ENGINEER, "engineer123!"),
    ("jordan@acme.demo", "Jordan Lee", UserRole.ENGINEER, "engineer123!"),
]

REPO_ROOT = Path(__file__).resolve().parent.parent


def ensure_bootstrap_projects() -> None:
    """Add seeded demo projects when missing (no full DB reset)."""
    db = SessionLocal()
    try:
        ensure_ecommerce_awaiting_scan(db)
        ensure_streaming_clean(db)
        db.commit()
    finally:
        db.close()

    streaming_root = (REPO_ROOT / "demo" / "streaming").resolve()
    if not streaming_root.is_dir():
        return
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "acme"))
        admin = db.scalar(select(User).where(User.email == "admin@acme.demo")) if org else None
        if not org or not admin:
            return
        streaming = db.scalar(
            select(Project).where(Project.organization_id == org.id, Project.slug == "streaming")
        )
        presets = default_streaming_presets(streaming_root)
        primary = presets[0]
        correct_ws = primary["workspace"]
        if not streaming:
            streaming = Project(
                organization_id=org.id,
                slug="streaming",
                name="Streaming Platform",
                description=f"OTT microservices on disk: {streaming_root}",
                workspace_path=correct_ws,
                org_config_path="",
                readiness_presets_json=serialize_presets_json(presets),
            )
            db.add(streaming)
            db.flush()
            _scan_project(db, streaming, admin)
            db.commit()
            print(f"Added Streaming Platform project ({streaming_root})")
            return
        dep_count = len(
            db.scalars(
                select(ServiceDependency).where(ServiceDependency.project_id == streaming.id)
            ).all()
        )
        ws = (streaming.workspace_path or "").strip()
        preset_blob = streaming.readiness_presets_json or ""
        junk_prs = db.scalar(
            select(FixProposal.id).where(
                FixProposal.project_id == streaming.id,
                FixProposal.status.in_(
                    [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
                ),
                FixProposal.code.in_(("missing_repo", "unknown_repo")),
            ).limit(1)
        )
        open_scan_pr = db.scalar(
            select(FixProposal.id).where(
                FixProposal.project_id == streaming.id,
                FixProposal.status.in_(
                    [FixProposalStatus.OPEN, FixProposalStatus.NEEDS_HUMAN, FixProposalStatus.APPROVED]
                ),
            ).limit(1)
        )
        needs_rescan = (
            dep_count == 0
            or "demo/streaming" not in ws.replace("\\", "/")
            or "acme-fixtures" in preset_blob
            or junk_prs is not None
            or open_scan_pr is not None
        )
        if needs_rescan:
            streaming.workspace_path = correct_ws
            streaming.org_config_path = ""
            streaming.readiness_presets_json = serialize_presets_json(presets)
            streaming.description = f"OTT microservices on disk: {streaming_root}"
            close_junk_fix_proposals(db, streaming.id)
            _scan_project(db, streaming, admin)
            ensure_streaming_clean(db)
            db.commit()
            print(f"Repaired Streaming Platform workspace and graph ({streaming_root})")
    finally:
        db.close()


def ensure_demo_staff() -> None:
    """Ensure bootstrap login accounts exist (not product data)."""
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "acme"))
        if not org:
            return
        added = 0
        for email, name, role, password in BOOTSTRAP_USERS:
            if db.scalar(select(User).where(User.email == email)):
                continue
            db.add(
                User(
                    email=email,
                    full_name=name,
                    hashed_password=hash_password(password),
                    role=role,
                    organization_id=org.id,
                )
            )
            added += 1
        if added:
            db.commit()
    finally:
        db.close()


def _scan_project(db, project: Project, admin: User) -> tuple[int, int]:
    path = (project.workspace_path or "").strip()
    if not path or not Path(path).is_dir():
        return 0, 0
    scan = scan_workspace(path)
    if scan.get("error"):
        raise RuntimeError(f"Could not scan workspace: {scan.get('error')}")
    stats = apply_workspace_scan(db, project, scan, actor=admin)
    n_svc = int(stats.get("services") or 0)
    n_issues = len(scan.get("issues") or [])
    return n_svc, n_issues


def seed(reset: bool = False) -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.scalar(select(Organization).where(Organization.slug == "acme"))
        if existing and not reset:
            print("Seed data already exists (org acme). Use --reset to recreate.")
            return

        if reset:
            from releasegraph.database import Base, engine

            Base.metadata.drop_all(bind=engine)
            init_db()

        org = Organization(slug="acme", name="Acme Commerce")
        db.add(org)
        db.flush()

        users_by_email = {}
        for email, name, role, password in BOOTSTRAP_USERS:
            u = User(
                email=email,
                full_name=name,
                hashed_password=hash_password(password),
                role=role,
                organization_id=org.id,
            )
            db.add(u)
            users_by_email[email] = u
        db.flush()
        admin = users_by_email["admin@acme.demo"]

        workspace_env = settings.default_workspace
        if workspace_env:
            ecommerce_root = Path(workspace_env).expanduser().resolve()
        else:
            ecommerce_root = (REPO_ROOT / "demo" / "ecommerce").resolve()

        ecommerce_presets = default_ecommerce_presets(ecommerce_root)
        primary_preset = ecommerce_presets[0]

        ecommerce = Project(
            organization_id=org.id,
            slug="ecommerce",
            name="E-Commerce Platform",
            description=f"Live shop microservices on disk: {ecommerce_root}",
            workspace_path=primary_preset["workspace"],
            org_config_path="",
            readiness_presets_json=serialize_presets_json(ecommerce_presets),
        )
        db.add(ecommerce)
        db.flush()

        streaming_root = (REPO_ROOT / "demo" / "streaming").resolve()
        streaming_presets = default_streaming_presets(streaming_root)
        streaming_primary = streaming_presets[0]
        streaming = Project(
            organization_id=org.id,
            slug="streaming",
            name="Streaming Platform",
            description=f"OTT microservices on disk: {streaming_root}",
            workspace_path=streaming_primary["workspace"],
            org_config_path="",
            readiness_presets_json=serialize_presets_json(streaming_presets),
        )
        db.add(streaming)
        db.flush()

        n_svc, n_issues = _scan_project(db, streaming, admin)
        print(f"  Project streaming: {n_svc} services, {n_issues} scanner issues")
        print("  Project ecommerce: awaiting Readiness scan (graph empty until then)")

        db.commit()
        print("Seed complete (2 projects).")
        print(f"  E-commerce workspace: {ecommerce.workspace_path}")
        print(f"  Streaming workspace: {streaming.workspace_path}")
        print("  Login: admin@acme.demo / admin123!")
    finally:
        db.close()


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
