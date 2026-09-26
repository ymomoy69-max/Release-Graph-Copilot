"""Live demo shop status from gateway health."""
from __future__ import annotations

from releasegraph.checkout_incidents import read_payment_failure_mode
from releasegraph.config import settings


def shop_status_payload() -> dict[str, str | bool | None]:
    gateway = settings.shop_gateway_url.rstrip("/")
    mode = read_payment_failure_mode(gateway)
    storefront = getattr(settings, "shop_storefront_url", None) or "http://127.0.0.1:8082"
    if mode is True:
        payment_label = "failure_on"
    elif mode is False:
        payment_label = "ok"
    else:
        payment_label = "unknown"
    return {
        "gateway_url": gateway,
        "storefront_url": storefront,
        "payment_failure_mode": mode,
        "payment_status": payment_label,
    }
