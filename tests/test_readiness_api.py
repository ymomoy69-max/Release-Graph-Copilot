import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_readiness.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient

from releasegraph.database import Base, engine, init_db
from releasegraph.main import app
from releasegraph.seed import seed


def test_readiness_preset_safe_go():
    Base.metadata.drop_all(bind=engine)
    init_db()
    seed(reset=True)
    client = TestClient(app)
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@acme.demo", "password": "admin123!"},
    ).json()["access_token"]
    r = client.post(
        "/api/v1/readiness/check",
        headers={"Authorization": f"Bearer {token}"},
        json={"preset": "safe-go"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ready_to_release"] is True
    assert body["checklist"]["verdict"] == "go"
