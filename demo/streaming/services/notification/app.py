"""notification-service — email and push for playback events."""
from __future__ import annotations

import uuid

from fastapi import FastAPI

from demo.streaming.common.config import SERVICE_NAME
from demo.streaming.common.schemas import NotificationRequest

app = FastAPI(title="notification-service", version="1.0.0")

_log: list[dict] = []


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME or "notification-service", "simulator": True}


@app.post("/notifications")
def send_notification(body: NotificationRequest):
    rec = {"id": uuid.uuid4().hex[:10], **body.model_dump(), "status": "queued"}
    _log.append(rec)
    return rec


@app.get("/notifications")
def list_notifications():
    return {"notifications": _log[-50:]}
