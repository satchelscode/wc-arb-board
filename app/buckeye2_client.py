"""Fetch Buckeye2 WC lines from kraken69.com."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.buckeye2_auth import buckeye2_auth_headers
from app.config import BUCKEYE2_LINES_POST_BODY, BUCKEYE2_LINES_URL

log = logging.getLogger(__name__)


def fetch_buckeye2_lines() -> Any | None:
    headers = buckeye2_auth_headers()
    if headers is None:
        log.warning("Buckeye2: no auth headers (set username/password or extra headers)")
        return None
    url = (BUCKEYE2_LINES_URL or "").strip()
    if not url:
        log.warning("Buckeye2: BUCKEYE2_LINES_URL is not set")
        return None
    body_raw = (BUCKEYE2_LINES_POST_BODY or "").strip()
    try:
        body = json.loads(body_raw) if body_raw else {}
        response = requests.post(url, headers=headers, json=body, timeout=35)
        if response.status_code == 401:
            log.warning("Buckeye2 lines 401 — check credentials")
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        log.warning("Buckeye2 lines fetch failed: %s", exc)
        return None
