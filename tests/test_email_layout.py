"""Email layout must survive clients that drop <style> or ignore flexbox.

caniemail.com data: Outlook for Windows does not support display:flex, and
the Gmail apps drop <style> for non-Google accounts. So every styled element
carries its own inline style, and side-by-side layouts use tables.
"""

import re

import email_builder

BOOKS = [
    {
        "title": "BookA", "author": "AA", "coverUrl": "https://x/a.jpg",
        "highlights": [{"text": "alpha", "note": "n", "location": "L1", "color": "pink"}],
    },
    {"title": "BookB", "author": "BB", "coverUrl": None, "highlights": [{"text": "beta"}]},
]
ECHO = {
    "highlight_a": {"text": "alpha", "book_title": "BookA", "book_author": "AA"},
    "highlight_b": {"text": "beta", "book_title": "BookB", "book_author": "BB"},
    "explanation": "why",
}
REVISIT = {
    "book_title": "BookC", "book_author": "CC", "first_sent": "2020-01-01",
    "highlight": {"text": "gamma", "note": "m", "location": "", "color": "blue"},
}


def _html(**kw):
    return email_builder.build_html(
        BOOKS, {"totalBooks": 2, "totalHighlights": 2}, echo=ECHO, revisit=REVISIT, **kw
    )


def _body(html):
    return html.split("<body", 1)[1]


def test_no_flexbox():
    assert "flex" not in _html()


def test_every_classed_element_has_an_inline_style():
    tags = re.findall(r"<[a-z0-9]+\b[^>]*\bclass=\"[^\"]+\"[^>]*>", _body(_html()))
    assert tags
    for tag in tags:
        assert 'style="' in tag, tag


def test_design_tokens_reach_the_inline_styles():
    tokens = dict(email_builder._DEFAULT_TOKENS, **{"color-ink": "#123456"})
    body = _body(_html(tokens=tokens))
    assert re.search(r'class="header"[^>]*style="[^"]*#123456', body)


def test_side_by_side_layouts_are_presentation_tables():
    body = _body(_html())
    assert body.count('role="presentation"') >= 3  # two book headers + echo pair
    echo = body.split('class="echo-section"', 1)[1]
    assert len(re.findall(r'<td class="echo-card"', echo)) == 2


def test_style_block_keeps_only_the_mobile_overrides():
    style = _html().split("<style>", 1)[1].split("</style>", 1)[0]
    assert "@media only screen and (max-width: 640px)" in style
    assert ".echo-card" in style  # stack the echo pair on phones


def test_highlight_colour_and_token_quotes_stay_valid():
    tokens = dict(email_builder._DEFAULT_TOKENS, **{"font-body": 'x" onload="y'})
    body = _body(_html(tokens=tokens))
    assert 'onload="y' not in body
    assert "#f48fb1" in body  # pink highlight border


def test_last_book_has_no_bottom_margin():
    sections = re.findall(r'class="book-section" style="([^"]*)"', _body(_html()))
    assert len(sections) == 2
    assert "margin-bottom: 44px" in sections[0] and "margin-bottom: 0" in sections[1]
