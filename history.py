import hashlib
import json
import logging
import os
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from digest import book_author, book_title, normalize_highlight

logger = logging.getLogger(__name__)


def load_history(path: str) -> dict:
    try:
        p = Path(path)
        if not p.exists():
            return {"highlight_log": {}}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("highlight_log"), dict):
            raise ValueError("unexpected schema")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Could not load history from %s (%s) — starting fresh", path, e)
        return {"highlight_log": {}}


def save_history(history: dict, path: str) -> None:
    try:
        p = Path(path)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(history, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        logger.error("Could not save history to %s: %s", path, e)


def get_highlight_id(book_title: str, highlight_text: str) -> str:
    raw = f"{book_title}\x00{highlight_text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def get_unseen_or_old_highlight(
    data: dict,
    history: dict,
    today_ids: set,
    cutoff_days: int = 30,
) -> Optional[dict]:
    log = history.get("highlight_log", {})
    cutoff = date.today() - timedelta(days=cutoff_days)

    never_seen = []
    old_seen = []

    for book in data.get("books", []):
        title = book_title(book)
        author = book_author(book)
        for h in book.get("highlights", []):
            hid = get_highlight_id(title, h["text"])
            if hid in today_ids:
                continue
            last = _last_sent(log.get(hid))
            if last is None:
                never_seen.append((title, author, h, None))
            elif last < cutoff:
                old_seen.append((title, author, h, log[hid].get("first_sent"), last))

    if never_seen:
        # Random, not file order: taking the first entry walked the library
        # book by book, so Revisit came from the same book for weeks.
        title, author, h, _ = random.choice(never_seen)
        return _make_revisit(title, author, h, first_sent=None)

    if old_seen:
        old_seen.sort(key=lambda x: x[4])
        title, author, h, first_sent, _ = old_seen[0]
        return _make_revisit(title, author, h, first_sent=first_sent)

    return None


def _last_sent(entry) -> Optional[date]:
    """The entry's last send date, or None when the entry is missing or
    damaged. A damaged entry then counts as never seen and is rewritten on
    the next send."""
    if not isinstance(entry, dict):
        return None
    try:
        return date.fromisoformat(entry["last_sent"])
    except (KeyError, TypeError, ValueError):
        return None


def _make_revisit(title: str, author: str, h: dict, first_sent: Optional[str]) -> dict:
    return {
        "book_title": title,
        "book_author": author,
        "highlight": normalize_highlight(h),
        "first_sent": first_sent,
    }


def record_sent_highlights(history: dict, sent_highlights: list) -> None:
    today_str = date.today().isoformat()
    log = history.setdefault("highlight_log", {})
    for item in sent_highlights:
        hid = item["id"]
        entry = log.get(hid)
        if _last_sent(entry) is None:
            # New, or damaged in any way: start the entry over.
            log[hid] = {"first_sent": today_str, "last_sent": today_str}
        else:
            entry["last_sent"] = today_str
