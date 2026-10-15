# Contributing

Welcome. If you haven't yet, read the [Charter](CHARTER.md) first; it matters more than anything below.

This project started with ad tech people who like shipping things, mostly with AI coding tools, and it's open to anyone who does. That is encouraged. The rules below exist so the code stays trustworthy when a lot of it was written quickly.

## Before your first PR

1. **Check your employment contract.** Many ad tech employers own what you build, sometimes even on weekends. If yours does, get written permission to contribute before you open a PR. When in doubt, ask your employer.
2. **Find your commune.** Every path in the repo is owned by a commune (see [COMMUNES.md](COMMUNES.md)). Small fixes can go straight to a PR; anything bigger, say hello in the commune's channel or open an issue first.
3. **Read the privacy principle.** No persistent identifiers in ad traffic, and targeting happens on the developer's machine. PRs that weaken this will be closed, however clever.

## Sign your commits (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/) instead of a CLA. Add a sign-off to every commit:

```bash
git commit -s -m "Add flat_rate pricing to tty_tests_green"
```

That line certifies you have the right to submit the work under the project's licence. Commits without it will fail the check.

## Vibecoding rules

AI-assisted code is welcome. You still own it.

- **You understand what you submit.** If a reviewer asks why a line exists, "the model wrote it" is not an answer.
- **Say how it was made.** The PR template asks whether the change was mostly human-written, AI-assisted or mostly AI-generated. No judgement either way; it tells reviewers where to look harder.
- **Tests are not optional.** New behaviour comes with tests. The suite must pass: `pytest`.
- **The spec is the referee.** Anything that touches AdCP requests or responses must keep `tests/test_conformance.py` green. It validates against the official AdCP schemas, which beats anyone's memory of the spec, human or model.
- **No secrets, no real user data** in code, tests, fixtures or prompts you paste into a tool.
- **Never add network calls from `adterm`** beyond the seller endpoints, and never send anything identifying. The Terminal commune reviews every change to `adterm/` with this in mind.

## How changes land

| Change | Route |
|---|---|
| Inside one commune's paths | PR, one approving review from that commune |
| Touches another commune | PR tagged with both, 72 hours of lazy consensus |
| New product, protocol change, policy, or anything cross-cutting | RFC first (`rfcs/0000-template.md`), then PRs |
| Splits, licence, legal home, Social Contract | Assembly vote |

See [GOVERNANCE.md](GOVERNANCE.md) for the full decision ladder.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # schema conformance and adterm tests
stdout-seller                # run the seller on :8080
python scripts/demo_buyer.py # act as a buyer agent
```

## Style

- Python 3.10+ for the seller; `adterm` stays standard library only, Python 3.9+.
- Keep `adterm` a single file a developer can read in one sitting. That readability is a privacy feature.
- Small PRs merge faster than big ones.
