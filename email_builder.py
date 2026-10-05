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


def _styles(t: dict) -> dict[str, str]:
    """Inline CSS for each element class, from a resolved token set.

    Every styled element carries its own ``style`` attribute: the Gmail apps
    drop ``<style>`` for non-Google accounts (caniemail.com, html-style).
    Token values are literal (not CSS ``var()``), which email clients need.
    Honours the design system's shadow-free, value-contrast elevation.
    """
    return {
        "body": f"margin: 0; padding: 0; background: {t['color-fog']}; font-family: {t['font-body']};",
        "wrapper": f"background: {t['color-fog']}; padding: 40px 16px; font-family: {t['font-body']};",
        "card": f"background: {t['color-snow']}; max-width: 768px; margin: 0 auto; border-radius: {t['radius-card']}; overflow: hidden;",
        "header": f"background: {t['color-ink']}; padding: 36px 48px;",
        "header-title": f"margin: 0; color: {t['color-snow']}; font-family: {t['font-display']}; font-size: 28px; font-weight: 700; letter-spacing: -0.02em;",
        "header-date": f"margin: 8px 0 0; color: {t['color-silver-mist']}; font-size: 14px; letter-spacing: -0.01em;",
        "body-inner": "padding: 40px 48px;",
        "book-section": "margin-bottom: 44px;",
        "book-meta": "margin-bottom: 20px;",
        "book-cover-cell": "width: 64px; padding: 0 16px 0 0; vertical-align: top;",
        "book-cover": "display: block; width: 64px; height: 88px; object-fit: cover; border-radius: 8px;",
        "book-info": "vertical-align: top;",
        "book-title": f"margin: 0 0 4px; font-size: 20px; color: {t['color-ink']}; font-weight: 700; letter-spacing: -0.02em;",
        "book-author": f"margin: 0; font-size: 14px; color: {t['color-graphite']};",
        "highlight-block": f"border-left: 3px solid {t['color-silver-mist']}; padding: 14px 18px; margin-bottom: 16px; border-radius: 0 8px 8px 0; background: {t['color-fog']};",
        "highlight-text": f"margin: 0; font-size: 17px; line-height: 1.5; color: {t['color-ink']}; letter-spacing: -0.01em;",
        "highlight-note": f"margin: 12px 0 0; font-size: 14px; color: {t['color-slate']};",
        "note-label": f"color: {t['color-graphite']};",
        "highlight-location": f"margin: 8px 0 0; font-size: 12px; color: {t['color-graphite']};",
        "divider": f"border: none; border-top: 1px solid {t['color-silver-mist']}; margin: 36px 0;",
        "footer": f"background: {t['color-fog']}; padding: 24px 48px; border-top: 1px solid {t['color-silver-mist']};",
        "footer-text": f"margin: 0; font-size: 12px; color: {t['color-graphite']}; line-height: 1.5;",
        "echo-section": f"margin: 0 0 32px; padding: 24px; background: {t['color-fog']}; border-radius: {t['radius-card']};",
        "echo-label": f"margin: 0 0 16px; font-size: 12px; color: {t['color-graphite']}; letter-spacing: 0.08em; text-transform: uppercase;",
        "echo-pair": "margin-bottom: 16px;",
        # The cards are the table cells, so both share the row's height.
        "echo-card": f"width: 49%; vertical-align: top; background: {t['color-snow']}; border-radius: 16px; padding: 16px;",
        "echo-gap": "width: 2%; font-size: 0; line-height: 0;",
        "echo-text": f"margin: 0 0 8px; font-size: 15px; line-height: 1.5; color: {t['color-ink']};",
        "echo-source": f"font-size: 12px; color: {t['color-graphite']};",
        "echo-explanation": f"margin: 0; font-size: 14px; color: {t['color-slate']}; line-height: 1.5;",
        "revisit-section": f"margin: 0 0 32px; padding: 22px 24px; background: {t['color-fog']}; border-radius: {t['radius-card']};",
        "revisit-label": f"margin: 0 0 12px; font-size: 12px; color: {t['color-graphite']}; letter-spacing: 0.08em; text-transform: uppercase;",
        "revisit-meta": f"margin: 10px 0 0; font-size: 12px; color: {t['color-graphite']};",
    }


# Phone-width overrides. Only clients that keep <style> apply them, and they
# need !important to beat the inline styles.
_MOBILE_CSS = """
    @media only screen and (max-width: 640px) {
        .wrapper { padding: 0 !important; }
        .card { border-radius: 0 !important; }
        .header { padding: 28px 24px !important; }
        .body-inner { padding: 28px 24px !important; }
        .footer { padding: 20px 24px !important; }
        .echo-section { padding: 18px !important; }
        .echo-card { display: block !important; width: auto !important; }
        .echo-gap { display: block !important; width: auto !important; height: 12px !important; }
        .revisit-section { padding: 18px !important; }
    }
""".strip()

# Attributes for a layout table: no cell spacing. Screen readers skip it.
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'


