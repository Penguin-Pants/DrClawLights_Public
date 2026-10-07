"""Unit tests for the code-review fixes.

Run with ``pytest -q``. These exercise the digest/email/config logic directly
(no web server, no network); resend and the Anthropic echo call are monkeypatched.
"""

import json
import os

import pytest

import config
import email_builder
import history
import main


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Point the config store at a throwaway config.json."""
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))
    return tmp_path


# --- config: blank path env vars fall back to defaults -----------------------

def test_blank_path_env_falls_back(monkeypatch, tmp_config):
    monkeypatch.setenv("HIGHLIGHTS_FILE", "")  # present but blank
    assert config.get_runtime_config()["highlights_file"] == "/data/highlights.json"


def test_set_path_env_is_used(monkeypatch, tmp_config):
    monkeypatch.setenv("HISTORY_FILE", "/srv/hist.json")
    assert config.get_runtime_config()["history_file"] == "/srv/hist.json"


# --- config: a blank stored value must not mask a non-empty env seed ---------

def test_blank_stored_does_not_mask_seed(monkeypatch, tmp_config):
    monkeypatch.setenv("FROM_EMAIL", "seed@x.com")
    config.save_settings({"from_email": ""})  # form persists a blank field
    assert config.load_settings()["from_email"] == "seed@x.com"


def test_nonblank_stored_overrides_seed(monkeypatch, tmp_config):
    monkeypatch.setenv("FROM_EMAIL", "seed@x.com")
    config.save_settings({"from_email": "user@x.com"})
    assert config.load_settings()["from_email"] == "user@x.com"


# --- config: the path accessor exposes no secrets ----------------------------

def test_runtime_paths_has_no_secrets(tmp_config):
    paths = config.runtime_paths()
    assert set(paths) == {"highlights_file", "history_file", "design_file"}
    assert not any("key" in k for k in paths)


# --- subject builder ---------------------------------------------------------

def test_subject_two_books():
    out = email_builder.build_subject([{"title": "A"}, {"title": "B"}])
    assert out == "Today's highlights from A & B"


def test_subject_single_book_strips_default_separator():
    out = email_builder.build_subject([{"title": "A"}])
    assert out == "Today's highlights from A"


def test_subject_single_book_strips_custom_comma():
    out = email_builder.build_subject([{"title": "A"}], "Highlights: {book1}, {book2}")
    assert out == "Highlights: A"


def test_subject_single_book_keeps_hyphen_in_title():
    # A trailing hyphen is part of the title, not a separator — must survive.
    out = email_builder.build_subject([{"title": "Re-"}], "{book1}")
    assert out == "Re-"


# --- email rendering: coverUrl is escaped ------------------------------------

def test_cover_url_is_escaped():
    book = {"title": "T", "author": "A", "coverUrl": 'http://x/a" onerror="y', "highlights": []}
    html = email_builder.build_html([book], {})
    assert 'onerror="y' not in html
    assert "&quot;" in html


def test_library_totals_are_escaped():
    html = email_builder.build_html([], {"totalBooks": "<b>x</b>", "totalHighlights": 3})
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


# --- design token cache: returns copies and invalidates on mtime -------------

def test_design_token_cache(tmp_path):
    p = tmp_path / "design.md"
    p.write_text(":root{--color-ink: #111111;}")
    first = email_builder.load_design_tokens(str(p))
    assert first["color-ink"] == "#111111"

    first["color-ink"] = "MUTATED"  # must not affect the cache
    assert email_builder.load_design_tokens(str(p))["color-ink"] == "#111111"

    p.write_text(":root{--color-ink: #222222;}")
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 5))  # force a new mtime
    assert email_builder.load_design_tokens(str(p))["color-ink"] == "#222222"


# --- run_digest: refuses to send when unconfigured ---------------------------

def test_run_digest_blocks_when_unconfigured(monkeypatch):
    import resend

    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda payload: sent.append(payload) or {"id": "1"})
    sent_ok, message = main.run_digest(
        {
            "resend_api_key": "rk",
            "from_email": "",  # missing sender
            "recipient_email": "r@x",
            "highlights_file": "/nonexistent.json",
        }
    )
    assert sent == []
    assert sent_ok is False and "sender address" in message


# --- run_digest: echoed highlights are recorded in history -------------------

def test_echoed_highlights_recorded(tmp_path, monkeypatch):
    import resend

    hp = tmp_path / "highlights.json"
    histp = tmp_path / "history.json"
    hp.write_text(
        json.dumps(
            {
                "totalBooks": 2,
                "totalHighlights": 2,
                "books": [
                    {"title": "BookA", "author": "AA", "coverUrl": None, "highlights": [{"text": "alpha"}]},
                    {"title": "BookB", "author": "BB", "coverUrl": None, "highlights": [{"text": "beta"}]},
                ],
            }
        )
    )
    monkeypatch.setattr(resend.Emails, "send", lambda payload: {"id": "1"})
    monkeypatch.setattr(
        main,
        "find_echo",
        lambda selections, key, model: {
            "highlight_a": {"text": "alpha", "book_title": "BookA", "book_author": "AA"},
            "highlight_b": {"text": "beta", "book_title": "BookB", "book_author": "BB"},
            "explanation": "x",
        },
    )

    cfg = {
        "highlights_file": str(hp),
        "history_file": str(histp),
        "design_file": str(tmp_path / "design.md"),
        "resend_api_key": "rk",
        "from_email": "f@x",
        "recipient_email": "r@x",
        "anthropic_api_key": "ak",
        "books_per_email": 2,
        "highlights_per_book": 1,
        "show_echo": True,
        "show_revisit": False,
        "subject_template": None,
    }
    assert main.run_digest(cfg)[0] is True

    log = history.load_history(str(histp))["highlight_log"]
    assert history.get_highlight_id("BookA", "alpha") in log
    assert history.get_highlight_id("BookB", "beta") in log


# --- subject builder: templates cannot reach attributes or crash ------------

@pytest.mark.parametrize("template", ["{book1.x}", "{book1.upper}", "{book1[0]}", "{count:d}", "{", "{unknown}"])
def test_subject_template_never_raises_or_leaks(template):
    out = email_builder.build_subject([{"title": "A"}, {"title": "B"}], template)
    assert isinstance(out, str) and out
    assert "built-in method" not in out


def test_subject_replaces_every_placeholder():
    out = email_builder.build_subject(
        [{"title": "A"}, {"title": "B"}], "{book1}|{book2}|{book_list}|{count}"
    )
    assert out == "A|B|A & B|2"
