import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import ROOT


def setup(name: str = "animalwatch", level=logging.INFO) -> logging.Logger:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_aw_setup", False):
        return logging.getLogger(name)
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)-14s %(message)s")
    fh = RotatingFileHandler(logs / f"{name}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    # Console output only when interactive; under launchd stdout goes to a non-rotating file.
    if sys.stderr.isatty():
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)
    for noisy in ("werkzeug", "urllib3", "ultralytics"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._aw_setup = True
    return logging.getLogger(name)
