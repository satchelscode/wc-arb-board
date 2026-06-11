from datetime import datetime, timezone
from typing import Any

import requests

from app.config import ODDS_API_BASE, ODDS_API_KEY


def fetch_events_for_sport(sport_key: str) -> list[dict[str, Any]]:
    if not ODDS_API_KEY:
        return []
    url = f"{ODDS_API_BASE}/sports/{sport_key}/events"
    params = {"apiKey": ODDS_API_KEY, "dateFormat": "iso"}
    try:
        response = requests.get(url, params=params, timeout=20)
        if response.status_code in (401, 404, 422):
            return []
        response.raise_for_status()
        events = response.json()
    except requests.RequestException:
        return []
    upcoming: list[dict[str, Any]] = []
    for event in events:
        commence_raw = event.get("commence_time", "")
        try:
            commence_dt = datetime.fromisoformat(str(commence_raw).replace("Z", "+00:00"))
            if commence_dt < datetime.now(timezone.utc):
                continue
        except ValueError:
            pass
        upcoming.append(event)
    return upcoming
