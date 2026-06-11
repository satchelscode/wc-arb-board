"""Parse Buckeye2 (kraken69.com) Get_LeagueLines2 JSON."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.events import matchup_key
from app.names import display_team_name, team_norm

_ET = ZoneInfo("America/New_York")
_CT = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class BuckeyeLine:
    team: str
    opponent: str
    event_date: str
    market: str
    line: float
    over_price: int | None
    under_price: int | None


def _american(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None


def _point(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    return None


def _game_date_et(row: dict[str, Any]) -> str:
    raw = str(row.get("GameDateTime") or row.get("ScheduleDate") or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_CT)
        return dt.astimezone(_ET).date().isoformat()
    except ValueError:
        if len(raw) >= 10 and raw[4] == "-":
            return raw[:10]
    return ""


def _team_name(row: dict[str, Any], *, side: int) -> str:
    short_key = f"ShortName{side}"
    id_key = f"Team{side}ID"
    short = row.get(short_key)
    if isinstance(short, str) and short.strip():
        return short.strip()
    full = row.get(id_key)
    if isinstance(full, str) and full.strip():
        return full.strip()
    return ""


def _is_wc_row(row: dict[str, Any]) -> bool:
    subtype = str(row.get("SportSubType") or "").strip().upper()
    display = str(row.get("SportSubTypeDisplay") or "").strip().upper()
    if "WORLD CUP" in subtype or "WORLD CUP" in display:
        return True
    comments = str(row.get("Comments") or "").strip().upper()
    return "WORLD CUP" in comments


def _add_line(
    bucket: dict[tuple[str, str, str, str, float], BuckeyeLine],
    *,
    team: str,
    opponent: str,
    event_date: str,
    market: str,
    line: float,
    over_price: int | None,
    under_price: int | None,
) -> None:
    if not team or not event_date or over_price is None and under_price is None:
        return
    if market == "team_totals":
        key = (
            team_norm(team),
            team_norm(opponent),
            event_date,
            market,
            round(line, 2),
        )
    else:
        mk = matchup_key(team, opponent)
        key = (mk[0], mk[1], event_date, market, round(line, 2))
    row = BuckeyeLine(
        team=display_team_name(team),
        opponent=display_team_name(opponent),
        event_date=event_date,
        market=market,
        line=round(line, 2),
        over_price=over_price,
        under_price=under_price,
    )
    prev = bucket.get(key)
    if prev is None:
        bucket[key] = row
        return
    over = prev.over_price
    if over_price is not None:
        over = over_price if over is None else max(over, over_price)
    under = prev.under_price
    if under_price is not None:
        under = under_price if under is None else max(under, under_price)
    bucket[key] = BuckeyeLine(
        team=prev.team,
        opponent=prev.opponent,
        event_date=prev.event_date,
        market=prev.market,
        line=prev.line,
        over_price=over,
        under_price=under,
    )


def extract_wc_lines_from_buckeye2(payload: Any) -> list[BuckeyeLine]:
    if not isinstance(payload, dict):
        return []
    lines_raw = payload.get("Lines")
    if not isinstance(lines_raw, list):
        return []
    bucket: dict[tuple[str, str, str, str, float], BuckeyeLine] = {}
    for row in lines_raw:
        if not isinstance(row, dict):
            continue
        if not _is_wc_row(row):
            continue
        if str(row.get("Status") or "").strip().upper() not in ("O", "I"):
            continue
        if int(row.get("PeriodNumber") or 0) != 0:
            continue
        event_date = _game_date_et(row)
        away = _team_name(row, side=1)
        home = _team_name(row, side=2)
        if not away or not home:
            continue

        t1_line = _point(row.get("Team1TotalPoints"))
        if t1_line is not None:
            _add_line(
                bucket,
                team=away,
                opponent=home,
                event_date=event_date,
                market="team_totals",
                line=t1_line,
                over_price=_american(row.get("Team1TtlPtsAdj1")),
                under_price=_american(row.get("Team1TtlPtsAdj2")),
            )
        t2_line = _point(row.get("Team2TotalPoints"))
        if t2_line is not None:
            _add_line(
                bucket,
                team=home,
                opponent=away,
                event_date=event_date,
                market="team_totals",
                line=t2_line,
                over_price=_american(row.get("Team2TtlPtsAdj1")),
                under_price=_american(row.get("Team2TtlPtsAdj2")),
            )

        game_line = _point(row.get("TotalPoints"))
        if game_line is not None:
            _add_line(
                bucket,
                team=away,
                opponent=home,
                event_date=event_date,
                market="totals",
                line=game_line,
                over_price=_american(row.get("TtlPtsAdj1")),
                under_price=_american(row.get("TtlPtsAdj2")),
            )
    return list(bucket.values())
