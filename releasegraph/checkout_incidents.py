"""Keep checkout-failure incidents in sync with live shop payment failure mode."""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from releasegraph.models import Incident, IncidentEvent, IncidentStatus, User

CHECKOUT_PREFIX = "Checkout failed:"


def checkout_incident_title(service_name: str) -> str:
    return f"{CHECKOUT_PREFIX} {service_name} rejected the charge"


def read_payment_failure_mode(
    gateway_url: str,
    *,
    client: httpx.Client | None = None,
) -> bool | None:
    """True/False when the gateway reports payment failure mode; None if unknown or shop down."""
    base = gateway_url.rstrip("/")
    owns = client is None
    http = client or httpx.Client(timeout=5.0)
    try:
        resp = http.get(f"{base}/health")
        resp.raise_for_status()
        data = resp.json()
        payment = (data.get("backends") or {}).get("payment-service")
        if not isinstance(payment, dict):
            return None
        failure = payment.get("failure_mode")
        if isinstance(failure, dict) and "enabled" in failure:
            return bool(failure["enabled"])
        return None
    except httpx.HTTPError:
        return None
    finally:
        if owns:
            http.close()


def sync_checkout_incidents_from_shop(
    db: Session,
    project_id: int,
    gateway_url: str,
    *,
    actor: User | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, int | bool | None]:
    """Resolve open checkout incidents when payment failure mode is off in the running shop."""
    failure_on = read_payment_failure_mode(gateway_url, client=http_client)
    if failure_on is not False:
        return {"resolved": 0, "payment_failure_mode": failure_on}

    open_rows = db.scalars(
        select(Incident).where(
            Incident.project_id == project_id,
            Incident.title.startswith(CHECKOUT_PREFIX),
            Incident.status != IncidentStatus.RESOLVED,
        )
    ).all()
    resolved = 0
    for inc in open_rows:
        inc.status = IncidentStatus.RESOLVED
        db.add(
            IncidentEvent(
                incident_id=inc.id,
                event_type="payments_restored",
                message=(
                    "Shop payment failure mode is off (restored in the storefront). "
                    "Checkout can succeed again."
                ),
                actor=actor.email if actor else "shop-sync",
            )
        )
        resolved += 1
    return {"resolved": resolved, "payment_failure_mode": False}
