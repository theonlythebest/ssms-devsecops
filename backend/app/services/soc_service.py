"""SOC (Security Operations Center) event aggregation.

Filters the existing Alert table down to cybersecurity-relevant categories
only, excluding normal retail noise like stock/expiry/web-order alerts
which already have their own dashboard sections.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.alert import Alert

# Categories that belong on the SOC feed.
#   security  - quarantine, ransomware-pattern, write spikes, request bursts
#   auth      - failed logins, invalid tokens, unauthorized admin actions
#   anomaly   - sales anomalies (high-value, off-hours, refund/cancel bursts)
#   barcode   - unknown / suspicious barcode scans
#   system    - backend lifecycle, latency spikes, repeated 5xx
SOC_CATEGORIES: tuple[str, ...] = ("security", "auth", "anomaly", "barcode", "system")


def list_soc_events(db: Session, limit: int = 50) -> list[Alert]:
    """Return SOC events newest-first, excluding stock/cctv/web noise."""
    return (
        db.query(Alert)
        .filter(Alert.category.in_(SOC_CATEGORIES))
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )


def count_by_severity(db: Session) -> dict[str, int]:
    """Tiny helper for SOC summary widgets — counts open events by severity."""
    rows = (
        db.query(Alert.severity)
        .filter(Alert.category.in_(SOC_CATEGORIES))
        .filter(Alert.resolved.is_(False))
        .all()
    )
    out = {"critical": 0, "warning": 0, "info": 0}
    for (sev,) in rows:
        out[sev] = out.get(sev, 0) + 1
    return out