"""Incidents follow workspace scan findings."""
from pathlib import Path

from releasegraph.database import SessionLocal
from releasegraph.models import Incident, IncidentStatus, Organization, Project
from releasegraph.workspace_incidents import sync_incidents_from_scan
from releasegraph.workspace_scan import persist_scan, scan_workspace


def test_sync_creates_and_resolves_scan_incidents():
    root = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    scan = scan_workspace(root)
    db = SessionLocal()
    try:
        org = Organization(slug="sync-test", name="Sync Test")
        db.add(org)
        db.flush()
        project = Project(organization_id=org.id, slug="p", name="P", workspace_path=root)
        db.add(project)
        db.flush()
        persist_scan(db, project, scan)
        out = sync_incidents_from_scan(db, project.id, scan)
        assert out["active_findings"] >= 1
        assert out["created"] >= 1
        open_rows = db.scalars(
            __import__("sqlalchemy").select(Incident).where(
                Incident.project_id == project.id,
                Incident.status != IncidentStatus.RESOLVED,
            )
        ).all()
        assert any(i.title.startswith("Code scan:") for i in open_rows)

        clean = {**scan, "issues": []}
        out2 = sync_incidents_from_scan(db, project.id, clean)
        assert out2["resolved"] >= 1
    finally:
        db.rollback()
        db.close()
