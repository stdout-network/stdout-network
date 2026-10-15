# stdout Network

An ad network for the developer terminal, run by its members as a co-op.

```
$ adterm npm install
 sponsored  Cachely: node_modules is 1.2GB again. Cache it once, restore it in 3s.  Try free -> http://127.0.0.1:8080/c/Cap7pIdYCo5a

up to date in 739ms
```

**Site:** https://stdout-network.github.io/stdout-network/

This is an early idea, kept deliberately basic. Play with it, pull it apart, comment, contribute, or ignore it. Nothing here is decided.

## The idea

- Developers opt in by typing `adterm` in front of a command. They'd keep 70% of what their screen earns, or send it to an open source project or charity.
- Targeting happens on the developer's machine. The ad request carries only the moment (install, build, tests green) and the tool name. No IDs, paths or package names.
- Developers can say what they'd like ads about (`adterm --interests add postgres`). That stays on their machine too. In the status line, adterm reads the project folder from Claude Code and nothing else, never the transcript.
- Advertisers' AI agents buy it over [AdCP 3.2](https://adcontextprotocol.org), like any other seller agent.
- Ads never go into an AI agent's chat. In Claude Code an ad in a tool result would be prompt injection with a CPM, so `adterm` stays silent there. The agent's status line, which only the human sees, is its own product (`tty_agent_statusline`) that buyers can target. Ads are off in CI and non-interactive shells.

Yes, it's been tried. In 2019 `standard` put ads in npm installs and npm banned the practice within a week. Flossbank tried a wrapper instead. This is a wrapper too, so nothing runs unless you typed `adterm`.

Mostly, though, it's an excuse to build something together. Rough thoughts on how a members-run version could work are in [ideas/](ideas/), starting with the [Charter](ideas/CHARTER.md).

## Try it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

stdout-seller                         # terminal 1: the seller agent
python scripts/demo_buyer.py          # terminal 2: buy a test campaign
adterm pytest                         # terminal 3: see an ad (in a real terminal, not -q)
adterm --why                          # who bought it and why it matched
python scripts/demo_buyer.py --report # delivery: impressions, clicks, spend
```

For Claude Code's status bar, point `statusLine` in `~/.claude/settings.json` at `adterm --statusline`. Anything after it runs first, so an existing status line keeps its place:

```json
{"statusLine": {"type": "command", "command": "adterm --statusline bash ~/.claude/my-statusline.sh"}}
```

Each moment shows at most one ad every 10 minutes. To see more while testing, run `export ADTERM_FREQ_MINUTES=0`. `NO_ADS=1` turns it off.

## What's here

| Path | What |
|---|---|
| `seller/` | The AdCP seller agent (MCP), plus `/serve`, `/imp` and `/c` for adterm |
| `adterm/` | The wrapper. Standard library only |
| `scripts/demo_buyer.py` | A buyer agent that runs a full test campaign |
| `docs/` | The site |
| `ideas/` | Draft thoughts on running it as a co-op |

Apache-2.0.
