# ReleaseGraph — Zero-External-Dependencies Specification

## Problem

ReleaseGraph Copilot currently requires:
- A SQL database (SQLite / Postgres) via SQLAlchemy (`releasegraph/database.py`, 10+ `Base` models, 40+ `Depends(get_db)` endpoint dependencies)
- JWT auth + `python-jose` + `bcrypt` password verification backed by DB user lookups (`releasegraph/auth.py`, `get_current_user()` hits DB for every request)
- External HTTP calls (Groq/OpenAI LLM via `httpx` in `ai_layer.py`; shop gateway/storefront microservices via `checkout_failure.py`, `checkout_incidents.py`, `shop_status.py`)
- A Postgres plugin on Railway just to boot

This makes deployment require infrastructure provisioning and creates "Application Error" even when all user wanted was to run the UI locally. The user wants a single-runtime zero-external-dependency build that still "feels persistent" across page reloads and restarts, uses in-memory or client-side storage faking persistence, doesn't need Postgres plugin, doesn't need bcrypt/jose libraries, and still deploys with Railway `railway up` / `python -m releasegraph.cli serve_api` as one command.

## Users

- Evaluators who just want to "try the UI" without setting up DB/plugins/auth
- Trainers/demo runners: show ReleaseGraph graph/dashboard/readiness pages/copilot without provisioning
- Single-user local/dev install: no services, no passwords database file, no networking

## Goals

1. **Eliminate all SQLAlchemy / SQL database dependencies from the boot path.** Remove every `Depends(get_db)`, every `SessionLocal`, `Base.metadata.create_all`, etc.
2. **Eliminate all `python-jose` JWT decoding + bcrypt password dependency-backed auth** from the runtime. Provide a simplified session system that:
   - Does NOT require bcrypt to hash or verify passwords in a database
   - Uses in-memory user records plus signed self-contained tokens OR client-side cookies
   - Persists sessions across browser page reloads (via existing client-side `localStorage`)
3. **Replace every external-network call (Groq LLM, shop gateway, storefront) with deterministic no-op stubs** that return safe payloads so the app never calls out.
4. **Provide *persistent-feeling* storage across restarts:** use a single writable JSON file in `./data/releasegraph-store.json` (or env-configurable path) to save users/projects/releases/incidents/etc atomically.
5. **Keep the existing API surface** (`/api/*` routes, request/response shapes, `/health`, `/ready`, frontend `api.ts` client) so the React UI works unchanged — consumers never notice the backend was re-wired.
6. **Simplify deployment to a single Python process with one command**; Railway plugin variables are allowed but never required; `DATABASE_URL` can be set but is ignored with a warning; `GROQ_API_KEY` is allowed but unused safely.
7. **End-to-end test:** session persistence across reloads; app restart reloads JSON store; no network calls; deploys from Railway without Postgres plugin or Groq vars.

## Non-Goals

1. Do NOT preserve SQLAlchemy `Base` models, SQL queries, `models.py`, `database.py`, `auth.py` (these modules are gutted or replaced).
2. Do NOT preserve Postgres/SQLite specific code (init_db, column migrations, `_ensure_sqlite_columns`).
3. Do NOT preserve rgc workspace scans that invoke HTTPX network — stub them safely.
4. Do NOT preserve the seeded demo password bcrypt-hashed user records — users can be simple static in-memory users with password strings stored as plain SHA-256 hashes (NOT bcrypt) to avoid the dependency.
5. Do NOT preserve Groq/Copilot LLM rewording. Copilot agent becomes a deterministic rule-based responder.
6. Do NOT implement real authentication security. This is intentionally simplified for zero-dependency local/demo usage, not hardened multi-tenant SaaS.
7. Do NOT touch rgc CLI (`rgc/checkers/`, `rgc/cli.py`) or SDK code paths that are not imported at web boot — focus on API boot path and imported modules.
8. Do NOT change frontend UI code — frontend must work without any modifications.

## Functional Requirements

