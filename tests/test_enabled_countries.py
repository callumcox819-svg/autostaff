# -*- coding: utf-8 -*-
import json
import unittest

from services.csm_catalog import CSM_COUNTRIES
from services.enabled_countries import (
    countries_for_settings_ui,
    filter_csm_countries,
    normalize_country_id,
    parse_enabled_ids,
)


class EnabledCountriesTests(unittest.TestCase):
    def test_empty_means_all_on(self):
        all_ids = {c for c, _, _ in CSM_COUNTRIES}
        self.assertEqual(parse_enabled_ids(None), all_ids)
        self.assertEqual(parse_enabled_ids(""), all_ids)
        self.assertEqual(parse_enabled_ids("[]"), all_ids)

    def test_subset(self):
        got = parse_enabled_ids(json.dumps(["de", "nl", "xx"]))
        self.assertEqual(got, {"de", "nl"})

    def test_filter_csm(self):
        rows = filter_csm_countries({"de", "nl"})
        ids = [c for c, _, _ in rows]
        self.assertEqual(ids, ["nl", "de"])

    def test_ui_puts_de_nl_first(self):
        ids = [c for c, _, _ in countries_for_settings_ui()]
        self.assertEqual(ids[0], "de")
        self.assertEqual(ids[1], "nl")
        self.assertEqual(len(ids), len(CSM_COUNTRIES))
        self.assertEqual(normalize_country_id("nl"), "nl")


if __name__ == "__main__":
    unittest.main()
