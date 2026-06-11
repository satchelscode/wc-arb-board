"""JWT auth for Buckeye2 (kraken69.com cloud API)."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import (
    BUCKEYE2_API_ORIGIN,
    BUCKEYE2_AUTH_USERID,
    BUCKEYE2_BEARER_TOKEN,
    BUCKEYE2_DOMAIN,
    BUCKEYE2_EXTRA_HEADERS_JSON,
    BUCKEYE2_LOGIN_POST_BODY,
    BUCKEYE2_LOGIN_URL,
    BUCKEYE2_PASSWORD,
    BUCKEYE2_REFERER,
    BUCKEYE2_RENEW_URL,
    BUCKEYE2_USERNAME,
)

log = logging.getLogger(__name__)

_access_token: str | None = None
_auth_user_id: str | None = None
_token_expires_at: float = 0.0
_REFRESH_MARGIN_SEC = 120.0
_RENEW_WHEN_REMAINING_SEC = 600.0
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


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


def _strip_bearer(token: str) -> str:
    raw = (token or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _token_from_login_response(data: dict[str, Any]) -> str:
    for key in ("code", "AccessToken", "accessToken", "token", "Token", "jwt"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = data.get("data")
    if isinstance(nested, dict):
        return _token_from_login_response(nested)
    return ""


def _userid_from_login_response(data: dict[str, Any]) -> str:
    account = data.get("accountInfo")
    if isinstance(account, dict):
        for key in ("customerID", "CustomerID", "userId", "UserId"):
            val = account.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for key in ("UserId", "userId", "UserName", "userName", "customerID", "CustomerID"):
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


def _base_headers(*, with_auth: bool = False) -> dict[str, str]:
    origin = (BUCKEYE2_API_ORIGIN or "https://www.kraken69.com").rstrip("/")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Origin": origin,
        "Referer": (BUCKEYE2_REFERER or f"{origin}/").strip(),
    }
    if with_auth and _access_token:
        headers["Authorization"] = f"Bearer {_access_token}"
    _apply_extra_headers(headers, skip_authorization=not with_auth)
    return headers


def _domain_name() -> str:
    explicit = (BUCKEYE2_DOMAIN or "").strip()
    if explicit:
        return explicit.replace("www.", "")
    origin = (BUCKEYE2_API_ORIGIN or "https://www.kraken69.com").strip()
    host = urlparse(origin).hostname or "kraken69.com"
    return host.replace("www.", "")


def _login_bodies() -> list[dict[str, Any]]:
    raw = (BUCKEYE2_LOGIN_POST_BODY or "").strip()
    if raw and raw not in ("", "{}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            log.warning("BUCKEYE2_LOGIN_POST_BODY is not valid JSON; using default")

    customer = (BUCKEYE2_USERNAME or "").strip().upper()
    password = (BUCKEYE2_PASSWORD or "").strip().upper()
    domain = _domain_name()
    return [
        {
            "customerID": customer,
            "state": True,
            "password": password,
            "multiaccount": 1,
            "response_type": "code",
            "client_id": customer,
            "domain": domain,
            "redirect_uri": domain,
            "operation": "authenticateCustomer",
            "RRO": 1,
        }
    ]


def _parse_login_response(response: requests.Response) -> dict[str, Any] | None:
    if response.status_code == 204:
        return None
    if response.status_code >= 400:
        return None
    text = (response.text or "").strip()
    if not text:
        return None
    if text.lstrip().startswith("<"):
        return None
    try:
        data = response.json()
    except ValueError:
        match = _JWT_RE.search(text)
        if match:
            return {"code": match.group(0)}
        return None
    return data if isinstance(data, dict) else None


def _store_token(token: str, data: dict[str, Any] | None = None) -> None:
    global _access_token, _auth_user_id, _token_expires_at
    _access_token = token
    if data:
        _auth_user_id = _userid_from_login_response(data) or BUCKEYE2_USERNAME
    else:
        _auth_user_id = (BUCKEYE2_AUTH_USERID or BUCKEYE2_USERNAME or "").strip()
    exp = _jwt_exp_unix(token)
    _token_expires_at = exp if exp is not None else time.time() + 3600.0
    log.info("Buckeye2 JWT obtained (expires ~%s)", int(_token_expires_at))


def _static_bearer_token() -> str | None:
    token = _strip_bearer(BUCKEYE2_BEARER_TOKEN)
    if token:
        return token
    if not BUCKEYE2_EXTRA_HEADERS_JSON:
        return None
    try:
        extra = json.loads(BUCKEYE2_EXTRA_HEADERS_JSON)
        auth = extra.get("Authorization") or extra.get("authorization")
        if isinstance(auth, str) and auth.strip():
            return _strip_bearer(auth)
    except json.JSONDecodeError:
        return None
    return None


def _renew() -> bool:
    global _access_token, _token_expires_at
    if not _access_token:
        return False
    url = (BUCKEYE2_RENEW_URL or "").strip()
    if not url:
        return False
    headers = _base_headers(with_auth=True)
    headers["Content-Type"] = "application/json"
    body = {"operation": "renewToken"}
    try:
        response = requests.post(url, headers=headers, json=body, timeout=25)
        data = _parse_login_response(response)
        if not data:
            return False
        token = _token_from_login_response(data)
        if not token:
            return False
        _store_token(token, data)
        return True
    except requests.RequestException as exc:
        log.debug("Buckeye2 renewToken failed: %s", exc)
        return False


def _login() -> bool:
    global _access_token, _auth_user_id, _token_expires_at
    static = _static_bearer_token()
    if static:
        _store_token(static, None)
        return True
    if not (BUCKEYE2_USERNAME and BUCKEYE2_PASSWORD):
        return False
    url = (BUCKEYE2_LOGIN_URL or "").strip()
    if not url:
        log.warning("Buckeye2: BUCKEYE2_LOGIN_URL is not set")
        return False

    last_status: int | None = None
    for body in _login_bodies():
        for content_type, payload in (
            ("application/json", ("json", body)),
            ("application/x-www-form-urlencoded", ("data", body)),
        ):
            headers = _base_headers(with_auth=False)
            headers["Content-Type"] = content_type
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    timeout=30,
                    **{payload[0]: payload[1]},
                )
            except requests.RequestException as exc:
                log.warning("Buckeye2 login request failed: %s", exc)
                continue
            last_status = response.status_code
            data = _parse_login_response(response)
            if not data:
                continue
            token = _token_from_login_response(data)
            if not token:
                continue
            _store_token(token, data)
            return True

    if last_status == 204:
        log.warning("Buckeye2 login rejected (wrong username/password)")
    else:
        log.warning(
            "Buckeye2 login failed — check BUCKEYE2_LOGIN_URL and credentials (last HTTP %s)",
            last_status if last_status is not None else "?",
        )
    _access_token = None
    _auth_user_id = None
    _token_expires_at = 0.0
    return False


def invalidate_buckeye2_auth() -> None:
    global _access_token, _auth_user_id, _token_expires_at
    _access_token = None
    _auth_user_id = None
    _token_expires_at = 0.0


def buckeye2_auth_headers(*, force_refresh: bool = False) -> dict[str, str] | None:
    global _access_token, _auth_user_id, _token_expires_at
    if force_refresh:
        invalidate_buckeye2_auth()

    now = time.time()
    if _access_token and now < _token_expires_at - _REFRESH_MARGIN_SEC:
        remaining = _token_expires_at - now
        if (
            remaining < _RENEW_WHEN_REMAINING_SEC
            and not BUCKEYE2_BEARER_TOKEN
            and _renew()
        ):
            pass
    elif not _access_token or now >= _token_expires_at - _REFRESH_MARGIN_SEC:
        if not _login():
            return None

    if not _access_token:
        return None

    origin = (BUCKEYE2_API_ORIGIN or "https://www.kraken69.com").rstrip("/")
    user_id = (BUCKEYE2_AUTH_USERID or _auth_user_id or BUCKEYE2_USERNAME or "").strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; wc-arb-board/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": (BUCKEYE2_REFERER or f"{origin}/").strip(),
        "Authorization": f"Bearer {_access_token}",
    }
    if user_id:
        headers["X-Auth-Userid"] = user_id
    _apply_extra_headers(headers, skip_authorization=True)
    return headers
