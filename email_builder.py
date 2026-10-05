import re
from datetime import date
from pathlib import Path

from config import DEFAULT_SUBJECT_TEMPLATE

# Map highlight colours to subtle left-border accents. These represent the
# Kindle highlight colours themselves, so they are intentionally NOT driven by
# the uploaded design tokens.
_COLOUR_MAP = {
    "yellow": "#f5c842",
    "pink": "#f48fb1",
    "blue": "#64b5f6",
    "orange": "#ffb74d",
}

# Fallback design tokens (the Apple reference). Used when no design.md is
# available or a token is missing from the uploaded file.
_DEFAULT_TOKENS = {
    "color-ink": "#1d1d1f",
    "color-graphite": "#707070",
    "color-slate": "#474747",
    "color-fog": "#f5f5f7",
    "color-snow": "#ffffff",
    "color-obsidian": "#000000",
    "color-silver-mist": "#e8e8ed",
    "color-azure": "#0071e3",
    "color-cobalt-link": "#0066cc",
    "radius-card": "28px",
    "font-body": (
        "'SF Pro Text', ui-sans-serif, system-ui, -apple-system, "
        "BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    ),
    "font-display": (
        "'SF Pro Display', ui-sans-serif, system-ui, -apple-system, "
        "BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    ),
}

# How design.md custom-property names map onto our internal token keys.
_TOKEN_ALIASES = {
    "font-sf-pro-text": "font-body",
    "font-sf-pro-display": "font-display",
    "radius-cards": "radius-card",
    "radius-3xl": "radius-card",
}


# Cache of parsed tokens keyed by file path -> (mtime, tokens). The design file
# only changes on upload, so the preview (which fires on every HTMX refresh)
# can reuse the parse until the file's mtime changes.
_TOKEN_CACHE: dict[str, tuple[float, dict]] = {}


def _parse_design_tokens(text: str) -> dict:
    tokens = dict(_DEFAULT_TOKENS)
    for raw_name, raw_value in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", text, re.IGNORECASE):
        name = raw_name.strip().lower()
        value = raw_value.strip()
        if not value or value.startswith("var("):
            continue
        key = _TOKEN_ALIASES.get(name, name)
        if key in tokens:
            tokens[key] = value
    return tokens


def load_design_tokens(path: str | None = None) -> dict:
    """Parse CSS custom properties out of a design.md file.

    Scans every ``--name: value;`` declaration in the file (the Quick Start
    ``:root`` block in the reference design) and maps the ones we care about
    onto internal token keys. Unknown properties are ignored. Always returns a
    complete token set by falling back to the Apple defaults. The parse is
    cached per file and invalidated when the file's mtime changes.
    """
    if not path:
        return dict(_DEFAULT_TOKENS)
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return dict(_DEFAULT_TOKENS)

    cached = _TOKEN_CACHE.get(path)
    if cached and cached[0] == mtime:
        return dict(cached[1])

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return dict(_DEFAULT_TOKENS)

    tokens = _parse_design_tokens(text)
    _TOKEN_CACHE[path] = (mtime, tokens)
    return dict(tokens)


def _build_style(t: dict) -> str:
    """Build the email's <style> block from a resolved token set.

    Token values are baked in as literal hex/strings (not CSS ``var()``) so the
    result renders correctly in email clients, which do not support custom
    properties. Honours the design system's shadow-free, value-contrast
    elevation.
    """
    return f"""
    body {{ margin: 0; padding: 0; background: {t['color-fog']}; font-family: {t['font-body']}; }}
    .wrapper {{ background: {t['color-fog']}; padding: 40px 16px; }}
    .card {{ background: {t['color-snow']}; max-width: 768px; margin: 0 auto; border-radius: {t['radius-card']}; overflow: hidden; }}
    .header {{ background: {t['color-ink']}; padding: 36px 48px; }}
    .header h1 {{ margin: 0; color: {t['color-snow']}; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }}
    .header p {{ margin: 8px 0 0; color: {t['color-silver-mist']}; font-size: 14px; letter-spacing: -0.01em; }}
    .body {{ padding: 40px 48px; }}
    .book-section {{ margin-bottom: 44px; }}
    .book-section:last-child {{ margin-bottom: 0; }}
    .book-meta {{ display: flex; align-items: flex-start; gap: 16px; margin-bottom: 20px; }}
    .book-cover {{ width: 64px; min-width: 64px; height: 88px; object-fit: cover; border-radius: 8px; }}
    .book-info {{ flex: 1; }}
    .book-title {{ margin: 0 0 4px; font-size: 20px; color: {t['color-ink']}; font-weight: 700; letter-spacing: -0.02em; }}
    .book-author {{ margin: 0; font-size: 14px; color: {t['color-graphite']}; }}
    .highlight-block {{ border-left: 3px solid {t['color-silver-mist']}; padding: 14px 18px; margin-bottom: 16px; border-radius: 0 8px 8px 0; background: {t['color-fog']}; }}
    .highlight-text {{ margin: 0; font-size: 17px; line-height: 1.5; color: {t['color-ink']}; letter-spacing: -0.01em; }}
    .highlight-note {{ margin: 12px 0 0; font-size: 14px; color: {t['color-slate']}; }}
    .highlight-note span {{ color: {t['color-graphite']}; }}
    .highlight-location {{ margin: 8px 0 0; font-size: 12px; color: {t['color-graphite']}; }}
    .divider {{ border: none; border-top: 1px solid {t['color-silver-mist']}; margin: 36px 0; }}
    .footer {{ background: {t['color-fog']}; padding: 24px 48px; border-top: 1px solid {t['color-silver-mist']}; }}
    .footer p {{ margin: 0; font-size: 12px; color: {t['color-graphite']}; line-height: 1.5; }}
    .echo-section {{ margin: 0 0 32px; padding: 24px; background: {t['color-fog']}; border-radius: {t['radius-card']}; }}
    .echo-label {{ margin: 0 0 16px; font-size: 12px; color: {t['color-graphite']}; letter-spacing: 0.08em; text-transform: uppercase; }}
    .echo-pair {{ display: flex; gap: 14px; margin-bottom: 16px; }}
    .echo-card {{ flex: 1; background: {t['color-snow']}; border-radius: 16px; padding: 16px; }}
    .echo-card p {{ margin: 0 0 8px; font-size: 15px; line-height: 1.5; color: {t['color-ink']}; }}
    .echo-card small {{ font-size: 12px; color: {t['color-graphite']}; }}
    .echo-explanation {{ margin: 0; font-size: 14px; color: {t['color-slate']}; line-height: 1.5; }}
    .revisit-section {{ margin: 0 0 32px; padding: 22px 24px; background: {t['color-fog']}; border-radius: {t['radius-card']}; }}
    .revisit-label {{ margin: 0 0 12px; font-size: 12px; color: {t['color-graphite']}; letter-spacing: 0.08em; text-transform: uppercase; }}
    .revisit-meta {{ margin: 10px 0 0; font-size: 12px; color: {t['color-graphite']}; }}
    @media only screen and (max-width: 640px) {{
        .wrapper {{ padding: 0 !important; }}
        .card {{ border-radius: 0 !important; }}
        .header {{ padding: 28px 24px !important; }}
        .body {{ padding: 28px 24px !important; }}
        .footer {{ padding: 20px 24px !important; }}
        .echo-section {{ padding: 18px !important; }}
        .echo-pair {{ flex-direction: column !important; }}
        .revisit-section {{ padding: 18px !important; }}
    }}
""".strip()


_PLACEHOLDER_RE = re.compile(r"\{(book1|book2|book_list|count)\}")


def build_subject(selections: list[dict], template: str | None = None) -> str:
    template = (template or DEFAULT_SUBJECT_TEMPLATE).strip()
    if not selections:
        return "Your Daily Highlights"

    titles = [s["title"] for s in selections]
    fields = {
        "book1": titles[0],
        "book2": titles[1] if len(titles) > 1 else "",
        "book_list": " & ".join(titles),
        "count": str(len(titles)),
    }
    # Replace only the known placeholders. str.format would also run attribute
    # and index lookups such as "{book1.x}" from the user-edited template, and
    # a failing lookup raised on every render. Other text stays as typed.
    subject = _PLACEHOLDER_RE.sub(lambda m: fields[m.group(1)], template)

    if len(titles) == 1:
        # Drop a trailing punctuation separator left by an unfilled {book2}
        # placeholder. Limited to punctuation so we never trim a word or hyphen
        # that is genuinely part of a single book's title.
        subject = re.sub(r"\s*[&,/–—]\s*$", "", subject).strip()
    return subject or "Your Daily Highlights"


def build_html(
    selections: list[dict],
    metadata: dict,
    *,
    echo: dict | None = None,
    revisit: dict | None = None,
    tokens: dict | None = None,
    show_covers: bool = True,
    today: date | None = None,
) -> str:
    tokens = tokens or _DEFAULT_TOKENS
    date_line = (today or date.today()).strftime("%A, %d %B %Y")
    total_books = _esc(str(metadata.get("totalBooks", "—")))
    total_highlights = _esc(str(metadata.get("totalHighlights", "—")))

    book_sections = "\n".join(_render_book(b, show_covers=show_covers) for b in selections)

    special_parts = []
    if echo:
        special_parts.append(_render_echo(echo))
    if revisit:
        special_parts.append(_render_revisit(revisit))
    if special_parts:
        special_parts.append('<hr class="divider">')
    special_html = "\n".join(special_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your Daily Highlights</title>
<style>{_build_style(tokens)}</style>
</head>
<body>
<div class="wrapper">
  <div class="card">
    <div class="header">
      <h1>Your Daily Highlights</h1>
      <p>{date_line}</p>
    </div>
    <div class="body">
      {special_html}
      {book_sections}
    </div>
    <div class="footer">
      <p>Your library: {total_books} books &middot; {total_highlights} highlights<br>
      Sent by DrClawLights &mdash; your personal highlights digest.</p>
    </div>
  </div>
</div>
</body>
</html>"""


def _render_echo(echo: dict) -> str:
    a = echo["highlight_a"]
    b = echo["highlight_b"]
    return f"""<div class="echo-section">
  <p class="echo-label">Echo &mdash; same idea, different books</p>
  <div class="echo-pair">
    <div class="echo-card">
      <p>&ldquo;{_esc(a["text"])}&rdquo;</p>
      <small>{_esc(a["book_title"])} &mdash; {_esc(a["book_author"])}</small>
    </div>
    <div class="echo-card">
      <p>&ldquo;{_esc(b["text"])}&rdquo;</p>
      <small>{_esc(b["book_title"])} &mdash; {_esc(b["book_author"])}</small>
    </div>
  </div>
  <p class="echo-explanation">{_esc(echo["explanation"])}</p>
</div>"""


def _render_revisit(revisit: dict) -> str:
    h = revisit["highlight"]
    border_color = _COLOUR_MAP.get(h.get("color", "yellow"), "#f5c842")
    note_html = ""
    if h.get("note"):
        note_html = f'<p class="highlight-note"><span>Your note: </span>{_esc(h["note"])}</p>'
    first_sent = revisit.get("first_sent")
    meta_html = ""
    if first_sent:
        meta_html = f'<p class="revisit-meta">First seen {_esc(str(first_sent))}</p>'
    return f"""<div class="revisit-section">
  <p class="revisit-label">Revisiting &mdash; {_esc(revisit["book_title"])}</p>
  <div class="highlight-block" style="border-left-color: {border_color}; margin-bottom: 0;">
    <p class="highlight-text">&ldquo;{_esc(h["text"])}&rdquo;</p>
    {note_html}
  </div>
  {meta_html}
</div>"""


def _render_book(book: dict, *, show_covers: bool = True) -> str:
    cover_html = ""
    if show_covers and book.get("coverUrl"):
        cover_html = (
            f'<img class="book-cover" src="{_esc(book["coverUrl"])}" '
            f'alt="Cover of {_esc(book["title"])}">'
        )

    highlights_html = "\n".join(_render_highlight(h) for h in book["highlights"])

    return f"""<div class="book-section">
  <div class="book-meta">
    {cover_html}
    <div class="book-info">
      <p class="book-title">{_esc(book["title"])}</p>
      <p class="book-author">{_esc(book["author"])}</p>
    </div>
  </div>
  {highlights_html}
</div>"""


def _render_highlight(h: dict) -> str:
    border_color = _COLOUR_MAP.get(h.get("color", "yellow"), "#f5c842")
    note_html = ""
    if h.get("note"):
        note_html = (
            f'<p class="highlight-note"><span>Your note: </span>{_esc(h["note"])}</p>'
        )
    location_html = ""
    if h.get("location"):
        location_html = f'<p class="highlight-location">{_esc(h["location"])}</p>'

    return f"""<div class="highlight-block" style="border-left-color: {border_color};">
  <p class="highlight-text">&ldquo;{_esc(h["text"])}&rdquo;</p>
  {note_html}
  {location_html}
</div>"""


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
