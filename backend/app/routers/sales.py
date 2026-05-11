"""Sales endpoints (EPOS)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.sale import SaleCreate, SaleKPI, SaleOut
from app.services import sales_service

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("/", response_model=SaleOut, status_code=201)
def create_sale(
    payload: SaleCreate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    return sales_service.create_sale(db, payload)


@router.get("/", response_model=list[SaleOut])
def list_sales(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return sales_service.list_sales(db, limit=limit)


@router.get("/kpi", response_model=SaleKPI)
def kpi(db: Session = Depends(get_db)):
    return sales_service.compute_kpi(db)


@router.get("/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db)):
    return sales_service.get_sale(db, sale_id)
