"""Fetch Kalshi World Cup markets (public API, no auth required)."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.config import KALSHI_API_BASE, KALSHI_MARKET_STATUS, KALSHI_SERIES_TICKERS

log = logging.getLogger(__name__)

_MARKETS_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_CACHE_TTL_S = 300.0
_SERIES_PAUSE_S = 1.25
_RETRY_BACKOFF_S = (2.0, 5.0, 12.0, 25.0)
_MIN_CACHED_MARKETS = 900


def _parse_series_list(raw: str) -> list[str]:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


def _request_json(
    url: str,
    *,
    params: dict[str, str | int],
    series_ticker: str,
) -> dict[str, Any] | None:
    for attempt in range(len(_RETRY_BACKOFF_S)):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=35,
                headers={"User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)"},
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_s = float(retry_after) if retry_after else _RETRY_BACKOFF_S[attempt]
                except (TypeError, ValueError):
                    wait_s = _RETRY_BACKOFF_S[attempt]
                log.warning(
                    "Kalshi 429 for %s (attempt %s/%s), sleeping %.0fs",
                    series_ticker,
                    attempt + 1,
                    len(_RETRY_BACKOFF_S),
                    wait_s,
                )
                time.sleep(wait_s)
                continue
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return None
        except (requests.RequestException, ValueError) as exc:
            if attempt + 1 < len(_RETRY_BACKOFF_S):
                wait_s = _RETRY_BACKOFF_S[attempt]
                log.warning(
                    "Kalshi request failed for %s (attempt %s/%s): %s",
                    series_ticker,
                    attempt + 1,
                    len(_RETRY_BACKOFF_S),
                    exc,
                )
                time.sleep(wait_s)
                continue
            log.warning("Kalshi markets fetch failed (%s): %s", series_ticker, exc)
            return None
    log.warning("Kalshi markets fetch exhausted retries (%s)", series_ticker)
    return None


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
    while True:
        payload = _request_json(url, params=params, series_ticker=series_ticker)
        if payload is None:
            break
        batch = payload.get("markets")
        if isinstance(batch, list):
            for market in batch:
                if not isinstance(market, dict):
                    continue
                stamped = market
                if not stamped.get("series_ticker"):
                    stamped = {**market, "series_ticker": series_ticker}
                out.append(stamped)
        cursor = str(payload.get("cursor") or "").strip()
        if not cursor:
            break
        params["cursor"] = cursor
        time.sleep(0.35)
    return out


def _fetch_all_uncached() -> list[dict[str, Any]]:
    series_list = _parse_series_list(KALSHI_SERIES_TICKERS)
    if not series_list:
        return []
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for idx, series in enumerate(series_list):
        if idx:
            time.sleep(_SERIES_PAUSE_S)
        batch = fetch_kalshi_markets(series_ticker=series)
        for market in batch:
            ticker = str(market.get("ticker") or "")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            merged.append(market)
    return merged


def fetch_all_kalshi_wc_markets() -> list[dict[str, Any]]:
    global _MARKETS_CACHE

    now = time.monotonic()
    cached: list[dict[str, Any]] | None = None
    if _MARKETS_CACHE is not None:
        cached_at, cached = _MARKETS_CACHE
        if now - cached_at < _CACHE_TTL_S and len(cached) >= _MIN_CACHED_MARKETS:
            return cached

    merged = _fetch_all_uncached()
    series_count = len(_parse_series_list(KALSHI_SERIES_TICKERS))
    log.info(
        "Kalshi: fetched %s markets across %s series",
        len(merged),
        series_count,
    )

    if len(merged) >= _MIN_CACHED_MARKETS:
        _MARKETS_CACHE = (time.monotonic(), merged)
        return merged

    if cached and len(cached) > len(merged):
        log.warning(
            "Kalshi: reusing cached markets (%s) after partial fetch (%s)",
            len(cached),
            len(merged),
        )
        return cached

    if merged:
        _MARKETS_CACHE = (time.monotonic(), merged)
    return merged
