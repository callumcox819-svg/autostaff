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
        outbound_rfc_message_id="<CACold@mail.gmail.com>",
    )
    assert kw["in_reply_to"] == "<CACold@mail.gmail.com>"
    assert kw["references"] == "<CACold@mail.gmail.com> <inbound@mail.gmail.com>"


def test_threading_send_kwargs_with_parent_references():
    kw = threading_send_kwargs(
        "<ja@mail.gmail.com>",
        outbound_rfc_message_id="<CAcold@mail.gmail.com>",
        parent_references="<CAcold@mail.gmail.com>",
    )
    assert kw["in_reply_to"] == "<CAcold@mail.gmail.com>"
    assert kw["references"] == "<CAcold@mail.gmail.com> <ja@mail.gmail.com>"


def test_threading_send_kwargs_for_dialog_chain():
    from services.email_threading import threading_send_kwargs_for_dialog

    kw = threading_send_kwargs_for_dialog(
        inbound_rfc_message_id="<seller2@mail.gmail.com>",
        cold_outbound_rfc_message_id="<cold@mail.gmail.com>",
        last_our_outbound_rfc_message_id="<preset@mail.gmail.com>",
        parent_references="<cold@mail.gmail.com> <seller1@mail.gmail.com> <preset@mail.gmail.com>",
        dialog_references="<cold@mail.gmail.com> <preset@mail.gmail.com>",
    )
    assert kw["in_reply_to"] == "<cold@mail.gmail.com>"
    assert kw["references"].startswith("<cold@mail.gmail.com>")
    assert "<preset@mail.gmail.com>" in kw["references"]
    assert kw["references"].endswith("<seller2@mail.gmail.com>")


def test_threading_falls_back_to_cold_when_no_inbound():
    from services.email_threading import threading_send_kwargs

    kw = threading_send_kwargs(None, outbound_rfc_message_id="<CAcold@mail.gmail.com>")
    assert kw["in_reply_to"] == "<CAcold@mail.gmail.com>"
    assert kw["references"] == "<CAcold@mail.gmail.com>"


def test_no_inbound_uses_client_cold_mid():
    from services.email_threading import threading_send_kwargs

    cold = "<1757781234567.1.1234567890123456789@gmail.com>"
    kw = threading_send_kwargs(
        None,
        outbound_rfc_message_id=cold,
        parent_references="<CAFooBar@mail.gmail.com>",
    )
    # Корень = cold из лога (то, что у получателя), не Sent @mail.gmail.com.
    assert kw["in_reply_to"] == cold
    assert cold in kw["references"]
    assert "<CAFooBar@mail.gmail.com>" in kw["references"]


def test_client_gmail_smtp_id_used_as_in_reply_to():
    from services.email_threading import threading_send_kwargs

    cold = "<1757781234567.1.1234567890123456789@gmail.com>"
    kw = threading_send_kwargs(
        "<jaajaja@mail.gmail.com>",
        outbound_rfc_message_id=cold,
        parent_references=f"{cold} <CAOrig@mail.gmail.com>",
    )
    assert kw["in_reply_to"] == cold
    assert cold in kw["references"]
    assert kw["references"].endswith("<jaajaja@mail.gmail.com>")


def test_prefer_thread_root_skips_sent_rewrite():
    from services.email_threading import prefer_thread_root_message_id

    client = "<178983505180.1.15370952257649259846@gmail.com>"
    sent = "<CAC-ogsLX1Fn_Ae=tV9Mj80y8wJwmn7cYsV-5s0zdzJN=NVeezg@mail.gmail.com>"
    assert prefer_thread_root_message_id(sent, client) == client
    assert prefer_thread_root_message_id(client, sent) == client
    from services.email_threading import threading_send_kwargs

    cold = "<1757781234567.1.1234567890123456789@gmail.com>"
    kw = threading_send_kwargs(None, outbound_rfc_message_id=cold)
    assert kw["in_reply_to"] == cold
    assert kw["references"] == cold


def test_build_references_header_dedupes():
    assert (
        build_references_header("<a@b.c>", "<a@b.c>", "<d@e.f>")
        == "<a@b.c> <d@e.f>"
    )


def test_format_gmail_style_reply_body_appends_mailing_root():
    from services.email_threading import format_gmail_style_reply_body

    out = format_gmail_style_reply_body(
        "Prima",
        parent_from_name="Dave",
        parent_body="jaaa",
        root_body="Hi, ich interessiere mich für 3 paar thermosokken.",
        root_from_name="Gremlis Anna",
        root_from_email="bot@gmail.com",
    )
    assert out.startswith("Prima\n\n")
    assert "> jaaa" in out
    assert "thermosokken" in out


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
    assert "> On earlier wrote:" in out
    assert "> old" in out


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
        references="<CA1789@mail.gmail.com> <seller-msg@marktplaats.nl>",
    )
    raw = msg.as_bytes().decode("utf-8", "replace")
    assert msg["In-Reply-To"] == "<seller-msg@marktplaats.nl>"
    assert msg["References"] == "<CA1789@mail.gmail.com> <seller-msg@marktplaats.nl>"
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
