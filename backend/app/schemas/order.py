"""Web / Click & Collect order schemas (anonymous)."""
from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class WebOrderItemCreate(BaseModel):
    product_name: str
    quantity: int = Field(ge=1, default=1)


class WebOrderCreate(BaseModel):
    items: List[WebOrderItemCreate]


class WebOrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_name: str
    quantity: int
    unit_price: float
    line_total: float
    fulfillable: int


class WebOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    status: str
    total: float
    created_at: datetime
    items: List[WebOrderItemOut] = []


class WebAnalytics(BaseModel):
    total_orders: int
    peak_hour: int | None
    most_searched: list[dict]
    missing_products: list[str]
