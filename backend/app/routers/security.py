"""Cybersecurity status + quarantine control endpoints (SOC integrated)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_role
from app.utils.logger import persist_alert, security_monitor

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/status")
def status():
    """Return current monitoring counters and quarantine state."""
    return security_monitor.stats()


@router.post("/quarantine/release")
def release(
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Admin-only: clear quarantine after manual review.

    Persists a SOC event so the audit trail captures who released it.
    """
    was_quarantined = security_monitor.quarantined
    security_monitor.release_quarantine()
    if was_quarantined:
        persist_alert(
            db, "security", "info",
            f"Quarantine released by admin '{user.username}'",
        )
    return {"quarantined": False, "message": "Quarantine released."}


@router.post("/quarantine/trigger")
def trigger(
    reason: str = "manual",
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Admin-only: simulate a quarantine event (testing / drills).

    Persists a SOC critical event so it shows up in the SOC feed.
    """
    security_monitor.trigger_quarantine(reason)
    persist_alert(
        db, "security", "critical",
        f"Quarantine triggered: {reason} (by admin '{user.username}')",
    )
    return {"quarantined": True, "reason": reason}