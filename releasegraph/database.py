"""In-process store. No Postgres, no SQLite file, no DATABASE_URL.

SQLAlchemy still maps objects in this process using a shared in-memory SQLite
engine (StaticPool). Railway/Postgres plugins and DATABASE_URL are ignored.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

_log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


if os.getenv("DATABASE_URL"):
    _log.warning("DATABASE_URL is set but ignored — this app uses in-memory storage only.")

NORM_DB_URL = "sqlite://"
engine = create_engine(
    NORM_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from releasegraph import models  # noqa: F401 — register metadata

    Base.metadata.create_all(bind=engine)
    _log.info("In-memory store ready (no database server or disk file)")
