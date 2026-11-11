"""ntfy.sh notifications with the snapshot as attachment."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("animalwatch.notify")


def send(server: str, topic: str, title: str, message: str, image: bytes | None = None,
         filename: str = "snapshot.jpg", tags: list[str] | None = None, priority: int = 4,
         token: str = "", timeout: float = 30) -> bool:
    if not topic:
        log.error("NTFY_TOPIC is empty, notification not sent")
        return False
    url = f"{server.rstrip('/')}/{topic}"
    # Title/Message go as query params: HTTP headers can't carry UTF-8 (ă, î, ș...) reliably.
    params = {"title": title, "priority": str(priority)}
    if tags:
        params["tags"] = ",".join(tags)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        if image is not None:
            params["message"] = message
            headers["Filename"] = filename
            r = requests.put(url, data=image, params=params, headers=headers, timeout=timeout)
        else:
            r = requests.post(url, data=message.encode("utf-8"), params=params, headers=headers, timeout=timeout)
        if r.status_code >= 300:
            log.error("ntfy error %s: %s", r.status_code, r.text[:300])
            return False
        return True
    except requests.RequestException as e:
        log.error("ntfy request failed: %s", e)
        return False
