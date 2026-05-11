"""CCTV analytics business logic (GDPR-safe)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cctv import CCTVEvent
from app.schemas.cctv import CCTVEventCreate, LayoutSuggestion, ZoneStat
from app.utils.logger import logger, persist_alert

CROWDED_THRESHOLD = 20  # people in a single sample
SPIKE_FACTOR = 2.5  # current sample is N x average


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

    # detect abnormal traffic spike vs the zone's recent baseline
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
