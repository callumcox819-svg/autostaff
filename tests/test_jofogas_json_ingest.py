from handlers.validation import _extract_items, _normalize_items
from services.offer_storage import fields_from_item, marketplace_service_from_link
from services.seller_name import (
    seller_name_eligible_for_validation,
    seller_name_from_item,
)
from services.validemail_validator import _make_local_part_variants


def test_jofogas_export_keeps_fields_and_real_names():
    raw = {
        "items": [
            {
                "item_title": "Xiaomi Watch S1 Pro",
                "item_photo": "https://img.jofogas.hu/images/watch.jpg",
                "item_price": "40 000 Ft",
                "item_link": "https://www.jofogas.hu/budapest/Xiaomi_Watch_161526373.htm",
                "item_person_name": "Kovács Dávid",
                "location": "IV. kerület, Budapest",
            }
        ]
    }
    items = _normalize_items(_extract_items(raw))
    assert len(items) == 1
    it = items[0]
    assert seller_name_from_item(it) == "Kovács Dávid"
    f = fields_from_item(it)
    assert "Kovács" in f["person_name"]
    assert f["title"].startswith("Xiaomi")
    assert "jofogas.hu" in f["link"]
    assert f["photo"].startswith("https://img.jofogas.hu")
    assert "40 000" in f["price"]
    assert marketplace_service_from_link(f["link"])[1] == "jofogas_hu"
    assert seller_name_eligible_for_validation("Kovács Dávid", country="hu")
    vs = _make_local_part_variants("Kovács Dávid", require_first_and_last=False, country="hu")
    assert "kovacs.david" in vs
    assert "kovacsdavid" in vs


def test_jofogas_placeholder_private_person_is_no_name():
    it = _normalize_items(
        _extract_items(
            {
                "item_title": "PS4",
                "item_link": "https://www.jofogas.hu/gyor/ps4.htm",
                "item_photo": "https://img.jofogas.hu/x.jpg",
                "item_price": "54 990 Ft",
                "item_person_name": "Частное лицо",
            }
        )
    )[0]
    assert it["item_person_name"] == "Частное лицо"
    assert seller_name_from_item(it) == ""
    assert not seller_name_eligible_for_validation("Частное лицо", country="hu")
    f = fields_from_item(it)
    assert "54 990" in f["price"]
    assert f["title"] == "PS4"


def test_jofogas_nick_and_short_first_name():
    assert seller_name_eligible_for_validation("Aristarhios9", country="hu")
    vs = _make_local_part_variants(
        "Aristarhios9", require_first_and_last=False, country="hu"
    )
    assert "aristarhios9" in vs

    assert not seller_name_eligible_for_validation("Jan Kovács", country="hu")
    assert not _make_local_part_variants(
        "Jan Kovács", require_first_and_last=False, country="hu"
    )
    assert not seller_name_eligible_for_validation("Bestpups Kft", country="hu")
    assert not _make_local_part_variants(
        "Bestpups Kft", require_first_and_last=False, country="hu"
    )
