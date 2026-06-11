"""Book keys shown on the dashboard (skin name, not backend host)."""

from __future__ import annotations

# Internal scrape keys -> user-facing book id
BOOK_ALIASES: dict[str, str] = {
    "falcon": "ace",  # legacy snapshots before rename
    "betonlineag": "betonline",  # Odds API key; user-facing label
}


def normalize_book_key(key: str) -> str:
    raw = (key or "").strip().lower()
    return BOOK_ALIASES.get(raw, raw)


def display_book(key: str) -> str:
    return normalize_book_key(key).upper()
