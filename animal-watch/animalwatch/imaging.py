"""Draw boxes and compress JPEGs under a size limit."""
from __future__ import annotations

import cv2
import numpy as np

from .labels import ro


def annotate(img: np.ndarray, dets: list, label_override: str | None = None) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    th = max(2, round(min(w, h) / 300))
    fs = max(0.6, min(w, h) / 900)
    for d in dets:
        x1, y1, x2, y2 = d.box
        p1 = (int(x1 * w), int(y1 * h))
        p2 = (int(x2 * w), int(y2 * h))
        cv2.rectangle(out, p1, p2, (0, 0, 255), th)
        text = f"{label_override or ro(d.cls)} {d.conf:.0%}"
        text = _ascii(text)
        (tw, tht), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        ty = p1[1] - 6 if p1[1] - tht - 10 > 0 else p2[1] + tht + 6
        cv2.rectangle(out, (p1[0], ty - tht - 6), (p1[0] + tw + 8, ty + base), (0, 0, 255), -1)
        cv2.putText(out, text, (p1[0] + 4, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th, cv2.LINE_AA)
    return out


_TR = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaissttAAISSTT")


def _ascii(s: str) -> str:
    # OpenCV's Hershey fonts only render ASCII
    return s.translate(_TR).encode("ascii", "replace").decode()


def encode_jpeg(img: np.ndarray, max_bytes: int = 900_000, max_width: int = 1920) -> bytes:
    h, w = img.shape[:2]
    if w > max_width:
        img = cv2.resize(img, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    for q in (88, 80, 72, 64, 55, 45, 35):
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        if ok and len(buf) <= max_bytes:
            return buf.tobytes()
    while True:  # still too big: downscale
        h, w = img.shape[:2]
        img = cv2.resize(img, (int(w * 0.75), int(h * 0.75)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if len(buf) <= max_bytes or w < 320:
            return buf.tobytes()
