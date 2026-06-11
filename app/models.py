from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArbBoardSnapshot(Base):
    __tablename__ = "arb_board_snapshots"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
