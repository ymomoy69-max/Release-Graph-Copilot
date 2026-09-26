"""recommendation-service — personalized rows for the catalog."""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from demo.streaming.common.config import CONTENT_SERVICE_URL, SERVICE_NAME

app = FastAPI(title="recommendation-service", version="1.0.0")


@app.get("/health")
def health():
    upstream = "ok"
    try:
        with httpx.Client(timeout=5.0) as c:
            upstream = c.get(f"{CONTENT_SERVICE_URL}/health").json().get("status", "ok")
    except httpx.HTTPError:
        upstream = "down"
    return {
        "status": "ok",
        "service": SERVICE_NAME or "recommendation-service",
        "content-service": upstream,
    }


@app.get("/recommendations")
def recommendations(profile_id: str = "default"):
    with httpx.Client(timeout=10.0) as c:
        titles = c.get(f"{CONTENT_SERVICE_URL}/titles").json().get("titles", [])
    ordered = sorted(titles, key=lambda t: t.get("name", ""), reverse=True)
    return {"profile_id": profile_id, "rows": [{"label": "For you", "titles": ordered}]}
