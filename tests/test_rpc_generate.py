# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.api_teams import default_service_for_team, normalize_team_id
from services.rpc_catalog import (
    RPC_DEFAULT_SERVICE,
    force_rpc_generate_service,
    parse_rpc_service,
    platforms_for_rpc_country,
    rpc_api_service_code,
    rpc_service_label,
)
from services.rpc_network import extract_rpc_link, rpc_create_ad, rpc_method_for_link_type


class RpcCatalogTests(unittest.TestCase):
    def test_hungary_jofogas_and_aliases(self):
        ids = [sid for sid, _, _ in platforms_for_rpc_country("hu")]
        self.assertIn("jofogas", ids)
        self.assertIn("facebook", ids)
        self.assertEqual(RPC_DEFAULT_SERVICE, "jofogas")
        self.assertEqual(parse_rpc_service("jofogas_hu"), ("jofogas", "hu"))
        self.assertEqual(rpc_api_service_code("jofogas_hu"), "jofogas")
        self.assertIn("Jófogás", rpc_service_label("jofogas"))
        self.assertEqual(normalize_team_id("rpc"), "rpc")
        self.assertEqual(normalize_team_id("continental"), "rpc")
        self.assertEqual(default_service_for_team("rpc"), "jofogas")
        self.assertEqual(default_service_for_team("bastard"), "jofogas_hu")

    def test_croatia_njuskalo(self):
        ids = [sid for sid, _, _ in platforms_for_rpc_country("hr")]
        self.assertEqual(ids[0], "njuskalo")
        self.assertIn("facebook", ids)
        self.assertEqual(parse_rpc_service("njuskalo"), ("njuskalo", "hr"))
        self.assertEqual(parse_rpc_service("njuskalo_hr"), ("njuskalo", "hr"))
        self.assertEqual(rpc_api_service_code("njuskalo_hr"), "njuskalo")
        self.assertIn("Njuškalo", rpc_service_label("njuskalo"))
        self.assertEqual(force_rpc_generate_service("hr", "jofogas"), "njuskalo")
        self.assertEqual(force_rpc_generate_service("hr", "njuskalo"), "njuskalo")
        self.assertEqual(force_rpc_generate_service("hr", "facebook_hu"), "facebook")
        from services.country_scope import force_croatia_njuskalo_service

        self.assertEqual(force_croatia_njuskalo_service("rpc", "jofogas"), "njuskalo")
        self.assertEqual(force_croatia_njuskalo_service("rpc", "facebook"), "facebook")

    def test_hungary_available_on_both_teams(self):
        from services.country_scope import force_hungary_jofogas_service

        self.assertEqual(force_hungary_jofogas_service("rpc", ""), "jofogas")
        self.assertEqual(force_hungary_jofogas_service("rpc", "jofogas_hu"), "jofogas")
        self.assertEqual(force_hungary_jofogas_service("rpc", "facebook"), "facebook")
        self.assertEqual(force_hungary_jofogas_service("bastard", ""), "jofogas_hu")
        self.assertEqual(force_hungary_jofogas_service("bastard", "facebook_hu"), "facebook_hu")


class RpcLinkTests(unittest.TestCase):
    def test_prefers_short_link_for_method(self):
        data = {
            "status": "success",
            "data": {
                "tag": "015Zs08xGx",
                "paths": {"phishing": {"2_0": "/p/015Zs08xGx", "1_0": "/p1/015Zs08xGx"}},
                "domains": {"general": "shop.example.com", "short": "s.example.com"},
                "short_links": [
                    {
                        "method": "2_0",
                        "public": "https://s.example.com/r/1",
                        "private": "https://my-short.example.com/r/2",
                    }
                ],
            },
        }
        self.assertEqual(
            extract_rpc_link(data, method="2_0"),
            "https://my-short.example.com/r/2",
        )
        self.assertEqual(rpc_method_for_link_type("lk"), "2_0")
        self.assertEqual(rpc_method_for_link_type("card"), "1_0")

    def test_builds_from_paths_when_no_short(self):
        data = {
            "status": "success",
            "data": {
                "paths": {"phishing": {"2_0": "/p/abc"}},
                "domains": {"general": "shop.example.com"},
            },
        }
        self.assertEqual(extract_rpc_link(data), "https://shop.example.com/p/abc")


class RpcCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_body_hungary_jofogas(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="{}")
        resp.json = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "paths": {"phishing": {"2_0": "/p/x"}},
                    "domains": {"general": "land.example.com"},
                },
            }
        )
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            link = await rpc_create_ad(
                api_key="secret-key",
                api_base="https://api.rpc-host.com/api/v1",
                country_code="hu",
                service_code="jofogas",
                title="Kerékpár",
                price="155000",
                full_name="Kiss Anna",
                address="Budapest",
                image="https://img.example/a.jpg",
                link_type="lk",
            )
        self.assertEqual(link, "https://land.example.com/p/x")
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://api.rpc-host.com/api/v1/ad/create")
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "secret-key")
        self.assertEqual(kwargs["json"]["country_code"], "HU")
        self.assertEqual(kwargs["json"]["service_code"], "jofogas")
        self.assertEqual(kwargs["json"]["title"], "Kerékpár")
        self.assertEqual(kwargs["json"]["price"], 155000.0)
        self.assertEqual(kwargs["json"]["profile"]["full_name"], "Kiss Anna")
        self.assertEqual(kwargs["json"]["images"]["0"]["url"], "https://img.example/a.jpg")

    async def test_create_body_croatia_njuskalo(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="{}")
        resp.json = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "paths": {"phishing": {"2_0": "/p/hr"}},
                    "domains": {"general": "land.example.com"},
                },
            }
        )
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            link = await rpc_create_ad(
                api_key="secret-key",
                api_base="https://api.rpc-host.com/api/v1",
                country_code="hr",
                service_code="njuskalo",
                title="Bicikl",
                price="250",
                full_name="Ivan Horvat",
                address="Zagreb",
                image="https://img.example/b.jpg",
                link_type="lk",
            )
        self.assertEqual(link, "https://land.example.com/p/hr")
        _args, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"]["country_code"], "HR")
        self.assertEqual(kwargs["json"]["service_code"], "njuskalo")
        self.assertEqual(kwargs["json"]["title"], "Bicikl")
        self.assertEqual(kwargs["json"]["profile"]["full_name"], "Ivan Horvat")


if __name__ == "__main__":
    unittest.main()
