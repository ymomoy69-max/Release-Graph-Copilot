import os

os.environ["DATABASE_URL"] = "sqlite:///./data/test_releasegraph.db"
os.environ["JWT_SECRET"] = "test-secret"

import pytest
from fastapi.testclient import TestClient

from releasegraph.database import Base, engine, init_db
from releasegraph.main import app
from releasegraph.seed import seed


@pytest.fixture(scope="module", autouse=True)
def _db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    seed(reset=True)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _auth(client: TestClient) -> tuple[str, int]:
    token = client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.demo", "password": "admin123!"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pid = next(
        p["id"] for p in client.get("/api/v1/projects", headers=headers).json() if p["slug"] == "ecommerce"
    )
    return token, pid


def test_baseline_release_from_scan(client: TestClient):
    token, pid = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}
    train = client.get(f"/api/v1/release-train?project_id={pid}", headers=headers).json()
    assert train["production_version"] == "1.0.0"
    assert train["production_release_id"]
    assert train["draft_release_id"] is None
    assert train["can_start_next"] is True


def test_next_deploy_and_rollback(client: TestClient, monkeypatch):
    monkeypatch.setattr("releasegraph.release_train._deploy_block_reason", lambda _project: None)
    token, pid = _auth(client)
    headers = {"Authorization": f"Bearer {token}"}

    nxt = client.post(f"/api/v1/releases/next?project_id={pid}", headers=headers, json={})
    assert nxt.status_code == 200, nxt.text
    draft = nxt.json()
    assert draft["version"] == "1.0.1"
    assert draft["baseline_version"] == "1.0.0"
    assert draft["status"] == "DRAFT"

    ready = client.post(f"/api/v1/releases/{draft['id']}/mark-ready", headers=headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY"

    deploy = client.post(
        f"/api/v1/releases/{draft['id']}/deploy",
        headers=headers,
        json={"confirm": True, "environment_slug": "production"},
    )
    assert deploy.status_code == 200, deploy.text
    assert deploy.json()["version"] == "1.0.1"
    assert deploy.json()["previous_production_version"] == "1.0.0"

    train = client.get(f"/api/v1/release-train?project_id={pid}", headers=headers).json()
    assert train["production_version"] == "1.0.1"
    assert train["can_start_next"] is True

    rollback = client.post(
        f"/api/v1/releases/{draft['id']}/rollback",
        headers=headers,
        json={"confirm": True},
    )
    assert rollback.status_code == 200, rollback.text
    body = rollback.json()
    assert body["production_version"] == "1.0.0"
    assert body["rolled_back_version"] == "1.0.1"

    train = client.get(f"/api/v1/release-train?project_id={pid}", headers=headers).json()
    assert train["production_version"] == "1.0.0"