### FR-1: In-memory + JSON-file-backed persistence layer (no SQL)
- Replace `releasegraph/database.py` with a `Store` class using nested Python dicts/lists and atomic `json.dump` + `os.replace` writes.
- All write operations auto-flush to the JSON file path; reads come from in-memory dict with lazy load from JSON on first access.
- Store auto-seeds: org + 5 demo users, ecommerce + streaming projects, services, releases, incidents, audit entries — the same seeded data shape as before.
- Data shape is compatible enough with `api.py` route handlers that every existing endpoint continues to return 200 JSON matching what the React UI expects (or close enough for UX to work).
- Configurable path via `RELEASEGRAPH_STORE_PATH` env var; default `./data/releasegraph-store.json`.
- Auto-create parent dir.

### FR-2: Simplified auth without bcrypt/jose/SQL
- Replace `releasegraph/auth.py`:
  - Remove bcrypt password hashing.
  - Remove JWT jose token signing/verification and DB user lookup for every request.
  - Tokens become opaque signed session tokens: `base64(user_id + "." + email + "." + role + "." + issued_at + "." + HMAC_SHA256(key, payload))`. Use Python stdlib only (`hmac`, `hashlib`, `base64`, `json`, `time`).
  - The secret key is read from `JWT_SECRET` env var (reuse this name for familiarity) but do NOT require `python-jose`.
  - `get_current_user` dependency decodes the HMAC token, looks up user in in-memory store, returns a user-like object (TypedDict, no ORM).
  - Password verification: compare SHA-256 of submitted password against stored SHA-256 of demo passwords. This is intentionally *not* bcrypt (zero-dep requirement dominates security).
  - `require_roles` dependency still gates routes by role enum strings — logic preserved.
- Frontend login flow works unchanged (calls `/api/auth/login`, gets `access_token`, stores in `localStorage`, uses `Authorization: Bearer <token>`).

### FR-3: Remove all external network calls
- `releasegraph/ai_layer.py`: `llm_enabled()` returns `False` always; `enrich_issues` is identity; `complete_from_tools` returns deterministic canned strings. No `httpx.Client`.
- `releasegraph/checkout_failure.py`, `checkout_incidents.py`, `shop_status.py`: stub all functions to return safe pre-populated dicts indicating "shop unavailable, skipping" — no `httpx.Client`.
- Remove all `import httpx` from runtime import paths of the API server.
- HTTPX can remain a listed dependency if still needed by other import-lazy modules, but the API server boot path + normal endpoint requests must not instantiate or use `httpx.Client`.

### FR-4: Remove SQLAlchemy, DB lookups, Postgres extras from runtime
- `releasegraph/models.py`: Remove SQLAlchemy import + `Base` usage entirely; replace models with `TypedDict` or `dataclass` representations used by the new store layer. Keep enum classes (`UserRole`, `ReleaseStatus`, etc.) since they have no DB dependency and are referenced throughout.
- Every route in `releasegraph/api.py` that previously used `db: Annotated[Session, Depends(get_db)]` — replace with store access: `store: Annotated[Store, Depends(get_store)]`.
- Replace SQLAlchemy `select(Model).where(...).scalars().all()` patterns with equivalent dict/list lookups in store.
- Remove `releasegraph/seed.py` DB seeding with SQLAlchemy sessions; seed logic moves into `Store.__init__` / `Store._seed_defaults()` for fresh JSON files.
- In `main.py`: lifespan no longer calls `init_db()`; it calls `store.ensure_seeded()`. Remove import of `init_db`/`database.py` entirely.

### FR-5: Single-command startup, zero external service required
- `python -m releasegraph.cli serve_api` must start successfully with **no env vars set, no Postgres, no plugin, no network**. Confirm no imports fail.
- Startup works offline (disable network, server still boots).
- Startup succeeds even if all of these are missing: `DATABASE_URL`, `JWT_SECRET` (falls back to dev secret), `GROQ_API_KEY`, all shop URLs.
- Railway `railway.json` env defaults are updated: `DATABASE_URL` and Postgres extras install are marked optional; no plugin is *required*. The store path is declared (`RELEASEGRAPH_STORE_PATH=./data/releasegraph-store.json`) with a warning note about ephemeral disk.

