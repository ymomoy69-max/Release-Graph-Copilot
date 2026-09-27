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
./scripts/dev-all.sh
# Platform UI :5173, API :8000, shop :8082, gateway :8080/health
# Or separately: ./scripts/dev-platform.sh and python demo/ecommerce/run_all.py
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

## Deploy to Railway

ReleaseGraph Copilot ships with a complete Railway configuration. You can deploy the full stack (FastAPI + Postgres + built React UI) from a Git push with zero manual config beyond setting a required `JWT_SECRET`.

### What's included

- [`railway.json`](railway.json) — Railway service manifest: Nixpacks build plan (Python + Node), build commands, start command, `/health` healthcheck, restart policy, and all environment variable declarations with descriptions.
- [`Procfile`](Procfile) — Nixpacks fallback: `web: python -m releasegraph.cli serve_api`.
- [`Dockerfile`](Dockerfile) — Multi-stage production image (Node 20 builder for Vite, Python 3.12-slim runtime). Use this instead of Nixpacks by setting `builder: DOCKERFILE` in `railway.json` if you prefer explicit container builds.
- [`.dockerignore`](.dockerignore) — Excludes `.venv`, caches, `node_modules`, local `data/`, `.env`, editor files.
- Port binding: server honors Railway's dynamic `$PORT` env var (defaults to 8000 locally) and always binds to `0.0.0.0`.

### Prerequisites

1. A [Railway](https://railway.app/) account.
2. Railway CLI (optional for CLI deploys, required for local build validation):
   - macOS: `brew install railway`
   - npm: `npm i -g @railway/cli`
   - or see <https://docs.railway.app/guides/cli>

### Deploy in 6 steps

```bash
# 1. Install CLI and log in
railway login

# 2. Initialize a new Railway project/service in your repo clone
railway init
#   → Create new project, name it e.g. "releasegraph", service name "api"

# 3. (RECOMMENDED) Add the Postgres plugin for *persistent* storage.
#    Without this, DATABASE_URL falls back to SQLite on the ephemeral disk
#    and ALL data (users, releases, incidents, graph) is wiped on restart.
railway add plugin postgresql

# 4. Set the ONE required env var via the dashboard or CLI:
#    Go to Railway → your service → Variables → New Variable.
#    Generate a JWT secret with:
python -c 'import secrets; print(secrets.token_urlsafe(64))'
#    → Add a variable named JWT_SECRET and paste that value.
#
#    Optional CLI shortcut (less secure, ends up in shell history):
# railway variables set JWT_SECRET "$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"

# 5. (Optional) Enable the AI Copilot. By default RG_AI_DISABLE=true so the
#    app boots without LLM keys. To enable Copilot issue rephrasing:
#    - Railway dashboard → Variables → RG_AI_DISABLE = false
#    - Railway dashboard → Variables → GROQ_API_KEY = <your key>

# 6. Deploy.
#    Option A — connect your Git repo in the Railway dashboard (recommended
#    for CD: every push to main redeploys).
#    Option B — one-off CLI deploy:
railway up
```

### After deploy

1. Visit the generated Railway domain (shown in the dashboard or via `railway open`).
2. First login uses seeded demo credentials:
   - **Email**: `admin@acme.demo`
   - **Password**: `admin123!`
3. ⚠️ **Production warning**: After first login, immediately change the demo admin password from the API (`/api/docs` → `/api/users/me/password`) or disable the seeded users via a custom migration. Do not expose a Railway instance with these default credentials on the public internet unchanged.
4. Confirm `/health` returns `{"status":"ok",...}`.
5. Confirm `/ready` returns `{"status":"ready"}`.
6. OpenAPI docs live at `/api/docs`.

### Environment variables reference

All variables are declared with descriptions in [`railway.json`](railway.json) and appear pre-filled in the Railway dashboard Variables tab.

| Variable | Default (Railway) | Required | Notes |
|---|---|---|---|
| `ENVIRONMENT` | `production` | no | Tag only; triggers the weak-JWT warning when prod + default secret. |
| `DEBUG` | `false` | no | Set to `true` for verbose logs. |
| `PORT` | `8000` | auto | Railway overrides at runtime — **do not** edit this manually. |
| `DATABASE_URL` | `sqlite:///./data/releasegraph.db` | auto* | *Auto-injected with a Postgres URL when you add the Postgres plugin. SQLite is ephemeral — do not rely on it in production. |
| `JWT_SECRET` | *(none)* | **yes** | Generate via `python -c 'import secrets; print(secrets.token_urlsafe(64))'`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | no | Session TTL; default = 24 hours. |
| `CORS_ORIGINS` | `*` | no | Allow-list. `*` is convenient on Railway because the app domain is dynamic; lock it down to your custom domain for stricter browser security. |
| `RG_AI_DISABLE` | `true` | no | Set to `false` + provide `GROQ_API_KEY` to enable Copilot features. |
| `GROQ_API_KEY` | *(none)* | no | Groq / OpenRouter / OpenAI-compatible API key. |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | no | Override for OpenRouter (`https://openrouter.ai/api/v1`) or a local OpenAI-compatible gateway. |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | no | Model name passed to the LLM provider. |
| `RELEASEGRAPH_WORKSPACE` | *(none)* | no | Optional path to a local workspace auto-scanned at first boot. |

### Redeploy, logs, scaling

- Redeploy after a new commit: Railway does this automatically when Git is connected, or run `railway up`, or click **Redeploy** in the dashboard.
- View logs: Railway dashboard → your service → **Deployments** / **Metrics**, or `railway logs`.
- Scale vertically (RAM/CPU): Railway dashboard → your service → **Settings** → **Service**.
- Observability: All application logs are structured JSON-friendly lines written to stdout/stderr, including request IDs via `X-Request-Id`. Health metrics and uptime come from Railway's built-in `/health` polling.

### Local Railway build validation

Before pushing, simulate the Railway build + start flow locally:

```bash
# 1. Build the frontend (matches the Railway build phase)
cd web && npm ci && npm run build && cd ..

# 2. Install Python deps (if not already)
python -m pip install -e ".[postgres]"

# 3. Start on a random PORT simulating Railway's runtime
PORT=9123 ENVIRONMENT=production JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')" python -m releasegraph.cli serve_api &

# 4. Verify
curl -s http://127.0.0.1:9123/health | jq .
curl -s http://127.0.0.1:9123/ready  | jq .
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:9123/
kill %1
```

## Documentation

- [Architecture](docs/architecture.md)
- [Demo scenarios](docs/demo-scenarios.md)
- IBM Bob build spec: [IBM_BOB_2.0_EXECUTION_PLAN.md](IBM_BOB_2.0_EXECUTION_PLAN.md) (original checker product)

## IBM Bob

The **rgc** checker pipeline, fixtures, and org-scan design were implemented per the IBM Bob 2.0 hackathon plan. The **platform layer** adds SaaS APIs, seeded e-commerce engineering data, graph UI, risk engine, and evidence-based Copilot tools on top of that foundation.
