# Railway Deployment Specification for ReleaseGraph Copilot

## Problem

ReleaseGraph Copilot currently lacks any Railway platform deployment artifacts or configuration. The project cannot be deployed directly from a Git repository to Railway without manual setup, port binding is hardcoded, database configuration does not account for Railway's Postgres plugin, and the frontend build process is not integrated into any deployment pipeline.

## Users

- **DevOps Engineers / Platform Teams**: Need a push-button deployment to Railway from a Git repository with zero manual configuration beyond setting required environment variables.
- **Developers**: Need to validate local Railway CLI builds before pushing changes.
- **Product Evaluators**: Need to spin up an instance on Railway quickly for demos.

## Goals

1. Configure the project to be deployable to Railway directly from a Git repository.
2. Ensure correct port binding on Railway's dynamically assigned `$PORT`.
3. Integrate frontend build into the Railway build phase so static assets are served by the FastAPI backend.
4. Configure environment variable management compatible with Railway's dashboard (sensitive + non-sensitive vars).
5. Create all required deployment artifacts: `railway.json`, Dockerfile, `.dockerignore`, Procfile.
6. Ensure Railway Postgres plugin integration (respect `DATABASE_URL` from Railway).
7. Implement logging/monitoring compatible with Railway observability (stdout/stderr, structured logs).
8. Enable CORS to work with Railway's dynamic domain.
9. Validate the setup locally via Railway CLI.
10. Document the deployment steps clearly.

## Non-Goals

1. Do not modify core business logic, safety checkers, models, or database schema beyond what is strictly required for deployment.
2. Do not create standalone frontend hosting (frontend will be served by FastAPI, per existing pattern in `releasegraph/main.py`).
3. Do not set up demo microservices (ecommerce/streaming) as separate Railway services unless explicitly required; they remain optional demos.
4. Do not implement CI/CD pipeline changes beyond Railway-specific artifacts.
5. Do not commit secrets or production credentials.

## Functional Requirements

### FR-1: Railway Configuration File
- A `railway.json` at the project root defines the service name, build command, start command, healthcheck path, and declares required/recommended environment variables.
- Build command installs Python dependencies (including optional `postgres` extras), installs Node dependencies in `web/`, and builds the Vite frontend.
- Start command runs the FastAPI server, binding to `$PORT` (not hardcoded 8000) and `0.0.0.0`.
- Declares a Postgres service reference/integration recommendation.

### FR-2: Port Binding Flexibility
- The CLI/server entry point MUST bind to the port specified in the `PORT` environment variable when present, falling back to 8000 only when `PORT` is unset.
- The server MUST bind to `0.0.0.0` (not 127.0.0.1) so Railway's proxy can reach it.

### FR-3: Dockerfile (Optional but Recommended)
- A production `Dockerfile` at the project root builds both the frontend and Python backend in reproducible stages.
- A `.dockerignore` excludes `.venv/`, `.git/`, `__pycache__/`, `web/node_modules/`, `web/dist/`, `data/`, `.env`, pytest caches, and OS editor files.
- The Docker image exposes no fixed port but honors `$PORT` at runtime via the start command.

### FR-4: Procfile (Fall-back for Nixpacks)
- A root `Procfile` declares the `web` process with the correct start command honoring `$PORT`.

### FR-5: Environment Variable Management
- All configuration values in `.env.example` are represented in `railway.json` (where applicable) with Railway-friendly defaults and descriptions.
- `DATABASE_URL` defaults to SQLite only as a fallback; in production a Railway Postgres plugin-provided `DATABASE_URL` should be used.
- `JWT_SECRET` is marked required in production with no weak default in the Railway spec.
- `CORS_ORIGINS` supports a wildcard-aware configuration or dynamic origin discovery so Railway-generated domains work without a redeploy.
- `DEBUG` defaults to `false` in the Railway production environment override.
- `ENVIRONMENT` defaults to `production`.
- `RG_AI_DISABLE` defaults to `true` so the app boots without Groq/OpenAI keys.

### FR-6: Database Compatibility
- `init_db()` and SQLAlchemy engine creation work with a Railway-provided Postgres `DATABASE_URL` (no modifications needed here; validate existing code path).
- SQLite-only column migrations in `_ensure_sqlite_columns()` are skipped for Postgres (already implemented).
- The default SQLite path (`sqlite:///./data/releasegraph.db`) creates the `data/` directory on first run even in a container.

### FR-7: Observability / Logging
- Application logs go to stdout/stderr with Railway-compatible formatting (existing format is acceptable; ensure no file logger is enabled in production).
- `/health` and `/ready` endpoints remain accessible for Railway healthchecks.
- The request ID middleware continues to work unchanged.

### FR-8: Build & Start Validation
- The project builds cleanly with `railway build` (or equivalent local validation).
- The project starts cleanly with a simulated `PORT` variable set.
- Hitting `/health` returns `{"status":"ok",...}`.
- Hitting `/` serves the built frontend `index.html`.

### FR-9: Deployment Documentation
- An in-code set of deployment steps is documented via the artifacts (a user-facing doc summary). Document:
  1. Prerequisites (Railway account, CLI installed).
  2. `railway login`, `railway init`, `railway add plugin postgresql`, `railway up`.
  3. Required environment variables to set in the dashboard.
  4. How to trigger a redeploy, view logs, and scale.
  5. Default demo login credentials (and warning to change them).

## Non-Functional Requirements

### NFR-1: Security
- No secrets are committed in `railway.json`, Dockerfile, or any other artifact.
- `JWT_SECRET` must be explicitly set by the operator; a Railway-deployed instance must not fall back to the dev default silently if `ENVIRONMENT=production` and `JWT_SECRET` is the weak default — log a warning.

