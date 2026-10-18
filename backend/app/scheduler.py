"""Runs scans and grading on a market hours schedule (New York time)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.db import SessionLocal
from app.service import NotConfigured, TokenPending, connect, grade_open_picks, scan, work_lock

log = logging.getLogger("scheduler")


def parse_times(spec: str) -> list[time]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            h, m = part.split(":")
            out.append(time(int(h), int(m)))
    return sorted(out)


@dataclass(frozen=True)
class Job:
    kind: str  # scan | grade
    at: datetime


def is_trading_day(day: date) -> bool:
    # Weekends only; on market holidays the screener simply returns no movers.
    return day.weekday() < 5


def next_job(now: datetime, scan_times: list[time], grade_time: time) -> Job:
    """The next scheduled job strictly after `now` (now is timezone aware)."""
    candidates = []
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).date()
        if not is_trading_day(day):
            continue
        for t in scan_times:
            candidates.append(Job("scan", datetime.combine(day, t, now.tzinfo)))
        candidates.append(Job("grade", datetime.combine(day, grade_time, now.tzinfo)))
        future = [j for j in candidates if j.at > now]
        if future:
            return min(future, key=lambda j: j.at)
    raise RuntimeError("no trading day in the next week")  # pragma: no cover


def run_job(kind: str, settings: Settings, trigger: str = "schedule") -> str:
    """Execute one job synchronously. Returns a short status for logs and the API."""
    if not work_lock.acquire(blocking=False):
        return "busy"
    try:
        with SessionLocal() as db:
            try:
                market = connect(settings, db)
            except (NotConfigured, TokenPending) as exc:
                return str(exc)
            today = datetime.now(ZoneInfo(settings.timezone)).date()
            if kind == "scan":
                run = scan(db, market, settings.rules(), settings, trigger, today)
                return f"scan {run.status}: {run.picks} picks"
            graded = grade_open_picks(db, market, settings.rules(), today)
            return f"graded {graded}"
    except Exception as exc:  # keep the loop alive
        log.exception("%s job failed", kind)
        return f"{kind} failed: {exc}"
    finally:
        work_lock.release()


async def scheduler_loop(settings: Settings) -> None:
    tz = ZoneInfo(settings.timezone)
    scan_times = parse_times(settings.scan_times)
    grade_time = parse_times(settings.grade_time)[0]
    while True:
        job = next_job(datetime.now(tz), scan_times, grade_time)
        delay = (job.at - datetime.now(tz)).total_seconds()
        log.info("next %s at %s", job.kind, job.at.isoformat())
        await asyncio.sleep(max(1.0, delay))
        result = await asyncio.to_thread(run_job, job.kind, settings)
        log.info("%s: %s", job.kind, result)
