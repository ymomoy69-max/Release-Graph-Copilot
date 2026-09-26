"""Place one live shop order after turning payment failure on.

The incident timeline is the gateway response. This does not invent a ticket
when the shop is down or when checkout succeeds.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx


class ShopUnavailable(Exception):
    """The shop gateway could not be called."""


class CheckoutDidNotFail(Exception):
    """The order went through, so there is no failed checkout to record."""


@dataclass(frozen=True)
class CheckoutProbe:
    service: str
    gateway: str
    product_id: str
    http_status: int
    detail: str
    steps: tuple[tuple[str, str], ...]


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("detail"):
        return str(body["detail"])
    text = (response.text or "").strip()
    return text[:500] or response.reason_phrase


def _first_product_id(http: httpx.Client, base: str) -> str:
    try:
        resp = http.get(f"{base}/products")
        resp.raise_for_status()
        products = resp.json().get("products") or []
        if products and isinstance(products[0], dict) and products[0].get("id"):
            return str(products[0]["id"])
    except httpx.HTTPError:
        pass
    raise ShopUnavailable(
        f"Could not load a product from {base}/products. "
        "Start the shop stack and ensure the catalog endpoint responds."
    )


def run_checkout_failure(
    gateway_url: str,
    *,
    service_name: str,
    customer_email: str = "checkout-probe@releasegraph.local",
    client: httpx.Client | None = None,
) -> CheckoutProbe:
    """Enable payment failure, place one order, and return the failed checkout."""
    base = gateway_url.rstrip("/")
    owns_client = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        try:
            health = http.get(f"{base}/health")
            health.raise_for_status()
        except httpx.HTTPError as exc:
            raise ShopUnavailable(
                f"Shop gateway is not reachable at {base}. "
                "Start it with: python demo/ecommerce/run_all.py"
            ) from exc

        product_id = _first_product_id(http, base)

        try:
            mode = http.post(
                f"{base}/admin/failure-mode",
                json={"enabled": True, "latency_ms": 0},
            )
            mode.raise_for_status()
        except httpx.HTTPError as exc:
            raise ShopUnavailable(
                f"Could not turn on payment failure mode at {base}/admin/failure-mode."
            ) from exc

        order = http.post(
            f"{base}/orders",
            json={
                "product_id": product_id,
                "quantity": 1,
                "customer_email": customer_email,
            },
        )
        detail = _detail(order)
        if order.status_code < 400:
            try:
                http.post(
                    f"{base}/admin/failure-mode",
                    json={"enabled": False, "latency_ms": 0},
                )
            except httpx.HTTPError:
                pass
            raise CheckoutDidNotFail(
                f"Checkout succeeded (HTTP {order.status_code}), so no incident was opened. "
                "Payments were restored."
            )

        steps = (
            (
                "failure_mode_enabled",
                f"Turned on failure mode for {service_name} through the shop gateway. "
                "The next charge is rejected.",
            ),
            (
                "checkout_failed",
                f"Placed order {product_id} for {customer_email}. "
                f"Gateway returned HTTP {order.status_code}: {detail}",
            ),
        )
        return CheckoutProbe(
            service=service_name,
            gateway=base,
            product_id=product_id,
            http_status=order.status_code,
            detail=detail,
            steps=steps,
        )
    finally:
        if owns_client:
            http.close()
