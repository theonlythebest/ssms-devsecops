"""Inventory activity log business logic."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.inventory_log import InventoryLog
from app.models.stock import StockItem


def record_log(
    db: Session,
    *,
    product: StockItem,
    action: str,
    quantity_change: int,
    username: str | None = None,
) -> InventoryLog:
    """Persist a single inventory movement entry.

    Called from `stock_service.scan_product` after the stock mutation so
    every scan endpoint (direct id or barcode) is automatically logged
    without duplicating the call.
    """
    entry = InventoryLog(
        product_name=product.name,
        barcode=product.barcode,
        action=action,
        quantity_change=quantity_change,
        quantity_after=product.quantity,
        username=username,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_logs(db: Session, limit: int = 50) -> list[InventoryLog]:
    """Return logs newest-first."""
    return (
        db.query(InventoryLog)
        .order_by(InventoryLog.timestamp.desc())
        .limit(limit)
        .all()
    )