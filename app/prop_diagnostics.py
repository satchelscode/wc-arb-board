"""Summarize cross-book prop grouping for operational verification."""

from __future__ import annotations

from collections import defaultdict
from itertools import product
from typing import Any

from app.arb_engine import Offer, dedupe_offers, group_key, implied_prob_american
from app.names import display_team_name
from app.prop_keys import binary_side_from_offer


def _prop_type_from_subject(subject: str) -> str:
    parts = (subject or "").split(":", 2)
    return parts[1] if len(parts) >= 2 else "unknown"


def _matchup_label(matchup: tuple[str, str]) -> str:
    left, right = matchup
    if left and right and left != right:
        return f"{display_team_name(left)} vs {display_team_name(right)}"
    return display_team_name(left or right)


def _best_by_book(offers: list[Offer]) -> dict[str, Offer]:
    best: dict[str, Offer] = {}
    for offer in offers:
        prev = best.get(offer.book)
        if prev is None or offer.american > prev.american:
            best[offer.book] = offer
    return best


def _edge_pct(over_price: int, under_price: int) -> float:
    total = implied_prob_american(over_price) + implied_prob_american(under_price)
    return max(0.0, (1.0 - total) * 100.0)


def summarize_prop_cross_book(
    offers: list[Offer],
    *,
    sample_limit: int = 10,
    min_edge_pct: float = 0.0,
) -> dict[str, Any]:
    """
    Report how many prop groups appear on 2+ books and whether binary sides align.

    Uses the same grouping keys as arb detection.
    """
    prop_offers = dedupe_offers([o for o in offers if o.market == "props"])
    by_group: dict[tuple[str, str, tuple[str, str], str, str, float], list[Offer]] = (
        defaultdict(list)
    )
    for offer in prop_offers:
        by_group[group_key(offer)].append(offer)

    type_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "groups": 0,
            "multi_book": 0,
            "both_sides": 0,
            "arb_ready": 0,
        }
    )
    multi_book_rows: list[dict[str, Any]] = []

    for key, group in by_group.items():
        event_date, _period, matchup, subject, _market, line = key
        ptype = _prop_type_from_subject(subject)
        type_stats[ptype]["groups"] += 1

        books = sorted({o.book for o in group})
        if len(books) < 2:
            continue
        type_stats[ptype]["multi_book"] += 1

        overs = _best_by_book(
            [
                o
                for o in group
                if (
                    binary_side_from_offer(
                        label=o.label,
                        participant=o.participant,
                        side=o.side,
                    )
                    or o.side
                )
                == "over"
            ]
        )
        unders = _best_by_book(
            [
                o
                for o in group
                if (
                    binary_side_from_offer(
                        label=o.label,
                        participant=o.participant,
                        side=o.side,
                    )
                    or o.side
                )
                == "under"
            ]
        )
        both_sides = bool(overs) and bool(unders)
        if both_sides:
            type_stats[ptype]["both_sides"] += 1

        best_edge = 0.0
        best_pair: tuple[str, str] | None = None
        if both_sides:
            for over_o, under_o in product(overs.values(), unders.values()):
                if over_o.book == under_o.book:
                    continue
                edge = _edge_pct(over_o.american, under_o.american)
                if edge > best_edge:
                    best_edge = edge
                    best_pair = (over_o.book, under_o.book)
            if best_pair and best_edge >= min_edge_pct - 1e-9:
                type_stats[ptype]["arb_ready"] += 1

        event_label = next((o.event_label for o in group if o.event_label), "")
        if not event_label:
            event_label = _matchup_label(matchup)

        row = {
            "subject": subject,
            "prop_type": ptype,
            "event_date": event_date,
            "event_label": event_label,
            "books": books,
            "book_count": len(books),
            "both_sides": both_sides,
            "best_edge_pct": round(best_edge, 3),
            "best_pair": best_pair,
            "over_prices": {b: o.american for b, o in sorted(overs.items())},
            "under_prices": {b: o.american for b, o in sorted(unders.items())},
            "ml_prices": {
                b: o.american
                for b, o in sorted(_best_by_book(group).items())
                if b not in overs and b not in unders
            }
            or {
                b: o.american
                for b, o in sorted(_best_by_book(group).items())
            },
            "line": line,
        }
        multi_book_rows.append(row)

    multi_book_rows.sort(
        key=lambda r: (-r["book_count"], -r["best_edge_pct"], r["event_label"], r["subject"])
    )

    focus_types = ("btts_game", "ht_ft", "correct_score", "first_goalscorer")
    samples = []
    for ptype in focus_types:
        for row in multi_book_rows:
            if row["prop_type"] != ptype:
                continue
            samples.append(row)
            if len(samples) >= sample_limit:
                break
        if len(samples) >= sample_limit:
            break
    if len(samples) < sample_limit:
        seen = {s["subject"] for s in samples}
        for row in multi_book_rows:
            if row["subject"] in seen:
                continue
            samples.append(row)
            seen.add(row["subject"])
            if len(samples) >= sample_limit:
                break

    sharp_books = {"ace", "metallic"}
    retail_books = {"draftkings", "fanduel", "pinnacle", "betonline", "bookmaker"}
    cross_source: dict[str, int] = defaultdict(int)
    for row in multi_book_rows:
        books = set(row["books"])
        if books & sharp_books and books & retail_books:
            cross_source[row["prop_type"]] += 1

    return {
        "prop_offer_count": len(prop_offers),
        "prop_group_count": len(by_group),
        "cross_book_group_count": len(multi_book_rows),
        "by_prop_type": dict(sorted(type_stats.items())),
        "sharp_to_retail": dict(sorted(cross_source.items())),
        "samples": samples,
    }


def format_prop_cross_book_log(summary: dict[str, Any]) -> str:
    parts = [
        f"props={summary.get('prop_offer_count', 0)}",
        f"groups={summary.get('prop_group_count', 0)}",
        f"cross_book={summary.get('cross_book_group_count', 0)}",
    ]
    for ptype, stats in (summary.get("by_prop_type") or {}).items():
        if stats.get("multi_book", 0) <= 0:
            continue
        parts.append(
            f"{ptype}={stats['multi_book']}/{stats['groups']}"
            f"(both_sides={stats.get('both_sides', 0)},"
            f" arb_ready={stats.get('arb_ready', 0)})"
        )
    sharp = summary.get("sharp_to_retail") or {}
    if sharp:
        parts.append(
            "sharp↔retail="
            + ",".join(f"{k}:{v}" for k, v in sorted(sharp.items()))
        )
    return "Prop cross-book: " + ", ".join(parts)
