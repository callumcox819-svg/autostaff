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


def test_marketplace_label_from_ricardo_link():
    off = SimpleNamespace(
        link="",
        raw_json='{"item_link": "https://www.ricardo.ch/de/a/1325658046/"}',
    )
    assert marketplace_service_label_from_offer(off) == "ricardo.ch"


def test_marketplace_label_from_stored_service_and_marktplaats_short_link():
    from services.offer_storage import (
        marketplace_service_from_link,
        marketplace_service_label_from_offer,
        stamp_marketplace_service_on_payload,
    )

    label, code = marketplace_service_from_link("https://link.marktplaats.nl/m2440712344")
    assert label == "marktplaats.nl"
    assert code == "marktplaats_nl"

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
