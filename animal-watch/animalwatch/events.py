"""Anti-false-alarm filters: confidence, box area, zones, N consecutive frames, cooldown, quiet hours."""
from __future__ import annotations

import datetime as dt
import time
from collections import defaultdict

from .config import Camera
from .detector import Detection


def point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def anchor_point(det: Detection, anchor: str) -> tuple[float, float]:
    x1, y1, x2, y2 = det.box
    cx = (x1 + x2) / 2
    return (cx, y2) if anchor == "bottom" else (cx, (y1 + y2) / 2)


def in_zones(det: Detection, cam: Camera) -> bool:
    if not cam.zones:
        return True
    x, y = anchor_point(det, cam.anchor)
    return any(len(p) >= 3 and point_in_polygon(x, y, p) for p in cam.zones)


def in_quiet_hours(cfg: dict, now: dt.datetime | None = None) -> bool:
    q = cfg.get("quiet_hours") or {}
    if not q.get("enabled"):
        return False
    now = (now or dt.datetime.now()).time()
    start = dt.time.fromisoformat(str(q["start"]))
    end = dt.time.fromisoformat(str(q["end"]))
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # crosses midnight


class EventFilter:
    """Feed it per-camera detections each analyzed frame; returns confirmed detections to alert on."""

    def __init__(self, det_cfg: dict):
        self.cfg = det_cfg
        self.streak: dict[tuple[int, str], int] = defaultdict(int)
        self.last_alert: dict[tuple[int, str], float] = {}

    def threshold(self, cls: str) -> float:
        return float((self.cfg.get("class_confidence") or {}).get(cls, self.cfg["min_confidence"]))

    def qualifies(self, det: Detection, cam: Camera) -> bool:
        return (
            det.conf >= self.threshold(det.cls)
            and det.area >= float(self.cfg["min_box_area"])
            and in_zones(det, cam)
        )

    def reset(self, channel: int):
        for key in [k for k in self.streak if k[0] == channel]:
            self.streak[key] = 0

    def update(self, cam: Camera, dets: list[Detection], now: float | None = None) -> list[Detection]:
        now = now or time.time()
        n_needed = int(self.cfg["confirm_frames"])
        cooldown = float(self.cfg["cooldown_seconds"])
        best_now: dict[str, Detection] = {}
        for d in dets:
            if self.qualifies(d, cam) and (d.cls not in best_now or d.conf > best_now[d.cls].conf):
                best_now[d.cls] = d
        confirmed = []
        for key in [k for k in self.streak if k[0] == cam.channel and k[1] not in best_now]:
            self.streak[key] = 0
        for cls, d in best_now.items():
            key = (cam.channel, cls)
            self.streak[key] += 1
            if self.streak[key] >= n_needed and now - self.last_alert.get(key, 0) >= cooldown:
                self.last_alert[key] = now
                confirmed.append(d)  # latest box: best matches where the animal is now
                self.streak[key] = 0
        return confirmed
