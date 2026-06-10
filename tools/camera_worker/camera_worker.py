"""
SSMS - Camera Worker (suspicious behaviour scoring)
===================================================

Detects people with YOLOv8-pose, tracks them with persistent IDs (ByteTrack),
computes a per-person SUSPICION SCORE based on multiple behavioural signals,
and POSTs graded alerts to the SSMS backend.

Signals fused into the suspicion score:
- Loitering : standing in a configured zone above a per-zone dwell threshold
- Crouching : sudden drop in bbox height (concealment gesture)
- Hand-to-pocket : wrist keypoint below the hip line, near body centre
- Fast departure : speed spike after loitering (run-out pattern)
- Score decays over time so old behaviour fades

Alert levels:
- score >= 30  -> WATCH    (info, just logged)
- score >= 60  -> SUSPECT  (warning, POSTed)
- score >= 80  -> ALERT    (critical, POSTed + screenshot)

Ethics note: this is a research / soutenance demo. In production it requires
informed consent (posted signage), a legal basis under GDPR, anonymisation
(no face storage), and is meant to ALERT a human operator, never to decide
in their place. Heuristics can be biased. Always keep a human in the loop.

Install once (Python 3.10+):
    pip install -r requirements.txt

Run:
    python camera_worker.py

Quit q, pause p, screenshot s.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import requests
from ultralytics import YOLO


VIDEO_SOURCE = "surveillance_test.mp4"

API_BASE_URL  = "http://localhost:8000"
API_USERNAME  = "admin"
API_PASSWORD  = "admin123"
HTTP_TIMEOUT  = 3.0

YOLO_POSE_WEIGHTS    = "yolov8n-pose.pt"
YOLO_CONFIDENCE      = 0.35
YOLO_IMGSZ           = 640

ZONES: Dict[str, dict] = {
    "stockroom_door": {
        "polygon": [(820,  60), (1230, 60), (1230, 460), (820, 460)],
        "color":         (60, 60, 230),
        "severity":      "critical",
        "loitering_s":   6.0,
        "score_mult":    1.5,
    },
    "checkout_area": {
        "polygon": [(60, 400), (480, 400), (480, 700), (60, 700)],
        "color":         (60, 165, 255),
        "severity":      "warning",
        "loitering_s":   15.0,
        "score_mult":    1.0,
    },
}

WATCH_THRESHOLD   = 30
SUSPECT_THRESHOLD = 60
ALERT_THRESHOLD   = 80

SCORE_LOITERING   = 30
SCORE_CROUCH      = 35
SCORE_HAND_POCKET = 40
SCORE_FAST_EXIT   = 25

DECAY_PER_SECOND  = 2.5
ALERT_COOLDOWN_S  = 8.0

CROUCH_DROP_RATIO   = 0.78
HEIGHT_HISTORY_SECS = 3.0
FAST_EXIT_PX_PER_S  = 220
KP_CONF_MIN         = 0.30

ALERT_HOLD_FRAMES   = 30
PING_INTERVAL_SECS  = 90.0

SHOW_WINDOW        = True
WINDOW_NAME        = "SSMS - Behaviour Worker"
DRAW_SKELETON      = True
DRAW_SCORE_BARS    = True
SCREENSHOT_DIR     = Path(__file__).parent / "screenshots"

COL_IDLE     = ( 80, 200,  80)
COL_WATCH    = ( 60, 220, 240)
COL_SUSPECT  = ( 40, 140, 255)
COL_ALERT    = ( 40,  40, 240)
COL_TEXT     = (250, 250, 250)
COL_BAR_BG   = ( 50,  55,  65)
COL_BANNER   = ( 30,  30, 180)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("camera_worker")


class SSMSClient:
    """Thin client for the SSMS backend with JWT auto-refresh and a fail-soft loop."""

    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: Optional[str] = None
        self.session = requests.Session()
        self._last_post_ts: float = 0.0
        self._min_post_interval: float = 1.2

    def login(self) -> bool:
        now = time.time()
        if hasattr(self, "_login_cooldown_until") and now < self._login_cooldown_until:
            return False
        try:
            r = self.session.post(
                f"{self.base_url}/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=HTTP_TIMEOUT,
            )
            r.raise_for_status()
            self.token = r.json()["access_token"]
            self._login_cooldown_until = 0
            log.info("Authenticated as %s", self.username)
            return True
        except Exception as exc:
            log.warning("Login failed: %s - retrying in 15s", exc)
            self.token = None
            self._login_cooldown_until = now + 15
            return False

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def post_event(self, payload) -> bool:
        if self.token is None and not self.login():
            return False

        now = time.time()
        elapsed = now - self._last_post_ts
        if elapsed < self._min_post_interval:
            time.sleep(self._min_post_interval - elapsed)

        url = f"{self.base_url}/cctv/events"
        for attempt in (1, 2):
            try:
                r = self.session.post(
                    url, json=payload, headers=self._auth_headers(),
                    timeout=HTTP_TIMEOUT,
                )
                if r.status_code == 401 and attempt == 1:
                    self.token = None
                    if not self.login():
                        return False
                    continue
                if r.status_code == 503:
                    log.warning("POST /cctv/events 503 (quarantine?) - backing off 30s")
                    time.sleep(30)
                    return False
                r.raise_for_status()
                self._last_post_ts = time.time()
                return True
            except requests.exceptions.RequestException as exc:
                log.warning("POST /cctv/events failed (attempt %d): %s", attempt, exc)
                if not isinstance(exc, requests.exceptions.HTTPError):
                    return False
        return False


class Zone:
    """Polygon + drawing helpers for a configured surveillance zone."""

    def __init__(self, name, cfg):
        self.name       = name
        self.poly_np    = np.array(cfg["polygon"], dtype=np.int32).reshape((-1, 1, 2))
        self.color      = cfg["color"]
        self.severity   = cfg["severity"]
        self.loitering_s= cfg["loitering_s"]
        self.score_mult = cfg["score_mult"]

    def contains(self, point: Tuple[int, int]) -> bool:
        return cv2.pointPolygonTest(self.poly_np, point, False) >= 0

    def draw(self, frame, alert: bool):
        color = (40, 40, 240) if alert else self.color
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.poly_np], color)
        cv2.addWeighted(overlay, 0.16, frame, 0.84, 0, dst=frame)
        cv2.polylines(frame, [self.poly_np], True, color, 2)
        x, y = int(self.poly_np[0][0][0]), int(self.poly_np[0][0][1])
        cv2.putText(frame, f"ZONE: {self.name}", (x, max(y - 8, 18)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


@dataclass
class TrackState:
    track_id:        int
    score:           float = 0.0
    last_update_ts:  float = 0.0
    first_seen_ts:   float = 0.0
    in_zone_since:   Dict[str, float] = field(default_factory=dict)
    dwell_counted:   Dict[str, bool]  = field(default_factory=dict)
    crouch_counted:  bool = False
    pocket_counted:  bool = False
    fast_exit_counted: bool = False
    height_hist:     deque = field(default_factory=lambda: deque(maxlen=120))
    foot_hist:       deque = field(default_factory=lambda: deque(maxlen=60))
    bbox:            Tuple[int, int, int, int] = (0, 0, 0, 0)
    last_zone:       Optional[str] = None
    last_alert_level:str = ""
    last_alert_ts:   float = 0.0
    reasons:         List[str] = field(default_factory=list)

    def label(self) -> str:
        if self.score >= ALERT_THRESHOLD:   return "ALERT"
        if self.score >= SUSPECT_THRESHOLD: return "SUSPECT"
        if self.score >= WATCH_THRESHOLD:   return "WATCH"
        return "idle"

    def color(self):
        lbl = self.label()
        return {"ALERT": COL_ALERT, "SUSPECT": COL_SUSPECT,
                "WATCH": COL_WATCH, "idle": COL_IDLE}[lbl]


COCO_SKELETON = [
    (5,7), (7,9), (6,8), (8,10),
    (5,6), (5,11), (6,12), (11,12),
    (11,13), (13,15), (12,14), (14,16),
]


def foot_point(xyxy) -> Tuple[int, int]:
    x1, y1, x2, y2 = xyxy
    return (int((x1 + x2) / 2), int(y2))


def median_height_recent(hist: deque, secs: float, now: float) -> float:
    cutoff = now - secs
    vals = [h for ts, h in hist if ts >= cutoff]
    return float(np.median(vals)) if vals else 0.0


def is_crouching(state: TrackState, current_h: float, now: float) -> bool:
    baseline = median_height_recent(state.height_hist, HEIGHT_HISTORY_SECS, now)
    if baseline < 60:
        return False
    return current_h < CROUCH_DROP_RATIO * baseline


def hand_to_pocket(keypoints_xy, keypoints_conf) -> bool:
    if keypoints_xy is None or keypoints_conf is None:
        return False
    try:
        ls, rs = keypoints_xy[5], keypoints_xy[6]
        lh, rh = keypoints_xy[11], keypoints_xy[12]
        lw, rw = keypoints_xy[9],  keypoints_xy[10]
        c_lh, c_rh = keypoints_conf[11], keypoints_conf[12]
        c_lw, c_rw = keypoints_conf[9],  keypoints_conf[10]
    except Exception:
        return False
    hip_y = (lh[1] + rh[1]) / 2
    body_x_min = min(ls[0], rs[0], lh[0], rh[0])
    body_x_max = max(ls[0], rs[0], lh[0], rh[0])
    body_w = body_x_max - body_x_min
    margin = max(15, body_w * 0.25)
    def wrist_in_pocket(wx, wy, cw, ch):
        if cw < KP_CONF_MIN or ch < KP_CONF_MIN: return False
        if wy < hip_y: return False
        return (body_x_min - margin) <= wx <= (body_x_max + margin)
    return wrist_in_pocket(lw[0], lw[1], c_lw, c_lh) or \
           wrist_in_pocket(rw[0], rw[1], c_rw, c_rh)


def compute_speed_px_s(hist: deque, now: float, window_s: float = 1.0) -> float:
    if len(hist) < 2:
        return 0.0
    cutoff = now - window_s
    pts = [(ts, pt) for ts, pt in hist if ts >= cutoff]
    if len(pts) < 2:
        pts = list(hist)[-2:]
    (t0, p0), (t1, p1) = pts[0], pts[-1]
    dt = max(t1 - t0, 1e-3)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return float(np.hypot(dx, dy) / dt)


def draw_score_bar(frame, x1, y1, x2, y2, score, color):
    bar_x = x2 + 6
    bar_h = max(y2 - y1, 60)
    bar_w = 8
    cv2.rectangle(frame, (bar_x, y1), (bar_x + bar_w, y1 + bar_h),
                  COL_BAR_BG, -1)
    s = max(0.0, min(100.0, score))
    fill_h = int((s / 100.0) * bar_h)
    cv2.rectangle(frame, (bar_x, y1 + bar_h - fill_h),
                  (bar_x + bar_w, y1 + bar_h), color, -1)
    cv2.rectangle(frame, (bar_x, y1), (bar_x + bar_w, y1 + bar_h),
                  (200, 200, 200), 1)


def draw_skeleton(frame, kp_xy, kp_conf):
    if kp_xy is None or kp_conf is None:
        return
    for a, b in COCO_SKELETON:
        if a >= len(kp_xy) or b >= len(kp_xy): continue
        if kp_conf[a] < KP_CONF_MIN or kp_conf[b] < KP_CONF_MIN: continue
        pa = (int(kp_xy[a][0]), int(kp_xy[a][1]))
        pb = (int(kp_xy[b][0]), int(kp_xy[b][1]))
        cv2.line(frame, pa, pb, (255, 230, 120), 2, cv2.LINE_AA)
    for i, (x, y) in enumerate(kp_xy):
        if kp_conf[i] < KP_CONF_MIN: continue
        cv2.circle(frame, (int(x), int(y)), 3, (0, 220, 255), -1)


def draw_banner(frame, text, color):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 58), color, -1)
    cv2.putText(frame, text, (18, 39),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, COL_TEXT, 2, cv2.LINE_AA)


def draw_hud(frame, fps, people, tracks, alert_active):
    h, w = frame.shape[:2]
    n_watch   = sum(1 for s in tracks.values() if s.label() == "WATCH")
    n_suspect = sum(1 for s in tracks.values() if s.label() == "SUSPECT")
    n_alert   = sum(1 for s in tracks.values() if s.label() == "ALERT")
    lines = [
        f"FPS         : {fps:5.1f}",
        f"People      : {people}",
        f"Tracks      : {len(tracks)}",
        f"Watch       : {n_watch}",
        f"Suspect     : {n_suspect}",
        f"Alert       : {n_alert}",
        f"State       : {'ALERT' if alert_active else 'idle'}",
    ]
    y = h - 18 - 22 * (len(lines) - 1)
    for line in lines:
        cv2.putText(frame, line, (12, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, COL_TEXT, 1, cv2.LINE_AA)
        y += 22


def update_track(state: TrackState, xyxy, kp_xy, kp_conf,
                 now: float, zones: Dict[str, Zone]) -> None:
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    state.bbox = (x1, y1, x2, y2)
    height = y2 - y1
    state.height_hist.append((now, height))

    feet = foot_point(xyxy)
    state.foot_hist.append((now, feet))

    if state.last_update_ts > 0:
        dt = now - state.last_update_ts
        state.score = max(0.0, state.score - DECAY_PER_SECOND * dt)

    in_any_zone = None
    for zname, zone in zones.items():
        if zone.contains(feet):
            in_any_zone = zname
            if zname not in state.in_zone_since:
                state.in_zone_since[zname] = now
                state.dwell_counted.setdefault(zname, False)
        else:
            if zname in state.in_zone_since:
                state.in_zone_since.pop(zname, None)
                state.dwell_counted.pop(zname, None)
    state.last_zone = in_any_zone

    new_reasons: List[str] = []

    for zname, t0 in state.in_zone_since.items():
        if state.dwell_counted.get(zname): continue
        if (now - t0) >= zones[zname].loitering_s:
            state.score += SCORE_LOITERING * zones[zname].score_mult
            state.dwell_counted[zname] = True
            new_reasons.append(f"loitering[{zname}]")

    if not state.crouch_counted and is_crouching(state, height, now):
        state.score += SCORE_CROUCH
        state.crouch_counted = True
        new_reasons.append("crouching")

    if not state.pocket_counted and kp_xy is not None and hand_to_pocket(kp_xy, kp_conf):
        state.score += SCORE_HAND_POCKET
        state.pocket_counted = True
        new_reasons.append("hand_to_pocket")

    if not state.fast_exit_counted:
        any_dwelled = any(state.dwell_counted.values())
        speed = compute_speed_px_s(state.foot_hist, now)
        if any_dwelled and speed > FAST_EXIT_PX_PER_S:
            state.score += SCORE_FAST_EXIT
            state.fast_exit_counted = True
            new_reasons.append(f"fast_exit({speed:.0f}px/s)")

    if new_reasons:
        state.reasons = (state.reasons + new_reasons)[-6:]
        log.info("ID %d -> +%s  score=%.0f", state.track_id,
                 ",".join(new_reasons), state.score)

    state.score = min(100.0, state.score)
    state.last_update_ts = now


def maybe_alert(state: TrackState, client: SSMSClient, now: float) -> Optional[str]:
    current = state.label()
    if current == "idle":
        return None
    if current == state.last_alert_level:
        return None
    if state.last_alert_ts and (now - state.last_alert_ts) < ALERT_COOLDOWN_S:
        return None

    zone_name = state.last_zone or (next(iter(state.in_zone_since)) if state.in_zone_since
                                    else "general")
    activity = int(state.score)
    note = (
        f"{current}: ID {state.track_id} - score {activity} - "
        f"reasons {','.join(state.reasons) or 'pattern'} at "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )
    if current == "ALERT":
        note = "INTRUSION: " + note

    payload = {
        "zone": zone_name,
        "people_count": 1,
        "activity_score": activity,
        "note": note,
    }
    if client.post_event(payload):
        state.last_alert_level = current
        state.last_alert_ts    = now
        log.warning("POSTED %s for ID %d at %s (score=%d)",
                    current, state.track_id, zone_name, activity)
        return current
    return None


def main() -> int:
    log.info("Loading YOLO pose model: %s", YOLO_POSE_WEIGHTS)
    model = YOLO(YOLO_POSE_WEIGHTS)

    log.info("Opening video source: %r", VIDEO_SOURCE)
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        log.error("Cannot open %r. Put surveillance_test.mp4 next to this script "
                  "or set VIDEO_SOURCE = 0 for webcam.", VIDEO_SOURCE)
        return 1

    zones = {name: Zone(name, cfg) for name, cfg in ZONES.items()}
    client = SSMSClient(API_BASE_URL, API_USERNAME, API_PASSWORD)
    client.login()

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    tracks: Dict[int, TrackState] = {}
    last_ping_ts: Optional[float] = None
    alert_hold = 0
    paused = False
    fps_smoothed = 0.0
    t_prev = time.perf_counter()

    log.info("Watching... q=quit, p=pause, s=screenshot.")

    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok:
                log.info("End of stream - looping.")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

        results = model.track(
            frame,
            imgsz=YOLO_IMGSZ,
            conf=YOLO_CONFIDENCE,
            persist=True,
            classes=[0],
            verbose=False,
            tracker="bytetrack.yaml",
        )

        boxes = results[0].boxes
        kps   = results[0].keypoints
        now = time.time()

        kp_xy_all = kps.xy.cpu().numpy() if (kps is not None and kps.xy is not None) else None
        kp_conf_all = kps.conf.cpu().numpy() if (kps is not None and kps.conf is not None) else None

        seen_ids = set()
        if boxes is not None and boxes.id is not None:
            ids = boxes.id.int().cpu().numpy()
            xyxys = boxes.xyxy.cpu().numpy()
            for i, tid in enumerate(ids):
                tid = int(tid)
                seen_ids.add(tid)
                if tid not in tracks:
                    tracks[tid] = TrackState(track_id=tid, first_seen_ts=now,
                                             last_update_ts=now)
                kp_xy = kp_xy_all[i] if kp_xy_all is not None else None
                kp_conf = kp_conf_all[i] if kp_conf_all is not None else None
                update_track(tracks[tid], xyxys[i], kp_xy, kp_conf, now, zones)
                level = maybe_alert(tracks[tid], client, now)
                if level == "ALERT":
                    alert_hold = ALERT_HOLD_FRAMES
                    snap = SCREENSHOT_DIR / f"alert_id{tid}_{int(now)}.jpg"
                    cv2.imwrite(str(snap), frame)

        stale_after = 5.0
        for tid in list(tracks.keys()):
            if tid not in seen_ids and (now - tracks[tid].last_update_ts) > stale_after:
                tracks.pop(tid, None)

        if (PING_INTERVAL_SECS > 0
                and (last_ping_ts is None or (now - last_ping_ts) >= PING_INTERVAL_SECS)
                and alert_hold == 0):
            client.post_event({
                "zone": "heartbeat",
                "people_count": len(seen_ids),
                "activity_score": 0,
                "note": "heartbeat",
            })
            last_ping_ts = now

        any_alert = any(s.label() == "ALERT" for s in tracks.values())
        for zname, zone in zones.items():
            zone_alert = any(s.last_zone == zname and s.label() == "ALERT"
                             for s in tracks.values())
            zone.draw(frame, alert=zone_alert)

        if boxes is not None and boxes.id is not None:
            ids = boxes.id.int().cpu().numpy()
            xyxys = boxes.xyxy.cpu().numpy()
            for i, tid in enumerate(ids):
                tid = int(tid)
                if tid not in tracks: continue
                state = tracks[tid]
                x1, y1, x2, y2 = [int(v) for v in xyxys[i]]
                col = state.color()
                cv2.rectangle(frame, (x1, y1), (x2, y2), col, 2)
                cv2.circle(frame, foot_point(xyxys[i]), 5, col, -1)
                label = f"ID {tid}  {state.label()}  {int(state.score)}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 10, y1),
                              col, -1)
                cv2.putText(frame, label, (x1 + 5, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (15, 15, 15),
                            2, cv2.LINE_AA)
                if DRAW_SCORE_BARS:
                    draw_score_bar(frame, x1, y1, x2, y2, state.score, col)
                if DRAW_SKELETON and kp_xy_all is not None:
                    draw_skeleton(frame, kp_xy_all[i], kp_conf_all[i])

        if alert_hold > 0:
            alert_hold -= 1
            draw_banner(frame, "ALERT - SUSPICIOUS BEHAVIOUR DETECTED", COL_BANNER)
            any_alert = True

        t_now = time.perf_counter()
        instant_fps = 1.0 / max(t_now - t_prev, 1e-6)
        t_prev = t_now
        fps_smoothed = (0.9 * fps_smoothed + 0.1 * instant_fps) if fps_smoothed else instant_fps

        draw_hud(frame, fps_smoothed, len(seen_ids), tracks, any_alert)

        if SHOW_WINDOW:
            cv2.imshow(WINDOW_NAME, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                log.info("Quit requested.")
                break
            elif key == ord("p"):
                log.info("Paused. Press any key to resume.")
                cv2.waitKey(-1)

    cap.release()
    if SHOW_WINDOW:
        cv2.destroyAllWindows()
    log.info("Camera worker stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
