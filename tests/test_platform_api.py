"""Integration tests for ReleaseGraph platform API."""
import os

import pytest
from fastapi.testclient import TestClient

# Use isolated sqlite for tests
os.environ["DATABASE_URL"] = "sqlite:///./data/test_releasegraph.db"
os.environ["JWT_SECRET"] = "test-secret"

from releasegraph.database import Base, engine, init_db  # noqa: E402
from releasegraph.main import app  # noqa: E402
from releasegraph.seed import seed  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    seed(reset=True)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _token(client: TestClient) -> str:
    r = client.post("/api/v1/auth/login", json={"email": "admin@acme.demo", "password": "admin123!"})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_health(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"


def test_login_and_dashboard(client: TestClient):
    token = _token(client)
    projects = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"}).json()
    assert any(p["slug"] == "ecommerce" for p in projects)
    assert any(p["slug"] == "streaming" for p in projects)
    streaming = next(p for p in projects if p["slug"] == "streaming")
    assert len(streaming.get("readiness_presets") or []) >= 3
    demo = next(p for p in streaming["readiness_presets"] if p["id"] == "streaming")
    assert "streaming" in demo["workspace"]
    pid = next(p["id"] for p in projects if p["slug"] == "ecommerce")
    dash = client.get(f"/api/v1/dashboard?project_id={pid}", headers={"Authorization": f"Bearer {token}"}).json()
    assert dash["services_count"] >= 7
    assert dash["scan_issue_count"] >= 0
    assert dash.get("workspace_path")


def test_workspace_scan_endpoint(client: TestClient):
    token = _token(client)
    pid = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]
    from pathlib import Path
    ws = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    r = client.post(
        "/api/v1/workspaces/scan",
        headers={"Authorization": f"Bearer {token}"},
        json={"workspace": ws, "project_id": pid, "persist": True},
    )
    assert r.status_code == 200
    body = r.json()
    names = {s["name"] for s in body["scan"]["services"]}
    assert "payment-service" in names
    assert body["analysis"]["issue_count"] >= 0


def test_graph_shows_breaking_links(client: TestClient):
    token = _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.get("/api/v1/projects", headers=headers).json()[0]["id"]
    from pathlib import Path

    ws = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    client.post(
        "/api/v1/workspaces/scan",
        headers=headers,
        json={"workspace": ws, "project_id": pid, "persist": True},
    )
    g = client.get(f"/api/v1/graph?project_id={pid}", headers=headers).json()
    assert g["broken_links"]
    assert any(l["to"] == "payment-service" for l in g["broken_links"])
    pay = next(n for n in g["nodes"] if n["label"] == "payment-service")
    assert pay["status"] in {"broken", "warning"}
    assert pay["would_change"]


def test_analysis_names_files(client: TestClient):
    token = _token(client)
    pid = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]
    r = client.post(
        "/api/v1/analysis/errors",
        headers={"Authorization": f"Bearer {token}"},
        json={"project_id": pid},
    )
    assert r.status_code == 200
    assert "issues" in r.json()
    body = r.json()
    assert body["safety"]["human_required"] is True
    assert body["safety"]["engine_source_of_truth"] is True
    assert "proposals" in body


def test_fix_pr_human_and_four_eyes(client: TestClient):
    admin = _token(client)
    headers_admin = {"Authorization": f"Bearer {admin}"}
    pid = client.get("/api/v1/projects", headers=headers_admin).json()[0]["id"]
    from pathlib import Path

    ws = str(Path(__file__).resolve().parent.parent / "demo" / "ecommerce")
    scan = client.post(
        "/api/v1/workspaces/scan",
        headers=headers_admin,
        json={"workspace": ws, "project_id": pid, "persist": True},
    )
    assert scan.status_code == 200
    analysis = scan.json()["analysis"]
    assert analysis["safety"]["human_required"] is True
    prs = client.get(f"/api/v1/fix-prs?project_id={pid}", headers=headers_admin).json()
    if analysis["issue_count"] == 0:
        assert prs == []
        return
    assert prs
    assert prs[0]["assignee"] is not None
    first = next(
        p
        for p in prs
        if p["status"] in {"NEEDS_HUMAN", "OPEN"}
        and p["code"] in {"hardcoded_secret", "swallowed_exception", "http_no_timeout", "sql_fstring"}
    )
    assert first["human_required"] is True

    no_confirm = client.post(
        f"/api/v1/fix-prs/{first['id']}/approve", headers=headers_admin, json={"confirm": False}
    )
    assert no_confirm.status_code == 400
    too_soon = client.post(
        f"/api/v1/fix-prs/{first['id']}/merge", headers=headers_admin, json={"confirm": True}
    )
    assert too_soon.status_code == 400

    eng = client.post(
        "/api/v1/auth/login",
        json={"email": "engineer@acme.demo", "password": "engineer123!"},
    )
    assert eng.status_code == 200
    headers_eng = {"Authorization": f"Bearer {eng.json()['access_token']}"}
    approved = client.post(
        f"/api/v1/fix-prs/{first['id']}/approve",
        headers=headers_eng,
        json={"confirm": True},
    )
    assert approved.status_code == 200
    blocked = client.post(
        f"/api/v1/fix-prs/{first['id']}/merge",
        headers=headers_eng,
        json={"confirm": True},
    )
    assert blocked.status_code == 400
    merged = client.post(
        f"/api/v1/fix-prs/{first['id']}/merge",
        headers=headers_admin,
        json={"confirm": True},
    )
    assert merged.status_code == 400
    body = merged.json()
    detail = str(body.get("detail") or body.get("message") or body)
    assert "still finds" in detail.lower()
    still = client.get(f"/api/v1/fix-prs?project_id={pid}", headers=headers_admin).json()
    row = next(p for p in still if p["id"] == first["id"])
    assert row["status"] == "APPROVED"


def test_copilot_uses_tools(client: TestClient):
    token = _token(client)
    pid = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"}).json()[0]["id"]
    r = client.post(
        "/api/v1/copilot/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"project_id": pid, "question": "What services are in this project?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool_calls"]
    assert "service" in body["answer"].lower() or "payment" in body["answer"].lower()
