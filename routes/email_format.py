"""Email format panel: design.md upload, section toggles, subject, preview."""

import logging
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

import config as config_store
from config import DEFAULT_SUBJECT_TEMPLATE
from email_builder import build_subject
from main import build_email
from routes.auth import require_auth
from routes.common import flash, templates

logger = logging.getLogger(__name__)
router = APIRouter()

_PLACEHOLDER_TITLES = ["The Midnight Library", "Sapiens"]


@router.get("/email-format", response_class=HTMLResponse)
def email_format_page(request: Request, _=Depends(require_auth)):
    # Pass only the editable settings to the template — never the secrets that
    # get_runtime_config() carries. runtime_paths() resolves the design path
    # from the env without a second config.json read.
    settings = config_store.load_settings()
    design_path = Path(config_store.runtime_paths()["design_file"])
    return templates.TemplateResponse(
        request,
        "email_format.html",
        {
            "settings": settings,
            "design_present": design_path.exists(),
            "design_name": design_path.name,
            "subject_preview": _subject_preview(settings["subject_template"]),
            "active": "email_format",
        },
    )


@router.post("/email-format/design", response_class=HTMLResponse)
async def upload_design(
    request: Request,
    _=Depends(require_auth),
    file: UploadFile = File(...),
):
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return flash("Design file must be UTF-8 text.", "error")
    if "--color-" not in text:
        return flash("That file has no design tokens (no --color-* properties).", "error")

    path = Path(config_store.runtime_paths()["design_file"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        logger.error("Could not write design file: %s", e)
        return flash("Could not save the design file on the server.", "error")

    return _flash_with_preview_refresh("Design updated. Preview refreshed.", "success")


@router.post("/email-format/toggles", response_class=HTMLResponse)
def save_toggles(
    request: Request,
    _=Depends(require_auth),
    show_echo: bool = Form(False),
    show_revisit: bool = Form(False),
    show_covers: bool = Form(False),
):
    config_store.save_settings(
        {"show_echo": show_echo, "show_revisit": show_revisit, "show_covers": show_covers}
    )
    return _flash_with_preview_refresh("Section toggles saved.", "success")


@router.post("/email-format/subject", response_class=HTMLResponse)
def save_subject(
    request: Request,
    _=Depends(require_auth),
    subject_template: str = Form(...),
):
    template = subject_template.strip() or DEFAULT_SUBJECT_TEMPLATE
    config_store.save_settings({"subject_template": template})
    preview = escape(_subject_preview(template))
    return HTMLResponse(
        f'<div class="flash success" role="status">Subject saved.</div>'
        f'<div id="subject-preview" hx-swap-oob="true" class="preview-line">'
        f"Subject preview: <strong>{preview}</strong></div>"
    )


@router.get("/email-format/preview", response_class=HTMLResponse)
def preview(request: Request, _=Depends(require_auth)):
    cfg = config_store.get_runtime_config()
    built = build_email(cfg, for_preview=True)
    if built is None:
        return HTMLResponse(
            '<!DOCTYPE html><html><body style="font-family:system-ui;padding:40px;'
            'color:#707070;text-align:center">'
            "<p>No highlights to preview yet.</p>"
            "<p>Upload a highlights.json file on the dashboard first.</p>"
            "</body></html>"
        )
    return HTMLResponse(built["html"])


def _subject_preview(template: str) -> str:
    # Returns the raw (unescaped) subject. The GET template path relies on
    # Jinja autoescaping; the POST path escapes explicitly before building HTML.
    fake = [{"title": t} for t in _PLACEHOLDER_TITLES]
    return build_subject(fake, template)


def _flash_with_preview_refresh(message: str, kind: str) -> HTMLResponse:
    # Emit an HTMX client event; base.html listens for it and reloads the
    # preview iframe. More reliable than injecting a <script> via innerHTML.
    response = HTMLResponse(f'<div class="flash {kind}" role="status">{message}</div>')
    response.headers["HX-Trigger"] = "refreshPreview"
    return response
