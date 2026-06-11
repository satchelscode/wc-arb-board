"""Integration tests for cross-book prop arbs."""

from app.arb_engine import Offer, find_cross_book_arbs


def test_btts_cross_book_arb():
    matchup = ("czechia", "korea republic")
    offers = [
        Offer(
            book="metallic",
            market="props",
            label="Both teams to score (90 min)",
            event_date="2026-06-11",
            event_label="Czechia vs Korea Republic",
            participant="Both teams",
            matchup=matchup,
            line=0.0,
            side="over",
            american=-115,
            period="game",
        ),
        Offer(
            book="ace",
            market="props",
            label="Both teams to score (90 min)",
            event_date="2026-06-11",
            event_label="Czechia vs Korea Republic",
            participant="BOTH TEAMS TO SCR / NO",
            matchup=matchup,
            line=0.0,
            side="ml",
            american=130,
            period="game",
        ),
    ]
    arbs = find_cross_book_arbs(offers)
    assert len(arbs) == 1
    assert arbs[0].over_book == "metallic"
    assert arbs[0].under_book == "ace"
