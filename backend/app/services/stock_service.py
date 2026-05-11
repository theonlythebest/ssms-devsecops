"""Stock + DLC (expiry) business logic."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.stock import StockItem
from app.schemas.stock import StockItemCreate, StockItemOut, StockItemUpdate, StockKPI
from app.services import inventory_service, sales_service
from app.utils.logger import logger, persist_alert

NEAR_EXPIRY_DAYS = 5


def _enrich(item: StockItem) -> StockItemOut:
    days_remaining = None
    is_expired = False
    is_near_expiry = False
    if item.expiry_date is not None:
        days_remaining = (item.expiry_date - date.today()).days
        is_expired = days_remaining < 0
        is_near_expiry = 0 <= days_remaining <= NEAR_EXPIRY_DAYS
    is_low_stock = item.quantity <= item.low_stock_threshold
    return StockItemOut(
        id=item.id, name=item.name, barcode=item.barcode,
        category=item.category, quantity=item.quantity,
        low_stock_threshold=item.low_stock_threshold,
        unit_price=item.unit_price, expiry_date=item.expiry_date,
        updated_at=item.updated_at, days_remaining=days_remaining,
        is_expired=is_expired, is_near_expiry=is_near_expiry,
        is_low_stock=is_low_stock,
    )


def create_item(db: Session, payload: StockItemCreate) -> StockItemOut:
    if db.query(StockItem).filter(StockItem.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Item already exists")
    item = StockItem(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    logger.info("Stock item created: %s", item.name)
    return _enrich(item)


def update_item(db: Session, item_id: int, payload: StockItemUpdate) -> StockItemOut:
    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Stock item not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    db.commit(); db.refresh(item)
    if item.quantity <= item.low_stock_threshold:
        persist_alert(db, "stock", "warning",
                      f"Low stock: {item.name} ({item.quantity} remaining)")
    return _enrich(item)


def list_items(db: Session) -> list[StockItemOut]:
    return [_enrich(i) for i in db.query(StockItem).order_by(StockItem.name).all()]


def list_expired(db: Session) -> list[StockItemOut]:
    today = date.today()
    items = (db.query(StockItem)
               .filter(StockItem.expiry_date.isnot(None))
               .filter(StockItem.expiry_date < today).all())
    return [_enrich(i) for i in items]


def list_near_expiry(db: Session) -> list[StockItemOut]:
    return [i for i in list_items(db) if i.is_near_expiry]


def list_low_stock(db: Session) -> list[StockItemOut]:
    return [i for i in list_items(db) if i.is_low_stock]


def scan_and_alert(db: Session) -> int:
    raised = 0
    for item in list_items(db):
        if item.is_expired:
            persist_alert(db, "stock", "critical", f"Expired product: {item.name}")
            raised += 1
        elif item.is_near_expiry:
            persist_alert(db, "stock", "info",
                          f"Near-expiry: {item.name} ({item.days_remaining}d left)")
            raised += 1
        if item.is_low_stock and not item.is_expired:
            persist_alert(db, "stock", "warning",
                          f"Low stock: {item.name} ({item.quantity} units)")
            raised += 1
    return raised


def get_item_by_id(db: Session, item_id: int) -> StockItem:
    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return item


def scan_product(db: Session, product_id: int, action: str = "sell",
                 *, username: str | None = None) -> dict:
    if action not in {"sell", "restock"}:
        raise HTTPException(status_code=400, detail=f"Invalid action '{action}'")
    product = get_item_by_id(db, product_id)
    if action == "sell":
        if product.quantity <= 0:
            raise HTTPException(status_code=400, detail="Out of stock")
        product.quantity -= 1
        change = -1
    else:
        product.quantity += 1
        change = +1
    db.commit(); db.refresh(product)
    inventory_service.record_log(db, product=product, action=action,
                                 quantity_change=change, username=username)
    sale_id = None
    sale_total = None
    if action == "sell":
        sale = sales_service.record_scan_sale(db, product, username=username)
        sale_id = sale.id
        sale_total = sale.total
    if action == "sell" and product.quantity <= product.low_stock_threshold:
        persist_alert(db, "stock", "warning",
                      f"Low stock after scan: {product.name} ({product.quantity} units)")
    logger.info("Scan: %s %s -> qty=%d (by %s)",
                action, product.name, product.quantity, username or "system")
    return {"message": "Scan successful", "product": product.name,
            "new_quantity": product.quantity,
            "sale_id": sale_id, "sale_total": sale_total}


def get_item_by_barcode(db: Session, barcode: str) -> StockItem:
    item = db.query(StockItem).filter(StockItem.barcode == barcode).first()
    if not item:
        # SOC event: a real or potentially suspicious unknown-barcode scan.
        persist_alert(db, "barcode", "warning",
                      f"Unknown barcode scanned: '{barcode}'")
        raise HTTPException(status_code=404,
                            detail=f"No product found for barcode '{barcode}'")
    return item


def scan_by_barcode(db: Session, barcode: str, action: str = "sell",
                    *, username: str | None = None) -> dict:
    product = get_item_by_barcode(db, barcode)
    return scan_product(db, product.id, action, username=username)


def compute_kpi(db: Session) -> StockKPI:
    items = list_items(db)
    total_items = len(items)
    total_units = sum(i.quantity for i in items)
    expired = sum(1 for i in items if i.is_expired)
    near = sum(1 for i in items if i.is_near_expiry)
    low = sum(1 for i in items if i.is_low_stock)
    waste = (expired / total_items) if total_items else 0.0
    return StockKPI(
        total_items=total_items, total_units=total_units,
        expired_count=expired, near_expiry_count=near,
        low_stock_count=low, waste_rate=round(waste, 4),
    )