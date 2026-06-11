"""Tests for cross-book prop market matching."""

from app.prop_keys import (
    binary_side_from_offer,
    detect_prop_type,
    prop_group_subject,
    prop_selection_key,
    strip_fixture_prefix,
)


def test_strip_fixture_prefix_ace_header():
    assert (
        strip_fixture_prefix("CZECHIA/KOREA REPUBLIC - BOTH TEAMS TO SCR")
        == "BOTH TEAMS TO SCR"
    )


def test_detect_btts_game_metallic_and_ace():
    assert detect_prop_type(
        "South Korea vs Czechia - Both teams to score - 90min + Injury time"
    ) == "btts_game"
    assert detect_prop_type("CZECHIA/KOREA REPUBLIC - BOTH TEAMS TO SCR") == "btts_game"


def test_detect_btts_1h_metallic_only():
    assert (
        detect_prop_type("South Korea vs Czechia - Both teams to score in the 1st half")
        == "btts_1h"
    )


def test_btts_cross_book_group_subject():
    met = prop_group_subject(
        label="Both teams to score - 90min + Injury time",
        participant="Both teams",
        prop_detail="Both teams to score - 90min + Injury time",
        period="game",
    )
    ace = prop_group_subject(
        label="BOTH TEAMS TO SCR",
        participant="BOTH TEAMS TO SCR / YES",
        prop_detail="CZECHIA/KOREA REPUBLIC - BOTH TEAMS TO SCR",
        period="game",
    )
    assert met == ace == "game:btts_game"


def test_binary_side_ace_yes_no():
    assert (
        binary_side_from_offer(
            label="BOTH TEAMS TO SCR",
            participant="BOTH TEAMS TO SCR / YES",
            side="ml",
        )
        == "over"
    )
    assert (
        binary_side_from_offer(
            label="BOTH TEAMS TO SCR",
            participant="BOTH TEAMS TO SCR / NO",
            side="ml",
        )
        == "under"
    )


def test_ht_ft_selection_normalization():
    met_sel = prop_selection_key(
        prop_type="ht_ft",
        label="South Korea - Draw",
        participant="South Korea - Draw",
        prop_detail="Halftime and Full Time exact result",
    )
    ace_sel = prop_selection_key(
        prop_type="ht_ft",
        label="KOREA REPUBLIC 1H / DRAW FT",
        participant="KOREA REPUBLIC 1H / DRAW FT",
        prop_detail="HALF TIME/FULL TIME",
    )
    assert met_sel == ace_sel


def test_ht_ft_odds_api_fanduel_format():
    api_sel = prop_selection_key(
        prop_type="ht_ft",
        label="Halftime and Full Time",
        participant="South Korea/Czech Republic",
        prop_detail="halftime_fulltime",
    )
    ace_sel = prop_selection_key(
        prop_type="ht_ft",
        label="SOUTH KOREA 1H / CZECH REPUBLIC FT",
        participant="SOUTH KOREA 1H / CZECH REPUBLIC FT",
        prop_detail="HALF TIME/FULL TIME",
    )
    assert api_sel == ace_sel


def test_btts_odds_api_group_and_side():
    assert (
        prop_group_subject(
            label="Both teams to score",
            participant="Yes",
            prop_detail="Both teams to score",
            period="game",
        )
        == "game:btts_game"
    )
    assert (
        binary_side_from_offer(
            label="Both teams to score",
            participant="No",
            side="no",
        )
        == "under"
    )


def test_correct_score_normalization():
    matchup = ("czechia", "korea republic")
    met = prop_selection_key(
        prop_type="correct_score",
        label="South Korea 1, Czechia 0",
        participant="South Korea 1, Czechia 0",
        prop_detail="Correct Score",
        matchup=matchup,
    )
    ace = prop_selection_key(
        prop_type="correct_score",
        label="KOREA REPUBLIC 1-0",
        participant="KOREA REPUBLIC 1-0",
        prop_detail="CORRECT SCORE",
        matchup=matchup,
    )
    assert met == ace == "korea republic:1|czechia:0"


def test_first_goalscorer_player_normalization():
    met = prop_selection_key(
        prop_type="first_goalscorer",
        label="Son Heung-Min",
        participant="Son Heung-Min",
        prop_detail="First Goalscorer",
    )
    ace = prop_selection_key(
        prop_type="first_goalscorer",
        label="HEUNG-MIN SON",
        participant="HEUNG-MIN SON",
        prop_detail="1ST GOALSCORER",
    )
    assert met == ace
