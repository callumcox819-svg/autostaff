from services.email_threading import normalize_rfc_message_id, threading_send_kwargs
from services.sender import _build_message


def test_normalize_rfc_message_id_brackets():
    assert normalize_rfc_message_id("<abc@mail.gmail.com>") == "<abc@mail.gmail.com>"
    assert normalize_rfc_message_id("abc@mail.gmail.com") == "<abc@mail.gmail.com>"
    assert normalize_rfc_message_id("  <x@y.z> junk") == "<x@y.z>"
    assert normalize_rfc_message_id("") is None
    assert normalize_rfc_message_id("not-an-id") is None


def test_threading_send_kwargs():
    assert threading_send_kwargs(None) == {}
    assert threading_send_kwargs("<a@b.c>") == {
        "in_reply_to": "<a@b.c>",
        "references": "<a@b.c>",
    }


def test_build_message_sets_reply_headers():
    msg = _build_message(
        from_email="me@gmail.com",
        to_email="seller@example.com",
        subject="Re: fiets",
        body="hoi",
        sender_name="Anna",
        is_html=False,
        in_reply_to="<seller-msg@marktplaats.nl>",
    )
    assert msg["In-Reply-To"] == "<seller-msg@marktplaats.nl>"
    assert msg["References"] == "<seller-msg@marktplaats.nl>"
    assert msg["Subject"] == "Re: fiets"
    assert "Anna" in (msg["From"] or "")


def test_build_message_without_reply_headers():
    msg = _build_message(
        from_email="me@gmail.com",
        to_email="seller@example.com",
        subject="Re: fiets",
        body="hoi",
        is_html=False,
    )
    assert msg.get("In-Reply-To") is None
    assert msg.get("References") is None
