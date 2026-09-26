"""content-service — catalog titles and metadata."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from demo.streaming.common.config import SERVICE_NAME

app = FastAPI(title="content-service", version="1.0.0")

_TITLES = {
    "title-aurora": {"id": "title-aurora", "name": "Aurora Falls", "tier": "premium", "minutes": 112},
    "title-neon": {"id": "title-neon", "name": "Neon Harbor", "tier": "standard", "minutes": 94},
    "title-drift": {"id": "title-drift", "name": "Drift Protocol", "tier": "premium", "minutes": 128},
}


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME or "content-service", "simulator": True}


@app.get("/titles")
def list_titles():
    return {"titles": list(_TITLES.values())}


@app.get("/titles/{title_id}")
def get_title(title_id: str):
    if title_id not in _TITLES:
        raise HTTPException(status_code=404, detail="Title not found")
    return _TITLES[title_id]
