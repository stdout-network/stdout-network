"""stdout Network - an AdCP 3.2 seller agent for terminal advertising.

Run:   python -m seller.server            (streamable HTTP at /mcp, port 8080)
       STDOUT_TRANSPORT=sse python -m seller.server   (SSE at /sse, like the Meta seller)

AdCP tools (MCP): get_adcp_capabilities, sync_accounts, list_accounts,
get_products, list_creative_formats, create_media_buy, update_media_buy,
get_media_buys, sync_creatives, list_creatives, get_media_buy_delivery.

Ad-serving routes (plain HTTP, used by the opt-in `adterm` wrapper):
  POST /serve            ask for an ad for a terminal moment
  POST /imp/{id}         confirm the ad was rendered (this is what bills)
  GET  /c/{id}           click redirect to the landing page
  GET  /.well-known/adagents.json
  GET  /health
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response

from . import catalog
from .catalog import CURRENCY, FORMATS, PRODUCT_BY_MOMENT, PRODUCTS, PRODUCTS_BY_ID, PUBLISHER_DOMAIN
from .store import Store, now_iso, parse_iso

SELLER_URL = os.environ.get("STDOUT_SELLER_URL", "http://127.0.0.1:8080").rstrip("/")
IDEMPOTENCY_TTL_SECONDS = 86400

mcp = FastMCP(
    "stdout Network",
    instructions=(
        "AdCP 3.2 seller agent for stdout Network, an opt-in terminal advertising network. "
        "Inventory is moments in a developer's terminal session: dependency installs, long builds, "
        "passing test suites, successful deploys and failed commands. Call get_adcp_capabilities first."
    ),
)
store = Store()

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _err(code: str, message: str, field: str | None = None, **details: Any) -> dict:
    e: dict[str, Any] = {"code": code, "message": message}
    if field:
        e["field"] = field
    if details:
        e["details"] = details
    return e


def _clean(d: dict) -> dict:
    """Drop None values so optional fields are omitted rather than null."""
    return {k: v for k, v in d.items() if v is not None}


def _payload_hash(args: dict) -> str:
    body = {k: v for k, v in args.items() if k != "idempotency_key" and v is not None}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _idempotent(tool: str, key: str | None, args: dict, fn) -> dict:
    """Replay-safe execution: same key + same payload replays, changed payload conflicts."""
    if not key:
        return fn()
    h = _payload_hash(args)
    prior = store.idem_get(key, tool)
    if prior:
        age = datetime.now(timezone.utc) - parse_iso(prior["created_at"])
        if age.total_seconds() > IDEMPOTENCY_TTL_SECONDS:
            return {"errors": [_err("IDEMPOTENCY_EXPIRED", "This idempotency_key has expired; use a new key.")]}
        if prior["payload_hash"] != h:
            return {
                "errors": [
                    _err(
                        "IDEMPOTENCY_CONFLICT",
                        "idempotency_key was already used with a different payload.",
                        "idempotency_key",
                    )
                ]
            }
        return json.loads(prior["response_json"])
    result = fn()
    if "errors" not in result or result.get("media_buy_id") or result.get("creatives"):
        store.idem_put(key, tool, h, result)
    return result


def _with_context(result: dict, context: dict | None) -> dict:
    if context is not None:
        result["context"] = context
    return result


# -- accounts ---------------------------------------------------------------


def _account_wire(row: dict) -> dict:
    return {
        "account_id": row["account_id"],
        "name": row["name"] or row["brand_domain"],
        "status": row["status"],
        "brand": {"domain": row["brand_domain"]},
        "operator": row["operator"],
        "billing": row["billing"],
        "sandbox": bool(row["sandbox"]),
    }


def _provision(brand_domain: str, operator: str, sandbox: bool, billing: str = "operator", name: str | None = None) -> tuple[dict, str]:
    row = store.one(
        "SELECT * FROM accounts WHERE brand_domain=? AND operator=? AND sandbox=?",
        (brand_domain, operator, int(sandbox)),
    )
    if row:
        return row, "unchanged"
    account_id = _id("acct")
    store.x(
        "INSERT INTO accounts (account_id, brand_domain, operator, name, billing, sandbox, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (account_id, brand_domain, operator, name, billing, int(sandbox), "active", now_iso()),
    )
    return store.one("SELECT * FROM accounts WHERE account_id=?", (account_id,)), "created"


def _resolve_account(account: dict | None, brand: dict | None) -> tuple[dict | None, dict | None]:
    """Resolve an AccountRef. Natural keys provision lazily (buyer-declared accounts)."""
    if account and account.get("account_id"):
        row = store.one("SELECT * FROM accounts WHERE account_id=?", (account["account_id"],))
        if not row:
            return None, _err("ACCOUNT_NOT_FOUND", "Unknown account_id.", "account.account_id")
        return row, None
    if account and account.get("brand", {}).get("domain") and account.get("operator"):
        row, _ = _provision(account["brand"]["domain"], account["operator"], bool(account.get("sandbox", False)))
        return row, None
    if brand and brand.get("domain"):
        # Lenient path for older buyers that only send brand: the brand is its own operator.
        row, _ = _provision(brand["domain"], brand["domain"], False)
        return row, None
    return None, _err("ACCOUNT_REQUIRED", "Provide account {account_id} or {brand, operator}.", "account")


# -- media buys -------------------------------------------------------------


def _spend_impressions(package_id: str, start: str | None = None, end: str | None = None) -> tuple[int, int]:
    sql = "SELECT COUNT(rendered_at) AS imps, COUNT(clicked_at) AS clicks FROM impressions WHERE package_id=? AND rendered_at IS NOT NULL"
    args: list[Any] = [package_id]
    if start:
        sql += " AND rendered_at >= ?"
        args.append(start)
    if end:
        sql += " AND rendered_at < ?"
        args.append(end)
    r = store.one(sql, tuple(args))
    return int(r["imps"] or 0), int(r["clicks"] or 0)


def _package_spend(pkg: dict) -> float:
    imps, _ = _spend_impressions(pkg["package_id"])
    return round(imps * pkg["cpm"] / 1000.0, 4)


def _has_approved_creative(package_id: str) -> bool:
    mb = store.one(
        "SELECT m.account_id FROM packages p JOIN media_buys m ON m.media_buy_id=p.media_buy_id WHERE p.package_id=?",
        (package_id,),
    )
    if not mb:
        return False
    r = store.one(
        "SELECT 1 FROM assignments a JOIN creatives c ON c.creative_id=a.creative_id AND c.account_id=? "
        "WHERE a.package_id=? AND c.status='approved' LIMIT 1",
        (mb["account_id"], package_id),
    )
    return bool(r)


def _media_buy_status(mb: dict) -> str:
    now = datetime.now(timezone.utc)
    if parse_iso(mb["end_time"]) <= now:
        return "completed"
    pkgs = store.q("SELECT * FROM packages WHERE media_buy_id=?", (mb["media_buy_id"],))
    if pkgs and all(_package_spend(p) >= p["budget"] for p in pkgs):
        return "completed"
    if not any(_has_approved_creative(p["package_id"]) for p in pkgs):
        return "pending_creatives"
    if parse_iso(mb["start_time"]) > now:
        return "pending_start"
    if mb["paused"]:
        return "paused"
    return "active"


def _package_wire(pkg: dict) -> dict:
    assigned = store.q("SELECT creative_id, weight FROM assignments WHERE package_id=?", (pkg["package_id"],))
    out = {
        "package_id": pkg["package_id"],
        "product_id": pkg["product_id"],
        "pricing_option_id": pkg["pricing_option_id"],
        "budget": pkg["budget"],
        "paused": bool(pkg["paused"]),
        "format_option_refs": [{"scope": "product", "format_option_id": pkg["format_option_id"]}],
    }
    if assigned:
        out["creative_assignments"] = [{"creative_id": a["creative_id"], "weight": a["weight"]} for a in assigned]
    if pkg.get("targeting_json"):
        out["targeting_overlay"] = json.loads(pkg["targeting_json"])
    if pkg["context_json"]:
        out["context"] = json.loads(pkg["context_json"])
    return out


# -- targeting ----------------------------------------------------------------

_COUNTRY = re.compile(r"^[A-Z]{2}$")
_SIGNAL_IDS = set(catalog.SIGNALS)


def _validate_overlay(overlay: dict | None, field: str) -> tuple[dict | None, dict | None]:
    """Validate a package targeting_overlay against what stdout Network can execute.

    Unsupported dimensions are rejected, never silently dropped: dropping an
    exclusion would be an unsafe failure. Returns (normalised_overlay, error).
    """
    if overlay is None:
        return None, None
    if not isinstance(overlay, dict):
        return None, _err("INVALID_REQUEST", "targeting_overlay must be an object.", field)
    unsupported = sorted(k for k, v in overlay.items() if v is not None and k not in catalog.SUPPORTED_OVERLAY_KEYS)
    if unsupported:
        return None, _err(
            "UNSUPPORTED_FEATURE",
            f"stdout Network cannot execute targeting on: {', '.join(unsupported)}.",
            f"{field}.{unsupported[0]}",
            supported_dimensions=sorted(catalog.SUPPORTED_OVERLAY_KEYS),
        )
    out: dict[str, Any] = {}
    for key in ("geo_countries", "geo_countries_exclude"):
        values = overlay.get(key)
        if values is None:
            continue
        if not isinstance(values, list) or not values or not all(isinstance(c, str) and _COUNTRY.match(c) for c in values):
            return None, _err("INVALID_REQUEST", f"{key} must be a non-empty list of ISO 3166-1 alpha-2 codes.", f"{field}.{key}")
        out[key] = sorted(set(values))
    groups = overlay.get("signal_targeting_groups")
    if groups is not None:
        gfield = f"{field}.signal_targeting_groups"
        if not isinstance(groups, dict) or groups.get("operator") != "all" or not isinstance(groups.get("groups"), list):
            return None, _err("INVALID_REQUEST", "signal_targeting_groups must be {operator: 'all', groups: [...]}.", gfield)
        if not groups["groups"] or len(groups["groups"]) > catalog.SIGNAL_RULES["max_signal_targeting_groups"]:
            return None, _err("INVALID_REQUEST", "Between 1 and 4 signal groups are allowed.", f"{gfield}.groups")
        for gi, g in enumerate(groups["groups"]):
            gf = f"{gfield}.groups[{gi}]"
            if g.get("operator") not in ("any", "none"):
                return None, _err("INVALID_REQUEST", "Child groups use operator 'any' (include) or 'none' (exclude).", f"{gf}.operator")
            sigs = g.get("signals") or []
            if not sigs or len(sigs) > catalog.SIGNAL_RULES["max_signals_per_targeting_group"]:
                return None, _err("INVALID_REQUEST", "Each group needs 1 to 8 signals.", f"{gf}.signals")
            for si, sig in enumerate(sigs):
                ref = sig.get("signal_ref") or {}
                if ref.get("scope") != "product" or ref.get("signal_id") not in _SIGNAL_IDS:
                    return None, _err(
                        "INVALID_REQUEST",
                        f"Unknown signal. Use a product-scoped signal from signal_targeting_options.",
                        f"{gf}.signals[{si}].signal_ref",
                    )
                if sig.get("value_type", "binary") != "binary" or sig.get("value", True) is not True:
                    return None, _err("INVALID_REQUEST", "Stack signals are binary; send value: true.", f"{gf}.signals[{si}].value")
        out["signal_targeting_groups"] = groups
    return (out or None), None


def _compile_rules(targeting: dict | None) -> dict:
    """Turn AdCP signal groups into the tiny rule shape adterm evaluates on-device."""
    rules: dict[str, Any] = {"any_of_groups": [], "none_of": []}
    if targeting and targeting.get("signal_targeting_groups"):
        for g in targeting["signal_targeting_groups"]["groups"]:
            ids = [s["signal_ref"]["signal_id"] for s in g["signals"]]
            if g["operator"] == "any":
                rules["any_of_groups"].append(ids)
            else:
                rules["none_of"].extend(ids)
    return rules


def _geo_ok(targeting: dict | None, country: str | None) -> bool:
    if not targeting:
        return True
    include, exclude = targeting.get("geo_countries"), targeting.get("geo_countries_exclude")
    if include and (not country or country not in include):
        return False
    if exclude and country and country in exclude:
        return False
    return True


def _media_buy_wire(mb: dict, full: bool = True) -> dict:
    pkgs = store.q("SELECT * FROM packages WHERE media_buy_id=? ORDER BY created_at", (mb["media_buy_id"],))
    acct = store.one("SELECT * FROM accounts WHERE account_id=?", (mb["account_id"],))
    out: dict[str, Any] = {
        "media_buy_id": mb["media_buy_id"],
        "media_buy_status": _media_buy_status(mb),
        "confirmed_at": mb["confirmed_at"],
        "creative_deadline": mb["creative_deadline"],
        "revision": mb["revision"],
        "currency": mb["currency"],
        "total_budget": round(sum(p["budget"] for p in pkgs), 2),
        "packages": [_package_wire(p) for p in pkgs],
    }
    if mb["name"]:
        out["name"] = mb["name"]
    if acct:
        out["account"] = _account_wire(acct)
    if mb["context_json"]:
        out["context"] = json.loads(mb["context_json"])
    return out


# -- creative review ----------------------------------------------------------

# C0/C1 controls, DEL and the CSI introducer: a buyer must never be able to put an
# escape sequence into someone's terminal (OSC 52 clipboard writes, title changes,
# cursor tricks). Bidi overrides are rejected too ("Trojan Source").
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")
_BANNED_WORDS = re.compile(r"(?i)\b(rm\s+-rf|sudo|curl\s+[^|]*\|\s*(ba)?sh|password|airdrop)\b")


def _review_creative(format_option_id: str | None, assets: dict) -> tuple[str, list[str]]:
    """Synchronous automated review. Returns (status, problems)."""
    problems: list[str] = []
    if format_option_id not in FORMATS:
        return "rejected", [f"Unknown format_option_id '{format_option_id}'. Use terminal_line or terminal_box."]
    limits = catalog.FORMAT_LIMITS[format_option_id]
    for slot in catalog.REQUIRED_SLOTS[format_option_id]:
        if slot not in assets:
            problems.append(f"Missing required asset '{slot}'.")
    for slot, asset in assets.items():
        if not isinstance(asset, dict):
            problems.append(f"Asset '{slot}' must be an object.")
            continue
        if asset.get("asset_type") == "url" or slot == "landing_page_url":
            url = asset.get("url", "")
            if urlparse(url).scheme != "https":
                problems.append(f"'{slot}' must be an https URL.")
            continue
        text = asset.get("content", "")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"'{slot}' must be non-empty text in 'content'.")
            continue
        if _FORBIDDEN.search(text):
            problems.append(f"'{slot}' contains control or bidi characters. Terminal escape sequences are not accepted.")
        if _BANNED_WORDS.search(text):
            problems.append(f"'{slot}' contains copy that tells developers to run something or hand over credentials.")
        if slot in limits and len(text) > limits[slot]:
            problems.append(f"'{slot}' is {len(text)} chars; limit is {limits[slot]}.")
    return ("rejected" if problems else "approved"), problems


def _format_option_from_creative(c: dict) -> str | None:
    ref = c.get("format_option_ref") or {}
    if ref.get("format_option_id"):
        return ref["format_option_id"]
    fid = c.get("format_id")
    if isinstance(fid, dict) and fid.get("id") in FORMATS:
        return fid["id"]
    if c.get("format_kind") == "native_in_feed":
        # Infer from assets: body_text means the box format.
        return "terminal_box" if "body_text" in (c.get("assets") or {}) else "terminal_line"
    return None


def _upsert_creative(account_id: str, c: dict) -> dict:
    creative_id = c.get("creative_id")
    if not creative_id:
        return {"creative_id": "", "action": "failed", "errors": [_err("INVALID_REQUEST", "creative_id is required.")]}
    fmt = _format_option_from_creative(c)
    assets = c.get("assets") or {}
    status, problems = _review_creative(fmt, assets)
    existing = store.one("SELECT * FROM creatives WHERE account_id=? AND creative_id=?", (account_id, creative_id))
    assets_json = json.dumps(assets, sort_keys=True)
    if existing and existing["assets_json"] == assets_json and existing["format_option_id"] == (fmt or ""):
        action = "unchanged"
        status = existing["status"]
    else:
        action = "updated" if existing else "created"
        ts = now_iso()
        store.x(
            "INSERT OR REPLACE INTO creatives (account_id, creative_id, name, format_option_id, assets_json, status, review_notes, revision_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                account_id,
                creative_id,
                c.get("name") or creative_id,
                fmt or "",
                assets_json,
                status,
                json.dumps(problems),
                c.get("revision_id"),
                existing["created_at"] if existing else ts,
                ts,
            ),
        )
    out: dict[str, Any] = {"creative_id": creative_id, "action": action, "status": status, "platform_id": f"stdout:{creative_id}"}
    if c.get("revision_id"):
        out["revision_id"] = c["revision_id"]
    if status == "rejected":
        out["warnings"] = problems
    return out


# ---------------------------------------------------------------------------
# AdCP tools
# ---------------------------------------------------------------------------


@mcp.tool
def get_adcp_capabilities(
    adcp_major_version: int | None = None,
    protocols: list[str] | None = None,
    context: dict | None = None,
) -> dict:
    """Discover what this seller supports. Call this first."""
    if adcp_major_version is not None and adcp_major_version != 3:
        return {"errors": [_err("VERSION_UNSUPPORTED", "stdout Network speaks AdCP major version 3 only.")]}
    result = {
        "status": "completed",
        "adcp": {
            "major_versions": [3],
            "idempotency": {"supported": True, "replay_ttl_seconds": IDEMPOTENCY_TTL_SECONDS},
        },
        "supported_protocols": ["media_buy"],
        "account": {
            "supported_billing": ["operator", "agent"],
            "supported_account_currency_modes": ["fixed"],
            "timezone": {"mode": "seller_fixed", "fixed_timezone": "UTC"},
            "require_operator_auth": False,
            "required_for_products": False,
            "sandbox": True,
        },
        "media_buy": {
            "anonymous_discovery": True,
            "supported_pricing_models": ["cpm"],
            "buying_modes": ["brief", "wholesale"],
            "creative_approval_mode": "auto_approve",
            "features": {"inline_creative_management": True},
            "execution": {"targeting": {"geo_countries": True}},
            "portfolio": {
                "publisher_domains": [PUBLISHER_DOMAIN],
                "primary_channels": ["display"],
                "primary_countries": ["GB", "US", "DE", "FR", "NL", "IE"],
                "description": (
                    "stdout Network sells moments in developers' terminal sessions through the opt-in "
                    "`adterm` wrapper: dependency installs, long builds, green test runs, successful "
                    "deploys and (at remnant rates) failed commands. Text-only, no tracking identifiers."
                ),
                "advertising_policies": (
                    "Text only. No terminal escape sequences, no instructions to run commands, "
                    "no credential requests. Crypto, gambling and recruitment campaigns are declined."
                ),
            },
        },
    }
    return _with_context(result, context)


@mcp.tool
def sync_accounts(
    accounts: list[dict],
    idempotency_key: str | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Declare buyer accounts (brand + operator). Provisions immediately; billing is operator or agent."""
    out = []
    for a in accounts:
        brand = (a.get("brand") or {}).get("domain")
        operator = a.get("operator")
        if not brand or not operator:
            out.append(
                {
                    "brand": a.get("brand") or {"domain": "unknown"},
                    "operator": operator or "unknown",
                    "action": "failed",
                    "status": "rejected",
                    "errors": [_err("INVALID_REQUEST", "brand.domain and operator are required.")],
                }
            )
            continue
        billing = a.get("billing", "operator")
        if billing not in ("operator", "agent"):
            out.append(
                {
                    "brand": a["brand"],
                    "operator": operator,
                    "action": "failed",
                    "status": "rejected",
                    "errors": [_err("UNSUPPORTED_FEATURE", "Billing must be operator or agent.", "billing")],
                }
            )
            continue
        row, action = _provision(brand, operator, bool(a.get("sandbox", False)), billing, a.get("name"))
        wire = _account_wire(row)
        wire["action"] = action
        out.append(wire)
    return _with_context({"status": "completed", "accounts": out}, context)


