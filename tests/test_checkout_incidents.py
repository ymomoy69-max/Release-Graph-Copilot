"""Checkout incidents follow live shop payment failure mode."""
import uuid

import httpx
from sqlalchemy import select

from releasegraph.checkout_incidents import (
    checkout_incident_title,
    read_payment_failure_mode,
    sync_checkout_incidents_from_shop,
)
from releasegraph.database import SessionLocal
from releasegraph.models import Incident, IncidentEvent, IncidentStatus, Organization, Project, Service


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_read_payment_failure_mode_from_gateway_health():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "backends": {
                        "payment-service": {
                            "failure_mode": {"enabled": True, "latency_ms": 0},
                        }
                    }
                },
            )
        return httpx.Response(404)

    with _client(handler) as client:
        assert read_payment_failure_mode("http://gw", client=client) is True


def _checkout_incident_db():
    db = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    org = Organization(slug=f"checkout-sync-{tag}", name="Checkout Sync")
    db.add(org)
    db.flush()
    project = Project(organization_id=org.id, slug="shop", name="Shop", workspace_path="/tmp")
    db.add(project)
    db.flush()
    svc = Service(project_id=project.id, name="payment-service", source_path="payment")
    db.add(svc)
    db.flush()
    inc = Incident(
        project_id=project.id,
        title=checkout_incident_title(svc.name),
        status=IncidentStatus.OPEN,
        severity="critical",
        service_id=svc.id,
    )
    db.add(inc)
    db.flush()
    db.add(
        IncidentEvent(
            incident_id=inc.id,
            event_type="checkout_failed",
            message="HTTP 502",
            actor="test",
        )
    )
    db.commit()
    return db, project, inc


def test_sync_resolves_when_failure_mode_off():
    db, project, inc = _checkout_incident_db()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "backends": {
                        "payment-service": {
                            "failure_mode": {"enabled": False, "latency_ms": 0},
                        }
                    }
                },
            )
        return httpx.Response(404)

    with _client(handler) as http:
        out = sync_checkout_incidents_from_shop(db, project.id, "http://gw", http_client=http)
    assert out["resolved"] == 1
    db.commit()
    db.refresh(inc)
    assert inc.status == IncidentStatus.RESOLVED
    events = db.scalars(
        select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)
    ).all()
    assert any(e.event_type == "payments_restored" for e in events)
    db.rollback()
    db.close()


def test_sync_does_not_resolve_when_shop_down():
    db, project, inc = _checkout_incident_db()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with _client(handler) as http:
        out = sync_checkout_incidents_from_shop(db, project.id, "http://gw", http_client=http)
    assert out["resolved"] == 0
    db.refresh(inc)
    assert inc.status == IncidentStatus.OPEN
    db.rollback()
    db.close()
