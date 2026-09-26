"""payment-service — charges with demo failure mode."""
from __future__ import annotations

import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException

from demo.ecommerce.common.config import SERVICE_NAME
from demo.ecommerce.common.schemas import FailureMode, PaymentRequest

app = FastAPI(title="payment-service", version="1.0.0")

# Intentional demo defect: processor credential in source (scanner: hardcoded_secret).
WEBHOOK_SECRET = "whsec_demo_hardcoded_rotate_me"

_failure = {"enabled": False, "latency_ms": 0}
_payments: dict[str, dict] = {}


def _processor_client() -> httpx.Client:
    # Intentional demo defect: outbound client with no timeout (scanner: http_no_timeout).
    return httpx.Client()


@app.get("/health")
def health():
    return {
        "status": "ok" if not _failure["enabled"] else "degraded",
        "service": SERVICE_NAME or "payment-service",
        "simulator": True,
        "failure_mode": _failure,
    }


@app.post("/admin/failure-mode")
def set_failure_mode(body: FailureMode):
    _failure["enabled"] = body.enabled
    _failure["latency_ms"] = max(0, body.latency_ms)
    return {"ok": True, ** _failure}


@app.post("/payments")
def create_payment(body: PaymentRequest):
    if _failure["latency_ms"]:
        time.sleep(_failure["latency_ms"] / 1000.0)
    if _failure["enabled"]:
        raise HTTPException(status_code=503, detail="Payment service failure (demo mode)")
    pid = uuid.uuid4().hex[:12]
    rec = {"id": pid, "status": "succeeded", **body.model_dump()}
    _payments[pid] = rec
    return rec


@app.get("/payments")
def list_payments():
    return {"payments": list(_payments.values())}


@app.get("/payments/{payment_id}")
def get_payment(payment_id: str):
    if payment_id not in _payments:
        raise HTTPException(status_code=404, detail="Payment not found")
    return _payments[payment_id]
