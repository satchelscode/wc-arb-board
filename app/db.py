from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL


def _normalize_database_url(raw_url: str) -> str:
    """Force SQLAlchemy to use psycopg v3 (not psycopg2) for all Postgres URLs."""
    url = (raw_url or "").strip().strip('"').strip("'")
    if not url or url.startswith("sqlite"):
        return url
    parsed = make_url(url)
    driver = parsed.drivername.lower()
    if driver == "postgresql+psycopg":
        return url
    base = driver.split("+", 1)[0]
    if base in ("postgresql", "postgres"):
        return parsed.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        )
    return url


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

def normalized_database_url(raw_url: str | None = None) -> str:
    return _normalize_database_url(raw_url if raw_url is not None else DATABASE_URL)


_db_url = normalized_database_url()
engine = create_engine(_db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