### NFR-2: Performance
- The frontend is built during the Railway build phase, not at runtime.
- Static asset serving is handled by FastAPI's `StaticFiles` (existing behavior) — no separate dev server runs in production.

### NFR-3: Maintainability
- Deployment files follow Railway's official patterns and latest best practices.
- Build/start commands are idempotent.

### NFR-4: Compatibility
- Works with Railway Nixpacks auto-detection (Procfile + railway.json) as well as explicit Dockerfile builds.
- Existing local development workflows (`./scripts/dev-platform.sh`, `uvicorn --reload`, `npm run dev`) remain unaffected.

## Constraints

1. Railway dynamically assigns a `PORT` env var; the application MUST listen on exactly this port.
2. Railway Postgres plugin injects a `DATABASE_URL` env var automatically.
3. Instances have ephemeral local disks — SQLite data is wiped on restart; Postgres plugin is required for persistent data.
4. Railway build containers have both Node and Python toolchains available when properly configured.

## Dependencies

- Railway platform (Nixpacks or Dockerfile builder).
- Railway Postgres plugin (recommended).
- Python 3.11+ (per `pyproject.toml`).
- Node 18+ (Vite build requirement — implicit in Nixpacks auto-detect via `web/package.json`).

## Assumptions

1. The FastAPI backend serves the built frontend SPA at `/` and assets at `/assets` — this existing pattern is sufficient and preferred over separate frontend hosting.
2. The `lifespan` handler's auto-seeding of demo users/projects is acceptable for a deployed demo instance and is intentionally not disabled.
3. Groq/OpenAI LLM features are optional; the app boots and functions without them (per `RG_AI_DISABLE=true` default).
4. Demo microservices (ecommerce/streaming) are not part of the base Railway deployment; they remain optional local-only demos.

## Open Questions

None at this time. The above assumptions are reasonable defaults.

## Acceptance Criteria

### rule AC-1: `railway.json` exists at repo root with build command, start command, service declaration, healthcheck, and env var declarations.
- Observable: File `railway.json` exists, parses as JSON, contains keys `build`, `start`, `deploy` (or equivalent Railway schema), and references `web` build + Python server.
- Evidence source: `Read` on `railway.json`.

### rule AC-2: Application honors `$PORT` env var and binds to `0.0.0.0`.
- Observable: Running `PORT=9123 python -m releasegraph.cli serve_api` and then `curl http://127.0.0.1:9123/health` returns a 200 with `status:ok`.
- Evidence source: `RunCommand` invoking curl after startup.

### rule AC-3: `Procfile` exists at repo root and defines a `web` process.
- Observable: File `Procfile` exists and contains a `web:` line starting the uvicorn/FastAPI server with `$PORT`.
- Evidence source: `Read` on `Procfile`.

### rule AC-4: `Dockerfile` and `.dockerignore` exist and follow Railway-compatible best practices.
- Observable: Files `Dockerfile` and `.dockerignore` exist at repo root; Dockerfile installs Python+Node deps, builds `web/`, and starts the server on `$PORT`; `.dockerignore` excludes dev artifacts.
- Evidence source: `Read` on both files; optional `docker build` local run if Docker available.

### rule AC-5: CORS origins accept Railway-generated domains without hardcoding.
- Observable: `CORS_ORIGINS` env var supports a comma-separated list AND/OR `*` wildcard works without crashing; default configuration in Railway matches the served domain.
- Evidence source: `Read` on `config.py` + launch with `CORS_ORIGINS=*` and verify `/health` works.

### rule AC-6: Postgres `DATABASE_URL` from Railway plugin is used transparently.
- Observable: Setting `DATABASE_URL=postgresql+psycopg2://...` causes the app to boot without SQLite-specific code paths (no crash).
- Evidence source: Read `database.py` + `config.py` confirming no hardcoded sqlite override.

### rule AC-7: Production defaults are safer.
- Observable: `railway.json` sets `ENVIRONMENT=production`, `DEBUG=false`, `RG_AI_DISABLE=true` by default; JWT_SECRET has no dev default in Railway spec.
- Evidence source: `Read` on `railway.json` env block.

### rule AC-8: Health and ready endpoints exist and return 200 on a running instance.
- Observable: `GET /health` → 200 JSON with `status: ok`; `GET /ready` → 200 JSON.
- Evidence source: Same curl-based evidence as AC-2, plus `Read` on `main.py` confirming endpoints.

### rubric AC-9: Railway deployment quality and completeness.
- Dimension: Clarity, correctness, and adherence to Railway best practices across all artifacts.
- Scale: 0 (missing/broken) to 2 (excellent, production-ready).
- Pass threshold: ≥ 2.
- Anchors:
  - 0 = artifacts missing or fundamentally wrong (e.g., hardcoded port, missing build step, no env docs).
  - 1 = artifacts present with minor gaps (e.g., missing env var descriptions, no healthcheck, brittle commands).
  - 2 = complete, clean, well-documented; `railway up` works from a clean Git clone after dashboard env setup.
- Evidence source: Artifact content review + local Railway CLI validation result.

### rubric AC-10: Documentation quality.
- Dimension: Usability and completeness of deployment step documentation.
- Scale: 0 (no docs) to 2 (standalone, complete, clear).
- Pass threshold: ≥ 2.
- Anchors:
  - 0 = no deployment instructions.
  - 1 = partial instructions, missing steps or unclear prerequisites.
  - 2 = step-by-step Railway deployment instructions covering CLI init, Postgres plugin, env vars, deploy, verify, first login, redeploy; includes warnings about JWT secret, demo creds, and persistence.
- Evidence source: Artifact content review of documentation.
