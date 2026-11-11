"""YOLO wrapper restricted to animal classes."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .config import ROOT

log = logging.getLogger("animalwatch.detector")


@dataclass
class Detection:
    cls: str
    conf: float
    box: tuple[float, float, float, float]  # normalized x1, y1, x2, y2

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def to_dict(self) -> dict:
        return {"cls": self.cls, "conf": round(self.conf, 3), "box": [round(v, 4) for v in self.box]}


def pick_device(wanted: str) -> str:
    import torch

    if wanted == "mps" and not torch.backends.mps.is_available():
        log.warning("MPS not available, falling back to CPU")
        return "cpu"
    if wanted.startswith("cuda") and not torch.cuda.is_available():
        return "cpu"
    return wanted


class Detector:
    def __init__(self, model: str, device: str, classes: list[str], imgsz: int = 640, min_conf: float = 0.25):
        from ultralytics import YOLO

        self.model_name = model
        weights = ROOT / model if (ROOT / model).exists() else model
        self.model = YOLO(str(weights))
        self.device = pick_device(device)
        self.imgsz = imgsz
        self.min_conf = min_conf
        names = self.model.names
        wanted = set(classes)
        self.class_ids = [i for i, n in names.items() if n in wanted]
        missing = wanted - {names[i] for i in self.class_ids}
        if missing:
            log.warning("classes not in model, ignored: %s", sorted(missing))
        self.last_infer_ms = 0.0
        # warm-up (first MPS call compiles kernels)
        self.detect([np.zeros((360, 640, 3), np.uint8)])
        log.info("model %s on %s, classes=%s", model, self.device, [names[i] for i in self.class_ids])

    def detect(self, frames: list[np.ndarray]) -> list[list[Detection]]:
        if not frames:
            return []
        t0 = time.perf_counter()
        results = self.model.predict(
            frames, imgsz=self.imgsz, conf=self.min_conf, classes=self.class_ids,
            device=self.device, verbose=False,
        )
        self.last_infer_ms = (time.perf_counter() - t0) * 1000
        out = []
        for r in results:
            dets = []
            if r.boxes is not None and len(r.boxes):
                xyxyn = r.boxes.xyxyn.cpu().numpy()
                confs = r.boxes.conf.cpu().numpy()
                clss = r.boxes.cls.cpu().numpy().astype(int)
                for b, c, k in zip(xyxyn, confs, clss):
                    dets.append(Detection(self.model.names[int(k)], float(c), tuple(float(v) for v in b)))
            out.append(dets)
        return out
