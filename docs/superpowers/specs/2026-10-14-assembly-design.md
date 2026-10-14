# Assembly: members, communes and votes

- **Date:** 2026-10-14
- **Status:** design approved in chat, awaiting spec review
- **Owner:** Confederal Council (`assembly/` in CODEOWNERS)

## Purpose

A small web app where stdout Network's members sign in, see who belongs to which commune and who holds which seat, and run the votes the [Social Contract](../../../SOCIAL_CONTRACT.md) and [GOVERNANCE.md](../../../GOVERNANCE.md) describe. It replaces the manual parts: `MEMBERS.md` edits, the empty seats table in `COMMUNES.md`, and vote counting in GitHub Discussions.

**Success:** the Founding Assembly's yes/no ballots (1 to 6 and 10) and every later commune, Council and Assembly vote can be run in the app. Each result exports as a `decisions/NNNN-slug.md` record, ready to commit.

## Decisions taken

| Question | Answer |
|---|---|
| Source of truth | The app. Closed votes export decision records to the repo, and `MEMBERS.md` is generated from the app. |
| Login | Email magic link |
| Ballot secrecy | Open by default; whoever opens a vote can mark it secret |
| Stack | Python package `assembly/` in this repo: Starlette, SQLite, server-rendered HTML |
| Permissions | Mirror the governance docs, plus a temporary convenor role |

## Out of scope (v1)

- Ranked-choice ballots. Ballots 7 (the name) and 9 (the Peace and Consensus Committee) at the Founding Assembly are tallied by hand.
- Lazy-consensus and RFC timers. These stay on GitHub issues and PRs.
- Email reminders and notifications (other than login links).
- Treasury, payouts and budgets.
- **Fighting fund requests. These never go in this app.** Section 7 of the Social Contract says nobody outside the panel learns who asked, so they stay as private email to the panel.

## Architecture

New package `assembly/`, written in the same style as `seller/`. The only dependency is Starlette, which `fastmcp` already brings in. No JavaScript build and no template engine.

| File | Responsibility |
|---|---|
| `assembly/rules.py` | Pure functions for eligibility, quorum, thresholds, the tally and the employer check. No database or web imports. |
| `assembly/store.py` | SQLite schema (a single `SCHEMA` string) and queries. The path comes from `ASSEMBLY_DB` (default `./assembly.db`). |
| `assembly/auth.py` | Magic-link tokens, the signed session cookie and sending email |
| `assembly/server.py` | Starlette routes and HTML rendering (f-strings with `html.escape` throughout), plus `main()` |
| `scripts/import_members.py` | One-off: seeds members from `MEMBERS.md` and the 7 communes from `COMMUNES.md` |

Entry point: `stdout-assembly = "assembly.server:main"` in `pyproject.toml`, and add `assembly` to `[tool.setuptools] packages`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ASSEMBLY_DB` | `./assembly.db` | SQLite path |
| `ASSEMBLY_HOST` / `ASSEMBLY_PORT` | `127.0.0.1` / `8090` | Bind address |
| `ASSEMBLY_URL` | `http://127.0.0.1:8090` | Base URL for login links |
| `ASSEMBLY_REPO_URL` | unset | Base URL for Charter and Social Contract links on the landing page |
| `ASSEMBLY_SECRET` | required outside loopback | HMAC key for session cookies. The server refuses to start on a non-loopback host without it. |
| `ASSEMBLY_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM` | unset | Unset means login links are printed to the server console (dev only) |

## Data model

```sql
members(id, name, email UNIQUE, github, employer, brought_in_by -> members,
        signed_at, is_convenor, active)
communes(id, slug UNIQUE, name)
commune_members(commune_id, member_id, joined_at, PRIMARY KEY (commune_id, member_id))
seats(id, commune_id, member_id, term_start, term_end, ended_at, ended_reason)
    -- ended_reason: rotated | recalled | resigned; NULL while sitting
votes(id, body, commune_id NULL, title, text, kind, secret, recall_seat_id NULL,
      opened_by, opened_at, closes_at, closed_at, status)
    -- body: commune | council | assembly
    -- kind: ordinary | recall
    -- status: gathering (assembly co-sign) | open | closed
vote_cosigns(vote_id, member_id, PRIMARY KEY (vote_id, member_id))
electorate(vote_id, member_id, PRIMARY KEY (vote_id, member_id))
ballots(vote_id, member_id NULL, choice, interest_declared, cast_at)
    -- choice: for | against | abstain
voted(vote_id, member_id, PRIMARY KEY (vote_id, member_id))
invites(token_hash PRIMARY KEY, email, invited_by, commune_id NULL, expires_at, used_at)
login_tokens(token_hash PRIMARY KEY, member_id, expires_at, used_at)
```

