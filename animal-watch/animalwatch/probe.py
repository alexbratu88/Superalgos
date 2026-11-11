"""Step 2: test the DVR connection and read every channel; save one snapshot per camera."""
from __future__ import annotations

import platform
import socket
import subprocess

import cv2
import numpy as np

from . import config as configmod
from .capture import grab_frame_verbose
from .config import ROOT


def ping(host: str) -> bool:
    flag = ["-W", "1000"] if platform.system() == "Darwin" else ["-W", "1"]
    try:
        return subprocess.run(["ping", "-c", "2", *flag, host], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def port_open(host: str, port: int, timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def looks_blank(img: np.ndarray) -> bool:
    small = cv2.resize(img, (160, 90))
    return float(small.std()) < 4.0  # uniform black/blue "no video" screen


def run(channels: list[int], update_config: bool = False) -> dict[int, bool]:
    s = configmod.load()
    if not s.dvr_ip:
        print("Lipsește DVR_IP în .env")
        return {}
    out_dir = ROOT / "snapshots_setup"
    out_dir.mkdir(exist_ok=True)
    print(f"DVR {s.dvr_ip}")
    print(f"  ping: {'OK' if ping(s.dvr_ip) else 'fără răspuns (poate fi blocat ICMP; continuăm)'}")
    if not port_open(s.dvr_ip, s.dvr_port):
        print(f"  port RTSP {s.dvr_port}: ÎNCHIS / inaccesibil. Verifică IP-ul, rețeaua și că RTSP e activ pe DVR.")
        return {}
    print(f"  port RTSP {s.dvr_port}: deschis\n")
    print(f"{'Canal':<6}{'Substream (X02)':<28}{'Main stream (X01)':<28}Rezultat")
    has_image: dict[int, bool] = {}
    errors: list[str] = []
    thumbs = []
    for ch in channels:
        row = [f"{ch:<6}"]
        ok_any = False
        for main in (False, True):
            img, err = grab_frame_verbose(s.rtsp_url(ch, main=main), timeout=20)
            if img is None:
                err = s.redact(err)
                if "401" in err:
                    err = "401: user/parolă greșite sau fără drept"
                elif "404" in err:
                    err = "404: canal inexistent"
                errors.append(f"  canal {ch} {'main' if main else 'sub'}: {err}")
                row.append(f"{'eroare (vezi jos)':<28}")
                continue
            h, w = img.shape[:2]
            blank = looks_blank(img)
            row.append(f"{f'{w}x{h}' + (' (fără semnal)' if blank else ''):<28}")
            cv2.imwrite(str(out_dir / f"cam{ch}_{'main' if main else 'sub'}.jpg"), img)
            if main and not blank:
                thumbs.append((ch, img))
            ok_any = ok_any or not blank
        has_image[ch] = ok_any
        row.append("IMAGINE" if ok_any else "—")
        print("".join(row), flush=True)

    if thumbs:  # contact sheet with all cameras
        tiles = []
        for ch, img in thumbs:
            t = cv2.resize(img, (640, 360))
            cv2.putText(t, f"Canal {ch}", (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(t, f"Canal {ch}", (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
            tiles.append(t)
        while len(tiles) % 2:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
        cv2.imwrite(str(out_dir / "toate_camerele.jpg"), sheet)
    if errors:
        print("\nErori:\n" + "\n".join(errors))
    print(f"\nCanale cu imagine: {[c for c, v in has_image.items() if v]}")
    print(f"Snapshot-uri în {out_dir}/ (toate_camerele.jpg = toate pe o pagină)")

    if update_config and s.config_path.name == "config.yaml":
        for ch, ok in has_image.items():
            if s.camera(ch):
                configmod.update_camera_fields(s.config_path, ch, enabled=ok)
        print("config.yaml actualizat: camerele fără imagine au enabled: false")
    return has_image
