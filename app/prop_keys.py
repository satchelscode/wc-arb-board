"""
Cross-book WC soccer prop matching (Metallic/Steam22 <-> ACE/Falcon).

Per-fixture market inventory
------------------------------

| Canonical type     | Metallic (Steam22)                         | ACE (Falcon)                 | Cross-book |
|--------------------|---------------------------------------------|------------------------------|------------|
| btts_game          | Both teams to score - 90min + Injury time   | BOTH TEAMS TO SCR            | yes        |
| btts_1h            | Both teams to score in the 1st half         | —                            | no         |
| team_score_game    | {Team} to score - 90min + Injury time       | —                            | no         |
| team_score_1h      | {Team} to score in the 1st half             | —                            | no         |
| ht_ft              | Halftime and Full Time exact result         | HALF TIME/FULL TIME          | yes*       |
|                    |                                             | Odds API: halftime_fulltime  | (FanDuel+) |
| btts_game          | (see above)                                 | Odds API: btts               | (DK/FD/Pin)|
| correct_score      | Correct Score                               | CORRECT SCORE                | yes*       |
| first_goalscorer   | First Goalscorer                            | 1ST GOALSCORER               | yes*       |
| anytime_scorer     | {Player} to score a goal - 90min            | ANYTIME GOALSCORER           | partial    |
| team_score_first   | —                                           | TEAM TO SCR FIRST            | ace only   |
| first_goal_time    | —                                           | TIME 1ST GOAL BRACKETS       | ace only   |
| draw_no_bet        | —                                           | DRAW NO BET                  | ace only   |
| margin             | —                                           | MARGIN OF VICTORY            | ace only   |
| half_most_goals    | —                                           | HALF WITH MOST GOALS         | ace only   |

*Multi-outcome ML markets: matched per selection (not yes/no arbs).

Binary props (btts, team score, player anytime yes/no) arb as over=yes vs under=no.
"""

from __future__ import annotations

import re
from typing import Literal

from app.names import WC_TEAM_ALIASES, normalize_name, team_norm

PropType = Literal[
    "btts_game",
    "btts_1h",
    "team_score_game",
    "team_score_1h",
    "ht_ft",
    "correct_score",
    "first_goalscorer",
    "anytime_scorer",
    "team_score_first",
    "first_goal_time",
    "draw_no_bet",
    "margin",
    "half_most_goals",
    "unknown",
]

_HALF_RE = re.compile(r"\b(1st\s*half|first\s*half|1h\b|in\s*1st)\b", re.I)
_BTTS_RE = re.compile(r"\b(both\s+teams?\s+to\s+score|both\s+teams?\s+to\s+scr)\b", re.I)
_TEAM_SCORE_RE = re.compile(
    r"\b(.+?)\s+to\s+score(?:\s+a\s+goal)?(?:\s+-\s*90|\s+-\s*90|\s+in\s+the\s+1st)",
    re.I,
)
_HT_FT_RE = re.compile(
    r"\b(halftime\s+and\s+full\s*time|half\s*time\s*/?\s*full\s*time|ht\s*/?\s*ft)\b",
    re.I,
)
_CORRECT_SCORE_RE = re.compile(r"\bcorrect\s+score\b", re.I)
_FIRST_GS_RE = re.compile(r"\b(1st\s+goalscorer|first\s+goalscorer)\b", re.I)
_ANYTIME_GS_RE = re.compile(r"\banytime\s+goalscorer\b", re.I)
_TEAM_FIRST_RE = re.compile(r"\bteam\s+to\s+scr(?:ore)?\s+first\b", re.I)
_GOAL_TIME_RE = re.compile(r"\btime\s+(?:of\s+)?1st\s+goal\b", re.I)
_DNB_RE = re.compile(r"\bdraw\s+no\s+bet\b", re.I)
_MARGIN_RE = re.compile(r"\bmargin\s+of\s+victory\b", re.I)
_HALF_MOST_RE = re.compile(r"\bhalf\s+with\s+most\s+goals\b", re.I)

