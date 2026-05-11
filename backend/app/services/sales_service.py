"""Sales business logic + anomaly detection."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sale import Sale, SaleItem
from app.models.stock import StockItem
from app.schemas.sale import SaleCreate, SaleItemCreate, SaleKPI
from app.utils.logger import logger, persist_alert

HIGH_VALUE_THRESHOLD = 500.0
NIGHT_WINDOW = (0, 5)
REFUND_BURST_WINDOW = timedelta(hours=1)
REFUND_BURST_LIMIT = 4


def _detect_anomalies(db: Session, sale: Sale) -> None:
    now = sale.created_at or datetime.now(timezone.utc)

    if sale.total >= HIGH_VALUE_THRESHOLD:
        persist_alert(db, "anomaly", "warning",
                      f"High-value transaction: sale #{sale.id} = {sale.total:.2f}")

    hour = now.hour
    if NIGHT_WINDOW[0] <= hour <= NIGHT_WINDOW[1]:
        persist_alert(db, "anomaly", "warning",
                      f"Time-based anomaly: sale #{sale.id} at {hour:02d}:00 (off-hours)")

    if sale.status == "refunded":
        recent = (db.query(func.count(Sale.id))
                    .filter(Sale.status == "refunded",
                            Sale.created_at >= now - REFUND_BURST_WINDOW)
                    .scalar() or 0)
        if recent >= REFUND_BURST_LIMIT:
            persist_alert(db, "anomaly", "critical",
                          f"Frequent refunds detected: {recent} in last hour")

    if sale.status == "cancelled":
        recent = (db.query(func.count(Sale.id))
                    .filter(Sale.status == "cancelled",
                            Sale.created_at >= now - timedelta(hours=1))
                    .scalar() or 0)
        if recent >= REFUND_BURST_LIMIT:
            persist_alert(db, "anomaly", "warning",
                          f"Repeated cancellations: {recent} in last hour")


def create_sale(db: Session, payload: SaleCreate) -> Sale:
    if not payload.items:
        raise HTTPException(status_code=400, detail="Sale must contain at least one item")
    sale = Sale(cashier=payload.cashier, status=payload.status,
                is_refund=(payload.status == "refunded"))
    total = 0.0
    for item in payload.items:
        line = round(item.unit_price * item.quantity, 2)
        total += line
        sale.items.append(SaleItem(
            product_name=item.product_name, quantity=item.quantity,
            unit_price=item.unit_price, line_total=line,
        ))
    sale.total = round(total, 2)
    db.add(sale); db.commit(); db.refresh(sale)
    _detect_anomalies(db, sale)
    logger.info("Sale recorded: #%s total=%.2f status=%s", sale.id, sale.total, sale.status)
    return sale


def record_scan_sale(db: Session, product: StockItem, *,
                     quantity: int = 1, username: str | None = None) -> Sale:
    payload = SaleCreate(
        cashier=username or "system", status="completed",
        items=[SaleItemCreate(product_name=product.name, quantity=quantity,
                              unit_price=product.unit_price)],
    )
    sale = create_sale(db, payload)
    logger.info("Scan-sale: #%s product=%s qty=%d revenue=%.2f cashier=%s",
                sale.id, product.name, quantity, sale.total, sale.cashier)
    return sale


def list_sales(db: Session, limit: int = 100) -> list[Sale]:
    return db.query(Sale).order_by(Sale.created_at.desc()).limit(limit).all()


def get_sale(db: Session, sale_id: int) -> Sale:
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


def compute_kpi(db: Session) -> SaleKPI:
    sales = db.query(Sale).all()
    total_sales = len(sales)
    total_revenue = sum(s.total for s in sales if s.status == "completed")
    refund_count = sum(1 for s in sales if s.status == "refunded")
    refund_rate = (refund_count / total_sales) if total_sales else 0.0
    completed = sum(1 for s in sales if s.status == "completed")
    avg_basket = total_revenue / max(1, completed)
    by_day: dict[str, float] = defaultdict(float)
    for s in sales:
        if s.status == "completed" and s.created_at:
            by_day[s.created_at.date().isoformat()] += s.total
    return SaleKPI(
        total_revenue=round(total_revenue, 2), total_sales=total_sales,
        refund_count=refund_count, refund_rate=round(refund_rate, 4),
        average_basket=round(avg_basket, 2),
        revenue_by_day=dict(sorted(by_day.items())),
    )