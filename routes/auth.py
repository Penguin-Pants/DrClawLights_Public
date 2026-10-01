"""Single-admin authentication via a signed session cookie."""

import hmac
import logging
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from routes.common import templates

logger = logging.getLogger(__name__)
router = APIRouter()

COOKIE_NAME = "drclawlights_session"
MAX_AGE = 60 * 60 * 24 * 14  # 14 days
_SALT = "drclawlights-auth"


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

    # Compare bytes: compare_digest rejects str arguments with non-ASCII
    # characters (TypeError -> HTTP 500).
    if hmac.compare_digest(password.encode("utf-8"), admin.encode("utf-8")):
        token = _serializer().dumps({"ok": True})
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME, token,
            max_age=MAX_AGE, httponly=True, samesite="lax",
        )
        return response

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
