"""Alert schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    severity: str
    message: str
    resolved: bool
    created_at: datetime


class DashboardSummary(BaseModel):
    total_revenue: float
    total_sales: int
    refund_rate: float
    expired_products: int
    near_expiry_products: int
    low_stock_alerts: int
    cctv_anomalies: int
    web_orders: int
    web_revenue: float
    anomaly_count: int
    open_alerts: int
    security_status: str
