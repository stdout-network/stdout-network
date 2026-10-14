# stdout Network

An AdCP 3.2 seller agent for terminal advertising, plus `adterm`, the opt-in wrapper that renders the ads.

Buyer agents discover, buy and report on moments in a developer's terminal session using standard AdCP tasks. `adterm npm install` shows the line they bought. Every request and response the seller produces validates against the official AdCP 3.2.3 JSON schemas.

```
$ adterm npm install
 sponsored  Cachely: node_modules is 1.2GB again. Cache it once, restore it in 3s.  Try free -> http://127.0.0.1:8080/c/Cap7pIdYCo5a

up to date in 739ms
```

## Why this exists

Software is getting cheap; any of us could vibe a CRM over a weekend. What can't be generated is trust, reputation and the people who pick up when you call. stdout Network is an ad network, but mostly it's an excuse for people to build something together and look after each other. It starts with about sixty of us from ad tech, then opens to developers and anyone else who fancies a slightly whacky experiment in confederalism.

**Start with the [Charter](CHARTER.md).** It takes four minutes, and signing it is how you join.

The rest is machinery for when money and disagreements arrive: a confederation of small, self-governing communes, co-chairs instead of bosses, recallable delegates, and one member one vote. Employers and advertisers get a voice, never a vote.

| Read | For |
|---|---|
| [CHARTER.md](CHARTER.md) | Why we exist and how we treat each other. Read this one. |
| [SOCIAL_CONTRACT.md](SOCIAL_CONTRACT.md) | The constitution: principles, structure, money, amendments |
| [GOVERNANCE.md](GOVERNANCE.md) | Day to day: which decisions go where, rhythms, votes |
| [COMMUNES.md](COMMUNES.md) | The seven communes and the code each one owns |
| [CONTRIBUTING.md](CONTRIBUTING.md) | DCO sign-off, employer IP, rules for AI-assisted code |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Expectations and the Peace and Consensus Committee |
| [FOUNDING_ASSEMBLY.md](FOUNDING_ASSEMBLY.md) | The first session and its ten ballots |
| [LICENSING.md](LICENSING.md) | Apache-2.0 for now, and why; the licence ballot |

Developers who run `adterm` get 70% of revenue from the ads they see (or can send it to an open source project or charity), and 20% of impressions go free to verified charities. Of any profit, 10% goes to a fighting fund for members who lose their jobs, and the rest is beer money and marketing budget. All of this is proposed until the Founding Assembly ratifies it. Nobody expects to get rich.

## Why a wrapper and not a postinstall script

In 2019 the `standard` package started printing ads after install via a dependency called `funding`. Within a week npm changed its policy to ban packages that display ads at runtime, on installation, or via npm scripts. Publishing this as a package that advertises on install would break npm's terms.

The compliant version is the one Flossbank shipped: a package manager wrapper the developer installs and invokes themselves. Nothing runs unless you typed `adterm`. That is what this is.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# terminal 1: the seller (streamable HTTP at http://127.0.0.1:8080/mcp)
stdout-seller

# terminal 2: be the buyer (capabilities, account, brief, media buy, creatives)
python scripts/demo_buyer.py

# terminal 3: be the audience
adterm npm install
adterm make
adterm pytest
adterm --why

# back in terminal 2: delivery
python scripts/demo_buyer.py --report
```

To plug into a buyer agent that speaks SSE (like the earlier Meta seller setup), run `STDOUT_TRANSPORT=sse stdout-seller` and point it at `http://127.0.0.1:8080/sse`.

## Inventory

All products are non-guaranteed, fixed CPM in GBP, channel `display`, property type `desktop_app`.

| Product | Moment | Trigger | CPM | Format |
|---|---|---|---|---|
| `tty_install_sponsor` | install | `npm/pnpm/yarn/bun install`, `pip install`, `uv add`, `cargo add` | £12 | `terminal_line` |
| `tty_build_wait` | build | `docker build`, `cargo build`, `make`, `npm run build`, `tsc` | £18 | `terminal_box` |
| `tty_tests_green` | tests_green | test command exits 0 (`pytest`, `jest`, `vitest`, `go test`, `npm test`) | £28 | `terminal_line` |
| `tty_ship_it` | ship_it | `git push` or a deploy CLI exits 0 | £24 | `terminal_line` |
| `tty_stack_trace` | failure | any command exits non-zero | £2.50 | `terminal_line` |

Briefs mentioning crypto, gambling or recruitment get the `GetProductsRejected` arm with a reason. Developers already get enough recruiter messages.

## Targeting

Every product supports two kinds of targeting, set per package in `targeting_overlay` and declared in each product's `overlay_support`.

