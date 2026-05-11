"""CCTV schemas (GDPR-safe — no personal identifiers)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CCTVEventCreate(BaseModel):
    zone: str
    people_count: int = Field(ge=0, default=0)
    activity_score: int = Field(ge=0, default=0)
    note: Optional[str] = None


class CCTVEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    zone: str
    people_count: int
    activity_score: int
    note: Optional[str] = None
    timestamp: datetime


class ZoneStat(BaseModel):
    zone: str
    avg_people: float
    max_people: int
    avg_activity: float
    sample_count: int


class LayoutSuggestion(BaseModel):
    high_traffic_zones: list[str]
    low_traffic_zones: list[str]
    recommendation: str
