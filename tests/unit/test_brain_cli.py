"""CLI Claude Code vue par la préparation (presentation-edition-v1 Slice 07, HV-PACKAGE-02 : jamais redistribuée).

Aucun test ne lance la vraie CLI : la recherche et les sondes reçoivent des fonctions injectées.
"""

from __future__ import annotations

import subprocess

from jarvis.runtime import brain_cli
from jarvis.runtime import cli_catalog


def done(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_locate_prefers_the_configured_command_then_path_then_official_locations_in_the_product(tmp_path):
    native = tmp_path / "profile" / ".local" / "bin" / "claude.exe"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"")
    env = {"USERPROFILE": str(tmp_path / "profile"), "APPDATA": str(tmp_path / "roaming"),
           "LOCALAPPDATA": str(tmp_path / "local")}
    nowhere = lambda name: None  # noqa: E731
    assert brain_cli.locate(environ=env, installed=True, which=nowhere) == str(native)
    # Développement : jamais d'emplacement deviné hors du PATH.
    assert brain_cli.locate(environ=env, installed=False, which=nowhere) is None
    assert brain_cli.locate(environ=env, installed=True, which=lambda name: f"X:/bin/{name}.exe") == "X:/bin/claude.exe"
    configured = {**env, "JARVIS_CLAUDE_CLI": "myclaude"}
    assert brain_cli.locate(environ=configured, installed=True, which=lambda name: f"/p/{name}") == "/p/myclaude"


def test_known_locations_follow_the_official_installers():
    rows = brain_cli.known_locations({"USERPROFILE": "U", "APPDATA": "A", "LOCALAPPDATA": "L"})
    assert [p.as_posix() for p in rows] == ["U/.local/bin/claude.exe", "A/npm/claude.cmd",
                                            "L/Microsoft/WinGet/Links/claude.exe"]


def test_auth_status_keeps_only_the_login_state_and_method():
    text = '{"loggedIn": true, "authMethod": "claude.ai", "email": "someone@example.com", "orgId": "x"}'
    assert brain_cli.parse_auth_status(text) == (True, "claude.ai")
    assert brain_cli.parse_auth_status("not json") == (None, None)
    assert brain_cli.parse_auth_status('{"loggedIn": "yes"}') == (None, None)


def test_probe_reads_version_and_login_and_never_returns_an_account_identifier():
    calls = []

    def run(argv, timeout):
        calls.append(argv[1:])
        if argv[1] == "--version":
            return done("2.1.310 (Claude Code)\n")
        return done('{"loggedIn": true, "authMethod": "claude.ai", "email": "someone@example.com"}')

    facts = brain_cli.probe("claude", run=run)
    assert facts.found and facts.logged_in and facts.version == "2.1.310" and facts.auth_method == "claude.ai"
    assert "someone" not in repr(facts)
    assert calls == [["--version"], ["auth", "status", "--json"]]


def test_probe_failures_are_typed_and_never_guessed():
    assert brain_cli.probe(None).error.startswith("claude_cli_not_found")

    def timeout(argv, t):
        if argv[1] == "--version":
            return done("2.1.0")
        raise subprocess.TimeoutExpired(argv, t)

    slow = brain_cli.probe("claude", run=timeout)
    assert slow.found and slow.logged_in is None and slow.error.startswith("claude_auth_status_timeout")

    def garbage(argv, t):
        return done("2.1.0") if argv[1] == "--version" else done("", 1, "Error: something")

    bad = brain_cli.probe("claude", run=garbage)
    assert bad.logged_in is None and "Error: something" in bad.error

    def missing(argv, t):
        raise FileNotFoundError(2, "not found")

    gone = brain_cli.probe("claude", run=missing)
    assert not gone.found and gone.error.startswith("claude_cli_unrunnable")


def test_sign_in_opens_the_official_login_in_its_own_window():
    seen = {}

    class Proc:
        def poll(self):
            return None

    def spawn(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return Proc()

    sign_in = brain_cli.start_sign_in("C:/x/claude.exe", spawn=spawn, clock=lambda: 7.0)
    assert seen["argv"] == ["C:/x/claude.exe", "auth", "login"] and sign_in.running() and sign_in.started_at == 7.0


def test_resolve_command_reads_official_locations_only_in_the_installed_product(monkeypatch, tmp_path):
    native = tmp_path / ".local" / "bin" / "claude.exe"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cli_catalog.shutil, "which", lambda name: None)
    monkeypatch.setattr(brain_cli.shutil, "which", lambda name: None)
    from jarvis import private_runtime

    monkeypatch.setattr(private_runtime, "package_layout", lambda: None)
    assert cli_catalog.resolve_command("claude") == "claude"  # développement : inchangé
    monkeypatch.setattr(private_runtime, "package_layout", lambda: private_runtime.PackageLayout(tmp_path))
    assert cli_catalog.resolve_command("claude") == str(native)
    assert cli_catalog.resolve_command("codex") == "codex"
