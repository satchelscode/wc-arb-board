"""Parse Metallic / Steam22 WC schedule JSON into all offered markets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.events import matchup_key, matchup_label
from app.names import display_team_name, strip_team_total_suffix, team_norm

_ET = ZoneInfo("America/New_York")
_DATE_IN_TEXT = re.compile(
    r"(?P<mon>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?",
    re.I,
)
_VS_RE = re.compile(r"\s+vs\s+", re.I)
_ROUND_PREFIX = re.compile(r"^Round\s+\d+\s*-\s*", re.I)
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
class MetallicOffer:
    event_date: str
    event_label: str
    fixture_label: str
    category: str
    market: str
    participant: str
    opponent: str
    line: float
    side: str
    american: int
    prop_detail: str = ""


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
        s = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s[:10]):
            return s[:10]
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        if re.fullmatch(r"\d{8}", s):
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


def _side_from_bet_id(cell: dict[str, Any]) -> str | None:
    bet_id = str(cell.get("i") or "")
    prefix = bet_id.split("_", 1)[0] if bet_id else ""
    # Steam22 game totals in ls.t: 4 = over, 5 = under.
    if prefix == "4":
        return "over"
    if prefix == "5":
        return "under"
    return None


def _team_total_side_from_bet_id(cell: dict[str, Any]) -> str | None:
    bet_id = str(cell.get("i") or "")
    prefix = bet_id.split("_", 1)[0] if bet_id else ""
    # Steam22 team totals in ls.t fallback: 6/7 = over, 8/9 = under (never 4/5).
    if prefix in ("6", "7"):
        return "over"
    if prefix in ("8", "9"):
        return "under"
    return None


def _ou_pairs_from_cells(
    cells: list[dict[str, Any]],
) -> list[tuple[float, int | None, int | None]]:
    overs: dict[float, int] = {}
    unders: dict[float, int] = {}
    unpaired: dict[float, list[int]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        point, odds = _cell_point_odds(cell)
        if point is None or odds is None:
            continue
        side = _side_from_bet_id(cell)
        if side == "over":
            overs[point] = odds
        elif side == "under":
            unders[point] = odds
        else:
            unpaired.setdefault(point, []).append(odds)

    points = sorted(set(overs) | set(unders) | set(unpaired))
    out: list[tuple[float, int | None, int | None]] = []
    for point in points:
        over_p = overs.get(point)
        under_p = unders.get(point)
        if over_p is None or under_p is None:
            prices = sorted(unpaired.get(point, []), reverse=True)
            if over_p is None and prices:
                over_p = prices[0]
            if under_p is None and len(prices) >= 2:
                under_p = prices[-1]
            elif under_p is None and len(prices) == 1 and over_p != prices[0]:
                under_p = prices[0]
        if over_p is None and under_p is None:
            continue
        out.append((point, over_p, under_p))
    return out


def _team_totals_from_ls(ls: dict[str, Any]) -> list[tuple[float, int | None, int | None]]:
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
    if not over_by_point and not under_by_point:
        for cell in ls.get("t") or []:
            if not isinstance(cell, dict):
                continue
            side = _team_total_side_from_bet_id(cell)
            if side not in ("over", "under"):
                continue
            point, odds = _cell_point_odds(cell)
            if point is None or odds is None:
                continue
            if side == "over":
                over_by_point[point] = odds
            else:
                under_by_point[point] = odds
    lines: list[tuple[float, int | None, int | None]] = []
    for point in sorted(set(over_by_point) | set(under_by_point)):
        over_p = over_by_point.get(point)
        under_p = under_by_point.get(point)
        if over_p is None and under_p is None:
            continue
        lines.append((point, over_p, under_p))
    return lines


def _team_name(node: dict[str, Any]) -> str:
    for key in ("n", "m", "tn"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return strip_team_total_suffix(val.strip())
    return ""


def _category_from_sc(sc: dict[str, Any]) -> str:
    spid = sc.get("spid")
    period = sc.get("p", 0)
    league = str(sc.get("l") or "").lower()
    ps = str(sc.get("ps") or "").upper()
    pd = str(sc.get("pd") or "").lower()
    if spid == 396 or "futures" in league:
        return "futures"
    if spid == 231 or "props" in league:
        return "props"
    if spid == 232 and (period == 1 or ps == "1H" or "1st half" in pd):
        return "1h"
    return "game"


def _period_prefix(category: str) -> str:
    if category == "1h":
        return "[1H] "
    if category == "props":
        return "[Props] "
    if category == "futures":
        return "[Futures] "
    return ""


def _split_game_name(name: str) -> tuple[str, str, str]:
    raw = _ROUND_PREFIX.sub("", (name or "").strip())
    if " - " in raw:
        head, tail = raw.split(" - ", 1)
        if _VS_RE.search(head):
            parts = _VS_RE.split(head, maxsplit=1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip(), tail.strip()
    if _VS_RE.search(raw):
        parts = _VS_RE.split(raw, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip(), ""
    return "", "", raw


def _fixture_label(team_a: str, team_b: str, fallback: str) -> str:
    if team_a and team_b:
        return matchup_label(team_a, team_b)
    return fallback


def _game_kind(category: str, game_name: str, teams: list[dict[str, Any]]) -> str:
    if category == "futures":
        return "futures"
    if category == "props":
        lower = game_name.lower()
        if any(
            k in lower
            for k in (
                "first goalscorer",
                "correct score",
                "halftime and full",
                "ht/ft",
                "ht ft",
            )
        ):
            return "prop_ml"
        return "prop_ou"
    for row in teams:
        ls = row.get("ls")
        if not isinstance(ls, dict):
            continue
        if ls.get("s") or ls.get("to") or ls.get("tu"):
            return "matchup"
    if _VS_RE.search(game_name) or _ROUND_PREFIX.search(game_name or ""):
        return "matchup"
    return "prop_ml"


def _append_ou_offers(
    out: list[MetallicOffer],
    *,
    event_date: str,
    event_label: str,
    fixture_label: str,
    category: str,
    market: str,
    participant: str,
    opponent: str,
    pairs: list[tuple[float, int | None, int | None]],
    prop_detail: str = "",
) -> None:
    for point, over_p, under_p in pairs:
        if over_p is not None:
            out.append(
                MetallicOffer(
                    event_date=event_date,
                    event_label=event_label,
                    fixture_label=fixture_label,
                    category=category,
                    market=market,
                    participant=participant,
                    opponent=opponent,
                    line=point,
                    side="over",
                    american=over_p,
                    prop_detail=prop_detail,
                )
            )
        if under_p is not None:
            out.append(
                MetallicOffer(
                    event_date=event_date,
                    event_label=event_label,
                    fixture_label=fixture_label,
                    category=category,
                    market=market,
                    participant=participant,
                    opponent=opponent,
                    line=point,
                    side="under",
                    american=under_p,
                    prop_detail=prop_detail,
                )
            )


def _lines_from_matchup(
    *,
    game_name: str,
    teams: list[dict[str, Any]],
    event_date: str,
    category: str,
) -> list[MetallicOffer]:
    team_a, team_b, _prop = _split_game_name(game_name)
    fixture = _fixture_label(team_a, team_b, game_name)
    prefix = _period_prefix(category)
    event_label = f"{prefix}{fixture}" if fixture else f"{prefix}{game_name}"
    out: list[MetallicOffer] = []

    names = [_team_name(t) for t in teams]
    draw_idx = next(
        (i for i, n in enumerate(names) if n.lower() == "draw"),
        None,
    )
    matchup_rows: list[tuple[int, str, str, dict[str, Any]]] = []
    for idx, row in enumerate(teams):
        name = names[idx]
        if not name:
            continue
        if draw_idx is not None and idx == draw_idx:
            opponent = ""
        elif team_a and team_b:
            opponent = team_b if team_norm(name) == team_norm(team_a) else team_a
        elif len(names) == 2:
            opponent = names[1 - idx]
        else:
            others = [n for j, n in enumerate(names) if j != idx and n and n.lower() != "draw"]
            opponent = others[0] if others else ""
        ls = row.get("ls")
        if not isinstance(ls, dict):
            continue
        matchup_rows.append((idx, name, opponent, ls))

    for _idx, team, opponent, ls in matchup_rows:
        if team.lower() == "draw":
            for cell in ls.get("m") or []:
                if not isinstance(cell, dict):
                    continue
                _, odds = _cell_point_odds(cell)
                if odds is None:
                    continue
                out.append(
                    MetallicOffer(
                        event_date=event_date,
                        event_label=event_label,
                        fixture_label=fixture,
                        category=category,
                        market="h2h",
                        participant="Draw",
                        opponent="",
                        line=0.0,
                        side="ml",
                        american=odds,
                    )
                )
            continue

        for cell in ls.get("s") or []:
            if not isinstance(cell, dict):
                continue
            point, odds = _cell_point_odds(cell)
            if odds is None:
                continue
            out.append(
                MetallicOffer(
                    event_date=event_date,
                    event_label=event_label,
                    fixture_label=fixture,
                    category=category,
                    market="spreads",
                    participant=display_team_name(team),
                    opponent=display_team_name(opponent),
                    line=point or 0.0,
                    side="spread",
                    american=odds,
                )
            )

        for cell in ls.get("m") or []:
            if not isinstance(cell, dict):
                continue
            _, odds = _cell_point_odds(cell)
            if odds is None:
                continue
            out.append(
                MetallicOffer(
                    event_date=event_date,
                    event_label=event_label,
                    fixture_label=fixture,
                    category=category,
                    market="h2h",
                    participant=display_team_name(team),
                    opponent=display_team_name(opponent),
                    line=0.0,
                    side="ml",
                    american=odds,
                )
            )

        _append_ou_offers(
            out,
            event_date=event_date,
            event_label=event_label,
            fixture_label=fixture,
            category=category,
            market="team_totals",
            participant=display_team_name(team),
            opponent=display_team_name(opponent),
            pairs=_team_totals_from_ls(ls),
        )

    non_draw = [
        (names[i], teams[i].get("ls"))
        for i in range(len(teams))
        if i != draw_idx and isinstance(teams[i].get("ls"), dict)
    ]
    if len(non_draw) >= 2:
        cells: list[dict[str, Any]] = []
        for _name, ls_obj in non_draw[:2]:
            cells.extend(c for c in (ls_obj.get("t") or []) if isinstance(c, dict))
        _append_ou_offers(
            out,
            event_date=event_date,
            event_label=event_label,
            fixture_label=fixture,
            category=category,
            market="totals",
            participant="game",
            opponent="",
            pairs=_ou_pairs_from_cells(cells),
        )

    return out


def _lines_from_prop_ou(
    *,
    game_name: str,
    teams: list[dict[str, Any]],
    event_date: str,
    category: str,
) -> list[MetallicOffer]:
    team_a, team_b, prop = _split_game_name(game_name)
    fixture = _fixture_label(team_a, team_b, game_name)
    prefix = _period_prefix(category)
    prop_detail = prop or game_name
    event_label = f"{prefix}{game_name}"
    out: list[MetallicOffer] = []

    for row in teams:
        name = _team_name(row)
        ls = row.get("ls")
        if not isinstance(ls, dict):
            continue
        cells = [c for c in (ls.get("t") or []) if isinstance(c, dict)]
        if not cells:
            continue
        participant = display_team_name(name) if name else prop_detail
        _append_ou_offers(
            out,
            event_date=event_date,
            event_label=event_label,
            fixture_label=fixture,
            category=category,
            market="props",
            participant=participant,
            opponent="",
            pairs=_ou_pairs_from_cells(cells),
            prop_detail=prop_detail,
        )
    return out


def _lines_from_prop_ml(
    *,
    game_name: str,
    teams: list[dict[str, Any]],
    event_date: str,
    category: str,
    market: str,
) -> list[MetallicOffer]:
    team_a, team_b, prop = _split_game_name(game_name)
    fixture = _fixture_label(team_a, team_b, game_name)
    prefix = _period_prefix(category)
    prop_detail = prop or game_name
    event_label = f"{prefix}{game_name}"
    out: list[MetallicOffer] = []

    for row in teams:
        name = _team_name(row)
        if not name:
            continue
        ls = row.get("ls")
        if not isinstance(ls, dict):
            continue
        for cell in ls.get("m") or []:
            if not isinstance(cell, dict):
                continue
            _, odds = _cell_point_odds(cell)
            if odds is None:
                continue
            out.append(
                MetallicOffer(
                    event_date=event_date,
                    event_label=event_label,
                    fixture_label=fixture,
                    category=category,
                    market=market,
                    participant=display_team_name(name),
                    opponent="",
                    line=0.0,
                    side="ml",
                    american=odds,
                    prop_detail=prop_detail,
                )
            )
    return out


def _roots_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _lines_from_schedule_tree(payload: Any) -> list[MetallicOffer]:
    out: list[MetallicOffer] = []
    for root in _roots_from_payload(payload):
        sc = root.get("sc")
        if not isinstance(sc, dict):
            continue
        category = _category_from_sc(sc)
        for schl in sc.get("schl") or []:
            if not isinstance(schl, dict):
                continue
            block_date = _epoch_to_et_date(schl.get("d")) or _parse_date_text(
                str(schl.get("l") or "")
            )
            for game in schl.get("g") or []:
                if not isinstance(game, dict):
                    continue
                game_date = block_date or _epoch_to_et_date(game.get("t"))
                game_name = str(game.get("n") or "").strip()
                teams = [t for t in (game.get("ts") or []) if isinstance(t, dict)]
                if not teams:
                    continue
                kind = _game_kind(category, game_name, teams)
                if kind == "matchup":
                    out.extend(
                        _lines_from_matchup(
                            game_name=game_name,
                            teams=teams,
                            event_date=game_date,
                            category=category,
                        )
                    )
                elif kind == "prop_ou":
                    out.extend(
                        _lines_from_prop_ou(
                            game_name=game_name,
                            teams=teams,
                            event_date=game_date,
                            category=category,
                        )
                    )
                elif kind == "futures":
                    out.extend(
                        _lines_from_prop_ml(
                            game_name=game_name,
                            teams=teams,
                            event_date=game_date,
                            category=category,
                            market="futures",
                        )
                    )
                else:
                    out.extend(
                        _lines_from_prop_ml(
                            game_name=game_name,
                            teams=teams,
                            event_date=game_date,
                            category=category,
                            market="props",
                        )
                    )
    return out


def _dedupe_offers(offers: list[MetallicOffer]) -> list[MetallicOffer]:
    best: dict[tuple[Any, ...], MetallicOffer] = {}
    for offer in offers:
        if not offer.event_date or offer.american is None:
            continue
        key = (
            offer.category,
            offer.event_date,
            offer.fixture_label,
            offer.market,
            team_norm(offer.participant),
            round(offer.line, 2),
            offer.side,
            offer.prop_detail,
        )
        prev = best.get(key)
        if prev is None or offer.american > prev.american:
            best[key] = offer
    return list(best.values())


def extract_all_offers_from_schedule(payload: Any) -> list[MetallicOffer]:
    if not isinstance(payload, (dict, list)):
        return []
    return _dedupe_offers(_lines_from_schedule_tree(payload))


def _offers_to_metallic_lines(offers: list[MetallicOffer]) -> list[MetallicLine]:
    """Collapse O/U offers into MetallicLine rows for legacy callers."""
    bucket: dict[tuple[str, str, str, str, float], MetallicLine] = {}
    for offer in offers:
        if offer.market not in ("team_totals", "totals"):
            continue
        if offer.market == "totals":
            team = offer.fixture_label.split(" vs ")[0] if " vs " in offer.fixture_label else ""
            opponent = (
                offer.fixture_label.split(" vs ", 1)[1]
                if " vs " in offer.fixture_label
                else ""
            )
            if not team:
                parts = offer.fixture_label.split(" vs ")
                team = parts[0] if parts else offer.fixture_label
                opponent = parts[1] if len(parts) > 1 else ""
        else:
            team = offer.participant
            opponent = offer.opponent
        key = (
            team_norm(team),
            team_norm(opponent),
            offer.event_date,
            offer.market,
            round(offer.line, 2),
        )
        prev = bucket.get(key)
        over_p = prev.over_price if prev else None
        under_p = prev.under_price if prev else None
        if offer.side == "over":
            over_p = offer.american if over_p is None else max(over_p, offer.american)
        elif offer.side == "under":
            under_p = offer.american if under_p is None else max(under_p, offer.american)
        bucket[key] = MetallicLine(
            team=display_team_name(team),
            opponent=display_team_name(opponent),
            event_date=offer.event_date,
            market=offer.market,
            line=offer.line,
            over_price=over_p,
            under_price=under_p,
        )
    return list(bucket.values())


def extract_wc_lines_from_schedule(payload: Any) -> list[MetallicLine]:
    """Legacy: team totals and game totals only."""
    return _offers_to_metallic_lines(extract_all_offers_from_schedule(payload))


def matchup_tuple(a: str, b: str) -> tuple[str, str]:
    return matchup_key(a, b)
