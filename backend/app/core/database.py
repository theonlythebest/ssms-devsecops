"""Database engine + session.

Tries PostgreSQL first; if unavailable, falls back transparently to SQLite so
the application never crashes during local development or first boot.
"""
from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger("ssms.db")


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def _make_engine(url: str) -> Engine:
    """Create a SQLAlchemy engine with sensible defaults for the URL scheme."""
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_engine(url, pool_pre_ping=True, future=True)


def _resolve_engine() -> tuple[Engine, str]:
    """Pick PostgreSQL if reachable, else SQLite fallback."""
    primary = settings.DATABASE_URL
    fallback = settings.SQLITE_FALLBACK_URL

    try:
        engine = _make_engine(primary)
        with engine.connect() as conn:  # eager connect to validate
            conn.exec_driver_sql("SELECT 1")
        logger.info("Connected to primary database: %s", primary.split("@")[-1])
        return engine, primary
    except (OperationalError, SQLAlchemyError, Exception) as exc:  # pragma: no cover
        logger.warning(
            "Primary database unavailable (%s); falling back to SQLite.",
            exc.__class__.__name__,
        )

    engine = _make_engine(fallback)
    return engine, fallback


engine, ACTIVE_DATABASE_URL = _resolve_engine()
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def init_db() -> None:
    """Create all tables (idempotent)."""
    # Importing here ensures models are registered with Base.metadata
    from app.models import alert, cctv, inventory_log, order, sale, stock, user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()