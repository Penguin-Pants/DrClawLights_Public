"""Input checks at the trust boundaries: the highlights file, settings from
the environment or config.json, and the history file."""

import json

import pytest

import config
import digest
import email_builder
import history
import main


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))
    for name in ("BOOKS_PER_EMAIL", "HIGHLIGHTS_PER_BOOK"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


# --- highlights file: odd field types must not crash the digest -------------

ODD_DATA = {
    "totalBooks": 1,
    "totalHighlights": 1,
    "books": [
        {
            "title": None,
            "author": 42,
            "coverUrl": ["not", "a", "url"],
            "highlights": [{"text": "x", "location": 1234, "note": 7, "color": ["pink"]}],
        }
    ],
}


def test_odd_field_types_pass_validation_and_render():
    assert digest.validate_highlights(ODD_DATA) is None
    selections = digest.select_books_and_highlights(ODD_DATA, 1, 1)
    html = email_builder.build_html(selections, ODD_DATA)
    assert "Unknown Title" in html and "42" in html and "1234" in html


def test_odd_field_types_render_in_revisit():
    r = history.get_unseen_or_old_highlight(ODD_DATA, {"highlight_log": {}}, set())
    assert r["book_title"] == "Unknown Title"
    html = email_builder.build_html([], ODD_DATA, revisit=r)
    assert "Unknown Title" in html


def test_selection_and_revisit_use_the_same_highlight_id():
    sel = digest.select_books_and_highlights(ODD_DATA, 1, 1)
    today_ids = {history.get_highlight_id(sel[0]["title"], sel[0]["highlights"][0]["text"])}
    assert history.get_unseen_or_old_highlight(ODD_DATA, {"highlight_log": {}}, today_ids) is None


# --- settings: ranges apply to every source ---------------------------------

@pytest.mark.parametrize("raw", ["-1", "0", "abc"])
def test_out_of_range_env_seed_falls_back_to_default(tmp_config, monkeypatch, raw):
    monkeypatch.setenv("BOOKS_PER_EMAIL", raw)
    assert config.load_settings()["books_per_email"] == config.DEFAULTS["books_per_email"]


@pytest.mark.parametrize("key, value", [("send_hour", 25), ("send_minute", -1), ("highlights_per_book", 0)])
def test_out_of_range_stored_value_falls_back_to_default(tmp_config, key, value):
    (tmp_config / "config.json").write_text(json.dumps({key: value}))
    assert config.load_settings()[key] == config.DEFAULTS[key]


def test_in_range_values_are_kept(tmp_config, monkeypatch):
    monkeypatch.setenv("BOOKS_PER_EMAIL", "5")
    (tmp_config / "config.json").write_text(json.dumps({"send_hour": 23, "send_minute": 59}))
    s = config.load_settings()
    assert (s["books_per_email"], s["send_hour"], s["send_minute"]) == (5, 23, 59)


def test_bad_env_seed_does_not_break_the_digest(tmp_config, tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKS_PER_EMAIL", "-1")
    monkeypatch.setenv("HIGHLIGHTS_FILE", str(tmp_path / "h.json"))
    monkeypatch.setenv("HISTORY_FILE", str(tmp_path / "hist.json"))
    monkeypatch.setenv("DESIGN_FILE", str(tmp_path / "d.md"))
    (tmp_path / "h.json").write_text(json.dumps(ODD_DATA))
    assert main.build_email(config.get_runtime_config(), for_preview=True) is not None


# --- history file: damaged content starts fresh or is skipped ---------------

@pytest.mark.parametrize("content", ["[]", '"text"', "null", '{"highlight_log": []}'])
def test_damaged_history_starts_fresh(tmp_path, content):
    p = tmp_path / "history.json"
    p.write_text(content)
    assert history.load_history(str(p)) == {"highlight_log": {}}


REVISIT_DATA = {"books": [{"title": "A", "author": "AA", "highlights": [{"text": "a1"}]}]}


@pytest.mark.parametrize(
    "entry",
    ["oops", {}, {"first_sent": "2020-01-01"}, {"first_sent": "2020-01-01", "last_sent": "bad"}],
)
def test_damaged_history_entry_counts_as_never_seen(entry):
    hid = history.get_highlight_id("A", "a1")
    r = history.get_unseen_or_old_highlight(REVISIT_DATA, {"highlight_log": {hid: entry}}, set())
    assert r["highlight"]["text"] == "a1" and r["first_sent"] is None


def test_record_overwrites_damaged_entry():
    hid = history.get_highlight_id("A", "a1")
    hist = {"highlight_log": {hid: "oops"}}
    history.record_sent_highlights(hist, [{"id": hid}])
    assert set(hist["highlight_log"][hid]) == {"first_sent", "last_sent"}
