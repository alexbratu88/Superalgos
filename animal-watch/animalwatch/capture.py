"""RTSP capture: one thread per camera, keeps only the latest frame, reconnects with backoff."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np

# Force RTSP over TCP for the OpenCV FFmpeg backend (must be set before opening captures).
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;10000000")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

log = logging.getLogger("animalwatch.capture")

STALE_SECONDS = 15.0


def open_capture(url: str) -> cv2.VideoCapture:
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000]
    try:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
    except TypeError:  # very old OpenCV
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


class CameraStream(threading.Thread):
    def __init__(self, channel: int, name: str, url: str, redact=lambda s: s):
        super().__init__(name=f"cam{channel}", daemon=True)
        self.channel = channel
        self.cam_name = name
        self.url = url
        self.redact = redact
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._ts = 0.0
        self._seq = 0
        self._stop = threading.Event()
        self.connected = False
        self.reconnects = 0
        self.last_error = ""

    def latest(self) -> tuple[np.ndarray | None, float, int]:
        with self._lock:
            return self._frame, self._ts, self._seq

    @property
    def healthy(self) -> bool:
        return self.connected and (time.time() - self._ts) < STALE_SECONDS

    def stop(self):
        self._stop.set()

    def run(self):
        backoff = 2.0
        while not self._stop.is_set():
            cap = open_capture(self.url)
            if not cap.isOpened():
                self.connected = False
                self.last_error = "nu se poate deschide stream-ul"
                log.warning("[%s] cannot open stream, retry in %.0fs", self.cam_name, backoff)
                cap.release()
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            log.info("[%s] connected", self.cam_name)
            self.connected = True
            got_any = False
            fails = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if fails >= 5:
                        break
                    time.sleep(0.2)
                    continue
                fails = 0
                if not got_any:
                    got_any = True
                    backoff = 2.0
                with self._lock:
                    self._frame = frame
                    self._ts = time.time()
                    self._seq += 1
            cap.release()
            self.connected = False
            if self._stop.is_set():
                break
            self.reconnects += 1
            self.last_error = "stream întrerupt"
            log.warning("[%s] stream lost, reconnect in %.0fs", self.cam_name, backoff)
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 60.0)


def ffmpeg_bin() -> str | None:
    for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    return None


def grab_frame(url: str, timeout: float = 20.0) -> np.ndarray | None:
    """Grab one decoded frame (used for main-stream snapshots and probing)."""
    return grab_frame_verbose(url, timeout)[0]


def grab_frame_verbose(url: str, timeout: float = 20.0) -> tuple[np.ndarray | None, str]:
    ff = ffmpeg_bin()
    err = ""
    if ff:
        cmd = [ff, "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
               "-i", url, "-frames:v", "1", "-q:v", "2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout)
            if out.returncode == 0 and out.stdout:
                img = cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img, ""
            err = out.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["ffmpeg failed"]
            err = err[0]
        except subprocess.TimeoutExpired:
            err = f"timeout {timeout:.0f}s"
    # Fallback: OpenCV
    cap = open_capture(url)
    try:
        if not cap.isOpened():
            return None, err or "OpenCV nu poate deschide stream-ul"
        for _ in range(10):  # first frames can be grey until a keyframe arrives
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame, ""
        return None, err or "niciun cadru citit"
    finally:
        cap.release()