_SCORE_PAIR_RE = re.compile(
    r"(\d+)\s*[,/-]\s*(\d+)|(\d+)\s*-\s*(\d+)",
    re.I,
)
_HT_FT_SEL_RE = re.compile(
    r"^(?P<h>.+?)\s*[-/]\s*(?P<f>.+)$",
    re.I,
)
_HT_FT_ACE_RE = re.compile(
    r"^(?P<h>.+?)\s+1h\s*/\s*(?P<f>.+?)\s+ft$",
    re.I,
)

_YES_TOKENS = frozenset({"yes", "y"})
_NO_TOKENS = frozenset({"no", "n"})


def strip_fixture_prefix(text: str) -> str:
    """
    Strip fixture prefix from prop headers.

    ACE: 'CZECHIA/KOREA REPUBLIC - BOTH TEAMS TO SCR'
    Metallic: 'South Korea vs Czechia - Both teams to score - 90min + Injury time'
    """
    raw = (text or "").strip()
    if " - " not in raw:
        return raw
    head, tail = raw.split(" - ", 1)
    head_l = head.lower()
    if "/" in head or " vs " in head_l:
        return tail.strip()
    return raw


def prop_period_from_text(*parts: str) -> str:
    blob = " ".join(strip_fixture_prefix(p) for p in parts if p).lower()
    if _HALF_RE.search(blob):
        return "1h"
    return "game"


def detect_prop_type(*parts: str) -> PropType:
    blob = " ".join(strip_fixture_prefix(p) for p in parts if p)
    lower = blob.lower()

    if _BTTS_RE.search(lower):
        return "btts_1h" if prop_period_from_text(blob) == "1h" else "btts_game"
    if _TEAM_SCORE_RE.search(lower) and "both teams" not in lower:
        return "team_score_1h" if prop_period_from_text(blob) == "1h" else "team_score_game"
    if _HT_FT_RE.search(lower):
        return "ht_ft"
    if _CORRECT_SCORE_RE.search(lower):
        return "correct_score"
    if _FIRST_GS_RE.search(lower):
        return "first_goalscorer"
    if _ANYTIME_GS_RE.search(lower):
        return "anytime_scorer"
    if _TEAM_FIRST_RE.search(lower):
        return "team_score_first"
    if _GOAL_TIME_RE.search(lower):
        return "first_goal_time"
    if _DNB_RE.search(lower):
        return "draw_no_bet"
    if _MARGIN_RE.search(lower):
        return "margin"
    if _HALF_MOST_RE.search(lower):
        return "half_most_goals"
    return "unknown"


def _strip_yes_no_suffix(text: str) -> tuple[str, str | None]:
    raw = (text or "").strip()
    norm = normalize_name(raw)
    for sep in (" / ", "/", " - "):
        if sep in raw:
            left, right = raw.rsplit(sep, 1)
            side = yes_no_side(right)
            if side:
                return left.strip(), side
    tokens = norm.split()
    if tokens and tokens[-1] in _YES_TOKENS | _NO_TOKENS:
        side = "yes" if tokens[-1] in _YES_TOKENS else "no"
        return " ".join(tokens[:-1]), side
    if norm in _YES_TOKENS:
        return "", "yes"
    if norm in _NO_TOKENS:
        return "", "no"
    if norm.endswith(" yes"):
        return norm[:-4].strip(), "yes"
    if norm.endswith(" no"):
        return norm[:-3].strip(), "no"
    return raw, None


def yes_no_side(text: str) -> str | None:
    norm = normalize_name(text)
    if not norm:
        return None
    if norm in _YES_TOKENS or norm.endswith(" yes") or "/ yes" in norm:
        return "yes"
    if norm in _NO_TOKENS or norm.endswith(" no") or "/ no" in norm:
        return "no"
    if "scores in 1sth" in norm or norm == "scores":
        return None
    return None


