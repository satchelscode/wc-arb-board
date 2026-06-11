"""Tests for prop cross-book diagnostics."""

from app.arb_engine import Offer
from app.prop_diagnostics import summarize_prop_cross_book


def test_btts_cross_book_detected_without_arb_threshold():
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
        Offer(
            book="fanduel",
            market="props",
            label="Both teams to score",
            event_date="2026-06-11",
            event_label="Czechia vs Korea Republic",
            participant="Yes",
            matchup=matchup,
            line=0.0,
            side="yes",
            american=-118,
            period="game",
        ),
    ]
    summary = summarize_prop_cross_book(offers)
    assert summary["cross_book_group_count"] == 1
    assert summary["by_prop_type"]["btts_game"]["multi_book"] == 1
    assert summary["by_prop_type"]["btts_game"]["both_sides"] == 1
    assert summary["by_prop_type"]["btts_game"]["arb_ready"] == 1
    sample = summary["samples"][0]
    assert set(sample["books"]) == {"ace", "fanduel", "metallic"}
    assert summary["sharp_to_retail"]["btts_game"] == 1


def test_ht_ft_cross_book_ace_metallic_fanduel():
    matchup = ("czechia", "korea republic")
    selection = "South Korea/Czech Republic"
    offers = [
        Offer(
            book="fanduel",
            market="props",
            label="Halftime and Full Time",
            event_date="2026-06-11",
            event_label="Czech Republic @ South Korea",
            participant=selection,
            matchup=matchup,
            line=0.0,
            side="ml",
            american=410,
            period="game",
        ),
        Offer(
            book="ace",
            market="props",
            label="Halftime / full time — korea republic|czechia",
            event_date="2026-06-11",
            event_label="Czechia vs Korea Republic",
            participant="KOREA REPUBLIC 1H / CZECH REPUBLIC FT",
            matchup=matchup,
            line=0.0,
            side="ml",
            american=400,
            period="game",
        ),
        Offer(
            book="metallic",
            market="props",
            label="Halftime / full time — korea republic|czechia",
            event_date="2026-06-11",
            event_label="South Korea vs Czechia",
            participant="South Korea - Czech Republic",
            matchup=matchup,
            line=0.0,
            side="ml",
            american=395,
            period="game",
        ),
    ]
    summary = summarize_prop_cross_book(offers)
    assert summary["cross_book_group_count"] == 1
    assert summary["by_prop_type"]["ht_ft"]["multi_book"] == 1
    assert summary["sharp_to_retail"]["ht_ft"] == 1
