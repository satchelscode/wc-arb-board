"""Collect World Cup offers from ACE + Odds API and persist arb snapshot."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.ace_client import fetch_wc_helper_pages
from app.ace_parser import AceOffer, TeamTotalLine, extract_all_offers_from_helper
from app.ace_sites import configured_ace_sites
from app.arb_engine import Offer, arb_to_dict, find_cross_book_arbs
from app.books import normalize_book_key
from app.buckeye2_client import fetch_buckeye2_lines
from app.buckeye2_parser import BuckeyeLine, extract_wc_lines_from_buckeye2
from app.config import (
    BUCKEYE2_ENABLED,
    KALSHI_ENABLED,
    METALLIC_ENABLED,
    ODDS_API_BASE,
    ODDS_API_BOOKS,
    ODDS_API_KEY,
    ODDS_API_MARKETS,
    ODDS_API_MAX_EVENTS,
    ODDS_API_PROP_MARKETS,
    ODDS_API_REGIONS,
    ODDS_API_SPORT_KEY,
)
from app.kalshi_client import fetch_all_kalshi_wc_markets
from app.kalshi_parser import KalshiOffer, extract_offers_from_kalshi
from app.metallic_client import fetch_metallic_schedule
from app.metallic_parser import (
    MetallicLine,
    MetallicOffer,
    extract_all_offers_from_schedule,
)
from app.events import matchup_key, matchup_label, opponent_in_event
from app.models import ArbBoardSnapshot, utc_now
from app.names import team_norm, team_total_label
from app.prop_keys import (
    detect_prop_type,
    display_prop_type,
    prop_selection_key,
    strip_fixture_prefix,
)
from app.odds_client import fetch_events_for_sport

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_STATE_KEY = "latest"
# Full-game main lines + WC props/futures from Metallic (exclude 1H — different period).
_METALLIC_INGEST_CATEGORIES = frozenset({"game", "props", "futures"})
_HALF_PROP_RE = re.compile(r"\b(1st\s*half|first\s*half|1h\b|in\s*1st)\b", re.I)


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


def _offers_by_market(offers: list[Offer]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for offer in offers:
        counts[offer.market] = counts.get(offer.market, 0) + 1
    return counts


def _prop_period(label: str) -> str:
    if _HALF_PROP_RE.search(label or ""):
        return "1h"
    return "game"


def _offer_period(
    mo: MetallicOffer | AceOffer | KalshiOffer,
    *,
    label: str = "",
) -> str:
    category = getattr(mo, "category", None)
    if category == "1h":
        return "1h"
    if mo.market == "props":
        return _prop_period(label or getattr(mo, "prop_detail", "") or mo.event_label)
    return "game"


def _parsed_offers_to_scanner(
    offers: list[MetallicOffer] | list[AceOffer] | list[KalshiOffer],
    *,
    book: str,
) -> list[Offer]:
    out: list[Offer] = []
    for mo in offers:
        if mo.opponent:
            matchup = matchup_key(mo.participant, mo.opponent)
        elif mo.fixture_label and " vs " in mo.fixture_label:
            parts = mo.fixture_label.split(" vs ", 1)
            matchup = matchup_key(parts[0], parts[1])
        else:
            matchup = matchup_key(mo.participant, mo.participant)

        fixture = mo.fixture_label or mo.event_label
        period_label = mo.prop_detail or mo.event_label
        if book == "kalshi" and mo.prop_detail:
            label = mo.prop_detail
        elif mo.market == "totals":
            label = (
                mo.prop_detail
                if book == "kalshi" and mo.prop_detail
                else f"{fixture} game total {mo.line:g}"
            )
            participant = "game"
        elif mo.market == "team_totals":
            label = team_total_label(mo.participant, mo.line)
            participant = mo.participant
        elif mo.market == "spreads":
            label = f"{mo.participant} {mo.line:+g}"
            participant = mo.participant
        elif mo.market == "h2h":
            label = f"{fixture} {mo.participant}"
            participant = mo.participant
        elif mo.market in ("props", "futures"):
            detail = strip_fixture_prefix(mo.prop_detail or mo.event_label)
            period_label = detail
            ptype = detect_prop_type(detail, mo.participant)
            if ptype != "unknown":
                label = display_prop_type(ptype)
                sel = prop_selection_key(
                    prop_type=ptype,
                    label=detail,
                    participant=mo.participant,
                    prop_detail=detail,
                )
                if ptype in (
                    "team_score_game",
                    "team_score_1h",
                    "ht_ft",
                    "correct_score",
                    "first_goalscorer",
                    "anytime_scorer",
                ) and sel:
                    label = f"{label} — {sel}"
            else:
                label = detail
                if mo.participant and mo.participant.lower() not in label.lower():
                    label = f"{label} — {mo.participant}"
            participant = mo.participant
        else:
            label = mo.event_label
            participant = mo.participant

        out.append(
            Offer(
                book=book,
                market=mo.market,
                label=label,
                event_date=mo.event_date,
                event_label=fixture,
                participant=participant,
                matchup=matchup,
                line=mo.line,
                side=mo.side,
                american=int(mo.american),
                period=_offer_period(mo, label=period_label),
            )
        )
    return out


def _external_lines_to_offers(
    lines: list[MetallicLine] | list[BuckeyeLine],
    *,
    book: str,
) -> list[Offer]:
    offers: list[Offer] = []
    for line in lines:
        pt = round(line.line, 2)
        matchup = matchup_key(line.team, line.opponent)
        fixture = matchup_label(line.team, line.opponent)
        if line.market == "totals":
            label = f"{fixture} total {pt:g}"
            participant = "game"
        else:
            label = team_total_label(line.team, pt)
            participant = line.team
        if line.over_price is not None:
            offers.append(
                Offer(
                    book=book,
                    market=line.market,
                    label=label,
                    event_date=line.event_date,
                    event_label=fixture,
                    participant=participant,
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
                    market=line.market,
                    label=label,
                    event_date=line.event_date,
                    event_label=fixture,
                    participant=participant,
                    matchup=matchup,
                    line=pt,
                    side="under",
                    american=int(line.under_price),
                )
            )
    return offers


def collect_metallic_offers() -> list[Offer]:
    if not METALLIC_ENABLED:
        return []
    payload = fetch_metallic_schedule()
    if payload is None:
        return []
    parsed = extract_all_offers_from_schedule(payload)
    parsed = [o for o in parsed if o.category in _METALLIC_INGEST_CATEGORIES]
    offers = _parsed_offers_to_scanner(parsed, book="metallic")
    if not offers:
        log.info("Metallic: 0 offers (check schedule POST body / sport menu)")
    else:
        by_market = _offers_by_market(offers)
        log.info(
            "Metallic: %s offers (%s)",
            len(offers),
            ", ".join(f"{k}={v}" for k, v in sorted(by_market.items())),
        )
    return offers


def collect_buckeye2_offers() -> list[Offer]:
    if not BUCKEYE2_ENABLED:
        return []
    payload = fetch_buckeye2_lines()
    if payload is None:
        return []
    lines = extract_wc_lines_from_buckeye2(payload)
    offers = _external_lines_to_offers(lines, book="buckeye2")
    log.info("Buckeye2: %s priced WC lines", len(lines))
    return offers


def collect_ace_offers() -> list[Offer]:
    offers: list[Offer] = []
    for site in configured_ace_sites():
        pages = fetch_wc_helper_pages(site)
        if not pages:
            continue
        parsed: list[AceOffer] = []
        for html, _url in pages:
            parsed.extend(extract_all_offers_from_helper(html))
        site_offers = _parsed_offers_to_scanner(parsed, book=site.key)
        offers.extend(site_offers)
        by_market = _offers_by_market(site_offers)
        log.info(
            "%s: %s offers from %s helper page(s) (%s)",
            site.label,
            len(site_offers),
            len(pages),
            ", ".join(f"{k}={v}" for k, v in sorted(by_market.items())),
        )
        if set(by_market.keys()) == {"team_totals"}:
            log.info(
                "%s: only team totals — add main-line lg to FALCON_WC_HELPER_URLS if spreads/ML missing",
                site.label,
            )
    return offers


def collect_kalshi_offers() -> list[Offer]:
    if not KALSHI_ENABLED:
        return []
    markets = fetch_all_kalshi_wc_markets()
    if not markets:
        return []
    parsed = extract_offers_from_kalshi(markets)
    if markets and not parsed:
        sample = markets[0]
        log.warning(
            "Kalshi: %s markets but 0 parsed offers (sample ticker=%s series=%s)",
            len(markets),
            sample.get("ticker"),
            sample.get("series_ticker"),
        )
    offers = _parsed_offers_to_scanner(parsed, book="kalshi")
    by_market = _offers_by_market(offers)
    log.info(
        "Kalshi: %s offers (%s)",
        len(offers),
        ", ".join(f"{k}={v}" for k, v in sorted(by_market.items())),
    )
    return offers


def _offer_subject(
    *,
    market: str,
    participant: str,
    event_label: str,
    prop_key: str = "",
) -> str:
    if market in ("team_totals", "spreads", "h2h"):
        return team_norm(participant)
    if market == "props":
        base = team_norm(participant) or participant.lower()
        return f"{base}:{prop_key}" if prop_key else base
    return " ".join(event_label.lower().split())


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
    prop_key: str = "",
) -> None:
    if market == "team_totals":
        label = team_total_label(participant, line)
    subject = _offer_subject(
        market=market,
        participant=participant,
        event_label=event_label,
        prop_key=prop_key,
    )
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


def _odds_api_internal_market(api_key: str) -> tuple[str, str]:
    mk = api_key.strip().lower()
    if mk in ("alternate_spreads",):
        return "spreads", mk
    if mk in ("alternate_totals", "alternate_team_totals"):
        if "team" in mk:
            return "team_totals", mk
        return "totals", mk
    if mk in ("btts", "halftime_fulltime"):
        return "props", mk
    if mk.startswith("player_"):
        return "props", mk
    return mk, mk


def collect_odds_api_offers() -> list[Offer]:
    books = _parse_csv(ODDS_API_BOOKS)
    featured = _parse_csv(ODDS_API_MARKETS)
    prop_keys = _parse_csv(ODDS_API_PROP_MARKETS)
    requested = tuple(dict.fromkeys(featured + prop_keys))
    if not ODDS_API_KEY or not books or not requested:
        return []

    bucket: dict[tuple[str, str, str, tuple[str, str], str, float, str], Offer] = {}
    events = fetch_events_for_sport(ODDS_API_SPORT_KEY)[: max(1, ODDS_API_MAX_EVENTS)]
    markets_param = ",".join(requested)
    books_param = ",".join(books)
    allowed = set(requested)

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
                if mk not in allowed:
                    continue
                internal_market, prop_key = _odds_api_internal_market(mk)
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

                    if internal_market == "team_totals":
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
                            market=internal_market,
                            label=f"{team} team total {point:g}",
                            event_date=event_date,
                            event_label=fixture,
                            participant=team,
                            matchup=team_matchup,
                            line=point,
                            side=side,
                            american=american,
                            prop_key=prop_key,
                        )
                    elif internal_market == "totals" and point is not None:
                        if name_field.lower() in ("over", "under"):
                            side = name_field.lower()
                        elif desc_field.lower() in ("over", "under"):
                            side = desc_field.lower()
                        else:
                            continue
                        _put_offer(
                            bucket,
                            book=book,
                            market=internal_market,
                            label=f"{event_label} total {point:g}",
                            event_date=event_date,
                            event_label=event_label,
                            participant="game",
                            matchup=game_matchup,
                            line=point,
                            side=side,
                            american=american,
                            prop_key=prop_key,
                        )
                    elif internal_market == "spreads" and point is not None:
                        team = name_field or desc_field
                        if not team:
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
                            market=internal_market,
                            label=f"{team} {point:+g}",
                            event_date=event_date,
                            event_label=fixture,
                            participant=team,
                            matchup=team_matchup,
                            line=point,
                            side="spread",
                            american=american,
                            prop_key=prop_key,
                        )
                    elif internal_market == "h2h":
                        participant = name_field or desc_field
                        if not participant:
                            continue
                        _put_offer(
                            bucket,
                            book=book,
                            market=internal_market,
                            label=f"{event_label} {participant}",
                            event_date=event_date,
                            event_label=event_label,
                            participant=participant,
                            matchup=game_matchup,
                            line=0.0,
                            side="ml",
                            american=american,
                        )
                    elif internal_market == "props" and prop_key == "btts":
                        low_name = name_field.lower()
                        if low_name not in ("yes", "no"):
                            continue
                        _put_offer(
                            bucket,
                            book=book,
                            market=internal_market,
                            label="Both teams to score",
                            event_date=event_date,
                            event_label=event_label,
                            participant=name_field,
                            matchup=game_matchup,
                            line=0.0,
                            side=low_name,
                            american=american,
                            prop_key=prop_key,
                        )
                    elif internal_market == "props" and prop_key == "halftime_fulltime":
                        selection = name_field or desc_field
                        if not selection:
                            continue
                        _put_offer(
                            bucket,
                            book=book,
                            market=internal_market,
                            label="Halftime and Full Time",
                            event_date=event_date,
                            event_label=event_label,
                            participant=selection,
                            matchup=game_matchup,
                            line=0.0,
                            side="ml",
                            american=american,
                            prop_key=prop_key,
                        )
                    elif internal_market == "props":
                        low_name = name_field.lower()
                        low_desc = desc_field.lower()
                        if low_name in ("over", "under"):
                            side, player = low_name, desc_field
                            if point is None:
                                continue
                            label = f"{prop_key.replace('_', ' ')} — {player} {point:g}"
                            _put_offer(
                                bucket,
                                book=book,
                                market=internal_market,
                                label=label,
                                event_date=event_date,
                                event_label=event_label,
                                participant=player,
                                matchup=game_matchup,
                                line=point,
                                side=side,
                                american=american,
                                prop_key=prop_key,
                            )
                        elif low_desc in ("over", "under"):
                            side, player = low_desc, name_field
                            if point is None:
                                continue
                            label = f"{prop_key.replace('_', ' ')} — {player} {point:g}"
                            _put_offer(
                                bucket,
                                book=book,
                                market=internal_market,
                                label=label,
                                event_date=event_date,
                                event_label=event_label,
                                participant=player,
                                matchup=game_matchup,
                                line=point,
                                side=side,
                                american=american,
                                prop_key=prop_key,
                            )
                        elif low_name in ("yes", "no"):
                            player = desc_field or name_field
                            label = f"{prop_key.replace('_', ' ')} — {player}"
                            _put_offer(
                                bucket,
                                book=book,
                                market=internal_market,
                                label=label,
                                event_date=event_date,
                                event_label=event_label,
                                participant=player,
                                matchup=game_matchup,
                                line=0.0,
                                side=low_name,
                                american=american,
                                prop_key=prop_key,
                            )
    offers = list(bucket.values())
    if offers:
        by_market = _offers_by_market(offers)
        log.info(
            "Odds API: %s offers (%s)",
            len(offers),
            ", ".join(f"{k}={v}" for k, v in sorted(by_market.items())),
        )
    return offers


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
    metallic = collect_metallic_offers()
    buckeye2 = collect_buckeye2_offers()
    kalshi = collect_kalshi_offers()
    api = collect_odds_api_offers()
    all_offers = ace + metallic + buckeye2 + kalshi + api
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
            "offers_by_market": _offers_by_market(all_offers),
            "metallic_by_market": _offers_by_market(metallic),
            "ace_by_market": _offers_by_market(ace),
            "kalshi_by_market": _offers_by_market(kalshi),
            "odds_api_by_market": _offers_by_market(api),
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
