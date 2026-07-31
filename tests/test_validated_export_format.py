import json

from services.offer_storage import format_validated_export_document, format_validated_export_item


def test_validated_export_void_shape_and_no_dup_aliases():
    row = {
        "item_title": "Sofa",
        "title": "Sofa dup",
        "item_link": "https://ricardo.ch/a/1",
        "link": "https://ricardo.ch/a/1",
        "item_price": "100",
        "price": "100",
        "validated_emails": ["seller@example.com"],
        "offer_id": 42,
    }
    doc = format_validated_export_document([row])
    assert list(doc.keys()) == ["items"]
    item = doc["items"][0]
    assert "title" not in item
    assert "link" not in item
    assert "price" not in item
    assert item["item_title"] == "Sofa"
    assert item["validated_emails"] == ["seller@example.com"]
    assert item["offer_id"] == 42
    pretty = json.dumps(doc, ensure_ascii=False, indent=2)
    assert "\n" in pretty
    assert '"items"' in pretty


def test_format_validated_export_item_preserves_extra_fields():
    raw = format_validated_export_item({"item_title": "X", "custom_flag": True})
    assert raw["custom_flag"] is True
