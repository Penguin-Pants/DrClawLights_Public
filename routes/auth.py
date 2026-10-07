"""Single-admin authentication via a signed session cookie."""

import hmac
import logging
import os
import threading
import time
from collections import deque

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from routes.common import templates

logger = logging.getLogger(__name__)
router = APIRouter()

COOKIE_NAME = "drclawlights_session"
MAX_AGE = 60 * 60 * 24 * 14  # 14 days
# "-v2": cookies signed before the Secure flag existed no longer verify, so
# every session after this change carries the new cookie attributes.
_SALT = "drclawlights-auth-v2"

# Failed sign-ins one client may make in a sliding window before that client
# is refused until the window passes. Per client, so one attacker cannot lock
# the admin out. A locked client is refused even with the right password, so
# its guesses learn nothing. In memory only, so a restart clears it.
MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = 15 * 60  # seconds
# Bounds memory when many addresses fail; the oldest client is dropped first.
MAX_TRACKED_CLIENTS = 10_000
_failed_logins: dict[str, deque[float]] = {}
_failed_lock = threading.Lock()


def _client_key(request: Request) -> str:
    # Railway's edge sends the client's address as X-Real-IP (Railway docs,
    # networking/public-networking/specs-and-limits). Without the proxy
    # (local runs) use the socket address.
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def _recent_failures(key: str, now: float) -> deque[float]:
    """The client's failures inside the window. Call with the lock held."""
    failures = _failed_logins.get(key, deque())
    while failures and failures[0] <= now - FAILED_LOGIN_WINDOW:
        failures.popleft()
    return failures


def _locked_out(key: str) -> bool:
    with _failed_lock:
        return len(_recent_failures(key, time.monotonic())) >= MAX_FAILED_LOGINS


def _record_failed_login(key: str) -> None:
    with _failed_lock:
        now = time.monotonic()
        failures = _recent_failures(key, now)
        failures.append(now)
        # Re-insert so dict order runs from least to most recently failed.
        _failed_logins.pop(key, None)
        _failed_logins[key] = failures
        while len(_failed_logins) > MAX_TRACKED_CLIENTS:
            del _failed_logins[next(iter(_failed_logins))]


def _clear_failed_logins(key: str) -> None:
    with _failed_lock:
        _failed_logins.pop(key, None)


def _is_https(request: Request) -> bool:
    # Railway ends TLS at its proxy and forwards plain HTTP, so also trust
    # its X-Forwarded-Proto. Local http:// development keeps working.
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or proto == "https"


class NotAuthenticated(Exception):
    """Raised by ``require_auth``; handled in app.py with a redirect."""


def _admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "").strip()


def _serializer() -> URLSafeTimedSerializer:
    # The admin password doubles as the signing secret, so changing it
    # invalidates existing sessions. Callers check a password is set first.
    return URLSafeTimedSerializer(_admin_password(), salt=_SALT)


def _is_valid(token: str) -> bool:
    try:
        _serializer().loads(token, max_age=MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_auth(request: Request) -> bool:
    """Dependency: allow the request only when a valid session cookie exists."""
    token = request.cookies.get(COOKIE_NAME)
    # Fail closed: with no ADMIN_PASSWORD there is no secret to verify against,
    # so no session can be valid.
    if _admin_password() and token and _is_valid(token):
        return True
    raise NotAuthenticated()


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    admin = _admin_password()
    if not admin:
        logger.error("ADMIN_PASSWORD is not set — refusing all logins")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Server is missing ADMIN_PASSWORD."},
            status_code=503,
        )

    client = _client_key(request)
    if _locked_out(client):
        logger.warning("Login refused for %s: too many failed sign-ins", client)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Too many failed sign-ins. Try again in 15 minutes."},
            status_code=429,
        )

    # Compare bytes: compare_digest rejects str arguments with non-ASCII
    # characters (TypeError -> HTTP 500).
    if hmac.compare_digest(password.encode("utf-8"), admin.encode("utf-8")):
        _clear_failed_logins(client)
        token = _serializer().dumps({"ok": True})
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME, token,
            max_age=MAX_AGE, httponly=True, samesite="lax", secure=_is_https(request),
        )
        return response

    _record_failed_login(client)
    logger.warning("Failed sign-in attempt from %s", client)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Incorrect password."},
        status_code=401,
    )


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
