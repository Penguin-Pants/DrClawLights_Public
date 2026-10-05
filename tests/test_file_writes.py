"""File writes: atomic, unique temp names, and safe under concurrent saves."""

import threading

import pytest

import config
import storage


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))
    return tmp_path


def _run_threads(target, n):
    errors = []

    def wrap(i):
        try:
            target(i)
        except Exception as e:  # noqa: BLE001 — collected and asserted below
            errors.append(e)

    threads = [threading.Thread(target=wrap, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_concurrent_settings_saves_keep_every_update(tmp_config):
    # Regression: two saves shared "config.tmp" (one os.replace then failed)
    # and each read-modify-write could drop the other's change.
    keys = ["show_echo", "show_revisit", "show_covers"]
    config.save_settings({k: True for k in keys})

    def save(i):
        for _ in range(30):
            config.save_settings({keys[i % 3]: False, "from_email": f"t{i}@x"})

    assert _run_threads(save, 12) == []
    s = config.load_settings()
    assert [s[k] for k in keys] == [False, False, False]
    assert not list(tmp_config.glob("*.tmp"))


def test_atomic_write_replaces_file_and_leaves_no_temp(tmp_path):
    p = tmp_path / "sub" / "file.md"
    storage.atomic_write(p, "one")
    storage.atomic_write(p, b"two")
    assert p.read_text() == "two"
    assert [f.name for f in p.parent.iterdir()] == ["file.md"]


def test_atomic_write_keeps_old_file_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "file.md"
    p.write_text("old")

    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.atomic_write(p, "new")
    assert p.read_text() == "old"
    assert [f.name for f in tmp_path.iterdir()] == ["file.md"]


def test_concurrent_digests_keep_both_history_updates(tmp_path, monkeypatch):
    # Regression: Send Now and the scheduled job each loaded history, sent,
    # then saved, so the later save dropped the earlier run's highlights.
    import json
    import time

    import history
    import main
    import resend

    # Each thread sends from its own highlights file into the shared history.
    def cfg(i):
        books = [{"title": f"B{i}-{n}", "author": "A", "highlights": [{"text": "t"}]} for n in range(3)]
        (tmp_path / f"h{i}.json").write_text(json.dumps({"books": books}))
        return {
            "highlights_file": str(tmp_path / f"h{i}.json"),
            "history_file": str(tmp_path / "history.json"),
            "design_file": None,
            "resend_api_key": "rk", "from_email": "f@x", "recipient_email": "r@x",
            "anthropic_api_key": "", "books_per_email": 3, "highlights_per_book": 1,
            "show_echo": False, "show_revisit": False, "timezone": "UTC", "subject_template": None,
        }

    configs = [cfg(0), cfg(1)]
    monkeypatch.setattr(resend.Emails, "send", lambda payload: time.sleep(0.2) or {"id": "1"})
    assert _run_threads(lambda i: main.run_digest(configs[i]), 2) == []
    assert len(history.load_history(str(tmp_path / "history.json"))["highlight_log"]) == 6


def test_failed_design_seed_leaves_no_partial_file(tmp_path, monkeypatch):
    # Regression: a copy that failed midway left a partial design.md, and
    # the next startup skipped the seed because the file existed.
    import seed

    dest = tmp_path / "design.md"
    monkeypatch.setenv("DESIGN_FILE", str(dest))

    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    seed.ensure_design_file()
    assert not dest.exists()

    monkeypatch.undo()
    monkeypatch.setenv("DESIGN_FILE", str(dest))
    seed.ensure_design_file()
    assert dest.read_bytes() == seed._BUNDLED_DESIGN.read_bytes()
