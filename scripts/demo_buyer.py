"""Act as an AdCP buyer against a running stdout Network seller.

    python scripts/demo_buyer.py                      # http://127.0.0.1:8080/mcp
    python scripts/demo_buyer.py --url http://host:8080/mcp
    python scripts/demo_buyer.py --report             # just print delivery

Walks the standard AdCP flow over real MCP: capabilities, accounts, a brief,
a media buy across three terminal moments, creatives, then delivery.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastmcp import Client

BRAND = {"domain": "cachely.example"}
ACCOUNT = {"brand": BRAND, "operator": "streets-digital.example", "billing": "operator", "sandbox": True}

CREATIVES = [
    {
        "creative_id": "cachely_install_line",
        "name": "Install line",
        "format_kind": "native_in_feed",
        "format_option_ref": {"scope": "product", "format_option_id": "terminal_line"},
        "assets": {
            "title": {"asset_type": "text", "content": "node_modules is 1.2GB again. Cache it once, restore it in 3s."},
            "advertiser_name": {"asset_type": "text", "content": "Cachely"},
            "cta": {"asset_type": "text", "content": "Try free"},
            "landing_page_url": {"asset_type": "url", "url": "https://cachely.example/npm"},
        },
    },
    {
        "creative_id": "cachely_build_box",
        "name": "Build-wait box",
        "format_kind": "native_in_feed",
        "format_option_ref": {"scope": "product", "format_option_id": "terminal_box"},
        "assets": {
            "title": {"asset_type": "text", "content": "This build will take 4 minutes. Ours took 9 seconds."},
            "body_text": {
                "asset_type": "text",
                "content": "Remote build cache for Docker, Cargo and Turborepo. Point it at your repo and stop watching progress bars.",
            },
            "advertiser_name": {"asset_type": "text", "content": "Cachely"},
            "cta": {"asset_type": "text", "content": "See benchmarks"},
            "landing_page_url": {"asset_type": "url", "url": "https://cachely.example/builds"},
        },
    },
    {
        "creative_id": "cachely_green_line",
        "name": "Green tests line",
        "format_kind": "native_in_feed",
        "format_option_ref": {"scope": "product", "format_option_id": "terminal_line"},
        "assets": {
            "title": {"asset_type": "text", "content": "All green. Now make CI as fast as your laptop."},
            "advertiser_name": {"asset_type": "text", "content": "Cachely"},
            "cta": {"asset_type": "text", "content": "Speed up CI"},
            "landing_page_url": {"asset_type": "url", "url": "https://cachely.example/ci"},
        },
    },
]

CREATIVES.append(
    {
        "creative_id": "cachely_pg_line",
        "name": "Postgres projects, UK",
        "format_kind": "native_in_feed",
        "format_option_ref": {"scope": "product", "format_option_id": "terminal_line"},
        "assets": {
            "title": {"asset_type": "text", "content": "Tests green, queries slow? Cache your Postgres reads at the edge."},
            "advertiser_name": {"asset_type": "text", "content": "Cachely"},
            "cta": {"asset_type": "text", "content": "Cache Postgres"},
            "landing_page_url": {"asset_type": "url", "url": "https://cachely.example/postgres"},
        },
    }
)

# UK developers whose project uses Postgres. Country is checked by the seller,
# the Postgres part is checked on the developer's machine by adterm.
UK_POSTGRES = {
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

# (product, creative, budget, targeting)
PLAN = [
    ("tty_install_sponsor", "cachely_install_line", 150, None),
    ("tty_build_wait", "cachely_build_box", 250, None),
    ("tty_tests_green", "cachely_green_line", 300, None),
    ("tty_tests_green", "cachely_pg_line", 900, UK_POSTGRES),
]


def say(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2)[:1800])


async def buy(url: str) -> None:
    async with Client(url) as c:
        caps = (await c.call_tool("get_adcp_capabilities", {})).structured_content
        say("get_adcp_capabilities", {"adcp": caps["adcp"], "portfolio": caps["media_buy"]["portfolio"]["description"]})

        accts = (await c.call_tool("sync_accounts", {"idempotency_key": str(uuid.uuid4()), "accounts": [ACCOUNT]})).structured_content
        account_id = accts["accounts"][0]["account_id"]
        say("sync_accounts", accts)

        brief = "Developer tools launch for a remote build cache. Reach engineers during installs, builds and test runs."
        prods = (await c.call_tool("get_products", {"buying_mode": "brief", "brief": brief, "brand": BRAND})).structured_content
        say("get_products (brief)", {"products": [{k: p[k] for k in ("product_id", "name", "brief_relevance")} | {"cpm": p["pricing_options"][0]["fixed_price"]} for p in prods["products"]]})

        end = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        packages = []
        for pid, cid, budget, targeting in PLAN:
            pk = {"product_id": pid, "pricing_option_id": f"{pid}_cpm_gbp", "budget": budget, "context": {"line_item": cid}}
            if targeting:
                pk["targeting_overlay"] = targeting
            packages.append(pk)
        buy_resp = (
            await c.call_tool(
                "create_media_buy",
                {
                    "idempotency_key": str(uuid.uuid4()),
                    "account": {"account_id": account_id},
                    "brand": BRAND,
                    "name": "Cachely terminal launch",
                    "start_time": "asap",
                    "end_time": end,
                    "packages": packages,
                },
            )
        ).structured_content
        say("create_media_buy", {k: buy_resp[k] for k in ("media_buy_id", "media_buy_status", "total_budget", "currency")}
            | {"targeted_package": next(p["targeting_overlay"] for p in buy_resp["packages"] if p.get("targeting_overlay"))})

        pkg_for = {p["context"]["line_item"]: p["package_id"] for p in buy_resp["packages"]}
        sync = (
            await c.call_tool(
                "sync_creatives",
                {
                    "idempotency_key": str(uuid.uuid4()),
                    "account": {"account_id": account_id},
                    "creatives": CREATIVES,
                    "assignments": [{"creative_id": cid, "package_id": pkg_for[cid]} for _, cid, _, _ in PLAN],
                },
            )
        ).structured_content
        say("sync_creatives", {"creatives": [{k: r.get(k) for k in ("creative_id", "action", "status", "assigned_to")} for r in sync["creatives"]]})

        mbs = (await c.call_tool("get_media_buys", {"media_buy_ids": [buy_resp["media_buy_id"]]})).structured_content
        print(f"\nMedia buy {buy_resp['media_buy_id']} is now: {mbs['media_buys'][0]['status']}")
        print("Now run some commands through adterm, then: python scripts/demo_buyer.py --report")


async def report(url: str) -> None:
    async with Client(url) as c:
        d = (
            await c.call_tool(
                "get_media_buy_delivery",
                {"status_filter": ["active", "paused", "completed"], "reporting_dimensions": {"geo": {"geo_level": "country"}}},
            )
        ).structured_content
        for mb in d["media_buy_deliveries"]:
            t = mb["totals"]
            print(f"\n{mb['media_buy_id']} [{mb['status']}]  {t['impressions']} imps  {t['clicks']} clicks  £{t['spend']:.4f}")
            for p in mb["by_package"]:
                geo = ", ".join(f"{g['geo_code']}:{g['impressions']}" for g in p.get("by_geo", [])) or "-"
                print(f"  {p['product_id']:<22} {p['impressions']:>4} imps  {p['clicks']:>2} clicks  £{p['spend']:.4f}  @ £{p['rate']:.2f} CPM  geo {geo}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    asyncio.run(report(a.url) if a.report else buy(a.url))
