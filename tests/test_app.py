"""Web app tests: startup, auth and the dashboard routes.

Each test gets its own data directory and runs the real FastAPI lifespan
(design seeding + scheduler). resend and the Anthropic call are never reached
unless a test monkeypatches them.
"""

import html
import json
import re

from collections import deque

import pytest
from fastapi.testclient import TestClient

import config
import scheduler
from app import app
from routes import auth
from routes.common import flash

PASSWORD = "test-password"

HIGHLIGHTS = {
    "totalBooks": 2,
    "totalHighlights": 2,
    "books": [
        {"title": "BookA", "author": "AA", "coverUrl": None, "highlights": [{"text": "alpha"}]},
        {"title": "BookB", "author": "BB", "coverUrl": None, "highlights": [{"text": "beta"}]},
    ],
}

SETTINGS_FORM = {
    "from_email": "f@example.com",
    "recipient_email": "r@example.com",
    "books_per_email": "2",
    "highlights_per_book": "3",
    "send_time": "07:15",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A logged-out TestClient whose data files live in ``tmp_path``."""
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("HIGHLIGHTS_FILE", str(tmp_path / "highlights.json"))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("DESIGN_FILE", str(tmp_path / "design.md"))
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    for name in (
        "RESEND_API_KEY", "ANTHROPIC_API_KEY", "FROM_EMAIL", "RECIPIENT_EMAIL",
        "BOOKS_PER_EMAIL", "HIGHLIGHTS_PER_BOOK", "TIMEZONE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(scheduler, "_last_run", None)
    monkeypatch.setattr(auth, "_failed_logins", deque())
    with TestClient(app, follow_redirects=False) as c:
        yield c


def login(c: TestClient) -> None:
    r = c.post("/login", data={"password": PASSWORD})
    assert r.status_code == 303


# --- startup + login smoke tests (formerly inline scripts in ci.yml) ---------

def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_login_page_loads(client):
    r = client.get("/login")
    assert r.status_code == 200 and "sign in" in r.text.lower()


def test_dashboard_requires_login(client):
    r = client.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_login_then_dashboard(client):
    login(client)
    assert "drclawlights_session" in client.cookies
    assert client.get("/").status_code == 200


# --- auth hardening -----------------------------------------------------------

def _forged(secret: str) -> str:
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(secret, salt="drclawlights-auth").dumps({"ok": True})


@pytest.mark.parametrize("secret", ["drclawlights-unset", ""])
def test_no_password_means_no_valid_session(client, monkeypatch, secret):
    # Without ADMIN_PASSWORD the dashboard must stay locked, even for a cookie
    # signed with the old public fallback key or an empty key.
    monkeypatch.delenv("ADMIN_PASSWORD")
    client.cookies.set("drclawlights_session", _forged(secret))
    assert client.get("/").status_code == 303
    assert client.post("/send-now").status_code == 303


def test_no_password_refuses_login(client, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert client.post("/login", data={"password": "anything"}).status_code == 503


def test_wrong_password_rejected(client):
    r = client.post("/login", data={"password": "nope"})
    assert r.status_code == 401 and "drclawlights_session" not in client.cookies


def test_non_ascii_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "pässwörd")
    assert client.post("/login", data={"password": "wrong-€"}).status_code == 401
    assert client.post("/login", data={"password": "pässwörd"}).status_code == 303


def test_api_docs_are_not_public(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_preview_iframe_is_sandboxed(client):
    login(client)
    assert 'sandbox="allow-same-origin"' in client.get("/email-format").text


# --- scheduler ------------------------------------------------------------------

def test_scheduled_job_tolerates_late_wakeup(client):
    assert scheduler._scheduler.get_job("daily_digest").misfire_grace_time == 3600


# --- settings -----------------------------------------------------------------

def test_settings_reject_unknown_timezone(client):
    login(client)
    r = client.post("/settings", data={**SETTINGS_FORM, "timezone": "America/New York"})
    assert "flash error" in r.text and "Unknown timezone" in r.text
    assert config.load_settings()["timezone"] == "Europe/Berlin"  # nothing saved


def test_settings_save_reschedules_in_new_timezone(client):
    import pytz

    login(client)
    r = client.post("/settings", data={**SETTINGS_FORM, "timezone": "america/new_york"})
    assert "Settings saved" in r.text
    assert config.load_settings()["timezone"] == "America/New_York"  # canonical spelling
    nxt = scheduler._scheduler.get_job("daily_digest").next_run_time
    assert nxt.astimezone(pytz.timezone("America/New_York")).strftime("%H:%M") == "07:15"


# --- Send Now -----------------------------------------------------------------

def _stub_resend(monkeypatch) -> list:
    import resend

    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda payload: sent.append(payload) or {"id": "x"})
    return sent


def test_send_now_reports_missing_config(client, monkeypatch):
    sent = _stub_resend(monkeypatch)
    login(client)
    r = client.post("/send-now")
    assert "flash error" in r.text and "RESEND_API_KEY" in r.text
    assert sent == []


def test_send_now_reports_nothing_to_send(client, monkeypatch):
    # Regression: this used to flash "Digest sent" although nothing went out.
    sent = _stub_resend(monkeypatch)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    config.save_settings({"from_email": "f@example.com", "recipient_email": "r@example.com"})
    login(client)
    r = client.post("/send-now")
    assert "flash error" in r.text and "Nothing to send" in r.text
    assert sent == []


def test_send_now_sends(client, monkeypatch, tmp_path):
    sent = _stub_resend(monkeypatch)
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    config.save_settings({"from_email": "f@example.com", "recipient_email": "r@example.com"})
    (tmp_path / "highlights.json").write_text(json.dumps(HIGHLIGHTS))
    login(client)
    r = client.post("/send-now")
    assert "flash success" in r.text and "Digest sent" in r.text
    assert len(sent) == 1 and sent[0]["to"] == "r@example.com"


# --- highlights upload ----------------------------------------------------------

def _upload(c: TestClient, payload) -> str:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    r = c.post("/upload", files={"file": ("highlights.json", body, "application/json")})
    return html.unescape(r.text)


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"not json", "isn't valid JSON"),
        ({"items": []}, '"books" key'),
        ({"books": {"a": 1}}, "must be a list"),
        ({"books": [{"title": "T", "highlights": None}]}, "Book 1"),
        ({"books": [{"title": "T", "highlights": [{"note": "no text"}]}]}, "highlight without text"),
    ],
)
def test_upload_rejects_unusable_file(client, tmp_path, payload, message):
    (tmp_path / "highlights.json").write_text(json.dumps(HIGHLIGHTS))
    login(client)
    text = _upload(client, payload)
    assert "flash error" in text and message in text
    assert json.loads((tmp_path / "highlights.json").read_text()) == HIGHLIGHTS  # untouched


def test_upload_replaces_highlights_file(client, tmp_path):
    login(client)
    text = _upload(client, HIGHLIGHTS)
    assert "flash success" in text and "2 book(s)" in text
    assert json.loads((tmp_path / "highlights.json").read_text()) == HIGHLIGHTS
    assert not (tmp_path / "highlights.tmp").exists()


# --- schedule status on the dashboard -----------------------------------------------

def test_dashboard_shows_schedule_status(client):
    login(client)
    page = client.get("/").text
    assert "Next digest:" in page and "06:00" in page  # default send time
    assert "None since the service started." in page


def test_settings_save_refreshes_next_run_line(client):
    login(client)
    r = client.post("/settings", data={**SETTINGS_FORM, "timezone": "Europe/Berlin"})
    assert 'id="next-run" hx-swap-oob="true"' in r.text and "07:15" in r.text


def _failing_run(cfg):
    raise RuntimeError("boom")


@pytest.mark.parametrize(
    "outcome, shown",
    [
        (lambda cfg: (True, "Sent: Today's highlights"), "Sent: Today&#39;s highlights"),
        (lambda cfg: (False, "Nothing to send: no file."), "Nothing to send: no file."),
        (_failing_run, "Failed: boom"),
    ],
)
def test_last_scheduled_run_is_shown(client, monkeypatch, outcome, shown):
    monkeypatch.setattr(scheduler, "run_digest", outcome)
    scheduler._run_job()
    login(client)
    assert shown in client.get("/").text


# --- preview ------------------------------------------------------------------------

def test_preview_without_highlights(client):
    login(client)
    r = client.get("/email-format/preview")
    assert r.status_code == 200 and "No highlights to preview yet" in r.text


def test_preview_with_highlights(client, tmp_path):
    (tmp_path / "highlights.json").write_text(json.dumps(HIGHLIGHTS))
    login(client)
    r = client.get("/email-format/preview")
    assert r.status_code == 200 and "BookA" in r.text and "BookB" in r.text


# --- subject template ---------------------------------------------------------------

def test_bad_subject_template_does_not_break_the_page(client):
    # Regression: "{book1.x}" was saved, then every render raised AttributeError.
    login(client)
    r = client.post("/email-format/subject", data={"subject_template": "{book1.x}"})
    assert r.status_code == 200 and "Subject saved" in r.text
    assert client.get("/email-format").status_code == 200


# --- notifications and toggles ------------------------------------------------------

def test_settings_and_subject_responses_use_the_shared_flash(client):
    login(client)
    shared = flash("Settings saved.").body.decode()
    assert client.post("/settings", data={**SETTINGS_FORM, "timezone": "UTC"}).text.startswith(shared)
    shared = flash("Subject saved.").body.decode()
    assert client.post("/email-format/subject", data={"subject_template": "{book1}"}).text.startswith(shared)


def test_section_toggles_have_accessible_names(client):
    login(client)
    page = client.get("/email-format").text
    boxes = re.findall(r'<input type="checkbox"[^>]*>', page)
    assert len(boxes) == 3
    for box in boxes:
        target = re.search(r'aria-labelledby="([^"]+)"', box).group(1)
        assert f'id="{target}"' in page


# --- login throttle -----------------------------------------------------------------

def test_failed_logins_are_throttled_then_released(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert client.post("/login", data={"password": "nope"}).status_code == 401
    # Locked: even the right password is refused, so guesses learn nothing.
    r = client.post("/login", data={"password": PASSWORD})
    assert r.status_code == 429 and "Too many failed sign-ins" in r.text
    now[0] += auth.FAILED_LOGIN_WINDOW + 1
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303


def test_successful_login_clears_failures(client):
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        client.post("/login", data={"password": "nope"})
    login(client)
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        assert client.post("/login", data={"password": "nope"}).status_code == 401


# --- session cookie -------------------------------------------------------------------

@pytest.mark.parametrize(
    "base_url, headers, secure",
    [
        ("http://testserver", {}, False),
        ("https://testserver", {}, True),
        ("http://testserver", {"X-Forwarded-Proto": "https"}, True),
    ],
)
def test_session_cookie_is_secure_over_https(client, base_url, headers, secure):
    client.base_url = base_url
    r = client.post("/login", data={"password": PASSWORD}, headers=headers)
    assert r.status_code == 303
    assert ("secure" in r.headers["set-cookie"].lower()) is secure


# --- upload size limits -----------------------------------------------------------------

def test_oversized_highlights_upload_is_rejected(client, tmp_path, monkeypatch):
    from routes import dashboard

    monkeypatch.setattr(dashboard, "MAX_HIGHLIGHTS_BYTES", 100)
    login(client)
    text = _upload(client, b"{" + b" " * 200 + b"}")
    assert "flash error" in text and "too large" in text
    assert not (tmp_path / "highlights.json").exists()


def test_oversized_design_upload_is_rejected(client, tmp_path, monkeypatch):
    from routes import email_format

    monkeypatch.setattr(email_format, "MAX_DESIGN_BYTES", 100)
    login(client)
    body = b"--color-ink: #000;" + b" " * 200
    r = client.post("/email-format/design", files={"file": ("design.md", body, "text/markdown")})
    assert "flash error" in r.text and "too large" in r.text
