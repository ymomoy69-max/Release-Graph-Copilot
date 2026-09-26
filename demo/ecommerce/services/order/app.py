"""order-service — orchestrates inventory, payment, and notifications."""
from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI, HTTPException

from demo.ecommerce.common.config import (
    INVENTORY_SERVICE_URL,
    NOTIFICATION_SERVICE_URL,
    PAYMENT_SERVICE_URL,
    PRODUCT_SERVICE_URL,
    SERVICE_NAME,
)
from demo.ecommerce.common.schemas import OrderRequest

app = FastAPI(title="order-service", version="1.0.0")

_orders: dict[str, dict] = {}


def _client() -> httpx.Client:
    return httpx.Client(timeout=10.0)


@app.get("/health")
def health():
    deps = {}
    with _client() as c:
        for name, url in [
            ("product-service", PRODUCT_SERVICE_URL),
            ("inventory-service", INVENTORY_SERVICE_URL),
            ("payment-service", PAYMENT_SERVICE_URL),
            ("notification-service", NOTIFICATION_SERVICE_URL),
        ]:
            try:
                r = c.get(f"{url}/health")
                deps[name] = r.json()
            except httpx.HTTPError as exc:
                deps[name] = {"status": "down", "error": str(exc)}
    return {"status": "ok", "service": SERVICE_NAME or "order-service", "dependencies": deps}


@app.post("/orders")
def create_order(body: OrderRequest):
    with _client() as c:
        pr = c.get(f"{PRODUCT_SERVICE_URL}/products/{body.product_id}")
        if pr.status_code == 404:
            raise HTTPException(status_code=404, detail="Product not found")
        pr.raise_for_status()
        product = pr.json()

        ir = c.post(
            f"{INVENTORY_SERVICE_URL}/inventory/reserve",
            params={"product_id": body.product_id, "quantity": body.quantity},
        )
        if ir.status_code == 409:
            raise HTTPException(status_code=409, detail="Out of stock")
        ir.raise_for_status()

        oid = uuid.uuid4().hex[:12]
        amount = float(product["price"]) * body.quantity
        order = {
            "id": oid,
            "product_id": body.product_id,
            "quantity": body.quantity,
            "amount": amount,
            "customer_email": str(body.customer_email),
            "status": "created",
        }
        _orders[oid] = order

        pay = c.post(
            f"{PAYMENT_SERVICE_URL}/payments",
            json={"order_id": oid, "amount": amount, "currency": "USD"},
        )
        if pay.status_code >= 400:
            order["status"] = "payment_failed"
            _orders[oid] = order
            c.post(
                f"{INVENTORY_SERVICE_URL}/inventory/release",
                params={"product_id": body.product_id, "quantity": body.quantity},
            )
            raise HTTPException(status_code=502, detail="Payment dependency failed")

        payment = pay.json()
        order["payment_id"] = payment["id"]
        order["status"] = "confirmed"
        _orders[oid] = order

        try:
            c.post(
                f"{NOTIFICATION_SERVICE_URL}/notifications",
                json={
                    "channel": "email",
                    "to": str(body.customer_email),
                    "body": f"Order {oid} confirmed for {product['name']}",
                },
            )
        except Exception: pass

    return order


@app.get("/orders")
def list_orders():
    return {"orders": list(_orders.values())}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    if order_id not in _orders:
        raise HTTPException(status_code=404, detail="Order not found")
    return _orders[order_id]
