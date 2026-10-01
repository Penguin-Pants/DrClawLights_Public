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


def _fake_anthropic(reply: str, calls: list):
    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.messages = self

        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(text=reply)])

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
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, hist, today_ids)
    assert (r["book_title"], r["highlight"]["text"], r["first_sent"]) == ("A", "a2", None)


def test_revisit_picks_randomly_among_never_seen(monkeypatch):
    monkeypatch.setattr(history.random, "choice", lambda items: items[-1])
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, {"highlight_log": {}}, set())
    assert r["highlight"]["text"] == "b1"  # the last candidate, not file order


def test_revisit_falls_back_to_oldest_seen():
    hist = _log(
        A_a1={"first_sent": "2020-01-01", "last_sent": "2021-06-01"},
        A_a2={"first_sent": "2020-01-01", "last_sent": "2020-02-01"},
        B_b1={"first_sent": "2020-01-01", "last_sent": "2022-01-01"},
    )
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, hist, set())
    assert r["highlight"]["text"] == "a2" and r["first_sent"] == "2020-01-01"


def test_revisit_none_when_everything_is_recent():
    today = datetime.now().date().isoformat()
    recent = {"first_sent": today, "last_sent": today}
    hist = _log(A_a1=recent, A_a2=recent, B_b1=recent)
    assert history.get_unseen_or_old_highlight(REVISIT_DATA, hist, set()) is None
