from types import SimpleNamespace

from services.offer_storage import (
    marketplace_service_label_from_offer,
    offer_effective_photo,
    offer_effective_title,
)


def test_void_raw_json_wins_over_stale_columns():
    off = SimpleNamespace(
        title="WRONG TITLE",
        photo="https://wrong.example/x.jpg",
        raw_json='{"item_title": "Badehut Gr. 53cm", "item_photo": "https://img.ricardostatic.ch/badehut.jpg"}',
    )
    assert offer_effective_title(off) == "Badehut Gr. 53cm"
    assert "badehut" in offer_effective_photo(off).lower()


def test_effective_photo_from_images_list_and_protocol_relative():
    off = SimpleNamespace(
        photo="",
        raw_json='{"images": ["//cdn.example/a.jpg", "https://cdn.example/b.jpg"]}',
    )
    assert offer_effective_photo(off) == "//cdn.example/a.jpg"


def test_effective_title_decodes_parser_html_entities():
    off = SimpleNamespace(
        title="",
        raw_json='{"item_title": "Rahmen Gr 40&#x2F;50"}',
    )
    assert offer_effective_title(off) == "Rahmen Gr 40/50"


def test_marketplace_label_from_ricardo_link():
    off = SimpleNamespace(
        link="",
        raw_json='{"item_link": "https://www.ricardo.ch/de/a/1325658046/"}',
    )
    assert marketplace_service_label_from_offer(off) == "ricardo.ch"


def test_marketplace_label_from_markt_ch_link():
    from services.offer_storage import marketplace_service_from_link

    label, code = marketplace_service_from_link("https://www.markt.ch/de/inserat/123")
    assert label == "markt.ch"
    assert code == "markt_ch"


def test_marketplace_label_from_stored_service_and_marktplaats_short_link():
    from services.offer_storage import (
        marketplace_service_from_link,
        marketplace_service_label_from_offer,
        stamp_marketplace_service_on_payload,
    )

    label, code = marketplace_service_from_link("https://link.marktplaats.nl/m2440712344")
    assert label == "marktplaats.nl"
    assert code == "marktplaats_nl"

    label_at, code_at = marketplace_service_from_link(
        "https://www.laendleanzeiger.at/anzeigen/12345"
    )
    assert label_at == "Laendleanzeiger"
    assert code_at == "laendleanzeiger_at"

    payload = stamp_marketplace_service_on_payload(
        {"item_link": "https://link.marktplaats.nl/m2440712344", "item_title": "X"}
    )
    assert payload["service_label"] == "marktplaats.nl"
    assert payload["service_code"] == "marktplaats_nl"

    off = SimpleNamespace(
        link="",
        raw_json='{"item_link":"https://example.com/x","service_label":"marktplaats.nl","service_code":"marktplaats_nl"}',
    )
    assert marketplace_service_label_from_offer(off) == "marktplaats.nl"
