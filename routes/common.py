"""Shared helpers for the route modules: templates, flash fragments, TZ list."""

from html import escape
from typing import Callable

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


# Room for the multipart boundaries and part headers around the file itself.
MULTIPART_SLACK_BYTES = 64 * 1024

_TOO_LARGE_HTML = (
    b'<div class="flash error" role="status">That file is too large.'
    b'<button type="button" class="flash-close" aria-label="Dismiss">&times;</button></div>'
)


class _BodyTooLarge(Exception):
    pass


async def _send_too_large(send) -> None:
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"text/html; charset=utf-8")],
    })
    await send({"type": "http.response.body", "body": _TOO_LARGE_HTML})


class UploadSizeLimit:
    """ASGI middleware: refuse an upload body over its route's limit before
    FastAPI parses the form, which writes file parts to temporary disk.

    ``limits`` maps a POST path to a callable that returns the file limit in
    bytes, read per request. A Content-Length over the limit is refused at
    once; otherwise the bytes are counted as they arrive.
    """

    def __init__(self, app, limits: dict[str, Callable[[], int]]):
        self.app = app
        self.limits = limits

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] not in self.limits:
            await self.app(scope, receive, send)
            return
        limit = self.limits[scope["path"]]() + MULTIPART_SLACK_BYTES
        length = dict(scope["headers"]).get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            await _send_too_large(send)
            return

        received = 0
        exceeded = False
        replied = False

        async def limited_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message):
            nonlocal replied
            if not exceeded:
                await send(message)
            elif message["type"] == "http.response.start" and not replied:
                # FastAPI turns the parse error into a 400; answer 413 instead.
                replied = True
                await _send_too_large(send)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            pass
        if exceeded and not replied:
            await _send_too_large(send)