**Country** (`geo_countries`, `geo_countries_exclude`). The seller works out the country when the ad is requested and never stores the IP. Sources, in order:

1. Edge headers (`CF-IPCountry`, `X-Vercel-IP-Country`, `CloudFront-Viewer-Country`), only when `STDOUT_TRUST_GEO_HEADERS=1`, because a client talking to the seller directly could spoof them.
2. Loopback requests (local development) use `STDOUT_DEV_COUNTRY`, default `GB`.
3. A MaxMind GeoLite2 Country database if `STDOUT_GEOIP_DB` points at one and `geoip2` is installed.

Unknown country fails an include and passes an exclude. Developers use a lot of VPNs and cloud dev boxes, so sell countries, never cities.

**Stack signals** (`signal_targeting_groups`), evaluated on the developer's machine:

| Signal | True when the project... |
|---|---|
| `lang_javascript`, `lang_python`, `lang_rust`, `lang_go`, `lang_ruby` | has that ecosystem's manifest |
| `stack_postgres` | depends on `pg`, `psycopg2`, `asyncpg`, `tokio-postgres`, `pgx` and similar |
| `stack_redis`, `stack_stripe`, `stack_react`, `stack_nextjs`, `stack_django`, `stack_fastapi` | depends on them |
| `stack_llm_sdk` | depends on `openai`, `anthropic`, `langchain` and similar |
| `stack_docker` | has a `Dockerfile` or compose file |

A buyer asking for "UK developers whose project uses Postgres" sends:

```json
"targeting_overlay": {
  "geo_countries": ["GB"],
  "signal_targeting_groups": {
    "operator": "all",
    "groups": [{"operator": "any", "signals": [
      {"signal_ref": {"scope": "product", "signal_id": "stack_postgres"}, "value_type": "binary", "value": true}
    ]}]
  }
}
```

Groups with `operator: "any"` must each have one true signal; a group with `operator: "none"` excludes. Unsupported dimensions (regions, metros, devices and so on) are rejected with `UNSUPPORTED_FEATURE`, never silently dropped. A brief that mentions a stack ("Postgres", "Rust", "LLM") gets suggested signals in `brief_relevance`.

### How on-device matching works

1. `adterm` sends the moment and tool name. Nothing else.
2. The seller filters by moment, flight, budget, pause state and country, then returns a slate of up to 12 eligible ads. Each carries its stack rule (`{"any_of_groups": [["stack_postgres"]], "none_of": []}`), plus the dependency names that define each signal used.
3. `adterm` reads the project's manifests (`package.json`, `requirements.txt`, `pyproject.toml`, `Pipfile`, `Cargo.toml`, `go.mod`, `Gemfile`, plus `Dockerfile` and compose files by name) in the current directory and the git root. It drops ads whose rules fail, picks one weighted by the seller's pacing weights, renders it, and beacons only that one.
4. Only the rendered ad bills. The other slate entries are never counted.

`adterm` only ever opens names on its own fixed list, so a seller cannot use a signal definition to probe for `~/.ssh/id_rsa` or anything outside the project. `adterm --signals` shows what it can tell about the current project, computed locally.

**What the seller still learns:** which ad rendered. If that ad was Postgres-targeted, the seller can infer that one anonymous render came from a Postgres project, which is no more than any targeted buy reveals. It never sees the dependency list, file names, repo names or paths.

Delivery supports `reporting_dimensions: {"geo": {"geo_level": "country"}}`, returning `by_geo` per package.

## Creative contract

Both formats are the canonical `native_in_feed` kind, narrowed to text-only slots. The terminal is the feed.

| Format option | Required slots | Limits |
|---|---|---|
| `terminal_line` | `title`, `advertiser_name`, `landing_page_url` (`cta` optional) | title 72, cta 20, advertiser 32 |
| `terminal_box` | `title`, `body_text`, `advertiser_name`, `landing_page_url` (`cta` optional) | title 60, body 140, cta 20 |

Review is automated and synchronous (`creative_approval_mode: auto_approve`). A creative is rejected if any text contains:

- C0/C1 control characters or the CSI introducer, so no ANSI or OSC escape sequences. An advertiser must never be able to write to someone's clipboard (OSC 52), retitle their terminal or move their cursor.
- Unicode bidi overrides and zero-width characters ("Trojan Source").
- Copy telling developers to run things (`curl ... | sh`, `sudo`, `rm -rf`) or asking for passwords.

`adterm` strips the same characters client-side as well.

## AdCP surface

