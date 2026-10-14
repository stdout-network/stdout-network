"""stdout Network - the inventory catalogue.

Every product is a "moment" in a developer's terminal session. The opt-in
`adterm` wrapper reports which moment it is in (install, build, tests passed,
shipped, failed) and the seller fills it from active media buys.

Creative contract: canonical `native_in_feed` (AdCP 3.2), narrowed to
text-only slots. A sponsored line in a stream of terminal output is an
in-feed native unit; the terminal is the feed. No images, no icons, and no
buyer-supplied control characters (see creative review in server.py).
"""

from __future__ import annotations

import os

PUBLISHER_DOMAIN = os.environ.get("STDOUT_PUBLISHER_DOMAIN", "stdout.example")
CURRENCY = "GBP"
REPORTING_TZ = "UTC"

# ---------------------------------------------------------------------------
# Format declarations (canonical native_in_feed, text-only)
# ---------------------------------------------------------------------------

LINE_TITLE_MAX = 72
BOX_TITLE_MAX = 60
BOX_BODY_MAX = 140
CTA_MAX = 20
ADVERTISER_MAX = 32

TERMINAL_LINE = {
    "format_kind": "native_in_feed",
    "format_option_id": "terminal_line",
    "display_name": "Terminal sponsored line (single line, text only)",
    "technical_requirements_complete": True,
    "params": {
        "title_max_chars": LINE_TITLE_MAX,
        "cta_max_chars": CTA_MAX,
        "ssl_required": True,
        "asset_source": "buyer_uploaded",
        "slots": [
            {"asset_group_id": "title", "asset_type": "text", "required": True},
            {"asset_group_id": "advertiser_name", "asset_type": "text", "required": True},
            {"asset_group_id": "cta", "asset_type": "text", "required": False},
            {"asset_group_id": "landing_page_url", "asset_type": "url", "required": True},
        ],
    },
}

TERMINAL_BOX = {
    "format_kind": "native_in_feed",
    "format_option_id": "terminal_box",
    "display_name": "Terminal box takeover (title + body, text only)",
    "technical_requirements_complete": True,
    "params": {
        "title_max_chars": BOX_TITLE_MAX,
        "body_text_max_chars": BOX_BODY_MAX,
        "cta_max_chars": CTA_MAX,
        "ssl_required": True,
        "asset_source": "buyer_uploaded",
        "slots": [
            {"asset_group_id": "title", "asset_type": "text", "required": True},
            {"asset_group_id": "body_text", "asset_type": "text", "required": True},
            {"asset_group_id": "advertiser_name", "asset_type": "text", "required": True},
            {"asset_group_id": "cta", "asset_type": "text", "required": False},
            {"asset_group_id": "landing_page_url", "asset_type": "url", "required": True},
        ],
    },
}

FORMATS = {f["format_option_id"]: f for f in (TERMINAL_LINE, TERMINAL_BOX)}

# Hard limits enforced at creative review, keyed by format option.
FORMAT_LIMITS = {
    "terminal_line": {"title": LINE_TITLE_MAX, "cta": CTA_MAX, "advertiser_name": ADVERTISER_MAX},
    "terminal_box": {
        "title": BOX_TITLE_MAX,
        "body_text": BOX_BODY_MAX,
        "cta": CTA_MAX,
        "advertiser_name": ADVERTISER_MAX,
    },
}
REQUIRED_SLOTS = {
    fid: [s["asset_group_id"] for s in f["params"]["slots"] if s["required"]] for fid, f in FORMATS.items()
}

# ---------------------------------------------------------------------------
# Products: one per terminal moment
# ---------------------------------------------------------------------------

_REPORTING = {
    "available_reporting_frequencies": ["hourly", "daily"],
    "expected_delay_minutes": 0,
    "timezone": REPORTING_TZ,
    "supports_webhooks": False,
    "available_metrics": ["impressions", "spend", "clicks", "ctr"],
    "date_range_support": "date_range",
    "supports_creative_breakdown": True,
    "supports_geo_breakdown": {"country": True},
}

# ---------------------------------------------------------------------------
# Stack signals, evaluated ON THE DEVELOPER'S MACHINE by adterm
# ---------------------------------------------------------------------------
# The seller never sees a dependency list. It ships these definitions with each
# ad slate; adterm reads the project's manifests locally, decides which signals
# are true, filters the slate and reports back only which ad it rendered.
#
#   deps  = package names to look for in package.json, requirements.txt,
#           pyproject.toml, Pipfile, Cargo.toml, go.mod and Gemfile
#   files = project files whose mere presence sets the signal (adterm only
#           checks names on its own fixed allow-list, never arbitrary paths)

