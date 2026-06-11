"""Collect World Cup offers from ACE + Odds API and persist arb snapshot."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.ace_client import fetch_wc_helper_page
from app.ace_parser import TeamTotalLine, extract_team_totals_from_helper
from app.ace_sites import configured_ace_sites
from app.arb_engine import Offer, arb_to_dict, find_cross_book_arbs
from app.books import normalize_book_key
from app.config import (
    ODDS_API_BASE,
    ODDS_API_BOOKS,
    ODDS_API_KEY,
    ODDS_API_MARKETS,
    ODDS_API_MAX_EVENTS,
    ODDS_API_REGIONS,
    ODDS_API_SPORT_KEY,
)
from app.events import matchup_key, matchup_label, opponent_in_event
from app.models import ArbBoardSnapshot, utc_now
from app.names import team_norm, team_total_label
from app.odds_client import fetch_events_for_sport

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_STATE_KEY = "latest"


def _parse_csv(raw: str) -> tuple[str, ...]:
    return tuple(x.strip().lower() for x in (raw or "").split(",") if x.strip())


def _commence_to_et_date(commence: str | None) -> str:
    if not commence:
        return ""
    try:
        dt = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        return dt.astimezone(ET).date().isoformat()
    except ValueError:
        return ""


def _team_lines_to_offers(lines: list[TeamTotalLine], *, book: str) -> list[Offer]:
    offers: list[Offer] = []
    for line in lines:
        pt = round(line.line, 2)
        label = team_total_label(line.team, pt)
        matchup = matchup_key(line.team, line.opponent)
        fixture = matchup_label(line.team, line.opponent)
        if line.over_price is not None:
            offers.append(
                Offer(
                    book=book,
                    market="team_totals",
                    label=label,
                    event_date=line.event_date,
                    event_label=fixture,
                    participant=line.team,
                    matchup=matchup,
                    line=pt,
                    side="over",
                    american=int(line.over_price),
                )
            )
        if line.under_price is not None:
            offers.append(
                Offer(
                    book=book,
                    market="team_totals",
                    label=label,
                    event_date=line.event_date,
                    event_label=fixture,
                    participant=line.team,
                    matchup=matchup,
                    line=pt,
                    side="under",
                    american=int(line.under_price),
                )
            )
    return offers


def collect_ace_offers() -> list[Offer]:
    offers: list[Offer] = []
    for site in configured_ace_sites():
        page = fetch_wc_helper_page(site)
        if not page:
            continue
        html, _url = page
        lines = extract_team_totals_from_helper(html)
        offers.extend(_team_lines_to_offers(lines, book=site.key))
        log.info("%s: %s team-total lines", site.label, len(lines))
    return offers


def _put_offer(
    bucket: dict[tuple[str, str, str, tuple[str, str], str, float, str], Offer],
    *,
    book: str,
    market: str,
    label: str,
    event_date: str,
    event_label: str,
    participant: str,
    matchup: tuple[str, str],
    line: float,
    side: str,
    american: int,
) -> None:
    if market == "team_totals":
        subject = team_norm(participant)
        label = team_total_label(participant, line)
    else:
        subject = " ".join(event_label.lower().split())
    key = (book, market, event_date, matchup, subject, round(line, 2), side)
    prev = bucket.get(key)
    if prev is None or american > prev.american:
        bucket[key] = Offer(
            book=book,
            market=market,
            label=label,
            event_date=event_date,
            event_label=event_label,
            participant=participant,
            matchup=matchup,
            line=round(line, 2),
            side=side,
            american=american,
        )


def collect_odds_api_offers() -> list[Offer]:
    books = _parse_csv(ODDS_API_BOOKS)
    markets = _parse_csv(ODDS_API_MARKETS)
    if not ODDS_API_KEY or not books or not markets:
        return []

    bucket: dict[tuple[str, str, str, tuple[str, str], str, float, str], Offer] = {}
    events = fetch_events_for_sport(ODDS_API_SPORT_KEY)[: max(1, ODDS_API_MAX_EVENTS)]
    markets_param = ",".join(markets)
    books_param = ",".join(books)

    for event in events:
        event_id = event.get("id")
        if not event_id:
            continue
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        event_label = f"{away} @ {home}" if away and home else ""
        event_date = _commence_to_et_date(event.get("commence_time"))
        game_matchup = matchup_key(away, home)
        url = f"{ODDS_API_BASE}/sports/{ODDS_API_SPORT_KEY}/events/{event_id}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": ODDS_API_REGIONS,
            "markets": markets_param,
            "bookmakers": books_param,
            "oddsFormat": "american",
        }
        try:
            response = requests.get(url, params=params, timeout=25)
            if response.status_code in (404, 422):
                continue
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            log.warning("Odds API event %s failed: %s", event_id, exc)
            continue

        for bookmaker in payload.get("bookmakers", []):
            book = str(bookmaker.get("key") or "").strip().lower()
            if book not in books:
                continue
            for market in bookmaker.get("markets", []):
                mk = str(market.get("key") or "").strip().lower()
                if mk not in markets:
                    continue
                for outcome in market.get("outcomes", []):
                    if not isinstance(outcome, dict):
                        continue
                    name_field = str(outcome.get("name") or "").strip()
                    desc_field = str(outcome.get("description") or "").strip()
                    price_raw = outcome.get("price")
                    if not isinstance(price_raw, (int, float)) or isinstance(price_raw, bool):
                        continue
                    american = int(price_raw)
                    point_raw = outcome.get("point")
                    point: float | None = None
                    if isinstance(point_raw, (int, float)) and not isinstance(point_raw, bool):
                        point = float(point_raw)

                    if mk == "team_totals":
                        if name_field.lower() in ("over", "under"):
                            side, team = name_field.lower(), desc_field
                        elif desc_field.lower() in ("over", "under"):
                            side, team = desc_field.lower(), name_field
                        else:
                            continue
                        if point is None:
                            continue
                        opponent = opponent_in_event(home=home, away=away, team=team)
                        team_matchup = (
                            matchup_key(team, opponent) if opponent else game_matchup
                        )
                        fixture = (
                            matchup_label(team, opponent)
                            if opponent
                            else event_label
                        )
                        _put_offer(
                            bucket,
                            book=book,
                            market=mk,
                            label=f"{team} team total {point:g}",
                            event_date=event_date,
                            event_label=fixture,
                            participant=team,
                            matchup=team_matchup,
                            line=point,
                            side=side,
                            american=american,
                        )
                    elif mk == "totals" and point is not None:
                        if name_field.lower() in ("over", "under"):
                            side = name_field.lower()
                        elif desc_field.lower() in ("over", "under"):
                            side = desc_field.lower()
                        else:
                            continue
                        _put_offer(
                            bucket,
                            book=book,
                            market=mk,
                            label=f"{event_label} total {point:g}",
                            event_date=event_date,
                            event_label=event_label,
                            participant="game",
                            matchup=game_matchup,
                            line=point,
                            side=side,
                            american=american,
                        )
    return list(bucket.values())


def _normalize_snapshot_books(payload: dict[str, Any]) -> dict[str, Any]:
    books = sorted({normalize_book_key(b) for b in payload.get("books") or []})
    by_book: dict[str, int] = {}
    for book, count in (payload.get("offers_by_book") or {}).items():
        key = normalize_book_key(str(book))
        by_book[key] = by_book.get(key, 0) + int(count)
    arbs = []
    for row in payload.get("arbs") or []:
        if not isinstance(row, dict):
            continue
        arbs.append(
            {
                **row,
                "over_book": normalize_book_key(str(row.get("over_book") or "")),
                "under_book": normalize_book_key(str(row.get("under_book") or "")),
            }
        )
    return {**payload, "books": books, "offers_by_book": by_book, "arbs": arbs}


def refresh_snapshot(*, session) -> dict[str, Any]:
    ace = collect_ace_offers()
    api = collect_odds_api_offers()
    all_offers = ace + api
    arbs = find_cross_book_arbs(all_offers)

    books = sorted({o.book for o in all_offers})
    by_book = {b: sum(1 for o in all_offers if o.book == b) for b in books}
    scanned_at = utc_now()
    payload = _normalize_snapshot_books(
        {
            "scanned_at": scanned_at.isoformat(),
            "sport_key": ODDS_API_SPORT_KEY,
            "offer_count": len(all_offers),
            "arb_count": len(arbs),
            "books": books,
            "offers_by_book": by_book,
            "arbs": [arb_to_dict(a) for a in arbs],
        }
    )
    body = json.dumps(payload)
    row = session.get(ArbBoardSnapshot, _STATE_KEY)
    if row is None:
        session.add(ArbBoardSnapshot(key=_STATE_KEY, scanned_at=scanned_at, payload_json=body))
    else:
        row.scanned_at = scanned_at
        row.payload_json = body
    session.commit()
    log.info("Scan complete: offers=%s arbs=%s", len(all_offers), len(arbs))
    return payload


def load_snapshot(*, session) -> dict[str, Any]:
    row = session.get(ArbBoardSnapshot, _STATE_KEY)
    if row is None or not row.payload_json:
        return {
            "scanned_at": None,
            "sport_key": ODDS_API_SPORT_KEY,
            "offer_count": 0,
            "arb_count": 0,
            "books": [],
            "offers_by_book": {},
            "arbs": [],
        }
    try:
        data = json.loads(row.payload_json)
        if isinstance(data, dict):
            return _normalize_snapshot_books(data)
    except json.JSONDecodeError:
        pass
    return {"arbs": [], "offer_count": 0, "arb_count": 0}
