"""Unit tests for the adterm wrapper: moment detection, opt-outs and sanitising."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("adterm", Path(__file__).parents[1] / "adterm" / "adterm.py")
adterm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adterm)  # type: ignore[union-attr]


def test_install_moments() -> None:
    for cmd in (["npm", "install"], ["pnpm", "add", "zod"], ["pip", "install", "x"], ["uv", "add", "x"], ["cargo", "add", "serde"]):
        assert adterm.classify(cmd)[0] == "install", cmd


def test_build_moments() -> None:
    for cmd in (["docker", "build", "."], ["docker", "compose", "build"], ["cargo", "build"], ["make"], ["npm", "run", "build"]):
        assert adterm.classify(cmd)[0] == "build", cmd


def test_post_run_moments() -> None:
    assert "tests_green" in adterm.classify(["pytest"])[1]
    assert "tests_green" in adterm.classify(["npm", "test"])[1]
    assert "tests_green" in adterm.classify(["python", "-m", "pytest"])[1]
    assert "ship_it" in adterm.classify(["git", "push"])[1]
    assert "ship_it" not in adterm.classify(["git", "status"])[1]
    assert adterm.classify(["ls"]) == (None, {"failure"})


def test_opt_outs(monkeypatch) -> None:
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_CHILD_SESSION", raising=False)
    monkeypatch.setenv("ADTERM_FORCE", "1")
    for var, val in [("CI", "1"), ("NO_ADS", "1"), ("OPEN_SOURCE_CONTRIBUTOR", "true"), ("TERM", "dumb")]:
        monkeypatch.setenv(var, val)
        assert adterm.opted_out(["npm", "install"]), var
        monkeypatch.delenv(var)
    for var in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI", "NO_ADS", "ADTERM_DISABLE", "OPEN_SOURCE_CONTRIBUTOR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert adterm.opted_out(["npm", "install", "--silent"])
    assert adterm.opted_out(["npm", "install", "-s"])
    assert adterm.opted_out(["pytest", "-s"]) is None  # pytest -s means no capture, not silent
    assert adterm.opted_out(["npm", "install"]) is None
    monkeypatch.setenv("CLAUDECODE", "1")  # ADTERM_FORCE must not push ads into an agent's context
    assert "Claude Code" in adterm.opted_out(["npm", "install"])


def test_sanitiser_strips_escape_sequences() -> None:
    nasty = "hello\x1b]52;c;cm0gLXJmIH4=\x07 world\u202e"
    assert adterm._safe(nasty, 200) == "hello]52;c;cm0gLXJmIH4= world"


def test_seller_down_means_no_ad(monkeypatch) -> None:
    monkeypatch.setattr(adterm, "SELLER_URL", "http://127.0.0.1:9")
    assert adterm.fetch_ad("install", "npm") is None


# ---------------------------------------------------------------------------
# on-device signals
# ---------------------------------------------------------------------------

DEFS = {
    "stack_postgres": {"deps": ["pg", "psycopg2", "psycopg2-binary", "asyncpg", "tokio-postgres", "github.com/jackc/pgx/v5"], "files": []},
    "stack_redis": {"deps": ["redis", "ioredis"], "files": []},
    "lang_rust": {"deps": [], "files": ["Cargo.toml"]},
    "stack_docker": {"deps": [], "files": ["Dockerfile"]},
    "sneaky": {"deps": [], "files": ["../../.ssh/id_rsa", "/etc/passwd"]},
}


def _signals_for(tmp_path: Path) -> set[str]:
    deps, files = adterm.parse_manifests([tmp_path])
    return adterm.local_signals(DEFS, deps, files)


def test_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {"pg": "^8"}, "devDependencies": {"ioredis": "5"}}')
    assert _signals_for(tmp_path) == {"stack_postgres", "stack_redis"}


def test_requirements_and_pyproject(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("# db\npsycopg2_binary[extra]>=2.9 ; python_version>'3'\n-r other.txt\n")
    assert _signals_for(tmp_path) == {"stack_postgres"}
    (tmp_path / "requirements.txt").unlink()
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["asyncpg>=0.29", "redis"]\n')
    assert _signals_for(tmp_path) == {"stack_postgres", "stack_redis"}


def test_cargo_go_and_files(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text('[package]\nname="x"\n[dependencies]\ntokio-postgres = "0.7"\n')
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    assert _signals_for(tmp_path) == {"stack_postgres", "lang_rust", "stack_docker"}
    go = tmp_path / "svc"
    go.mkdir()
    (go / "go.mod").write_text("module x\n\nrequire (\n\tgithub.com/jackc/pgx/v5 v5.5.0 // indirect\n)\n")
    assert _signals_for(go) == {"stack_postgres"}


def test_seller_cannot_probe_arbitrary_files(tmp_path: Path) -> None:
    assert "sneaky" not in _signals_for(tmp_path)


def test_rules() -> None:
    assert adterm.passes({"any_of_groups": [["stack_postgres"]], "none_of": []}, {"stack_postgres"})
    assert not adterm.passes({"any_of_groups": [["stack_postgres"]], "none_of": []}, {"lang_rust"})
    assert not adterm.passes({"any_of_groups": [], "none_of": ["lang_rust"]}, {"lang_rust"})
    assert adterm.passes({"any_of_groups": [["a", "b"], ["c"]], "none_of": ["d"]}, {"b", "c"})
    assert adterm.passes(None, set())


def test_choose_filters_on_device(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "19"}}')
    slate = {
        "slate": [
            {"impression_id": "pg", "title": "Postgres ad", "weight": 1000, "rules": {"any_of_groups": [["stack_postgres"]], "none_of": []}},
            {"impression_id": "any", "title": "Anyone ad", "weight": 1, "rules": {"any_of_groups": [], "none_of": []}},
        ],
        "signals": {"stack_postgres": DEFS["stack_postgres"]},
    }
    for _ in range(20):
        ad, _sig = adterm.choose(slate, [tmp_path])
        assert ad["impression_id"] == "any"
    (tmp_path / "package.json").write_text('{"dependencies": {"pg": "8"}}')
    picks = {adterm.choose(slate, [tmp_path])[0]["impression_id"] for _ in range(50)}
    assert "pg" in picks


def test_statusline_bills_once_per_rotation(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(adterm, "STATE_DIR", tmp_path)
    monkeypatch.setattr(adterm, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(adterm, "FREQ_MINUTES", 10)
    monkeypatch.setenv("CLAUDECODE", "1")  # the status line is the one surface allowed inside an agent
    monkeypatch.setenv("NO_COLOR", "1")
    for var in ("NO_ADS", "ADTERM_DISABLE", "OPEN_SOURCE_CONTRIBUTOR"):
        monkeypatch.delenv(var, raising=False)
    ad = {"advertiser": "Cachely", "title": "Cache\x1b[2J it", "cta": "Try", "click_url": adterm.SELLER_URL + "/c/x"}
    fetches, beacons = [], []
    monkeypatch.setattr(adterm, "fetch_slate", lambda m, t: fetches.append(m) or {"slate": [ad]})
    monkeypatch.setattr(adterm, "beacon", beacons.append)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO('{"model": {}}'))

    for _ in range(3):  # the agent redraws constantly
        adterm.cmd_statusline(["echo", "[PONYTAIL]"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "[PONYTAIL]   sponsored  Cachely: Cache[2J it  Try -> " + adterm.SELLER_URL + "/c/x"
    assert len(set(lines)) == 1 and fetches == ["agent_statusline"] and len(beacons) == 1

    monkeypatch.setenv("NO_ADS", "1")
    adterm.cmd_statusline(["echo", "[PONYTAIL]"])
    assert capsys.readouterr().out == "[PONYTAIL]\n"


def test_declared_interests_match_locally(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(adterm, "STATE_DIR", tmp_path)
    monkeypatch.setattr(adterm, "STATE_FILE", tmp_path / "state.json")
    adterm.cmd_interests(["add", "Postgres", "rust"])
    adterm.cmd_interests(["remove", "rust"])
    assert adterm.load_state()["interests"] == ["postgres"]
    defs = {"stack_postgres": {}, "lang_rust": {}}
    assert adterm.declared_signals(defs, ["postgres"]) == {"stack_postgres"}
    pg_only = {"title": "pg", "rules": {"any_of_groups": [["stack_postgres"]]}}
    slate = {"slate": [pg_only], "signals": defs}
    assert adterm.choose(slate, [tmp_path])[0] is None  # empty project, no interest: no match
    assert adterm.choose(slate, [tmp_path], ["postgres"])[0] is pg_only


def test_statusline_targets_the_session_project(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(adterm, "STATE_DIR", tmp_path / "home")
    monkeypatch.setattr(adterm, "STATE_FILE", tmp_path / "home" / "state.json")
    monkeypatch.setenv("NO_COLOR", "1")
    for var in ("NO_ADS", "ADTERM_DISABLE", "OPEN_SOURCE_CONTRIBUTOR"):
        monkeypatch.delenv(var, raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("psycopg2\n")
    secret = tmp_path / "transcript.jsonl"
    secret.write_text("the conversation")
    defs = {"stack_postgres": {"deps": ["psycopg2"], "files": []}}
    pg_only = {"advertiser": "PgCo", "title": "pg", "rules": {"any_of_groups": [["stack_postgres"]]}}
    monkeypatch.setattr(adterm, "fetch_slate", lambda m, t: {"slate": [pg_only], "signals": defs})
    monkeypatch.setattr(adterm, "beacon", lambda ad: None)
    opened = []
    real_read = adterm._read
    monkeypatch.setattr(adterm, "_read", lambda p: opened.append(p) or real_read(p))
    session = {"workspace": {"project_dir": str(proj)}, "transcript_path": str(secret)}
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(__import__("json").dumps(session)))
    adterm.cmd_statusline([])
    assert "PgCo: pg" in capsys.readouterr().out
    assert secret not in opened
