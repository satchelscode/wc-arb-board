"""Fetch Metallic (Steam22) WC schedule JSON."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from app.config import (
    METALLIC_REFERER,
    METALLIC_SCHEDULE_POST_BODY,
    METALLIC_SCHEDULE_URL,
)
from app.metallic_auth import metallic_access_token

log = logging.getLogger(__name__)

_WC_RE = re.compile(r"world\s*cup|fifa", re.I)
_LEGACY_BODY_KEYS = frozenset({"languageID", "lineType", "id"})
# Steam22 FIFA World Cup 2026 — spid from schedule response (see DevTools schedules/S/0).
_DEFAULT_WC_SCHEDULE_REQUESTS: list[dict[str, int]] = [
    {"IdSport": 232, "Period": 0},  # FIFA - World Cup (spread/ML/total/team total)
]


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://steam22.com",
        "Referer": (METALLIC_REFERER or "https://steam22.com/v2/").strip(),
    }


def _is_legacy_body(body: Any) -> bool:
    return isinstance(body, dict) and bool(_LEGACY_BODY_KEYS & set(body.keys()))


def _sport_request(node: dict[str, Any]) -> dict[str, int] | None:
    id_sport = node.get("IdSportType")
    if id_sport is None:
        id_sport = node.get("IdSport")
    if id_sport is None:
        id_sport = node.get("spid")
    if id_sport is None:
        id_sport = node.get("Id")
    if id_sport is None:
        return None
    period = node.get("PeriodNumber")
    if period is None:
        period = node.get("Period")
    if period is None:
        period = node.get("p", 0)
    try:
        return {"IdSport": int(id_sport), "Period": int(period)}
    except (TypeError, ValueError):
        return None


def _node_text(node: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("Description", "Name", "Label", "l", "n", "desc", "Sport", "SubSport", "sb"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return " ".join(parts)


def _collect_sport_requests(
    payload: Any,
    *,
    wc_only: bool,
) -> list[dict[str, int]]:
    found: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()

    def _add(node: dict[str, Any], *, force: bool = False) -> None:
        if not force and wc_only and not _WC_RE.search(_node_text(node)):
            return
        req = _sport_request(node)
        if req is None:
            return
        key = (req["IdSport"], req["Period"])
        if key in seen:
            return
        seen.add(key)
        found.append(req)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            _add(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return found


def _sports_menu_urls(schedule_url: str) -> list[str]:
    """Derive sports-menu URLs from the schedule endpoint (keep /S/0 suffix when present)."""
    base = schedule_url.strip()
    if not base:
        return [
            "https://steam22.com/player-api/api/wager/sportsavailablebyplayeronleague/S/0",
            "https://steam22.com/player-api/api/wager/sportsavailablebyplayeronleague/",
        ]
    urls: list[str] = []
    for pattern, repl in (
        (r"wager/schedules/([^/]+/0)\s*$", r"wager/sportsavailablebyplayeronleague/\1"),
        (r"wager/schedules/[^/]+/0\s*$", "wager/sportsavailablebyplayeronleague/"),
    ):
        candidate = re.sub(pattern, repl, base)
        if candidate not in urls:
            urls.append(candidate)
    for fallback in (
        "https://steam22.com/player-api/api/wager/sportsavailablebyplayeronleague/S/0",
        "https://steam22.com/player-api/api/wager/sportsavailablebyplayeronleague/",
    ):
        if fallback not in urls:
            urls.append(fallback)
    return urls


def _fetch_sports_menu(token: str) -> Any | None:
    schedule_url = (METALLIC_SCHEDULE_URL or "").strip()
    headers = _auth_headers(token)
    last_error: str | None = None
    for menu_url in _sports_menu_urls(schedule_url):
        for method, body in (("GET", None), ("POST", {}), ("POST", [])):
            try:
                if method == "GET":
                    response = requests.get(menu_url, headers=headers, timeout=35)
                else:
                    response = requests.post(
                        menu_url, headers=headers, json=body, timeout=35
                    )
                if response.status_code == 401:
                    log.warning("Metallic sports menu 401 — check credentials")
                    return None
                if response.status_code == 404:
                    last_error = f"404 for {method} {menu_url}"
                    continue
                response.raise_for_status()
                payload = response.json()
                log.info("Metallic sports menu ok (%s %s)", method, menu_url)
                return payload
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                last_error = str(exc)
    log.warning("Metallic sports menu fetch failed: %s", last_error or "no candidates")
    return None


def _schedule_post_bodies(token: str) -> list[Any]:
    raw = (METALLIC_SCHEDULE_POST_BODY or "").strip()
    if raw and raw not in ("", "{}"):
        try:
            parsed = json.loads(raw)
            if not _is_legacy_body(parsed):
                return [parsed]
        except json.JSONDecodeError:
            log.warning("METALLIC_SCHEDULE_POST_BODY is not valid JSON; using auto-discovery")

    menu = _fetch_sports_menu(token)
    if menu is not None:
        wc = _collect_sport_requests(menu, wc_only=True)
        if wc:
            log.info("Metallic: discovered %s WC sport id(s) from menu", len(wc))
            return [wc]
        soccer = _collect_sport_requests(menu, wc_only=False)
        soccer = [s for s in soccer if s]  # noqa: C416 — explicit copy
        if soccer:
            log.info("Metallic: using %s sport id(s) from menu (no FIFA/WC label match)", len(soccer))
            return [soccer[:12]]

    # Last resort: legacy body if user left it in env, else known WC spid defaults.
    if raw and raw not in ("", "{}"):
        try:
            return [json.loads(raw)]
        except json.JSONDecodeError:
            pass
    log.info(
        "Metallic: using default WC schedule body IdSport=%s",
        _DEFAULT_WC_SCHEDULE_REQUESTS[0]["IdSport"],
    )
    return [_DEFAULT_WC_SCHEDULE_REQUESTS]


def _post_schedule(token: str, body: Any) -> Any | None:
    url = (METALLIC_SCHEDULE_URL or "").strip()
    if not url:
        log.warning("Metallic: METALLIC_SCHEDULE_URL is not set")
        return None
    try:
        response = requests.post(
            url, headers=_auth_headers(token), json=body, timeout=35
        )
        if response.status_code == 401:
            log.warning("Metallic schedule 401 — check credentials")
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        log.warning("Metallic schedule fetch failed: %s", exc)
        return None


def _payload_stats(payload: Any) -> str:
    if isinstance(payload, list):
        games = 0
        team_rows = 0
        tt_cells = 0
        for root in payload:
            if not isinstance(root, dict):
                continue
            sc = root.get("sc")
            if not isinstance(sc, dict):
                continue
            for schl in sc.get("schl") or []:
                if not isinstance(schl, dict):
                    continue
                for game in schl.get("g") or []:
                    if not isinstance(game, dict):
                        continue
                    games += 1
                    for team in game.get("ts") or []:
                        if not isinstance(team, dict):
                            continue
                        team_rows += 1
                        ls = team.get("ls")
                        if isinstance(ls, dict):
                            tt_cells += len(ls.get("to") or []) + len(ls.get("tu") or [])
        return f"roots={len(payload)} games={games} team_rows={team_rows} tt_cells={tt_cells}"
    if isinstance(payload, dict):
        return f"dict_keys={list(payload.keys())[:8]}"
    return f"type={type(payload).__name__}"


def fetch_metallic_schedule() -> Any | None:
    token = metallic_access_token()
    if not token:
        log.warning("Metallic: no JWT (set METALLIC_USERNAME / METALLIC_PASSWORD)")
        return None

    best: Any | None = None
    best_score = -1
    for body in _schedule_post_bodies(token):
        payload = _post_schedule(token, body)
        if payload is None:
            continue
        stats = _payload_stats(payload)
        score = 0
        if "tt_cells=" in stats:
            score = int(stats.split("tt_cells=")[-1])
        if score > best_score:
            best = payload
            best_score = score
        if score > 0:
            log.debug("Metallic schedule ok (%s)", stats)
            return payload

    if best is not None:
        log.info("Metallic schedule fetched (%s)", _payload_stats(best))
        return best
    return None
