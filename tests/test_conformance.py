"""Full buyer flow against the seller, in-process.

Every request we send and every response the seller returns is validated
against the official AdCP 3.2 JSON schemas bundled in the `adcp` SDK.
Then the ad-serving path is exercised and delivery is checked for the
right numbers.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("STDOUT_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from adcp.validation.schema_validator import format_issues, validate_request, validate_response  # noqa: E402
from fastmcp import Client  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from seller.server import mcp, store  # noqa: E402

ACCOUNT = {"brand": {"domain": "linear-ish.example"}, "operator": "agency.example", "sandbox": True}
BRAND = {"domain": "linear-ish.example"}


async def call(client: Client, tool: str, args: dict, *, check_request: bool = True) -> dict:
    if check_request:
        req = validate_request(tool, args)
        assert req.valid, f"{tool} request invalid: {format_issues(req.issues, 10)}"
    result = await client.call_tool(tool, args, raise_on_error=False)
    assert not result.is_error, f"{tool} transport error: {result.content}"
    payload = result.structured_content
    res = validate_response(tool, payload)
    assert res.valid, f"{tool} response invalid ({res.variant}): {format_issues(res.issues, 10)}\n{payload}"
    return payload


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_full_flow() -> None:
    store.reset()
    asyncio.run(_flow())


async def _flow() -> None:
    async with Client(mcp) as c:
        caps = await call(c, "get_adcp_capabilities", {})
        assert caps["adcp"]["major_versions"] == [3]

        accts = await call(c, "sync_accounts", {"idempotency_key": str(uuid.uuid4()), "accounts": [{**ACCOUNT, "billing": "operator"}]})
        account_id = accts["accounts"][0]["account_id"]
        await call(c, "list_accounts", {})

        prods = await call(
            c,
            "get_products",
            {"buying_mode": "brief", "brief": "Developer tools launch: reach engineers while their tests pass and deploys ship", "brand": BRAND},
        )
        ids = [p["product_id"] for p in prods["products"]]
        assert "tty_tests_green" in ids and "tty_ship_it" in ids, ids

        wholesale = await call(c, "get_products", {"buying_mode": "wholesale", "filters": {"pricing_currencies": ["GBP"]}})
        assert len(wholesale["products"]) == 6

        declined = await call(c, "get_products", {"buying_mode": "brief", "brief": "Crypto token sale for devs", "brand": BRAND})
        assert declined["status"] == "rejected"

        await call(c, "list_creative_formats", {})

        now = datetime.now(timezone.utc)
        buy = await call(
            c,
            "create_media_buy",
            {
                "idempotency_key": str(uuid.uuid4()),
                "account": {"account_id": account_id},
                "brand": BRAND,
                "start_time": "asap",
                "end_time": iso(now + timedelta(days=14)),
                "packages": [
                    {
                        "product_id": "tty_tests_green",
                        "pricing_option_id": "tty_tests_green_cpm_gbp",
                        "budget": 500,
                        "format_option_refs": [{"scope": "product", "format_option_id": "terminal_line"}],
                        "context": {"line_item": "green-tests"},
                    },
                    {
                        "product_id": "tty_build_wait",
                        "pricing_option_id": "tty_build_wait_cpm_gbp",
                        "budget": 300,
                    },
                ],
            },
        )
        assert buy["media_buy_status"] == "pending_creatives"
        mb_id = buy["media_buy_id"]
        pkg_green, pkg_build = (p["package_id"] for p in buy["packages"])

        sync = await call(
            c,
            "sync_creatives",
            {
                "idempotency_key": str(uuid.uuid4()),
                "account": {"account_id": account_id},
                "creatives": [
                    {
                        "creative_id": "green_line_1",
                        "name": "Green tests line",
                        "format_kind": "native_in_feed",
                        "format_option_ref": {"scope": "product", "format_option_id": "terminal_line"},
                        "assets": {
                            "title": {"asset_type": "text", "content": "All green. Now find the bugs your tests missed."},
                            "advertiser_name": {"asset_type": "text", "content": "Sentryish"},
                            "cta": {"asset_type": "text", "content": "Try free"},
                            "landing_page_url": {"asset_type": "url", "url": "https://sentryish.example/terminal"},
                        },
                    },
                    {
                        "creative_id": "build_box_1",
                        "name": "Build wait box",
                        "format_kind": "native_in_feed",
                        "format_option_ref": {"scope": "product", "format_option_id": "terminal_box"},
                        "assets": {
                            "title": {"asset_type": "text", "content": "Your build takes 4 minutes. Ours took 9 seconds."},
                            "body_text": {"asset_type": "text", "content": "Remote build cache for Docker and Cargo. Point it at your repo and stop watching progress bars."},
                            "advertiser_name": {"asset_type": "text", "content": "Cachely"},
                            "cta": {"asset_type": "text", "content": "See benchmarks"},
                            "landing_page_url": {"asset_type": "url", "url": "https://cachely.example"},
                        },
                    },
                    {
                        "creative_id": "evil_1",
                        "name": "Escape sequence attempt",
                        "format_kind": "native_in_feed",
                        "format_option_ref": {"scope": "product", "format_option_id": "terminal_line"},
                        "assets": {
                            "title": {"asset_type": "text", "content": "Totally normal ad \x1b]52;c;cm0gLXJmIH4=\x07"},
                            "advertiser_name": {"asset_type": "text", "content": "Mallory"},
                            "landing_page_url": {"asset_type": "url", "url": "https://mallory.example"},
                        },
                    },
                ],
                "assignments": [
                    {"creative_id": "green_line_1", "package_id": pkg_green},
                    {"creative_id": "build_box_1", "package_id": pkg_build},
                ],
            },
        )
        statuses = {r["creative_id"]: r["status"] for r in sync["creatives"]}
        assert statuses == {"green_line_1": "approved", "build_box_1": "approved", "evil_1": "rejected"}, statuses

        await call(c, "list_creatives", {"account": {"account_id": account_id}})

        buys = await call(c, "get_media_buys", {"media_buy_ids": [mb_id]})
        assert buys["media_buys"][0]["status"] == "active"

        # Idempotent replay returns the same buy; a changed payload conflicts.
        key = str(uuid.uuid4())
        replay_args = {
            "idempotency_key": key,
            "account": {"account_id": account_id},
            "brand": BRAND,
            "start_time": "asap",
            "end_time": iso(now + timedelta(days=7)),
            "packages": [{"product_id": "tty_ship_it", "pricing_option_id": "tty_ship_it_cpm_gbp", "budget": 100}],
        }
        first = await call(c, "create_media_buy", replay_args)
        second = await call(c, "create_media_buy", replay_args)
        assert first["media_buy_id"] == second["media_buy_id"]
        conflict = await call(c, "create_media_buy", {**replay_args, "packages": [{**replay_args["packages"][0], "budget": 200}]})
        assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"

    # --- serve ads through the plain HTTP routes ---------------------------
    http = TestClient(mcp.http_app())
    served = 0
    for _ in range(40):
        r = http.post("/serve", json={"moment": "tests_green", "tool": "pytest"})
        assert r.status_code == 200, r.text
        slate = r.json()["slate"]
        ad = slate[0]
        assert ad["advertiser"] == "Sentryish" and len(slate) == 1
        assert http.post(f"/imp/{ad['impression_id']}").status_code == 204
        served += 1
    click = http.get(f"/c/{ad['impression_id']}", follow_redirects=False)
    assert click.status_code == 302 and click.headers["location"] == "https://sentryish.example/terminal"
    assert http.post("/serve", json={"moment": "failure"}).status_code == 204  # nobody bought remnant
    box = http.post("/serve", json={"moment": "build", "tool": "docker"}).json()["slate"][0]
    assert box["format"] == "terminal_box" and box["body"]

    async with Client(mcp) as c:
        d = await call(c, "get_media_buy_delivery", {"media_buy_ids": [mb_id]})
        totals = d["media_buy_deliveries"][0]["totals"]
        assert totals["impressions"] == served, totals
        assert totals["clicks"] == 1
        assert abs(totals["spend"] - served * 28 / 1000) < 1e-6, totals

        upd = await call(
            c,
            "update_media_buy",
            {
                "account": {"account_id": account_id},
                "media_buy_id": mb_id,
                "revision": buy["revision"],
                "paused": True,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert upd["media_buy_status"] == "paused"
    assert http.post("/serve", json={"moment": "tests_green"}).status_code == 204  # paused buys do not serve


TARGETING = {
    "geo_countries": ["GB"],
    "signal_targeting_groups": {
        "operator": "all",
        "groups": [
            {
                "operator": "any",
                "signals": [{"signal_ref": {"scope": "product", "signal_id": "stack_postgres"}, "value_type": "binary", "value": True}],
            }
        ],
    },
}


def test_targeting(monkeypatch) -> None:
    store.reset()
    monkeypatch.setenv("STDOUT_TRUST_GEO_HEADERS", "1")
    asyncio.run(_targeting())


async def _targeting() -> None:
    now = datetime.now(timezone.utc)
    async with Client(mcp) as c:
        caps = await call(c, "get_adcp_capabilities", {})
        assert caps["media_buy"]["execution"]["targeting"]["geo_countries"] is True

        prods = await call(
            c,
            "get_products",
            {
                "buying_mode": "brief",
                "brief": "UK developers using Postgres, reach them when tests pass",
                "brand": BRAND,
                "targeting_overlay": TARGETING,
                "required_overlay_support": {"geo_countries": True, "signal_targeting_groups": True},
            },
        )
        green = next(p for p in prods["products"] if p["product_id"] == "tty_tests_green")
        assert green["is_custom"] and green["expires_at"]
        assert "stack_postgres" in green["brief_relevance"]
        assert any(o["signal_ref"]["signal_id"] == "stack_postgres" for o in green["signal_targeting_options"])

        bad = await call(
            c,
            "get_products",
            {"buying_mode": "wholesale", "required_overlay_support": {"geo_metros": {"systems": ["nielsen_dma"]}}},
        )
        assert bad["products"] == [] and "required_overlay_support" in bad["filter_diagnostics"]["excluded_by"]

        base = {
            "account": {"brand": BRAND, "operator": "agency.example", "sandbox": True},
            "brand": BRAND,
            "start_time": "asap",
            "end_time": iso(now + timedelta(days=14)),
        }
        unsupported = await call(
            c,
            "create_media_buy",
            {
                **base,
                "idempotency_key": str(uuid.uuid4()),
                "packages": [
                    {
                        "product_id": "tty_tests_green",
                        "pricing_option_id": "tty_tests_green_cpm_gbp",
                        "budget": 100,
                        "targeting_overlay": {"geo_regions": ["GB-ENG"]},
                    }
                ],
            },
        )
        assert unsupported["errors"][0]["code"] == "UNSUPPORTED_FEATURE"

        creative = lambda cid, title: {  # noqa: E731
            "creative_id": cid,
            "name": cid,
            "format_kind": "native_in_feed",
            "format_option_ref": {"scope": "product", "format_option_id": "terminal_line"},
            "assets": {
                "title": {"asset_type": "text", "content": title},
                "advertiser_name": {"asset_type": "text", "content": "Neonish"},
                "landing_page_url": {"asset_type": "url", "url": "https://neonish.example"},
            },
        }
        buy = await call(
            c,
            "create_media_buy",
            {
                **base,
                "idempotency_key": str(uuid.uuid4()),
                "packages": [
                    {
                        "product_id": "tty_tests_green",
                        "pricing_option_id": "tty_tests_green_cpm_gbp",
                        "budget": 200,
                        "targeting_overlay": TARGETING,
                        "creatives": [creative("pg_uk", "Tests pass. Now branch your Postgres per PR.")],
                    },
                    {
                        "product_id": "tty_tests_green",
                        "pricing_option_id": "tty_tests_green_cpm_gbp",
                        "budget": 100,
                        "creatives": [creative("anyone", "Serverless Postgres, free tier.")],
                    },
                ],
            },
        )
        assert buy["packages"][0]["targeting_overlay"]["geo_countries"] == ["GB"]
        assert "targeting_overlay" not in buy["packages"][1]
        pkg_targeted = buy["packages"][0]["package_id"]

    http = TestClient(mcp.http_app())
    uk = http.post("/serve", json={"moment": "tests_green"}, headers={"CF-IPCountry": "GB"}).json()
    assert uk["country"] == "GB"
    targeted = [a for a in uk["slate"] if a["rules"]["any_of_groups"]]
    assert len(targeted) == 1 and targeted[0]["rules"]["any_of_groups"] == [["stack_postgres"]]
    assert "stack_postgres" in uk["signals"] and "pg" in uk["signals"]["stack_postgres"]["deps"]
    assert http.post(f"/imp/{targeted[0]['impression_id']}").status_code == 204

    us = http.post("/serve", json={"moment": "tests_green"}, headers={"CF-IPCountry": "US"}).json()
    assert us["country"] == "US" and all(not a["rules"]["any_of_groups"] for a in us["slate"])  # geo excluded server-side
    assert us["signals"] == {}
    assert http.post(f"/imp/{us['slate'][0]['impression_id']}").status_code == 204

    async with Client(mcp) as c:
        d = await call(
            c,
            "get_media_buy_delivery",
            {"media_buy_ids": [buy["media_buy_id"]], "reporting_dimensions": {"geo": {"geo_level": "country"}}},
        )
        pkgs = {p["package_id"]: p for p in d["media_buy_deliveries"][0]["by_package"]}
        assert pkgs[pkg_targeted]["by_geo"] == [
            {"geo_level": "country", "geo_code": "GB", "impressions": 1, "spend": 0.028, "clicks": 0}
        ]
        other = next(p for pid, p in pkgs.items() if pid != pkg_targeted)
        assert [g["geo_code"] for g in other["by_geo"]] == ["US"]

        # Clearing country targeting on update keeps the signal targeting.
        upd = await call(
            c,
            "update_media_buy",
            {
                "account": {"brand": BRAND, "operator": "agency.example", "sandbox": True},
                "media_buy_id": buy["media_buy_id"],
                "idempotency_key": str(uuid.uuid4()),
                "packages": [{"package_id": pkg_targeted, "targeting_overlay": {"geo_countries": None}}],
            },
        )
        t = next(p for p in upd["affected_packages"] if p["package_id"] == pkg_targeted)["targeting_overlay"]
        assert "geo_countries" not in t and "signal_targeting_groups" in t
