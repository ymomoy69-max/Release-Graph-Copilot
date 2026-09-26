"""Seed demo e-commerce engineering data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from releasegraph.auth import hash_password
from releasegraph.database import SessionLocal, init_db
from releasegraph.models import (
    Artifact,
    Build,
    Commit,
    Deployment,
    DeploymentStatus,
    Environment,
    Incident,
    IncidentEvent,
    IncidentStatus,
    Organization,
    Project,
    PullRequest,
    Release,
    ReleaseCommit,
    ReleasePullRequest,
    ReleaseService,
    ReleaseStatus,
    Repository,
    RiskFactor,
    Service,
    ServiceDependency,
    TestRun,
    User,
    UserRole,
)
from releasegraph.risk_engine import calculate_release_risk


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


DEMO_STAFF = [
    ("admin@acme.demo", "Admin User", UserRole.ADMIN, "admin123!"),
    ("engineer@acme.demo", "Release Engineer", UserRole.RELEASE_MANAGER, "engineer123!"),
    ("priya@acme.demo", "Priya Shah", UserRole.ENGINEER, "engineer123!"),
    ("sam@acme.demo", "Sam Ortiz", UserRole.ENGINEER, "engineer123!"),
    ("jordan@acme.demo", "Jordan Lee", UserRole.ENGINEER, "engineer123!"),
]


def ensure_demo_staff() -> None:
    """Add missing demo employees without wiping existing data."""
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "acme"))
        if not org:
            return
        added = 0
        for email, name, role, password in DEMO_STAFF:
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
        for email, name, role, password in DEMO_STAFF:
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
        engineer = users_by_email["engineer@acme.demo"]

        demo_root = str((Path(__file__).resolve().parent.parent / "demo" / "ecommerce").resolve())
        project = Project(
            organization_id=org.id,
            slug="ecommerce",
            name="E-Commerce Platform",
            description="Demo microservices storefront (simulated CI/CD and deployments)",
            workspace_path=demo_root,
        )
        db.add(project)
        db.flush()

        repos = {}
        for name in ("frontend", "api-gateway", "product-service", "order-service", "payment-service", "inventory-service", "notification-service"):
            r = Repository(project_id=project.id, name=name, url=f"https://git.demo/acme/{name}")
            db.add(r)
            repos[name] = r
        db.flush()

        services = {}
        crit = {
            "frontend": "low",
            "api-gateway": "high",
            "product-service": "medium",
            "order-service": "high",
            "payment-service": "high",
            "inventory-service": "medium",
            "notification-service": "low",
        }
        for name, repo in repos.items():
            s = Service(
                project_id=project.id,
                name=name,
                criticality=crit[name],
                repository_id=repo.id,
                source_path=str(Path(demo_root) / "services" / name.replace("-service", "").replace("api-gateway", "api_gateway") / "app.py"),
            )
            db.add(s)
            services[name] = s
        db.flush()

        dep_pairs = [
            ("frontend", "api-gateway"),
            ("api-gateway", "product-service"),
            ("api-gateway", "order-service"),
            ("order-service", "inventory-service"),
            ("order-service", "payment-service"),
            ("order-service", "notification-service"),
        ]
        for frm, to in dep_pairs:
            db.add(
                ServiceDependency(
                    project_id=project.id,
                    from_service_id=services[frm].id,
                    to_service_id=services[to].id,
                )
            )

        staging = Environment(project_id=project.id, name="Staging", slug="staging")
        prod = Environment(project_id=project.id, name="Production", slug="production")
        db.add_all([staging, prod])
        db.flush()

        commits_data = [
            ("payment-service", "a1b2c3d", "feat: add payment retry mechanism"),
            ("order-service", "e4f5g6h", "fix: prevent duplicate orders"),
            ("inventory-service", "i7j8k9l", "refactor: improve inventory reservation"),
            ("payment-service", "m0n1o2p", "fix: handle payment timeout"),
            ("frontend", "q3r4s5t", "feat: improve checkout validation"),
        ]
        commit_objs = []
        for repo_name, sha, msg in commits_data:
            c = Commit(
                repository_id=repos[repo_name].id,
                sha=sha + "0" * (40 - len(sha)),
                author="demo@acme.dev",
                message=msg,
                committed_at=_utcnow() - timedelta(days=2),
            )
            db.add(c)
            commit_objs.append(c)
        db.flush()

        prs = []
        for i, (repo_name, title) in enumerate(
            [
                ("payment-service", "Payment retry and timeout handling"),
                ("order-service", "Idempotent order creation"),
                ("frontend", "Checkout validation UX"),
            ],
            start=140,
        ):
            pr = PullRequest(
                repository_id=repos[repo_name].id,
                number=i,
                title=title,
                author="demo@acme.dev",
                state="merged",
                merged_at=_utcnow() - timedelta(days=1),
            )
            db.add(pr)
            prs.append(pr)
        db.flush()

        release = Release(
            project_id=project.id,
            version="v2.8.0",
            status=ReleaseStatus.DEPLOYED,
            environment_id=prod.id,
            summary="Payment reliability and checkout improvements",
            created_at=_utcnow() - timedelta(hours=6),
            rollback_available=True,
        )
        db.add(release)
        db.flush()

        for c in commit_objs:
            db.add(ReleaseCommit(release_id=release.id, commit_id=c.id))
        for pr in prs:
            db.add(ReleasePullRequest(release_id=release.id, pull_request_id=pr.id))
        for name in ("frontend", "api-gateway", "order-service", "payment-service"):
            db.add(ReleaseService(release_id=release.id, service_id=services[name].id))

        build = Build(
            project_id=project.id,
            release_id=release.id,
            status="success",
            started_at=_utcnow() - timedelta(hours=5, minutes=50),
            completed_at=_utcnow() - timedelta(hours=5, minutes=40),
            duration_seconds=600,
        )
        db.add(build)
        db.flush()
        db.add_all(
            [
                TestRun(build_id=build.id, suite="unit", status="success", passed=420, failed=0),
                TestRun(build_id=build.id, suite="integration", status="success", passed=85, failed=0),
            ]
        )
        db.add(Artifact(build_id=build.id, name="ecommerce-bundle", version="v2.8.0", uri="s3://demo/artifacts/v2.8.0"))

        deployment = Deployment(
            release_id=release.id,
            environment_id=prod.id,
            status=DeploymentStatus.SUCCESS,
            started_at=_utcnow() - timedelta(hours=2),
            completed_at=_utcnow() - timedelta(hours=1, minutes=45),
            duration_seconds=900,
            initiated_by_user_id=engineer.id,
        )
        db.add(deployment)
        db.flush()

        svc_list = [services[n] for n in ("frontend", "api-gateway", "order-service", "payment-service")]
        risk = calculate_release_risk(
            release,
            svc_list,
            commit_count=len(commit_objs),
            pr_count=len(prs),
            failed_builds=0,
            failed_tests=0,
            production=True,
            dependency_depth=2,
            recent_incidents=0,
        )
        release.risk_level = risk.level
        release.risk_score = risk.score
        for factor, weight, detail in risk.factors:
            db.add(RiskFactor(release_id=release.id, factor=factor, weight=weight, detail=detail))

        incident = Incident(
            project_id=project.id,
            title="Elevated payment errors after v2.8.0 deploy",
            status=IncidentStatus.INVESTIGATING,
            severity="high",
            service_id=services["payment-service"].id,
            release_id=release.id,
            deployment_id=deployment.id,
            created_at=_utcnow() - timedelta(minutes=90),
        )
        db.add(incident)
        db.flush()

        timeline = [
            ("deployment_completed", "Release v2.8.0 deployed to production"),
            ("metric_spike", "Payment error rate increased"),
            ("alert", "Pager alert: payment-service error budget burn"),
            ("incident_created", "Incident opened by on-call"),
            ("copilot_analysis", "Copilot correlated deployment with error spike"),
        ]
        base = _utcnow() - timedelta(minutes=90)
        for i, (etype, msg) in enumerate(timeline):
            db.add(
                IncidentEvent(
                    incident_id=incident.id,
                    timestamp=base + timedelta(minutes=i * 8),
                    event_type=etype,
                    message=msg,
                    actor="system" if etype != "incident_created" else engineer.email,
                )
            )

        db.commit()
        print("Seed complete.")
        print("  Login: admin@acme.demo / admin123!")
        print("  Employees: priya@acme.demo, sam@acme.demo, jordan@acme.demo / engineer123!")
        print("  Project: ecommerce (E-Commerce Platform)")
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
