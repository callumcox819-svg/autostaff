from handlers.validation import _extract_items, _normalize_items
from services.offer_storage import fields_from_item, marketplace_service_from_link
from services.seller_name import (
    ch_local_part_variants,
    seller_name_eligible_for_validation,
    seller_name_from_item,
)


def test_markt_export_maps_seller_name_url_and_image():
    raw = {
        "url": "https://www.markt.ch/kochtopf/a/31e6a234/?geoUrlId=berlin",
        "title": "Kleiner feiner Kochtopf von Silit",
        "price": 14.5,
        "currency": "EUR",
        "country_code": "ch",
        "seller_name": "besteangebote",
        "main_image": "https://imagecache.markt.de/pic",
    }
    items = _normalize_items(_extract_items([raw]))
    assert len(items) == 1
    it = items[0]
    assert seller_name_from_item(it) == "besteangebote"
    f = fields_from_item(it)
    assert f["person_name"] == "besteangebote"
    assert f["title"].startswith("Kleiner feiner")
    assert "markt.ch" in f["link"]
    assert f["photo"].startswith("https://imagecache.markt.de")
    assert "14.5" in f["price"]
    assert marketplace_service_from_link(f["link"])[1] == "markt_ch"
    assert seller_name_eligible_for_validation("besteangebote", country="ch")
    locals_ = ch_local_part_variants("besteangebote")
    assert "besteangebote" in locals_


def test_markt_strips_profile_rename_suffix():
    raw = {
        "url": "https://www.markt.ch/tisch/a/9a6de790/",
        "title": "Esszimmer Tisch",
        "seller_name": "Rainer SchaperNeuDas Mitglied hat vor kurzem den Profilnamen geändert.",
    }
    it = _normalize_items(_extract_items([raw]))[0]
    assert seller_name_from_item(it) == "Rainer Schaper"


def test_markt_hyphen_shop_kept_for_local_parts():
    raw = {
        "url": "https://www.markt.ch/receiver/a/abc/",
        "title": "Receiver",
        "seller_name": "Hifi-Audio-Oldy-Shop",
    }
    it = _normalize_items(_extract_items([raw]))[0]
    assert seller_name_from_item(it) == "Hifi-Audio-Oldy-Shop"
    locals_ = ch_local_part_variants(seller_name_from_item(it))
    assert "hifi.audio.oldy.shop" in locals_
