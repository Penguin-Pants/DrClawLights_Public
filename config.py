"""Configuration store for DrClawLights.

UI-editable settings live in a JSON file on the Railway volume
(``/data/config.json`` by default). Secrets and infrastructure paths stay in
environment variables. ``get_runtime_config`` merges the two into the single
dict shape the digest pipeline expects.

Precedence for an editable setting: built-in default -> environment seed
(for first-run migration) -> value stored in config.json.
"""

import json
import logging
import os
from pathlib import Path

import pytz

logger = logging.getLogger(__name__)

CONFIG_FILE = os.environ.get("CONFIG_FILE", "/data/config.json")

# The product default subject line. Referenced wherever an unset/blank template
# falls back, so the default lives in exactly one place.
DEFAULT_SUBJECT_TEMPLATE = "Today's highlights from {book1} & {book2}"

# UI-editable settings and their built-in defaults.
DEFAULTS = {
    "from_email": "",
    "recipient_email": "",
    "books_per_email": 2,
    "highlights_per_book": 3,
    "send_hour": 6,
    "send_minute": 0,
    "timezone": "Europe/Berlin",
    "subject_template": DEFAULT_SUBJECT_TEMPLATE,
    "show_echo": True,
    "show_revisit": True,
    "show_covers": True,
}

_INT_KEYS = {"books_per_email", "highlights_per_book", "send_hour", "send_minute"}
_BOOL_KEYS = {"show_echo", "show_revisit", "show_covers"}

# Environment variables that seed editable settings before the first UI save,
# so an existing Railway deployment keeps its configured values.
_ENV_SEED = {
    "from_email": "FROM_EMAIL",
    "recipient_email": "RECIPIENT_EMAIL",
    "books_per_email": "BOOKS_PER_EMAIL",
    "highlights_per_book": "HIGHLIGHTS_PER_BOOK",
    "timezone": "TIMEZONE",
}


def _coerce(key: str, value) -> object:
    if key in _INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
    if key in _BOOL_KEYS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "on", "yes")
    return value


def _seed_from_env() -> dict:
    seeded = {}
    for key, env_name in _ENV_SEED.items():
        raw = os.environ.get(env_name, "").strip()
        if raw:
            seeded[key] = _coerce(key, raw)
    return seeded


def load_settings() -> dict:
    """Return the full set of UI-editable settings with all keys present."""
    settings = dict(DEFAULTS)
    seeded = _seed_from_env()
    settings.update(seeded)

    path = Path(CONFIG_FILE)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            for key in DEFAULTS:
                if key not in stored:
                    continue
                value = _coerce(key, stored[key])
                # A blank value persisted by the settings form must not mask a
                # non-empty environment seed — keep the seeded value instead.
                if value == "" and seeded.get(key):
                    continue
                settings[key] = value
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Could not load config from %s (%s) — using defaults", CONFIG_FILE, e)
    return settings


def save_settings(updates: dict) -> dict:
    """Merge ``updates`` into the stored settings and persist them atomically."""
    settings = load_settings()
    for key in DEFAULTS:
        if key in updates:
            settings[key] = _coerce(key, updates[key])

    path = Path(CONFIG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return settings


def resolve_timezone(name: str | None):
    """The pytz zone for ``name``, falling back to the default zone when the
    name is blank or unknown (e.g. a bad TIMEZONE env seed)."""
    try:
        return pytz.timezone(name or DEFAULTS["timezone"])
    except pytz.UnknownTimeZoneError:
        logger.warning("Unknown timezone %r — falling back to %s", name, DEFAULTS["timezone"])
        return pytz.timezone(DEFAULTS["timezone"])


def _path_env(name: str, default: str) -> str:
    """Read a path override from the env, falling back to the default when the
    variable is unset *or* present-but-blank (Railway often injects empty vars)."""
    return os.environ.get(name, "").strip() or default


def runtime_paths() -> dict:
    """File paths from the env, with defaults. Contains no secrets, so it is
    safe to expose to templates/routes that only need a path."""
    return {
        "highlights_file": _path_env("HIGHLIGHTS_FILE", "/data/highlights.json"),
        "history_file": _path_env("HISTORY_FILE", "/data/history.json"),
        "design_file": _path_env("DESIGN_FILE", "/data/design.md"),
    }


def get_runtime_config() -> dict:
    """Editable settings merged with secrets and file paths from the env."""
    settings = load_settings()
    return {
        **settings,
        "resend_api_key": os.environ.get("RESEND_API_KEY", "").strip(),
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        **runtime_paths(),
    }
