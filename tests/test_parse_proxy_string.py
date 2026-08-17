import unittest

from handlers.proxies import parse_proxy_string


class ParseProxyStringTests(unittest.TestCase):
    def test_user_pass_at_host_port(self):
        d = parse_proxy_string("luxsocks:luxsocks@213.199.56.46:15828")
        self.assertIsNotNone(d)
        self.assertEqual(d["host"], "213.199.56.46")
        self.assertEqual(d["port"], 15828)
        self.assertEqual(d["username"], "luxsocks")
        self.assertEqual(d["password"], "luxsocks")
        self.assertEqual(d["type"], "socks5")

    def test_socks5_url(self):
        d = parse_proxy_string("socks5://luxsocks:luxsocks@213.199.56.46:15828")
        self.assertIsNotNone(d)
        self.assertEqual(d["host"], "213.199.56.46")
        self.assertEqual(d["port"], 15828)
        self.assertEqual(d["username"], "luxsocks")
        self.assertEqual(d["type"], "socks5")


if __name__ == "__main__":
    unittest.main()
