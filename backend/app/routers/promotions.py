"""Promotion engine endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import promotions_service

router = APIRouter(prefix="/promotions", tags=["promotions"])


@router.get("/top-sellers")
def top_sellers(days: int = 14, db: Session = Depends(get_db)):
    return promotions_service.historical_top_sellers(db, days=days)


@router.get("/discounts")
def near_expiry_discounts(db: Session = Depends(get_db)):
    return promotions_service.near_expiry_discount_suggestions(db)


@router.get("/bundles")
def bundles(db: Session = Depends(get_db)):
    return promotions_service.bundle_suggestions(db)


@router.get("/seasonal/{event}")
def seasonal(event: str):
    return promotions_service.seasonal_event(event)
