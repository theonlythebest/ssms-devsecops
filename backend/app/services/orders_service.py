"""Web / Click & Collect business logic (anonymous orders)."""
from __future__ import annotations

import secrets
import string
from collections import Counter, defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.order import WebOrder, WebOrderItem
from app.models.stock import StockItem
from app.schemas.order import WebAnalytics, WebOrderCreate
from app.utils.logger import logger, persist_alert


def _new_public_id() -> str:
    return "WO-" + "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10)
    )


def create_order(db: Session, payload: WebOrderCreate) -> WebOrder:
    if not payload.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    order = WebOrder(public_id=_new_public_id(), status="pending")
    total = 0.0
    missing: list[str] = []

    for line in payload.items:
        stock = (
            db.query(StockItem).filter(StockItem.name == line.product_name).first()
        )
        unit_price = stock.unit_price if stock else 0.0
        line_total = round(unit_price * line.quantity, 2)
        total += line_total

        fulfillable = 1
        if not stock:
            fulfillable = 0
            missing.append(line.product_name)
        elif stock.quantity < line.quantity:
            fulfillable = 0
            missing.append(line.product_name)
        else:
            # decrement stock immediately for accepted orders
            stock.quantity -= line.quantity

        order.items.append(
            WebOrderItem(
                product_name=line.product_name,
                quantity=line.quantity,
                unit_price=unit_price,
                line_total=line_total,
                fulfillable=fulfillable,
            )
        )

    order.total = round(total, 2)
    if missing:
        order.status = "partial"
        persist_alert(
            db,
            "web",
            "warning",
            f"Web order {order.public_id} has missing/insufficient stock: {', '.join(missing)}",
        )
    else:
        order.status = "confirmed"

    db.add(order)
    db.commit()
    db.refresh(order)
    logger.info(
        "Web order %s created: total=%.2f status=%s", order.public_id, order.total, order.status
    )
    return order


def list_orders(db: Session, limit: int = 100) -> list[WebOrder]:
    return (
        db.query(WebOrder)
        .order_by(WebOrder.created_at.desc())
        .limit(limit)
        .all()
    )


def get_order(db: Session, public_id: str) -> WebOrder:
    o = db.query(WebOrder).filter(WebOrder.public_id == public_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return o


def analytics(db: Session) -> WebAnalytics:
    orders = db.query(WebOrder).all()
    total_orders = len(orders)

    # peak hour
    hour_counts: dict[int, int] = defaultdict(int)
    for o in orders:
        if o.created_at:
            hour_counts[o.created_at.hour] += 1
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

    # most searched / requested products
    product_counter: Counter[str] = Counter()
    for o in orders:
        for it in o.items:
            product_counter[it.product_name] += it.quantity
    most_searched = [
        {"product": name, "requested_units": qty}
        for name, qty in product_counter.most_common(5)
    ]

    # missing products = anything where demand > current stock
    missing: list[str] = []
    for name, demand in product_counter.items():
        stock = db.query(StockItem).filter(StockItem.name == name).first()
        if not stock or stock.quantity < demand:
            missing.append(name)

    return WebAnalytics(
        total_orders=total_orders,
        peak_hour=peak_hour,
        most_searched=most_searched,
        missing_products=missing,
    )
