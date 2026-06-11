"""Parse ACE NewScheduleHelper JSON for World Cup team totals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

_TEAM_TOTAL_SUFFIX = re.compile(r"\s*\(TEAM TOTAL\)\s*$", re.I)


@dataclass(frozen=True)
class TeamTotalLine:
    team: str
    event_date: str
    line: float
    over_price: int | None
    under_price: int | None


def _first_str(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _first_int(row: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        val = row.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return int(val)
        if isinstance(val, str):
            s = val.strip()
            if re.fullmatch(r"[+-]?\d+", s):
                return int(s)
            m = re.search(r"([+-]\d{2,4})\b", s)
            if m:
                return int(m.group(1))
    return None


def _line_from_row(row: dict[str, Any]) -> float | None:
    for key in ("unt", "ovt"):
        val = row.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return abs(float(val))
        if isinstance(val, str):
            try:
                return abs(float(val.strip()))
            except ValueError:
                continue
    for key in ("ovh", "unh"):
        text = _first_str(row, key)
        if not text:
            continue
        m = re.search(r"(\d+)(?:\s*&frac12;|½|\.5)?", text, re.I)
        if m:
            base = float(m.group(1))
            if "&frac12;" in text or "½" in text:
                base += 0.5
            return base
    return None


def _ou_prices(row: dict[str, Any]) -> tuple[int | None, int | None]:
    over = _first_int(row, "ovoddst", "OverOdds", "hoddsh")
    under = _first_int(row, "unoddst", "UnderOdds", "hoddst")
    return over, under


def _is_priced_ou_row(row: dict[str, Any]) -> bool:
    if row.get("EmptyGame"):
        return False
    if _first_str(row, "ovh", "unh"):
        return True
    if row.get("unt") not in (None, "") or row.get("ovt") not in (None, ""):
        return True
    return _first_int(row, "ovoddst") is not None or _first_int(row, "unoddst") is not None


def _gmdt_to_iso(gmdt: str) -> str:
    s = (gmdt or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return ""


def _strip_team_label(name: str) -> str:
    return _TEAM_TOTAL_SUFFIX.sub("", (name or "").strip()).strip()


def _iter_json_nodes(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_nodes(child)


def _line_from_game(game: dict[str, Any]) -> TeamTotalLine | None:
    label = _first_str(game, "htm", "vtm", "gdesc")
    if "(TEAM TOTAL)" not in label.upper():
        return None
    glines = game.get("GameLines")
    if not isinstance(glines, list) or not glines:
        return None
    row = glines[0] if isinstance(glines[0], dict) else {}
    if not _is_priced_ou_row(row):
        return None
    line_pt = _line_from_row(row)
    over_p, under_p = _ou_prices(row)
    if line_pt is None or (over_p is None and under_p is None):
        return None
    team = _strip_team_label(_first_str(game, "htm", "vtm"))
    if not team:
        return None
    return TeamTotalLine(
        team=team,
        event_date=_gmdt_to_iso(_first_str(game, "gmdt")),
        line=line_pt,
        over_price=over_p,
        under_price=under_p,
    )


def extract_team_totals_from_helper(
    html: str,
    *,
    wc_lg: str = "3749",
) -> list[TeamTotalLine]:
    try:
        payload = json.loads(html)
    except json.JSONDecodeError:
        return []
    found: list[TeamTotalLine] = []
    seen: set[tuple[str, str, float]] = set()
    for node in _iter_json_nodes(payload):
        if not isinstance(node, dict):
            continue
        desc = node.get("Description")
        if isinstance(desc, str) and desc and "team total" not in desc.lower():
            continue
        games = node.get("Games")
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            line = _line_from_game(game)
            if not line:
                continue
            key = (line.team.upper(), line.event_date, round(line.line, 2))
            if key in seen:
                continue
            seen.add(key)
            found.append(line)
    return found
