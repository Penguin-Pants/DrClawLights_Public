import json
import logging
import re
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"


def find_echo(selected_books: list, api_key: str) -> Optional[dict]:
    if len(selected_books) < 2:
        return None
    try:
        flat = []
        for book in selected_books:
            for h in book["highlights"]:
                flat.append({
                    "index": len(flat),
                    "book_title": book["title"],
                    "book_author": book["author"],
                    "text": h["text"],
                })

        if len(flat) < 2:
            return None

        highlights_json = json.dumps(
            [{"index": h["index"], "book": h["book_title"], "text": h["text"]} for h in flat],
            ensure_ascii=False,
        )

        prompt = (
            "You are given a list of book highlights from today's reading digest.\n\n"
            f"{highlights_json}\n\n"
            "Find the single most resonant pair of highlights that are from DIFFERENT books "
            "and express the same idea, or are in interesting intellectual dialogue. "
            "Respond with JSON only, no other text:\n"
            '{"a": <index>, "b": <index>, "explanation": "<1-2 sentences connecting the two>"}'
        )

        # The SDK default (10 min timeout, 2 retries) could hold Send Now open
        # for ~30 minutes if the API stalls; Echo is optional, so give up early.
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=1)
        message = client.messages.create(
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            logger.warning("find_echo: no JSON object found in response: %r", raw[:200])
            return None
        result = json.loads(match.group())

        a = flat[int(result["a"])]
        b = flat[int(result["b"])]

        if a["book_title"] == b["book_title"]:
            logger.warning("find_echo: Claude returned two highlights from the same book; skipping")
            return None

        return {
            "highlight_a": {"text": a["text"], "book_title": a["book_title"], "book_author": a["book_author"]},
            "highlight_b": {"text": b["text"], "book_title": b["book_title"], "book_author": b["book_author"]},
            "explanation": result["explanation"],
        }

    except Exception as e:
        logger.warning("find_echo failed: %s", e)
        return None
