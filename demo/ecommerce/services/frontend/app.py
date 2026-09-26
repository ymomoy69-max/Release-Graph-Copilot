"""frontend — storefront UI calling api-gateway."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

GATEWAY = os.getenv("API_GATEWAY_URL", "http://127.0.0.1:8080")

app = FastAPI(title="frontend", version="1.0.0")

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
    }}
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
  </style>
</head>
<body>
  <header>
    <strong>Acme Shop</strong>
    <span class="muted">Demo microservices · simulator</span>
  </header>
  <main>
    <p class="muted">Orders go through <code>api-gateway</code> at {GATEWAY} → product, inventory, payment, notification.</p>
    <div id="products" class="card">Loading products…</div>
    <div class="card">
      <h2>Place order</h2>
      <label>Product ID <input id="pid" value="sku-100" /></label>
      <label>Email <input id="email" value="buyer@acme.demo" /></label>
      <button id="order-btn" style="margin-top:1rem">Place order</button>
      <pre id="order-out"></pre>
    </div>
    <div class="card">
      <h2>Incident simulation</h2>
      <p class="muted">Breaks payment-service so checkout fails — use this with ReleaseGraph Copilot.</p>
      <button id="fail-on">Enable payment failure</button>
      <button class="ghost" id="fail-off">Restore payments</button>
      <p id="fail-msg" class="muted"></p>
    </div>
  </main>
  <script>
    const GW = "{GATEWAY}";
    async function loadProducts() {{
      const r = await fetch(GW + "/products");
      const d = await r.json();
      document.getElementById("products").innerHTML =
        "<h2>Catalog</h2>" + d.products.map(p =>
          `<div class="product"><span>${{p.name}}</span><span>$${{p.price}} · <code>${{p.id}}</code></span></div>`).join("");
    }}
    document.getElementById("order-btn").onclick = async () => {{
      const out = document.getElementById("order-out");
      out.textContent = "Placing order…";
      const r = await fetch(GW + "/orders", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          product_id: document.getElementById("pid").value,
          quantity: 1,
          customer_email: document.getElementById("email").value,
        }}),
      }});
      const text = await r.text();
      out.textContent = r.ok ? text : "ERROR " + r.status + ": " + text;
      out.className = r.ok ? "ok" : "err";
    }};
    document.getElementById("fail-on").onclick = async () => {{
      await fetch(GW + "/admin/failure-mode", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ enabled: true, latency_ms: 200 }}),
      }});
      document.getElementById("fail-msg").textContent = "Payment failure mode ON — next checkout should fail.";
    }};
    document.getElementById("fail-off").onclick = async () => {{
      await fetch(GW + "/admin/failure-mode", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ enabled: false, latency_ms: 0 }}),
      }});
      document.getElementById("fail-msg").textContent = "Payments restored.";
    }};
    loadProducts().catch(e => document.getElementById("products").textContent = e);
  </script>
</body>
</html>"""


@app.get("/health")
def health():
    return {"status": "ok", "service": "frontend", "gateway": GATEWAY}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_HTML)
