"""CCTV analytics business logic (GDPR-safe)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cctv import CCTVEvent
from app.models.inventory_log import InventoryLog
from app.schemas.cctv import CCTVEventCreate, LayoutSuggestion, ZoneStat
from app.utils.logger import logger, persist_alert

CROWDED_THRESHOLD = 20                             
SPIKE_FACTOR = 2.5                                 

def record_event(db: Session, payload: CCTVEventCreate) -> CCTVEvent:
    event = CCTVEvent(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)

    if event.people_count >= CROWDED_THRESHOLD:
        persist_alert(
            db,
            "cctv",
            "warning",
            f"Crowded zone '{event.zone}': {event.people_count} people",
        )

    baseline_cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    samples = (
        db.query(CCTVEvent.people_count)
        .filter(CCTVEvent.zone == event.zone)
        .filter(CCTVEvent.timestamp >= baseline_cutoff)
        .filter(CCTVEvent.id != event.id)
        .all()
    )
    if samples:
        baseline = statistics.mean(s[0] for s in samples)
        if baseline > 0 and event.people_count >= baseline * SPIKE_FACTOR:
            persist_alert(
                db,
                "cctv",
                "warning",
                f"Traffic spike in '{event.zone}': {event.people_count} vs baseline {baseline:.1f}",
            )

    logger.info("CCTV event recorded: zone=%s people=%d", event.zone, event.people_count)
    return event

def list_events(db: Session, zone: str | None = None, limit: int = 100) -> list[CCTVEvent]:
    q = db.query(CCTVEvent)
    if zone:
        q = q.filter(CCTVEvent.zone == zone)
    return q.order_by(CCTVEvent.timestamp.desc()).limit(limit).all()

def per_zone_stats(db: Session) -> list[ZoneStat]:
    rows = db.query(CCTVEvent).all()
    grouped: dict[str, list[CCTVEvent]] = defaultdict(list)
    for r in rows:
        grouped[r.zone].append(r)

    stats: list[ZoneStat] = []
    for zone, events in grouped.items():
        people = [e.people_count for e in events]
        activity = [e.activity_score for e in events]
        stats.append(
            ZoneStat(
                zone=zone,
                avg_people=round(statistics.mean(people), 2) if people else 0.0,
                max_people=max(people) if people else 0,
                avg_activity=round(statistics.mean(activity), 2) if activity else 0.0,
                sample_count=len(events),
            )
        )
    return sorted(stats, key=lambda s: s.avg_people, reverse=True)

def layout_suggestion(db: Session) -> LayoutSuggestion:
    stats = per_zone_stats(db)
    if not stats:
        return LayoutSuggestion(
            high_traffic_zones=[],
            low_traffic_zones=[],
            recommendation="Insufficient data — collect more CCTV samples.",
        )
    top = [s.zone for s in stats[: max(1, len(stats) // 3)]]
    bottom = [s.zone for s in stats[-max(1, len(stats) // 3) :]]
    rec = (
        f"Move high-margin / promotional products toward {', '.join(top)}; "
        f"reorganize or de-emphasize {', '.join(bottom)} to free up floor space."
    )
    return LayoutSuggestion(high_traffic_zones=top, low_traffic_zones=bottom, recommendation=rec)

def detect_anomalies(db: Session) -> list[dict]:
    """Recompute anomalies across the most recent window — used by the dashboard."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    events = (
        db.query(CCTVEvent)
        .filter(CCTVEvent.timestamp >= cutoff)
        .order_by(CCTVEvent.timestamp.desc())
        .all()
    )
    out: list[dict] = []
    for e in events:
        if e.people_count >= CROWDED_THRESHOLD:
            out.append(
                {
                    "zone": e.zone,
                    "people_count": e.people_count,
                    "timestamp": e.timestamp.isoformat(),
                    "type": "crowded",
                }
            )
    return out

def get_event(db: Session, event_id: int) -> CCTVEvent:
    e = db.query(CCTVEvent).filter(CCTVEvent.id == event_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="CCTV event not found")
    return e

def auto_verdict_recent(db: Session, limit: int = 80) -> dict:
    """Cross-correlate CCTV events with inventory_log to auto-classify alerts.

    For each recent CCTV event we open a [event.ts - 30s, event.ts + 5min]
    window in the inventory log. Two independent signals decide the verdict:

    * Stock loss adjustment (action='adjust' with negative quantity_change)
      not explainable by a normal sale -> strong theft confirmation -> AUTO TP.
    * No inventory movement at all in the window -> nothing happened -> AUTO FP.
    * Score critical (>=80) but no stock impact yet -> ambiguous, left to human.

    Returns: { event_id: {verdict, confidence, reason} }
    """
    events = (
        db.query(CCTVEvent)
        .order_by(CCTVEvent.timestamp.desc())
        .limit(limit)
        .all()
    )
    out: dict = {}

    for e in events:
        win_start = e.timestamp - timedelta(seconds=30)
        win_end   = e.timestamp + timedelta(minutes=5)

        logs = (
            db.query(InventoryLog)
            .filter(InventoryLog.timestamp >= win_start)
            .filter(InventoryLog.timestamp <= win_end)
            .all()
        )

        unexplained = [l for l in logs if l.action == "adjust" and l.quantity_change < 0]
        sells       = [l for l in logs if l.action == "sell"]
        any_move    = bool(logs)

        if unexplained:
            total_lost = sum(-l.quantity_change for l in unexplained)
            out[e.id] = {
                "verdict": "tp",
                "confidence": round(min(0.95, 0.70 + 0.05 * total_lost), 2),
                "reason": f"Stock loss detected: {total_lost} unit(s) adjusted in window",
            }
            continue

        score = e.activity_score or 0
        if score >= 80:
            out[e.id] = {
                "verdict": "unknown",
                "confidence": 0.30,
                "reason": "Critical score but no stock loss yet -- needs review",
            }
        elif score >= 60:
            out[e.id] = {
                "verdict": "unknown",
                "confidence": 0.40,
                "reason": "Suspect-level score with no inventory correlation -- manual check",
            }
        elif score >= 30:
            note = "No stock impact in window"
            if sells:
                note += f" ({len(sells)} normal sale(s) only)"
            out[e.id] = {
                "verdict": "fp",
                "confidence": 0.70 if any_move else 0.85,
                "reason": note,
            }

    return out