| Tool | Notes |
|---|---|
| `get_adcp_capabilities` | AdCP major 3, idempotency supported (24h replay), media_buy only |
| `sync_accounts`, `list_accounts` | Buyer-declared accounts (brand + operator), operator or agent billing, sandbox supported |
| `get_products` | `brief` (keyword curation, `brief_relevance`) and `wholesale`; filters with `filter_diagnostics`; targeting-aware discovery (`targeting_overlay`, `required_overlay_support`) |
| `list_creative_formats` | Deprecated 3.x compatibility surface |
| `create_media_buy` | Synchronous, atomic validation, inline creatives, idempotent replay and `IDEMPOTENCY_CONFLICT` |
| `update_media_buy` | Pause/resume, extend flight, package budgets and per-dimension targeting changes, revision checks, validates before mutating |
| `get_media_buys` | Lifecycle status: `pending_creatives`, `active`, `paused`, `completed` |
| `sync_creatives`, `list_creatives` | Upsert, assignments, `dry_run` |
| `get_media_buy_delivery` | Rendered impressions, clicks, spend, pacing index, `by_creative`, `by_geo` (country), daily breakdown |

Unknown request fields are ignored rather than rejected, so newer buyers do not break the seller.

## The adterm wrapper

Standard library only. The wrapped command always runs with your exact arguments and exit code, and ads go to stderr so piped stdout stays clean.

- The ad request carries only the moment and the tool name. No IDs, paths, package names or project names. Stack targeting happens on the machine (see Targeting).
- The seller gets 350ms. Slow or down means no ad, never a slower command.
- Billing happens only when `adterm` confirms it rendered the ad (`POST /imp/{id}`).
- Frequency capping is local: one ad per moment per 10 minutes, 6 an hour.
- `adterm --why` shows who bought the last ad, via which AdCP media buy, what was targeted, and what matched on your machine.
- `adterm --signals` shows the manifests read and the stack signals that are true for this project. Nothing it prints is sent anywhere.

Ads are off automatically inside Claude Code and other agents (`CLAUDECODE` is set): an ad in a tool result would be read by the model, which is prompt injection with a CPM. `ADTERM_FORCE` does not override this. They are also off in CI (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `BUILDKITE`), in non-interactive shells, with `--silent`/`--quiet`, and with `NO_ADS=1`, `ADTERM_DISABLE=1` or `OPEN_SOURCE_CONTRIBUTOR=true` (the variable that silenced the original 2019 ads).

`adterm --aliases` prints shell aliases if you want it everywhere. You probably do not.

## Configuration

| Variable | Default | Used by |
|---|---|---|
| `STDOUT_TRANSPORT` | `http` | seller (`sse` for SSE clients) |
| `STDOUT_HOST` / `STDOUT_PORT` | `127.0.0.1` / `8080` | seller |
| `STDOUT_SELLER_URL` | `http://127.0.0.1:8080` | seller (base for click and beacon URLs) |
| `STDOUT_DB` | `./stdout_network.db` | seller |
| `STDOUT_PUBLISHER_DOMAIN` | `stdout.example` | seller |
| `STDOUT_TRUST_GEO_HEADERS` | unset | seller (`1` behind Cloudflare, Vercel or CloudFront) |
| `STDOUT_DEV_COUNTRY` | `GB` | seller (country for loopback requests) |
| `STDOUT_GEOIP_DB` | unset | seller (path to a GeoLite2 Country `.mmdb`) |
| `ADTERM_SELLER_URL` | `http://127.0.0.1:8080` | adterm |
| `ADTERM_TIMEOUT` | `0.35` | adterm |
| `ADTERM_FREQ_MINUTES` / `ADTERM_MAX_PER_HOUR` | `10` / `6` | adterm |
| `ADTERM_FORCE` | unset | adterm (show ads when stderr is not a TTY, for demos) |

## Tests

```bash
pytest
```

`tests/test_conformance.py` runs the full buyer flow in-process and validates every request and response against the AdCP 3.2.3 schemas bundled in the `adcp` SDK. It serves 40 ads, checks spend to the penny, confirms an escape-sequence creative is rejected and paused buys stop serving. It also books a UK + Postgres package, checks a US request never receives it, checks the slate carries the on-device rule, reads `by_geo` back, and clears country targeting on update while keeping the stack signal.

`tests/test_adterm.py` covers moment detection, opt-outs (including Claude Code), sanitising, manifest parsing for npm, pip, pyproject, Cargo and Go, the file allow-list, and on-device slate filtering.

## Demo-grade, on purpose

- No authentication on MCP or the ad routes, and SQLite storage.
- Impressions are client-asserted (the beacon), so a motivated person could inflate them. Signed render receipts would fix this.
- `/.well-known/adagents.json` is served by the seller for convenience. In production it belongs on the publisher's own domain, and `stdout.example` is a reserved placeholder.
- No proposals, audiences or reporting webhooks.
