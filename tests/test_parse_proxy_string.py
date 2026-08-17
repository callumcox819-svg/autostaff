import unittest

from handlers.proxies import parse_proxy_string
from services.proxy_verify import _tunnel_types_to_try


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

    def test_loma_host_port_user_pass_is_socks5(self):
        d = parse_proxy_string("proxy.lomaproxy.com:48176:lomaUser:lomaPass")
        self.assertIsNotNone(d)
        self.assertEqual(d["host"], "proxy.lomaproxy.com")
        self.assertEqual(d["port"], 48176)
        self.assertEqual(d["username"], "lomaUser")
        self.assertEqual(d["password"], "lomaPass")
        self.assertEqual(d["type"], "socks5")

    def test_socks5_scheme_prefix_colon(self):
        d = parse_proxy_string("socks5:proxy.lomaproxy.com:48176:lomaUser:lomaPass")
        self.assertIsNotNone(d)
        self.assertEqual(d["host"], "proxy.lomaproxy.com")
        self.assertEqual(d["type"], "socks5")

    def test_loma_tunnel_fallback_order(self):
        types = _tunnel_types_to_try(
            {"host": "proxy.lomaproxy.com", "type": "socks5"}
        )
        self.assertEqual(types, ["socks5", "socks5h", "http"])


if __name__ == "__main__":
    unittest.main()
