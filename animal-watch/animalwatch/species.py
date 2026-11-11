"""Optional species identification with a local Ollama vision model."""
from __future__ import annotations

import base64
import logging
import re
import time

import requests

log = logging.getLogger("animalwatch.species")


class SpeciesIdentifier:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.url = cfg["ollama_url"].rstrip("/")
        self.model = cfg["model"]
        self._available: bool | None = None
        self._checked_at = 0.0

    def available(self) -> bool:
        mode = str(self.cfg.get("enabled", "auto")).lower()
        if mode in ("false", "0", "no", "off"):
            return False
        # re-check every 5 min so starting Ollama later is picked up
        if self._available is not None and time.time() - self._checked_at < 300:
            return self._available
        self._checked_at = time.time()
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=3)
            names = [m.get("name", "") for m in r.json().get("models", [])]
            base = self.model.split(":")[0]
            ok = any(n == self.model or n.split(":")[0] == base for n in names)
            if not ok and self._available is not False:
                log.warning("Ollama runs but model %s is not pulled (ollama pull %s)", self.model, self.model)
            self._available = ok
        except Exception:
            if self._available is not False:
                log.info("Ollama not reachable at %s: species step disabled", self.url)
            self._available = False
        return self._available

    def identify(self, jpeg: bytes) -> str | None:
        if not self.available():
            return None
        try:
            t0 = time.time()
            r = requests.post(f"{self.url}/api/generate", json={
                "model": self.model, "prompt": self.cfg["prompt"], "stream": False,
                "images": [base64.b64encode(jpeg).decode()],
                "options": {"temperature": 0, "num_predict": 20},
                "keep_alive": "30m",
            }, timeout=float(self.cfg.get("timeout_seconds", 60)))
            r.raise_for_status()
            text = clean(r.json().get("response", ""))
            log.info("species: %r in %.1fs", text, time.time() - t0)
            return text or None
        except Exception as e:
            log.warning("species identification failed: %s", e)
            return None


def clean(text: str) -> str:
    text = text.strip().splitlines()[0] if text.strip() else ""
    text = re.sub(r"^(este|e|it is|răspuns:)\s+", "", text, flags=re.I)
    text = re.sub(r"^(o|un|una|a|an)\s+", "", text, flags=re.I)
    text = text.strip(" .,:;!\"'*`")
    words = text.split()
    text = " ".join(words[:3])
    return text[:1].upper() + text[1:40] if text else ""
