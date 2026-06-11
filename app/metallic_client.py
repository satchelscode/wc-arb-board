"""Fetch Metallic (Steam22) WC schedule JSON."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.config import (
    METALLIC_REFERER,
    METALLIC_SCHEDULE_POST_BODY,
    METALLIC_SCHEDULE_URL,
)
from app.metallic_auth import metallic_access_token

log = logging.getLogger(__name__)


def fetch_metallic_schedule() -> Any | None:
    token = metallic_access_token()
    if not token:
        log.warning("Metallic: no JWT (set METALLIC_USERNAME / METALLIC_PASSWORD)")
        return None
    url = (METALLIC_SCHEDULE_URL or "").strip()
    if not url:
        log.warning("Metallic: METALLIC_SCHEDULE_URL is not set")
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Origin": "https://steam22.com",
        "Referer": (METALLIC_REFERER or "https://steam22.com/v2/").strip(),
    }
    body_raw = (METALLIC_SCHEDULE_POST_BODY or "").strip()
    try:
        if body_raw:
            body = json.loads(body_raw)
            headers["Content-Type"] = "application/json"
            response = requests.post(url, headers=headers, json=body, timeout=35)
        else:
            response = requests.post(url, headers=headers, json={}, timeout=35)
        if response.status_code == 401:
            log.warning("Metallic schedule 401 — check credentials")
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        log.warning("Metallic schedule fetch failed: %s", exc)
        return None
