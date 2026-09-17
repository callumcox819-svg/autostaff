# -*- coding: utf-8 -*-
import unittest
from dataclasses import replace

from services.api_teams import ApiTeamConfig
from services.country_scope import (
    GERMANY_VALIDATION_DOMAINS,
    austria_html_service,
    austria_html_service_for_code,
    force_austria_html_service,
    force_germany_ebay_service,
    germany_generate_service,
    scoped_blob_key,
    scoped_setting_key,
)
from services.enabled_countries import DEFAULT_ACTIVE_COUNTRY, normalize_country_id, parse_enabled_ids


class CountryScopeTests(unittest.TestCase):
    def test_scoped_keys(self):
        self.assertEqual(scoped_setting_key("domain_priority", "de"), "domain_priority__de")
        self.assertEqual(scoped_blob_key("templates", "nl"), "templates__nl")
        self.assertEqual(normalize_country_id("DE"), "de")
        self.assertIn("gmail.com", GERMANY_VALIDATION_DOMAINS)
        self.assertLess(
            GERMANY_VALIDATION_DOMAINS.index("gmail.com"),
            GERMANY_VALIDATION_DOMAINS.index("web.de"),
        )

    def test_germany_ebay_service_per_team(self):
        self.assertEqual(germany_generate_service("csm"), "ebay_de")
        self.assertEqual(germany_generate_service("hustle"), "ebay_de")
        self.assertEqual(germany_generate_service("evoleum"), "ebay_de")
        self.assertEqual(force_germany_ebay_service("csm", "kleinanzeigen_de"), "ebay_de")
        self.assertEqual(force_germany_ebay_service("hustle", "vinted_de"), "ebay_de")
        self.assertEqual(force_germany_ebay_service("evoleum", "marktplaats_nl"), "ebay_de")
        self.assertEqual(force_germany_ebay_service("csm", "depop_verify_all"), "depop_verify_all")
        self.assertEqual(force_germany_ebay_service("hustle", "kleinanzeigenverif_de"), "kleinanzeigenverif_de")

    def test_austria_html_service(self):
        self.assertEqual(austria_html_service("csm"), "willhaben_at")
        self.assertEqual(force_austria_html_service("csm", "willhaben_at"), "willhaben_at")
        self.assertEqual(force_austria_html_service("csm", "willhaben"), "willhaben_at")
        self.assertEqual(
            force_austria_html_service("csm", "laendleanzeiger_at"),
            "laendleanzeiger_at",
        )
        self.assertEqual(
            force_austria_html_service("csm", "laendleanzeiger"),
            "laendleanzeiger_at",
        )
        self.assertEqual(force_austria_html_service("csm", "ebay_de"), "willhaben_at")
        self.assertEqual(force_austria_html_service("csm", "marktplaats_nl"), "willhaben_at")
        self.assertEqual(force_austria_html_service("csm", "depop_verify_all"), "depop_verify_all")

    def test_legacy_nl_still_all_countries_if_unset(self):
        self.assertIn("de", parse_enabled_ids(None))
        self.assertIn("nl", parse_enabled_ids(None))


class GermanyGenerateOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_de_replaces_service_not_verify(self):
        cfg = ApiTeamConfig(
            team_id="csm",
            label="CSM",
            api_key="k",
            team_key="",
            service_code="kleinanzeigen_de",
            profile_id="p",
            link_type="lk",
        )
        new = replace(cfg, service_code=germany_generate_service(cfg.team_id))
        self.assertEqual(new.service_code, "ebay_de")
        self.assertEqual(cfg.service_code, "kleinanzeigen_de")


if __name__ == "__main__":
    unittest.main()
