"""Config loading: secrets from .env, everything else from config.yaml."""
from __future__ import annotations

import copy
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
_yaml_lock = threading.Lock()

DEFAULTS: dict = {
    "detection": {
        "model": "yolo11s.pt", "device": "mps", "fps_per_camera": 1.5, "imgsz": 640,
        "min_confidence": 0.45, "class_confidence": {}, "min_box_area": 0.003,
        "confirm_frames": 3, "cooldown_seconds": 300,
        "classes": ["bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"],
    },
    "autotune": {"enabled": True, "max_cpu_percent": 70, "min_fps": 0.5, "allow_model_downgrade": True},
    "notifications": {
        "enabled": True, "priority": 4, "class_priority": {}, "use_main_stream": True,
        "jpeg_max_bytes": 900_000, "max_width": 1920,
        "quiet_hours": {"enabled": False, "start": "23:00", "end": "06:00", "save_events": True},
    },
    "species": {
        "enabled": "auto", "ollama_url": "http://127.0.0.1:11434", "model": "qwen2.5vl:7b",
        "timeout_seconds": 60,
        "prompt": "Ce animal e în chenar? Răspunde cu specia în română, un cuvânt sau două.",
    },
    "storage": {"events_dir": "events", "retention_days": 30},
    "web": {"host": "127.0.0.1", "port": 8765},
    "power": {"caffeinate": False},
    "cameras": [],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _plain(obj):
    """ruamel CommentedMap/Seq -> plain dict/list."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


@dataclass
class Camera:
    channel: int
    name: str
    enabled: bool = True
    anchor: str = "bottom"
    zones: list = field(default_factory=list)  # list of polygons, each [[x,y],...] normalized

    @property
    def id(self) -> int:
        return self.channel


@dataclass
class Settings:
    data: dict
    cameras: list[Camera]
    dvr_ip: str
    dvr_port: int
    dvr_user: str
    dvr_pass: str
    ntfy_server: str
    ntfy_topic: str
    ntfy_token: str
    config_path: Path

    def section(self, name: str) -> dict:
        return self.data[name]

    def rtsp_url(self, channel: int, main: bool = False) -> str:
        stream = f"{channel}0{1 if main else 2}"
        user = quote(self.dvr_user, safe="")
        pw = quote(self.dvr_pass, safe="")
        return f"rtsp://{user}:{pw}@{self.dvr_ip}:{self.dvr_port}/Streaming/Channels/{stream}"

    def redact(self, text: str) -> str:
        if self.dvr_pass:
            text = text.replace(self.dvr_pass, "***").replace(quote(self.dvr_pass, safe=""), "***")
        return text

    def camera(self, channel: int) -> Camera | None:
        return next((c for c in self.cameras if c.channel == channel), None)

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ROOT / p


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    return y


def load(config_path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    config_path = config_path or Path(os.environ.get("ANIMALWATCH_CONFIG", ROOT / "config.yaml"))
    if not config_path.exists():
        config_path = ROOT / "config.example.yaml"
    with _yaml_lock, open(config_path, encoding="utf-8") as f:
        raw = _plain(_yaml().load(f) or {})
    data = _merge(DEFAULTS, raw)
    cams = [
        Camera(
            channel=int(c["channel"]),
            name=str(c.get("name") or f"Camera {c['channel']}"),
            enabled=bool(c.get("enabled", True)),
            anchor=str(c.get("anchor", "bottom")),
            zones=[[[float(x), float(y)] for x, y in poly] for poly in (c.get("zones") or [])],
        )
        for c in data["cameras"]
    ]
    return Settings(
        data=data, cameras=cams,
        dvr_ip=os.environ.get("DVR_IP", ""), dvr_port=int(os.environ.get("DVR_PORT", "554") or 554),
        dvr_user=os.environ.get("DVR_USER", ""), dvr_pass=os.environ.get("DVR_PASS", ""),
        ntfy_server=(os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/"),
        ntfy_topic=os.environ.get("NTFY_TOPIC", ""), ntfy_token=os.environ.get("NTFY_TOKEN", ""),
        config_path=config_path,
    )


def update_camera_fields(config_path: Path, channel: int, **fields) -> None:
    """Edit one camera entry in config.yaml in place, keeping comments."""
    from ruamel.yaml.comments import CommentedSeq

    with _yaml_lock:
        y = _yaml()
        with open(config_path, encoding="utf-8") as f:
            doc = y.load(f)
        for cam in doc.get("cameras") or []:
            if int(cam["channel"]) == channel:
                for k, v in fields.items():
                    if k == "zones":
                        seq = CommentedSeq()
                        for poly in v:
                            p = CommentedSeq([CommentedSeq([round(float(x), 4), round(float(yv), 4)]) for x, yv in poly])
                            p.fa.set_flow_style()
                            for pt in p:
                                pt.fa.set_flow_style()
                            seq.append(p)
                        seq.fa.set_flow_style()
                        cam[k] = seq
                    else:
                        cam[k] = v
                break
        else:
            raise KeyError(f"camera channel {channel} not in config")
        tmp = config_path.with_suffix(".yaml.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            y.dump(doc, f)
        tmp.replace(config_path)
