"""Login to ACE-family backends and fetch World Cup helper JSON."""

from __future__ import annotations

import json
import logging
import re

import requests

from app.ace_sites import AceSite

log = logging.getLogger(__name__)
_LG_RE = re.compile(r"[?&]lg=(\d+)", re.I)
_WC_RE = re.compile(r"world\s*cup|fifa", re.I)


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


def _helper_base(site: AceSite) -> str:
    return f"{site.origin.rstrip('/')}/wager/NewScheduleHelper.aspx?WT=0"


def _discover_wc_helper_urls(site: AceSite, html: str) -> list[str]:
    seen = {u.strip() for u in site.wc_helper_urls if u.strip()}
    discovered: list[str] = []
    host = re.escape(site.origin.rstrip("/"))
    helper_full = re.compile(
        rf"https?://{host}/wager/NewScheduleHelper\.aspx\?[^\"'\s<>\\]+",
        re.I,
    )
    base = _helper_base(site)

    def _add(url: str) -> None:
        u = url.strip()
        if u and u not in seen:
            seen.add(u)
            discovered.append(u)

    for m in helper_full.finditer(html or ""):
        candidate = m.group(0)
        if _WC_RE.search(candidate):
            _add(candidate)
    lg_ids: list[str] = []
    for m in _LG_RE.finditer(html or ""):
        lg_ids.append(m.group(1))
    for lg in sorted(set(lg_ids), key=int):
        _add(f"{base}&lg={lg}")
        if len(discovered) >= 12:
            break

    if (html or "").strip().startswith(("{", "[")):
        try:
            payload = json.loads(html)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            stack = [payload]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    desc = node.get("Description")
                    if isinstance(desc, str) and _WC_RE.search(desc):
                        for key in (
                            "LeagueId",
                            "LeagueID",
                            "ID",
                            "Id",
                            "lg",
                            "LG",
                            "CategoryId",
                        ):
                            val = node.get(key)
                            if val is not None and str(val).strip().isdigit():
                                _add(f"{base}&lg={str(val).strip()}")
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    return discovered


def fetch_wc_helper_pages(site: AceSite) -> list[tuple[str, str]]:
    """Return (json_text, url) for each WC helper page."""
    s = _session_for_site(site)
    if s is None:
        return []
    urls = list(site.wc_helper_urls)
    try:
        straight = (site.straight_url or "").strip()
        if straight:
            r = s.get(
                straight,
                timeout=25,
                headers={"Referer": site.login_url, "Accept": "text/html,*/*"},
            )
            r.raise_for_status()
            urls.extend(_discover_wc_helper_urls(site, r.text))
    except requests.RequestException as exc:
        log.warning("%s CreateSports fetch failed: %s", site.label, exc)

    seen: set[str] = set()
    pages: list[tuple[str, str]] = []
    for helper in urls:
        helper = helper.strip()
        if not helper or helper in seen:
            continue
        seen.add(helper)
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
            pages.append((r.text, r.url))
        except requests.RequestException as exc:
            log.warning("%s WC helper GET failed (%s): %s", site.label, helper, exc)
    return pages


def fetch_wc_helper_page(site: AceSite) -> tuple[str, str] | None:
    """Return first helper page for backward compatibility."""
    pages = fetch_wc_helper_pages(site)
    return pages[0] if pages else None
