"""CCTV analytics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.cctv import CCTVEventCreate, CCTVEventOut, LayoutSuggestion, ZoneStat
from app.services import cctv_service

router = APIRouter(prefix="/cctv", tags=["cctv"])


@router.post("/events", response_model=CCTVEventOut, status_code=201)
def record(
    payload: CCTVEventCreate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    return cctv_service.record_event(db, payload)


@router.get("/events", response_model=list[CCTVEventOut])
def list_events(
    zone: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return cctv_service.list_events(db, zone=zone, limit=limit)


@router.get("/zones", response_model=list[ZoneStat])
def zones(db: Session = Depends(get_db)):
    return cctv_service.per_zone_stats(db)


@router.get("/layout", response_model=LayoutSuggestion)
def layout(db: Session = Depends(get_db)):
    return cctv_service.layout_suggestion(db)


@router.get("/anomalies")
def anomalies(db: Session = Depends(get_db)):
    return cctv_service.detect_anomalies(db)
