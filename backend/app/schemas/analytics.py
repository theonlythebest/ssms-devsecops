"""Sales analytics schemas."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class TimelinePoint(BaseModel):
    bucket: str
    revenue: float
    sales_count: int


class TopSeller(BaseModel):
    product: str
    units: int
    revenue: float


class HeatmapPoint(BaseModel):
    hour: int
    sales: int
    revenue: float


class LatestSale(BaseModel):
    id: int
    products: str
    item_count: int
    total: float
    cashier: str
    timestamp: Optional[str] = None


class RealtimeFeed(BaseModel):
    now: str
    sales_last_minute: int
    sales_last_5_minutes: int
    sales_last_hour: int
    revenue_last_hour: float
    scans_per_minute: float
    latest_sales: List[LatestSale]