"""Digest pipeline tests: selection, revisit, echo and email building.

No network: the Anthropic client and resend are replaced with fakes.
"""

import json
from datetime import datetime
from types import SimpleNamespace

import pytz

import digest
import history
import insights
import main

TWO_BOOKS = [
    {"title": "BookA", "author": "AA", "highlights": [{"text": "alpha"}]},
    {"title": "BookB", "author": "BB", "highlights": [{"text": "beta"}]},
]


def _reply(text: str, stop_reason: str = "end_turn"):
    """A Messages API response shape: thinking (empty) then the text block."""
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
    )


def _fake_anthropic(reply: str, calls: list):
    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.messages = self

        def create(self, **kwargs):
            return _reply(reply)

    return FakeClient


# --- echo ---------------------------------------------------------------------

def test_find_echo_parses_reply_and_bounds_the_call(monkeypatch):
    calls = []
    reply = 'Here you go:\n```json\n{"a": 0, "b": 1, "explanation": "Both."}\n```'
    monkeypatch.setattr(insights.anthropic, "Anthropic", _fake_anthropic(reply, calls))

    echo = insights.find_echo(TWO_BOOKS, "key")

    assert echo["highlight_a"] == {"text": "alpha", "book_title": "BookA", "book_author": "AA"}
    assert echo["highlight_b"]["book_title"] == "BookB"
    assert echo["explanation"] == "Both."
    assert calls[0]["timeout"] == 30.0 and calls[0]["max_retries"] == 1


def test_find_echo_rejects_same_book_pair(monkeypatch):
    books = [{"title": "BookA", "author": "AA", "highlights": [{"text": "a1"}, {"text": "a2"}]},
             {"title": "BookB", "author": "BB", "highlights": [{"text": "b1"}]}]
    reply = '{"a": 0, "b": 1, "explanation": "x"}'
    monkeypatch.setattr(insights.anthropic, "Anthropic", _fake_anthropic(reply, []))
    assert insights.find_echo(books, "key") is None


# --- build_email ----------------------------------------------------------------

def _cfg(tmp_path, books=TWO_BOOKS, **overrides) -> dict:
    hp = tmp_path / "highlights.json"
    hp.write_text(json.dumps({"totalBooks": len(books), "totalHighlights": 2, "books": books}))
    cfg = {
        "highlights_file": str(hp),
        "history_file": str(tmp_path / "history.json"),
        "design_file": str(tmp_path / "design.md"),
        "books_per_email": 2,
        "highlights_per_book": 3,
        "timezone": "Europe/Berlin",
        "show_echo": True,
        "show_revisit": True,
        "show_covers": True,
        "subject_template": None,
        "anthropic_api_key": "",
    }
    cfg.update(overrides)
    return cfg


def test_preview_echo_needs_api_key(tmp_path):
    # Regression: the preview showed a sample Echo even when production
    # could not produce one.
    assert main.build_email(_cfg(tmp_path), for_preview=True)["echo"] is None
    with_key = main.build_email(_cfg(tmp_path, anthropic_api_key="k"), for_preview=True)
    assert with_key["echo"] is not None


def test_header_date_uses_configured_timezone(tmp_path, monkeypatch):
    # 22:00 UTC on 1 Jan is already 2 Jan in Tokyo.
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, 22, 0, tzinfo=pytz.utc).astimezone(tz)

    monkeypatch.setattr(main, "datetime", FixedDatetime)
    html = main.build_email(_cfg(tmp_path, timezone="Asia/Tokyo"))["html"]
    assert "Friday, 02 January 2026" in html
    html = main.build_email(_cfg(tmp_path, timezone="Europe/Berlin"))["html"]
    assert "Thursday, 01 January 2026" in html


# --- selection ----------------------------------------------------------------------

def test_selection_skips_empty_books_and_caps_counts():
    data = {"books": [
        {"title": "Empty", "author": "E", "highlights": []},
        {"title": "Small", "author": "S", "highlights": [{"text": "one"}]},
        {"title": "Big", "author": "B", "highlights": [{"text": str(i)} for i in range(10)]},
    ]}
    picked = digest.select_books_and_highlights(data, n_books=5, n_highlights=3)
    assert sorted(b["title"] for b in picked) == ["Big", "Small"]
    sizes = {b["title"]: len(b["highlights"]) for b in picked}
    assert sizes == {"Big": 3, "Small": 1}


# --- revisit ------------------------------------------------------------------------

TODAY = datetime(2026, 6, 1).date()

REVISIT_DATA = {"books": [
    {"title": "A", "author": "AA", "highlights": [{"text": "a1"}, {"text": "a2"}]},
    {"title": "B", "author": "BB", "highlights": [{"text": "b1"}]},
]}


def _log(**entries):
    return {"highlight_log": {history.get_highlight_id(*k.split("_")): v for k, v in entries.items()}}


def test_revisit_prefers_never_seen_and_skips_today():
    today_ids = {history.get_highlight_id("A", "a1")}
    seen_long_ago = {"first_sent": "2020-01-01", "last_sent": "2020-01-01"}
    hist = _log(B_b1=seen_long_ago)
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, hist, today_ids, today=TODAY)
    assert (r["book_title"], r["highlight"]["text"], r["first_sent"]) == ("A", "a2", None)


def test_revisit_picks_randomly_among_never_seen(monkeypatch):
    monkeypatch.setattr(history.random, "choice", lambda items: items[-1])
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, {"highlight_log": {}}, set(), today=TODAY)
    assert r["highlight"]["text"] == "b1"  # the last candidate, not file order


