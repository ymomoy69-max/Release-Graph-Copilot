"""entitlement-service — viewing rights and concurrent stream slots."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from demo.streaming.common.config import SERVICE_NAME

app = FastAPI(title="entitlement-service", version="1.0.0")

_SLOTS: dict[str, int] = {"default": 2, "family": 4}
_ACTIVE: dict[str, int] = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME or "entitlement-service", "simulator": True}


@app.get("/entitlements/{profile_id}")
def get_entitlements(profile_id: str):
    return {
        "profile_id": profile_id,
        "max_streams": _SLOTS.get(profile_id, 1),
        "active_streams": _ACTIVE.get(profile_id, 0),
        "plans": ["standard", "premium"],
    }


@app.post("/entitlements/reserve")
def reserve_stream(profile_id: str):
    limit = _SLOTS.get(profile_id, 1)
    used = _ACTIVE.get(profile_id, 0)
    if used >= limit:
        raise HTTPException(status_code=409, detail="Concurrent stream limit reached")
    _ACTIVE[profile_id] = used + 1
    return {"profile_id": profile_id, "active_streams": _ACTIVE[profile_id]}


@app.post("/entitlements/release")
def release_stream(profile_id: str):
    used = max(0, _ACTIVE.get(profile_id, 0) - 1)
    _ACTIVE[profile_id] = used
    return {"profile_id": profile_id, "active_streams": used}