- **Open votes:** `ballots.member_id` is set, with one row per member, and a member can change their ballot until the vote closes.
- **Secret votes:** `ballots.member_id` is NULL and the `voted` row is what stops a second ballot, so the database holds no link between a member and their choice. A secret ballot cannot be changed once cast, and the vote page says so before submission.
- **Recall:** `recall_seat_id` names the seat. When a recall passes, the seat closes automatically (`ended_reason = 'recalled'`).

## Voting rules (`rules.py`)

The electorate is frozen when a vote moves to `open`:

| Body | Electorate | Quorum (participants / electorate) | Passes when |
|---|---|---|---|
| Commune, ordinary | Active members of that commune | none | for > against |
| Commune, recall | Active members of that commune | none | for > half the electorate |
| Council | Members holding a sitting seat | ⅔ | for > against |
| Assembly | All active members | ⅓ | for ≥ ⅔ × (for + against) |

- **Participants** means everyone who cast a ballot, abstentions included. Abstentions count towards quorum but not towards the threshold.
- **No quorum** means the result is "failed: no quorum", whatever the counts.
- **A tie** (for = against) fails.
- **The interest declaration** is a checkbox on an abstain ballot ("I have a direct commercial interest"). Totals report it separately.
- **The one-third employer check** (`employer_breach(delegates)`): Council vote pages warn when more than ⅓ of sitting delegates share a declared employer. This is a warning only, because the fix is a commune changing its delegate.

`rules.tally(electorate_size, ballots, body, kind) -> Result(counts, quorum_met, passed, reason)` is the single function the server and the decision export both use.

## Permissions

| Action | Who |
|---|---|
| Invite a member | Any member. The inviter is recorded as "brought in by". |
| Join or leave a commune | The member themselves |
| Assign or end a seat | Convenors |
| Open a commune vote (including a recall) | That commune's sitting co-chairs |
| Open a Council vote | Any sitting co-chair |
| Open an Assembly vote | Any sitting co-chair (on behalf of the Council), or any member starting a draft that opens once 10 members have co-signed |
| Close a vote early | Nobody. Votes close at `closes_at`. |
| Everything above | Convenors, until the first Council is seated. Convenor status is a flag that a convenor can clear. |

Votes close lazily. Any request that reads a vote whose `closes_at` has passed closes it and stores the tally. There is no scheduler.

The default voting window is 7 days, per GOVERNANCE.md. Whoever opens the vote can change it, with a minimum of 72 hours.

## Pages

| Route | Page |
|---|---|
| `GET/POST /login` | Email form; always replies "check your email" (no account enumeration) |
| `GET /auth/{token}` | Consumes the token, sets the session, redirects home |
| `GET /invite/{token}` | New member: name, employer (required), GitHub, the Charter link and a sign checkbox |
| `GET /` | Signed out: the public landing page (see below). Signed in: your open votes (not yet voted first) and your communes. |
| `GET /members` | Directory: name, employer, communes, seats, brought in by |
| `GET /communes/{slug}` | Members, co-chairs and term ends, votes, join/leave |
| `GET/POST /votes/new` | Body, commune, title, text, secret?, recall seat, closes_at |
| `GET /votes/{id}` | Text and status. While open: your ballot form and turnout. Once closed: the result, plus who voted what if the vote was open. |
| `POST /votes/{id}/ballot`, `/votes/{id}/cosign` | Cast a ballot or co-sign |
| `GET /votes/{id}/decision.md` | Decision record (closed votes only) filled from `decisions/0000-template.md` |
| `GET /members.md` | A generated `MEMBERS.md` table |
| `POST /logout` | |

All POSTs require a session and a CSRF token tied to the session.

## Public landing page

`GET /` without a session serves `assembly/landing.html`. It is one static file: inline CSS, inline SVG diagrams, no JavaScript and no external requests. It is the only page visible signed out, so it is written for a stranger: a prospective member, a developer or an advertiser. Wherever it gives a split or policy that is still a proposal, it says so ("proposed until the Founding Assembly ratifies it").

Sections, top to bottom:

