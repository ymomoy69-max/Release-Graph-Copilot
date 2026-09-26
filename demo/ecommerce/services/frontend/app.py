"""frontend — storefront UI calling api-gateway."""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

GATEWAY = os.getenv("API_GATEWAY_URL", "http://127.0.0.1:8080")

app = FastAPI(title="frontend", version="1.0.0")

_SKIP_HEADERS = frozenset({"host", "content-length", "connection"})


async def _proxy_to_gateway(method: str, path: str, request: Request) -> Response:
    """Same-origin proxy so the browser is not blocked by cross-port CORS."""
    base = GATEWAY.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _SKIP_HEADERS
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method,
            url,
            content=body,
            headers=headers,
            params=request.query_params,
        )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
    )


@app.get("/products")
async def list_products(request: Request):
    return await _proxy_to_gateway("GET", "products", request)


@app.post("/orders")
async def create_order(request: Request):
    return await _proxy_to_gateway("POST", "orders", request)


@app.post("/admin/failure-mode")
async def failure_mode(request: Request):
    return await _proxy_to_gateway("POST", "admin/failure-mode", request)


_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Acme Shop</title>
  <style>
    :root {{
      --primary: #2663EB; --navy: #0E172A; --bg: #F9FAFB; --panel: #FFFFFF;
      --border: #E6E7EB; --text: #0E172A; --muted: #6B7280; --accent: #2663EB;
      --ok: #16A34A; --err: #DC2626;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, sans-serif; margin: 0; background: var(--bg); color: var(--text);
    }}
    header {{
      padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border); background: var(--navy); color: #fff;
      display: flex; justify-content: space-between; align-items: baseline;
    }}
    header .muted {{ color: #93A3B8; }}
    main {{ max-width: 760px; margin: 0 auto; padding: 1.5rem; }}
    .card {{
      background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
      padding: 1.1rem 1.2rem; margin: 1rem 0; box-shadow: 0 1px 2px rgba(14,23,42,0.05);
    }}
    button {{
      background: var(--accent); color: white; border: none; border-radius: 8px;
      padding: 0.55rem 1rem; cursor: pointer; font-weight: 600; min-height: 36px;
      margin-right: 0.5rem;
    }}
    button:disabled {{ opacity: 0.55; cursor: not-allowed; }}
    button.ghost {{ background: #fff; color: var(--navy); border: 1px solid var(--border); }}
    .err {{ color: var(--err); }}
    .ok {{ color: var(--ok); }}
    label {{ display: block; margin-top: 0.7rem; color: var(--muted); font-size: 0.85rem; }}
    input {{
      width: 100%; margin-top: 0.25rem; padding: 0.5rem 0.7rem; border-radius: 8px;
      border: 1px solid var(--border); background: #fff; color: var(--text);
    }}
    .product {{
      display: flex; justify-content: space-between; padding: 0.55rem 0;
      border-bottom: 1px solid var(--border);
    }}
    .muted {{ color: var(--muted); font-size: 0.85rem; }}
    pre {{ white-space: pre-wrap; font-size: 0.82rem; }}
    .row {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.75rem; }}
  </style>
</head>
<body>
  <header>
    <strong>Acme Shop</strong>
    <span class="muted">Demo microservices · simulator</span>
  </header>
  <main>
    <p class="muted">This page calls the API on the same host (proxied to <code>api-gateway</code> at {GATEWAY}).</p>
    <div id="products" class="card">Loading products…</div>
    <div class="card">
      <h2>Place order</h2>
      <label>Product ID <input id="pid" value="sku-100" /></label>
      <label>Email <input id="email" value="buyer@acme.demo" /></label>
      <button id="order-btn" type="button" style="margin-top:1rem">Place order</button>
      <pre id="order-out"></pre>
    </div>
    <div class="card">
      <h2>Incident simulation</h2>
      <p class="muted">Breaks payment-service so checkout fails — use this with ReleaseGraph Copilot.</p>
      <div class="row">
        <button type="button" id="fail-on">Enable payment failure</button>
        <button type="button" class="ghost" id="fail-off">Restore payments</button>
      </div>
      <p id="fail-msg" class="muted"></p>
    </div>
  </main>
  <script>
    async function api(path, options) {{
      const r = await fetch(path, options);
      const text = await r.text();
      return {{ ok: r.ok, status: r.status, text }};
    }}

    function setBusy(busy) {{
      for (const id of ["order-btn", "fail-on", "fail-off"]) {{
        const el = document.getElementById(id);
        if (el) el.disabled = busy;
      }}
    }}

    async function loadProducts() {{
      const box = document.getElementById("products");
      try {{
        const r = await api("/products");
        if (!r.ok) throw new Error("HTTP " + r.status + ": " + r.text);
        const d = JSON.parse(r.text);
        box.innerHTML =
          "<h2>Catalog</h2>" + (d.products || []).map(p =>
            `<div class="product"><span>${{p.name}}</span><span>$${{p.price}} · <code>${{p.id}}</code></span></div>`
          ).join("");
      }} catch (e) {{
        box.innerHTML = "<p class=\\"err\\">Could not load catalog: " + e.message + "</p>";
      }}
    }}

    document.getElementById("order-btn").addEventListener("click", async () => {{
      const out = document.getElementById("order-out");
      out.textContent = "Placing order…";
      out.className = "";
      setBusy(true);
      try {{
        const r = await api("/orders", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            product_id: document.getElementById("pid").value,
            quantity: 1,
            customer_email: document.getElementById("email").value,
          }}),
        }});
        out.textContent = r.ok ? r.text : "ERROR " + r.status + ": " + r.text;
        out.className = r.ok ? "ok" : "err";
      }} catch (e) {{
        out.textContent = "Request failed: " + e.message;
        out.className = "err";
      }} finally {{
        setBusy(false);
      }}
    }});

    async function setFailureMode(enabled) {{
      const msg = document.getElementById("fail-msg");
      msg.textContent = enabled ? "Turning failure mode on…" : "Restoring payments…";
      msg.className = "muted";
      setBusy(true);
      try {{
        const r = await api("/admin/failure-mode", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ enabled, latency_ms: enabled ? 0 : 0 }}),
        }});
        if (!r.ok) throw new Error("HTTP " + r.status + ": " + r.text);
        msg.textContent = enabled
          ? "Payment failure mode ON — the next checkout should fail."
          : "Payments restored — checkout should work again.";
        msg.className = "ok";
      }} catch (e) {{
        msg.textContent = "Could not reach payment admin: " + e.message;
        msg.className = "err";
      }} finally {{
        setBusy(false);
      }}
    }}

    document.getElementById("fail-on").addEventListener("click", () => setFailureMode(true));
    document.getElementById("fail-off").addEventListener("click", () => setFailureMode(false));
    loadProducts();
  </script>
</body>
</html>"""


@app.get("/health")
def health():
    return {"status": "ok", "service": "frontend", "gateway": GATEWAY}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_HTML)
