"""
Cross-book arb detection for World Cup markets.

Only flags arbs where the same line exists on two+ books with over/under on
different books. Orphan lines (one book only) are never shown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product

from app.config import MIN_EDGE_PCT
from app.names import team_norm


@dataclass(frozen=True)
class Offer:
    book: str
    market: str
    label: str
    event_date: str
    event_label: str
    participant: str
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


def _group_key(offer: Offer) -> tuple[str, str, str, float]:
    if offer.market == "team_totals":
        subject = team_norm(offer.participant)
    else:
        subject = " ".join(offer.event_label.lower().split())
    return (offer.event_date, subject, offer.market, round(offer.line, 2))


def _edge_pct(over_price: int, under_price: int) -> float:
    total = implied_prob_american(over_price) + implied_prob_american(under_price)
    return max(0.0, (1.0 - total) * 100.0)


def find_cross_book_arbs(offers: list[Offer]) -> list[Arb]:
    by_group: dict[tuple[str, str, str, float], list[Offer]] = {}
    for offer in offers:
        by_group.setdefault(_group_key(offer), []).append(offer)

    arbs: list[Arb] = []
    seen: set[tuple] = set()

    for (_event_date, _subject, market, line), group in by_group.items():
        overs = [o for o in group if o.side == "over"]
        unders = [o for o in group if o.side == "under"]
        if not overs or not unders:
            continue
        if len({o.book for o in group}) < 2:
            continue

        for over_o, under_o in product(overs, unders):
            if over_o.book == under_o.book:
                continue
            edge = _edge_pct(over_o.american, under_o.american)
            if edge < MIN_EDGE_PCT - 1e-9:
                continue
            dedupe = (
                market,
                over_o.label,
                over_o.event_date,
                over_o.book,
                under_o.book,
                line,
                over_o.american,
                under_o.american,
            )
            if dedupe in seen:
                continue
            seen.add(dedupe)
            arbs.append(
                Arb(
                    market=market,
                    label=over_o.label,
                    event_date=over_o.event_date,
                    event_label=over_o.event_label,
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
