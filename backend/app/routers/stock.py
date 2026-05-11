"""Stock + DLC endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.schemas.stock import StockItemCreate, StockItemOut, StockItemUpdate, StockKPI
from app.services import stock_service

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/", response_model=list[StockItemOut])
def list_items(db: Session = Depends(get_db)):
    return stock_service.list_items(db)


@router.post("/", response_model=StockItemOut, status_code=201)
def create_item(
    payload: StockItemCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    return stock_service.create_item(db, payload)


@router.patch("/{item_id}", response_model=StockItemOut)
def update_item(
    item_id: int,
    payload: StockItemUpdate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    return stock_service.update_item(db, item_id, payload)


@router.get("/expired", response_model=list[StockItemOut])
def expired(db: Session = Depends(get_db)):
    return stock_service.list_expired(db)


@router.get("/near-expiry", response_model=list[StockItemOut])
def near_expiry(db: Session = Depends(get_db)):
    return stock_service.list_near_expiry(db)


@router.get("/low-stock", response_model=list[StockItemOut])
def low_stock(db: Session = Depends(get_db)):
    return stock_service.list_low_stock(db)


@router.post("/scan", status_code=200)
def scan(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    raised = stock_service.scan_and_alert(db)
    return {"alerts_raised": raised}


@router.get("/kpi", response_model=StockKPI)
def kpi(db: Session = Depends(get_db)):
    return stock_service.compute_kpi(db)


@router.post("/scan-product")
def scan_product(
    product_id: int,
    action: str = "sell",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Simulate a real POS / barcode scan: sell or restock by 1 unit."""
    return stock_service.scan_product(db, product_id, action, username=user.username)


@router.post("/scan-barcode")
def scan_barcode(
    barcode: str,
    action: str = "sell",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Phone-scanned barcode workflow: looks up the product by `barcode`
    and delegates to the same `scan_product` core logic."""
    return stock_service.scan_by_barcode(db, barcode, action, username=user.username)