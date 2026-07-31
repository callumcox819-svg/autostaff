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
