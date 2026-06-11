"""Event identity helpers — match offers to the same fixture across books."""

from __future__ import annotations

from app.names import display_team_name, team_norm, teams_match


def matchup_key(team_a: str, team_b: str) -> tuple[str, str]:
    """Sorted normalized pair identifying a fixture (home/away order ignored)."""
    a, b = team_norm(team_a), team_norm(team_b)
    if not a and not b:
        return ("", "")
    if not b:
        return (a, a)
    if not a:
        return (b, b)
    return tuple(sorted((a, b)))


def matchup_label(team_a: str, team_b: str) -> str:
    a, b = team_norm(team_a), team_norm(team_b)
    if not a and not b:
        return ""
    if not b or a == b:
        return display_team_name(team_a or team_b)
    left, right = sorted((display_team_name(team_a), display_team_name(team_b)))
    return f"{left} vs {right}"


def opponent_in_event(*, home: str, away: str, team: str) -> str:
    if teams_match(team, home):
        return away
    if teams_match(team, away):
        return home
    return ""
