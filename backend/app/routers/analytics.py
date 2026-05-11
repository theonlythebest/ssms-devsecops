"""Sales analytics endpoints — read-only aggregations on existing Sale data."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.analytics import (
    HeatmapPoint,
    RealtimeFeed,
    TimelinePoint,
    TopSeller,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/revenue-timeline", response_model=list[TimelinePoint])
def revenue_timeline(
    hours: int = Query(24, ge=1, le=720),
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    db: Session = Depends(get_db),
):
    """Revenue & sales-count grouped by hour or day, zero-filled."""
    return analytics_service.revenue_timeline(db, hours=hours, bucket=bucket)


@router.get("/top-sellers", response_model=list[TopSeller])
def top_sellers(
    limit: int = Query(10, ge=1, le=50),
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """Top products by units sold within the rolling window."""
    return analytics_service.top_sellers(db, limit=limit, hours=hours)


@router.get("/heatmap", response_model=list[HeatmapPoint])
def heatmap(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Sales-by-hour-of-day heatmap, useful to spot peak periods."""
    return analytics_service.sales_heatmap(db, days=days)


@router.get("/realtime", response_model=RealtimeFeed)
def realtime(db: Session = Depends(get_db)):
    """Live counters + the latest sales (intended for fast-poll widgets)."""
    return analytics_service.realtime_feed(db)