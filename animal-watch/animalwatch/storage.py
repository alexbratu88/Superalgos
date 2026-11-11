"""Event history: JPEGs in events/YYYY-MM-DD/ and rows in events/events.db (SQLite)."""
from __future__ import annotations

import datetime as dt
import logging
import shutil
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger("animalwatch.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,              -- local time, ISO 8601
    camera INTEGER NOT NULL,
    camera_name TEXT NOT NULL,
    cls TEXT NOT NULL,             -- COCO class
    confidence REAL NOT NULL,
    species TEXT,                  -- from the local vision model, if any
    image TEXT,                    -- path relative to events dir
    notified INTEGER NOT NULL DEFAULT 0,
    box TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


class Store:
    def __init__(self, events_dir: Path):
        self.dir = events_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "events.db"
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def image_path(self, when: dt.datetime, camera: int, cls: str) -> tuple[Path, str]:
        rel = f"{when:%Y-%m-%d}/{when:%H%M%S}_cam{camera}_{cls}_{when:%f}.jpg"
        full = self.dir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        return full, rel

    def add(self, when: dt.datetime, camera: int, camera_name: str, cls: str, conf: float,
            species: str | None, image_rel: str | None, notified: bool, box: list | None) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO events (ts, camera, camera_name, cls, confidence, species, image, notified, box)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (when.isoformat(timespec="seconds"), camera, camera_name, cls, round(conf, 3), species,
                 image_rel, int(notified), ",".join(f"{v:.4f}" for v in box) if box else None),
            )
            return int(cur.lastrowid)

    def set_notified(self, event_id: int, notified: bool):
        with self._lock, self._conn() as c:
            c.execute("UPDATE events SET notified=? WHERE id=?", (int(notified), event_id))

    def query(self, camera: int | None = None, animal: str | None = None, day: str | None = None,
              limit: int = 200, offset: int = 0) -> list[dict]:
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if camera is not None:
            sql += " AND camera=?"
            args.append(camera)
        if animal:
            sql += " AND (cls=? OR lower(species) LIKE ?)"
            args += [animal, f"%{animal.lower()}%"]
        if day:
            sql += " AND ts LIKE ?"
            args.append(f"{day}%")
        sql += " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def facets(self) -> dict:
        with self._conn() as c:
            cams = [dict(r) for r in c.execute(
                "SELECT camera, max(camera_name) AS name, count(*) AS n FROM events GROUP BY camera ORDER BY camera")]
            classes = [dict(r) for r in c.execute(
                "SELECT cls, count(*) AS n FROM events GROUP BY cls ORDER BY n DESC")]
            species = [dict(r) for r in c.execute(
                "SELECT species, count(*) AS n FROM events WHERE species IS NOT NULL AND species != ''"
                " GROUP BY species ORDER BY n DESC")]
            total = c.execute("SELECT count(*) FROM events").fetchone()[0]
        return {"cameras": cams, "classes": classes, "species": species, "total": total}

    def cleanup(self, retention_days: int) -> int:
        cutoff = dt.datetime.now() - dt.timedelta(days=retention_days)
        with self._lock, self._conn() as c:
            n = c.execute("DELETE FROM events WHERE ts < ?", (cutoff.isoformat(timespec="seconds"),)).rowcount
        removed_dirs = 0
        for d in self.dir.iterdir():
            if d.is_dir():
                try:
                    day = dt.datetime.strptime(d.name, "%Y-%m-%d")
                except ValueError:
                    continue
                if day.date() < cutoff.date():
                    shutil.rmtree(d, ignore_errors=True)
                    removed_dirs += 1
        if n or removed_dirs:
            log.info("cleanup: removed %d events, %d day folders older than %d days", n, removed_dirs, retention_days)
        return n
