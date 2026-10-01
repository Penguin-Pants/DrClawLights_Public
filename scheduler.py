"""Background digest scheduler for the web app.

The Railway deployment runs the FastAPI app, which owns a single
``BackgroundScheduler``. Changing the send time or timezone in the dashboard
calls ``reschedule`` to update the running job in place — no restart needed.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from config import get_runtime_config, resolve_timezone
from main import run_digest

logger = logging.getLogger(__name__)

_JOB_ID = "daily_digest"
_scheduler: BackgroundScheduler | None = None
# Outcome of the latest scheduled run, for the dashboard. In memory only, so a
# restart clears it; Railway logs remain the full record.
_last_run: dict | None = None


def _run_job() -> None:
    global _last_run
    started = datetime.now(timezone.utc)
    try:
        _, detail = run_digest(get_runtime_config())
    except Exception as e:
        logger.exception("Scheduled digest run failed")
        detail = f"Failed: {e}"
    _last_run = {"at": started, "detail": detail}


def next_run_time() -> datetime | None:
    """When the daily job fires next, or None if the scheduler isn't running."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_JOB_ID)
    return job.next_run_time if job else None


def last_run() -> dict | None:
    """``{"at", "detail"}`` for the latest scheduled run since startup."""
    return _last_run


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    cfg = get_runtime_config()
    _scheduler = BackgroundScheduler(timezone=resolve_timezone(cfg["timezone"]))
    # APScheduler's default grace is 1 second: a scheduler thread that wakes
    # any later than that (CPU pause, busy host) silently skips the day.
    _scheduler.add_job(
        _run_job, "cron",
        hour=cfg["send_hour"], minute=cfg["send_minute"], id=_JOB_ID,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — digest at %02d:%02d %s",
        cfg["send_hour"], cfg["send_minute"], cfg["timezone"],
    )
    return _scheduler


def reschedule() -> None:
    """Apply the current stored send time/timezone to the running job."""
    if _scheduler is None:
        return
    cfg = get_runtime_config()
    _scheduler.reschedule_job(
        _JOB_ID,
        trigger="cron",
        hour=cfg["send_hour"],
        minute=cfg["send_minute"],
        timezone=resolve_timezone(cfg["timezone"]),
    )
    logger.info(
        "Scheduler rescheduled — digest at %02d:%02d %s",
        cfg["send_hour"], cfg["send_minute"], cfg["timezone"],
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