def binary_side_from_offer(
    *,
    label: str,
    participant: str,
    side: str,
) -> str | None:
    """Map yes/no props to over (yes) or under (no) for arb pairing."""
    if side in ("over", "under"):
        return side
    for text in (participant, label):
        yn = yes_no_side(text)
        if yn == "yes":
            return "over"
        if yn == "no":
            return "under"
    if side == "ml":
        yn = yes_no_side(participant) or yes_no_side(label)
        if yn == "yes":
            return "over"
        if yn == "no":
            return "under"
    return None


def _canonical_team_norm(name: str) -> str:
    n = team_norm(name)
    if not n:
        return normalize_name(name)
    for canonical, aliases in WC_TEAM_ALIASES.items():
        if n in aliases:
            return canonical
    return n


def _normalize_team_token(name: str) -> str:
    return _canonical_team_norm(name)


def _ht_ft_part(token: str) -> str:
    if (token or "").strip().lower() == "draw":
        return "draw"
    return _normalize_team_token(token)


def _normalize_ht_ft_selection(selection: str) -> str:
    raw = (selection or "").strip()
    m = _HT_FT_ACE_RE.match(raw)
    if m:
        h = _ht_ft_part(m.group("h"))
        f = _ht_ft_part(m.group("f"))
        return f"{h}|{f}"
    m = _HT_FT_SEL_RE.match(raw)
    if m:
        h = _ht_ft_part(m.group("h"))
        f = _ht_ft_part(m.group("f"))
        return f"{h}|{f}"
    return normalize_name(raw)


def _normalize_score_selection(
    selection: str,
    *,
    matchup: tuple[str, str] = ("", ""),
) -> str:
    raw = (selection or "").strip()
    lower = raw.lower()
    if lower.startswith("draw "):
        m = re.search(r"(\d+)\s*[-/]\s*(\d+)", raw)
        if m:
            return f"draw:{m.group(1)}-{m.group(2)}"

    # Metallic: "South Korea 1, Czechia 0"
    m = re.match(
        r"^(?P<team_a>.+?)\s+(?P<a>\d+)\s*,\s*(?P<team_b>.+?)\s+(?P<b>\d+)\s*$",
        raw,
        re.I,
    )
    if m:
        ta = _normalize_team_token(m.group("team_a"))
        tb = _normalize_team_token(m.group("team_b"))
        a, b = int(m.group("a")), int(m.group("b"))
        return f"{ta}:{a}|{tb}:{b}"

    # ACE: "KOREA REPUBLIC 1-0" or "DRAW 1-1"
    m = re.match(r"^(?P<team>.+?)\s+(?P<a>\d+)\s*-\s*(?P<b>\d+)\s*$", raw, re.I)
    if m:
        team = m.group("team").strip()
        a, b = int(m.group("a")), int(m.group("b"))
        if team.lower().startswith("draw"):
            return f"draw:{a}-{b}"
        ta = _normalize_team_token(team)
        left, right = matchup
        if left and right:
            tb = _normalize_team_token(right if ta == _normalize_team_token(left) else left)
            return f"{ta}:{a}|{tb}:{b}"
        return f"{ta}:{a}-{b}"

    m = _SCORE_PAIR_RE.search(raw)
    if m:
        a = m.group(1) or m.group(3)
        b = m.group(2) or m.group(4)
        if a and b:
            return f"{a}-{b}"
    return normalize_name(raw)


def _normalize_player_selection(selection: str) -> str:
    norm = normalize_name(selection)
    # Align "heung min son" with "son heung min" via sorted tokens when 2+ words.
    parts = [p for p in norm.split() if p not in {"jr", "sr"}]
    if len(parts) >= 2:
        return " ".join(sorted(parts))
    return norm


