"""Masquage des diagnostics qui quittent le poste (presentation-edition-v1 Slice 10, `docs/release.md` › *Support bundle*).

Tous les secrets ci-dessous sont FAUX (formes réalistes, valeurs inventées).
"""

from __future__ import annotations

import subprocess

from jarvis.domain.diagnostic_redaction import DiagnosticRedactor, path_tokens
from jarvis.runtime import brain_cli

ENV = {"LOCALAPPDATA": r"C:\Users\Jean.Dupont\AppData\Local", "APPDATA": r"C:\Users\Jean.Dupont\AppData\Roaming",
       "TEMP": r"C:\Users\Jean.Dupont\AppData\Local\Temp", "USERPROFILE": r"C:\Users\Jean.Dupont", "USERNAME": "Jean.Dupont"}
FAKE_ANTHROPIC = "sk-ant-api03-FAKEfakeFAKEfake0123456789abcdef"
FAKE_OPENAI = "sk-proj-FAKE0123456789fakeFAKEfake"
FAKE_GOOGLE = "AIzaSyFAKE-fake_FAKE-0123456789abcdefghij"
FAKE_OAUTH = "ya29.a0FAKEfakeFAKEfake0123456789_-fake"
FAKE_REFRESH = "1//0gFAKEfakeFAKE0123456789fake"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9fakefakefake.eyJzdWIiOiJmYWtlIn0fake.c2lnbmF0dXJlZmFrZQ"
SECRETS = (FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_GOOGLE, FAKE_OAUTH, FAKE_REFRESH, FAKE_JWT, "hunter2-fake")


def test_secret_shapes_and_named_pairs_are_masked():
    r = DiagnosticRedactor(ENV)
    line = (f"key {FAKE_ANTHROPIC} then {FAKE_OPENAI} google={FAKE_GOOGLE} auth {FAKE_OAUTH} refresh {FAKE_REFRESH} "
            f"Authorization: Bearer {FAKE_JWT} password=hunter2-fake")
    out = r.text(line)
    for secret in SECRETS:
        assert secret not in out, secret
    assert "[secret masqué]" in out


def test_personal_paths_user_name_and_email_are_replaced():
    r = DiagnosticRedactor(ENV)
    out = r.text(r"open C:\Users\Jean.Dupont\AppData\Local\CIRCOE\Jarvis\data\state\jarvis.sqlite3 failed; "
                 r"export C:\Users\Jean.Dupont\Documents\Jarvis\deck.mp4; other C:\Users\Marie\x; "
                 "c:/users/jean.dupont/appdata/roaming/claude; mail jean.dupont@circoe.com; user Jean.Dupont")
    assert "Jean.Dupont" not in out and "jean.dupont" not in out.lower().replace("<user>", "")
    assert r"%LOCALAPPDATA%\CIRCOE\Jarvis\data" in out and r"%USERPROFILE%\Documents" in out
    assert "%APPDATA%/claude" in out and r"C:\Users\<user>\x" in out and "<email>" in out and "Marie" not in out


def test_a_longer_folder_that_only_starts_like_a_root_is_not_cut_in_the_middle():
    r = DiagnosticRedactor(ENV)
    out = r.text(r"C:\Users\Jean.DupontArchive\notes.txt")
    assert out == r"C:\Users\<user>\notes.txt"


def test_json_escaped_paths_are_replaced_too():
    r = DiagnosticRedactor(ENV)
    out = r.text('{"path": "C:\\\\Users\\\\Jean.Dupont\\\\AppData\\\\Local\\\\x"}')
    assert "Jean.Dupont" not in out and "%LOCALAPPDATA%" in out


def test_structured_values_keep_their_shape_and_lose_content_and_credentials():
    r = DiagnosticRedactor(ENV, known_secrets=["hunter2-fake"])
    out = r.structured({"message": r"failed in C:\Users\Jean.Dupont\x", "data": {
        "text": "ce que la salle a dit", "transcript": "bonjour", "api_key": "zzz-fake", "count": 3,
        "nested": [{"prompt": "fais une vidéo", "note": "hunter2-fake"}]}})
    assert out["message"] == r"failed in %USERPROFILE%\x"
    data = out["data"]
    assert data["text"].startswith("<") and "salle" not in data["text"] and data["transcript"] == "<7 caractères retirés>"
    assert data["api_key"] == "[secret masqué]" and data["count"] == 3
    assert "vidéo" not in data["nested"][0]["prompt"] and data["nested"][0]["note"] == "[secret masqué]"


def test_path_tokens_go_from_the_most_precise_root_to_the_widest():
    tokens = [token for _prefix, token in path_tokens(ENV)]
    assert tokens.index("%TEMP%") < tokens.index("%LOCALAPPDATA%") < tokens.index("%USERPROFILE%")
    assert path_tokens({"TEMP": "", "USERPROFILE": "C:"}) == ()  # vide ou trop court : jamais une racine


def test_the_claude_cli_error_tail_is_redacted_before_it_reaches_the_report(monkeypatch):
    """I-009 point 5 : la dernière ligne d'un `claude auth status` illisible ne porte ni clé, ni adresse, ni chemin."""

    for name, value in ENV.items():
        monkeypatch.setenv(name, value)

    def run(argv, timeout_s):
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "2.1.310 (Claude Code)", "")
        return subprocess.CompletedProcess(argv, 1, "", f"error for jean.dupont@circoe.com key {FAKE_ANTHROPIC} "
                                                        r"in C:\Users\Jean.Dupont\.claude\config.json")

    facts = brain_cli.probe("claude", run=run)
    assert facts.error.startswith("claude_auth_status_unreadable: exit 1")
    assert FAKE_ANTHROPIC not in facts.error and "circoe.com" not in facts.error and "Jean.Dupont" not in facts.error
    assert r"%USERPROFILE%\.claude" in facts.error
