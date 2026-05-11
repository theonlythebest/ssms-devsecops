"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Centralized configuration for SSMS."""

    APP_NAME: str = "Smart Store Management System (SSMS)"
    APP_VERSION: str = "1.0.0"

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://ssms:ssms_secret@localhost:5432/ssms",
    )
    SQLITE_FALLBACK_URL: str = os.getenv(
        "SQLITE_FALLBACK_URL", "sqlite:///./ssms.db"
    )

    # Auth / JWT
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

    # Behavior flags
    SEED_ON_STARTUP: bool = _bool(os.getenv("SEED_ON_STARTUP"), default=True)

    # Security thresholds (cybersecurity module)
    WRITE_BURST_THRESHOLD: int = int(os.getenv("WRITE_BURST_THRESHOLD", "30"))
    AUTH_FAIL_THRESHOLD: int = int(os.getenv("AUTH_FAIL_THRESHOLD", "5"))
    REQUEST_BURST_THRESHOLD: int = int(os.getenv("REQUEST_BURST_THRESHOLD", "120"))


settings = Settings()
