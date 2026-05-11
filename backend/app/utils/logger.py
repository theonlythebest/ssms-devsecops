"""Cybersecurity-aware logger and SecurityMonitor."""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Deque, Dict

from app.core.config import settings


def _build_logger() -> logging.Logger:
    log = logging.getLogger("ssms")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s :: %(message)s")
    )
    log.addHandler(handler)
    log.propagate = False
    return log


logger = _build_logger()


class SecurityMonitor:
    """In-memory anomaly detector with cooldowns + multi-vector correlation."""

    WINDOW_SECONDS = 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._auth_failures: Deque[float] = deque()
        self._quarantined: bool = False
        self._quarantine_reason: str | None = None
        self._raised_alerts: Dict[str, float] = {}

    def _trim(self, dq: Deque[float], now: float) -> None:
        cutoff = now - self.WINDOW_SECONDS
        while dq and dq[0] < cutoff:
            dq.popleft()

    def can_alert(self, key: str, cooldown: int = 30) -> bool:
        """Public dedupe gate — used by middleware too."""
        now = time.time()
        last = self._raised_alerts.get(key, 0.0)
        if now - last < cooldown:
            return False
        self._raised_alerts[key] = now
        return True

    def record_event(self, name: str) -> int:
        now = time.time()
        with self._lock:
            dq = self._events[name]
            dq.append(now)
            self._trim(dq, now)
            return len(dq)

    def record_auth_failure(self) -> int:
        now = time.time()
        with self._lock:
            self._auth_failures.append(now)
            self._trim(self._auth_failures, now)
            return len(self._auth_failures)

    def analyze(self) -> list[dict]:
        """Return detected anomalies. Also auto-triggers quarantine on
        write-burst (ransomware-pattern) and emits a multi-vector
        correlation alert when 2+ vectors fire in the same window."""
        anomalies: list[dict] = []
        triggered_vectors: set[str] = set()

        with self._lock:
            now = time.time()
            self._trim(self._auth_failures, now)
            for dq in self._events.values():
                self._trim(dq, now)
            request_rate = len(self._events.get("request", []))
            write_rate = len(self._events.get("db_write", []))
            auth_fail_rate = len(self._auth_failures)

        # API flood / request spike
        if request_rate > settings.REQUEST_BURST_THRESHOLD:
            triggered_vectors.add("api_flood")
            if self.can_alert("api_flood", cooldown=60):
                anomalies.append({
                    "category": "security",
                    "severity": "warning",
                    "message": f"Potential API flooding detected: {request_rate}/min",
                })

        # Database write anomaly + ransomware-like behavior + auto-containment
        if write_rate > settings.WRITE_BURST_THRESHOLD:
            triggered_vectors.add("ransomware")
            if self.can_alert("db_write_burst", cooldown=60):
                anomalies.append({
                    "category": "security",
                    "severity": "critical",
                    "message": f"Abnormal database write activity detected: {write_rate}/min",
                })
            if self.can_alert("ransomware", cooldown=120):
                anomalies.append({
                    "category": "security",
                    "severity": "critical",
                    "message": "Potential ransomware activity detected",
                })
            if not self._quarantined:
                self.trigger_quarantine("Ransomware indicators (write-burst)")
                anomalies.append({
                    "category": "security",
                    "severity": "critical",
                    "message": "Automatic containment activated due to ransomware indicators",
                })

        # Auth flood
        if auth_fail_rate > settings.AUTH_FAIL_THRESHOLD:
            triggered_vectors.add("auth_flood")
            if self.can_alert("auth_flood", cooldown=60):
                anomalies.append({
                    "category": "security",
                    "severity": "warning",
                    "message": f"Multiple authentication failures: {auth_fail_rate}/min",
                })

        # Multi-vector attack correlation
        if len(triggered_vectors) >= 2 and self.can_alert("multi_vector", cooldown=120):
            anomalies.append({
                "category": "security",
                "severity": "critical",
                "message": "Multi-vector attack pattern detected: " +
                           ", ".join(sorted(triggered_vectors)),
            })

        return anomalies

    def trigger_quarantine(self, reason: str) -> None:
        with self._lock:
            self._quarantined = True
            self._quarantine_reason = reason
        logger.critical("QUARANTINE TRIGGERED :: %s", reason)

    def release_quarantine(self) -> None:
        with self._lock:
            self._quarantined = False
            self._quarantine_reason = None
        logger.warning("Quarantine released.")

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    @property
    def quarantine_reason(self) -> str | None:
        return self._quarantine_reason

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            for dq in self._events.values():
                self._trim(dq, now)
            self._trim(self._auth_failures, now)
            return {
                "request_rate_per_min": len(self._events.get("request", [])),
                "db_write_rate_per_min": len(self._events.get("db_write", [])),
                "auth_failure_rate_per_min": len(self._auth_failures),
                "quarantined": self._quarantined,
                "quarantine_reason": self._quarantine_reason,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }


security_monitor = SecurityMonitor()


def persist_alert(db, category: str, severity: str, message: str) -> None:
    from app.models.alert import Alert
    alert = Alert(category=category, severity=severity, message=message)
    db.add(alert)
    db.commit()
    logger.info("ALERT [%s/%s] %s", category, severity, message)