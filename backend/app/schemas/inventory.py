"""Inventory log schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class InventoryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_name: str
    barcode: Optional[str] = None
    action: str
    quantity_change: int
    quantity_after: int
    username: Optional[str] = None
    timestamp: datetime