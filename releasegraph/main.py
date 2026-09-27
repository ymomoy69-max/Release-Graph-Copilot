"""ReleaseGraph Copilot API."""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from releasegraph.api import router
from releasegraph.config import settings
from releasegraph.database import init_db
from releasegraph.errors import http_exception_handler, validation_exception_handler
from releasegraph.seed import ensure_bootstrap_projects, ensure_demo_staff


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] request_id=%(request_id)s %(message)s",
)
logging.getLogger().addFilter(RequestIdFilter())
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestIdFilter())

_WEAK_JWT_DEFAULTS = {
    "dev-change-me-in-production",
    "change-me-use-long-random-string",
    "",
}

if (
    settings.environment == "production"
    and settings.jwt_secret.strip() in _WEAK_JWT_DEFAULTS
):
    logging.getLogger(__name__).warning(
        "SECURITY WARNING: JWT_SECRET is set to the weak dev default in ENVIRONMENT=production. "
        "Set JWT_SECRET to a long random string via the Railway dashboard before exposing this instance. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _logger = logging.getLogger(__name__)
    from releasegraph import database as _db_mod

    _scheme = _db_mod.NORM_DB_URL.split("://", 1)[0] if "://" in _db_mod.NORM_DB_URL else "unknown"
    _logger.info(
        "Starting ReleaseGraph lifespan: ENVIRONMENT=%s DEBUG=%s PORT(from_env)=%s DATABASE_scheme=%s CORS_count=%d",
        settings.environment,
        settings.debug,
        os.environ.get("PORT", "<unset>"),
        _scheme,
        len(settings.cors_origins),
    )
    try:
        init_db()
        _logger.info("init_db() completed")
    except Exception as exc:  # noqa: BLE001
        _logger.exception("init_db() FAILED: %s (check DATABASE_URL, Postgres plugin network, and psycopg2 install)", exc)
    try:
        ensure_demo_staff()
        _logger.info("ensure_demo_staff() completed")
    except Exception as exc:  # noqa: BLE001
        _logger.exception("ensure_demo_staff() FAILED (non-fatal; login may not work): %s", exc)
    try:
        ensure_bootstrap_projects()
        _logger.info("ensure_bootstrap_projects() completed")
    except Exception as exc:  # noqa: BLE001
        _logger.exception("ensure_bootstrap_projects() FAILED (non-fatal; demo projects missing): %s", exc)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get(settings.request_id_header) or uuid.uuid4().hex
    request.state.request_id = rid
    response = await call_next(request)
    response.headers[settings.request_id_header] = rid
    return response


from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.include_router(router)


@app.get("/health")
def health():
    from releasegraph.ai_layer import llm_enabled

    return {"status": "ok", "service": "releasegraph-api", "groq": llm_enabled()}


@app.get("/ready")
def ready():
    return {"status": "ready"}


# Serve built frontend if present
_web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _web_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_web_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        from fastapi import HTTPException

        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        # Serve static files from dist if present (favicon, etc.)
        candidate = _web_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_web_dist / "index.html")
