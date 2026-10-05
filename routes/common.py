"""Shared helpers for the route modules: templates, flash fragments, TZ list."""

from html import escape

from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

# A curated short list for the timezone picker. The field also accepts any
# free-text IANA name, so this is just for convenience.
COMMON_TIMEZONES = [
    "Europe/Berlin",
    "Europe/London",
    "Europe/Paris",
    "Europe/Madrid",
    "Europe/Rome",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
    "UTC",
]


def flash(
    message: str,
    kind: str = "success",
    *,
    extra_html: str = "",
    trigger: str | None = None,
) -> HTMLResponse:
    """A small HTMX fragment shown in the toast zone after an action.

    ``message`` is escaped. ``extra_html`` (already-safe markup, e.g. an
    out-of-band swap) is appended after the toast, and ``trigger`` sets the
    HX-Trigger client event. Errors get a dismiss button: base.html only
    auto-dismisses success toasts, so an error stays until the user reads it.
    """
    dismiss = (
        '<button type="button" class="flash-close" aria-label="Dismiss">&times;</button>'
        if kind == "error"
        else ""
    )
    response = HTMLResponse(
        f'<div class="flash {kind}" role="status">{escape(message)}{dismiss}</div>{extra_html}'
    )
    if trigger:
        response.headers["HX-Trigger"] = trigger
    return response


async def read_upload(file: UploadFile, limit: int) -> bytes | None:
    """The uploaded bytes, or None when the file is larger than ``limit``.

    Reads at most ``limit + 1`` bytes, so an oversized upload never lands in
    memory in full.
    """
    data = await file.read(limit + 1)
    return None if len(data) > limit else data
