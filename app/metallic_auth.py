"""JWT auth for Metallic (Steam22 player API at steam22.com)."""

from __future__ import annotations

import base64
import json
import logging
import time

import requests

from app.config import (
    METALLIC_EXTRA_HEADERS_JSON,
    METALLIC_JS_VERSION,
    METALLIC_LOGIN_URL,
    METALLIC_LOGIN_WEBSITE,
    METALLIC_PASSWORD,
    METALLIC_REFERER,
    METALLIC_RENEW_URL,
    METALLIC_USERNAME,
)

log = logging.getLogger(__name__)

_access_token: str | None = None
_token_expires_at: float = 0.0
_REFRESH_MARGIN_SEC = 120.0
_RENEW_WHEN_REMAINING_SEC = 600.0


def _jwt_exp_unix(token: str) -> float | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        pad = (-len(payload_b64)) % 4
        payload_b64 += "=" * pad
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return float(exp)
    except (ValueError, TypeError, json.JSONDecodeError, OSError):
        return None
    return None


def _parse_login_expiration(data: dict, token: str) -> float:
    raw = data.get("ExpirationEpoch")
    if isinstance(raw, (int, float)) and float(raw) > 0:
        exp = float(raw)
        if exp > 1e12:
            exp /= 1000.0
        return exp
    jwt_exp = _jwt_exp_unix(token)
    if jwt_exp is not None:
        return jwt_exp
    return time.time() + 3600.0


def _apply_extra_headers(headers: dict[str, str], *, skip_authorization: bool) -> None:
    if not METALLIC_EXTRA_HEADERS_JSON:
        return
    try:
        extra = json.loads(METALLIC_EXTRA_HEADERS_JSON)
        if not isinstance(extra, dict):
            return
        for key, value in extra.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if skip_authorization and key.lower() == "authorization":
                continue
            headers[key] = value
    except json.JSONDecodeError:
        log.warning("METALLIC_EXTRA_HEADERS_JSON is not valid JSON")


def _login() -> bool:
    global _access_token, _token_expires_at
    if not (METALLIC_USERNAME and METALLIC_PASSWORD):
        return False
    url = METALLIC_LOGIN_URL or "https://steam22.com/player-api/identity/customerLogin/"
    body = {
        "userName": METALLIC_USERNAME,
        "password": METALLIC_PASSWORD,
        "website": METALLIC_LOGIN_WEBSITE or "steam22.com",
        "version": METALLIC_JS_VERSION or "1.3.47",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://steam22.com",
        "Referer": (METALLIC_REFERER or "https://steam22.com/v2/").strip(),
    }
    _apply_extra_headers(headers, skip_authorization=True)
    try:
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Metallic customerLogin failed: %s", exc)
        _access_token = None
        _token_expires_at = 0.0
        return False
    if not isinstance(data, dict):
        return False
    token = (data.get("AccessToken") or data.get("accessToken") or "").strip()
    if not token:
        err = (data.get("ErrorMessage") or data.get("errorMessage") or "").strip()
        log.warning("Metallic customerLogin: no token (%s)", err[:120])
        return False
    _access_token = token
    _token_expires_at = _parse_login_expiration(data, token)
    log.info("Metallic JWT obtained (expires ~%s)", int(_token_expires_at))
    return True


def _renew() -> bool:
    global _access_token, _token_expires_at
    if not _access_token:
        return False
    url = (METALLIC_RENEW_URL or "https://steam22.com/player-api/identity/renewToken").rstrip("/")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {_access_token}",
        "Origin": "https://steam22.com",
        "Referer": (METALLIC_REFERER or "https://steam22.com/v2/").strip(),
    }
    _apply_extra_headers(headers, skip_authorization=True)
    try:
        response = requests.post(url, headers=headers, data=b"", timeout=25)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.debug("Metallic renewToken failed: %s", exc)
        return False
    if not isinstance(data, dict):
        return False
    token = (data.get("AccessToken") or data.get("accessToken") or "").strip()
    if not token:
        return False
    _access_token = token
    _token_expires_at = _parse_login_expiration(data, token)
    return True


def metallic_access_token() -> str | None:
    global _access_token, _token_expires_at
    if not (METALLIC_USERNAME and METALLIC_PASSWORD):
        return None
    now = time.time()
    if _access_token and now < _token_expires_at - _REFRESH_MARGIN_SEC:
        remaining = _token_expires_at - now
        if remaining < _RENEW_WHEN_REMAINING_SEC and _renew():
            return _access_token
        return _access_token
    if _access_token and _renew():
        return _access_token
    if _login():
        return _access_token
    return None
