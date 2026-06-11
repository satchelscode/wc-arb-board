"""Parse Kalshi WC markets into normalized single-sided offers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.events import matchup_key, matchup_label
from app.names import display_team_name, team_norm

_TICKER_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_VS_RE = re.compile(r"^(.+?)\s+vs\s+(.+?)(?:\s+Winner)?\??$", re.I)
_TOTAL_RE = re.compile(r"over\s+(\d+(?:\.\d+)?)\s+goals?", re.I)
_TEAM_TOTAL_RE = re.compile(
    r"(?:Will|If)\s+(.+?)\s+score\s+over\s+(\d+(?:\.\d+)?)\s+goals?",
    re.I,
)
_SPREAD_RE = re.compile(
    r"(.+?)\s+wins?\s+by\s+over\s+(\d+(?:\.\d+)?)\s+goals?",
    re.I,
)
_GOALSCORER_RE = re.compile(r"^(.+?):\s*(\d+)\+\s*goals?$", re.I)
_RULES_FIXTURE_RE = re.compile(
    r"in the (.+?)\s+vs\s+(.+?)\s+professional",
    re.I,
)


@dataclass(frozen=True)
class KalshiOffer:
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


def prob_to_american(prob: float) -> int | None:
    if prob <= 0 or prob >= 1:
        return None
    if prob >= 0.5:
        return int(-round(prob / (1 - prob) * 100))
    return int(round((1 - prob) / prob * 100))


def _dollar_ask(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _date_from_ticker(ticker: str) -> str:
    m = _TICKER_DATE.search(ticker or "")
    if not m:
        return ""
    yy, mon, dd = m.group(1), m.group(2).upper(), m.group(3)
    month = _MONTHS.get(mon)
    if not month:
        return ""
    return f"20{yy}-{month:02d}-{int(dd):02d}"


def _series_from_market(market: dict[str, Any]) -> str:
    series = str(market.get("series_ticker") or "").strip().upper()
    if series:
        return series
    ticker = str(market.get("ticker") or market.get("event_ticker") or "")
    if "-" in ticker:
        return ticker.split("-", 1)[0].upper()
    return ""


def _fixture_from_title(title: str) -> tuple[str, str, str]:
    m = _VS_RE.match((title or "").strip())
    if not m:
        return "", "", title
    team_a = display_team_name(m.group(1).strip())
    team_b = display_team_name(m.group(2).strip())
    return team_a, team_b, matchup_label(team_a, team_b)


def _fixture_from_rules(rules: str) -> tuple[str, str, str]:
    m = _RULES_FIXTURE_RE.search(rules or "")
    if not m:
        return "", "", ""
    team_a = display_team_name(m.group(1).strip())
    team_b = display_team_name(m.group(2).strip())
    return team_a, team_b, matchup_label(team_a, team_b)


def _fixture_context(
    title: str, rules: str
) -> tuple[str, str, str]:
    team_a, team_b, fixture = _fixture_from_title(title)
    if fixture and team_a and team_b:
        return team_a, team_b, fixture
    return _fixture_from_rules(rules)


def _append_side(
    out: list[KalshiOffer],
    *,
    event_date: str,
    fixture: str,
    market: str,
    participant: str,
    opponent: str,
    line: float,
    side: str,
    ask_prob: float | None,
    prop_detail: str = "",
) -> None:
    if ask_prob is None:
        return
    american = prob_to_american(ask_prob)
    if american is None:
        return
    out.append(
        KalshiOffer(
            event_date=event_date,
            event_label=fixture or participant,
            fixture_label=fixture,
            market=market,
            participant=participant,
            opponent=opponent,
            line=line,
            side=side,
            american=american,
            prop_detail=prop_detail,
        )
    )


def _lines_from_market(market: dict[str, Any]) -> list[KalshiOffer]:
    series = _series_from_market(market)
    title = str(market.get("title") or "").strip()
    rules = str(market.get("rules_primary") or "").strip()
    yes_sub = str(market.get("yes_sub_title") or "").strip()
    ticker = str(market.get("ticker") or "")
    event_date = _date_from_ticker(ticker) or _date_from_ticker(
        str(market.get("event_ticker") or "")
    )
    team_a, team_b, fixture = _fixture_context(title, rules)
    yes_ask = _dollar_ask(market.get("yes_ask_dollars"))
    no_ask = _dollar_ask(market.get("no_ask_dollars"))
    out: list[KalshiOffer] = []

    if series == "KXWCTOTAL":
        m = _TOTAL_RE.search(title) or _TOTAL_RE.search(yes_sub) or _TOTAL_RE.search(rules)
        if m:
            line = float(m.group(1))
            _append_side(
                out,
                event_date=event_date,
                fixture=fixture,
                market="totals",
                participant="game",
                opponent="",
                line=line,
                side="over",
                ask_prob=yes_ask,
            )
            _append_side(
                out,
                event_date=event_date,
                fixture=fixture,
                market="totals",
                participant="game",
                opponent="",
                line=line,
                side="under",
                ask_prob=no_ask,
            )
        return out

    if series == "KXWCTEAMTOTAL":
        m = (
            _TEAM_TOTAL_RE.search(title)
            or _TEAM_TOTAL_RE.search(rules)
            or _TEAM_TOTAL_RE.search(yes_sub)
        )
        if m:
            team = display_team_name(m.group(1).strip())
            line = float(m.group(2))
            opponent = team_b if team_norm(team) == team_norm(team_a) else team_a
            if not opponent and team_a and team_b:
                opponent = team_b if team != team_a else team_a
            fix = fixture or matchup_label(team, opponent)
            _append_side(
                out,
                event_date=event_date,
                fixture=fix,
                market="team_totals",
                participant=team,
                opponent=opponent,
                line=line,
                side="over",
                ask_prob=yes_ask,
            )
            _append_side(
                out,
                event_date=event_date,
                fixture=fix,
                market="team_totals",
                participant=team,
                opponent=opponent,
                line=line,
                side="under",
                ask_prob=no_ask,
            )
        return out

    if series == "KXWCSPREAD":
        m = _SPREAD_RE.search(title) or _SPREAD_RE.search(rules) or _SPREAD_RE.search(yes_sub)
        if m:
            team = display_team_name(m.group(1).strip())
            line = -float(m.group(2))
            opponent = team_b if team_norm(team) == team_norm(team_a) else team_a
            fix = fixture or matchup_label(team, opponent)
            _append_side(
                out,
                event_date=event_date,
                fixture=fix,
                market="spreads",
                participant=team,
                opponent=opponent,
                line=line,
                side="spread",
                ask_prob=yes_ask,
            )
        return out

    if series == "KXWCGOAL":
        m = _GOALSCORER_RE.match(yes_sub) or _GOALSCORER_RE.match(title)
        if m:
            player = m.group(1).strip()
            goals = int(m.group(2))
            prop_detail = f"{player} {goals}+ goals"
            _append_side(
                out,
                event_date=event_date,
                fixture=fixture,
                market="props",
                participant=player,
                opponent="",
                line=float(goals) - 0.5,
                side="yes",
                ask_prob=yes_ask,
                prop_detail=prop_detail,
            )
            _append_side(
                out,
                event_date=event_date,
                fixture=fixture,
                market="props",
                participant=player,
                opponent="",
                line=float(goals) - 0.5,
                side="no",
                ask_prob=no_ask,
                prop_detail=prop_detail,
            )
        return out

    if series == "KXWCGAME":
        participant = display_team_name(yes_sub or "")
        if not participant:
            return out
        if participant.lower() == "tie":
            participant = "Draw"
        opponent = ""
        if team_a and team_b and participant != "Draw":
            opponent = team_b if team_norm(participant) == team_norm(team_a) else team_a
        fix = fixture or title
        _append_side(
            out,
            event_date=event_date,
            fixture=fix,
            market="h2h",
            participant=participant,
            opponent=opponent,
            line=0.0,
            side="ml",
            ask_prob=yes_ask,
        )
        return out

    return out


def extract_offers_from_kalshi(markets: list[dict[str, Any]]) -> list[KalshiOffer]:
    best: dict[tuple[Any, ...], KalshiOffer] = {}
    for market in markets:
        for offer in _lines_from_market(market):
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
