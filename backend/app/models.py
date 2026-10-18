from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20))  # schedule | manual
    status: Mapped[str] = mapped_column(String(20), default="running")  # ok | error
    candidates: Mapped[int] = mapped_column(Integer, default=0)
    picks: Mapped[int] = mapped_column(Integer, default=0)
    spy_change: Mapped[float] = mapped_column(Float, default=0.0)
    rejected: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Pick(Base):
    __tablename__ = "picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"))
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open|win|loss

    trade_date: Mapped[date] = mapped_column(Date)
    expiry: Mapped[date] = mapped_column(Date)
    close_by: Mapped[date] = mapped_column(Date)
    alert_level: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    score: Mapped[int] = mapped_column(Integer)

    short_symbol: Mapped[str] = mapped_column(String(32))
    long_symbol: Mapped[str] = mapped_column(String(32))
    short_strike: Mapped[float] = mapped_column(Float)
    long_strike: Mapped[float] = mapped_column(Float)
    credit: Mapped[float] = mapped_column(Float)
    contracts: Mapped[int] = mapped_column(Integer)
    est_profit: Mapped[float] = mapped_column(Float)
    max_loss: Mapped[float] = mapped_column(Float)

    # Everything else from the proposal (CSP side, score parts, warnings).
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    buckets: Mapped[dict] = mapped_column(JSON, default=dict)

    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_spread_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    grade_reason: Mapped[str] = mapped_column(String(200), default="")
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeyValue(Base):
    """Small persistent state (Webull access token, its status)."""

    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