### FR-6: Session persistence across reloads/restarts
- Across browser hard reload (Ctrl+Shift+R): the React app's `localStorage.rgc_token` remains valid; the backend still recognizes the token (because HMAC key on server is stable across reloads, and user still exists in store).
- Across server restart:
  1. Server writes store to JSON on every write.
  2. After restart, server reads JSON file, so user/project/release records persist.
  3. Tokens remain valid because the HMAC key (JWT_SECRET) is the same env var as before restart.
- If HMAC key changes across restart, all tokens are invalidated (user must re-login) — this is acceptable, documented behavior.

### FR-7: Simplified deployment artifacts
- Remove `[postgres]` extras from install requirements in `railway.json` build and `Dockerfile` (still install but not required; if `pip install -e ".[postgres]"` fails, fallback `pip install -e "."` is kept).
- `railway.json` env var `DATABASE_URL` optional with note "Ignored. Uses JSON file store."; remove `JWT_SECRET: required=true` because zero-dep mode must boot with a fallback.
- Add `RELEASEGRAPH_STORE_PATH` env var to `railway.json` with default path and note.
- Dockerfile: no longer needs `libpq-dev`, `libssl-dev` for psycopg2. Keep `build-essential` only if still needed (we shouldn't need it).
- `Procfile` start command stays the same.

### FR-8: End-to-end runtime tests
- Write new test functions:
  1. Start server, login, hit `/api/auth/me` → 200 with user info.
  2. Hard reload simulation: token stored, new API client hits `/me` again → same user.
  3. Server restart simulation: write store JSON, kill in-memory store, reload, confirm users/projects still exist.
  4. Offline mode: no httpx client creation traced during login + dashboard endpoints.
- Also run existing smoke tests where still applicable.

## Non-Functional Requirements

### NFR-1: Zero external processes required
- Net new dependencies: 0. Existing deps that are no longer used (SQLAlchemy, jose, bcrypt, psycopg2) remain in `pyproject.toml` for backward compatibility of CLI/other code paths if present, but API server boot path imports must not use them, so missing them on a minimal install still boots.

### NFR-2: Backward-compatible request/response shapes
- Every route called by the React app (login, me, list_projects, graph releases, incidents, audits, readiness, release detail, copilot question) returns HTTP 200 with JSON shapes the UI can render without JavaScript errors.

### NFR-3: Deterministic behavior
- The simplified store + stubbed LLM/shop yields the same demo data on every fresh boot.

### NFR-4: Deployment simplification
- A developer should be able to: `pip install -e "." && python -m releasegraph.cli serve_api` → visit `http://localhost:8000` → login → click around — in under 2 minutes, **without installing Node, npm, or a DB** (the built frontend is still served from `web/dist` as before, but for full zero-dep, a developer can skip the npm build and rely on prebuilt or accept no static assets).

### NFR-5: Security posture is intentionally relaxed, and documented
- Passwords stored in JSON as SHA-256 hex of the plaintext; no salt, no bcrypt. Tokens signed with HMAC-SHA256 of a configurable secret. Document that this is NOT for production SaaS use, it's for single-user zero-dependency demos.

## Constraints

1. Frontend code in `web/src/**` must **not** be modified. Zero changes.
2. `python -m releasegraph.cli serve_api` remains the entry command.
3. Server still honors `$PORT` env var for Railway, defaults to 8000.
4. Existing route paths (e.g. `/api/auth/login`, `/api/projects`, `/api/graph`, `/health`) remain unchanged.
5. Env vars: `DATABASE_URL`, `JWT_SECRET`, `PORT`, `GROQ_API_KEY`, `CORS_ORIGINS` names are not renamed (backward-compat for anyone who already set them).

## Dependencies

Python standard library only for the new store/auth layers. Any existing third-party package can still be listed in `pyproject.toml` for other code paths, but the API server boot must not crash if `sqlalchemy`, `jose`, `bcrypt`, `psycopg2`, `httpx` are absent (lazy import or guard).

## Assumptions

1. Demo password `admin123!`/etc. remains the same. Stored as SHA-256 in seeded JSON.
2. Railway ephemeral disk: JSON file will be wiped on restart unless a volume is attached. Acceptable; documented.
3. Frontend `localStorage` already persists `rgc_token` across page reloads — no frontend change needed.
4. Users requesting this change do NOT require real SaaS-grade security.
5. rgc-specific modules may still import sqlalchemy via lazy paths; we guard only the API server import chain.

## Open Questions

None. All assumptions are accepted defaults per requirements.

## Acceptance Criteria

### rule AC-1: No SQLAlchemy import or usage on API boot path.
- Observable: Running `python -c "import releasegraph.main"` in an environment where `sqlalchemy` is force-uninstalled does NOT raise `ModuleNotFoundError: No module named 'sqlalchemy'`. Same check for `bcrypt` and `jose`.
- Evidence source: `RunCommand` + fresh isolated module import attempt.

### rule AC-2: No Postgres or plugin required to boot.
- Observable: Running `PORT=9500 python -m releasegraph.cli serve_api` with NO env vars at all → `/health` returns HTTP 200.
- Evidence source: curl on `/health`.

### rule AC-3: Session tokens survive client-side localStorage reload and new HTTP requests.
- Observable: POST `/api/auth/login` with admin credentials → returns `access_token`. Store token. GET `/api/auth/me` using token → HTTP 200 returns `admin@acme.demo` user. Simulate reload by making a second identical `/me` call in a new python process that shares no state → same result.
- Evidence source: curl/httpx requests.

### rule AC-4: Server restart persistence for seeded demo data + writes.
- Observable: Start server, hit endpoint that mutates store (e.g. create release via API). Stop server. Restart. GET `/api/projects/{id}/releases` includes the newly created release.
- Evidence source: Two consecutive start/write/restart/read test runs.

### rule AC-5: Zero external network calls on common UI flows (login, dashboard, project list, graph, readiness, audits, incidents, copilot ask).
- Observable: Monkey-patch `socket.socket.connect` or wrap `httpx.Client.__init__` to raise if called during 10 endpoint calls. No network calls should fire.
- Evidence source: Unit test with patched socket/httpx counting calls = 0.

### rule AC-6: Railway deployment no longer requires Postgres plugin or Groq keys.
- Observable: `railway.json` env block has no `required=true` entries. `DATABASE_URL` has description "Ignored (JSON store)". No mention of Postgres plugin as required. No `[postgres]` extras install as hard requirement.
- Evidence source: `Read` on `railway.json`, `Dockerfile`, `README.md`.

### rule AC-7: Login flow works without bcrypt or jose installed.
- Observable: Same as AC-1 but exercise login + token verification to confirm zero usage of those packages.
- Evidence source: Import + login test under blocked imports.

### rule AC-8: JSON store file path works and is configurable.
- Observable: `RELEASEGRAPH_STORE_PATH=/tmp/rgc-test-store.json PORT=9501 python -m releasegraph.cli serve_api` → server boots and `/tmp/rgc-test-store.json` is created on first write/read.
- Evidence source: File exists after boot, contains valid JSON.

### rubric AC-9: Code maintainability & endpoint coverage
- Dimension: Readability, modularity, and completeness of endpoint rewrites.
- Scale: 0 (nothing works / spaghetti) — 2 (clean store+auth abstraction, every React-called endpoint returns usable JSON).
- Pass threshold: ≥ 2.
- Evidence source: Code review + runtime curl spot checks for all 10 key endpoints.

### rubric AC-10: Deployment simplification quality
- Dimension: Clarity and correctness of docs + single-command usability.
- Scale: 0 (still requires plugins/DB) — 2 (`pip install -e "." && serve_api` just works, README updated to match).
- Pass threshold: ≥ 2.
- Evidence source: README review + actual single-command boot test.
