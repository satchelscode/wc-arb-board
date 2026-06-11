"""Login to ACE-family backends and fetch World Cup helper JSON."""

from __future__ import annotations

import json
import logging
import re

import requests

from app.ace_sites import AceSite

log = logging.getLogger(__name__)


def _aspnet_hidden_fields(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for fname in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(
            rf'(?:name|id)="{re.escape(fname)}"[^>]*value="([^"]*)"',
            html,
            re.I | re.DOTALL,
        )
        if m:
            out[fname] = m.group(1)
    return out


def _session_for_site(site: AceSite) -> requests.Session | None:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    if site.cookie:
        s.headers["Cookie"] = site.cookie
        return s
    if not (site.username and site.password):
        return None
    login_url = site.login_url
    try:
        pre = s.get(login_url, timeout=25)
        pre.raise_for_status()
    except requests.RequestException as exc:
        log.warning("%s login GET failed: %s", site.label, exc)
        return None
    hidden = _aspnet_hidden_fields(pre.text)
    payload: dict[str, str] = {**hidden}
    if site.login_extra_json:
        try:
            extra = json.loads(site.login_extra_json)
            if isinstance(extra, dict):
                payload.update({str(k): str(v) for k, v in extra.items()})
        except json.JSONDecodeError:
            log.warning("%s login extra JSON invalid", site.label)
    payload[site.username_field] = site.username
    payload[site.password_field] = site.password
    try:
        s.post(
            login_url,
            data=payload,
            timeout=25,
            headers={"Referer": login_url, "Origin": site.origin},
        )
    except requests.RequestException as exc:
        log.warning("%s login POST failed: %s", site.label, exc)
        return None
    return s


def fetch_wc_helper_page(site: AceSite) -> tuple[str, str] | None:
    """Return (json_text, url) for the WC team-totals helper, or None."""
    s = _session_for_site(site)
    if s is None:
        return None
    helper = (site.wc_helper_url or "").strip()
    if not helper:
        return None
    try:
        r = s.get(
            helper,
            timeout=25,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": site.straight_url,
            },
        )
        r.raise_for_status()
        return r.text, r.url
    except requests.RequestException as exc:
        log.warning("%s WC helper GET failed (%s): %s", site.label, helper, exc)
        return None
