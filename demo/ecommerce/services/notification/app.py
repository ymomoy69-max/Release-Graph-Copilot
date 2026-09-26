"""notification-service — email/SMS simulation."""
from __future__ import annotations

import random
import uuid

from fastapi import FastAPI, HTTPException

from demo.ecommerce.common.config import SERVICE_NAME
from demo.ecommerce.common.schemas import NotificationRequest

app = FastAPI(title="notification-service", version="1.0.0")

_notifications: dict[str, dict] = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME or "notification-service", "simulator": True}


@app.post("/notifications")
def send_notification(body: NotificationRequest):
    nid = uuid.uuid4().hex[:12]
    status = "sent" if random.random() > 0.05 else "failed"
    rec = {"id": nid, "status": status, **body.model_dump()}
    _notifications[nid] = rec
    return rec


@app.get("/notifications/{notification_id}")
def get_notification(notification_id: str):
    if notification_id not in _notifications:
        raise HTTPException(status_code=404, detail="Notification not found")
    return _notifications[notification_id]
