"""HTTP middleware that feeds the SecurityMonitor + persists SOC events."""
from __future__ import annotations

from prometheus_client import Counter, Gauge

# =========================
# AUTH / SECURITY METRICS
# =========================

successful_logins_total = Counter(
    "successful_logins_total",
    "Total successful logins"
)

failed_logins_total = Counter(
    "failed_logins_total",
    "Total failed login attempts"
)

invalid_jwt_total = Counter(
    "invalid_jwt_total",
    "Invalid JWT attempts"
)

forbidden_requests_total = Counter(
    "forbidden_requests_total",
    "Forbidden access attempts"
)

unauthorized_requests_total = Counter(
    "unauthorized_requests_total",
    "Unauthorized requests"
)

auth_flood_alerts_total = Counter(
    "auth_flood_alerts_total",
    "Authentication flood detections"
)

soc_alerts_total = Counter(
    "soc_alerts_total",
    "Total SOC alerts",
    ["severity"]
)

critical_soc_alerts_total = Counter(
    "critical_soc_alerts_total",
    "Critical SOC alerts"
)

# =========================
# QUARANTINE METRICS
# =========================

quarantine_trigger_total = Counter(
    "quarantine_trigger_total",
    "Total quarantine activations"
)

quarantine_release_total = Counter(
    "quarantine_release_total",
    "Total quarantine releases"
)

quarantine_blocked_requests_total = Counter(
    "quarantine_blocked_requests_total",
    "Requests blocked during quarantine"
)

quarantine_state = Gauge(
    "quarantine_state",
    "Current quarantine state (0=off,1=on)"
)

# =========================
# BARCODE / RETAIL SECURITY
# =========================

unknown_barcode_total = Counter(
    "unknown_barcode_total",
    "Unknown barcode scans"
)

barcode_scans_total = Counter(
    "barcode_scans_total",
    "Total barcode scans"
)

barcode_sell_operations_total = Counter(
    "barcode_sell_operations_total",
    "Sell operations through barcode scans"
)

barcode_restock_operations_total = Counter(
    "barcode_restock_operations_total",
    "Restock operations through barcode scans"
)

# =========================
# SALES / BUSINESS METRICS
# =========================

sales_total = Counter(
    "sales_total",
    "Total completed sales"
)

orders_total = Counter(
    "orders_total",
    "Total ecommerce orders"
)

confirmed_orders_total = Counter(
    "confirmed_orders_total",
    "Confirmed ecommerce orders"
)

revenue_total = Counter(
    "revenue_total",
    "Total revenue generated"
)

refunds_total = Counter(
    "refunds_total",
    "Total refunds"
)

promotion_generated_total = Counter(
    "promotion_generated_total",
    "Promotion suggestions generated"
)

top_seller_events_total = Counter(
    "top_seller_events_total",
    "Top seller updates"
)

# =========================
# INVENTORY METRICS
# =========================

inventory_updates_total = Counter(
    "inventory_updates_total",
    "Inventory updates"
)

low_stock_alerts_total = Counter(
    "low_stock_alerts_total",
    "Low stock alerts"
)

expired_products_total = Counter(
    "expired_products_total",
    "Expired products detected"
)

near_expiry_products_total = Counter(
    "near_expiry_products_total",
    "Near expiry products detected"
)

inventory_activity_total = Counter(
    "inventory_activity_total",
    "Inventory activity logs"
)

# =========================
# SYSTEM / API METRICS
# =========================

api_errors_total = Counter(
    "api_errors_total",
    "Total API errors"
)

server_errors_total = Counter(
    "server_errors_total",
    "Total server errors"
)

healthcheck_requests_total = Counter(
    "healthcheck_requests_total",
    "Health endpoint requests"
)

dashboard_requests_total = Counter(
    "dashboard_requests_total",
    "Dashboard requests"
)

metrics_requests_total = Counter(
    "metrics_requests_total",
    "Metrics endpoint requests"
)

# =========================
# SOC / ANOMALY DETECTION
# =========================

anomaly_detection_total = Counter(
    "anomaly_detection_total",
    "Detected anomalies"
)

suspicious_activity_total = Counter(
    "suspicious_activity_total",
    "Suspicious activities detected"
)

potential_ransomware_total = Counter(
    "potential_ransomware_total",
    "Potential ransomware detections"
)

db_write_spike_total = Counter(
    "db_write_spike_total",
    "Database write spikes"
)

request_spike_total = Counter(
    "request_spike_total",
    "Request spikes detected"
)

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.database import SessionLocal
from app.utils.logger import logger, persist_alert, security_monitor

# Endpoints that stay reachable while the system is quarantined,
# otherwise the operator could not lift the quarantine without restarting.
QUARANTINE_WHITELIST = {
    "/security/status",
    "/security/quarantine/release",
    "/health",
}


class MonitoringMiddleware(BaseHTTPMiddleware):
    """Counts requests, runs anomaly analysis, persists SOC events."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Quarantine: read-only OR explicitly whitelisted endpoints only.
        if (
            security_monitor.quarantined
            and path not in QUARANTINE_WHITELIST
            and request.method not in {"GET", "HEAD", "OPTIONS"}
        ):

            quarantine_blocked_requests_total.inc()

            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service isolated due to security anomaly.",
                    "reason": security_monitor.quarantine_reason,
                },
            )

        security_monitor.record_event("request")

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            security_monitor.record_event("db_write")

        start = time.perf_counter()

        try:
            response = await call_next(request)

        except Exception as exc:  # pragma: no cover

            server_errors_total.inc()

            logger.exception("Unhandled error: %s", exc)

            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error."},
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        # SOC: persist auth events based on response status (with cooldowns).
        if response.status_code == 401:

            failed_logins_total.inc()
            invalid_jwt_total.inc()
            unauthorized_requests_total.inc()

            security_monitor.record_auth_failure()

            # /auth/login already persists its own alert in auth_service.
            if path != "/auth/login" and security_monitor.can_alert(
                f"jwt_invalid:{path}",
                cooldown=60,
            ):

                db = SessionLocal()

                try:
                    persist_alert(
                        db,
                        "auth",
                        "warning",
                        f"Invalid JWT token detected on {path}",
                    )

                finally:
                    db.close()

        if response.status_code == 403:

            forbidden_requests_total.inc()

            if security_monitor.can_alert(
                f"unauth_admin:{path}",
                cooldown=30,
            ):

                db = SessionLocal()

                try:
                    persist_alert(
                        db,
                        "auth",
                        "critical",
                        f"Unauthorized admin endpoint access attempt on {path}",
                    )

                finally:
                    db.close()

        # Periodic monitor analysis (multi-vector correlation, ransomware,
        # API flood, write burst, auto-containment) — all SOC-relevant.
        anomalies = security_monitor.analyze()

        if anomalies:

            anomaly_detection_total.inc()
            suspicious_activity_total.inc()

            db = SessionLocal()

            try:
                for a in anomalies:
                    persist_alert(
                        db,
                        a["category"],
                        a["severity"],
                        a["message"],
                    )

            finally:
                db.close()

        response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.2f}"

        return response