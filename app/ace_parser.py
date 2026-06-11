"""Parse ACE NewScheduleHelper JSON for all World Cup markets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.events import matchup_label
from app.names import display_team_name, team_norm

_TEAM_TOTAL_SUFFIX = re.compile(r"\s*\(TEAM TOTAL\)\s*$", re.I)
_VS_RE = re.compile(r"\s+vs\s+", re.I)


@dataclass(frozen=True)
class AceOffer:
    event_date: str
    event_label: str
    fixture_label: str
    market: str
    participant: str
    opponent: str
    line: float
    side: str
    american: int
    prop_detail: str = ""


@dataclass(frozen=True)
class TeamTotalLine:
    team: str
    opponent: str
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


def _first_float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        val = row.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("pk", "pick", "pick'em", "pickem"):
                return 0.0
            try:
                return float(s)
            except ValueError:
                m = re.search(r"([+-]?\d+(?:\.\d+)?)", s)
                if m:
                    try:
                        return float(m.group(1))
                    except ValueError:
                        continue
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
    over = _first_int(row, "ovoddst", "OverOdds", "hoddsh", "hspoddst")
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


def _append_ou(
    out: list[AceOffer],
    *,
    event_date: str,
    fixture: str,
    market: str,
    participant: str,
    opponent: str,
    line: float,
    over_p: int | None,
    under_p: int | None,
    prop_detail: str = "",
) -> None:
    if over_p is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market=market,
                participant=participant,
                opponent=opponent,
                line=line,
                side="over",
                american=over_p,
                prop_detail=prop_detail,
            )
        )
    if under_p is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market=market,
                participant=participant,
                opponent=opponent,
                line=line,
                side="under",
                american=under_p,
                prop_detail=prop_detail,
            )
        )


def _team_and_opponent(game: dict[str, Any]) -> tuple[str, str]:
    htm_raw = _first_str(game, "htm")
    vtm_raw = _first_str(game, "vtm")
    htm = _strip_team_label(htm_raw)
    vtm = _strip_team_label(vtm_raw)
    if "(TEAM TOTAL)" in htm_raw.upper():
        return htm, vtm
    if "(TEAM TOTAL)" in vtm_raw.upper():
        return vtm, htm
    return "", ""


def _is_team_total_game(game: dict[str, Any]) -> bool:
    label = _first_str(game, "htm", "vtm", "gdesc")
    return "(TEAM TOTAL)" in label.upper()


def _is_matchup_game(game: dict[str, Any]) -> bool:
    if _is_team_total_game(game):
        return False
    htm = _strip_team_label(_first_str(game, "htm"))
    vtm = _strip_team_label(_first_str(game, "vtm"))
    if htm and vtm and htm.lower() != vtm.lower():
        return True
    gdesc = _first_str(game, "gdesc")
    return bool(_VS_RE.search(gdesc))


def _matchup_teams(game: dict[str, Any]) -> tuple[str, str]:
    htm = display_team_name(_strip_team_label(_first_str(game, "htm")))
    vtm = display_team_name(_strip_team_label(_first_str(game, "vtm")))
    if htm and vtm and htm.lower() != vtm.lower():
        return htm, vtm
    gdesc = _first_str(game, "gdesc")
    if _VS_RE.search(gdesc):
        parts = _VS_RE.split(gdesc, maxsplit=1)
        if len(parts) == 2:
            return display_team_name(parts[0].strip()), display_team_name(parts[1].strip())
    return "", ""


def _lines_from_team_total_game(game: dict[str, Any]) -> list[AceOffer]:
    glines = game.get("GameLines")
    if not isinstance(glines, list) or not glines:
        return []
    row = glines[0] if isinstance(glines[0], dict) else {}
    if not _is_priced_ou_row(row):
        return []
    line_pt = _line_from_row(row)
    over_p, under_p = _ou_prices(row)
    if line_pt is None or (over_p is None and under_p is None):
        return []
    team, opponent = _team_and_opponent(game)
    if not team:
        return []
    fixture = matchup_label(team, opponent) if opponent else team
    event_date = _gmdt_to_iso(_first_str(game, "gmdt"))
    out: list[AceOffer] = []
    _append_ou(
        out,
        event_date=event_date,
        fixture=fixture,
        market="team_totals",
        participant=display_team_name(team),
        opponent=display_team_name(opponent),
        line=line_pt,
        over_p=over_p,
        under_p=under_p,
    )
    return out


def _lines_from_matchup_game(game: dict[str, Any]) -> list[AceOffer]:
    glines = game.get("GameLines")
    if not isinstance(glines, list) or not glines:
        return []
    row = glines[0] if isinstance(glines[0], dict) else {}
    if row.get("EmptyGame"):
        return []
    team_a, team_b = _matchup_teams(game)
    if not team_a or not team_b:
        return []
    fixture = matchup_label(team_a, team_b)
    event_date = _gmdt_to_iso(_first_str(game, "gmdt"))
    out: list[AceOffer] = []

    spread_a = _first_float(row, "hsprdh", "hsprdt", "HomSpread")
    spread_b = _first_float(row, "vsprdh", "vsprdt", "VisSpread")
    odds_a = _first_int(row, "hsprdoddst", "hspoddst", "hsprdodds")
    odds_b = _first_int(row, "vsprdoddst", "vspoddst", "vsprdodds")
    if odds_a is not None and spread_a is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market="spreads",
                participant=team_a,
                opponent=team_b,
                line=spread_a,
                side="spread",
                american=odds_a,
            )
        )
    if odds_b is not None and spread_b is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market="spreads",
                participant=team_b,
                opponent=team_a,
                line=spread_b,
                side="spread",
                american=odds_b,
            )
        )

    ml_a = _first_int(row, "hoddsh", "hoddst", "hmloddst", "HomMoneyLine")
    ml_b = _first_int(row, "voddsh", "voddst", "vmloddst", "VisMoneyLine")
    ml_d = _first_int(row, "doddsh", "doddst", "dmloddst", "DrawMoneyLine")
    if ml_a is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market="h2h",
                participant=team_a,
                opponent=team_b,
                line=0.0,
                side="ml",
                american=ml_a,
            )
        )
    if ml_b is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market="h2h",
                participant=team_b,
                opponent=team_a,
                line=0.0,
                side="ml",
                american=ml_b,
            )
        )
    if ml_d is not None:
        out.append(
            AceOffer(
                event_date=event_date,
                event_label=fixture,
                fixture_label=fixture,
                market="h2h",
                participant="Draw",
                opponent="",
                line=0.0,
                side="ml",
                american=ml_d,
            )
        )

    line_pt = _line_from_row(row)
    over_p, under_p = _ou_prices(row)
    if line_pt is not None and (over_p is not None or under_p is not None):
        _append_ou(
            out,
            event_date=event_date,
            fixture=fixture,
            market="totals",
            participant="game",
            opponent="",
            line=line_pt,
            over_p=over_p,
            under_p=under_p,
        )
    return out


def _prop_detail_from_game(game: dict[str, Any], fallback: str) -> str:
    gdesc = _first_str(game, "gdesc", "Description")
    if gdesc and not _VS_RE.search(gdesc):
        return gdesc
    return fallback


def _lines_from_prop_rows(
    *,
    game: dict[str, Any],
    fixture: str,
    event_date: str,
    prop_detail: str,
) -> list[AceOffer]:
    out: list[AceOffer] = []
    glines = game.get("GameLines")
    if not isinstance(glines, list):
        return out
    for row in glines:
        if not isinstance(row, dict) or row.get("EmptyGame"):
            continue
        participant = _strip_team_label(
            _first_str(row, "gdesc", "Description", "PlayerName", "Selection")
        )
        if not participant:
            participant = _prop_detail_from_game(game, prop_detail)
        line_pt = _line_from_row(row)
        over_p, under_p = _ou_prices(row)
        if line_pt is not None and (over_p is not None or under_p is not None):
            _append_ou(
                out,
                event_date=event_date,
                fixture=fixture,
                market="props",
                participant=display_team_name(participant),
                opponent="",
                line=line_pt,
                over_p=over_p,
                under_p=under_p,
                prop_detail=prop_detail,
            )
            continue
        ml = _first_int(row, "hoddsh", "hoddst", "ovoddst", "unoddst")
        if ml is not None and participant:
            out.append(
                AceOffer(
                    event_date=event_date,
                    event_label=fixture or prop_detail,
                    fixture_label=fixture,
                    market="props",
                    participant=display_team_name(participant),
                    opponent="",
                    line=0.0,
                    side="ml",
                    american=ml,
                    prop_detail=prop_detail,
                )
            )
    return out


def _lines_from_prop_children(
    game: dict[str, Any],
    *,
    fixture: str,
    event_date: str,
    depth: int = 0,
) -> list[AceOffer]:
    if depth > 6:
        return []
    out: list[AceOffer] = []
    for key in ("GamePROPTNTChilds", "GameChilds"):
        children = game.get(key)
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            prop_detail = _prop_detail_from_game(child, _first_str(child, "Description"))
            for sub in child.get("Games") or []:
                if not isinstance(sub, dict):
                    continue
                sub_fixture = fixture
                if not sub_fixture:
                    ta, tb = _matchup_teams(sub)
                    sub_fixture = matchup_label(ta, tb) if ta and tb else ""
                sub_date = _gmdt_to_iso(_first_str(sub, "gmdt")) or event_date
                out.extend(
                    _lines_from_prop_rows(
                        game=sub,
                        fixture=sub_fixture,
                        event_date=sub_date,
                        prop_detail=prop_detail or _prop_detail_from_game(sub, ""),
                    )
                )
                out.extend(
                    _lines_from_prop_children(
                        sub,
                        fixture=sub_fixture,
                        event_date=sub_date,
                        depth=depth + 1,
                    )
                )
            out.extend(
                _lines_from_prop_rows(
                    game=child,
                    fixture=fixture,
                    event_date=event_date,
                    prop_detail=prop_detail,
                )
            )
    return out


def _lines_from_game(game: dict[str, Any]) -> list[AceOffer]:
    if _is_team_total_game(game):
        return _lines_from_team_total_game(game)
    team_a, team_b = _matchup_teams(game)
    fixture = matchup_label(team_a, team_b) if team_a and team_b else ""
    event_date = _gmdt_to_iso(_first_str(game, "gmdt"))
    if _is_matchup_game(game):
        return _lines_from_matchup_game(game) + _lines_from_prop_children(
            game, fixture=fixture, event_date=event_date
        )
    prop_detail = _prop_detail_from_game(game, "")
    prop_lines = _lines_from_prop_rows(
        game=game,
        fixture=fixture,
        event_date=event_date,
        prop_detail=prop_detail,
    )
    prop_lines.extend(
        _lines_from_prop_children(game, fixture=fixture, event_date=event_date)
    )
    return prop_lines


def _dedupe_offers(offers: list[AceOffer]) -> list[AceOffer]:
    best: dict[tuple[Any, ...], AceOffer] = {}
    for offer in offers:
        if not offer.event_date:
            continue
        key = (
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


def extract_all_offers_from_helper(html: str) -> list[AceOffer]:
    try:
        payload = json.loads(html)
    except json.JSONDecodeError:
        return []
    out: list[AceOffer] = []
    for node in _iter_json_nodes(payload):
        if not isinstance(node, dict):
            continue
        games = node.get("Games")
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            out.extend(_lines_from_game(game))
    return _dedupe_offers(out)


def extract_team_totals_from_helper(
    html: str,
    *,
    wc_lg: str = "3749",
) -> list[TeamTotalLine]:
    del wc_lg  # URL filter only; kept for call-site compatibility
    bucket: dict[tuple[str, str, str, float], TeamTotalLine] = {}
    for offer in extract_all_offers_from_helper(html):
        if offer.market != "team_totals":
            continue
        key = (
            team_norm(offer.participant),
            team_norm(offer.opponent),
            offer.event_date,
            round(offer.line, 2),
        )
        prev = bucket.get(key)
        over_p = prev.over_price if prev else None
        under_p = prev.under_price if prev else None
        if offer.side == "over":
            over_p = offer.american
        elif offer.side == "under":
            under_p = offer.american
        bucket[key] = TeamTotalLine(
            team=offer.participant,
            opponent=offer.opponent,
            event_date=offer.event_date,
            line=offer.line,
            over_price=over_p,
            under_price=under_p,
        )
    return list(bucket.values())
