"""Aggregate dashboard service — combines every module into one summary."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.cctv import CCTVEvent
from app.models.order import WebOrder
from app.models.sale import Sale
from app.schemas.alert import DashboardSummary
from app.services import cctv_service, sales_service, stock_service
from app.utils.logger import security_monitor


def build_summary(db: Session) -> DashboardSummary:
    sales_kpi = sales_service.compute_kpi(db)
    stock_kpi = stock_service.compute_kpi(db)
    cctv_anomalies = len(cctv_service.detect_anomalies(db))

    web_orders = db.query(WebOrder).count()
    web_revenue = sum(
        o.total or 0.0 for o in db.query(WebOrder).filter(WebOrder.status != "cancelled").all()
    )

    open_alerts = db.query(Alert).filter(Alert.resolved.is_(False)).count()
    anomaly_count = (
        db.query(Alert)
        .filter(Alert.severity.in_(["warning", "critical"]))
        .count()
    )

    security_status = "QUARANTINED" if security_monitor.quarantined else "OK"

    return DashboardSummary(
        total_revenue=sales_kpi.total_revenue,
        total_sales=sales_kpi.total_sales,
        refund_rate=sales_kpi.refund_rate,
        expired_products=stock_kpi.expired_count,
        near_expiry_products=stock_kpi.near_expiry_count,
        low_stock_alerts=stock_kpi.low_stock_count,
        cctv_anomalies=cctv_anomalies,
        web_orders=web_orders,
        web_revenue=round(web_revenue, 2),
        anomaly_count=anomaly_count,
        open_alerts=open_alerts,
        security_status=security_status,
    )


def list_recent_alerts(db: Session, limit: int = 25):
    return (
        db.query(Alert)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
