"""Main service: capture threads + detection loop + event pipeline + web UI + housekeeping."""
from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import subprocess
import sys
import threading
import time

import psutil

from . import config as configmod
from .capture import CameraStream
from .detector import Detector
from .events import EventFilter
from .pipeline import EventPipeline, Job
from .species import SpeciesIdentifier
from .storage import Store

log = logging.getLogger("animalwatch.app")


class App:
    def __init__(self, settings: configmod.Settings):
        self.s = settings
        det = settings.section("detection")
        self.fps = float(det["fps_per_camera"])
        self.target_fps = self.fps
        self.store = Store(settings.path(settings.section("storage")["events_dir"]))
        self.species = SpeciesIdentifier(settings.section("species"))
        self.pipeline = EventPipeline(settings, self.store, self.species)
        self.filter = EventFilter(det)
        self.detector: Detector | None = None
        self.streams: dict[int, CameraStream] = {}
        self._stop = threading.Event()
        self._last_seq: dict[int, int] = {}
        self.cycle_ms = 0.0
        self.perf: dict = {}
        self.started = time.time()
        self._caffeinate: subprocess.Popen | None = None
        self._model_lock = threading.Lock()

    # ---------- lifecycle ----------
    def start(self):
        det = self.s.section("detection")
        min_conf = min([float(det["min_confidence"])] + [float(v) for v in (det.get("class_confidence") or {}).values()])
        self.detector = Detector(det["model"], det["device"], det["classes"], int(det["imgsz"]), min_conf)
        for cam in self.s.cameras:
            if cam.enabled:
                st = CameraStream(cam.channel, cam.name, self.s.rtsp_url(cam.channel), self.s.redact)
                self.streams[cam.channel] = st
                st.start()
        log.info("started %d cameras: %s", len(self.streams), [c.name for c in self.s.cameras if c.enabled])
        self.pipeline.start()
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()
        threading.Thread(target=self._autotune, name="autotune", daemon=True).start()
        if self.s.section("power").get("caffeinate"):
            self._start_caffeinate()
        from .web import create_app

        web = self.s.section("web")
        flask_app = create_app(self.s, self.store, self)
        threading.Thread(
            target=lambda: flask_app.run(host=web["host"], port=int(web["port"]), threaded=True, use_reloader=False),
            name="web", daemon=True).start()
        log.info("web UI: http://%s:%s", web["host"], web["port"])

    def stop(self, *_):
        log.info("stopping")
        self._stop.set()
        for st in self.streams.values():
            st.stop()
        self.pipeline.stop()
        if self._caffeinate:
            self._caffeinate.terminate()

    def _start_caffeinate(self):
        if sys.platform != "darwin":
            return
        # -s: prevent system sleep while on AC power; -w: ends automatically with this process
        self._caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-s", "-w", str(os.getpid())])
        log.info("caffeinate -s active (Mac stays awake while on AC power)")

    # ---------- main loop ----------
    def run_forever(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.start()
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.step()
            except Exception:
                log.exception("detection step failed")
            self.cycle_ms = (time.time() - t0) * 1000
            interval = 1.0 / max(self.fps, 0.05)
            self._stop.wait(max(0.0, interval - (time.time() - t0)))

    def step(self):
        """One detection pass over all cameras that have a new frame (batched on the GPU)."""
        frames, cams, ts = [], [], []
        for ch, st in self.streams.items():
            cam = self.s.camera(ch)
            frame, t, seq = st.latest()
            if not st.healthy or frame is None:
                self.filter.reset(ch)
                continue
            if self._last_seq.get(ch) == seq:
                continue  # no new frame since last pass
            self._last_seq[ch] = seq
            frames.append(frame)
            cams.append(cam)
            ts.append(t)
        if not frames:
            return
        with self._model_lock:
            results = self.detector.detect(frames)
        now = time.time()
        for cam, frame, dets in zip(cams, frames, results):
            for d in self.filter.update(cam, dets, now):
                log.info("[%s] confirmed %s %.2f box=%s", cam.name, d.cls, d.conf, d.to_dict()["box"])
                self.pipeline.submit(Job(cam, d, frame.copy(), dt.datetime.now()))

    # ---------- background ----------
    def _housekeeping(self):
        retention = int(self.s.section("storage")["retention_days"])
        while not self._stop.is_set():
            try:
                self.store.cleanup(retention)
            except Exception:
                log.exception("cleanup failed")
            self._stop.wait(6 * 3600)

    def _autotune(self):
        cfg = self.s.section("autotune")
        proc = psutil.Process()
        proc.cpu_percent(None)
        psutil.cpu_percent(None)
        overloaded_rounds = 0
        while not self._stop.wait(30):
            sys_cpu = psutil.cpu_percent(None)
            proc_cpu = proc.cpu_percent(None)
            interval_ms = 1000.0 / max(self.fps, 0.05)
            mps_mb = None
            try:
                import torch

                if self.detector and self.detector.device == "mps":
                    mps_mb = round(torch.mps.current_allocated_memory() / 1e6)
            except Exception:
                pass
            self.perf = {
                "system_cpu": sys_cpu, "process_cpu": proc_cpu, "fps_per_camera": round(self.fps, 2),
                "infer_ms": round(self.detector.last_infer_ms if self.detector else 0),
                "cycle_ms": round(self.cycle_ms), "mps_mem_mb": mps_mb,
                "model": self.detector.model_name if self.detector else None,
                "device": self.detector.device if self.detector else None,
                "rss_mb": round(proc.memory_info().rss / 1e6),
            }
            log.info("perf %s", self.perf)
            if not cfg.get("enabled", True):
                continue
            too_busy = sys_cpu > float(cfg["max_cpu_percent"]) or self.cycle_ms > 0.9 * interval_ms
            if too_busy:
                overloaded_rounds += 1
                new = max(float(cfg["min_fps"]), self.fps * 0.75)
                if new < self.fps:
                    log.warning("autotune: load high (cpu %.0f%%, cycle %.0fms) -> fps %.2f -> %.2f",
                                sys_cpu, self.cycle_ms, self.fps, new)
                    self.fps = new
                elif overloaded_rounds >= 4 and cfg.get("allow_model_downgrade") and self._downgrade_model():
                    overloaded_rounds = 0
            else:
                overloaded_rounds = 0
                if sys_cpu < float(cfg["max_cpu_percent"]) - 25 and self.fps < self.target_fps:
                    self.fps = min(self.target_fps, self.fps * 1.25)
                    log.info("autotune: load ok -> fps %.2f", self.fps)

    def _downgrade_model(self) -> bool:
        name = self.detector.model_name
        if "n." in name or name.endswith("n.pt"):
            return False
        smaller = name.replace("s.pt", "n.pt").replace("m.pt", "n.pt")
        if smaller == name:
            return False
        det = self.s.section("detection")
        log.warning("autotune: still overloaded at min fps, switching model %s -> %s", name, smaller)
        new = Detector(smaller, det["device"], det["classes"], int(det["imgsz"]), self.detector.min_conf)
        with self._model_lock:
            self.detector = new
        return True

    def status(self) -> dict:
        cams = []
        for cam in self.s.cameras:
            st = self.streams.get(cam.channel)
            _, t, seq = st.latest() if st else (None, 0, 0)
            cams.append({
                "channel": cam.channel, "name": cam.name, "enabled": cam.enabled,
                "healthy": bool(st and st.healthy), "last_frame_age_s": round(time.time() - t, 1) if t else None,
                "frames": seq, "reconnects": st.reconnects if st else 0, "error": st.last_error if st else "",
                "zones": len(cam.zones),
            })
        return {"uptime_s": round(time.time() - self.started), "perf": self.perf, "cameras": cams,
                "species_enabled": self.species.available(), "recent": self.pipeline.results[-5:]}


def main():
    from .logutil import setup

    setup()
    s = configmod.load()
    if not s.dvr_ip:
        log.error("DVR_IP missing: run install.sh or create .env")
        sys.exit(2)
    App(s).run_forever()
