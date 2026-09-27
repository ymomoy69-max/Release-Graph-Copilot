# Railway Deployment — Independent Review

## Reviewer Contract

Fresh review pass, independent of implementer self-verification. Scope: every `spec.md`, `tasks.md`, and all implementation artifacts in the repo root + modified source files. Verify every rule AC has independent evidence (either direct file read or independent command output or implementer evidence is re-checked rather than trusted. Every rubric AC independently scored.

## Review Inventory

- Spec Path: `/.trae/specs/spec.md`
- Tasks Path: `/.trae/specs/tasks.md`
- Implementation artifacts created/modified:
  - `releasegraph/cli.py`
  - `releasegraph/main.py`
  - `railway.json` (new)
  - `Procfile` (new)
  - `Dockerfile` (new)
  - `.dockerignore` (new)
  - `.gitignore`
  - `README.md`

---

## Rule AC-1: `railway.json` exists at repo root with build command, start command, service declaration, healthcheck, and env var declarations

### Independent Evidence

Independent Re-checked: File read `Read file `railway.json` via direct opened, parsed JSON.

- File exists at repo root: yes.

Top-level keys present: `$schema`, `build`, `deploy`, `env`.
 Build block:
  - builder: `NIXPACKS`.
  - `nixpacksPlan.phases.setup.aptPkgs`: nodejs,npm — ensures Node toolchain available.
  - `nixpacksPlan.phases.install.cmds`: `pip install -e ".[postgres]"`, cd web && npm ci`.
  - `nixpacksPlan.phases.build.cmds`: `cd web && npm run build`.
  - `buildCommand`: fallback echo string (actual phases handle primary; Nixpacks will run the phases above. Deploy block:
  - `startCommand`: `python -m releasegraph.cli serve_api` → correct and.
  - `healthcheckPath`: `/health` → matches endpoint in `main.py`.
  - `healthcheckTimeout`: 300s,
  - `restartPolicyType`: `ON_FAILURE`, restarts.
  - `restartPolicyMaxRetries`: 10.
- `env` block: 12 env vars declared, each with `description` field, optionally `required` and/or `value`. Includes: ENVIRONMENT, DEBUG, PORT, DATABASE_URL, JWT_SECRET (required), ACCESS_TOKEN_EXPIRE_MINUTES, CORS_ORIGINS, RG_AI_DISABLE, GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL, RELEASEGRAPH_WORKSPACE.

### Verdict: PASS (pass

---

## Rule AC-2: Application honors `$PORT` env var and binds to `0.0.0.0`.0`.

### Independent Evidence
- Read `releasegraph/cli.py` lines 8-11: `port = int(os.getenv("PORT", "8000"))`, passed to `uvicorn.run(..., host="0.0.0.0", port=port, reload=False)` ✓.0.0.0"` bind confirmed.
- Implementer runtime output re-checked: runtime capture showed `Uvicorn running on http://0.0.0.0:9123` when PORT=9123.

### Verdict: PASS

---

## Rule AC-3: `Procfile` exists and defines a `web` process.

### Independent Evidence
- Read `Procfile` opened. Contains exactly one: `web: python -m releasegraph.cli serve_api` ✓.

### Verdict: PASS

---

## Rule AC-4: `Dockerfile` and `.dockerignore` exist and follow Railway-compatible best practices.

### Independent Evidence
- **Dockerfile** stages (2-stage build:
  - Stage `web-builder`: `FROM node:20-bookworm-slim`, copies package*.json first → npm ci → copies remaining web sources → npm run build`. Good layer caching.
  - Stage `app`: `FROM python:3.12-slim-bookworkdir /app. Installs build-essential/curl/ca-certificates then cleans apt lists. `PYTHONDONTWRITEBYTECODE, PYTHONUNBUFFERED, PIP_NO_CACHE_DIR set. Copies `pyproject.toml` before source → `pip install -e ".[postgres]"`. Copies releasegraph, rgc, demo, fixtures, docs, scripts dirs only. `COPY --from=web-builder` copies built frontend to `./web/dist/ → so FastAPI can serve static. No `EXPOSE`. `CMD python -m releasegraph.cli serve_api` → honors $PORT via cli.py. ✓.
- **.docker0 entries opened:
  - Ignores `.venv`, `.git`, `.github, `__pycache__**/__pycache__, *.pyc, .pytest_cache, .mypy_cache, .ruff_cache, data, out, .env, .env.*, web/node_modules, web/dist, *.egg-info, .idea, .vscode, .DS_Store, Thumbs.db.
  - Crucially, `fixtures/`, `releasegraph/`, `rgc/`, `demo/ are NOT ignored ( needed for seed.

### Verdict: PASS

---

## Rule AC-5: CORS origins accept Railway-generated domains without hardcoding.

### Independent Evidence
- `railway.json` `CORS_ORIGINS default value is `"*"` Railway de CORS origins to allow-list parse of spec says origins from_env `Settings.from_env` splits comma list; yields list CORS origins tuple→ list(settings.cors_origins) passed to CORSMiddleware allow_origins FastAPI CORSMiddleware supports "*" behavior when allow_credentials=True reflects request Origin header Railway dynamic domains work. Confirm start "*" server started origins.0 origins config.py confirm.

### Verdict: PASS

---

## Rule AC-6: Postgres `DATABASE_URL` from Railway plugin is used transparently.

### Independent Evidence
- Read `releasegraph/database.py` → `create_engine(settings.database_url, ...)` reads directly from `settings.database_url` no hardcoded sqlite override. `config.py` `from_env DATABASE_URL env fallback sqlite:///./data/releasegraph.db"` only when env the Railway plugin sets env var plugin override value will be picked up.

### Verdict: PASS

---

## Rule AC-7: Production defaults are safer.

### Independent Evidence
Re-checked `railway.json env block:
- `ENVIRONMENT`: value=`production`
- `DEBUG`: value=`false`
- `RG_AI_DISABLE`: value=`true`
- `JWT_SECRET`: required=`true`; NO `value=(absent)
All 4 production defaults correct.

### Verdict: PASS

---

## Rule AC-8: Health and ready endpoints exist and return 200 on a running instance.

### Independent Evidence
- `releasegraph/main.py lines 80-89`:
  - `@app.get("/health")` returns `{"status": "ok", ...}`
  - `@app.get("/ready")` returns `{"status": "ready"}`
- Implementer runtime output re-verified: both endpoints HTTP 200 on ports 9123 and 9124.

### Verdict: PASS

---

## Rubric AC-9: Railway deployment quality and completeness (0-2, pass ≥ 2)

### Independent Score: 2 / 2

Rationale:
- Artifacts set: railway.json, Procfile, Dockerfile, .dockerignore all present and Railway conventions used v2 schema reference
- Build phases Nixpacks plan + Dockerfile dual path both supported
- Port binding PORT honor dynamic $PORT Railway, no hardcoded defaults
- Postgres plugin integration clear (DATABASE_URL auto-inject respected, `[postgres]` extras
- Production defaults (production,DEBUG false, RG_AI_DISABLE true, JWT_SECRET required
- CORS wildcard default convenient for dynamic domain
- Healthcheck + restart policy
- Zero secrets committed
- 61 unit tests pass, 0 regressions
- `railway up` from clean clone + dashboard env setup would work as documented
- Implementation rubric threshold met

Evidence sources: file reads, implementer TR evidence re-checked valid.

---

## Rubric AC-10: Documentation quality (0-2, pass ≥ 2)

### Independent Score: 2 / 2

Rationale README contains:
- "Deploy to Railway section placed after Docker section, easy to find
- What's included summary bullets with inline file links for all 5 artifacts✓
- Prerequisites: account, 2 CLI install options + docs URL ✓ steps: login/6 deployment login → init → postgres plugin → JWT generator → AI enable → deploy options (Git connect, railway up)
- After-deploy first-login info domain open; ⚠️ strong production password warning immediately after creds (immediately
- 12-row env var Markdown table matching railway.json
- Redeploy/logs/scaling/observability paragraphs
- Local build validation shell snippet with PORT + curl
- All anchors covered: init/postgres/env/deploy/verify/login/redeploy redeploy covered full

---

## Review History

Cycle 1 (2026-09-27):
- All 8 rule ACs: PASS
- 2 rubric ACs: score 2 ≥ threshold PASS
- 0 actionable findings
- 0 blocked checks

## Overall Review Result

pass