SIGNALS: dict[str, dict] = {
    "lang_javascript": {"name": "JavaScript / TypeScript project", "files": ["package.json"], "deps": []},
    "lang_python": {"name": "Python project", "files": ["pyproject.toml", "requirements.txt", "Pipfile", "setup.py"], "deps": []},
    "lang_rust": {"name": "Rust project", "files": ["Cargo.toml"], "deps": []},
    "lang_go": {"name": "Go project", "files": ["go.mod"], "deps": []},
    "lang_ruby": {"name": "Ruby project", "files": ["Gemfile"], "deps": []},
    "stack_postgres": {
        "name": "Uses PostgreSQL",
        "files": [],
        "deps": ["pg", "postgres", "psycopg", "psycopg2", "psycopg2-binary", "asyncpg", "tokio-postgres",
                 "github.com/jackc/pgx/v5", "github.com/jackc/pgx/v4", "github.com/lib/pq", "@neondatabase/serverless"],
    },
    "stack_redis": {
        "name": "Uses Redis",
        "files": [],
        "deps": ["redis", "ioredis", "@upstash/redis", "github.com/redis/go-redis/v9", "github.com/go-redis/redis/v8"],
    },
    "stack_stripe": {
        "name": "Integrates Stripe",
        "files": [],
        "deps": ["stripe", "@stripe/stripe-js", "@stripe/react-stripe-js", "github.com/stripe/stripe-go/v76", "async-stripe"],
    },
    "stack_react": {"name": "Uses React", "files": [], "deps": ["react"]},
    "stack_nextjs": {"name": "Uses Next.js", "files": [], "deps": ["next"]},
    "stack_django": {"name": "Uses Django", "files": [], "deps": ["django"]},
    "stack_fastapi": {"name": "Uses FastAPI", "files": [], "deps": ["fastapi"]},
    "stack_llm_sdk": {
        "name": "Calls an LLM API",
        "files": [],
        "deps": ["openai", "anthropic", "@anthropic-ai/sdk", "langchain", "@langchain/core", "llama-index", "ai", "async-openai"],
    },
    "stack_docker": {"name": "Ships with Docker", "files": ["Dockerfile", "docker-compose.yml", "compose.yaml"], "deps": []},
}

# Words in a brief that point at a signal, used to suggest selections in brief_relevance.
SIGNAL_HINTS = {
    "lang_javascript": ["javascript", "typescript", "node"],
    "lang_python": ["python"],
    "lang_rust": ["rust"],
    "lang_go": ["golang", " go "],
    "lang_ruby": ["ruby", "rails"],
    "stack_postgres": ["postgres", "postgresql", "database"],
    "stack_redis": ["redis", "cache", "caching"],
    "stack_stripe": ["stripe", "payments", "billing"],
    "stack_react": ["react", "frontend"],
    "stack_nextjs": ["next.js", "nextjs"],
    "stack_django": ["django"],
    "stack_fastapi": ["fastapi"],
    "stack_llm_sdk": ["llm", " ai ", "openai", "anthropic", "agent"],
    "stack_docker": ["docker", "container"],
}

SIGNAL_OPTIONS = [
    {
        "signal_ref": {"scope": "product", "signal_id": sid},
        "name": s["name"],
        "description": "Evaluated on the developer's machine from project manifests. The seller never receives the dependency list.",
        "value_type": "binary",
    }
    for sid, s in SIGNALS.items()
]

SIGNAL_RULES = {
    "resolution_model": "direct_targeting",
    "selection_mode": "optional",
    "max_signal_targeting_groups": 4,
    "max_signals_per_targeting_group": 8,
}

OVERLAY_SUPPORT = {"geo_countries": True, "geo_countries_exclude": True, "signal_targeting_groups": True}
SUPPORTED_OVERLAY_KEYS = set(OVERLAY_SUPPORT)


