# Communes

Seven starting communes, sized for about 60 founding members (roughly 6 to 10 each). Each owns its paths in the repo through `.github/CODEOWNERS`, and its co-chairs sit on the Confederal Council. Join one by turning up to its meeting, or open an issue tagged with its name.

Co-chair seats are filled at the [Founding Assembly](FOUNDING_ASSEMBLY.md). Terms run 6 months; the first terms are staggered (one co-chair per commune serves 3 months) so a commune never replaces both at once.

| Commune | Owns | Code and paths | First missions |
|---|---|---|---|
| **Seller** | The AdCP seller agent: products, pricing, targeting, conformance with the spec | `seller/`, `tests/test_conformance.py` | Flat-rate and `time` pricing; track AdCP releases; signed render receipts |
| **Terminal** | `adterm`, the developer's side: rendering, opt-outs, on-device signals, privacy guarantees | `adterm/`, `tests/test_adterm.py` | Packaging (pipx, Homebrew); more manifest formats; local wallet |
| **Treasury** | Money in and out: payouts, blind-signed earnings tokens, fraud caps, the books, the legal and fiscal host | `treasury/`, `payouts/` | Pick a fiscal host; build the token wallet and redemption ledger; monthly public summary; sit on the fighting fund panel |
| **Commons** | Ads for good and creative policy: charity verification, the 20% allocation, what we will and won't run | `policy/`, `commons/` | Charity verification process; advertising policy v1; review queue |
| **Agents** | Everything agentic beyond the seller: buyer demos, the Claude Code status line, connectors to other networks | `scripts/`, `statusline/`, `connectors/` | Status line product; buyer-agent examples; an EthicalAds connector spike |
| **Market** | Advertisers and buyers: rate card, prospectus, launch sponsorships, buyer feedback | `market/` | Rate card v1; sell the first 5 moment sponsorships; advertiser onboarding |
| **Voice** | How we sound and look: docs, brand, website, community, press, and the members' app | `README.md`, `docs/`, `brand/`, `assembly/` (the Council keeps `assembly/rules.py`) | Name and identity; docs site; launch post; run the members' app |

The Social Contract, this file and the governance docs belong to the **Confederal Council**.

## Seats

| Commune | Co-chair | Co-chair | Term ends |
|---|---|---|---|
| Seller | | | |
| Terminal | | | |
| Treasury | | | |
| Commons | | | |
| Agents | | | |
| Market | | | |
| Voice | | | |

## Starting a new commune

Any 3 members can propose one with an RFC that states its scope, the paths it would own, and which existing commune gives them up. The Assembly approves new communes. A commune that falls below 3 active members for two months merges into a neighbour or dissolves, and its paths return to the Council until reassigned.
