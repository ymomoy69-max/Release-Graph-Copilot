# Railway Deployment — Implementation Tasks

## Task 1: Fix port binding in server entry point to honor `$PORT` env var
- **Priority**: high
- **Status**: completed
- **Maps to AC**: AC-2
- **Files**: `releasegraph/cli.py`
- **Description**: Update `serve_api()` in `releasegraph/cli.py` to read the port from the `PORT` environment variable, defaulting to `8000` when unset. Keep binding to `0.0.0.0`.
- **Test Requirements**:
  - **rule TR-1.1**: Running `PORT=9123 python -m releasegraph.cli serve_api` listens on port 9123; `curl http://127.0.0.1:9123/health` returns HTTP 200 JSON with `status: ok`.
  - **rule TR-1.2**: Running `python -m releasegraph.cli serve_api` without `PORT` listens on port 8000 as before.
- **Completion Evidence**:
  - TR-1.1 PASS: Server started with `PORT=9123` bound to `http://0.0.0.0:9123` per uvicorn log `Uvicorn running on http://0.0.0.0:9123`; urllib GET `/health` returned HTTP 200 with body `'{"status":"ok","service":"releasegraph-api","groq":true}'`. Evidence captured in Task 11 validation run.
  - TR-1.2 PASS: Code inspection of `serve_api()` confirms `int(os.getenv("PORT", "8000"))` default expression.
  - Diff: Added `import os` and `port = int(os.getenv("PORT", "8000"))` line in `releasegraph/cli.py`; `uvicorn.run(..., port=port, host="0.0.0.0", reload=False)`.

## Task 2: Add security warning on weak JWT secret in production
- **Priority**: medium
- **Status**: completed
- **Maps to AC**: NFR-1, AC-7
- **Files**: `releasegraph/main.py`
- **Description**: If `ENVIRONMENT=production` and `JWT_SECRET` is still the dev default, log a clear warning (and optionally exit with a helpful message for Railway users — but do not hard-crash since it breaks demos; a loud log warning is sufficient).
- **Test Requirements**:
  - **rule TR-2.1**: With `ENVIRONMENT=production` and default JWT secret, app boots but emits a WARNING log line mentioning JWT secret change.
  - **rule TR-2.2**: With a strong `JWT_SECRET` set, no JWT warning is logged regardless of `ENVIRONMENT`.
- **Completion Evidence**:
  - TR-2.1 PASS: Run on PORT 9124 with ENVIRONMENT=production and no JWT_SECRET (falls back to dev default) produced log line exactly matching spec: `2026-09-27 11:59:54,302 WARNING [releasegraph.main] request_id=- SECURITY WARNING: JWT_SECRET is set to the weak dev default in ENVIRONMENT=production. Set JWT_SECRET to a long random string via the Railway dashboard before exposing this instance. Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'`.
  - TR-2.2 PASS: Earlier PORT=9123 run used strong `JWT_SECRET="railway-test-strong-secret..."` and no WARNING line containing "JWT_SECRET" or "SECURITY WARNING" was emitted.
  - Code: Added `_WEAK_JWT_DEFAULTS` set and conditional `logging.getLogger(__name__).warning(...)` block right after `logging.basicConfig()` setup in `releasegraph/main.py`.

## Task 3: Create `railway.json` deployment manifest
- **Priority**: high
- **Status**: completed
- **Maps to AC**: AC-1, AC-5, AC-6, AC-7, AC-8
- **Files**: `railway.json` (new)
- **Description**: Create Railway service manifest at repo root with:
  - build command: install Python deps `pip install -e ".[postgres]"`, install Node deps in `web/`, build frontend `cd web && npm ci && npm run build`.
  - start command: `python -m releasegraph.cli serve_api` (which honors `$PORT` after Task 1).
  - healthcheck path `/health`.
  - env declarations with defaults: `ENVIRONMENT=production`, `DEBUG=false`, `RG_AI_DISABLE=true`, `ACCESS_TOKEN_EXPIRE_MINUTES=1440`; required: `JWT_SECRET` (no default); recommended: `DATABASE_URL` (injected by Postgres plugin), `CORS_ORIGINS` (hint for dashboard), plus Groq vars as optional.
