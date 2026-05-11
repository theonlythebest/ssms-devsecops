"""Promotion engine — detect trends, suggest discounts and bundles."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.sale import Sale, SaleItem
from app.models.stock import StockItem


SEASONAL_EVENTS = {
    "ramadan": ["Milk 1L", "Yogurt", "Cheese", "Pasta", "Olive Oil"],
    "summer": ["Soda 1.5L", "Water 1.5L", "Tomato", "Salmon"],
    "winter": ["Coffee", "Tea", "Cereal"],
    "back_to_school": ["Cereal", "Yogurt", "Apple", "Banana"],
}


def historical_top_sellers(db: Session, days: int = 14) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(SaleItem)
        .join(Sale)
        .filter(Sale.created_at >= cutoff, Sale.status == "completed")
        .all()
    )
    counter: Counter[str] = Counter()
    for r in rows:
        counter[r.product_name] += r.quantity
    return [
        {"product": name, "units_sold": qty}
        for name, qty in counter.most_common(10)
    ]


def near_expiry_discount_suggestions(db: Session, near_days: int = 5) -> list[dict]:
    today = date.today()
    items = (
        db.query(StockItem)
        .filter(StockItem.expiry_date.isnot(None))
        .all()
    )
    suggestions: list[dict] = []
    for it in items:
        if it.expiry_date is None:
            continue
        days_left = (it.expiry_date - today).days
        if 0 <= days_left <= near_days and it.quantity > 0:
            discount = 50 if days_left <= 1 else 30 if days_left <= 3 else 15
            suggestions.append(
                {
                    "product": it.name,
                    "days_left": days_left,
                    "stock": it.quantity,
                    "suggested_discount_pct": discount,
                    "reason": "near-expiry — apply discount to reduce waste",
                }
            )
    return suggestions


def bundle_suggestions(db: Session) -> list[dict]:
    """Find products frequently bought together (basket co-occurrence)."""
    sales = db.query(Sale).filter(Sale.status == "completed").all()
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for s in sales:
        names = sorted({i.product_name for i in s.items})
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pair_counts[(names[i], names[j])] += 1
    top = sorted(pair_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return [
        {"bundle": list(pair), "frequency": count, "suggestion": "10% off when bought together"}
        for pair, count in top
        if count >= 2
    ]


def seasonal_event(event: str) -> dict:
    event = event.lower()
    if event not in SEASONAL_EVENTS:
        return {
            "event": event,
            "supported": False,
            "available": list(SEASONAL_EVENTS.keys()),
        }
    return {
        "event": event,
        "supported": True,
        "promoted_products": SEASONAL_EVENTS[event],
        "suggestion": f"Run a themed campaign with featured aisle near entrance for {event}.",
    }