1. **Hero.** "Ads for the moments developers wait." It shows a terminal mock of `adterm npm install` with the sponsored line, as in the README, followed by a **Members sign in** button and the line "Membership is by invitation; ask a member."
2. **The audience.** Developers, reached in the terminal at five high-intent moments: install, build, tests green, ship it, and failure. A table lists each moment, its trigger and its CPM. Two points carry this section:
   - Browser ad blockers don't reach the terminal, but nothing runs unless the developer typed `adterm`.
   - Targeting is by stack (Postgres, Rust, LLM SDKs…), not by profiling the person.
3. **Privacy by design.** The only things that leave the machine are the moment and the tool name. *Diagram 1, on-device matching:* a sequence from `adterm` to the seller (moment and tool), then a slate of up to 12 ads with their stack rules coming back, the manifests read locally, one ad picked, and the render beacon that is the only thing billed.
4. **Built for agents.** Ads are bought by AI buyer agents over AdCP 3.2, and every request and response is checked against the official schemas. *Diagram 2, architecture:*
   - The buyer agent talks to the seller agent over MCP (`get_products`, `create_media_buy`, `get_media_buy_delivery`).
   - The seller talks to `adterm` over HTTP (`/serve`, `/imp`, `/c`).
   - The seller stores state in SQLite.
   - The diagram also notes that ads are off inside Claude Code, in CI and in non-interactive shells.
5. **Where the money goes.** *Diagram 3, split bar:*
   - 70% to the developer, who can redirect it to an open source project or a charity.
   - 30% runs the network.
   - Of profit, 10% goes to the fighting fund, and the rest is split between beer and marketing.
   - Below the bar: 20% of impressions are free to verified charities.
6. **Who runs it.** A confederation of small self-governing communes: one member, one vote, co-chairs rather than bosses, and recallable delegates. Employers and advertisers get a voice, never a vote. *Diagram 4, governance:* the Assembly at the top, then the Council, with the 7 communes linked to the Council by two-way delegate arrows. This is the GOVERNANCE.md flowchart redrawn in SVG.
7. **Footer.** Links to the Charter and Social Contract (via `ASSEMBLY_REPO_URL`, falling back to plain text names when unset), plus sign in.

**Design rules:**
- Colours are defined once as CSS variables, with a `prefers-color-scheme: dark` variant, and the SVG diagrams use `currentColor` and those variables so they work in both themes.
- Body text uses the system font stack. The terminal mock and code use a monospace stack.
- Single column, readable at 360px. Diagrams scale with `viewBox` and have a text `<title>`/`<desc>` for screen readers.

**Config:** add `ASSEMBLY_REPO_URL` (unset by default) to the configuration table. The server substitutes it into the footer with `str.replace` on a `{{REPO_URL}}` marker. That's the only templating the file needs.

## Security

- Login and invite tokens are 32 random bytes from `secrets`. Only their SHA-256 hash is stored, they are single-use, and they expire after 15 minutes (invites after 7 days).
- Session cookie: `HttpOnly`, `SameSite=Lax`, and `Secure` when `ASSEMBLY_URL` is https. It is signed with HMAC-SHA256 over the member id and an expiry 30 days out.
- `/login` is rate limited in memory: 5 requests per email per hour.
- All user text goes through `html.escape`, and decision exports escape markdown table pipes.
- Member emails are shown only to convenors.

## Testing

`tests/test_assembly.py`:

- **`rules`:**
  - Assembly quorum at exactly ⅓.
  - The ⅔ threshold at the boundary.
  - Abstentions count towards quorum but not the threshold.
  - A tie fails.
  - A recall needs a majority of the electorate, not just of votes cast.
  - Council quorum at ⅔.
  - The employer breach check.
- **Store:**
  - The electorate is frozen when a vote opens, so a member who joins later cannot vote.
  - A secret ballot row has no `member_id`.
  - A second secret ballot is rejected.
  - A recall that passes closes the seat.
- **Landing:**
  - `GET /` signed out returns the landing page (contains "Members sign in" and no member names).
  - `GET /` signed in returns the dashboard.
- **One end-to-end flow** with Starlette's `TestClient`: invite, then login (link captured from the console sender), then join a commune, open a vote, cast ballots, close it, and export a decision record that contains the tally.

## Open questions

The Social Contract gives no quorum for ordinary commune votes, so v1 uses none. A commune can set its own norm later, and this becomes a per-commune setting if one asks for it.
