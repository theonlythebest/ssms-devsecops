"""CCTV analytics model — GDPR-safe (NO personal data, only zone counts)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CCTVEvent(Base):
    __tablename__ = "cctv_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    people_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activity_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
