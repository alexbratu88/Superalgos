"""What happens after a confirmed detection: snapshot -> species -> annotate -> save -> notify."""
from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from . import imaging, notify
from .capture import grab_frame
from .config import Camera, Settings
from .detector import Detection
from .events import in_quiet_hours
from .labels import TAGS, ro
from .species import SpeciesIdentifier
from .storage import Store

log = logging.getLogger("animalwatch.pipeline")


@dataclass
class Job:
    camera: Camera
    det: Detection
    sub_frame: np.ndarray
    when: dt.datetime
    main_frame: np.ndarray | None = None  # set by the simulator; otherwise grabbed from main stream


class EventPipeline:
    def __init__(self, settings: Settings, store: Store, species: SpeciesIdentifier | None = None):
        self.s = settings
        self.store = store
        self.species = species
        self.q: queue.Queue[Job | None] = queue.Queue(maxsize=50)
        self._thread = threading.Thread(target=self._run, name="events", daemon=True)
        self.results: list[dict] = []  # last results, for tests/status

    def start(self):
        self._thread.start()

    def stop(self):
        self.q.put(None)

    def submit(self, job: Job):
        try:
            self.q.put_nowait(job)
        except queue.Full:
            log.warning("event queue full, dropping event from %s", job.camera.name)

    def _run(self):
        while True:
            job = self.q.get()
            if job is None:
                return
            try:
                self.process(job)
            except Exception:
                log.exception("event processing failed")

    def process(self, job: Job) -> dict:
        ncfg = self.s.section("notifications")
        cam, det = job.camera, job.det
        quiet = in_quiet_hours(ncfg, job.when)
        if quiet and not ncfg["quiet_hours"].get("save_events", True):
            log.info("quiet hours: ignoring %s on %s", det.cls, cam.name)
            return {}

        img = job.main_frame
        source = "simulat"
        if img is None and ncfg.get("use_main_stream", True):
            img = grab_frame(self.s.rtsp_url(cam.channel, main=True))
            source = "main"
            if img is None:
                log.warning("[%s] main stream snapshot failed, using substream frame", cam.name)
        if img is None:
            img, source = job.sub_frame, "sub"

        species = None
        if self.species is not None:
            preview = imaging.encode_jpeg(imaging.annotate(img, [det]), max_bytes=600_000, max_width=1280)
            species = self.species.identify(preview)

        label = species or ro(det.cls)
        jpeg = imaging.encode_jpeg(imaging.annotate(img, [det], label_override=label),
                                   max_bytes=int(ncfg["jpeg_max_bytes"]), max_width=int(ncfg["max_width"]))
        full, rel = self.store.image_path(job.when, cam.channel, det.cls)
        full.write_bytes(jpeg)
        event_id = self.store.add(job.when, cam.channel, cam.name, det.cls, det.conf, species, rel, False,
                                  list(det.box))

        sent = False
        title = f"{label} – {cam.name}"
        if ncfg.get("enabled", True) and not quiet:
            msg = f"{job.when:%H:%M:%S} · {ro(det.cls)} {det.conf:.0%}"
            if species and species.lower() != ro(det.cls).lower():
                msg += f" · specie: {species}"
            prio = int((ncfg.get("class_priority") or {}).get(det.cls, ncfg["priority"]))
            sent = notify.send(self.s.ntfy_server, self.s.ntfy_topic, title, msg, image=jpeg,
                               filename=f"{det.cls}_cam{cam.channel}_{job.when:%Y%m%d_%H%M%S}.jpg",
                               tags=[TAGS.get(det.cls, "paw_prints")], priority=prio, token=self.s.ntfy_token)
            if sent:
                self.store.set_notified(event_id, True)
        log.info("EVENT #%d %s conf=%.2f species=%s cam=%s img=%s(%dKB) notified=%s%s",
                 event_id, det.cls, det.conf, species, cam.name, source, len(jpeg) // 1024, sent,
                 " (quiet hours)" if quiet else "")
        res = {"id": event_id, "title": title, "species": species, "image": str(full), "bytes": len(jpeg),
               "notified": sent, "source": source}
        self.results = (self.results + [res])[-20:]
        return res


def load_image(path: str) -> np.ndarray:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    return img
