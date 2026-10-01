import argparse
import logging
import sys
from datetime import datetime

import resend

from config import get_runtime_config, resolve_timezone
from digest import load_highlights, select_books_and_highlights
from email_builder import build_html, build_subject, load_design_tokens
from history import (
    get_highlight_id,
    get_unseen_or_old_highlight,
    load_history,
    record_sent_highlights,
    save_history,
)
from insights import find_echo

def configure_logging() -> None:
    """Send INFO and below to stdout and WARNING and above to stderr.

    Railway tags every stderr line as an error, so routine lines must not go
    there (Python's default); real warnings and errors still do.
    """
    to_stdout = logging.StreamHandler(sys.stdout)
    to_stdout.addFilter(lambda record: record.levelno < logging.WARNING)
    to_stderr = logging.StreamHandler(sys.stderr)
    to_stderr.setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[to_stdout, to_stderr],
    )


configure_logging()
logger = logging.getLogger(__name__)


def _sample_echo(selections: list[dict]) -> dict | None:
    """A representative Echo block for the dashboard preview.

    The live digest calls the Anthropic API to find a genuine cross-book
    connection; that is too slow and costly to run on every preview refresh, so
    the preview instead pairs the first highlight of the first two books and
    labels the section clearly.
    """
    if len(selections) < 2:
        return None
    a_book, b_book = selections[0], selections[1]
    if not a_book["highlights"] or not b_book["highlights"]:
        return None
    a, b = a_book["highlights"][0], b_book["highlights"][0]
    return {
        "highlight_a": {"text": a["text"], "book_title": a_book["title"], "book_author": a_book["author"]},
        "highlight_b": {"text": b["text"], "book_title": b_book["title"], "book_author": b_book["author"]},
        "explanation": "Preview — in the live digest, AI finds a real thematic connection between two highlights.",
    }


def build_email(config: dict, *, for_preview: bool = False) -> dict | None:
    """Select highlights and render the digest email.

    Returns a dict with ``subject``, ``html`` and the supporting pieces, or
    ``None`` when there is nothing to send. Performs no I/O beyond reading the
    highlights/history/design files; sending and history writes are the
    caller's job (see ``run_digest``).
    """
    data = load_highlights(config["highlights_file"])
    if data is None:
        return None

    selections = select_books_and_highlights(
        data,
        n_books=config["books_per_email"],
        n_highlights=config["highlights_per_book"],
    )
    if not selections:
        logger.warning("No highlights selected — nothing to send")
        return None

    history = load_history(config["history_file"])
    today_ids = {
        get_highlight_id(b["title"], h["text"])
        for b in selections
        for h in b["highlights"]
    }

    revisit = None
    if config.get("show_revisit", True):
        revisit = get_unseen_or_old_highlight(data, history, today_ids)

    echo = None
    if config.get("show_echo", True):
        if for_preview:
            # Mirror production: without a key the real email has no Echo.
            echo = _sample_echo(selections) if config.get("anthropic_api_key") else None
        else:
            api_key = config["anthropic_api_key"]
            if api_key and len(selections) >= 2:
                echo = find_echo(selections, api_key)
            elif not api_key:
                logger.info("ANTHROPIC_API_KEY not set — skipping echo section")

    if echo:
        echo_texts = {
            (echo["highlight_a"]["book_title"], echo["highlight_a"]["text"]),
            (echo["highlight_b"]["book_title"], echo["highlight_b"]["text"]),
        }
        filtered = []
        for book in selections:
            remaining = [h for h in book["highlights"] if (book["title"], h["text"]) not in echo_texts]
            if remaining:
                filtered.append({**book, "highlights": remaining})
        selections = filtered

    tokens = load_design_tokens(config.get("design_file"))
    # The header date follows the configured timezone, not the server clock
    # (UTC on Railway), which can be a day off for zones far from UTC.
    today = datetime.now(resolve_timezone(config.get("timezone"))).date()
    html = build_html(
        selections,
        metadata=data,
        echo=echo,
        revisit=revisit,
        tokens=tokens,
        show_covers=config.get("show_covers", True),
        today=today,
    )
    subject = build_subject(selections, config.get("subject_template"))

    return {
        "subject": subject,
        "html": html,
        "selections": selections,
        "echo": echo,
        "revisit": revisit,
        "history": history,
        "config": config,
    }


def run_digest(config: dict) -> tuple[bool, str]:
    """Build, send and record one digest.

    Returns ``(sent, message)``: whether an email went out, plus a short
    outcome for the dashboard. Nothing-to-send cases return ``False``; send
    failures raise.
    """
    logger.info("Running digest job")

    missing = [
        name
        for name, value in (
            ("RESEND_API_KEY", config.get("resend_api_key")),
            ("sender address", config.get("from_email")),
            ("recipient address", config.get("recipient_email")),
        )
        if not value
    ]
    if missing:
        logger.error("Cannot send digest — not configured: %s", ", ".join(missing))
        return False, f"Not configured: {', '.join(missing)}."

    built = build_email(config)
    if built is None:
        return False, "Nothing to send: no highlights file, or no book in it has highlights."

    selections = built["selections"]
    revisit = built["revisit"]
    echo = built["echo"]
    history = built["history"]

    resend.api_key = config["resend_api_key"]
    response = resend.Emails.send(
        {
            "from": config["from_email"],
            "to": config["recipient_email"],
            "subject": built["subject"],
            "html": built["html"],
        }
    )
    for book in selections:
        logger.info(
            "Selected: %r — %d highlight(s): %s",
            book["title"],
            len(book["highlights"]),
            " | ".join(h["text"][:60] for h in book["highlights"]),
        )
    logger.info("Email sent — id=%s subject=%r", response.get("id"), built["subject"])

    all_sent = [
        {"id": get_highlight_id(b["title"], h["text"]), **h}
        for b in selections
        for h in b["highlights"]
    ]
    if revisit:
        rid = get_highlight_id(revisit["book_title"], revisit["highlight"]["text"])
        all_sent.append({"id": rid, **revisit["highlight"]})
    if echo:
        # The echoed highlights were pulled out of `selections` so they only
        # render once (in the Echo block), but they were still sent — record
        # them so they are not resurfaced as unseen revisits or future echoes.
        for side in ("highlight_a", "highlight_b"):
            e = echo[side]
            eid = get_highlight_id(e["book_title"], e["text"])
            all_sent.append({"id": eid, "text": e["text"]})
    record_sent_highlights(history, all_sent)
    save_history(history, config["history_file"])
    return True, f"Sent: {built['subject']}"


def main() -> None:
    parser = argparse.ArgumentParser(description="DrClawLights highlights digest")
    parser.add_argument(
        "--send-now",
        action="store_true",
        help="Send the digest immediately instead of waiting for the scheduled time",
    )
    args = parser.parse_args()

    config = get_runtime_config()

    if args.send_now:
        run_digest(config)
        return

    # Standalone scheduler mode. The Railway deployment runs the web app
    # (app.py), which owns the scheduler; this path remains for local use.
    from apscheduler.schedulers.blocking import BlockingScheduler

    tz = resolve_timezone(config["timezone"])
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        run_digest, "cron",
        hour=config["send_hour"], minute=config["send_minute"], args=[config],
    )
    logger.info(
        "Scheduler started — digest will run daily at %02d:%02d %s",
        config["send_hour"], config["send_minute"], config["timezone"],
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
