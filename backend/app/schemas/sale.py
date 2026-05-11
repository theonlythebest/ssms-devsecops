"""Sales schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


class SaleItemCreate(BaseModel):
    product_name: str
    quantity: int = Field(ge=1, default=1)
    unit_price: float = Field(ge=0)


class SaleCreate(BaseModel):
    cashier: str = "system"
    items: List[SaleItemCreate]
    status: Literal["completed", "refunded", "cancelled"] = "completed"


class SaleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cashier: str
    total: float
    status: str
    is_refund: bool
    created_at: datetime
    items: List[SaleItemOut] = []


class SaleKPI(BaseModel):
    total_revenue: float
    total_sales: int
    refund_count: int
    refund_rate: float
    average_basket: float
    revenue_by_day: dict
