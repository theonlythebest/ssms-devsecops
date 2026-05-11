"""Web / Click & Collect endpoints (anonymous)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.order import WebAnalytics, WebOrderCreate, WebOrderOut
from app.services import orders_service

router = APIRouter(prefix="/orders", tags=["web-orders"])


@router.post("/", response_model=WebOrderOut, status_code=201)
def create_order(payload: WebOrderCreate, db: Session = Depends(get_db)):
    """Create an anonymous web/click-and-collect order."""
    return orders_service.create_order(db, payload)


@router.get("/", response_model=list[WebOrderOut])
def list_orders(limit: int = 100, db: Session = Depends(get_db)):
    return orders_service.list_orders(db, limit=limit)


@router.get("/analytics", response_model=WebAnalytics)
def analytics(db: Session = Depends(get_db)):
    return orders_service.analytics(db)


@router.get("/{public_id}", response_model=WebOrderOut)
def get_order(public_id: str, db: Session = Depends(get_db)):
    return orders_service.get_order(db, public_id)
