"""SQLAlchemy engine and session."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from releasegraph.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
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
