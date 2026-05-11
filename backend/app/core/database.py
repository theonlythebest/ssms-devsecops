"""Database engine + session.

Primary target: MariaDB (via the mysql+pymysql driver).
If the primary database is unreachable (e.g. during cold-boot or local dev
without docker), the engine falls back transparently to a local SQLite file
so the application never crashes.
"""
from __future__ import annotations

import logging
import time
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger("ssms.db")


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def _is_mysql_like(url):
    return url.startswith("mysql") or url.startswith("mariadb")


def _is_sqlite(url):
    return url.startswith("sqlite")


def _make_engine(url):
    """Create a SQLAlchemy engine with sensible defaults for the URL scheme."""
    if _is_sqlite(url):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
        )

    if _is_mysql_like(url):
        # pool_pre_ping recycles stale conns; pool_recycle dodges MariaDB's
        # wait_timeout (~8h default).
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=10,
            max_overflow=20,
            future=True,
        )

    return create_engine(url, pool_pre_ping=True, future=True)


def _try_connect(url, retries=10, delay=2.0):
    """Try to connect to ``url`` with linear retries.

    Returns the live engine on success, ``None`` if every attempt fails.
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            engine = _make_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(
                "Connected to primary database on attempt %d/%d: %s",
                attempt, retries, url.split("@")[-1],
            )
            return engine
        except (OperationalError, SQLAlchemyError, Exception) as exc:
            last_exc = exc
            logger.warning(
                "DB connection attempt %d/%d failed (%s): %s",
                attempt, retries, exc.__class__.__name__, exc,
            )
            if attempt < retries:
                time.sleep(delay)

    logger.error(
        "Primary database unreachable after %d attempts. Last error: %s",
        retries, last_exc,
    )
    return None


def _resolve_engine():
    """Pick MariaDB if reachable, else SQLite fallback."""
    primary = settings.DATABASE_URL
    fallback = settings.SQLITE_FALLBACK_URL

    engine = _try_connect(primary)
    if engine is not None:
        return engine, primary

    logger.warning(
        "Falling back to SQLite at %s. This is intended for local/dev only.",
        fallback,
    )
    engine = _make_engine(fallback)
    return engine, fallback


engine, ACTIVE_DATABASE_URL = _resolve_engine()
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def active_backend_name():
    """Return a friendly label for the live engine."""
    url = ACTIVE_DATABASE_URL
    if _is_mysql_like(url):
        return "mariadb"
    if _is_sqlite(url):
        return "sqlite"
    return url.split(":", 1)[0]


def init_db():
    """Create all tables (idempotent)."""
    from app.models import alert, cctv, inventory_log, order, sale, stock, user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified on %s.", active_backend_name())


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
