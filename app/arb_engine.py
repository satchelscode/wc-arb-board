"""
Cross-book arb detection for World Cup markets.

Only flags arbs where the same line exists on two+ books with over/under on
different books. Orphan lines (one book only) are never shown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product

from app.config import MIN_EDGE_PCT
from app.names import display_team_name, team_norm, team_total_label


@dataclass(frozen=True)
class Offer:
    book: str
    market: str
    label: str
    event_date: str
    event_label: str
    participant: str
    matchup: tuple[str, str]
    line: float
    side: str
    american: int


@dataclass(frozen=True)
class Arb:
    market: str
    label: str
    event_date: str
    event_label: str
    line: float
    over_book: str
    over_price: int
    under_book: str
    under_price: int
    edge_pct: float


def implied_prob_american(american: int) -> float:
    if american > 0:
        return 100.0 / (american + 100.0)
    b = abs(american)
    return b / (b + 100.0)


def _group_key(offer: Offer) -> tuple[str, tuple[str, str], str, str, float]:
    if offer.market == "team_totals":
        subject = team_norm(offer.participant)
    else:
        subject = " ".join(offer.event_label.lower().split())
    return (offer.event_date, offer.matchup, subject, offer.market, round(offer.line, 2))


def _offer_identity_key(offer: Offer) -> tuple[str, str, tuple[str, str], str, float, str]:
    event_date, matchup, subject, market, line = _group_key(offer)
    return (offer.book, market, event_date, matchup, subject, line, offer.side)


def dedupe_offers(offers: list[Offer]) -> list[Offer]:
    """One offer per book/market/line/side — keep best (highest) American odds."""
    best: dict[tuple[str, str, tuple[str, str], str, float, str], Offer] = {}
    for offer in offers:
        key = _offer_identity_key(offer)
        prev = best.get(key)
        if prev is None or offer.american > prev.american:
            best[key] = offer
    return list(best.values())


def _best_offer_per_book(offers: list[Offer]) -> dict[str, Offer]:
    best: dict[str, Offer] = {}
    for offer in offers:
        prev = best.get(offer.book)
        if prev is None or offer.american > prev.american:
            best[offer.book] = offer
    return best


def _edge_pct(over_price: int, under_price: int) -> float:
    total = implied_prob_american(over_price) + implied_prob_american(under_price)
    return max(0.0, (1.0 - total) * 100.0)


def find_cross_book_arbs(offers: list[Offer]) -> list[Arb]:
    offers = dedupe_offers(offers)
    by_group: dict[tuple[str, tuple[str, str], str, str, float], list[Offer]] = {}
    for offer in offers:
        by_group.setdefault(_group_key(offer), []).append(offer)

    arbs: list[Arb] = []
    seen: set[tuple[str, tuple[str, str], str, str, float, str, str]] = set()

    for (event_date, matchup, subject, market, line), group in by_group.items():
        overs = _best_offer_per_book([o for o in group if o.side == "over"])
        unders = _best_offer_per_book([o for o in group if o.side == "under"])
        if not overs or not unders:
            continue
        if len({o.book for o in group}) < 2:
            continue

        if market == "team_totals":
            label = team_total_label(subject, line)
            if matchup[0] and matchup[1] and matchup[0] != matchup[1]:
                event_label = (
                    f"{display_team_name(matchup[0])} vs {display_team_name(matchup[1])}"
                )
            else:
                event_label = display_team_name(subject)
        else:
            label = next((o.label for o in group if o.label), "")
            event_label = next((o.event_label for o in group if o.event_label), "")

        for over_o, under_o in product(overs.values(), unders.values()):
            if over_o.book == under_o.book:
                continue
            edge = _edge_pct(over_o.american, under_o.american)
            if edge < MIN_EDGE_PCT - 1e-9:
                continue
            pair = (event_date, matchup, subject, market, line, over_o.book, under_o.book)
            if pair in seen:
                continue
            seen.add(pair)
            arbs.append(
                Arb(
                    market=market,
                    label=label,
                    event_date=event_date,
                    event_label=event_label,
                    line=line,
                    over_book=over_o.book,
                    over_price=over_o.american,
                    under_book=under_o.book,
                    under_price=under_o.american,
                    edge_pct=round(edge, 3),
                )
            )

    arbs.sort(key=lambda a: (-a.edge_pct, a.label, a.line))
    return arbs


def arb_to_dict(arb: Arb) -> dict:
    return asdict(arb)
