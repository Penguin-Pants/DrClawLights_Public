import json
import os
import random
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_highlights(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        logger.warning("Highlights file not found at %s — skipping today's digest", path)
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_highlights(raw: bytes, path: str) -> None:
    """Persist an uploaded highlights file to disk.

    Keeps the highlights file owned by this module (the dashboard upload route
    delegates here rather than writing the file itself). Written via a temp
    file + rename, like config and history, so a concurrent reader never sees
    a half-written file. Raises OSError on failure for the caller to surface.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, p)


def validate_highlights(data) -> str | None:
    """Check that ``data`` has the shape the digest reads (the HighlightsGrabber
    export). Returns a description of the first problem, or None if usable.

    Catches a wrong file at upload time instead of at the next scheduled send.
    """
    if not isinstance(data, dict) or "books" not in data:
        return 'JSON is missing a top-level "books" key.'
    if not isinstance(data["books"], list):
        return 'The "books" value must be a list.'
    for n, book in enumerate(data["books"], start=1):
        if not isinstance(book, dict) or not isinstance(book.get("highlights", []), list):
            return f"Book {n} is not an object with a list of highlights."
        for h in book.get("highlights", []):
            if not isinstance(h, dict) or not isinstance(h.get("text"), str):
                return f"Book {n} has a highlight without text."
    return None


def select_books_and_highlights(data: dict, n_books: int, n_highlights: int) -> list[dict]:
    books_with_highlights = [b for b in data.get("books", []) if b.get("highlights")]
    if not books_with_highlights:
        logger.warning("No books with highlights found in the file")
        return []

    chosen_books = random.sample(books_with_highlights, min(n_books, len(books_with_highlights)))

    result = []
    for book in chosen_books:
        chosen_highlights = random.sample(
            book["highlights"], min(n_highlights, len(book["highlights"]))
        )
        result.append(
            {
                "title": book.get("title", "Unknown Title"),
                "author": book.get("author", "Unknown Author"),
                "coverUrl": book.get("coverUrl"),
                "highlights": [
                    {
                        "text": h["text"],
                        "note": h.get("note"),
                        "location": h.get("location", ""),
                        "color": h.get("color", "yellow"),
                    }
                    for h in chosen_highlights
                ],
            }
        )
    return result
