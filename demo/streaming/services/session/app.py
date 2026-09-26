"""session-service — orchestrates entitlement, billing, and notifications for playback."""
from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI, HTTPException

from demo.streaming.common.config import (
    BILLING_SERVICE_URL,
    CONTENT_SERVICE_URL,
    ENTITLEMENT_SERVICE_URL,
    NOTIFICATION_SERVICE_URL,
    SERVICE_NAME,
)
from demo.streaming.common.schemas import SessionRequest

app = FastAPI(title="session-service", version="1.0.0")

_sessions: dict[str, dict] = {}


def _client() -> httpx.Client:
    return httpx.Client(timeout=10.0)


@app.get("/health")
def health():
    deps = {}
    with _client() as c:
        for name, url in [
            ("content-service", CONTENT_SERVICE_URL),
            ("entitlement-service", ENTITLEMENT_SERVICE_URL),
            ("billing-service", BILLING_SERVICE_URL),
            ("notification-service", NOTIFICATION_SERVICE_URL),
        ]:
            try:
                deps[name] = c.get(f"{url}/health").json()
            except httpx.HTTPError as exc:
                deps[name] = {"status": "down", "error": str(exc)}
    return {"status": "ok", "service": SERVICE_NAME or "session-service", "dependencies": deps}


@app.post("/sessions")
def start_session(body: SessionRequest):
    with _client() as c:
        tr = c.get(f"{CONTENT_SERVICE_URL}/titles/{body.title_id}")
        if tr.status_code == 404:
            raise HTTPException(status_code=404, detail="Title not found")
        title = tr.json()
        er = c.post(f"{ENTITLEMENT_SERVICE_URL}/entitlements/reserve", params={"profile_id": body.profile_id})
        if er.status_code >= 400:
            raise HTTPException(status_code=409, detail="Cannot reserve stream slot")
        amount = 9.99 if title.get("tier") == "premium" else 4.99
        br = c.post(
            f"{BILLING_SERVICE_URL}/billing/charges",
            json={"session_id": "pending", "amount": amount, "currency": "USD"},
        )
        if br.status_code >= 400:
            c.post(
                f"{ENTITLEMENT_SERVICE_URL}/entitlements/release",
                params={"profile_id": body.profile_id},
            )
            raise HTTPException(status_code=503, detail="Billing failed")
        sid = uuid.uuid4().hex[:12]
        session = {
            "id": sid,
            "title_id": body.title_id,
            "profile_id": body.profile_id,
            "status": "playing",
            "charge": br.json(),
        }
        _sessions[sid] = session
        c.post(
            f"{NOTIFICATION_SERVICE_URL}/notifications",
            json={
                "channel": "email",
                "to": str(body.customer_email),
                "body": f"Playback started: {title.get('name')} ({sid})",
            },
        )
    return session


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return _sessions[session_id]
