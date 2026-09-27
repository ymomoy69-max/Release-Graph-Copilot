# ReleaseGraph Zero-External-Dependencies — Implementation Tasks

## Task 1: Create the new JSON-backed in-memory `Store` class to replace SQLAlchemy engine/sessions
- **Priority**: high
- **Status**: pending
- **Maps to AC**: AC-1, AC-2, AC-4, AC-8
- **Files**: `releasegraph/store.py` (new), update `pyproject.toml` (optional — no changes needed)
- **Description**:
  - Implement `Store` with atomic JSON file read/write/replace, lazy seed, path from env `RELEASEGRAPH_STORE_PATH` default `./data/releasegraph-store.json`, auto-create parent dir.
  - Method shape roughly: `load()`, `save()`, `get_user(id)`, `get_user_by_email(email)`, `list_projects(org_id)`, `get_project(id)`, etc. Exact API mirrors what routes need.
  - Seed inside `_seed_defaults()`: org=acme, 5 demo users with role+email+full_name+sha256(password), ecommerce+streaming projects, services, releases, incidents, copilot proposals — matching existing demo data in fixtures/demo folders.
  - `get_store()` FastAPI dependency yields singleton store per request (no `Session`/connection open/close).
- **Test Requirements**:
  - **rule TR-1.1**: Store created at `RELEASEGRAPH_STORE_PATH=/tmp/x.json` → file created, valid JSON, contains 5 users, 2 projects.
  - **rule TR-1.2**: Store saved, killed in-memory, reloaded → users/projects still present.

## Task 2: Replace auth.py — HMAC-SHA256 tokens + SHA-256 passwords, zero third-party deps
- **Priority**: high
- **Status**: pending
- **Maps to AC**: AC-1, AC-3, AC-7
- **Files**: `releasegraph/auth.py` (replace)
- **Description**:
  - Remove imports of `bcrypt`, `jose`, `sqlalchemy`, `releasegraph.database`, `releasegraph.models.User`.
  - New `hash_password(plain)`: return `sha256(plain.encode()).hexdigest()`.
  - New `verify_password(plain, stored_hex)`: compare `hash_password(plain) == stored_hex`.
  - New `create_access_token(user_id, email, role)`: opaque token format `base64url(json_payload) + "." + base64url(hmac_sha256(key, payload))`. Payload includes `sub`, `email`, `role`, `iat`, `exp`. Uses `JWT_SECRET` from settings for HMAC key.
  - New `_decode_token(token)` → payload dict, or raise HTTPException on bad sig/expiry.
  - New `get_current_user(creds, store)` dependency: uses Store to look up the user.
  - Keep `require_roles(*roles)` logic, but returns TypedDict user instead of ORM User.
- **Test Requirements**:
  - **rule TR-2.1**: Force `bcrypt`/`jose` import to fail in isolated process; `import releasegraph.auth` works.
  - **rule TR-2.2**: Round-trip login: `create_access_token(5, "a@b.c", "ADMIN")` → decode → same fields. Tampered token → `_decode_token` raises.

## Task 3: Rewrite database.py to be Store + a thin shim, no SQLAlchemy imports at top level
- **Priority**: high
- **Status**: pending
- **Maps to AC**: AC-1, AC-2
- **Files**: `releasegraph/database.py` (replace), `releasegraph/models.py` (gut — keep enums only), remove `Base`/`engine`/`SessionLocal`/`get_db`
- **Description**:
  - Remove top-level `create_engine`, `SessionLocal`, `Base`, `get_db`, `init_db`, `_ensure_sqlite_columns`.
  - `models.py`: keep only the Enums and convert remaining classes to TypedDicts or dataclasses without SQLAlchemy.
  - `database.py` exports ONLY re-exports from store (e.g., `get_store`) plus helper `init_db` as a no-op stub (for any old imports still referencing). Fail loudly on sqlalchemy import if possible, lazy import guard.
