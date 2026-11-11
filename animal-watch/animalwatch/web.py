"""Local web UI (127.0.0.1 only): event history, zone editor, status, test notification."""
from __future__ import annotations

import datetime as dt
import logging

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

from . import config as configmod
from . import imaging, notify
from .capture import grab_frame
from .config import ROOT, Settings
from .labels import RO, ro
from .storage import Store

log = logging.getLogger("animalwatch.web")


def _test_image() -> np.ndarray:
    img = np.full((720, 1280, 3), (60, 90, 60), np.uint8)
    cv2.putText(img, "Animal Watch - test", (60, 360), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (255, 255, 255), 5, cv2.LINE_AA)
    cv2.putText(img, dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (60, 460), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                (230, 230, 230), 3, cv2.LINE_AA)
    return img


def send_test_notification(s: Settings, image: np.ndarray | None = None) -> bool:
    img = image if image is not None else _test_image()
    jpeg = imaging.encode_jpeg(img, int(s.section("notifications")["jpeg_max_bytes"]))
    return notify.send(s.ntfy_server, s.ntfy_topic, "Test Animal Watch – Pisică – Camera 3",
                       "Notificare de probă. Dacă vezi poza, totul e configurat corect.",
                       image=jpeg, filename="test.jpg", tags=["white_check_mark", "cat"], priority=3,
                       token=s.ntfy_token)


def create_app(s: Settings, store: Store, service=None) -> Flask:
    app = Flask(__name__, template_folder=str(ROOT / "animalwatch" / "templates"))
    events_dir = store.dir

    def require_json():
        # Blocks cross-site form posts from other web pages: they cannot send application/json
        # to localhost without a CORS preflight, which we never answer.
        if not request.is_json:
            abort(415)

    @app.get("/")
    def index():
        cam = request.args.get("camera", type=int)
        animal = request.args.get("animal") or None
        day = request.args.get("day") or None
        page = max(1, request.args.get("page", 1, type=int))
        rows = store.query(cam, animal, day, limit=60, offset=(page - 1) * 60)
        for r in rows:
            r["cls_ro"] = ro(r["cls"])
        return render_template("events.html", rows=rows, facets=store.facets(), camera=cam, animal=animal,
                               day=day, page=page, cameras=s.cameras, ro=ro)

    @app.get("/events/<path:rel>")
    def event_image(rel):
        return send_from_directory(events_dir, rel)

    @app.get("/zones")
    def zones_page():
        return render_template("zones.html", cameras=s.cameras)

    @app.get("/api/cameras")
    def api_cameras():
        return jsonify([{"channel": c.channel, "name": c.name, "enabled": c.enabled, "anchor": c.anchor,
                         "zones": c.zones} for c in s.cameras])

    @app.get("/api/snapshot/<int:ch>.jpg")
    def api_snapshot(ch):
        img = None
        if service is not None and ch in service.streams:
            img, _, _ = service.streams[ch].latest()
        if img is None:
            f = ROOT / "snapshots_setup" / f"cam{ch}_main.jpg"
            if f.exists() and request.args.get("live") != "1":
                return send_from_directory(f.parent, f.name)
            if s.dvr_ip:
                img = grab_frame(s.rtsp_url(ch, main=False), timeout=15)
        if img is None:
            img = np.full((360, 640, 3), 40, np.uint8)
            cv2.putText(img, f"Canal {ch}: fara imagine", (40, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (200, 200, 200), 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/zones/<int:ch>")
    def api_save_zones(ch):
        require_json()
        body = request.get_json()
        zones = body.get("zones") or []
        anchor = body.get("anchor", "bottom")
        if anchor not in ("bottom", "center"):
            abort(400)
        clean = []
        for poly in zones:
            pts = [[min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y)))] for x, y in poly]
            if len(pts) >= 3:
                clean.append(pts)
        cam = s.camera(ch)
        if cam is None:
            abort(404)
        if s.config_path.name == "config.example.yaml":
            return jsonify({"ok": False, "error": "Nu există config.yaml (rulează install.sh)."}), 400
        configmod.update_camera_fields(s.config_path, ch, zones=clean, anchor=anchor)
        cam.zones, cam.anchor = clean, anchor  # live update, no restart needed
        log.info("zones saved for %s: %d polygon(s), anchor=%s", cam.name, len(clean), anchor)
        return jsonify({"ok": True, "zones": clean})

    @app.post("/api/test-notify")
    def api_test_notify():
        require_json()
        return jsonify({"ok": send_test_notification(s)})

    @app.get("/api/status")
    def api_status():
        if service is None:
            return jsonify({"running": False, "note": "serviciul de detecție nu rulează în acest proces"})
        return jsonify({"running": True, **service.status()})

    @app.get("/api/labels")
    def api_labels():
        return jsonify(RO)

    return app


def main():
    """Standalone web UI (history + zone editor) without the detection service."""
    from .logutil import setup

    setup("web")
    s = configmod.load()
    store = Store(s.path(s.section("storage")["events_dir"]))
    web = s.section("web")
    port = int(web["port"]) + 1  # don't collide with the running service
    print(f"Deschide http://127.0.0.1:{port}/  (Ctrl+C pentru oprire)")
    create_app(s, store).run(host="127.0.0.1", port=port, threaded=True)
