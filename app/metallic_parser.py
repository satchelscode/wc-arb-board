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


def _cell_point_odds(cell: dict[str, Any]) -> tuple[float | None, int | None]:
    point = _point(cell.get("p"))
    if point is None:
        point = _point(cell.get("Points"))
    odds = _american(cell.get("o"))
    if odds is None:
        odds = _american(cell.get("Odds"))
    return point, odds


def _ou_from_cells(cells: list[dict[str, Any]]) -> tuple[float | None, int | None, int | None]:
    """Return (line, over, under) from game-total cells (ls.t)."""
    by_point: dict[float, list[int]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        point, odds = _cell_point_odds(cell)
        if point is None or odds is None:
            continue
        by_point.setdefault(point, []).append(odds)
    if not by_point:
        return None, None, None
    line = sorted(by_point)[0]
    prices = sorted(by_point[line], reverse=True)
    if len(prices) >= 2:
        return line, prices[0], prices[1]
    if len(prices) == 1:
        return line, prices[0], None
    return None, None, None


def _team_totals_from_ls(ls: dict[str, Any]) -> list[tuple[float, int | None, int | None]]:
    """Steam22 team totals use ls.to (over) and ls.tu (under), not ls.t."""
    over_by_point: dict[float, int] = {}
    under_by_point: dict[float, int] = {}
    for cell in ls.get("to") or []:
        if not isinstance(cell, dict):
            continue
        point, odds = _cell_point_odds(cell)
        if point is not None and odds is not None:
            over_by_point[point] = odds
    for cell in ls.get("tu") or []:
        if not isinstance(cell, dict):
            continue
        point, odds = _cell_point_odds(cell)
        if point is not None and odds is not None:
            under_by_point[point] = odds
    lines: list[tuple[float, int | None, int | None]] = []
    for point in sorted(set(over_by_point) | set(under_by_point)):
        if point > _TEAM_TOTAL_MAX_POINT:
            continue
        over_p = over_by_point.get(point)
        under_p = under_by_point.get(point)
        if over_p is None and under_p is None:
            continue
        lines.append((point, over_p, under_p))
    return lines


def _team_totals_from_lines_obj(lines: dict[str, Any]) -> list[tuple[float, int | None, int | None]]:
    over_by_point: dict[float, int] = {}
    under_by_point: dict[float, int] = {}
    for cell in lines.get("TeamTotalsOver") or []:
        if not isinstance(cell, dict):
            continue
        point, odds = _cell_point_odds(cell)
        if point is not None and odds is not None:
            over_by_point[point] = odds
    for cell in lines.get("TeamTotalsUnder") or []:
        if not isinstance(cell, dict):
            continue
        point, odds = _cell_point_odds(cell)
        if point is not None and odds is not None:
            under_by_point[point] = odds
    out: list[tuple[float, int | None, int | None]] = []
    for point in sorted(set(over_by_point) | set(under_by_point)):
        if point > _TEAM_TOTAL_MAX_POINT:
            continue
        over_p = over_by_point.get(point)
        under_p = under_by_point.get(point)
        if over_p is None and under_p is None:
            continue
        out.append((point, over_p, under_p))
    return out


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
    out: list[MetallicLine] = []
    for line, over_p, under_p in _team_totals_from_ls(ls):
        out.append(
            MetallicLine(
                team=display_team_name(team),
                opponent=display_team_name(opponent),
                event_date=event_date,
                market="team_totals",
                line=line,
                over_price=over_p,
                under_price=under_p,
            )
        )
    return out


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


def _roots_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _lines_from_schedule_tree(payload: Any) -> list[MetallicLine]:
    """Parse Steam22 schedule array: [{sc: {schl: [{d, g: [{t, ts: [{n, ls}]}]}]}}]."""
    out: list[MetallicLine] = []
    for root in _roots_from_payload(payload):
        sc = root.get("sc")
        if not isinstance(sc, dict):
            continue
        for schl in sc.get("schl") or []:
            if not isinstance(schl, dict):
                continue
            block_date = _epoch_to_et_date(schl.get("d")) or _parse_date_text(
                str(schl.get("l") or "")
            )
            for game in schl.get("g") or []:
                if not isinstance(game, dict):
                    continue
                game_date = _epoch_to_et_date(game.get("t")) or block_date
                teams = [t for t in (game.get("ts") or []) if isinstance(t, dict)]
                names = [_team_name(t) for t in teams]
                for idx, team_row in enumerate(teams):
                    team = _team_name(team_row)
                    if not team:
                        continue
                    others = [n for j, n in enumerate(names) if j != idx and n]
                    opponent = others[0] if len(others) == 1 else ""
                    if len(others) >= 2:
                        opponent = others[1] if idx == 0 else others[0]
                    ls = team_row.get("ls")
                    if not isinstance(ls, dict):
                        continue
                    for line in _lines_from_team_row(
                        team=team,
                        opponent=opponent,
                        event_date=game_date,
                        ls=ls,
                    ):
                        out.append(line)
                if len(teams) == 2:
                    away_ls = teams[0].get("ls") if isinstance(teams[0].get("ls"), dict) else {}
                    home_ls = teams[1].get("ls") if isinstance(teams[1].get("ls"), dict) else {}
                    out.extend(
                        _lines_from_game_totals(
                            away=names[0],
                            home=names[1],
                            event_date=game_date,
                            away_ls=away_ls,
                            home_ls=home_ls,
                        )
                    )
    return out


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

    tree_lines = _lines_from_schedule_tree(payload)
    for line in tree_lines:
        _add(line)

    if tree_lines:
        return list(found.values())

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
        if team and isinstance(ls, dict):
            event_date = _maybe_date_from_node(node) or current_date
            for line in _lines_from_team_row(
                team=team, opponent="", event_date=event_date, ls=ls
            ):
                _add(line)
            continue

        lines_obj = node.get("Lines")
        if isinstance(lines_obj, dict):
            team = _team_name(node)
            if not team:
                continue
            event_date = _maybe_date_from_node(node) or current_date
            opponent = ""
            for point, over_p, under_p in _team_totals_from_lines_obj(lines_obj):
                _add(
                    MetallicLine(
                        team=display_team_name(team),
                        opponent=display_team_name(opponent),
                        event_date=event_date,
                        market="team_totals",
                        line=point,
                        over_price=over_p,
                        under_price=under_p,
                    )
                )

    return list(found.values())


def matchup_tuple(a: str, b: str) -> tuple[str, str]:
    return matchup_key(a, b)
