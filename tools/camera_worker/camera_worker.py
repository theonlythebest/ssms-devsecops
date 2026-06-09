"""
SSMS — Camera Worker (intrusion / loitering detection)
======================================================

Standalone "smart camera" agent that runs OUTSIDE the SSMS Docker stack.
It watches a video source with YOLOv8, detects humans (COCO class 0),
checks whether they enter a configurable "forbidden zone" polygon, and
forwards the event to the SSMS FastAPI backend so the SOC middleware
(and Grafana panels) react in real time.

The script intentionally maps every intrusion to a HIGH `activity_score`
on the CCTVEventCreate schema. The existing SecurityMonitor +
prometheus counters react to activity_score spikes automatically, so
this drops in without any change to the backend.

────────────────────────────────────────────────────────────────────────
Install once (inside a Python 3.10+ virtualenv):

    pip install -r requirements.txt

Run:

    python camera_worker.py

Quit with `q`. Pause with `p`. Save a screenshot with `s`.
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import requests
from ultralytics import YOLO

VIDEO_SOURCE: str | int = "surveillance_test.mp4"

API_BASE_URL  = "http://localhost:8000"
API_USERNAME  = "admin"                                    
API_PASSWORD  = "admin123"                                 
HTTP_TIMEOUT  = 3.0                                          

YOLO_WEIGHTS         = "yolov8n.pt"
YOLO_PERSON_CLASS_ID = 0                                      
YOLO_CONFIDENCE      = 0.40                        
YOLO_IMGSZ           = 640                                

FORBIDDEN_ZONE_POLYGON: list[tuple[int, int]] = [
    (820,  60),
    (1230, 60),
    (1230, 460),
    (820,  460),
]
ZONE_NAME       = "stockroom_door"
ANOMALY_TYPE    = "intrusion"

COOLDOWN_SECONDS    = 10.0                                      
ALERT_HOLD_FRAMES   = 25                                                            
ACTIVITY_NORMAL     = 0                                                           
ACTIVITY_INTRUSION  = 90                                                             
PING_INTERVAL_SECS  = 60.0                                                           

SHOW_WINDOW           = True
WINDOW_NAME           = "SSMS · Camera Worker"
DRAW_BBOXES           = True
DRAW_CONFIDENCE_TEXT  = True
SCREENSHOT_DIR        = Path(__file__).parent / "screenshots"

COLOR_ZONE_IDLE  = (  0, 200, 220)          
COLOR_ZONE_ALERT = (  0,   0, 230)        
COLOR_PERSON_OK  = (  0, 200,   0)          
COLOR_PERSON_HIT = (  0,   0, 230)        
COLOR_BANNER_BG  = (  0,   0, 180)             
COLOR_TEXT       = (255, 255, 255)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("camera_worker")

class SSMSClient:
    """Thin client for the SSMS backend.

    Logs in once, refreshes the JWT on 401, and gracefully tolerates the
    backend being temporarily unreachable (we never want the camera loop
    to crash because the API blinked).
    """

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self.session = requests.Session()

    def login(self) -> bool:
        """OAuth2 password flow against /auth/login."""
        try:
            r = self.session.post(
                f"{self.base_url}/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=HTTP_TIMEOUT,
            )
            r.raise_for_status()
            self.token = r.json()["access_token"]
            log.info("Authenticated as '%s'", self.username)
            return True
        except Exception as exc:
            log.warning("Login failed: %s — events will be dropped.", exc)
            self.token = None
            return False

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def post_event(self, payload: dict) -> bool:
        """POST /cctv/events; retry once on 401 by re-authenticating."""
        if self.token is None and not self.login():
            return False

        url = f"{self.base_url}/cctv/events"
        for attempt in (1, 2):
            try:
                r = self.session.post(
                    url, json=payload,
                    headers=self._auth_headers(),
                    timeout=HTTP_TIMEOUT,
                )
                if r.status_code == 401 and attempt == 1:
                    log.info("Token expired, refreshing.")
                    self.token = None
                    if not self.login():
                        return False
                    continue
                r.raise_for_status()
                return True
            except requests.exceptions.RequestException as exc:
                log.warning("POST /cctv/events failed (attempt %d): %s",
                            attempt, exc)
                                                                           
                if not isinstance(exc, requests.exceptions.HTTPError):
                    return False
        return False

class ForbiddenZone:
    """Holds the polygon and provides containment tests / drawing."""

    def __init__(self, polygon: list[tuple[int, int]], name: str):
        if len(polygon) < 3:
            raise ValueError("A forbidden zone needs at least 3 vertices.")
        self.name = name
                                                     
        self.poly_np = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))

    def contains(self, point: tuple[int, int]) -> bool:
        """True if the (x, y) point is inside the polygon."""
        return cv2.pointPolygonTest(self.poly_np, point, False) >= 0

    def draw(self, frame: np.ndarray, *, alert: bool) -> None:
        color = COLOR_ZONE_ALERT if alert else COLOR_ZONE_IDLE
                                                               
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.poly_np], color)
        cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, dst=frame)
                        
        cv2.polylines(frame, [self.poly_np], isClosed=True,
                      color=color, thickness=3)
                
        x, y = self.poly_np[0][0]
        cv2.putText(frame, f"ZONE: {self.name}",
                    (int(x), max(int(y) - 8, 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    color, 2, cv2.LINE_AA)

def foot_point(xyxy: tuple[float, float, float, float]) -> tuple[int, int]:
    """Bottom-center of a bbox — a much better proxy for 'where the person
    stands' than the centroid when judging zone containment."""
    x1, y1, x2, y2 = xyxy
    return (int((x1 + x2) / 2), int(y2))

