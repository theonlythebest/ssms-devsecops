"""Dashboard endpoints — aggregated views."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.alert import AlertOut, DashboardSummary
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(db: Session = Depends(get_db)):
    return dashboard_service.build_summary(db)


@router.get("/alerts", response_model=list[AlertOut])
def alerts(limit: int = 25, db: Session = Depends(get_db)):
    return dashboard_service.list_recent_alerts(db, limit=limit)
