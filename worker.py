import logging
import sys
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("wc-arb-worker")

from app.config import DATABASE_URL, ODDS_API_KEY, SCAN_INTERVAL_SECONDS
from app.db import SessionLocal, engine, normalized_database_url
from app.models import Base
from app.scanner import refresh_snapshot


def _ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)


def main() -> None:
    db_driver = normalized_database_url(DATABASE_URL).split("://", 1)[0] if DATABASE_URL else "unset"
    log.info(
        "WC arb board worker starting (interval=%ss, db_driver=%s)",
        SCAN_INTERVAL_SECONDS,
        db_driver,
    )
    try:
        _ensure_schema()
    except Exception:
        log.exception("Database schema init failed — check DATABASE_URL")
        raise

    while True:
        if not ODDS_API_KEY:
            log.error(
                "ODDS_API_KEY is missing on wc-arb-board-worker — "
                "set it in Render → Environment, then redeploy"
            )
            time.sleep(60)
            continue
        if not DATABASE_URL:
            log.error("DATABASE_URL is missing on wc-arb-board-worker")
            time.sleep(60)
            continue
        try:
            with SessionLocal() as session:
                payload = refresh_snapshot(session=session)
            log.info(
                "Refreshed: offers=%s arbs=%s books=%s",
                payload.get("offer_count"),
                payload.get("arb_count"),
                ",".join(payload.get("books") or []),
            )
        except Exception:
            log.exception("Scan failed")
        time.sleep(max(60, SCAN_INTERVAL_SECONDS))


if __name__ == "__main__":
    main()
