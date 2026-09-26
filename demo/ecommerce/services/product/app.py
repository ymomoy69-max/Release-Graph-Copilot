"""product-service — catalog API."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from demo.ecommerce.common.config import SERVICE_NAME

app = FastAPI(title="product-service", version="1.0.0")

_PRODUCTS = [
    {"id": "sku-100", "name": "Wireless Headphones", "price": 79.99},
    {"id": "sku-200", "name": "USB-C Hub", "price": 34.5},
]


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME or "product-service", "simulator": True}


@app.get("/products")
def list_products():
    return {"products": _PRODUCTS}


@app.get("/products/{product_id}")
def get_product(product_id: str):
    for p in _PRODUCTS:
        if p["id"] == product_id:
            return p
    raise HTTPException(status_code=404, detail="Product not found")
