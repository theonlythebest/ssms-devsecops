"""SOC (Security Operations Center) endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.alert import AlertOut
from app.services import soc_service

router = APIRouter(prefix="/soc", tags=["soc"])


@router.get("/events", response_model=list[AlertOut])
def list_events(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return cybersecurity / SOC events only — newest first."""
    return soc_service.list_soc_events(db, limit=limit)


@router.get("/categories")
def categories():
    """List the categories the SOC feed accepts (read-only metadata)."""
    return {"categories": list(soc_service.SOC_CATEGORIES)}


@router.get("/severity-counts")
def severity_counts(db: Session = Depends(get_db)):
    """Open SOC events grouped by severity (for header badges)."""
    return soc_service.count_by_severity(db)