"""frontend — streaming catalog UI calling api-gateway."""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

GATEWAY = os.getenv("API_GATEWAY_URL", "http://127.0.0.1:8090")

app = FastAPI(title="frontend", version="1.0.0")

_SKIP_HEADERS = frozenset({"host", "content-length", "connection"})


async def _proxy_to_gateway(method: str, path: str, request: Request) -> Response:
    base = GATEWAY.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_HEADERS}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(method, url, content=body, headers=headers, params=request.query_params)
    return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "frontend", "gateway": GATEWAY}


@app.api_route("/titles", methods=["GET"])
@app.api_route("/titles/{path:path}", methods=["GET"])
@app.api_route("/recommendations", methods=["GET"])
@app.api_route("/sessions", methods=["POST"])
@app.api_route("/sessions/{path:path}", methods=["GET"])
@app.api_route("/admin/failure-mode", methods=["POST"])
async def proxy(request: Request, path: str = ""):
    full = request.url.path.lstrip("/")
    return await _proxy_to_gateway(request.method, full, request)


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>StreamGraph Demo</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
    button { margin: 0.25rem 0.5rem 0.25rem 0; }
    pre { background: #111; color: #eee; padding: 1rem; overflow: auto; }
    .err { color: #c00; }
  </style>
</head>
<body>
  <h1>StreamGraph catalog</h1>
  <p>Microservices: content, entitlement, billing, session, notification, recommendation, gateway.</p>
  <button id="load">Load titles</button>
  <button id="recs">Load recommendations</button>
  <button id="break">Break billing (demo)</button>
  <button id="fix">Restore billing</button>
  <div id="out"></div>
  <script>
    const out = document.getElementById('out');
    async function j(url, opts) {
      const r = await fetch(url, opts);
      const t = await r.text();
      let body;
      try { body = JSON.parse(t); } catch { body = t; }
      if (!r.ok) throw new Error(typeof body === 'string' ? body : JSON.stringify(body));
      return body;
    }
    document.getElementById('load').onclick = async () => {
      try { out.innerHTML = '<pre>' + JSON.stringify(await j('/titles'), null, 2) + '</pre>'; }
      catch (e) { out.innerHTML = '<p class="err">' + e.message + '</p>'; }
    };
    document.getElementById('recs').onclick = async () => {
      try { out.innerHTML = '<pre>' + JSON.stringify(await j('/recommendations'), null, 2) + '</pre>'; }
      catch (e) { out.innerHTML = '<p class="err">' + e.message + '</p>'; }
    };
    async function billingMode(enabled) {
      await j('/admin/failure-mode', { method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ enabled, latency_ms: 0 }) });
      out.innerHTML = '<p>Billing failure mode: ' + (enabled ? 'ON' : 'OFF') + '</p>';
    }
    document.getElementById('break').onclick = () => billingMode(true);
    document.getElementById('fix').onclick = () => billingMode(false);
  </script>
</body>
</html>"""
