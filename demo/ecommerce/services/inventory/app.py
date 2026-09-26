"""inventory-service — stock levels and reservations."""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException

from demo.ecommerce.common.config import SERVICE_NAME

app = FastAPI(title="inventory-service", version="1.0.0")

_INVENTORY: dict[str, int] = {"sku-100": 50, "sku-200": 120}


# DEMO-SCAN
def _warehouse_client() -> httpx.Client:
    return httpx.Client()


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME or "inventory-service", "simulator": True}


@app.get("/inventory/{product_id}")
def get_inventory(product_id: str):
    return {"product_id": product_id, "available": _INVENTORY.get(product_id, 0)}


@app.post("/inventory/reserve")
def reserve_inventory(product_id: str, quantity: int = 1):
    avail = _INVENTORY.get(product_id, 0)
    if avail < quantity:
        raise HTTPException(status_code=409, detail="Insufficient inventory")
    _INVENTORY[product_id] = avail - quantity
    return {"reserved": quantity, "remaining": _INVENTORY[product_id]}


@app.post("/inventory/release")
def release_inventory(product_id: str, quantity: int = 1):
    _INVENTORY[product_id] = _INVENTORY.get(product_id, 0) + quantity
    return {"released": quantity, "available": _INVENTORY[product_id]}
