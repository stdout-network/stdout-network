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
