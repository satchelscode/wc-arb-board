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


def configured_ace_sites() -> list[AceSite]:
    sites: list[AceSite] = []
    if FALCON_ENABLED:
        origin = _origin_from_url(FALCON_STRAIGHT_URL or FALCON_LOGIN_URL, "https://backend.falcon.ag")
        site = AceSite(
            key="falcon",
            label="Falcon",
            origin=origin,
            login_url=FALCON_LOGIN_URL or f"{origin}/",
            straight_url=FALCON_STRAIGHT_URL or f"{origin}/wager/CreateSports.aspx?WT=0",
            wc_helper_url=FALCON_WC_HELPER_URL,
            cookie=FALCON_COOKIE,
            username=FALCON_USERNAME,
            password=FALCON_PASSWORD,
            username_field=FALCON_USERNAME_FIELD,
            password_field=FALCON_PASSWORD_FIELD,
            login_extra_json=FALCON_LOGIN_EXTRA_FORM_JSON,
        )
        if site.has_auth():
            sites.append(site)
    if BETVEGAS23_ENABLED:
        origin = _origin_from_url(
            BETVEGAS23_STRAIGHT_URL or BETVEGAS23_LOGIN_URL,
            "https://backend.betvegas23.com",
        )
        site = AceSite(
            key="betvegas23",
            label="BetVegas23",
            origin=origin,
            login_url=BETVEGAS23_LOGIN_URL or f"{origin}/",
            straight_url=BETVEGAS23_STRAIGHT_URL or f"{origin}/wager/CreateSports.aspx?WT=0",
            wc_helper_url=BETVEGAS23_WC_HELPER_URL,
            cookie=BETVEGAS23_COOKIE,
            username=BETVEGAS23_USERNAME,
            password=BETVEGAS23_PASSWORD,
            username_field=BETVEGAS23_USERNAME_FIELD,
            password_field=BETVEGAS23_PASSWORD_FIELD,
            login_extra_json=BETVEGAS23_LOGIN_EXTRA_FORM_JSON,
        )
        if site.has_auth():
            sites.append(site)
    return sites
