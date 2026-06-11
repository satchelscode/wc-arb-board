"""Fetch Buckeye2 WC lines from kraken69.com."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.buckeye2_auth import buckeye2_auth_headers
from app.config import (
    BUCKEYE2_AUTH_USERID,
    BUCKEYE2_LINES_POST_BODY,
    BUCKEYE2_LINES_URL,
    BUCKEYE2_USERNAME,
)

log = logging.getLogger(__name__)


def _lines_request_body() -> dict[str, Any]:
    raw = (BUCKEYE2_LINES_POST_BODY or "").strip()
    if raw and raw not in ("", "{}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            log.warning("BUCKEYE2_LINES_POST_BODY is not valid JSON; using default")
    customer = (BUCKEYE2_AUTH_USERID or BUCKEYE2_USERNAME or "").strip()
    return {
        "customerID": customer,
        "operation": "Get_LeagueLines2",
        "sportType": "SOCCER",
        "sportSubType": "WORLD CUP",
        "office": "PPHINSIDER",
        "wagerType": "Straight",
        "period": "Game",
        "periodNumber": "0",
        "periods": 0,
        "RRO": 1,
        "correlationID": "",
        "hourFilter": 0,
        "keyword": "",
        "placeLateFlag": False,
        "propDescription": "",
        "rotOrder": 0,
    }


def fetch_buckeye2_lines() -> Any | None:
    headers = buckeye2_auth_headers()
    if headers is None:
        log.warning("Buckeye2: no auth headers (set username/password or extra headers)")
        return None
    url = (BUCKEYE2_LINES_URL or "").strip()
    if not url:
        log.warning("Buckeye2: BUCKEYE2_LINES_URL is not set")
        return None
    try:
        response = requests.post(
            url, headers=headers, json=_lines_request_body(), timeout=35
        )
        if response.status_code == 401:
            log.warning("Buckeye2 lines 401 — check credentials")
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        log.warning("Buckeye2 lines fetch failed: %s", exc)
        return None