def draw_banner(frame: np.ndarray, text: str) -> None:
    """Big top-of-screen banner used while an intrusion is active."""
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 56), COLOR_BANNER_BG, -1)
    cv2.putText(frame, text, (18, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                COLOR_TEXT, 2, cv2.LINE_AA)

def draw_hud(frame: np.ndarray, fps: float, people: int,
             alert_active: bool, last_alert: float | None) -> None:
    """Bottom-left HUD: FPS, count, last alert time."""
    h, w = frame.shape[:2]
    lines = [
        f"FPS         : {fps:5.1f}",
        f"People      : {people}",
        f"Zone        : {ZONE_NAME}",
        f"State       : {'ALERT' if alert_active else 'idle'}",
    ]
    if last_alert is not None:
        lines.append(f"Last alert  : {datetime.fromtimestamp(last_alert).strftime('%H:%M:%S')}")
    y = h - 18 - 22 * (len(lines) - 1)
    for line in lines:
        cv2.putText(frame, line, (12, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    COLOR_TEXT, 1, cv2.LINE_AA)
        y += 22

def main() -> int:
    log.info("Loading YOLO model: %s", YOLO_WEIGHTS)
    model = YOLO(YOLO_WEIGHTS)

    log.info("Opening video source: %r", VIDEO_SOURCE)
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        log.error("Cannot open video source %r. "
                  "Place 'surveillance_test.mp4' next to this script, "
                  "or set VIDEO_SOURCE = 0 for webcam.", VIDEO_SOURCE)
        return 1

    zone   = ForbiddenZone(FORBIDDEN_ZONE_POLYGON, ZONE_NAME)
    client = SSMSClient(API_BASE_URL, API_USERNAME, API_PASSWORD)
    client.login()                                       

    SCREENSHOT_DIR.mkdir(exist_ok=True, parents=True)

    last_alert_ts: float | None = None
    last_ping_ts:  float | None = None
    alert_hold_remaining = 0
    paused = False
    fps_smoothed = 0.0
    t_prev = time.perf_counter()

    log.info("Watching... press 'q' to quit, 'p' to pause, 's' for screenshot.")

    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok:
                                                               
                log.info("End of stream — looping.")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

        results = model(frame, imgsz=YOLO_IMGSZ,
                        conf=YOLO_CONFIDENCE,
                        classes=[YOLO_PERSON_CLASS_ID],
                        verbose=False)

        boxes = results[0].boxes
        people_count   = 0
        intruders_now  = 0

        for b in boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            conf = float(b.conf[0])
            people_count += 1

            feet = foot_point((x1, y1, x2, y2))
            in_zone = zone.contains(feet)
            if in_zone:
                intruders_now += 1

            if DRAW_BBOXES:
                color = COLOR_PERSON_HIT if in_zone else COLOR_PERSON_OK
                cv2.rectangle(frame, (int(x1), int(y1)),
                              (int(x2), int(y2)), color, 2)
                cv2.circle(frame, feet, 5, color, -1)
                if DRAW_CONFIDENCE_TEXT:
                    label = f"person {conf:.2f}"
                    cv2.putText(frame, label, (int(x1), int(y1) - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                color, 2, cv2.LINE_AA)

        now = time.time()
        alert_active = alert_hold_remaining > 0
        if intruders_now > 0:
            cooldown_ok = (last_alert_ts is None
                           or (now - last_alert_ts) >= COOLDOWN_SECONDS)
            if cooldown_ok:
                payload = {
                    "zone":           ZONE_NAME,
                    "people_count":   people_count,
                    "activity_score": ACTIVITY_INTRUSION,
                    "note": (
                        f"{ANOMALY_TYPE.upper()}: {intruders_now} person(s) "
                        f"in forbidden zone at "
                        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
                    ),
                }
                log.warning("INTRUSION → POST %s", payload)
                if client.post_event(payload):
                    last_alert_ts = now
                    alert_hold_remaining = ALERT_HOLD_FRAMES

        if alert_hold_remaining > 0:
            alert_hold_remaining -= 1
            alert_active = True

        if (PING_INTERVAL_SECS > 0
                and (last_ping_ts is None
                     or (now - last_ping_ts) >= PING_INTERVAL_SECS)
                and not alert_active):
            client.post_event({
                "zone": ZONE_NAME,
                "people_count": people_count,
                "activity_score": ACTIVITY_NORMAL,
                "note": "heartbeat",
            })
            last_ping_ts = now

        zone.draw(frame, alert=alert_active)
        if alert_active:
            draw_banner(frame, f"INTRUSION DETECTED — {ZONE_NAME}")

        t_now = time.perf_counter()
        instant_fps = 1.0 / max(t_now - t_prev, 1e-6)
        t_prev = t_now
        fps_smoothed = 0.9 * fps_smoothed + 0.1 * instant_fps if fps_smoothed else instant_fps

        draw_hud(frame, fps_smoothed, people_count, alert_active, last_alert_ts)

        if SHOW_WINDOW:
            cv2.imshow(WINDOW_NAME, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                log.info("Quit requested.")
                break
            elif key == ord("p"):
                paused = not paused
                log.info("Pause: %s", paused)
            elif key == ord("s"):
                fname = SCREENSHOT_DIR / f"snap_{int(now)}.jpg"
                cv2.imwrite(str(fname), frame)
                log.info("Screenshot saved: %s", fname)

    cap.release()
    if SHOW_WINDOW:
        cv2.destroyAllWindows()
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(130)