def _a(s: dict, cls: str, extra: str = "") -> str:
    """``class`` and inline ``style`` attributes for an element.

    The style is escaped: token values come from the uploaded design file.
    """
    return f'class="{cls}" style="{_esc(s[cls] + extra)}"'


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
    s = _styles(tokens or _DEFAULT_TOKENS)
    date_line = (today or date.today()).strftime("%A, %d %B %Y")
    total_books = _esc(str(metadata.get("totalBooks", "—")))
    total_highlights = _esc(str(metadata.get("totalHighlights", "—")))

    book_sections = "\n".join(
        _render_book(b, s, show_covers=show_covers, last=i == len(selections) - 1)
        for i, b in enumerate(selections)
    )

    special_parts = []
    if echo:
        special_parts.append(_render_echo(echo, s))
    if revisit:
        special_parts.append(_render_revisit(revisit, s))
    if special_parts:
        special_parts.append(f"<hr {_a(s, 'divider')}>")
    special_html = "\n".join(special_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your Daily Highlights</title>
<style>{_MOBILE_CSS}</style>
</head>
<body style="{_esc(s['body'])}">
<div {_a(s, 'wrapper')}>
  <div {_a(s, 'card')}>
    <div {_a(s, 'header')}>
      <h1 {_a(s, 'header-title')}>Your Daily Highlights</h1>
      <p {_a(s, 'header-date')}>{date_line}</p>
    </div>
    <div {_a(s, 'body-inner')}>
      {special_html}
      {book_sections}
    </div>
    <div {_a(s, 'footer')}>
      <p {_a(s, 'footer-text')}>Your library: {total_books} books &middot; {total_highlights} highlights<br>
      Sent by DrClawLights &mdash; your personal highlights digest.</p>
    </div>
  </div>
</div>
</body>
</html>"""


def _render_echo(echo: dict, s: dict) -> str:
    cells = f"\n      <td {_a(s, 'echo-gap')}>&nbsp;</td>\n".join(
        f"""      <td {_a(s, 'echo-card')}>
        <p {_a(s, 'echo-text')}>&ldquo;{_esc(h["text"])}&rdquo;</p>
        <span {_a(s, 'echo-source')}>{_esc(h["book_title"])} &mdash; {_esc(h["book_author"])}</span>
      </td>"""
        for h in (echo["highlight_a"], echo["highlight_b"])
    )
    return f"""<div {_a(s, 'echo-section')}>
  <p {_a(s, 'echo-label')}>Echo &mdash; same idea, different books</p>
  <table {_TABLE} {_a(s, 'echo-pair')}>
    <tr>
{cells}
    </tr>
  </table>
  <p {_a(s, 'echo-explanation')}>{_esc(echo["explanation"])}</p>
</div>"""


def _render_note(h: dict, s: dict) -> str:
    if not h.get("note"):
        return ""
    return (
        f'<p {_a(s, "highlight-note")}><span {_a(s, "note-label")}>Your note: </span>'
        f'{_esc(h["note"])}</p>'
    )


def _border(h: dict) -> str:
    return f" border-left-color: {_COLOUR_MAP.get(h.get('color', 'yellow'), '#f5c842')};"


def _render_revisit(revisit: dict, s: dict) -> str:
    h = revisit["highlight"]
    first_sent = revisit.get("first_sent")
    meta_html = ""
    if first_sent:
        meta_html = f'<p {_a(s, "revisit-meta")}>First seen {_esc(str(first_sent))}</p>'
    return f"""<div {_a(s, 'revisit-section')}>
  <p {_a(s, 'revisit-label')}>Revisiting &mdash; {_esc(revisit["book_title"])}</p>
  <div {_a(s, 'highlight-block', _border(h) + ' margin-bottom: 0;')}>
    <p {_a(s, 'highlight-text')}>&ldquo;{_esc(h["text"])}&rdquo;</p>
    {_render_note(h, s)}
  </div>
  {meta_html}
</div>"""


def _render_book(book: dict, s: dict, *, show_covers: bool = True, last: bool = False) -> str:
    cover_html = ""
    if show_covers and book.get("coverUrl"):
        cover_html = (
            f'<td {_a(s, "book-cover-cell")}><img {_a(s, "book-cover")} width="64" height="88" '
            f'src="{_esc(book["coverUrl"])}" alt="Cover of {_esc(book["title"])}"></td>'
        )

    highlights_html = "\n".join(_render_highlight(h, s) for h in book["highlights"])
    # The last section sits on the card's bottom padding, so it needs no gap.
    section_extra = " margin-bottom: 0;" if last else ""

    return f"""<div {_a(s, 'book-section', section_extra)}>
  <table {_TABLE} {_a(s, 'book-meta')}>
    <tr>
      {cover_html}
      <td {_a(s, 'book-info')}>
        <p {_a(s, 'book-title')}>{_esc(book["title"])}</p>
        <p {_a(s, 'book-author')}>{_esc(book["author"])}</p>
      </td>
    </tr>
  </table>
  {highlights_html}
</div>"""


def _render_highlight(h: dict, s: dict) -> str:
    location_html = ""
    if h.get("location"):
        location_html = f'<p {_a(s, "highlight-location")}>{_esc(h["location"])}</p>'

    return f"""<div {_a(s, 'highlight-block', _border(h))}>
  <p {_a(s, 'highlight-text')}>&ldquo;{_esc(h["text"])}&rdquo;</p>
  {_render_note(h, s)}
  {location_html}
</div>"""


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