def _team_from_score_prop(prop_detail: str) -> str:
    m = _TEAM_SCORE_RE.search(prop_detail or "")
    if not m:
        return ""
    team = m.group(1).strip()
    if team.lower().startswith("both teams"):
        return ""
    return _normalize_team_token(team)


def prop_selection_key(
    *,
    prop_type: PropType,
    label: str,
    participant: str,
    prop_detail: str = "",
    matchup: tuple[str, str] = ("", ""),
) -> str:
    """Normalized selection within a prop market (empty for pure yes/no markets)."""
    if prop_type in ("btts_game", "btts_1h"):
        return "both"
    if prop_type in ("team_score_game", "team_score_1h"):
        team = _team_from_score_prop(prop_detail) or _team_from_score_prop(label)
        if not team:
            team = _normalize_team_token(participant)
        return team or "team"
    if prop_type == "ht_ft":
        sel = participant or label
        _, yn = _strip_yes_no_suffix(sel)
        if yn:
            sel = _
        return _normalize_ht_ft_selection(sel)
    if prop_type == "correct_score":
        sel = participant or label
        return _normalize_score_selection(sel, matchup=matchup)
    if prop_type in ("first_goalscorer", "anytime_scorer"):
        sel = participant or label
        base, yn = _strip_yes_no_suffix(sel)
        if yn:
            return f"{_normalize_player_selection(base)}:{yn}"
        return _normalize_player_selection(sel)
    if prop_type == "team_score_first":
        return _normalize_team_token(participant) or normalize_name(participant)
    if prop_type == "first_goal_time":
        return normalize_name(participant or label)
    if prop_type == "draw_no_bet":
        return _normalize_team_token(participant) or normalize_name(participant)
    if prop_type == "margin":
        return normalize_name(participant or label)
    if prop_type == "half_most_goals":
        return normalize_name(participant or label)
    return normalize_name(participant or label or prop_detail)


def prop_group_subject(
    *,
    label: str,
    participant: str,
    prop_detail: str = "",
    period: str = "game",
    matchup: tuple[str, str] = ("", ""),
) -> str:
    """
    Canonical grouping subject for cross-book prop matching.
    Format: {period}:{prop_type}[:selection]
    """
    blob_parts = [prop_detail, label, participant]
    prop_type = detect_prop_type(*blob_parts)
    if prop_type == "unknown":
        return normalize_name(label or prop_detail or participant)

    eff_period = period or prop_period_from_text(*blob_parts)
    selection = prop_selection_key(
        prop_type=prop_type,
        label=label,
        participant=participant,
        prop_detail=prop_detail,
        matchup=matchup,
    )

    binary_types = {
        "btts_game",
        "btts_1h",
        "team_score_game",
        "team_score_1h",
    }
    if prop_type in binary_types:
        return f"{eff_period}:{prop_type}"
    if prop_type == "anytime_scorer" and (
        selection.endswith(":yes") or selection.endswith(":no")
    ):
        return f"{eff_period}:{prop_type}:{selection.rsplit(':', 1)[0]}"
    if selection:
        return f"{eff_period}:{prop_type}:{selection}"
    return f"{eff_period}:{prop_type}"


def display_prop_type(prop_type: PropType) -> str:
    names = {
        "btts_game": "Both teams to score (90 min)",
        "btts_1h": "Both teams to score (1st half)",
        "team_score_game": "Team to score (90 min)",
        "team_score_1h": "Team to score (1st half)",
        "ht_ft": "Halftime / full time",
        "correct_score": "Correct score",
        "first_goalscorer": "First goalscorer",
        "anytime_scorer": "Anytime goalscorer",
        "team_score_first": "Team to score first",
        "first_goal_time": "Time of first goal",
        "draw_no_bet": "Draw no bet",
        "margin": "Margin of victory",
        "half_most_goals": "Half with most goals",
    }
    return names.get(prop_type, prop_type)
