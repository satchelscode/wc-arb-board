import os


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_SPORT_KEY = os.getenv("ODDS_API_SPORT_KEY", "soccer_fifa_world_cup").strip()
ODDS_API_BOOKS = os.getenv(
    "ODDS_API_BOOKS",
    "pinnacle,draftkings,fanduel,betonlineag,bookmaker",
).strip()
ODDS_API_REGIONS = os.getenv("ODDS_API_REGIONS", "us,eu").strip()
ODDS_API_MARKETS = os.getenv("ODDS_API_MARKETS", "team_totals,totals").strip()
ODDS_API_MAX_EVENTS = int(os.getenv("ODDS_API_MAX_EVENTS", "80"))
MIN_EDGE_PCT = float(os.getenv("MIN_EDGE_PCT", "0.01"))

SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wc_arb.db").strip()

FALCON_ENABLED = _env_truthy("FALCON_ENABLED", "true")
FALCON_LOGIN_URL = os.getenv("FALCON_LOGIN_URL", "https://backend.falcon.ag/").strip()
FALCON_STRAIGHT_URL = os.getenv(
    "FALCON_STRAIGHT_URL",
    "https://backend.falcon.ag/wager/CreateSports.aspx?WT=0",
).strip()
FALCON_WC_HELPER_URL = os.getenv(
    "FALCON_WC_HELPER_URL",
    "https://backend.falcon.ag/wager/NewScheduleHelper.aspx?WT=0&lg=3749",
).strip()
FALCON_USERNAME = os.getenv("FALCON_USERNAME", "").strip()
FALCON_PASSWORD = os.getenv("FALCON_PASSWORD", "").strip()
FALCON_COOKIE = os.getenv("FALCON_COOKIE", "").strip()
FALCON_USERNAME_FIELD = os.getenv("FALCON_USERNAME_FIELD", "Account").strip()
FALCON_PASSWORD_FIELD = os.getenv("FALCON_PASSWORD_FIELD", "Password").strip()
FALCON_LOGIN_EXTRA_FORM_JSON = os.getenv("FALCON_LOGIN_EXTRA_FORM_JSON", "").strip()

BETVEGAS23_ENABLED = _env_truthy("BETVEGAS23_ENABLED", "false")
BETVEGAS23_LOGIN_URL = os.getenv("BETVEGAS23_LOGIN_URL", "https://backend.betvegas23.com/").strip()
BETVEGAS23_STRAIGHT_URL = os.getenv(
    "BETVEGAS23_STRAIGHT_URL",
    "https://backend.betvegas23.com/wager/CreateSports.aspx?WT=0",
).strip()
BETVEGAS23_WC_HELPER_URL = os.getenv(
    "BETVEGAS23_WC_HELPER_URL",
    "https://backend.betvegas23.com/wager/NewScheduleHelper.aspx?WT=0&lg=3749",
).strip()
BETVEGAS23_USERNAME = os.getenv("BETVEGAS23_USERNAME", "").strip()
BETVEGAS23_PASSWORD = os.getenv("BETVEGAS23_PASSWORD", "").strip()
BETVEGAS23_COOKIE = os.getenv("BETVEGAS23_COOKIE", "").strip()
BETVEGAS23_USERNAME_FIELD = os.getenv("BETVEGAS23_USERNAME_FIELD", "Account").strip()
BETVEGAS23_PASSWORD_FIELD = os.getenv("BETVEGAS23_PASSWORD_FIELD", "Password").strip()
BETVEGAS23_LOGIN_EXTRA_FORM_JSON = os.getenv("BETVEGAS23_LOGIN_EXTRA_FORM_JSON", "").strip()

# Metallic = Steam22 player API (steam22.com), not ACE backend.
METALLIC_ENABLED = _env_truthy("METALLIC_ENABLED", "false")
METALLIC_USERNAME = os.getenv("METALLIC_USERNAME", "").strip()
METALLIC_PASSWORD = os.getenv("METALLIC_PASSWORD", "").strip()
METALLIC_LOGIN_URL = os.getenv(
    "METALLIC_LOGIN_URL",
    "https://steam22.com/player-api/identity/customerLogin/",
).strip()
METALLIC_RENEW_URL = os.getenv(
    "METALLIC_RENEW_URL",
    "https://steam22.com/player-api/identity/renewToken",
).strip()
METALLIC_SCHEDULE_URL = os.getenv(
    "METALLIC_SCHEDULE_URL",
    "https://steam22.com/player-api/api/wager/schedules/S/0",
).strip()
METALLIC_SCHEDULE_POST_BODY = os.getenv(
    "METALLIC_SCHEDULE_POST_BODY",
    '{"id":0,"languageID":1,"lineType":0,"version":"1.3.47"}',
).strip()
METALLIC_LOGIN_WEBSITE = os.getenv("METALLIC_LOGIN_WEBSITE", "steam22.com").strip()
METALLIC_JS_VERSION = os.getenv("METALLIC_JS_VERSION", "1.3.47").strip()
METALLIC_REFERER = os.getenv("METALLIC_REFERER", "https://steam22.com/v2/").strip()
METALLIC_EXTRA_HEADERS_JSON = os.getenv("METALLIC_EXTRA_HEADERS_JSON", "").strip()

# Buckeye2 = kraken69.com cloud API (not ACE backend).
BUCKEYE2_ENABLED = _env_truthy("BUCKEYE2_ENABLED", "false")
BUCKEYE2_USERNAME = os.getenv("BUCKEYE2_USERNAME", "").strip()
BUCKEYE2_PASSWORD = os.getenv("BUCKEYE2_PASSWORD", "").strip()
BUCKEYE2_AUTH_USERID = os.getenv("BUCKEYE2_AUTH_USERID", "").strip()
BUCKEYE2_BEARER_TOKEN = os.getenv("BUCKEYE2_BEARER_TOKEN", "").strip()
BUCKEYE2_API_ORIGIN = os.getenv("BUCKEYE2_API_ORIGIN", "https://www.kraken69.com").strip()
BUCKEYE2_DOMAIN = os.getenv("BUCKEYE2_DOMAIN", "kraken69.com").strip()
BUCKEYE2_REFERER = os.getenv("BUCKEYE2_REFERER", "https://www.kraken69.com/").strip()
BUCKEYE2_LOGIN_URL = os.getenv(
    "BUCKEYE2_LOGIN_URL",
    "https://www.kraken69.com/cloud/api/System/authenticateCustomer",
).strip()
BUCKEYE2_RENEW_URL = os.getenv(
    "BUCKEYE2_RENEW_URL",
    "https://www.kraken69.com/cloud/api/System/renewToken",
).strip()
BUCKEYE2_LOGIN_POST_BODY = os.getenv("BUCKEYE2_LOGIN_POST_BODY", "").strip()
BUCKEYE2_LINES_URL = os.getenv(
    "BUCKEYE2_LINES_URL",
    "https://www.kraken69.com/cloud/api/Lines/Get_LeagueLines2",
).strip()
BUCKEYE2_LINES_POST_BODY = os.getenv("BUCKEYE2_LINES_POST_BODY", "{}").strip()
BUCKEYE2_EXTRA_HEADERS_JSON = os.getenv("BUCKEYE2_EXTRA_HEADERS_JSON", "").strip()
