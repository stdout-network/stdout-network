#!/usr/bin/env python3
"""adterm - an opt-in terminal ad wrapper for stdout Network.

    adterm npm install          one sponsored line while dependencies install
    adterm docker build .       a boxed message at the start of a long build
    adterm pytest               a line after the suite passes
    adterm git push             a line after a successful push
    adterm --why                why you saw the last ad, and who bought it
    adterm --signals            what adterm can tell about this project (computed here, never sent)
    adterm --status             config, opt-out state and frequency cap
    adterm --aliases            print shell aliases if you really want this everywhere
    adterm --interests add rust say what you'd like ads about (kept on this machine, never sent)
    adterm --statusline [cmd]   one line for Claude Code's status bar (seen by you, never the model)

Why a wrapper and not a postinstall script: npm has banned packages that show
ads at install time since 2019. A wrapper you install and invoke yourself is
the honest version (the Flossbank model): nothing runs unless you typed it.

Ground rules, enforced here:
  * The wrapped command always runs, with your exact arguments and exit code.
  * The ad request carries only the moment and the tool name. No IDs, no paths,
    no package names. The seller may derive your country from the connection
    and does not store the IP.
  * Targeting on your stack happens here. The seller sends a slate of eligible
    ads with rules ("show if the project uses Postgres"); adterm reads your
    manifests locally, picks one, and reports back only which ad it rendered.
    Your dependency list never leaves the machine.
  * The seller gets 350ms. If it is slow or down you just get your command.
  * Silent in CI, in non-interactive shells, with --silent/--quiet, with
    NO_ADS=1, ADTERM_DISABLE=1, or OPEN_SOURCE_CONTRIBUTOR=true (a nod to the
    env var that silenced the original 2019 terminal ads).
  * Silent inside Claude Code and other agents (CLAUDECODE=1): an ad in a
    tool result would be read by the model, which is prompt injection with a
    CPM. ADTERM_FORCE does not override this. The one exception is
    --statusline, which the agent's UI draws for the human, outside the chat.
  * Frequency capped locally: one ad per moment per 10 minutes, 6 an hour.

Standard library only. Python 3.9+.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

SELLER_URL = os.environ.get("ADTERM_SELLER_URL", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = float(os.environ.get("ADTERM_TIMEOUT", "0.35"))
FREQ_MINUTES = float(os.environ.get("ADTERM_FREQ_MINUTES", "10"))
MAX_PER_HOUR = int(os.environ.get("ADTERM_MAX_PER_HOUR", "6"))
STATE_DIR = Path(os.environ.get("ADTERM_HOME", Path.home() / ".adterm"))
STATE_FILE = STATE_DIR / "state.json"

INSTALL_PM = {"npm", "pnpm", "yarn", "bun"}
INSTALL_VERBS = {"install", "i", "add", "ci"}
BUILD_TOOLS = {"make", "tsc", "vite", "webpack", "next", "gradle", "mvn"}
TEST_TOOLS = {"pytest", "jest", "vitest", "mocha", "rspec", "phpunit", "tox", "nox"}
DEPLOY_TOOLS = {"vercel", "netlify", "wrangler", "flyctl", "fly", "terraform", "kubectl", "helm", "pulumi"}

# Defence in depth: the seller rejects these at creative review, the client strips them anyway.
_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")


# ---------------------------------------------------------------------------
# moment detection
# ---------------------------------------------------------------------------


def classify(argv: list[str]) -> tuple[str | None, set[str]]:
    """Return (pre_run_moment, post_run_moments) for a command line."""
    if not argv:
        return None, set()
    tool = os.path.basename(argv[0])
    rest = argv[1:]
    first = rest[0] if rest else ""
    post: set[str] = {"failure"}

    if tool in INSTALL_PM and first in INSTALL_VERBS:
        return "install", post
    if tool in {"pip", "pip3"} and first == "install":
        return "install", post
    if tool == "uv" and (first == "add" or rest[:2] == ["pip", "install"] or first == "sync"):
        return "install", post
    if tool in {"poetry", "cargo", "bundle"} and first in {"add", "install"}:
        return "install", post

    if tool in INSTALL_PM and (first == "test" or rest[:2] == ["run", "test"]):
        return None, post | {"tests_green"}
    if tool in TEST_TOOLS or (tool in {"go", "cargo"} and first == "test"):
        return None, post | {"tests_green"}
    if tool in {"python", "python3"} and rest[:2] == ["-m", "pytest"]:
        return None, post | {"tests_green"}

    if tool == "docker" and ("build" in rest[:2] or rest[:2] == ["compose", "build"]):
        return "build", post
    if tool in BUILD_TOOLS or (tool in {"cargo", "go"} and first == "build"):
        return "build", post
    if tool in INSTALL_PM and (first == "build" or rest[:2] == ["run", "build"]):
        return "build", post

    if tool == "git" and first == "push":
        return None, post | {"ship_it"}
    if tool in DEPLOY_TOOLS:
        return None, post | {"ship_it"}

    return None, post


# ---------------------------------------------------------------------------
# opt-outs and frequency cap
# ---------------------------------------------------------------------------


def opted_out(argv: list[str]) -> str | None:
    env = os.environ
    if env.get("ADTERM_DISABLE") or env.get("NO_ADS"):
        return "ADTERM_DISABLE / NO_ADS is set"
    if env.get("OPEN_SOURCE_CONTRIBUTOR", "").lower() == "true":
        return "OPEN_SOURCE_CONTRIBUTOR=true"
    if env.get("CI") or env.get("GITHUB_ACTIONS") or env.get("BUILDKITE") or env.get("GITLAB_CI"):
        return "running in CI"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_CHILD_SESSION"):
        return "running inside Claude Code (an ad here would reach the model, not you)"
    if env.get("TERM") == "dumb":
        return "TERM=dumb"
    quiet_flags = {"--silent", "--quiet", "-q", "--loglevel=silent"}
    if os.path.basename(argv[0]) in INSTALL_PM:
        quiet_flags.add("-s")  # npm -s is --silent; pytest -s is not
    if any(a in quiet_flags for a in argv[1:]):
        return "command asked to be quiet"
    if not env.get("ADTERM_FORCE") and not sys.stderr.isatty():
        return "stderr is not a terminal"
    return None


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def capped(state: dict, moment: str) -> bool:
    now = time.time()
    shown = [t for t in state.get("shown", []) if now - t < 3600]
    state["shown"] = shown
    if len(shown) >= MAX_PER_HOUR:
        return True
    last = state.get("last_by_moment", {}).get(moment, 0)
    return now - last < FREQ_MINUTES * 60


# ---------------------------------------------------------------------------
# on-device stack signals
# ---------------------------------------------------------------------------
# adterm only ever looks at these file names, in the project root and the current
# directory. Anything else the seller names is ignored, so a seller cannot probe
# for ~/.ssh/id_rsa or anything outside the project.

KNOWN_FILES = (
    "package.json", "requirements.txt", "pyproject.toml", "Pipfile", "setup.py",
    "Cargo.toml", "go.mod", "Gemfile", "Dockerfile", "docker-compose.yml", "compose.yaml",
)
MAX_MANIFEST_BYTES = 512 * 1024

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover
    _toml = None


def _norm(name: str) -> str:
    return re.sub(r"[._]+", "-", name.strip().lower())


def project_dirs(start: Path | None = None) -> list[Path]:
    """The current directory plus the nearest project root above it (git root or manifest)."""
    cwd = (start or Path.cwd()).resolve()
    dirs = [cwd]
    home = Path.home().resolve()
    probe = cwd
    for _ in range(6):
        if probe == home or probe.parent == probe:
            break
        if (probe / ".git").exists():
            if probe != cwd:
                dirs.append(probe)
            break
        probe = probe.parent
    return dirs


def _read(path: Path) -> str | None:
    try:
        if path.is_file() and path.stat().st_size <= MAX_MANIFEST_BYTES:
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return None


def _pep508_name(spec: str) -> str | None:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return _norm(m.group(1)) if m else None


def _toml_load(text: str) -> dict:
    if _toml is None:
        return {}
    try:
        return _toml.loads(text)
    except Exception:
        return {}


def parse_manifests(dirs: list[Path]) -> tuple[set[str], set[str]]:
    """Return (dependency names, present known files). Names only, never versions or paths."""
    deps: set[str] = set()
    files: set[str] = set()
    for d in dirs:
        for fname in KNOWN_FILES:
            text = _read(d / fname)
            if text is None:
                continue
            files.add(fname)
            if fname == "package.json":
                try:
                    pkg = json.loads(text)
                except ValueError:
                    continue
                for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                    if isinstance(pkg.get(key), dict):
                        deps.update(k.lower() for k in pkg[key])
            elif fname == "requirements.txt":
                for line in text.splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line and not line.startswith("-"):
                        n = _pep508_name(line)
                        if n:
                            deps.add(n)
            elif fname == "pyproject.toml":
                data = _toml_load(text)
                proj = data.get("project", {})
                specs = list(proj.get("dependencies", []))
                for group in proj.get("optional-dependencies", {}).values():
                    specs += group
                for group in data.get("dependency-groups", {}).values():
                    specs += [g for g in group if isinstance(g, str)]
                deps.update(n for n in (_pep508_name(x) for x in specs) if n)
                poetry = data.get("tool", {}).get("poetry", {})
                deps.update(_norm(k) for k in poetry.get("dependencies", {}) if k.lower() != "python")
                for group in poetry.get("group", {}).values():
                    deps.update(_norm(k) for k in group.get("dependencies", {}))
            elif fname == "Pipfile":
                data = _toml_load(text)
                for key in ("packages", "dev-packages"):
                    deps.update(_norm(k) for k in data.get(key, {}))
            elif fname == "Cargo.toml":
                data = _toml_load(text)
                for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                    deps.update(k.lower() for k in data.get(key, {}))
                deps.update(k.lower() for k in data.get("workspace", {}).get("dependencies", {}))
            elif fname == "go.mod":
                block = False
                for line in text.splitlines():
                    line = line.split("//", 1)[0].strip()
                    if line.startswith("require ("):
                        block = True
                    elif block and line == ")":
                        block = False
                    elif block and line:
                        deps.add(line.split()[0].lower())
                    elif line.startswith("require "):
                        parts = line.split()
                        if len(parts) >= 2:
                            deps.add(parts[1].lower())
            elif fname == "Gemfile":
                deps.update(m.lower() for m in re.findall(r"""^\s*gem\s+['"]([^'"]+)['"]""", text, re.M))
    return deps, files


def local_signals(definitions: dict, deps: set[str], files: set[str]) -> set[str]:
    """Which seller-defined signals are true for this project, decided entirely on this machine."""
    norm_deps = deps | {_norm(d) for d in deps}
    true: set[str] = set()
    for sid, spec in (definitions or {}).items():
        wanted_files = {f for f in spec.get("files", []) if f in KNOWN_FILES}
        wanted_deps = {d.lower() for d in spec.get("deps", [])} | {_norm(d) for d in spec.get("deps", [])}
        if (wanted_files & files) or (wanted_deps & norm_deps):
            true.add(sid)
    return true


def declared_signals(definitions: dict, interests: list[str]) -> set[str]:
    """Signals the developer switched on with `adterm --interests add`. "postgres" matches stack_postgres."""
    words = {i.lower() for i in interests}
    return {sid for sid in (definitions or {}) if sid in words or sid.split("_", 1)[-1] in words}


def passes(rules: dict | None, signals: set[str]) -> bool:
    if not rules:
        return True
    for group in rules.get("any_of_groups", []):
        if not signals.intersection(group):
            return False
    return not signals.intersection(rules.get("none_of", []))


# ---------------------------------------------------------------------------
# seller calls
# ---------------------------------------------------------------------------


def _post_json(path: str, payload: dict) -> dict | None:
    req = urllib.request.Request(
        f"{SELLER_URL}{path}", data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read(256 * 1024))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def fetch_slate(moment: str, tool: str) -> dict | None:
    data = _post_json("/serve", {"moment": moment, "tool": tool})
    if not data or not isinstance(data.get("slate"), list):
        return None
    return data


def choose(
    slate_resp: dict, dirs: list[Path] | None = None, interests: list[str] | None = None
) -> tuple[dict | None, set[str]]:
    """Filter the slate on-device and pick one ad, weighted by the seller's pacing weights."""
    candidates = [c for c in slate_resp.get("slate", []) if isinstance(c, dict) and c.get("title")]
    needs_signals = any((c.get("rules") or {}).get("any_of_groups") or (c.get("rules") or {}).get("none_of") for c in candidates)
    signals: set[str] = set()
    if needs_signals:
        deps, files = parse_manifests(dirs or project_dirs())
        signals = local_signals(slate_resp.get("signals", {}), deps, files)
        signals |= declared_signals(slate_resp.get("signals", {}), interests or [])
    eligible = [c for c in candidates if passes(c.get("rules"), signals)]
    if not eligible:
        return None, signals
    total = sum(max(float(c.get("weight", 1)), 0.0001) for c in eligible)
    r = random.uniform(0, total)
    for c in eligible:
        r -= max(float(c.get("weight", 1)), 0.0001)
        if r <= 0:
            return c, signals
    return eligible[-1], signals


