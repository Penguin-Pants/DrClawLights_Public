"""Notification fragments shown in the dashboard toast zone."""

from routes.common import flash


def test_flash_escapes_message_and_extra_parts_are_appended():
    r = flash("<b>x</b>", "success", extra_html='<i id="oob"></i>', trigger="refreshPreview")
    body = r.body.decode()
    assert "&lt;b&gt;x&lt;/b&gt;" in body and body.endswith('<i id="oob"></i>')
    assert r.headers["HX-Trigger"] == "refreshPreview"


def test_error_flash_has_a_dismiss_button_and_success_does_not():
    assert 'aria-label="Dismiss"' in flash("bad", "error").body.decode()
    assert "Dismiss" not in flash("ok").body.decode()
