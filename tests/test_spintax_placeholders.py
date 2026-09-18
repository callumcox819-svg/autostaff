from services.placeholders import apply_placeholders
from services.spintax import expand_spintax


def test_spintax_preserves_sender_name_placeholder_until_rendering():
    expanded = expand_spintax(
        "{Hallo|Grüezi}, ich interessiere mich für OFFER. "
        "Viele Grüße, {{SENDER_NAME}}"
    )

    assert "{{SENDER_NAME}}" in expanded
    rendered = apply_placeholders(expanded, ctx={"SENDER_NAME": "Anna Gremlis"})
    assert "Anna Gremlis" in rendered
    assert "SENDER_NAME" not in rendered


def test_spintax_preserves_all_double_brace_placeholders():
    expanded = expand_spintax("{{BUYER_NAME}} fragt nach {{ITEM_TITLE}}")

    assert expanded == "{{BUYER_NAME}} fragt nach {{ITEM_TITLE}}"
