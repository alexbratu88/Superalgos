"""CLI: python -m animalwatch <command>"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .config import ROOT

TEST_IMAGES = {
    "pisica.jpg": "https://raw.githubusercontent.com/EliSchwartz/imagenet-sample-images/master/n02123045_tabby.JPEG",
    "caine.jpg": "https://raw.githubusercontent.com/pjreddie/darknet/master/data/dog.jpg",
    "vulpe.jpg": "https://raw.githubusercontent.com/EliSchwartz/imagenet-sample-images/master/n02119022_red_fox.JPEG",
}


def default_test_images() -> list[str]:
    import requests

    d = ROOT / "tests" / "images"
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, url in TEST_IMAGES.items():
        p = d / name
        if not p.exists():
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                p.write_bytes(r.content)
            except Exception as e:
                print(f"nu pot descărca {url}: {e}")
                continue
        paths.append(str(p))
    return paths


def cmd_selftest(args):
    import cv2

    from . import config as configmod
    from . import imaging
    from .detector import Detector

    s = configmod.load()
    det = s.section("detection")
    d = Detector(args.model or det["model"], args.device or det["device"], det["classes"], int(det["imgsz"]), 0.25)
    out = ROOT / "snapshots_setup"
    out.mkdir(exist_ok=True)
    print(f"model {d.model_name} pe {d.device}")
    for path in args.images or default_test_images():
        img = cv2.imread(path)
        if img is None:
            print(f"{path}: nu pot citi imaginea")
            continue
        times = []
        for _ in range(3):
            dets = d.detect([img])[0]
            times.append(d.last_infer_ms)
        desc = ", ".join(f"{x.cls} {x.conf:.0%} (aria {x.area:.1%})" for x in dets) or "niciun animal COCO"
        print(f"{Path(path).name}: {desc}   [{min(times):.0f} ms]")
        cv2.imwrite(str(out / f"selftest_{Path(path).stem}.jpg"), imaging.annotate(img, dets))
    print(f"imagini adnotate în {out}/selftest_*.jpg")


def cmd_simulate(args):
    """Feed a still image through the full pipeline as if it came from a camera."""
    import cv2

    from . import config as configmod
    from .detector import Detector
    from .events import EventFilter
    from .pipeline import EventPipeline, Job
    from .species import SpeciesIdentifier
    from .storage import Store

    s = configmod.load()
    det = s.section("detection")
    cam = s.camera(args.camera) or (s.cameras[0] if s.cameras else None)
    if cam is None:
        sys.exit("nicio cameră în config")
    if args.no_notify:
        s.data["notifications"]["enabled"] = False
    img = cv2.imread(args.image)
    if img is None:
        sys.exit(f"nu pot citi {args.image}")
    d = Detector(det["model"], det["device"], det["classes"], int(det["imgsz"]), 0.25)
    flt = EventFilter(det)
    store = Store(s.path(s.section("storage")["events_dir"]))
    pipe = EventPipeline(s, store, SpeciesIdentifier(s.section("species")))
    n = int(det["confirm_frames"])
    print(f"Simulez {n + 1} cadre pe {cam.name} (zone: {len(cam.zones)}, confirmare: {n} cadre)")
    events = []
    for i in range(n + 1):
        dets = d.detect([img])[0]
        conf = flt.update(cam, dets)
        q = [x for x in dets if flt.qualifies(x, cam)]
        print(f"  cadru {i + 1}: {len(dets)} detecții, {len(q)} trec filtrele, confirmate: {[c.cls for c in conf]}")
        for c in conf:
            events.append(pipe.process(Job(cam, c, img, dt.datetime.now(), main_frame=img)))
    if not events:
        print("Niciun eveniment (nimic n-a trecut filtrele: prag, suprafață, zone).")
    for e in events:
        print(f"EVENIMENT #{e['id']}: „{e['title']}”, poză {e['bytes'] // 1024} KB -> {e['image']}, "
              f"notificare trimisă: {e['notified']}")


def cmd_test_notify(args):
    from . import config as configmod
    from .web import send_test_notification

    s = configmod.load()
    image = None
    if args.image:
        import cv2

        image = cv2.imread(args.image)
    ok = send_test_notification(s, image)
    print(f"Notificare trimisă la {s.ntfy_server}/{s.ntfy_topic}" if ok else "EROARE – vezi logs/animalwatch.log")
    sys.exit(0 if ok else 1)


def cmd_cleanup(args):
    from . import config as configmod
    from .storage import Store

    s = configmod.load()
    days = args.days if args.days is not None else int(s.section("storage")["retention_days"])
    n = Store(s.path(s.section("storage")["events_dir"])).cleanup(days)
    print(f"șterse {n} evenimente mai vechi de {days} zile")


def cmd_perf(args):
    import json

    import requests

    from . import config as configmod

    s = configmod.load()
    w = s.section("web")
    try:
        print(json.dumps(requests.get(f"http://{w['host']}:{w['port']}/api/status", timeout=5).json(),
                         indent=2, ensure_ascii=False))
    except Exception as e:
        sys.exit(f"serviciul nu răspunde: {e}")


def main():
    p = argparse.ArgumentParser(prog="animalwatch")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="pornește serviciul (detecție + web)")
    pr = sub.add_parser("probe", help="testează DVR-ul și salvează snapshot-uri în snapshots_setup/")
    pr.add_argument("--channels", default="1-8")
    pr.add_argument("--update-config", action="store_true")
    st = sub.add_parser("selftest", help="rulează YOLO pe imagini de test")
    st.add_argument("images", nargs="*")
    st.add_argument("--model")
    st.add_argument("--device")
    sm = sub.add_parser("simulate", help="trece o imagine prin tot lanțul (filtre, zone, specie, istoric, ntfy)")
    sm.add_argument("image")
    sm.add_argument("--camera", type=int, default=1)
    sm.add_argument("--no-notify", action="store_true")
    tn = sub.add_parser("test-notify", help="trimite o notificare de probă")
    tn.add_argument("--image")
    sub.add_parser("web", help="doar pagina web (istoric + zone), fără detecție")
    cl = sub.add_parser("cleanup", help="șterge evenimentele vechi")
    cl.add_argument("--days", type=int)
    sub.add_parser("perf", help="arată starea serviciului (CPU, FPS, camere)")
    args = p.parse_args()

    if args.cmd == "run":
        from .app import main as run_main

        run_main()
    elif args.cmd == "probe":
        from .probe import run

        a, _, b = args.channels.partition("-")
        chans = list(range(int(a), int(b or a) + 1))
        run(chans, update_config=args.update_config)
    elif args.cmd == "web":
        from .web import main as web_main

        web_main()
    else:
        from .logutil import setup

        setup("cli")
        {"selftest": cmd_selftest, "simulate": cmd_simulate, "test-notify": cmd_test_notify,
         "cleanup": cmd_cleanup, "perf": cmd_perf}[args.cmd](args)


if __name__ == "__main__":
    main()
