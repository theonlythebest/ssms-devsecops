"""Web / Click & Collect anonymous order model."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WebOrder(Base):
    __tablename__ = "web_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    items: Mapped[List["WebOrderItem"]] = relationship(
        "WebOrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class WebOrderItem(Base):
    __tablename__ = "web_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("web_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    line_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fulfillable: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1 = ok, 0 = stock missing

    order: Mapped["WebOrder"] = relationship("WebOrder", back_populates="items")