def fetch_ad(moment: str, tool: str) -> dict | None:
    """Backwards-compatible helper: fetch a slate and pick an ad for the current directory."""
    data = fetch_slate(moment, tool)
    if not data:
        return None
    ad, _ = choose(data)
    return ad


def beacon(ad: dict) -> None:
    url = ad.get("beacon_url")
    if not url or not url.startswith(SELLER_URL):
        return
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=TIMEOUT).close()
    except (urllib.error.URLError, OSError):
        pass


# ---------------------------------------------------------------------------
# rendering (stderr only, so piped stdout stays clean)
# ---------------------------------------------------------------------------


def _safe(text: str | None, limit: int) -> str:
    return _UNSAFE.sub("", text or "")[:limit]


def _style(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR"):
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def render(ad: dict) -> None:
    advertiser = _safe(ad.get("advertiser"), 32)
    title = _safe(ad.get("title"), 72)
    body = _safe(ad.get("body"), 140)
    cta = _safe(ad.get("cta"), 20)
    link = ad.get("click_url", "")
    if not link.startswith(SELLER_URL):
        link = ""
    width = min(shutil.get_terminal_size((80, 20)).columns, 72)
    out = sys.stderr

    if ad.get("format") == "terminal_box" and body:
        inner = width - 4
        label = f" sponsored · {advertiser} "
        top = "┌─" + label + "─" * max(0, inner + 1 - len(label)) + "┐"
        lines = textwrap.wrap(title, inner) + [""] + textwrap.wrap(body, inner)
        if cta or link:
            lines += [""] + textwrap.wrap(f"{cta} -> {link}".strip(" ->"), inner)
        print(_style("2", top), file=out)
        for ln in lines:
            print(_style("2", "│ ") + ln.ljust(inner) + _style("2", " │"), file=out)
        print(_style("2", "└" + "─" * (width - 2) + "┘"), file=out)
    else:
        tag = _style("2;7", " sponsored ")
        who = _style("1", advertiser)
        tail = f"  {_style('36', cta + ' ->')} {_style('4', link)}" if link else ""
        print(f"{tag} {who}: {title}{tail}", file=out)
    out.flush()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def maybe_show(moment: str, tool: str, state: dict) -> bool:
    if capped(state, moment):
        return False
    data = fetch_slate(moment, tool)
    if not data:
        return False
    ad, signals = choose(data, interests=state.get("interests"))
    if not ad:
        return False
    render(ad)
    beacon(ad)
    rules = ad.get("rules") or {}
    used = {sid for g in rules.get("any_of_groups", []) for sid in g} & signals
    now = time.time()
    state.setdefault("shown", []).append(now)
    state.setdefault("last_by_moment", {})[moment] = now
    state["last_ad"] = {
        "moment": moment,
        "advertiser": ad.get("advertiser"),
        "title": ad.get("title"),
        "landing_url": ad.get("landing_url"),
        "why": {
            **ad.get("why", {}),
            "country_seen_by_seller": data.get("country") or "unknown",
            "matched_on_device": ", ".join(sorted(used)) or "nothing (untargeted ad)",
            "sent_to_seller": "moment and tool name only",
        },
        "shown_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)
    return True


def cmd_why() -> int:
    last = load_state().get("last_ad")
    if not last:
        print("No ads shown yet. Enjoy it while it lasts.")
        return 0
    why = last.get("why", {})
    print(f"Last ad: {last.get('advertiser')}: {last.get('title')}")
    print(f"  shown at                {last.get('shown_at')} during the '{last.get('moment')}' moment")
    print(f"  landing page            {last.get('landing_url')}")
    for k, v in why.items():
        print(f"  {k.replace('_', ' '):<24}{v}")
    print("Opt out any time: export NO_ADS=1")
    return 0


def cmd_signals() -> int:
    dirs = project_dirs()
    deps, files = parse_manifests(dirs)
    definitions = {}
    try:
        with urllib.request.urlopen(f"{SELLER_URL}/signals.json", timeout=max(TIMEOUT, 1.0)) as resp:
            definitions = json.loads(resp.read(256 * 1024)).get("signals", {})
    except (urllib.error.URLError, OSError, ValueError):
        print("(seller unreachable, showing manifests only)")
    print(f"project dirs     {', '.join(str(d) for d in dirs)}")
    print(f"manifests read   {', '.join(sorted(files)) or 'none'}")
    print(f"dependencies     {len(deps)} names found")
    if definitions:
        true = local_signals(definitions, deps, files) | declared_signals(definitions, load_state().get("interests", []))
        print(f"signals true     {', '.join(sorted(true)) or 'none'}")
    print("None of this is sent anywhere. The seller only learns which ad you were shown.")
    return 0


def cmd_status() -> int:
    reason = opted_out(["adterm"])
    state = load_state()
    recent = [t for t in state.get("shown", []) if time.time() - t < 3600]
    print(f"seller           {SELLER_URL}")
    print(f"ads              {'off (' + reason + ')' if reason else 'on'}")
    print(f"frequency cap    1 per moment per {FREQ_MINUTES:g} min, {MAX_PER_HOUR}/hour ({len(recent)} shown this hour)")
    print(f"state file       {STATE_FILE}")
    return 0


def cmd_aliases() -> int:
    print("# Add to your shell rc if you genuinely want this. Remove to undo.")
    for name in ["npm", "pnpm", "yarn", "pip", "pytest", "cargo", "docker", "make"]:
        print(f"alias {name}='adterm {name}'")
    print("adterm_git() { if [ \"$1\" = push ]; then adterm git \"$@\"; else command git \"$@\"; fi; }")
    print("alias git=adterm_git")
    return 0


def cmd_interests(argv: list[str]) -> int:
    """adterm --interests [add|remove WORD...]: things you'd like ads about. Stored here, never sent."""
    state = load_state()
    interests = set(state.get("interests", []))
    if argv and argv[0] in {"add", "remove"}:
        words = {_safe(w, 40).lower() for w in argv[1:] if w.strip()}
        interests = interests | words if argv[0] == "add" else interests - words
        state["interests"] = sorted(interests)
        save_state(state)
    elif argv:
        print("usage: adterm --interests [add|remove WORD...]", file=sys.stderr)
        return 2
    print(f"interests        {', '.join(sorted(interests)) or 'none'}")
    print("Matched against ads on this machine. The seller only learns which ad you were shown.")
    return 0


def statusline_text(ad: dict) -> str:
    """One line for an agent's status bar. Sanitised like every other render."""
    advertiser = _safe(ad.get("advertiser"), 32)
    title = _safe(ad.get("title"), 72)
    cta = _safe(ad.get("cta"), 20)
    link = ad.get("click_url", "")
    tail = f"  {cta} -> {link}" if link.startswith(SELLER_URL) else ""
    return f"{_style('2;7', ' sponsored ')} {_style('1', advertiser)}: {title}{_style('2', tail)}"


def cmd_statusline(argv: list[str]) -> int:
    """For an agent's statusLine setting, e.g. Claude Code:

        {"statusLine": {"type": "command", "command": "adterm --statusline [your existing statusline command]"}}

    The agent's UI draws this for the human; it never reaches the model's context,
    which is why this is the one place adterm runs inside an agent. The agent
    re-runs it constantly, so one ad holds for FREQ_MINUTES and bills once per
    rotation, not per redraw. Any command after --statusline runs first (same
    stdin), so it can share the bar with another status line.
    """
    stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    # Claude Code sends session JSON. adterm reads the project directory from it and
    # nothing else: never transcript_path, never the conversation. Cost and model stay unread too.
    try:
        ws = json.loads(stdin).get("workspace") or {}
        project = Path(ws.get("project_dir") or ws.get("current_dir"))
    except (ValueError, TypeError, AttributeError):
        project = None
    parts = []
    if argv:
        try:
            out = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        if out:
            parts.append(out)

    env = os.environ
    off = env.get("ADTERM_DISABLE") or env.get("NO_ADS") or env.get("OPEN_SOURCE_CONTRIBUTOR", "").lower() == "true"
    if not off:
        state = load_state()
        slot = state.get("statusline") or {}
        now = time.time()
        if now - slot.get("at", 0) >= FREQ_MINUTES * 60:
            # ponytail: fetches inline on rotation (up to 2x TIMEOUT once per FREQ_MINUTES); background fetch if that stalls the bar
            data = fetch_slate("agent_statusline", "statusline")
            ad = choose(data, project_dirs(project), state.get("interests"))[0] if data else None
            slot = {"at": now, "ad": ad}  # an empty slot also waits a full rotation, so a down seller isn't retried every redraw
            if ad:
                beacon(ad)
                state["last_ad"] = {
                    "moment": "agent_statusline",
                    "advertiser": ad.get("advertiser"),
                    "title": ad.get("title"),
                    "landing_url": ad.get("landing_url"),
                    "why": {**ad.get("why", {}), "sent_to_seller": "moment and tool name only"},
                    "shown_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            state["statusline"] = slot
            save_state(state)
        if slot.get("ad"):
            parts.append(statusline_text(slot["ad"]))

    if parts:
        print("  ".join(parts))
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__.strip().split("\n\n")[0] + "\n\n" + __doc__.strip().split("\n\n")[1])
        return 0 if argv else 2
    if argv[0] == "--why":
        return cmd_why()
    if argv[0] == "--status":
        return cmd_status()
    if argv[0] == "--signals":
        return cmd_signals()
    if argv[0] == "--aliases":
        return cmd_aliases()
    if argv[0] == "--interests":
        return cmd_interests(argv[1:])
    if argv[0] == "--statusline":
        return cmd_statusline(argv[1:])

    tool = os.path.basename(argv[0])
    pre, post = classify(argv)
    quiet = opted_out(argv)
    state = load_state() if not quiet else {}
    shown = False

    if pre and not quiet:
        shown = maybe_show(pre, tool, state)

    try:
        code = subprocess.call(argv)
    except FileNotFoundError:
        print(f"adterm: command not found: {argv[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130

    if not quiet and not shown and code != 130:
        if code == 0:
            moment = next((m for m in ("tests_green", "ship_it") if m in post), None)
        else:
            moment = "failure"
        if moment:
            maybe_show(moment, tool, state)
    return code


def _entry() -> None:
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    _entry()