def test_revisit_falls_back_to_oldest_seen():
    hist = _log(
        A_a1={"first_sent": "2020-01-01", "last_sent": "2021-06-01"},
        A_a2={"first_sent": "2020-01-01", "last_sent": "2020-02-01"},
        B_b1={"first_sent": "2020-01-01", "last_sent": "2022-01-01"},
    )
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, hist, set(), today=TODAY)
    assert r["highlight"]["text"] == "a2" and r["first_sent"] == "2020-01-01"


def test_revisit_none_when_everything_is_recent():
    today = TODAY.isoformat()
    recent = {"first_sent": today, "last_sent": today}
    hist = _log(A_a1=recent, A_a2=recent, B_b1=recent)
    assert history.get_unseen_or_old_highlight(REVISIT_DATA, hist, set(), today=TODAY) is None


# --- subject and dates ----------------------------------------------------------

def test_subject_keeps_book_names_when_echo_takes_every_highlight(tmp_path):
    # Regression: with one highlight per book the Echo removed both books from
    # the list, and the subject fell back to "Your Daily Highlights".
    cfg = _cfg(tmp_path, highlights_per_book=1, anthropic_api_key="k", show_revisit=False)
    built = main.build_email(cfg, for_preview=True)
    assert built["echo"] is not None and built["selections"] == []
    assert "BookA" in built["subject"] and "BookB" in built["subject"]


class _LateEveningUTC(datetime):
    # 23:30 UTC on 1 Jan is already 2 Jan in Berlin.
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 1, 1, 23, 30, tzinfo=pytz.utc).astimezone(tz)


def test_history_dates_use_configured_timezone(tmp_path, monkeypatch):
    import resend

    monkeypatch.setattr(main, "datetime", _LateEveningUTC)
    monkeypatch.setattr(resend.Emails, "send", lambda payload: {"id": "1"})
    cfg = _cfg(tmp_path, timezone="Europe/Berlin", show_echo=False, show_revisit=False,
               resend_api_key="rk", from_email="f@x", recipient_email="r@x")
    assert main.run_digest(cfg)[0] is True
    log = history.load_history(cfg["history_file"])["highlight_log"]
    assert {e["last_sent"] for e in log.values()} == {"2026-01-02"}


def test_revisit_cutoff_counts_from_the_given_day():
    hist = _log(A_a1={"first_sent": "2026-01-01", "last_sent": "2026-01-01"},
                A_a2={"first_sent": "2026-01-01", "last_sent": "2026-01-01"},
                B_b1={"first_sent": "2026-01-01", "last_sent": "2026-01-01"})
    assert history.get_unseen_or_old_highlight(REVISIT_DATA, hist, set(), today=datetime(2026, 1, 30).date()) is None
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, hist, set(), today=datetime(2026, 2, 1).date())
    assert r is not None


# --- echo model and failures ------------------------------------------------------

def _api_error(cls, status):
    try:
        import httpx2 as httpx  # anthropic 1.x
    except ImportError:
        import httpx  # anthropic 0.x
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def _raising_anthropic(error):
    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = self

        def create(self, **kwargs):
            raise error

    return FakeClient


def test_find_echo_uses_the_given_model(monkeypatch):
    seen = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = self

        def create(self, **kwargs):
            seen.append(kwargs["model"])
            return _reply('{"a": 0, "b": 1, "explanation": "x"}')

    monkeypatch.setattr(insights.anthropic, "Anthropic", FakeClient)
    assert insights.find_echo(TWO_BOOKS, "key", model="some-model") is not None
    assert seen == ["some-model"]


def test_find_echo_reports_a_missing_model(monkeypatch):
    import anthropic
    import pytest

    error = _api_error(anthropic.NotFoundError, 404)
    monkeypatch.setattr(insights.anthropic, "Anthropic", _raising_anthropic(error))
    with pytest.raises(insights.EchoUnavailable, match="old-model.*ECHO_MODEL"):
        insights.find_echo(TWO_BOOKS, "key", model="old-model")


def test_find_echo_reports_other_api_errors(monkeypatch):
    import anthropic
    import pytest

    error = _api_error(anthropic.InternalServerError, 500)
    monkeypatch.setattr(insights.anthropic, "Anthropic", _raising_anthropic(error))
    with pytest.raises(insights.EchoUnavailable):
        insights.find_echo(TWO_BOOKS, "key")


def test_digest_still_sends_and_reports_a_failed_echo(tmp_path, monkeypatch):
    import resend

    sent = []
    monkeypatch.setattr(resend.Emails, "send", lambda payload: sent.append(payload) or {"id": "1"})

    def failing_echo(selections, key, model):
        raise insights.EchoUnavailable("model gone")

    monkeypatch.setattr(main, "find_echo", failing_echo)
    cfg = _cfg(tmp_path, anthropic_api_key="k", resend_api_key="rk",
               from_email="f@x", recipient_email="r@x", echo_model="m")
    ok, message = main.run_digest(cfg)
    assert ok is True and len(sent) == 1
    assert "Echo skipped: model gone" in message


def test_echo_model_comes_from_the_environment(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "c.json"))
    monkeypatch.delenv("ECHO_MODEL", raising=False)
    assert config.get_runtime_config()["echo_model"] == insights.DEFAULT_MODEL
    monkeypatch.setenv("ECHO_MODEL", "claude-x")
    assert config.get_runtime_config()["echo_model"] == "claude-x"


def test_find_echo_returns_none_on_refusal(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = self

        def create(self, **kwargs):
            return _reply("", stop_reason="refusal")

    monkeypatch.setattr(insights.anthropic, "Anthropic", FakeClient)
    assert insights.find_echo(TWO_BOOKS, "key") is None
