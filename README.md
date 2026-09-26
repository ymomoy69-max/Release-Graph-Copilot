# ReleaseGraph Copilot

AI-powered **release engineering** platform: dependency graphs, deterministic risk scoring, incident workflows, and a tool-backed Copilot — plus the original **rgc** deploy-safety engine (org YAML + five concurrent checkers).

## Product overview

| Component | Description |
|-----------|-------------|
| **Platform API** (`releasegraph/`) | FastAPI, SQLite/Postgres, JWT auth, releases, graph, incidents, audit, simulator |
| **Web UI** (`web/`) | React SPA — dashboard, releases, Release Graph (React Flow), Copilot, incidents |
| **Safety engine** (`rgc/`) | CLI + local UI — scan any org workspace via YAML config |
| **Demo services** (`demo/ecommerce/`) | Simulated microservices (payment failure mode for demos) |

Simulated CI/CD and demo services are **labeled**; they are not fake buttons — they write real rows to the database.

## Quick start (platform demo)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m releasegraph.seed --reset   # demo users + e-commerce project
.venv/bin/uvicorn releasegraph.main:app --reload --port 8000
```

Frontend (dev):

```bash
cd web && npm install && npm run dev
# http://localhost:5173 — login admin@acme.demo / admin123!
```

Or serve the built UI from the API:

```bash
cd web && npm run build
# API on :8000 serves web/dist at /
```

Demo microservices (7 separate processes):

```bash
.venv/bin/python demo/ecommerce/run_all.py
# or: .venv/bin/demo-ecommerce
# Storefront: http://127.0.0.1:8082  |  Gateway: http://127.0.0.1:8080/health
```

Docker: `docker compose -f docker-compose.demo.yml up --build`

See [demo/ecommerce/README.md](demo/ecommerce/README.md).

## Original rgc safety checks

```bash
.venv/bin/python -m rgc check --release fixtures/releases/safe.json --out out/safe
.venv/bin/python -m rgc serve --host 127.0.0.1 --port 8765
```

Direct org scan:

```bash
python3 -m rgc check \
  --workspace /path/to/org \
  --config /path/to/org.yaml \
  --repos gateway,api \
  --ci-dir /path/to/ci-status \
  --out out/scan
```

See [`fixtures/org.yaml`](fixtures/org.yaml) for org YAML fields.

## SDK (plug and play)

Scan any folder of connected services. No API server, no login, no database:

```python
from releasegraph.sdk import analyze_workspace

result = analyze_workspace("/path/to/microservices")
print(result["summary"])
for link in result["broken_links"]:
    print(link["from"], "→", link["to"], link["if_breaks"])
```

```bash
.venv/bin/releasegraph-scan /path/to/microservices
.venv/bin/releasegraph-scan /path/to/microservices --json
```

Talk to a running ReleaseGraph API with `releasegraph.sdk.Client(base_url, token)`.

## Environment variables

Copy [`.env.example`](.env.example). Key values:

- `DATABASE_URL` — default `sqlite:///./data/releasegraph.db`
- `JWT_SECRET` — required in production
- `CORS_ORIGINS` — frontend origin(s)

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Docker

```bash
docker compose up --build
# API :8000, Postgres :5432, demo services :8081
# Run seed inside API container after first start
```

## Documentation

- [Architecture](docs/architecture.md)
- [Demo scenarios](docs/demo-scenarios.md)
- IBM Bob build spec: [IBM_BOB_2.0_EXECUTION_PLAN.md](IBM_BOB_2.0_EXECUTION_PLAN.md) (original checker product)

## IBM Bob

The **rgc** checker pipeline, fixtures, and org-scan design were implemented per the IBM Bob 2.0 hackathon plan. The **platform layer** adds SaaS APIs, seeded e-commerce engineering data, graph UI, risk engine, and evidence-based Copilot tools on top of that foundation.
