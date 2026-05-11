"""Sales analytics derived 100% from existing Sale / SaleItem data.

This module owns no state of its own — it's purely read-side aggregation
on top of the rows that `sales_service` already produces. That keeps the
write path single-sourced (stock_service → sales_service) and the read
path side-effect-free.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.sale import Sale, SaleItem


# ---------------------------------------------------------------------------
# Revenue timeline (hour or day buckets, with zero-fill so the chart line
# is continuous even when there are gaps between sales)
# ---------------------------------------------------------------------------
def revenue_timeline(
    db: Session, hours: int = 24, bucket: str = "hour"
) -> list[dict]:
    """Revenue + sale-count grouped by hour (default) or day."""
    if bucket not in {"hour", "day"}:
        bucket = "hour"

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    sales = (
        db.query(Sale)
        .filter(Sale.status == "completed")
        .filter(Sale.created_at >= cutoff)
        .all()
    )

    def floor(dt: datetime) -> datetime:
        if bucket == "day":
            return datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo)
        return dt.replace(minute=0, second=0, microsecond=0)

    raw: dict[datetime, dict] = {}
    for s in sales:
        if not s.created_at:
            continue
        key = floor(s.created_at)
        b = raw.setdefault(key, {"revenue": 0.0, "sales_count": 0})
        b["revenue"] += s.total or 0.0
        b["sales_count"] += 1

    # Zero-fill so the chart shows a continuous time axis.
    step = timedelta(days=1) if bucket == "day" else timedelta(hours=1)
    cursor = floor(cutoff)
    end = floor(now)
    out: list[dict] = []
    while cursor <= end:
        b = raw.get(cursor, {"revenue": 0.0, "sales_count": 0})
        out.append(
            {
                "bucket": cursor.isoformat(),
                "revenue": round(b["revenue"], 2),
                "sales_count": b["sales_count"],
            }
        )
        cursor += step
    return out


# ---------------------------------------------------------------------------
# Top sellers (units + revenue, in a rolling window)
# ---------------------------------------------------------------------------
def top_sellers(db: Session, limit: int = 10, hours: int = 24) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = (
        db.query(SaleItem)
        .join(Sale)
        .filter(Sale.status == "completed", Sale.created_at >= cutoff)
        .all()
    )
    units: Counter[str] = Counter()
    revenue: dict[str, float] = defaultdict(float)
    for it in items:
        units[it.product_name] += it.quantity
        revenue[it.product_name] += it.line_total or 0.0
    return [
        {"product": name, "units": qty, "revenue": round(revenue[name], 2)}
        for name, qty in units.most_common(limit)
    ]


# ---------------------------------------------------------------------------
# Hourly heatmap (0-23) over the last N days
# ---------------------------------------------------------------------------
def sales_heatmap(db: Session, days: int = 7) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sales = (
        db.query(Sale)
        .filter(Sale.status == "completed", Sale.created_at >= cutoff)
        .all()
    )
    by_hour: dict[int, dict] = {h: {"sales": 0, "revenue": 0.0} for h in range(24)}
    for s in sales:
        if s.created_at:
            h = s.created_at.hour
            by_hour[h]["sales"] += 1
            by_hour[h]["revenue"] += s.total or 0.0
    return [
        {"hour": h, "sales": by_hour[h]["sales"], "revenue": round(by_hour[h]["revenue"], 2)}
        for h in range(24)
    ]


# ---------------------------------------------------------------------------
# Realtime feed (counters + last few sales)
# ---------------------------------------------------------------------------
def realtime_feed(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    one_min_ago = now - timedelta(minutes=1)
    five_min_ago = now - timedelta(minutes=5)
    one_hour_ago = now - timedelta(hours=1)

    base = db.query(Sale).filter(Sale.status == "completed")

    sales_last_minute = base.filter(Sale.created_at >= one_min_ago).count()
    sales_last_5min = base.filter(Sale.created_at >= five_min_ago).count()
    last_hour_sales = base.filter(Sale.created_at >= one_hour_ago).all()
    sales_last_hour = len(last_hour_sales)
    revenue_last_hour = sum(s.total or 0.0 for s in last_hour_sales)

    latest = (
        db.query(Sale)
        .filter(Sale.status == "completed")
        .order_by(Sale.created_at.desc())
        .limit(8)
        .all()
    )
    latest_payload = []
    for s in latest:
        first_items = list(s.items)[:3]
        products = ", ".join(i.product_name for i in first_items) or "—"
        latest_payload.append(
            {
                "id": s.id,
                "products": products,
                "item_count": len(s.items),
                "total": round(s.total or 0.0, 2),
                "cashier": s.cashier,
                "timestamp": s.created_at.isoformat() if s.created_at else None,
            }
        )

    # scans_per_minute uses the 5-minute window for a smoother number than 1m
    scans_per_minute = round(sales_last_5min / 5.0, 2)

    return {
        "now": now.isoformat(),
        "sales_last_minute": sales_last_minute,
        "sales_last_5_minutes": sales_last_5min,
        "sales_last_hour": sales_last_hour,
        "revenue_last_hour": round(revenue_last_hour, 2),
        "scans_per_minute": scans_per_minute,
        "latest_sales": latest_payload,
    }