from services.email_threading import (
    build_references_header,
    normalize_rfc_message_id,
    threading_send_kwargs,
)
from services.sender import _build_message


def test_normalize_rfc_message_id_brackets():
    assert normalize_rfc_message_id("<abc@mail.gmail.com>") == "<abc@mail.gmail.com>"
    assert normalize_rfc_message_id("abc@mail.gmail.com") == "<abc@mail.gmail.com>"
    assert normalize_rfc_message_id("  <x@y.z> junk") == "<x@y.z>"
    assert normalize_rfc_message_id("") is None
    assert normalize_rfc_message_id("not-an-id") is None


def test_threading_send_kwargs_inbound_only():
    assert threading_send_kwargs(None) == {}
    assert threading_send_kwargs("<a@b.c>") == {
        "in_reply_to": "<a@b.c>",
        "references": "<a@b.c>",
    }


def test_threading_send_kwargs_outbound_plus_inbound():
    kw = threading_send_kwargs(
        "<inbound@mail.gmail.com>",
        outbound_rfc_message_id="<1789.1.99@gmail.com>",
    )
    assert kw["in_reply_to"] == "<inbound@mail.gmail.com>"
    assert kw["references"] == "<1789.1.99@gmail.com> <inbound@mail.gmail.com>"


def test_threading_send_kwargs_with_parent_references():
    kw = threading_send_kwargs(
        "<ja@mail.gmail.com>",
        outbound_rfc_message_id="<cold@gmail.com>",
        parent_references="<cold@gmail.com>",
    )
    assert kw["in_reply_to"] == "<ja@mail.gmail.com>"
    assert kw["references"] == "<cold@gmail.com> <ja@mail.gmail.com>"


def test_threading_send_kwargs_for_dialog_chain():
    from services.email_threading import threading_send_kwargs_for_dialog

    kw = threading_send_kwargs_for_dialog(
        inbound_rfc_message_id="<seller2@x>",
        cold_outbound_rfc_message_id="<cold@x>",
        last_our_outbound_rfc_message_id="<preset@x>",
        parent_references="<cold@x> <seller1@x> <preset@x>",
        dialog_references="<cold@x> <preset@x>",
    )
    assert kw["in_reply_to"] == "<seller2@x>"
    assert kw["references"].startswith("<cold@x>")
    assert "<preset@x>" in kw["references"]
    assert kw["references"].endswith("<seller2@x>")


def test_threading_falls_back_to_cold_when_no_inbound():
    from services.email_threading import threading_send_kwargs

    kw = threading_send_kwargs(None, outbound_rfc_message_id="<cold@gmail.com>")
    assert kw["in_reply_to"] == "<cold@gmail.com>"
    assert kw["references"] == "<cold@gmail.com>"


def test_build_references_header_dedupes():
    assert (
        build_references_header("<a@b.c>", "<a@b.c>", "<d@e.f>")
        == "<a@b.c> <d@e.f>"
    )


def test_format_gmail_style_reply_body_quotes_parent():
    from services.email_threading import format_gmail_style_reply_body

    out = format_gmail_style_reply_body(
        "Prima",
        parent_from_name="Maria",
        parent_from_email="m@x.com",
        parent_date_str="Fri, 11 Sep 2026",
        parent_body="ja\n\nOn earlier wrote:\nold",
    )
    assert out.startswith("Prima\n\n")
    assert "On Fri, 11 Sep 2026 Maria wrote:" in out
    assert "> ja" in out


def test_build_message_headers_before_body():
    from services.sender import _build_message

    msg = _build_message(
        from_email="me@gmail.com",
        to_email="seller@example.com",
        subject="Re: fiets",
        body="hoi",
        sender_name="Anna",
        is_html=False,
        in_reply_to="<seller-msg@marktplaats.nl>",
        references="<1789.1.1@gmail.com> <seller-msg@marktplaats.nl>",
    )
    raw = msg.as_bytes().decode("utf-8", "replace")
    assert msg["In-Reply-To"] == "<seller-msg@marktplaats.nl>"
    assert msg["References"] == "<1789.1.1@gmail.com> <seller-msg@marktplaats.nl>"
    assert msg["Subject"] == "Re: fiets"
    assert raw.index("In-Reply-To:") < raw.index("\n\nhoi")
    assert "In-Reply-To: <seller-msg@marktplaats.nl>" in raw



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
