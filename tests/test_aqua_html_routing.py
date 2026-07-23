import unittest

from services.aqua_keys import aqua_service_for_html_dir, normalize_aqua_service
from services.html_templates import html_subdir_for_service, html_template_path


class AquaHtmlRoutingTests(unittest.TestCase):
    def test_normalize_services(self):
        self.assertEqual(normalize_aqua_service("ricardo.ch"), "ricardo_ch")
        self.assertEqual(normalize_aqua_service("tutti.ch"), "tutti_ch")

    def test_html_subdirs(self):
        self.assertEqual(html_subdir_for_service("ricardo_ch"), "ricardo_ch")
        self.assertEqual(html_subdir_for_service("tutti_ch"), "tutti_ch")
        self.assertEqual(aqua_service_for_html_dir("tutti_ch"), "tutti_ch")

    def test_template_paths_exist(self):
        for service, files in (
            ("ricardo_ch", ("confirmation.html", "confirmation_new.html", "return.html")),
            ("tutti_ch", ("confirmation.html", "return.html")),
        ):
            for name in files:
                p = html_template_path(service, name)
                self.assertIsNotNone(p, msg=f"{service}/{name}")
                self.assertTrue(p.is_file(), msg=f"{service}/{name}")

    def test_service_picks_different_dirs(self):
        go_r = html_template_path("ricardo_ch", "confirmation.html")
        go_t = html_template_path("tutti_ch", "confirmation.html")
        self.assertNotEqual(go_r, go_t)


if __name__ == "__main__":
    unittest.main()
