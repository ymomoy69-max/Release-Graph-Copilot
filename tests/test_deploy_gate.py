"""Deploy gate reflects live scanner blocking findings."""
from pathlib import Path

from releasegraph.database import SessionLocal
from releasegraph.deploy_gate import deploy_gate_details
from releasegraph.models import Organization, Project


def test_deploy_gate_clean_ecommerce_workspace():
    root = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    db = SessionLocal()
    try:
        org = Organization(slug="gate-test", name="Gate")
        db.add(org)
        db.flush()
        project = Project(
            organization_id=org.id,
            slug="ec",
            name="EC",
            workspace_path=root,
        )
        db.add(project)
        db.flush()
        gate = deploy_gate_details(db, project)
        assert gate["blocked"] is False
        assert gate["blocking_count"] == 0
    finally:
        db.rollback()
        db.close()
