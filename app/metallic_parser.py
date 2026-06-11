"""Parse Metallic / Steam22 WC schedule JSON into team-total and game-total lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.events import matchup_key
from app.names import display_team_name, team_norm

_ET = ZoneInfo("America/New_York")
_TEAM_TOTAL_MAX_POINT = 2.5
_DATE_IN_TEXT = re.compile(
    r"(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?",
    re.I,
)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass(frozen=True)
class MetallicLine:
    team: str
    opponent: str
    event_date: str
    market: str
    line: float
    over_price: int | None
    under_price: int | None


def _parse_date_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _DATE_IN_TEXT.search(raw)
    if not m:
        return ""
    mon = _MONTHS.get(m.group("mon")[:3].lower())
    if not mon:
        return ""
    try:
        day = int(m.group("day"))
    except ValueError:
        return ""
    year = m.group("year")
    yr = int(year) if year else datetime.now(_ET).year
    return f"{yr:04d}-{mon:02d}-{day:02d}"


def _epoch_to_et_date(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=_ET).date().isoformat()
        except (OSError, ValueError):
            return ""
    if isinstance(value, str):
        if re.fullmatch(r"\d{8}", value.strip()):
            s = value.strip()
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        return _parse_date_text(value)
    return ""


def _american(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None


def _point(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    return None


def _ou_from_cells(cells: list[dict[str, Any]]) -> tuple[float | None, int | None, int | None]:
    """Return (line, over, under) from ls.t / ls.s priced cells."""
    by_point: dict[float, list[int]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        point = _point(cell.get("p"))
        odds = _american(cell.get("o"))
        if point is None or odds is None:
            continue
        by_point.setdefault(point, []).append(odds)
    if not by_point:
        return None, None, None
    # Prefer the lowest priced line on the board (typical WC team total 0.5).
    line = sorted(by_point)[0]
    prices = sorted(by_point[line], reverse=True)
    if len(prices) >= 2:
        return line, prices[0], prices[1]
    if len(prices) == 1:
        return line, prices[0], None
    return None, None, None


def _team_name(node: dict[str, Any]) -> str:
    for key in ("n", "m", "tn"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _maybe_date_from_node(node: dict[str, Any]) -> str:
    for key in ("gd", "dt", "d", "date", "ld", "gmdt"):
        val = node.get(key)
        if val is None:
            continue
        iso = _epoch_to_et_date(val)
        if iso:
            return iso
    for key in ("n", "desc", "description", "ld"):
        val = node.get(key)
        if isinstance(val, str):
            iso = _parse_date_text(val)
            if iso:
                return iso
    return ""


def _iter_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_nodes(child)


def _lines_from_team_row(
    *,
    team: str,
    opponent: str,
    event_date: str,
    ls: dict[str, Any],
) -> list[MetallicLine]:
    if not team:
        return []
    t_cells = ls.get("t") if isinstance(ls.get("t"), list) else []
    cells = [c for c in t_cells if isinstance(c, dict)]
    if not cells:
        return []
    line, over_p, under_p = _ou_from_cells(cells)
    if line is None or (over_p is None and under_p is None):
        return []
    if line > _TEAM_TOTAL_MAX_POINT:
        return []
    return [
        MetallicLine(
            team=display_team_name(team),
            opponent=display_team_name(opponent),
            event_date=event_date,
            market="team_totals",
            line=line,
            over_price=over_p,
            under_price=under_p,
        )
    ]


def _lines_from_game_totals(
    *,
    away: str,
    home: str,
    event_date: str,
    away_ls: dict[str, Any],
    home_ls: dict[str, Any],
) -> list[MetallicLine]:
    away_cells = [c for c in (away_ls.get("t") or []) if isinstance(c, dict)]
    home_cells = [c for c in (home_ls.get("t") or []) if isinstance(c, dict)]
    merged = away_cells + home_cells
    line, over_p, under_p = _ou_from_cells(merged)
    if line is None or line <= _TEAM_TOTAL_MAX_POINT:
        return []
    if over_p is None and under_p is None:
        return []
    label_team = display_team_name(away)
    label_opp = display_team_name(home)
    return [
        MetallicLine(
            team=label_team,
            opponent=label_opp,
            event_date=event_date,
            market="totals",
            line=line,
            over_price=over_p,
            under_price=under_p,
        )
    ]


def extract_wc_lines_from_schedule(payload: Any) -> list[MetallicLine]:
    if not isinstance(payload, (dict, list)):
        return []
    found: dict[tuple[str, str, str, str, float], MetallicLine] = {}
    current_date = ""

    def _add(line: MetallicLine) -> None:
        if not line.event_date or not line.team:
            return
        if line.market == "team_totals":
            key = (
                team_norm(line.team),
                team_norm(line.opponent),
                line.event_date,
                line.market,
                round(line.line, 2),
            )
        else:
            pair = matchup_tuple(line.team, line.opponent)
            key = (pair[0], pair[1], line.event_date, line.market, round(line.line, 2))
        prev = found.get(key)
        if prev is None:
            found[key] = line
            return
        over = prev.over_price
        if line.over_price is not None:
            over = line.over_price if over is None else max(over, line.over_price)
        under = prev.under_price
        if line.under_price is not None:
            under = line.under_price if under is None else max(under, line.under_price)
        found[key] = MetallicLine(
            team=prev.team,
            opponent=prev.opponent,
            event_date=prev.event_date,
            market=prev.market,
            line=prev.line,
            over_price=over,
            under_price=under,
        )

    for node in _iter_nodes(payload):
        maybe_date = _maybe_date_from_node(node)
        if maybe_date:
            current_date = maybe_date

        ts = node.get("ts")
        if isinstance(ts, list) and len(ts) == 2:
            a_row = ts[0] if isinstance(ts[0], dict) else {}
            b_row = ts[1] if isinstance(ts[1], dict) else {}
            away = _team_name(a_row)
            home = _team_name(b_row)
            event_date = _maybe_date_from_node(node) or current_date
            away_ls = a_row.get("ls") if isinstance(a_row.get("ls"), dict) else {}
            home_ls = b_row.get("ls") if isinstance(b_row.get("ls"), dict) else {}
            for line in _lines_from_team_row(
                team=away, opponent=home, event_date=event_date, ls=away_ls
            ):
                _add(line)
            for line in _lines_from_team_row(
                team=home, opponent=away, event_date=event_date, ls=home_ls
            ):
                _add(line)
            for line in _lines_from_game_totals(
                away=away,
                home=home,
                event_date=event_date,
                away_ls=away_ls,
                home_ls=home_ls,
            ):
                _add(line)
            continue

        team = _team_name(node)
        ls = node.get("ls")
        if not team or not isinstance(ls, dict):
            continue
        event_date = _maybe_date_from_node(node) or current_date
        for line in _lines_from_team_row(team=team, opponent="", event_date=event_date, ls=ls):
            _add(line)

    return list(found.values())


def matchup_tuple(a: str, b: str) -> tuple[str, str]:
    return matchup_key(a, b)
