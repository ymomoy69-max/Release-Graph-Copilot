"""Live checkout failure: the incident is the shop response, not a pretend ticket."""
import json
import os

os.environ["DATABASE_URL"] = "sqlite:///./data/test_releasegraph.db"
os.environ["JWT_SECRET"] = "test-secret"

import httpx
import pytest
from fastapi.testclient import TestClient

from releasegraph.checkout_failure import (
    CheckoutDidNotFail,
    CheckoutProbe,
    ShopUnavailable,
    run_checkout_failure,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def client():
    from releasegraph.database import Base, engine, init_db
    from releasegraph.main import app
    from releasegraph.seed import seed

    Base.metadata.drop_all(bind=engine)
    init_db()
    seed(reset=True)
    return TestClient(app)


def test_probe_records_failed_checkout():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/admin/failure-mode":
            body = json.loads(request.content)
            assert body["enabled"] is True
            return httpx.Response(200, json={"ok": True, "enabled": True, "latency_ms": 0})
        if request.url.path == "/products":
            return httpx.Response(200, json={"products": [{"id": "sku-100", "name": "Test"}]})
        if request.url.path == "/orders":
            return httpx.Response(502, json={"detail": "Payment dependency failed"})
        return httpx.Response(404)

    with _client(handler) as client:
        probe = run_checkout_failure("http://shop", service_name="payment-service", client=client)

    assert probe.service == "payment-service"
    assert probe.http_status == 502
    assert probe.detail == "Payment dependency failed"
    assert probe.steps[0][0] == "failure_mode_enabled"
    assert "HTTP 502: Payment dependency failed" in probe.steps[1][1]


def test_probe_shop_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _client(handler) as client:
        with pytest.raises(ShopUnavailable, match="not reachable"):
            run_checkout_failure("http://shop", service_name="payment-service", client=client)


def test_probe_restores_payments_when_checkout_succeeds():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/admin/failure-mode":
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/products":
            return httpx.Response(200, json={"products": [{"id": "sku-100", "name": "Test"}]})
        if request.url.path == "/orders":
            return httpx.Response(200, json={"id": "abc", "status": "confirmed"})
        return httpx.Response(404)

    with _client(handler) as client:
        with pytest.raises(CheckoutDidNotFail, match="no incident was opened"):
            run_checkout_failure("http://shop", service_name="payment-service", client=client)

    assert calls[0]["enabled"] is True
    assert calls[1]["enabled"] is False


def test_api_opens_incident_from_probe(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "releasegraph.api.run_checkout_failure",
        lambda url, **kwargs: CheckoutProbe(
            service="payment-service",
            gateway="http://shop",
            product_id="sku-100",
            http_status=502,
            detail="Payment dependency failed",
            steps=(
                ("failure_mode_enabled", "Turned on payment-service failure mode through the shop gateway."),
                ("checkout_failed", "Gateway returned HTTP 502: Payment dependency failed"),
            ),
        ),
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.demo", "password": "admin123!"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.get("/api/v1/projects", headers=headers).json()[0]["id"]
    created = client.post(f"/api/v1/incidents/checkout-failure?project_id={pid}", headers=headers)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["service"] == "payment-service"
    assert body["reused"] is False
    assert "HTTP 502" in body["message"]
    detail = client.get(f"/api/v1/incidents/{body['incident_id']}", headers=headers).json()
    types = [e["type"] for e in detail["timeline"]]
    assert types == ["failure_mode_enabled", "checkout_failed"]
    assert "pretend" not in detail["title"].lower()

    again = client.post(f"/api/v1/incidents/checkout-failure?project_id={pid}", headers=headers)
    assert again.status_code == 200
    assert again.json()["reused"] is True
    assert again.json()["incident_id"] == body["incident_id"]
    detail = client.get(f"/api/v1/incidents/{body['incident_id']}", headers=headers).json()
    assert len(detail["timeline"]) == 4


def test_api_list_incidents_closes_checkout_when_payments_restored(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "releasegraph.checkout_incidents.read_payment_failure_mode",
        lambda url, **kwargs: False,
    )
    monkeypatch.setattr(
        "releasegraph.api.run_checkout_failure",
        lambda url, **kwargs: CheckoutProbe(
            service="payment-service",
            gateway="http://shop",
            product_id="sku-100",
            http_status=502,
            detail="fail",
            steps=(
                ("failure_mode_enabled", "on"),
                ("checkout_failed", "HTTP 502: fail"),
            ),
        ),
    )
    token = client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.demo", "password": "admin123!"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.get("/api/v1/projects", headers=headers).json()[0]["id"]
    created = client.post(f"/api/v1/incidents/checkout-failure?project_id={pid}", headers=headers)
    assert created.status_code == 200
    inc_id = created.json()["incident_id"]
    listed = client.get(f"/api/v1/incidents?project_id={pid}", headers=headers).json()
    row = next(i for i in listed if i["id"] == inc_id)
    assert row["status"] == "RESOLVED"


def test_api_does_not_invent_a_ticket_when_shop_is_down(client: TestClient, monkeypatch):
    def down(url: str, **kwargs):
        raise ShopUnavailable("Shop gateway is not reachable at http://shop.")

    monkeypatch.setattr("releasegraph.api.run_checkout_failure", down)
    token = client.post(
        "/api/v1/auth/login", json={"email": "admin@acme.demo", "password": "admin123!"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.get("/api/v1/projects", headers=headers).json()[0]["id"]
    before = client.get(f"/api/v1/incidents?project_id={pid}", headers=headers).json()
    failed = client.post(f"/api/v1/incidents/checkout-failure?project_id={pid}", headers=headers)
    assert failed.status_code == 424
    assert "not reachable" in failed.json()["message"]
    after = client.get(f"/api/v1/incidents?project_id={pid}", headers=headers).json()
    assert len(after) == len(before)
