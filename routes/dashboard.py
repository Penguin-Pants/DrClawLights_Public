"""Dashboard: settings form, highlights upload, and Send Now."""

import json
import logging
from datetime import datetime
from html import escape

import pytz
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

import config as config_store
import digest
import scheduler
from main import run_digest
from routes.auth import require_auth
from routes.common import COMMON_TIMEZONES, flash, templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _format_time(dt: datetime) -> str:
    return dt.strftime("%a %d %b, %H:%M %Z")


def _next_run_text() -> str:
    nxt = scheduler.next_run_time()
    return _format_time(nxt) if nxt else "Not scheduled"


def _last_run_text(tz_name: str) -> str:
    last = scheduler.last_run()
    if last is None:
        return "None since the service started."
    at = last["at"].astimezone(config_store.resolve_timezone(tz_name))
    return f"{_format_time(at)}: {last['detail']}"


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _=Depends(require_auth)):
    settings = config_store.load_settings()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "timezones": COMMON_TIMEZONES,
            "next_run": _next_run_text(),
            "last_run": _last_run_text(settings["timezone"]),
            "active": "dashboard",
        },
    )


@router.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    _=Depends(require_auth),
    from_email: str = Form(""),
    recipient_email: str = Form(""),
    books_per_email: str = Form("2"),
    highlights_per_book: str = Form("3"),
    send_time: str = Form("06:00"),
    timezone: str = Form("Europe/Berlin"),
):
    try:
        hour_str, minute_str = send_time.split(":", 1)
        send_hour, send_minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        return flash("Send time must be in HH:MM format.", "error")

    try:
        books = int(books_per_email)
        highlights = int(highlights_per_book)
    except (ValueError, TypeError):
        return flash("Books and highlights per email must be whole numbers.", "error")

    if not (0 <= send_hour <= 23) or not (0 <= send_minute <= 59):
        return flash("Send time must be a valid 24-hour time.", "error")
    if books < 1 or highlights < 1:
        return flash("Books and highlights per email must be at least 1.", "error")

    # An unknown name would otherwise be saved and the scheduler would quietly
    # fall back to Europe/Berlin. Store pytz's canonical spelling.
    try:
        tz_name = pytz.timezone(timezone.strip()).zone
    except pytz.UnknownTimeZoneError:
        return flash(f'Unknown timezone "{timezone.strip()}". Use a name like Europe/Berlin.', "error")

    config_store.save_settings(
        {
            "from_email": from_email.strip(),
            "recipient_email": recipient_email.strip(),
            "books_per_email": books,
            "highlights_per_book": highlights,
            "send_hour": send_hour,
            "send_minute": send_minute,
            "timezone": tz_name,
        }
    )
    scheduler.reschedule()
    # Also refresh the "Next digest" line out-of-band so it matches the save.
    return HTMLResponse(
        '<div class="flash success" role="status">Settings saved.</div>'
        f'<strong id="next-run" hx-swap-oob="true">{escape(_next_run_text())}</strong>'
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_highlights(
    request: Request,
    _=Depends(require_auth),
    file: UploadFile = File(...),
):
    raw = await file.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return flash("That file isn't valid JSON.", "error")
    problem = digest.validate_highlights(data)
    if problem:
        return flash(problem, "error")

    try:
        digest.save_highlights(raw, config_store.runtime_paths()["highlights_file"])
    except OSError as e:
        logger.error("Could not write highlights file: %s", e)
        return flash("Could not save the file on the server.", "error")

    n_books = len(data["books"])
    return flash(f"Highlights updated — {n_books} book(s) loaded.", "success")


@router.post("/send-now", response_class=HTMLResponse)
def send_now(request: Request, _=Depends(require_auth)):
    try:
        sent, message = run_digest(config_store.get_runtime_config())
    except Exception as e:  # noqa: BLE001 — surface any send failure to the UI
        logger.exception("Send Now failed")
        return flash(f"Send failed: {e}", "error")
    if not sent:
        return flash(message, "error")
    return flash("Digest sent. Check your inbox.", "success")
