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

from app.config import ODDS_API_KEY, SCAN_INTERVAL_SECONDS
from app.db import SessionLocal, engine
from app.models import Base
from app.scanner import refresh_snapshot

Base.metadata.create_all(bind=engine)


def main() -> None:
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is required")
    log.info("WC arb board worker started (interval=%ss)", SCAN_INTERVAL_SECONDS)
    while True:
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