def _product(
    product_id: str,
    moment: str,
    name: str,
    description: str,
    cpm: float,
    formats: list[dict],
    keywords: list[str],
) -> dict:
    return {
        "product_id": product_id,
        "name": name,
        "description": description,
        "publisher_properties": [
            {
                "publisher_domain": PUBLISHER_DOMAIN,
                "selection_type": "by_tag",
                "property_tags": ["terminal"],
            }
        ],
        "channels": ["display"],
        "format_options": formats,
        "delivery_type": "non_guaranteed",
        "pricing_options": [
            {
                "pricing_option_id": f"{product_id}_cpm_gbp",
                "pricing_model": "cpm",
                "currency": CURRENCY,
                "fixed_price": cpm,
            }
        ],
        "reporting_capabilities": dict(_REPORTING),
        "overlay_support": dict(OVERLAY_SUPPORT),
        "signal_targeting_allowed": True,
        "signal_targeting_options": SIGNAL_OPTIONS,
        "signal_targeting_rules": dict(SIGNAL_RULES),
        # Internal routing data, stripped before anything goes on the wire.
        "_moment": moment,
        "_keywords": keywords,
    }


PRODUCTS: list[dict] = [
    _product(
        "tty_install_sponsor",
        "install",
        "Install-Time Sponsored Line",
        "One sponsored line printed while a dependency install runs (npm, pnpm, yarn, bun, pip, uv, cargo add). "
        "Peak attention: the developer is staring at a progress bar with nothing else to do.",
        12.00,
        [TERMINAL_LINE],
        ["install", "npm", "package", "dependency", "javascript", "node", "python", "pip", "library", "sdk", "devtools", "developer"],
    ),
    _product(
        "tty_build_wait",
        "build",
        "Build-Wait Takeover",
        "A boxed message shown at the start of long builds (docker build, cargo build, make, vite/webpack/next build, tsc). "
        "Longest dwell time on the network. Pairs well with coffee.",
        18.00,
        [TERMINAL_BOX],
        ["build", "docker", "container", "compile", "rust", "ci", "infrastructure", "cloud", "hosting", "performance", "devtools"],
    ),
    _product(
        "tty_tests_green",
        "tests_green",
        "Green Tests Moment",
        "Shown only after a test suite exits 0 (pytest, jest, vitest, go test, cargo test, npm test). "
        "Contextual targeting on the single happiest moment in software development.",
        28.00,
        [TERMINAL_LINE],
        ["test", "testing", "quality", "qa", "observability", "monitoring", "error tracking", "developer"],
    ),
    _product(
        "tty_ship_it",
        "ship_it",
        "Ship-It Moment",
        "Shown after a successful git push or deploy (vercel, fly deploy, terraform apply, kubectl apply). "
        "Reaches developers at the point of maximum confidence and minimum review.",
        24.00,
        [TERMINAL_LINE],
        ["deploy", "git", "hosting", "cloud", "infrastructure", "ship", "release", "edge", "serverless"],
    ),
    _product(
        "tty_stack_trace",
        "failure",
        "Stack-Trace Adjacent (Remnant)",
        "Shown after any command exits non-zero. Heavily discounted because the audience is, at that moment, "
        "furious. Recommended only for debuggers, error trackers and therapists.",
        2.50,
        [TERMINAL_LINE],
        ["error", "debug", "observability", "monitoring", "error tracking", "logging", "support", "wellbeing"],
    ),
]

PRODUCTS_BY_ID = {p["product_id"]: p for p in PRODUCTS}
PRODUCT_BY_MOMENT = {p["_moment"]: p for p in PRODUCTS}

# Briefs the network politely declines (GetProductsRejected arm).
DECLINED_CATEGORIES = {
    "crypto": "Terminal users have seen enough airdrops. Crypto and token campaigns are not accepted.",
    "token sale": "Terminal users have seen enough airdrops. Crypto and token campaigns are not accepted.",
    "gambling": "Gambling campaigns are not accepted on stdout Network.",
    "casino": "Gambling campaigns are not accepted on stdout Network.",
    "recruit": "Developers already receive enough recruiter messages. Recruitment campaigns are not accepted.",
    "hiring": "Developers already receive enough recruiter messages. Recruitment campaigns are not accepted.",
}


def public_product(product: dict) -> dict:
    """Strip internal routing keys before a product goes on the wire."""
    return {k: v for k, v in product.items() if not k.startswith("_")}


def pricing_option(product: dict, pricing_option_id: str) -> dict | None:
    for po in product["pricing_options"]:
        if po["pricing_option_id"] == pricing_option_id:
            return po
    return None
