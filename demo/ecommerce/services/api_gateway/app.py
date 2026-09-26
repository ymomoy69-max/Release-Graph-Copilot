"""api-gateway — HTTP facade for the demo storefront."""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from demo.ecommerce.common.config import (
    INVENTORY_SERVICE_URL,
    NOTIFICATION_SERVICE_URL,
    ORDER_SERVICE_URL,
    PAYMENT_SERVICE_URL,
    PRODUCT_SERVICE_URL,
    SERVICE_NAME,
)

app = FastAPI(title="api-gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8082",
        "http://localhost:8082",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _forward(method: str, url: str, request: Request) -> Response:
    body = await request.body()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(method, url, content=body, params=request.query_params)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))


@app.get("/health")
def health():
    out = {"status": "ok", "service": SERVICE_NAME or "api-gateway", "backends": {}}
    with httpx.Client(timeout=5.0) as c:
        for name, base in {
            "product-service": PRODUCT_SERVICE_URL,
            "inventory-service": INVENTORY_SERVICE_URL,
            "payment-service": PAYMENT_SERVICE_URL,
            "order-service": ORDER_SERVICE_URL,
            "notification-service": NOTIFICATION_SERVICE_URL,
        }.items():
            try:
                out["backends"][name] = c.get(f"{base}/health").json()
            except httpx.HTTPError as exc:
                out["backends"][name] = {"status": "down", "error": str(exc)}
    return out


@app.get("/products")
async def list_products(request: Request):
    return await _forward("GET", f"{PRODUCT_SERVICE_URL}/products", request)


@app.get("/products/{product_id}")
async def get_product(product_id: str, request: Request):
    return await _forward("GET", f"{PRODUCT_SERVICE_URL}/products/{product_id}", request)


@app.get("/inventory/{product_id}")
async def get_inventory(product_id: str, request: Request):
    return await _forward("GET", f"{INVENTORY_SERVICE_URL}/inventory/{product_id}", request)


@app.post("/orders")
async def create_order(request: Request):
    data = await request.json()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{ORDER_SERVICE_URL}/orders", json=data)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))


@app.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    return await _forward("GET", f"{ORDER_SERVICE_URL}/orders/{order_id}", request)


@app.post("/payments")
async def create_payment(request: Request):
    return await _forward("POST", f"{PAYMENT_SERVICE_URL}/payments", request)


@app.post("/admin/failure-mode")
async def failure_mode(request: Request):
    """Demo: break payment-service (for incident scenarios)."""
    data = await request.json()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{PAYMENT_SERVICE_URL}/admin/failure-mode", json=data)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))