- **Test Requirements**:
  - **rule TR-3.1**: `import releasegraph.database` in a process without SQLAlchemy installed → no ModuleNotFoundError.
  - **rule TR-3.2**: `import releasegraph.models` no longer requires sqlalchemy.

## Task 4: Rewrite api.py — replace every `Depends(get_db)` / SQL query with Store lookups + non-SQL response builders
- **Priority**: highest
- **Status**: pending
- **Maps to AC**: AC-1, AC-2, AC-3, AC-4, AC-9
- **Files**: `releasegraph/api.py` (full refactor — largest single change)
- **Description**:
  - Delete `from sqlalchemy import ...`, `from sqlalchemy.orm import Session`, `from releasegraph.database import get_db`, `from releasegraph.models import <ORM models>` imports.
  - Replace imports with: `from releasegraph.auth import <new deps>`, `from releasegraph.store import Store, get_store`, `from releasegraph.models import <Enums and TypedDicts>`.
  - 40+ endpoints: replace each SQLAlchemy `select().where()` / `db.execute()` / `db.get()` / `db.add()` / `db.commit()` pattern with dict/list-based Store operations.
  - Preserve *exact* route paths, method verbs, request body schemas, and response shape keys (`access_token`, `email`, `role`, `releases`, `graph`, etc.) so the React frontend sees identical JSON.
  - Seed helpers previously in `seed.py` should be invoked by `store._seed_defaults()`.
- **Test Requirements**:
  - **rule TR-4.1**: `/api/auth/login` returns `{"access_token":"..."}` 200 for `admin@acme.demo / admin123!`.
  - **rule TR-4.2**: `/api/auth/me` with bearer token returns `{email, full_name, role}` 200.
  - **rule TR-4.3**: `/api/projects` 200 returns list with `[{slug:"ecommerce"}, {slug:"streaming"}]`.
  - **rule TR-4.4**: `/api/graph/:project_id` 200 returns `{nodes, links}`.
  - **rule TR-4.5**: `/api/releases/:project_id` 200 returns release list with status fields.
  - **rule TR-4.6**: `/api/readiness/:project_id` 200 returns readiness payload shape UI can render.

## Task 5: Stub all external network dependencies — Groq AI, shop gateway, storefront, incident sync
- **Priority**: high
- **Status**: pending
- **Maps to AC**: AC-5
- **Files**: `releasegraph/ai_layer.py`, `releasegraph/checkout_failure.py`, `releasegraph/checkout_incidents.py`, `releasegraph/shop_status.py`, `releasegraph/copilot/agent.py`, `releasegraph/analysis.py`
- **Description**:
  - `ai_layer.py`: `llm_enabled()` → `False`; `enrich_issues(issues)` → return `issues` unchanged; `complete_from_tools()` → return deterministic canned string "No LLM configured. ReleaseGraph findings above are the complete source of truth."
  - `checkout_failure.py`, `checkout_incidents.py`, `shop_status.py`: return empty/noop dicts without any `httpx.Client()` creation.
  - `copilot/agent.py`: rule-based answers that look up store data — never call `complete_from_tools` network.
  - Remove/guard any top-level `import httpx` that runs before a route is hit if possible.
- **Test Requirements**:
  - **rule TR-5.1**: `ai_layer.llm_enabled()` → False even if `GROQ_API_KEY` env var is set.
  - **rule TR-5.2**: Patching `socket.socket.connect` to raise during 10 standard endpoint calls → no calls, endpoints return 200.

## Task 6: Update main.py lifespan + imports — remove DB init, use Store ensure_seeded
- **Priority**: high
- **Status**: pending
- **Maps to AC**: AC-1, AC-2
- **Files**: `releasegraph/main.py`
- **Description**:
  - Remove imports of `releasegraph.database.init_db`, `releasegraph.seed.ensure_*` functions.
  - Lifespan: call `store.ensure_seeded()` instead; log counts of users/projects/releases.
  - Keep JWT warning but make it about zero-dep HMAC secret instead of "weak JWT dev default" message.
  - `/health` endpoint: drop `groq` True/False field (or always False) so import of ai_layer is safe.
