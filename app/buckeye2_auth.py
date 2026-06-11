"""JWT auth for Buckeye2 (kraken69.com cloud API)."""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests

from app.config import (
    BUCKEYE2_API_ORIGIN,
    BUCKEYE2_AUTH_USERID,
    BUCKEYE2_EXTRA_HEADERS_JSON,
    BUCKEYE2_LOGIN_URL,
    BUCKEYE2_PASSWORD,
    BUCKEYE2_REFERER,
    BUCKEYE2_USERNAME,
)

log = logging.getLogger(__name__)

_access_token: str | None = None
_auth_user_id: str | None = None
_token_expires_at: float = 0.0
_REFRESH_MARGIN_SEC = 120.0


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


def _token_from_login_response(data: dict[str, Any]) -> str:
    for key in ("AccessToken", "accessToken", "token", "Token", "jwt"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        return _token_from_login_response(nested)
    return ""


def _userid_from_login_response(data: dict[str, Any]) -> str:
    for key in ("UserId", "userId", "UserName", "userName", "preferred_username"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        return _userid_from_login_response(nested)
    return (BUCKEYE2_AUTH_USERID or BUCKEYE2_USERNAME or "").strip()


def _apply_extra_headers(headers: dict[str, str], *, skip_authorization: bool) -> None:
    if not BUCKEYE2_EXTRA_HEADERS_JSON:
        return
    try:
        extra = json.loads(BUCKEYE2_EXTRA_HEADERS_JSON)
        if not isinstance(extra, dict):
            return
        for key, value in extra.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if skip_authorization and key.lower() == "authorization":
                continue
            headers[key] = value
    except json.JSONDecodeError:
        log.warning("BUCKEYE2_EXTRA_HEADERS_JSON is not valid JSON")


def _login() -> bool:
    global _access_token, _auth_user_id, _token_expires_at
    if not (BUCKEYE2_USERNAME and BUCKEYE2_PASSWORD):
        return False
    url = (BUCKEYE2_LOGIN_URL or "").strip()
    if not url:
        log.warning("Buckeye2: BUCKEYE2_LOGIN_URL is not set")
        return False
    origin = (BUCKEYE2_API_ORIGIN or "https://www.kraken69.com").rstrip("/")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": (BUCKEYE2_REFERER or f"{origin}/v2/").strip(),
    }
    _apply_extra_headers(headers, skip_authorization=True)
    bodies = (
        {"userName": BUCKEYE2_USERNAME, "password": BUCKEYE2_PASSWORD},
        {"UserName": BUCKEYE2_USERNAME, "Password": BUCKEYE2_PASSWORD},
        {"username": BUCKEYE2_USERNAME, "password": BUCKEYE2_PASSWORD},
    )
    for body in bodies:
        try:
            response = requests.post(url, headers=headers, json=body, timeout=30)
            if response.status_code >= 400:
                continue
            data = response.json()
        except (requests.RequestException, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        token = _token_from_login_response(data)
        if not token:
            continue
        _access_token = token
        _auth_user_id = _userid_from_login_response(data) or BUCKEYE2_USERNAME
        exp = _jwt_exp_unix(token)
        _token_expires_at = exp if exp is not None else time.time() + 3600.0
        log.info("Buckeye2 JWT obtained (expires ~%s)", int(_token_expires_at))
        return True
    log.warning("Buckeye2 login failed — check BUCKEYE2_LOGIN_URL and credentials")
    _access_token = None
    _auth_user_id = None
    _token_expires_at = 0.0
    return False


def buckeye2_auth_headers() -> dict[str, str] | None:
    global _access_token, _auth_user_id, _token_expires_at
    now = time.time()
    if not _access_token or now >= _token_expires_at - _REFRESH_MARGIN_SEC:
        if not _login():
            if BUCKEYE2_EXTRA_HEADERS_JSON:
                try:
                    extra = json.loads(BUCKEYE2_EXTRA_HEADERS_JSON)
                    auth = extra.get("Authorization") or extra.get("authorization")
                    if isinstance(auth, str) and auth.strip():
                        origin = (BUCKEYE2_API_ORIGIN or "https://www.kraken69.com").rstrip("/")
                        headers = {
                            "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
                            "Accept": "application/json, text/plain, */*",
                            "Content-Type": "application/json",
                            "Origin": origin,
                            "Referer": (BUCKEYE2_REFERER or f"{origin}/v2/").strip(),
                            "Authorization": auth.strip(),
                        }
                        user_id = (
                            BUCKEYE2_AUTH_USERID
                            or extra.get("X-Auth-Userid")
                            or BUCKEYE2_USERNAME
                        )
                        if user_id:
                            headers["X-Auth-Userid"] = str(user_id).strip()
                        return headers
                except json.JSONDecodeError:
                    pass
            return None
    origin = (BUCKEYE2_API_ORIGIN or "https://www.kraken69.com").rstrip("/")
    user_id = (BUCKEYE2_AUTH_USERID or _auth_user_id or BUCKEYE2_USERNAME or "").strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": (BUCKEYE2_REFERER or f"{origin}/v2/").strip(),
        "Authorization": f"Bearer {_access_token}",
    }
    if user_id:
        headers["X-Auth-Userid"] = user_id
    _apply_extra_headers(headers, skip_authorization=True)
    return headers