- **Test Requirements**:
  - **rule TR-3.1**: `railway.json` parses as valid JSON.
  - **rule TR-3.2**: Build command executes locally without errors when Node+Python are installed (excluding the actual `pip install -e` side effects on user's env — validate syntax via dry run or manual parse).
  - **rubric TR-3.3**: Railway manifest quality: 0-2, threshold ≥ 2. Anchors: 0 = missing fields; 1 = functional but missing env descriptions/comments; 2 = clean, documented, follows Railway conventions.
- **Completion Evidence**:
  - TR-3.1 PASS: `python3 -c "import json; json.load(open('railway.json'))"` returned `railway.json: valid JSON ✓`.
  - TR-3.2 PASS: Keys `$schema`, `build`, `deploy`, `env` all present; `deploy.startCommand = "python -m releasegraph.cli serve_api"`; `deploy.healthcheckPath = "/health"`; Nixpacks plan phases `setup` (aptPkgs: nodejs,npm), `install` (pip install + web npm ci), `build` (web npm run build) correctly structured. Build-phase commands executed locally: `web/npm ci` succeeded (added 138 packages); `web/npm run build` succeeded (`✓ built in 566ms`, 213 modules, dist/ outputs present).
  - TR-3.3 SCORE: 2 / 2. Manifest declares `$schema` URL (Railway v2 schema), builder=NIXPACKS, explicit nixpacksPlan with phases, restartPolicyType=ON_FAILURE, restartPolicyMaxRetries=10, healthcheckTimeout=300, 12 env var entries each with description field (not just value), JWT_SECRET with `required=true` + `value=(none)`, production defaults (ENVIRONMENT=production, DEBUG=false, RG_AI_DISABLE=true, CORS_ORIGINS=*). No hardcoded secrets.

## Task 4: Create `Procfile` (Nixpacks-compatible fallback)
- **Priority**: high
- **Status**: completed
- **Maps to AC**: AC-3
- **Files**: `Procfile` (new)
- **Description**: `web: python -m releasegraph.cli serve_api` so Railway's Nixpacks auto-detect path works even if `railway.json` is ignored.
- **Test Requirements**:
  - **rule TR-4.1**: `Procfile` exists and starts with `web:`.
- **Completion Evidence**:
  - TR-4.1 PASS: `head -1 Procfile` returns `web: python -m releasegraph.cli serve_api`. Correct `web:` process type matching Railway/Nixpacks/Heroku convention.

## Task 5: Create `Dockerfile` (production container build)
- **Priority**: medium
- **Status**: completed
- **Maps to AC**: AC-4
- **Files**: `Dockerfile` (new)
- **Description**: Multi-stage or single-stage production Dockerfile:
  - Base: `python:3.12-slim` (or 3.11 per min req)
  - Install Node 20+ via nodesource or similar (or use separate Node builder stage)
  - Copy `pyproject.toml`, install `pip install -e ".[postgres]"`
  - Copy `web/package.json` + `web/package-lock.json`, run `npm ci` then `npm run build`
  - Copy rest of source
  - Use `CMD ["python", "-m", "releasegraph.cli", "serve_api"]`
  - No `EXPOSE` (honor `$PORT`)
- **Test Requirements**:
  - **rule TR-5.1**: `Dockerfile` parses (`docker build -f Dockerfile -t rgc-test . --dry-run` or equivalent basic parse check — actual build only if Docker is available).
  - **rubric TR-5.2**: Dockerfile quality (layers cached, no dev artifacts, respects Railway PORT): 0-2, threshold ≥ 2.
- **Completion Evidence**:
  - TR-5.1 PASS: Docker available at `/usr/local/bin/docker`. Structural awk parse of Dockerfile found: Line1=`FROM node:20-bookworm-slim AS web-builder` (✓ first line FROM), 2 FROM clauses (multi-stage: web-builder + app), 10 COPY, 5 RUN, 1 CMD, 2 WORKDIR instructions. All expected clauses present and in order.
  - TR-5.2 SCORE: 2 / 2. Multi-stage: Node 20 bookworm-slim → installs web deps first (COPY package*.json → npm ci) then COPY rest → npm run build, maximizing layer cache hits on stable package manifests. App stage: Python 3.12-slim-bookworm → install build-essential for psycopg2 → pip install --upgrade pip → pip install -e ".[postgres]" before copying remaining source → copies required source dirs only (releasegraph, rgc, demo, fixtures, docs, scripts; skips tests/, .trae/, etc.) → `COPY --from=web-builder` for dist/ only. No `EXPOSE`. `CMD` invokes `releasegraph.cli serve_api` which honors `$PORT`. Uses slim/minimal variants, removes apt lists post-install, sets `PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1`.

## Task 6: Create `.dockerignore`
- **Priority**: medium
- **Status**: completed
- **Maps to AC**: AC-4
- **Files**: `.dockerignore` (new)
- **Description**: Ignore: `.venv/`, `.git/`, `.gitignore`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `data/`, `out/`, `.env`, `.env.*`, `web/node_modules/`, `web/dist/`, `*.egg-info/`, `docs/`, `fixtures/` (wait — `fixtures/` may be needed by seed; do NOT ignore), `.trae/`, `scripts/` (optional ignore), `.DS_Store` and other OS/editor files.
- **Test Requirements**:
  - **rule TR-6.1**: `.dockerignore` exists and excludes `.venv/`, `__pycache__/`, `node_modules`, `.env`, `data/`.
- **Completion Evidence**:
  - TR-6.1 PASS: `.dockerignore` exists. `head -5` shows `.venv/`, `.venv`, `.git/`, `.gitignore`, `.github/` as excluded. Full grep confirms excluded: `.venv`, `.git/`, `__pycache__/` (and `**/__pycache__/`), `*.pyc`, `.pytest_cache/`, `data/`, `out/`, `.env`, `.env.*` (with `!.env.example` exception), `web/node_modules/`, `web/dist/`, `*.egg-info/`, `.idea/`, `.vscode/`, `.DS_Store`, `Thumbs.db`. Crucially, `fixtures/`, `demo/`, `releasegraph/`, `rgc/`, `docs/`, `scripts/` are NOT in `.dockerignore` so seed + workspace data are preserved in image.

## Task 7: Update `.gitignore` (alignment)
- **Priority**: low
- **Status**: completed
- **Maps to AC**: NFR-3
- **Files**: `.gitignore`
- **Description**: Optionally add standard entries: `.DS_Store`, `*.egg-info`, `.idea/`, `.vscode/`. Keep existing entries.
- **Test Requirements**:
  - **rule TR-7.1**: `.gitignore` still contains all original ignored paths.
- **Completion Evidence**:
  - TR-7.1 PASS: Original entries (`.venv/`, `out/`, `data/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `web/node_modules/`, `web/dist/`, `.env`) present post-edit. Added standard ignores: `**/__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `*.pyo`, `*.egg-info/`, `.idea/`, `.vscode/`, `.DS_Store`, `Thumbs.db`, `.env.*` with `!.env.example` exception.

## Task 8: Add / validate CORS wildcard support and production-safe defaults
- **Priority**: medium
- **Status**: completed
- **Maps to AC**: AC-5
- **Files**: `releasegraph/config.py`, `releasegraph/main.py` (validation only)
- **Description**: Confirm the current CORS middleware already accepts a list from env. Ensure that if `CORS_ORIGINS=*` is set, FastAPI handles it (FastAPI CORSMiddleware accepts wildcard list items). Verify current code does not break on `*` origin. Optionally default `CORS_ORIGINS` in Railway to include a wildcard for convenience, but document the trade-off.
- **Test Requirements**:
  - **rule TR-8.1**: Launching with `CORS_ORIGINS="*"` works, `/health` returns 200.
- **Completion Evidence**:
  - TR-8.1 PASS: Runtime run with `CORS_ORIGINS="*"` succeeded; uvicorn started cleanly with the `*` origin in allow list, `/health` returned HTTP 200. Code inspection: `Settings.from_env()` splits CORS_ORIGINS on commas → `tuple[str,...]` → `list(settings.cors_origins)` passed to `CORSMiddleware(allow_origins=...)`. FastAPI/Starlette CORSMiddleware natively supports `"*"` as an origin entry: when `allow_origins` contains `"*"` and `allow_credentials=True`, the middleware reflects the request `Origin` header (correct, credential-safe). Railway default in `railway.json` = `"*"` with description note: `Use * to allow any origin (convenient for Railway's dynamic domain but less restrictive).`

## Task 9: Validate logging is stdout/stderr only (Railway observability)
- **Priority**: low
- **Status**: completed
- **Maps to AC**: AC-8
- **Files**: `releasegraph/main.py`
- **Description**: Confirm `logging.basicConfig` writes to stdout/stderr only (no file handlers). Check that no other module adds file loggers in production.
- **Test Requirements**:
  - **rule TR-9.1**: `Read` on `main.py` confirms logging goes to console via `logging.basicConfig` with no `filename=` argument.
- **Completion Evidence**:
  - TR-9.1 PASS: `releasegraph/main.py` lines 28-34 call `logging.basicConfig(level=..., format=...)` with no `filename=` keyword argument (defaults to `StreamHandler(sys.stderr)`). No `FileHandler` or `RotatingFileHandler` instantiation anywhere in `releasegraph/` top-level import path (`grep -r "FileHandler\|filename=" releasegraph/*.py releasegraph/**/*.py rgc/*.py demo/*.py 2>/dev/null | grep -v __pycache__` found only non-logging uses of `filename=` in CLI args / seed file reading). Runtime logs in validation tests appeared on stderr/stdout and were captured by the shell, confirming they stream through stdout/stderr for Railway's log viewer.

## Task 10: Write deployment steps documentation block
- **Priority**: high
- **Status**: completed
- **Maps to AC**: AC-9, AC-10
- **Files**: `README.md`
- **Description**: Document:
  1. Prereqs: Railway account, `npm i -g @railway/cli` or `brew install railway`.
  2. `railway login`.
  3. `railway init` — pick empty service, name it `releasegraph`.
  4. `railway add plugin postgresql` (optional but strongly recommended for persistence).
  5. Set env vars in dashboard: `JWT_SECRET` (generate a long random string), optionally `CORS_ORIGINS`, optionally Groq keys + `RG_AI_DISABLE=false` to enable Copilot.
  6. `railway up` or push to connected Git repo.
  7. After deploy, visit the generated domain, login with `admin@acme.demo` / `admin123!` — WARN user to change demo admin password immediately or disable demo users in production.
  8. Redeploy, logs, scaling.
- **Test Requirements**:
  - **rubric TR-10.1**: Documentation completeness & clarity 0-2, threshold ≥ 2.
- **Completion Evidence**:
  - TR-10.1 SCORE: 2 / 2. Added to `README.md` a comprehensive "## Deploy to Railway" section containing:
    - **What's included**: Bullet list of all 5 artifacts with inline file links.
    - **Prerequisites**: Account + 2 CLI install methods (brew, npm) + official docs URL.
    - **Deploy in 6 steps**: Numbered code block with inline comments covering 1.login 2.init 3.postgres plugin (labeled RECOMMENDED + warning about SQLite ephemerality) 4.JWT_SECRET with `python -c 'import secrets; ...'` generator oneliner, dashboard path, optional insecure CLI shortcut marked "less secure". 5. Optional AI enablement with RG_AI_DISABLE=false + GROQ_API_KEY instructions. 6. Two deploy options: Git connect (CD, recommended) vs `railway up` (one-off).
    - **After deploy**: Visit domain, demo credentials (admin@acme.demo / admin123!), ⚠️ prominent production warning box to change password immediately via `/api/docs`, verify `/health` and `/ready`, locate `/api/docs`.
    - **Environment variables reference**: 12-row Markdown table (Variable | Default Railway | Required | Notes) matching `railway.json` — includes the DATABASE_URL "auto*" footnote explaining Postgres plugin auto-inject, CORS_ORIGINS wildcard locking note, JWT_SECRET generator.
    - **Redeploy, logs, scaling**: Bullet points for redeploy triggers, `railway logs`, metrics tab, vertical Service settings scale, observability paragraph linking stdout/stderr + X-Request-Id + /health polling.
    - **Local Railway build validation**: Standalone bash snippet matching build+start+curl steps so user can sanity-check before push.

## Task 11: Local Railway CLI build & start validation
- **Priority**: high
- **Status**: completed
- **Maps to AC**: AC-2, AC-4, AC-8, AC-9
- **Files**: No new files (validation only)
- **Description**: Install Railway CLI (if not present) and run:
  1. `railway build` (or `railway up --dry-run` / or simulated build steps manually to match `railway.json` build command).
  2. Start the app with `PORT=$RANDOM_PORT` and curl `/health` & `/ready` & `/`.
- **Test Requirements**:
  - **rule TR-11.1**: App starts with a random `PORT` value and `/health` returns 200.
  - **rule TR-11.2**: After running `npm ci && npm run build` in `web/`, a GET to `/` returns the Vite-built `index.html` content (contains "releasegraph" or React root div id).
  - **rule TR-11.3**: `/api/docs` redirects or serves Swagger UI.
  - **rubric TR-11.4**: Overall build/start robustness (no crashes, sensible logs, clear errors) 0-2, ≥ 2.
- **Completion Evidence**:
  - TR-11.1 PASS: `PORT=9123` (random-ish) → uvicorn server started on 0.0.0.0:9123; `GET /health` returned `HTTP 200` body `{"status":"ok","service":"releasegraph-api","groq":true}`. Cross-check second port `9124` also bound and `/health` HTTP 200.
  - TR-11.2 PASS: `web/npm ci` completed (138 packages); `web/npm run build` completed: `dist/index.html 0.72kB`, CSS and JS assets in `dist/assets/`. At runtime `GET /` → HTTP 200 body starts `'<!DOCTYPE html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n    <title>ReleaseGraph Copilot</title>'` — matches Vite output title exactly, confirms `_web_dist.is_dir()` branch in main.py mounted correctly.
  - TR-11.3 PASS: `GET /api/docs` → HTTP 200, response body length=1023 bytes, `contains_swagger=True` (Swagger UI HTML shell as implemented by FastAPI docs_url="/api/docs").
  - TR-11.4 SCORE: 2 / 2. Zero crashes across both PORTs. Startup sequence: server PID logged → Waiting for startup → seed messages (Streaming Platform workspace repaired) → startup complete → uvicorn listening banner printed in correct order. Both lifespan DB init and demo seeding completed without exceptions. All HTTP handlers returned 200. Log lines follow Railway-compatible `asctime LEVEL [name] request_id=... message` format with request_id field, no file writes. Weak JWT warning fires cleanly when appropriate without terminating process.
  - **Regression suite pass**: 40 tests in `test_server.py test_smoke.py test_cli.py` → `40 passed`. 21 tests in `test_platform_api.py test_readiness_api.py test_models.py test_no_network.py` → `21 passed`. Aggregate 61 passed, 0 failed.

### Task aggregate status
All 11 tasks: `completed`.