- **Test Requirements**:
  - **rule TR-6.1**: `python -c "import releasegraph.main"` works in isolated env without sqlalchemy/bcrypt/jose.

## Task 7: Simplify deployment artifacts — remove DB/postgres plugin requirement, optional AI/shop notes
- **Priority**: medium
- **Status**: pending
- **Maps to AC**: AC-6, AC-10
- **Files**: `railway.json`, `Dockerfile`, `.env.example`, `releasegraph/config.py`, `README.md`
- **Description**:
  - `railway.json`: set `JWT_SECRET` to have a generated-looking fallback and mark it `required=false`; change DATABASE_URL description to "Ignored (JSON store)"; remove any [postgres] hard-install requirement; add `RELEASEGRAPH_STORE_PATH` env with default; comment out Postgres plugin recommendation (now optional).
  - `Dockerfile`: remove `libpq-dev / libssl-dev / libffi-dev` apt packages (no psycopg2 needed).
  - `.env.example`: comment out `DATABASE_URL` and swap example values with JSON store + HMAC secret notes.
  - `config.py`: keep variable names (backward compat) but remove any database_url usage in store layer.
  - `README.md`: Add a prominent new section **"Zero-Dependency Quick Start"** with one command. Add note that DB/plugin/AI are optional.
- **Test Requirements**:
  - **rule TR-7.1**: `railway.json` has zero `required=true` env entries.
  - **rule TR-7.2**: `Dockerfile` no longer lists `libpq-dev`.

## Task 8: Seed store from demo fixtures & provide demo data richness — projects/releases/incidents/graph services
- **Priority**: medium
- **Status**: pending
- **Maps to AC**: AC-4, AC-9
- **Files**: `releasegraph/store.py` seed function, possibly reference `fixtures/graph/deploy-graph.yaml` for nodes/links if helpful
- **Description**: Populate seeded store so key React pages look populated: at least 2 projects, 4 releases per project, 2 incidents per project, service graph nodes/links (10+ services), audit log entries, fix proposals, readiness presets. Enough for user to click around without hitting empty screens.
- **Test Requirements**:
  - **rule TR-8.1**: Seeded store → `/api/graph` returns ≥10 nodes + ≥15 links for ecommerce project.
  - **rule TR-8.2**: Seeded store → `/api/releases` returns ≥4 releases.
  - **rule TR-8.3**: Seeded store → `/api/incidents` returns ≥2 incidents.

## Task 9: End-to-end runtime & restart persistence tests
- **Priority**: high
- **Status**: pending
- **Maps to AC**: AC-2, AC-3, AC-4, AC-8
- **Files**: add a new local test module (or reuse tests/) if tests dir already exists — do not break existing tests
- **Description**: Using FastAPI TestClient (or subprocess+curl) run:
  1. Start app, login, fetch `/me` twice in separate clients to prove token works across clients.
  2. Post a new incident (or any mutating endpoint). Kill store, restart from JSON file. Re-fetch → new incident present.
  3. Verify zero httpx/socket network calls during the flows.
  4. Isolated env test: `PYTHONDONTWRITEBYTECODE=1` + minimal path (force sqlalchemy/jose/bcrypt/psycopg2 NOT importable) → import main + boot + login works.
- **Test Requirements**:
  - **rule TR-9.1**: Full E2E login → /me → list projects → create release.
  - **rule TR-9.2**: Kill/restart persistence of created release.
  - **rule TR-9.3**: Isolated environment boot + login test passes.

## Task 10: Regression test sweep
- **Priority**: medium
- **Status**: pending
- **Maps to AC**: All
- **Files**: existing `tests/` dir
- **Description**: Run whatever existing test subset still passes after the refactor. Update or disable DB-backed tests that require SQLAlchemy (since they test deleted functionality).
- **Test Requirements**:
  - **rubric TR-10.1**: ≥ 80% of non-DB tests still pass. Critical failures (imports, startup) blocked on Task 1-9.
