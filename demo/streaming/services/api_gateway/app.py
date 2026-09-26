"""api-gateway — HTTP facade for the streaming demo."""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from demo.streaming.common.config import (
    BILLING_SERVICE_URL,
    CONTENT_SERVICE_URL,
    ENTITLEMENT_SERVICE_URL,
    NOTIFICATION_SERVICE_URL,
    RECOMMENDATION_SERVICE_URL,
    SESSION_SERVICE_URL,
    SERVICE_NAME,
)

app = FastAPI(title="api-gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8092", "http://localhost:8092"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _forward(method: str, url: str, request: Request) -> Response:
    body = await request.body()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.request(method, url, content=body, params=request.query_params)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))


@app.get("/health")
def health():
    out = {"status": "ok", "service": SERVICE_NAME or "api-gateway", "backends": {}}
    with httpx.Client(timeout=5.0) as c:
        for name, base in {
            "content-service": CONTENT_SERVICE_URL,
            "entitlement-service": ENTITLEMENT_SERVICE_URL,
            "billing-service": BILLING_SERVICE_URL,
            "session-service": SESSION_SERVICE_URL,
            "notification-service": NOTIFICATION_SERVICE_URL,
            "recommendation-service": RECOMMENDATION_SERVICE_URL,
        }.items():
            try:
                out["backends"][name] = c.get(f"{base}/health").json()
            except httpx.HTTPError as exc:
                out["backends"][name] = {"status": "down", "error": str(exc)}
    return out


@app.get("/titles")
async def list_titles(request: Request):
    return await _forward("GET", f"{CONTENT_SERVICE_URL}/titles", request)


@app.get("/titles/{title_id}")
async def get_title(title_id: str, request: Request):
    return await _forward("GET", f"{CONTENT_SERVICE_URL}/titles/{title_id}", request)


@app.get("/recommendations")
async def recommendations(request: Request):
    return await _forward("GET", f"{RECOMMENDATION_SERVICE_URL}/recommendations", request)


@app.get("/entitlements/{profile_id}")
async def entitlements(profile_id: str, request: Request):
    return await _forward("GET", f"{ENTITLEMENT_SERVICE_URL}/entitlements/{profile_id}", request)


@app.post("/sessions")
async def create_session(request: Request):
    data = await request.json()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{SESSION_SERVICE_URL}/sessions", json=data)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    return await _forward("GET", f"{SESSION_SERVICE_URL}/sessions/{session_id}", request)


@app.post("/admin/failure-mode")
async def failure_mode(request: Request):
    data = await request.json()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{BILLING_SERVICE_URL}/admin/failure-mode", json=data)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))
