from services.smart_preset_txt import (
    MAX_SMART_PRESETS_TOTAL,
    replace_smart_presets,
)


def test_txt_replacement_does_not_keep_old_presets():
    replacement, skipped = replace_smart_presets(["new one", "new two"])

    assert replacement == ["new one", "new two"]
    assert skipped == 0


def test_txt_replacement_respects_total_limit():
    imported = [f"preset {i}" for i in range(MAX_SMART_PRESETS_TOTAL + 3)]

    replacement, skipped = replace_smart_presets(imported)

    assert len(replacement) == MAX_SMART_PRESETS_TOTAL
    assert skipped == 3
