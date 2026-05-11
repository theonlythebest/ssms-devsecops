"""Initial data seeding so the dashboard is never empty."""
from __future__ import annotations

import random
import secrets
import string
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.cctv import CCTVEvent
from app.models.order import WebOrder, WebOrderItem
from app.models.sale import Sale, SaleItem
from app.models.stock import StockItem
from app.models.user import User
from app.utils.logger import logger

PRODUCTS = [
    ("Baguette", "bakery", 1.20),
    ("Croissant", "bakery", 1.50),
    ("Milk 1L", "dairy", 1.10),
    ("Yogurt", "dairy", 0.80),
    ("Cheese", "dairy", 3.50),
    ("Tomato", "produce", 0.60),
    ("Apple", "produce", 0.40),
    ("Banana", "produce", 0.30),
    ("Pasta", "grocery", 1.80),
    ("Olive Oil", "grocery", 6.50),
    ("Cereal", "grocery", 3.20),
    ("Chicken Breast", "butcher", 7.90),
    ("Beef Steak", "butcher", 12.50),
    ("Salmon", "seafood", 14.00),
    ("Soda 1.5L", "beverage", 1.90),
    ("Water 1.5L", "beverage", 0.70),
    ("Coffee", "beverage", 5.40),
    ("Tea", "beverage", 4.20),
    ("Chocolate Bar", "snack", 1.30),
    ("Chips", "snack", 2.10),
]

ZONES = ["entrance", "produce", "dairy", "checkout", "beverages", "snacks", "butcher"]

# GS1 prefix "200"-"299" is reserved for in-store / restricted-circulation
# barcodes — the correct range to use for an internal POS catalog.
EAN13_INTERNAL_PREFIX = "200"


def _ean13_check_digit(twelve_digits: str) -> str:
    """Compute the Mod-10 check digit for a 12-digit EAN-13 base."""
    if len(twelve_digits) != 12 or not twelve_digits.isdigit():
        raise ValueError("EAN-13 base must be exactly 12 digits")
    total = sum(
        int(d) * (3 if i % 2 else 1) for i, d in enumerate(twelve_digits)
    )
    return str((10 - total % 10) % 10)


def _generate_ean13(index: int) -> str:
    """Deterministic, valid EAN-13 barcode for a given product index.

    Format: <3-digit internal prefix><9-digit zero-padded index><check digit>
    """
    base = f"{EAN13_INTERNAL_PREFIX}{index:09d}"  # 12 digits
    return base + _ean13_check_digit(base)


def _random_id(n: int = 10) -> str:
    return "WO-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def _seed_users(db: Session) -> None:
    if db.query(User).count() > 0:
        return
    db.add_all(
        [
            User(
                username="admin",
                email="admin@ssms.local",
                hashed_password=hash_password("admin123"),
                role="admin",
            ),
            User(
                username="employee",
                email="employee@ssms.local",
                hashed_password=hash_password("employee123"),
                role="employee",
            ),
        ]
    )
    db.commit()
    logger.info("Seeded default users (admin / employee).")


def _seed_stock(db: Session) -> None:
    today = date.today()
    inserted = 0
    backfilled = 0

    for index, (name, cat, price) in enumerate(PRODUCTS, start=1):
        barcode = _generate_ean13(index)

        existing = db.query(StockItem).filter(StockItem.name == name).first()
        if existing is not None:
            if existing.barcode != barcode:
                existing.barcode = barcode
                backfilled += 1
            continue

        roll = random.random()
        if roll < 0.15:
            exp = today - timedelta(days=random.randint(1, 5))
        elif roll < 0.45:
            exp = today + timedelta(days=random.randint(1, 4))
        else:
            exp = today + timedelta(days=random.randint(15, 90))

        db.add(
            StockItem(
                name=name,
                barcode=barcode,
                category=cat,
                quantity=random.randint(0, 60),
                low_stock_threshold=random.choice([3, 5, 8]),
                unit_price=price,
                expiry_date=exp,
            )
        )
        inserted += 1

    db.commit()
    if inserted or backfilled:
        logger.info(
            "Stock seed: inserted=%d, barcode-backfilled=%d (valid EAN-13)",
            inserted,
            backfilled,
        )


def _seed_sales(db: Session) -> None:
    if db.query(Sale).count() > 0:
        return
    now = datetime.now(timezone.utc)
    for _ in range(random.randint(35, 50)):
        when = now - timedelta(
            days=random.randint(0, 6), hours=random.randint(0, 23), minutes=random.randint(0, 59)
        )
        status = random.choices(
            ["completed", "refunded", "cancelled"], weights=[0.85, 0.1, 0.05], k=1
        )[0]
        sale = Sale(
            cashier=random.choice(["alice", "bob", "carol"]),
            status=status,
            is_refund=(status == "refunded"),
            created_at=when,
        )
        n_items = random.randint(1, 5)
        total = 0.0
        chosen = random.sample(PRODUCTS, n_items)
        for name, _cat, price in chosen:
            qty = random.randint(1, 4)
            line = round(price * qty, 2)
            total += line
            sale.items.append(
                SaleItem(
                    product_name=name, quantity=qty, unit_price=price, line_total=line
                )
            )
        sale.total = round(total, 2)
        db.add(sale)
    db.commit()
    logger.info("Seeded sales records.")


def _seed_cctv(db: Session) -> None:
    if db.query(CCTVEvent).count() > 0:
        return
    now = datetime.now(timezone.utc)
    for _ in range(120):
        when = now - timedelta(hours=random.randint(0, 47), minutes=random.randint(0, 59))
        zone = random.choice(ZONES)
        people = max(0, int(random.gauss(6, 4)))
        if random.random() < 0.05:
            people += random.randint(15, 30)
        db.add(
            CCTVEvent(
                zone=zone,
                people_count=people,
                activity_score=min(100, people * random.randint(2, 5)),
                timestamp=when,
            )
        )
    db.commit()
    logger.info("Seeded CCTV events.")


def _seed_orders(db: Session) -> None:
    if db.query(WebOrder).count() > 0:
        return
    now = datetime.now(timezone.utc)
    for _ in range(random.randint(8, 16)):
        when = now - timedelta(days=random.randint(0, 5), hours=random.randint(0, 23))
        order = WebOrder(public_id=_random_id(), status="pending", created_at=when)
        chosen = random.sample(PRODUCTS, random.randint(1, 4))
        total = 0.0
        for name, _cat, price in chosen:
            qty = random.randint(1, 3)
            line = round(price * qty, 2)
            total += line
            order.items.append(
                WebOrderItem(
                    product_name=name,
                    quantity=qty,
                    unit_price=price,
                    line_total=line,
                    fulfillable=1,
                )
            )
        order.total = round(total, 2)
        db.add(order)
    db.commit()
    logger.info("Seeded web orders.")


def seed_all(db: Session) -> None:
    """Run all seeders. Idempotent."""
    random.seed()
    _seed_users(db)
    _seed_stock(db)
    _seed_sales(db)
    _seed_cctv(db)
    _seed_orders(db)