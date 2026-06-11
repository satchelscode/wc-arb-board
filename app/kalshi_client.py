"""Fetch Kalshi World Cup markets (public API, no auth required)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.config import KALSHI_API_BASE, KALSHI_MARKET_STATUS, KALSHI_SERIES_TICKERS

log = logging.getLogger(__name__)


def _parse_series_list(raw: str) -> list[str]:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


def fetch_kalshi_markets(*, series_ticker: str, status: str | None = None) -> list[dict[str, Any]]:
    base = (KALSHI_API_BASE or "").rstrip("/")
    if not base:
        return []
    status_val = (status or KALSHI_MARKET_STATUS or "open").strip()
    url = f"{base}/markets"
    params: dict[str, str | int] = {
        "series_ticker": series_ticker,
        "status": status_val,
        "limit": 1000,
    }
    out: list[dict[str, Any]] = []
    try:
        while True:
            response = requests.get(
                url,
                params=params,
                timeout=35,
                headers={"User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)"},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                break
            batch = payload.get("markets")
            if isinstance(batch, list):
                for market in batch:
                    if not isinstance(market, dict):
                        continue
                    if not market.get("series_ticker"):
                        market = {**market, "series_ticker": series_ticker}
                    out.append(market)
            cursor = str(payload.get("cursor") or "").strip()
            if not cursor:
                break
            params["cursor"] = cursor
    except (requests.RequestException, ValueError) as exc:
        log.warning("Kalshi markets fetch failed (%s): %s", series_ticker, exc)
    return out


def fetch_all_kalshi_wc_markets() -> list[dict[str, Any]]:
    series_list = _parse_series_list(KALSHI_SERIES_TICKERS)
    if not series_list:
        return []
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for series in series_list:
        for market in fetch_kalshi_markets(series_ticker=series):
            ticker = str(market.get("ticker") or "")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            merged.append(market)
    log.info(
        "Kalshi: fetched %s markets across %s series",
        len(merged),
        len(series_list),
    )
    return merged
