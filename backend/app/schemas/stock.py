"""Stock schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class StockItemCreate(BaseModel):
    name: str
    barcode: Optional[str] = None
    category: str = "general"
    quantity: int = Field(ge=0, default=0)
    low_stock_threshold: int = Field(ge=0, default=5)
    unit_price: float = Field(ge=0, default=0.0)
    expiry_date: Optional[date] = None


class StockItemUpdate(BaseModel):
    quantity: Optional[int] = Field(default=None, ge=0)
    low_stock_threshold: Optional[int] = Field(default=None, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    expiry_date: Optional[date] = None


class StockItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    barcode: Optional[str] = None
    category: str
    quantity: int
    low_stock_threshold: int
    unit_price: float
    expiry_date: Optional[date] = None
    updated_at: datetime
    days_remaining: Optional[int] = None
    is_expired: bool = False
    is_near_expiry: bool = False
    is_low_stock: bool = False


class StockKPI(BaseModel):
    total_items: int
    total_units: int
    expired_count: int
    near_expiry_count: int
    low_stock_count: int
    waste_rate: float
