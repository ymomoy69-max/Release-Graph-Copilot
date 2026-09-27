"""SQLAlchemy engine and session."""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from releasegraph.config import settings

_log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _normalize_db_url(url: str) -> str:
    """Normalize a DATABASE_URL so we accept both postgres:// and postgresql://
    schemes (the former is what Railway injects; SQLAlchemy 2.x needs the
    psycopg2 driver suffix set)."""
    import os as _os

    injected = url or _os.getenv("DATABASE_URL", "")
    if injected.startswith("postgres://"):
        return injected.replace("postgres://", "postgresql+psycopg2://", 1)
    if injected.startswith("postgresql://") and "+" not in injected.split(":", 1)[1].split("/", 1)[0]:
        # No driver specified; force psycopg2
        return injected.replace("postgresql://", "postgresql+psycopg2://", 1)
    return injected or "sqlite:///./data/releasegraph.db"


NORM_DB_URL = _normalize_db_url(settings.database_url)

connect_args = {"check_same_thread": False} if NORM_DB_URL.startswith("sqlite") else {}

_log.info(
    "Database URL loaded: scheme=%s present=%s",
    NORM_DB_URL.split("://", 1)[0] if "://" in NORM_DB_URL else "unknown",
    bool(NORM_DB_URL and "://" in NORM_DB_URL and "change-me" not in NORM_DB_URL),
)

_FALLBACK_SQLITE_URL = "sqlite:///./data/releasegraph.db"

try:
    engine = create_engine(NORM_DB_URL, connect_args=connect_args, future=True, pool_pre_ping=True)
    # Quick import-time smoke-test of the driver for Postgres URLs so we fail
    # fast with a clear error in Railway logs, not a cryptic 500 later.
    if NORM_DB_URL.startswith("postgresql"):
        _log.info("Postgres URL detected — verifying psycopg2 driver import…")
        import psycopg2  # noqa: F401

        _log.info("psycopg2 driver OK")
except Exception as _exc:  # noqa: BLE001
    _log.exception(
        "FAILED to create SQLAlchemy engine for scheme=%s: %s. FALLING BACK TO LOCAL SQLITE (data will not persist on Railway restart). Install the [postgres] extras and/or fix DATABASE_URL.",
        NORM_DB_URL.split("://", 1)[0] if "://" in NORM_DB_URL else "unknown",
        _exc,
    )
    NORM_DB_URL = _FALLBACK_SQLITE_URL
    connect_args = {"check_same_thread": False}
    engine = create_engine(NORM_DB_URL, connect_args=connect_args, future=True)
    _log.warning("Using FALLBACK engine: %s", NORM_DB_URL)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    insp = inspect(engine)
    wanted: dict[str, list[tuple[str, str]]] = {
        "projects": [
            ("workspace_path", "VARCHAR(1024) DEFAULT ''"),
            ("org_config_path", "VARCHAR(1024) DEFAULT ''"),
            ("readiness_presets_json", "TEXT DEFAULT '[]'"),
            ("production_release_id", "INTEGER"),
            ("workspace_synced_at", "DATETIME"),
        ],
        "fix_proposals": [("verify_message", "TEXT DEFAULT ''")],
        "services": [("source_path", "VARCHAR(1024) DEFAULT ''")],
        "releases": [("baseline_release_id", "INTEGER")],
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            if table not in insp.get_table_names():
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in columns:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def init_db() -> None:
    from releasegraph import models  # noqa: F401 — register metadata

    if settings.database_url.startswith("sqlite:///./"):
        import os
        os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
