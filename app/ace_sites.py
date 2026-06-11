from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import (
    BETVEGAS23_COOKIE,
    BETVEGAS23_ENABLED,
    BETVEGAS23_LOGIN_EXTRA_FORM_JSON,
    BETVEGAS23_LOGIN_URL,
    BETVEGAS23_PASSWORD,
    BETVEGAS23_PASSWORD_FIELD,
    BETVEGAS23_STRAIGHT_URL,
    BETVEGAS23_USERNAME,
    BETVEGAS23_USERNAME_FIELD,
    BETVEGAS23_WC_HELPER_URL,
    FALCON_COOKIE,
    FALCON_ENABLED,
    FALCON_LOGIN_EXTRA_FORM_JSON,
    FALCON_LOGIN_URL,
    FALCON_PASSWORD,
    FALCON_PASSWORD_FIELD,
    FALCON_STRAIGHT_URL,
    FALCON_USERNAME,
    FALCON_USERNAME_FIELD,
    FALCON_WC_HELPER_URL,
    BUCKEYE2_COOKIE,
    BUCKEYE2_ENABLED,
    BUCKEYE2_LOGIN_EXTRA_FORM_JSON,
    BUCKEYE2_LOGIN_URL,
    BUCKEYE2_PASSWORD,
    BUCKEYE2_PASSWORD_FIELD,
    BUCKEYE2_STRAIGHT_URL,
    BUCKEYE2_USERNAME,
    BUCKEYE2_USERNAME_FIELD,
    BUCKEYE2_WC_HELPER_URL,
)


@dataclass(frozen=True)
class AceSite:
    key: str
    label: str
    origin: str
    login_url: str
    straight_url: str
    wc_helper_url: str
    cookie: str
    username: str
    password: str
    username_field: str
    password_field: str
    login_extra_json: str

    def has_auth(self) -> bool:
        return bool(
            (self.cookie or "").strip()
            or ((self.username or "").strip() and (self.password or "").strip())
        )


def _origin_from_url(url: str, fallback: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return fallback


def _build_site(
    *,
    key: str,
    label: str,
    enabled: bool,
    default_origin: str,
    login_url: str,
    straight_url: str,
    wc_helper_url: str,
    cookie: str,
    username: str,
    password: str,
    username_field: str,
    password_field: str,
    login_extra_json: str,
) -> AceSite | None:
    if not enabled:
        return None
    origin = _origin_from_url(straight_url or login_url, default_origin)
    site = AceSite(
        key=key,
        label=label,
        origin=origin,
        login_url=login_url or f"{origin}/",
        straight_url=straight_url or f"{origin}/wager/CreateSports.aspx?WT=0",
        wc_helper_url=wc_helper_url,
        cookie=cookie,
        username=username,
        password=password,
        username_field=username_field,
        password_field=password_field,
        login_extra_json=login_extra_json,
    )
    return site if site.has_auth() else None


def configured_ace_sites() -> list[AceSite]:
    sites: list[AceSite] = []
    for site in (
        _build_site(
            key="ace",
            label="ACE",
            enabled=FALCON_ENABLED,
            default_origin="https://backend.falcon.ag",
            login_url=FALCON_LOGIN_URL,
            straight_url=FALCON_STRAIGHT_URL,
            wc_helper_url=FALCON_WC_HELPER_URL,
            cookie=FALCON_COOKIE,
            username=FALCON_USERNAME,
            password=FALCON_PASSWORD,
            username_field=FALCON_USERNAME_FIELD,
            password_field=FALCON_PASSWORD_FIELD,
            login_extra_json=FALCON_LOGIN_EXTRA_FORM_JSON,
        ),
        _build_site(
            key="buckeye2",
            label="Buckeye2",
            enabled=BUCKEYE2_ENABLED,
            default_origin="https://backend.buckeye2.com",
            login_url=BUCKEYE2_LOGIN_URL,
            straight_url=BUCKEYE2_STRAIGHT_URL,
            wc_helper_url=BUCKEYE2_WC_HELPER_URL,
            cookie=BUCKEYE2_COOKIE,
            username=BUCKEYE2_USERNAME,
            password=BUCKEYE2_PASSWORD,
            username_field=BUCKEYE2_USERNAME_FIELD,
            password_field=BUCKEYE2_PASSWORD_FIELD,
            login_extra_json=BUCKEYE2_LOGIN_EXTRA_FORM_JSON,
        ),
        _build_site(
            key="betvegas23",
            label="BetVegas23",
            enabled=BETVEGAS23_ENABLED,
            default_origin="https://backend.betvegas23.com",
            login_url=BETVEGAS23_LOGIN_URL,
            straight_url=BETVEGAS23_STRAIGHT_URL,
            wc_helper_url=BETVEGAS23_WC_HELPER_URL,
            cookie=BETVEGAS23_COOKIE,
            username=BETVEGAS23_USERNAME,
            password=BETVEGAS23_PASSWORD,
            username_field=BETVEGAS23_USERNAME_FIELD,
            password_field=BETVEGAS23_PASSWORD_FIELD,
            login_extra_json=BETVEGAS23_LOGIN_EXTRA_FORM_JSON,
        ),
    ):
        if site is not None:
            sites.append(site)
    return sites
