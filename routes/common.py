"""Shared helpers for the route modules: templates, flash fragments, TZ list."""

from html import escape

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


def flash(message: str, kind: str = "success") -> HTMLResponse:
    """A small HTMX fragment shown in the toast zone after an action."""
    return HTMLResponse(f'<div class="flash {kind}" role="status">{escape(message)}</div>')