@mcp.tool
def list_accounts(
    status: str | None = None,
    sandbox: bool | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """List accounts provisioned on stdout Network."""
    rows = store.q("SELECT * FROM accounts ORDER BY created_at")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if sandbox is not None:
        rows = [r for r in rows if bool(r["sandbox"]) == sandbox]
    return _with_context({"status": "completed", "accounts": [_account_wire(r) for r in rows]}, context)


def _score(product: dict, brief: str) -> int:
    b = brief.lower()
    return sum(1 for kw in product["_keywords"] if kw in b)


@mcp.tool
def get_products(
    buying_mode: str = "brief",
    brief: str | None = None,
    brand: dict | None = None,
    account: dict | None = None,
    filters: dict | None = None,
    targeting_overlay: dict | None = None,
    required_overlay_support: dict | None = None,
    fields: list[str] | None = None,
    pagination: dict | None = None,
    idempotency_key: str | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Discover terminal inventory. buying_mode 'brief' curates against a brief; 'wholesale' returns the full feed.

    Every product supports country targeting (include and exclude) and product-scoped stack
    signals (uses Postgres, Rust project, calls an LLM API, ...) that are evaluated on the
    developer's machine. Select them per package via targeting_overlay.
    """
    if buying_mode not in ("brief", "wholesale"):
        return {"errors": [_err("UNSUPPORTED_FEATURE", "Supported buying modes: brief, wholesale.", "buying_mode")]}
    if buying_mode == "brief" and not brief:
        return {"errors": [_err("INVALID_REQUEST", "brief is required when buying_mode is 'brief'.", "brief")]}
    if buying_mode == "wholesale" and brief:
        return {"errors": [_err("INVALID_REQUEST", "brief must not be sent in wholesale mode.", "brief")]}

    if brief:
        lowered = brief.lower()
        for word, reason in catalog.DECLINED_CATEGORIES.items():
            if word in lowered:
                return _with_context(
                    {
                        "status": "rejected",
                        "reason": reason,
                        "suggestions": ["Try a developer-tools, hosting, observability or testing brief."],
                    },
                    context,
                )

    candidates = list(PRODUCTS)
    excluded: dict[str, dict] = {}
    f = filters or {}

    def exclude(name: str, keep):
        nonlocal candidates
        before = len(candidates)
        candidates = [p for p in candidates if keep(p)]
        if before - len(candidates):
            excluded[name] = {"count": before - len(candidates)}

    if f.get("channels"):
        exclude("channels", lambda p: set(p["channels"]) & set(f["channels"]))
    if f.get("delivery_type"):
        exclude("delivery_type", lambda p: p["delivery_type"] == f["delivery_type"])
    if f.get("pricing_currencies"):
        exclude("pricing_currencies", lambda p: CURRENCY in f["pricing_currencies"])
    if f.get("format_kinds"):
        exclude("format_kinds", lambda p: any(fo["format_kind"] in f["format_kinds"] for fo in p["format_options"]))
    if f.get("is_fixed_price") is False:
        exclude("is_fixed_price", lambda p: False)
    if f.get("budget_range", {}).get("currency") and f["budget_range"]["currency"] != CURRENCY:
        exclude("budget_range", lambda p: False)
    if required_overlay_support:
        wanted = {k for k, v in required_overlay_support.items() if v}
        if wanted - catalog.SUPPORTED_OVERLAY_KEYS:
            exclude("required_overlay_support", lambda p: False)

    configured = None
    if targeting_overlay:
        configured, terr = _validate_overlay(targeting_overlay, "targeting_overlay")
        if terr:
            # A product that cannot honour the structured overlay is omitted, not mis-priced.
            exclude("targeting_overlay", lambda p: False)

    def stack_hints(text: str) -> list[str]:
        t = f" {text.lower()} "
        return [sid for sid, words in catalog.SIGNAL_HINTS.items() if any(w in t for w in words)]

    if buying_mode == "brief":
        scored = sorted(candidates, key=lambda p: _score(p, brief or ""), reverse=True)
        matched = [p for p in scored if _score(p, brief or "") > 0] or scored[:3]
        products = []
        for p in matched:
            wire = catalog.public_product(p)
            s = _score(p, brief or "")
            wire["brief_relevance"] = (
                f"Matched {s} brief signal(s) for the '{p['_moment']}' moment."
                if s
                else f"No direct keyword match; the '{p['_moment']}' moment is a broad developer reach option."
            )
            hints = stack_hints(brief or "")
            if hints:
                wire["brief_relevance"] += (
                    " Suggested stack signals for targeting_overlay.signal_targeting_groups: " + ", ".join(hints) + "."
                )
            products.append(wire)
    else:
        products = [catalog.public_product(p) for p in candidates]

    if configured:
        # Targeting-aware discovery: products are configured for this request and expire.
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        for p in products:
            p["is_custom"] = True
            p["expires_at"] = expires

    if fields:
        keep = set(fields) | {"product_id", "name"}
        products = [{k: v for k, v in p.items() if k in keep} for p in products]

    result: dict[str, Any] = {
        "status": "completed",
        "message": f"{len(products)} terminal moment(s) available.",
        "products": products,
        "cache_scope": "public",
    }
    if buying_mode == "wholesale":
        result["wholesale_feed_version"] = "stdout-v1"
    if excluded:
        result["filter_diagnostics"] = {"semantics": "only", "total_candidates": len(PRODUCTS), "excluded_by": excluded}
    return _with_context(result, context)


@mcp.tool
def list_creative_formats(
    format_ids: list[dict] | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Deprecated 3.x compatibility surface: named formats for terminal_line and terminal_box."""
    formats = []
    for fid, f in FORMATS.items():
        formats.append(
            {
                "format_id": {"agent_url": SELLER_URL, "id": fid},
                "name": f["display_name"],
                "description": "Text-only sponsored message rendered by the adterm wrapper. No images, no escape sequences.",
                "assets": [
                    {
                        "item_type": "individual",
                        "asset_id": s["asset_group_id"],
                        "asset_type": s["asset_type"],
                        "required": s["required"],
                    }
                    for s in f["params"]["slots"]
                ],
            }
        )
    return _with_context({"status": "completed", "formats": formats}, context)


def _resolve_times(start_time: str, end_time: str) -> tuple[str, str, dict | None]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        start = now if start_time == "asap" else parse_iso(start_time)
        end = parse_iso(end_time)
    except (TypeError, ValueError):
        return "", "", _err("INVALID_REQUEST", "start_time must be 'asap' or ISO 8601; end_time must be ISO 8601.", "start_time")
    if start_time != "asap" and start < now - timedelta(minutes=5):
        return "", "", _err("INVALID_REQUEST", "start_time must not be in the past.", "start_time")
    if end <= start:
        return "", "", _err("INVALID_REQUEST", "end_time must be after start_time.", "end_time")
    iso = lambda d: d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")  # noqa: E731
    return iso(start), iso(end), None


@mcp.tool
def create_media_buy(
    brand: dict,
    start_time: str,
    end_time: str,
    packages: list[dict] | None = None,
    account: dict | None = None,
    name: str | None = None,
    total_budget: dict | None = None,
    po_number: str | None = None,
    paused: bool | None = None,
    proposal_id: str | None = None,
    idempotency_key: str | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Buy terminal moments. Non-guaranteed CPM, so this confirms synchronously."""
    args = dict(locals())

    def run() -> dict:
        if proposal_id:
            return {"errors": [_err("PROPOSAL_NOT_FOUND", "stdout Network does not issue proposals; send packages.", "proposal_id")]}
        if not packages:
            return {"errors": [_err("INVALID_REQUEST", "At least one package is required.", "packages")]}
        acct, aerr = _resolve_account(account, brand)
        if aerr:
            return {"errors": [aerr]}
        start, end, terr = _resolve_times(start_time, end_time)
        if terr:
            return {"errors": [terr]}

        planned = []
        for i, pk in enumerate(packages):
            product = PRODUCTS_BY_ID.get(pk.get("product_id", ""))
            if not product:
                return {"errors": [_err("PRODUCT_NOT_FOUND", f"Unknown product_id '{pk.get('product_id')}'.", f"packages[{i}].product_id")]}
            po = catalog.pricing_option(product, pk.get("pricing_option_id", ""))
            if not po:
                return {"errors": [_err("INVALID_PRICING_OPTION", "pricing_option_id not offered on this product.", f"packages[{i}].pricing_option_id")]}
            budget = pk.get("budget")
            if not isinstance(budget, (int, float)) or budget <= 0:
                return {"errors": [_err("INVALID_REQUEST", "Each package needs a positive budget.", f"packages[{i}].budget")]}
            if budget < 50:
                return {"errors": [_err("BUDGET_TOO_LOW", "Minimum package budget is 50 GBP.", f"packages[{i}].budget")]}
            fmt_ids = [fo["format_option_id"] for fo in product["format_options"]]
            refs = pk.get("format_option_refs") or []
            fmt = fmt_ids[0]
            if refs:
                wanted = refs[0].get("format_option_id")
                if wanted not in fmt_ids:
                    return {
                        "errors": [
                            _err(
                                "UNSUPPORTED_FEATURE",
                                f"Product '{product['product_id']}' does not accept format option '{wanted}'.",
                                f"packages[{i}].format_option_refs[0]",
                                supported_format_option_refs=[{"scope": "product", "format_option_id": x} for x in fmt_ids],
                            )
                        ]
                    }
                fmt = wanted
            targeting, oerr = _validate_overlay(pk.get("targeting_overlay"), f"packages[{i}].targeting_overlay")
            if oerr:
                return {"errors": [oerr]}
            pk["_targeting"] = targeting
            planned.append((pk, product, po, fmt))

        if total_budget:
            if total_budget.get("currency") not in (None, CURRENCY):
                return {"errors": [_err("INVALID_REQUEST", "stdout Network transacts in GBP only.", "total_budget.currency")]}
            if abs(sum(p[0]["budget"] for p in planned) - float(total_budget.get("amount", 0))) > 0.01:
                return {"errors": [_err("INVALID_REQUEST", "total_budget must equal the sum of package budgets.", "total_budget")]}

        # Validate inline creatives before any mutation (the facade is atomic).
        for i, (pk, _product, _po, fmt) in enumerate(planned):
            for j, c in enumerate(pk.get("creatives") or []):
                c_fmt = _format_option_from_creative(c) or fmt
                if c_fmt != fmt:
                    return {"errors": [_err("UNSUPPORTED_FEATURE", f"Creative format '{c_fmt}' does not match package format '{fmt}'.", f"packages[{i}].creatives[{j}]")]}
            for j, ca in enumerate(pk.get("creative_assignments") or []):
                if not store.one("SELECT 1 FROM creatives WHERE account_id=? AND creative_id=?", (acct["account_id"], ca.get("creative_id"))):
                    return {"errors": [_err("CREATIVE_NOT_FOUND", f"Unknown creative_id '{ca.get('creative_id')}'.", f"packages[{i}].creative_assignments[{j}]")]}

        media_buy_id = _id("mb")
        confirmed = now_iso()
        deadline = start if parse_iso(start) > datetime.now(timezone.utc) else end
        with store.tx():
            store._conn.execute(
                "INSERT INTO media_buys (media_buy_id, account_id, brand_domain, name, start_time, end_time, paused, revision, currency, confirmed_at, creative_deadline, context_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (media_buy_id, acct["account_id"], brand["domain"], name, start, end, int(bool(paused)), 1, CURRENCY, confirmed, deadline,
                 json.dumps(context) if context is not None else None, confirmed),
            )
            for pk, product, po, fmt in planned:
                package_id = _id("pkg")
                store._conn.execute(
                    "INSERT INTO packages (package_id, media_buy_id, product_id, pricing_option_id, format_option_id, budget, cpm, paused, context_json, targeting_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (package_id, media_buy_id, product["product_id"], po["pricing_option_id"], fmt, float(pk["budget"]), po["fixed_price"],
                     int(bool(pk.get("paused"))), json.dumps(pk["context"]) if pk.get("context") is not None else None,
                     json.dumps(pk["_targeting"]) if pk.get("_targeting") else None, now_iso()),
                )
                pk["_package_id"] = package_id
        # Creatives and assignments go in after the commit; review state never rolls back a buy.
        for pk, _product, _po, fmt in planned:
            for c in pk.get("creatives") or []:
                c = dict(c)
                c.setdefault("format_option_ref", {"scope": "product", "format_option_id": fmt})
                _upsert_creative(acct["account_id"], c)
                store.x("INSERT OR REPLACE INTO assignments VALUES (?,?,?)", (pk["_package_id"], c["creative_id"], 100))
            for ca in pk.get("creative_assignments") or []:
                store.x("INSERT OR REPLACE INTO assignments VALUES (?,?,?)", (pk["_package_id"], ca["creative_id"], float(ca.get("weight", 100))))

        mb = store.one("SELECT * FROM media_buys WHERE media_buy_id=?", (media_buy_id,))
        return {"status": "completed", **_media_buy_wire(mb)}

    return _with_context(_idempotent("create_media_buy", idempotency_key, args, run), context)


@mcp.tool
def update_media_buy(
    media_buy_id: str,
    revision: int | None = None,
    paused: bool | None = None,
    end_time: str | None = None,
    packages: list[dict] | None = None,
    account: dict | None = None,
    idempotency_key: str | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Pause/resume a buy, extend its flight, or change package budgets, pause state and targeting.

    targeting_overlay updates replace per dimension: a value replaces that dimension, null clears it,
    and omitted dimensions are kept.
    """
    args = dict(locals())

    def run() -> dict:
        mb = store.one("SELECT * FROM media_buys WHERE media_buy_id=?", (media_buy_id,))
        if not mb:
            return {"errors": [_err("MEDIA_BUY_NOT_FOUND", "Unknown media_buy_id.", "media_buy_id")]}
        if revision is not None and revision != mb["revision"]:
            return {"errors": [_err("REVISION_CONFLICT", f"Current revision is {mb['revision']}.", "revision")]}
        if end_time:
            try:
                if parse_iso(end_time) <= parse_iso(mb["start_time"]):
                    raise ValueError
            except ValueError:
                return {"errors": [_err("INVALID_REQUEST", "end_time must be ISO 8601 and after start_time.", "end_time")]}

        # Validate everything before mutating anything.
        changes = []
        for i, pk in enumerate(packages or []):
            row = store.one("SELECT * FROM packages WHERE package_id=? AND media_buy_id=?", (pk.get("package_id"), media_buy_id))
            if not row:
                return {"errors": [_err("PACKAGE_NOT_FOUND", "Unknown package_id for this media buy.", f"packages[{i}].package_id")]}
            if "budget" in pk and pk["budget"] < _package_spend(row):
                return {"errors": [_err("INVALID_REQUEST", "Budget cannot go below spend to date.", f"packages[{i}].budget")]}
            new_targeting = json.loads(row["targeting_json"]) if row.get("targeting_json") else {}
            if "targeting_overlay" in pk:
                patch = pk["targeting_overlay"] or {}
                merged = {**new_targeting, **{k: v for k, v in patch.items() if v is not None}}
                for k, v in patch.items():
                    if v is None:
                        merged.pop(k, None)
                checked, oerr = _validate_overlay(merged, f"packages[{i}].targeting_overlay")
                if oerr:
                    return {"errors": [oerr]}
                new_targeting = checked or {}
            changes.append((pk, row, new_targeting))

        if paused is not None:
            store.x("UPDATE media_buys SET paused=? WHERE media_buy_id=?", (int(paused), media_buy_id))
        if end_time:
            store.x("UPDATE media_buys SET end_time=? WHERE media_buy_id=?", (end_time, media_buy_id))
        for pk, row, new_targeting in changes:
            if "budget" in pk:
                store.x("UPDATE packages SET budget=? WHERE package_id=?", (float(pk["budget"]), row["package_id"]))
            if "paused" in pk:
                store.x("UPDATE packages SET paused=? WHERE package_id=?", (int(bool(pk["paused"])), row["package_id"]))
            if "targeting_overlay" in pk:
                store.x(
                    "UPDATE packages SET targeting_json=? WHERE package_id=?",
                    (json.dumps(new_targeting) if new_targeting else None, row["package_id"]),
                )
        store.x("UPDATE media_buys SET revision=revision+1 WHERE media_buy_id=?", (media_buy_id,))
        mb = store.one("SELECT * FROM media_buys WHERE media_buy_id=?", (media_buy_id,))
        wire = _media_buy_wire(mb)
        return {
            "status": "completed",
            "media_buy_id": media_buy_id,
            "media_buy_status": wire["media_buy_status"],
            "revision": mb["revision"],
            "currency": CURRENCY,
            "total_budget": wire["total_budget"],
            "affected_packages": wire["packages"],
        }

    return _with_context(_idempotent("update_media_buy", idempotency_key, args, run), context)


@mcp.tool
def get_media_buys(
    media_buy_ids: list[str] | None = None,
    status_filter: str | list[str] | None = None,
    account: dict | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Read back media buys, packages, creative assignments and lifecycle status."""
    rows = store.q("SELECT * FROM media_buys ORDER BY created_at")
    if account and account.get("account_id"):
        rows = [r for r in rows if r["account_id"] == account["account_id"]]
    if media_buy_ids:
        rows = [r for r in rows if r["media_buy_id"] in media_buy_ids]
    buys = [_media_buy_wire(r) for r in rows]
    if status_filter:
        wanted = [status_filter] if isinstance(status_filter, str) else status_filter
        buys = [b for b in buys if b["media_buy_status"] in wanted]
    for b in buys:
        b["status"] = b.pop("media_buy_status")
    return _with_context({"status": "completed", "media_buys": buys}, context)


@mcp.tool
def sync_creatives(
    creatives: list[dict],
    account: dict | None = None,
    assignments: list[dict] | None = None,
    creative_ids: list[str] | None = None,
    dry_run: bool = False,
    validation_mode: str | None = None,
    delete_missing: bool = False,
    idempotency_key: str | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Upload or update text creatives. Review is automated and synchronous (approved or rejected)."""
    args = dict(locals())

    def run() -> dict:
        acct, aerr = _resolve_account(account, None)
        if aerr:
            return {"errors": [aerr]}
        ids = [c.get("creative_id") for c in creatives]
        if len(ids) != len(set(ids)):
            return {"errors": [_err("INVALID_REQUEST", "creative_id values must be unique within one request.", "creatives")]}
        scoped = [c for c in creatives if not creative_ids or c.get("creative_id") in creative_ids]
        if dry_run:
            results = []
            for c in scoped:
                status, problems = _review_creative(_format_option_from_creative(c), c.get("assets") or {})
                r = {"creative_id": c.get("creative_id", ""), "action": "unchanged", "status": status}
                if problems:
                    r["warnings"] = problems
                results.append(r)
            return {"status": "completed", "dry_run": True, "creatives": results}
        results = [_upsert_creative(acct["account_id"], c) for c in scoped]
        assigned: dict[str, list[str]] = {}
        for a in assignments or []:
            pkg = store.one(
                "SELECT p.package_id FROM packages p JOIN media_buys m ON m.media_buy_id=p.media_buy_id WHERE p.package_id=? AND m.account_id=?",
                (a.get("package_id"), acct["account_id"]),
            )
            if not pkg:
                for r in results:
                    if r["creative_id"] == a.get("creative_id"):
                        r.setdefault("warnings", []).append(f"Package '{a.get('package_id')}' not found; not assigned.")
                continue
            store.x("INSERT OR REPLACE INTO assignments VALUES (?,?,?)", (a["package_id"], a["creative_id"], float(a.get("weight", 100))))
            assigned.setdefault(a["creative_id"], []).append(a["package_id"])
        for r in results:
            if r["creative_id"] in assigned:
                r["assigned_to"] = assigned[r["creative_id"]]
        return {"status": "completed", "creatives": results}

    return _with_context(_idempotent("sync_creatives", idempotency_key, args, run), context)


@mcp.tool
def list_creatives(
    account: dict | None = None,
    filters: dict | None = None,
    pagination: dict | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Browse the creative library with review status."""
    rows = store.q("SELECT * FROM creatives ORDER BY created_at")
    if account and account.get("account_id"):
        rows = [r for r in rows if r["account_id"] == account["account_id"]]
    out = []
    for r in rows:
        item = {
            "creative_id": r["creative_id"],
            "name": r["name"],
            "format_kind": "native_in_feed",
            "format_option_ref": {"scope": "product", "format_option_id": r["format_option_id"]},
            "status": r["status"],
            "created_date": r["created_at"],
            "updated_date": r["updated_at"],
            "assets": json.loads(r["assets_json"]),
        }
        if r["revision_id"]:
            item["revision_id"] = r["revision_id"]
        out.append(item)
    return _with_context(
        {
            "status": "completed",
            "query_summary": {"total_matching": len(out), "returned": len(out)},
            "pagination": {"has_more": False},
            "creatives": out,
        },
        context,
    )


def _date_bounds(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None, dict | None]:
    if bool(start_date) != bool(end_date):
        return None, None, _err("VALIDATION_ERROR", "Provide both start_date and end_date, or neither.", "start_date")
    if not start_date:
        return None, None, None
    try:
        s, e = date.fromisoformat(start_date), date.fromisoformat(end_date)  # type: ignore[arg-type]
    except ValueError:
        return None, None, _err("INVALID_REQUEST", "Dates must be YYYY-MM-DD.", "start_date")
    if e <= s:
        return None, None, _err("VALIDATION_ERROR", "end_date is exclusive and must be after start_date.", "end_date")
    return f"{s.isoformat()}T00:00:00Z", f"{e.isoformat()}T00:00:00Z", None


@mcp.tool
def get_media_buy_delivery(
    media_buy_ids: list[str] | None = None,
    status_filter: str | list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    account: dict | None = None,
    reporting_dimensions: dict | None = None,
    adcp_major_version: int | None = None,
    context: dict | None = None,
) -> dict:
    """Delivery: rendered impressions (what bills), clicks, spend and pacing per package."""
    p_start, p_end, derr = _date_bounds(start_date, end_date)
    if derr:
        return {"errors": [derr]}
    rows = store.q("SELECT * FROM media_buys ORDER BY created_at")
    if account and account.get("account_id"):
        rows = [r for r in rows if r["account_id"] == account["account_id"]]
    if media_buy_ids:
        rows = [r for r in rows if r["media_buy_id"] in media_buy_ids]
    wanted = None
    if status_filter:
        wanted = [status_filter] if isinstance(status_filter, str) else status_filter
    elif not media_buy_ids:
        wanted = ["active"]

    now = datetime.now(timezone.utc)
    deliveries = []
    earliest = None
    for mb in rows:
        status = _media_buy_status(mb)
        if wanted and status not in wanted:
            continue
        mb_start, mb_end = parse_iso(mb["start_time"]), parse_iso(mb["end_time"])
        earliest = mb_start if earliest is None or mb_start < earliest else earliest
        elapsed = max(0.0, min(1.0, (now - mb_start).total_seconds() / max(1.0, (mb_end - mb_start).total_seconds())))
        by_package = []
        t_imps = t_clicks = 0
        t_spend = 0.0
        for pkg in store.q("SELECT * FROM packages WHERE media_buy_id=? ORDER BY created_at", (mb["media_buy_id"],)):
            imps, clicks = _spend_impressions(pkg["package_id"], p_start, p_end)
            spend = round(imps * pkg["cpm"] / 1000.0, 4)
            lifetime_spend = _package_spend(pkg)
            expected = pkg["budget"] * elapsed
            if lifetime_spend >= pkg["budget"]:
                dstatus = "budget_exhausted"
            elif mb_end <= now:
                dstatus = "flight_ended"
            elif imps:
                dstatus = "delivering"
            else:
                dstatus = "not_delivering" if status == "active" else "delivering"
            row: dict[str, Any] = {
                "package_id": pkg["package_id"],
                "product_id": pkg["product_id"],
                "impressions": imps,
                "spend": spend,
                "clicks": clicks,
                "ctr": round(clicks / imps, 4) if imps else 0,
                "pricing_model": "cpm",
                "rate": pkg["cpm"],
                "currency": CURRENCY,
                "paused": bool(pkg["paused"] or mb["paused"]),
                "delivery_status": dstatus,
                "pacing_index": round(lifetime_spend / expected, 3) if expected > 0 else 0,
            }
            creatives_rows = store.q(
                "SELECT creative_id, COUNT(rendered_at) AS imps, COUNT(clicked_at) AS clicks FROM impressions "
                "WHERE package_id=? AND rendered_at IS NOT NULL" + (" AND rendered_at >= ? AND rendered_at < ?" if p_start else "")
                + " GROUP BY creative_id",
                (pkg["package_id"], p_start, p_end) if p_start else (pkg["package_id"],),
            )
            if creatives_rows:
                row["by_creative"] = [
                    {
                        "creative_id": c["creative_id"],
                        "impressions": c["imps"],
                        "spend": round(c["imps"] * pkg["cpm"] / 1000.0, 4),
                        "clicks": c["clicks"],
                        "ctr": round(c["clicks"] / c["imps"], 4) if c["imps"] else 0,
                    }
                    for c in creatives_rows
                ]
                row["by_creative_truncated"] = False
            geo_req = (reporting_dimensions or {}).get("geo")
            if isinstance(geo_req, dict) and geo_req.get("geo_level") == "country":
                sort_by = geo_req.get("sort_by", "spend")
                if sort_by not in ("spend", "impressions", "clicks"):
                    sort_by = "spend"
                direction = geo_req.get("sort_direction", "desc")
                geo_rows = store.q(
                    "SELECT COALESCE(country, 'ZZ') AS cc, COUNT(rendered_at) AS imps, COUNT(clicked_at) AS clicks FROM impressions "
                    "WHERE package_id=? AND rendered_at IS NOT NULL" + (" AND rendered_at >= ? AND rendered_at < ?" if p_start else "")
                    + " GROUP BY cc",
                    (pkg["package_id"], p_start, p_end) if p_start else (pkg["package_id"],),
                )
                by_geo = [
                    {
                        "geo_level": "country",
                        "geo_code": g["cc"],
                        "impressions": g["imps"],
                        "spend": round(g["imps"] * pkg["cpm"] / 1000.0, 4),
                        "clicks": g["clicks"],
                    }
                    for g in geo_rows
                ]
                by_geo.sort(key=lambda g: g[sort_by], reverse=(direction == "desc"))
                limit = geo_req.get("limit")
                row["by_geo"] = by_geo[:limit] if isinstance(limit, int) and limit > 0 else by_geo
                row["by_geo_truncated"] = len(row["by_geo"]) < len(by_geo)
                row["by_geo_sorted_by"] = sort_by
                row["by_geo_sort_direction"] = direction
            by_package.append(row)
            t_imps += imps
            t_clicks += clicks
            t_spend += spend
        daily = store.q(
            "SELECT substr(i.rendered_at,1,10) AS d, COUNT(*) AS imps, SUM(p.cpm)/1000.0 AS spend FROM impressions i "
            "JOIN packages p ON p.package_id=i.package_id WHERE p.media_buy_id=? AND i.rendered_at IS NOT NULL"
            + (" AND i.rendered_at >= ? AND i.rendered_at < ?" if p_start else "")
            + " GROUP BY d ORDER BY d",
            (mb["media_buy_id"], p_start, p_end) if p_start else (mb["media_buy_id"],),
        )
        deliveries.append(
            {
                "media_buy_id": mb["media_buy_id"],
                "currency": CURRENCY,
                "status": status,
                "totals": {
                    "impressions": t_imps,
                    "spend": round(t_spend, 4),
                    "clicks": t_clicks,
                    "ctr": round(t_clicks / t_imps, 4) if t_imps else 0,
                },
                "by_package": by_package,
                "daily_breakdown": [{"date": d["d"], "impressions": d["imps"], "spend": round(d["spend"], 4)} for d in daily],
            }
        )

    iso = lambda d: d.replace(microsecond=0).isoformat().replace("+00:00", "Z")  # noqa: E731
    period_start = p_start or (iso(earliest) if earliest else iso(now))
    period_end = p_end or iso(now)
    return _with_context(
        {
            "status": "completed",
            "reporting_period": {"start": period_start, "end": period_end, "timezone": "UTC"},
            "media_buy_deliveries": deliveries,
        },
        context,
    )


# ---------------------------------------------------------------------------
# Ad serving (plain HTTP for the adterm wrapper)
# ---------------------------------------------------------------------------


SLATE_SIZE = 12

# Country comes from a trusted edge (Cloudflare, Vercel, CloudFront) or, for local
# development, from STDOUT_DEV_COUNTRY on loopback requests. The IP itself is
# never stored. Geo headers are only trusted when STDOUT_TRUST_GEO_HEADERS=1,
# because a client talking to the seller directly could otherwise spoof them.
_GEO_HEADERS = ("cf-ipcountry", "x-vercel-ip-country", "cloudfront-viewer-country", "x-country-code")
_NOT_A_COUNTRY = {"XX", "T1", "ZZ", "A1", "A2", "EU", "AP"}


def _country_for(request: Request) -> str | None:
    if os.environ.get("STDOUT_TRUST_GEO_HEADERS") == "1":
        for h in _GEO_HEADERS:
            v = (request.headers.get(h) or "").strip().upper()
            if _COUNTRY.match(v) and v not in _NOT_A_COUNTRY:
                return v
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        dev = os.environ.get("STDOUT_DEV_COUNTRY", "GB").strip().upper()
        return dev if _COUNTRY.match(dev) else None
    db = os.environ.get("STDOUT_GEOIP_DB")
    if db:
        try:
            import geoip2.database  # optional: pip install geoip2, plus a GeoLite2-Country.mmdb

            with geoip2.database.Reader(db) as reader:
                return reader.country(host).country.iso_code
        except Exception:
            return None
    return None


def _slate(moment: str, country: str | None) -> list[dict]:
    """Every ad eligible server-side (moment, flight, budget, country), ranked by weight.

    Stack-signal targeting is NOT applied here. It travels with each candidate as a
    rule and adterm applies it on the developer's machine.
    """
    product = PRODUCT_BY_MOMENT.get(moment)
    if not product:
        return []
    now = datetime.now(timezone.utc)
    candidates = []
    for pkg in store.q("SELECT * FROM packages WHERE product_id=? AND paused=0", (product["product_id"],)):
        mb = store.one("SELECT * FROM media_buys WHERE media_buy_id=?", (pkg["media_buy_id"],))
        if not mb or mb["paused"] or not (parse_iso(mb["start_time"]) <= now < parse_iso(mb["end_time"])):
            continue
        targeting = json.loads(pkg["targeting_json"]) if pkg.get("targeting_json") else None
        if not _geo_ok(targeting, country):
            continue
        remaining = pkg["budget"] - _package_spend(pkg)
        if remaining <= 0:
            continue
        creatives = store.q(
            "SELECT c.*, a.weight FROM assignments a JOIN creatives c ON c.creative_id=a.creative_id AND c.account_id=? "
            "WHERE a.package_id=? AND c.status='approved'",
            (mb["account_id"], pkg["package_id"]),
        )
        for c in creatives:
            candidates.append({"weight": remaining * max(c["weight"], 0.01), "pkg": pkg, "mb": mb, "creative": c, "targeting": targeting})
    candidates.sort(key=lambda x: x["weight"], reverse=True)
    return candidates[:SLATE_SIZE]


@mcp.custom_route("/serve", methods=["POST"])
async def serve(request: Request) -> Response:
    """Return a slate of eligible ads. adterm picks one on-device and beacons only that one."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    moment = str(body.get("moment", ""))
    tool = str(body.get("tool", ""))[:32]
    country = _country_for(request)
    candidates = _slate(moment, country)
    if not candidates:
        return Response(status_code=204)

    slate, used_signals = [], set()
    served = now_iso()
    for cand in candidates:
        pkg, c = cand["pkg"], cand["creative"]
        assets = json.loads(c["assets_json"])
        text = lambda k, a=assets: (a.get(k) or {}).get("content")  # noqa: E731
        rules = _compile_rules(cand["targeting"])
        used_signals.update(sid for g in rules["any_of_groups"] for sid in g)
        used_signals.update(rules["none_of"])
        impression_id = secrets.token_urlsafe(9)
        # One row per offered candidate; only the one adterm beacons is ever billed.
        store.x(
            "INSERT INTO impressions (impression_id, package_id, creative_id, moment, tool, country, served_at) VALUES (?,?,?,?,?,?,?)",
            (impression_id, pkg["package_id"], c["creative_id"], moment, tool, country, served),
        )
        geo = (cand["targeting"] or {}).get("geo_countries")
        slate.append(
            _clean(
                {
                    "impression_id": impression_id,
                    "weight": round(cand["weight"], 4),
                    "rules": rules,
                    "format": c["format_option_id"],
                    "advertiser": text("advertiser_name"),
                    "title": text("title"),
                    "body": text("body_text"),
                    "cta": text("cta"),
                    "landing_url": (assets.get("landing_page_url") or {}).get("url"),
                    "click_url": f"{SELLER_URL}/c/{impression_id}",
                    "beacon_url": f"{SELLER_URL}/imp/{impression_id}",
                    "why": _clean(
                        {
                            "network": "stdout Network",
                            "bought_via": "AdCP 3.2 create_media_buy",
                            "media_buy_id": cand["mb"]["media_buy_id"],
                            "product_id": pkg["product_id"],
                            "moment": moment,
                            "country_targeting": ", ".join(geo) if geo else None,
                            "identifiers_received": "none",
                        }
                    ),
                }
            )
        )
    signals = {sid: {"deps": catalog.SIGNALS[sid]["deps"], "files": catalog.SIGNALS[sid]["files"]} for sid in sorted(used_signals)}
    return JSONResponse({"slate": slate, "signals": signals, "country": country})


@mcp.custom_route("/imp/{impression_id}", methods=["POST"])
async def impression(request: Request) -> Response:
    imp_id = request.path_params["impression_id"]
    store.x("UPDATE impressions SET rendered_at=? WHERE impression_id=? AND rendered_at IS NULL", (now_iso(), imp_id))
    return Response(status_code=204)


@mcp.custom_route("/c/{impression_id}", methods=["GET"])
async def click(request: Request) -> Response:
    imp_id = request.path_params["impression_id"]
    row = store.one("SELECT * FROM impressions WHERE impression_id=?", (imp_id,))
    if not row:
        return PlainTextResponse("Unknown or expired link.", status_code=404)
    store.x("UPDATE impressions SET clicked_at=? WHERE impression_id=? AND clicked_at IS NULL", (now_iso(), imp_id))
    mb = store.one(
        "SELECT m.account_id FROM packages p JOIN media_buys m ON m.media_buy_id=p.media_buy_id WHERE p.package_id=?",
        (row["package_id"],),
    )
    c = store.one("SELECT assets_json FROM creatives WHERE account_id=? AND creative_id=?", (mb["account_id"], row["creative_id"])) if mb else None
    url = (json.loads(c["assets_json"]).get("landing_page_url") or {}).get("url") if c else None
    if not url or urlparse(url).scheme != "https":
        return PlainTextResponse("No landing page.", status_code=404)
    return RedirectResponse(url, status_code=302)


@mcp.custom_route("/.well-known/adagents.json", methods=["GET"])
async def adagents(request: Request) -> Response:
    """Publisher declaration for the demo. In production this lives on the publisher's own domain."""
    return JSONResponse(
        {
            "contact": {"name": "stdout Network", "domain": PUBLISHER_DOMAIN},
            "properties": [
                {
                    "property_id": "adterm_cli",
                    "property_type": "desktop_app",
                    "name": "adterm terminal wrapper",
                    "identifiers": [{"type": "domain", "value": PUBLISHER_DOMAIN}],
                    "tags": ["terminal"],
                    "supported_channels": ["display"],
                }
            ],
            "formats": [{k: v for k, v in f.items()} for f in FORMATS.values()],
            "authorized_agents": [
                {
                    "url": f"{SELLER_URL}/mcp",
                    "authorized_for": "All stdout Network terminal inventory",
                    "authorization_type": "property_tags",
                    "property_tags": ["terminal"],
                }
            ],
            "last_updated": now_iso(),
        }
    )


@mcp.custom_route("/signals.json", methods=["GET"])
async def signals_json(request: Request) -> Response:
    """Public signal definitions so `adterm --signals` can show what it would match locally."""
    return JSONResponse(
        {"signals": {sid: {"name": s["name"], "deps": s["deps"], "files": s["files"]} for sid, s in catalog.SIGNALS.items()}}
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"ok": True, "service": "stdout-network-seller", "adcp": "3.2"})


# ---------------------------------------------------------------------------
# Forward compatibility: ignore request fields this seller does not model
# ---------------------------------------------------------------------------
# AdCP buyers send optional fields this demo does not implement (ext,
# adcp_version, push_notification_config, targeting_overlay, ...). Strict
# argument validation would reject the whole call, so unknown keys are dropped
# before the tool runs. Anything that changes commercial meaning is still
# validated inside the tool itself.

import inspect  # noqa: E402

from fastmcp.server.middleware import Middleware, MiddlewareContext  # noqa: E402

_TOOL_FUNCS = [
    get_adcp_capabilities, sync_accounts, list_accounts, get_products, list_creative_formats,
    create_media_buy, update_media_buy, get_media_buys, sync_creatives, list_creatives, get_media_buy_delivery,
]
ALLOWED_ARGS = {
    getattr(f, "name", getattr(f, "__name__", "")): set(inspect.signature(getattr(f, "fn", f)).parameters)
    for f in _TOOL_FUNCS
}


class IgnoreUnknownArgs(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        allowed = ALLOWED_ARGS.get(context.message.name)
        args = context.message.arguments
        if allowed is not None and isinstance(args, dict):
            for key in [k for k in args if k not in allowed]:
                args.pop(key)
        return await call_next(context)


mcp.add_middleware(IgnoreUnknownArgs())


def main() -> None:
    transport = os.environ.get("STDOUT_TRANSPORT", "http")
    host = os.environ.get("STDOUT_HOST", "127.0.0.1")
    port = int(os.environ.get("STDOUT_PORT", "8080"))
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    main()
