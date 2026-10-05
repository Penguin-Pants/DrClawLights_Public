"""FastAPI application entrypoint for the DrClawLights admin dashboard.

Serves the admin UI and owns the background digest scheduler. Run with:

    uvicorn app:app --host 0.0.0.0 --port $PORT
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import scheduler
import seed
from routes import auth, dashboard, email_format
from main import configure_logging
from routes.auth import NotAuthenticated
from routes.common import UploadSizeLimit

configure_logging()
# uvicorn sets up its own "uvicorn" logger (startup/shutdown lines, errors) to
# write everything to stderr before it imports this module. Hand it to the root
# handlers instead so it gets the same stdout/stderr split. The access log
# ("uvicorn.access") already writes to stdout and is left alone.
_uvicorn_logger = logging.getLogger("uvicorn")
_uvicorn_logger.handlers.clear()
_uvicorn_logger.propagate = True
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("ADMIN_PASSWORD", "").strip():
        logger.warning("ADMIN_PASSWORD is not set — the dashboard cannot be logged into")
    seed.ensure_design_file()
    scheduler.start_scheduler()
    try:
        yield
    finally:
        scheduler.shutdown_scheduler()


# The auto-generated API docs would be public (they sit outside require_auth),
# and nothing here is meant to be called as an API, so turn them off.
app = FastAPI(
    title="DrClawLights Admin",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
# Checked before the form is parsed, so an oversized upload never reaches
# temporary disk. Read per request, so the route modules own the limits.
app.add_middleware(
    UploadSizeLimit,
    limits={
        "/upload": lambda: dashboard.MAX_HIGHLIGHTS_BYTES,
        "/email-format/design": lambda: email_format.MAX_DESIGN_BYTES,
    },
)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(email_format.router)


@app.exception_handler(NotAuthenticated)
async def _redirect_to_login(request: Request, exc: NotAuthenticated):
    # HTMX requests can't follow a normal 303, so steer them with HX-Redirect.
    if request.headers.get("HX-Request"):
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = "/login"
        return response
    return RedirectResponse("/login", status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
