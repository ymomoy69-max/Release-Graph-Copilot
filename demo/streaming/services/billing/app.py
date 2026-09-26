"""billing-service — subscription charges with demo failure mode."""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, HTTPException

from demo.streaming.common.config import SERVICE_NAME
from demo.streaming.common.schemas import BillingRequest, FailureMode

app = FastAPI(title="billing-service", version="1.0.0")

_failure = {"enabled": False, "latency_ms": 0}
_charges: dict[str, dict] = {}


@app.get("/health")
def health():
    return {
        "status": "ok" if not _failure["enabled"] else "degraded",
        "service": SERVICE_NAME or "billing-service",
        "simulator": True,
        "failure_mode": _failure,
    }


@app.post("/admin/failure-mode")
def set_failure_mode(body: FailureMode):
    _failure["enabled"] = body.enabled
    _failure["latency_ms"] = max(0, body.latency_ms)
    return {"ok": True, **_failure}


@app.post("/billing/charges")
def create_charge(body: BillingRequest):
    if _failure["latency_ms"]:
        time.sleep(_failure["latency_ms"] / 1000.0)
    if _failure["enabled"]:
        raise HTTPException(status_code=503, detail="Billing service failure (demo mode)")
    cid = uuid.uuid4().hex[:12]
    rec = {"id": cid, "status": "succeeded", **body.model_dump()}
    _charges[cid] = rec
    return rec


@app.get("/billing/charges")
def list_charges():
    return {"charges": list(_charges.values())}
