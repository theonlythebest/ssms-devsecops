"""Inventory activity log endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.inventory import InventoryLogOut
from app.services import inventory_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/logs", response_model=list[InventoryLogOut])
def list_logs(limit: int = 50, db: Session = Depends(get_db)):
    """Return inventory activity, newest first."""
    return inventory_service.list_logs(db, limit=limit)


@router.get("/logs/recent", response_model=list[InventoryLogOut])
def list_recent_logs(db: Session = Depends(get_db)):
    """Shortcut: last 10 movements (used by the dashboard widget)."""
    return inventory_service.list_logs(db, limit=10)