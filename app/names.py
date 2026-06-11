"""Team name normalization for cross-book matching."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")
_TEAM_TOTAL_SUFFIX = re.compile(r"\s*\(TEAM TOTAL\)\s*$", re.I)

WC_TEAM_ALIASES: dict[str, frozenset[str]] = {
    "bosnia and herzegovina": frozenset({"bosnia and herzegovina", "bosnia herzegovina"}),
    "cape verde": frozenset({"cape verde", "cabo verde"}),
    "congo dr": frozenset(
        {"congo dr", "dr congo", "democratic republic of the congo", "congo democratic republic"}
    ),
    "czechia": frozenset({"czechia", "czech republic"}),
    "ir iran": frozenset({"ir iran", "iran"}),
    "ivory coast": frozenset({"ivory coast", "cote d ivoire", "cote d'ivoire"}),
    "korea republic": frozenset({"korea republic", "south korea", "republic of korea"}),
    "turkiye": frozenset({"turkiye", "turkey"}),
    "usa": frozenset({"usa", "united states", "united states of america"}),
}


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("'", " ")
    text = _NON_ALNUM.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def strip_team_total_suffix(name: str) -> str:
    return _TEAM_TOTAL_SUFFIX.sub("", (name or "").strip()).strip()


def team_norm(name: str) -> str:
    return normalize_name(strip_team_total_suffix(name))


def display_team_name(name: str) -> str:
    """Canonical display casing for team totals (e.g. jordan -> Jordan)."""
    norm = team_norm(name)
    if not norm:
        return (name or "").strip()
    return " ".join(part.capitalize() for part in norm.split())


def team_total_label(team: str, line: float) -> str:
    return f"{display_team_name(team)} team total {line:g}"


def teams_match(a: str, b: str) -> bool:
    na, nb = team_norm(a), team_norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    for aliases in WC_TEAM_ALIASES.values():
        if na in aliases and nb in aliases:
            return True
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return True
    return False
