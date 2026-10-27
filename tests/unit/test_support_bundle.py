"""Paquet de support du produit (presentation-edition-v1 Slice 10, `docs/release.md` › *Support bundle*).

Profil jetable sous `tmp_path`, faux secrets, fausses paroles : le paquet ne doit emporter ni secret, ni chemin
personnel, ni contenu (paroles, présentations, `CONTEXT_GLOBAL`, bases), et rester borné.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.runtime import support_bundle as SB

FAKE_KEY = "sk-ant-api03-FAKEfakeFAKEfake0123456789abcdef"
ROOM_WORDS = "le budget confidentiel du client Durand"


def profile(tmp_path: Path) -> tuple[SB.BundleSources, dict[str, str]]:
    user_home = tmp_path / "Users" / "Jean.Dupont"
    local = user_home / "AppData" / "Local"
    home = local / "CIRCOE" / "Jarvis"
    data, runtime, config = home / "data", home / "runtime", home / "config"
    for folder in (data / "state", data / "CONTEXT_GLOBAL", data / "presentations" / "p1", runtime / "logs", config):
        folder.mkdir(parents=True)
    asyncio.run(_fresh_state(data / "state" / "jarvis.sqlite3"))
    (data / "CONTEXT_GLOBAL" / "profil.md").write_text(f"Préférences privées : {ROOM_WORDS}", encoding="utf-8")
    (data / "presentations" / "p1" / "presentation.json").write_text(json.dumps({"title": ROOM_WORDS}), encoding="utf-8")
    (config / ".env").write_text(f"# produit\nANTHROPIC_API_KEY={FAKE_KEY}\nexport GOOGLE_DRIVE_TOKEN=x\n", encoding="utf-8")
    (runtime / "control-center-settings.json").write_text(json.dumps({"openai_api_key": FAKE_KEY}), encoding="utf-8")
    (runtime / "core.token").write_text("tok-FAKE-0123456789", encoding="utf-8")
    errors = [{"ts": "t", "kind": "core.brain.failed", "level": "error",
               "message": f"auth failed for jean.dupont@circoe.com with {FAKE_KEY} at {local}\\CIRCOE\\Jarvis\\runtime",
               "data": {"text": ROOM_WORDS, "transcript": ROOM_WORDS, "authorization": f"Bearer {FAKE_KEY}", "code": 42}}
              for _ in range(SB.ERROR_LINES + 50)]
    (runtime / "errors.jsonl").write_text("".join(json.dumps(row) + "\n" for row in errors), encoding="utf-8")
    trace = [{"ts": "t", "kind": "presentation.room.transcript", "level": "info", "message": ROOM_WORDS,
              "data": {"text": ROOM_WORDS}}]
    (runtime / "trace.jsonl").write_text("".join(json.dumps(row) + "\n" for row in trace), encoding="utf-8")
    (runtime / "logs" / "core.log").write_text(
        "".join(f"line {i} token={FAKE_KEY} {user_home}\\Documents\n" for i in range(SB.LOG_LINES + 100))
        + "x" * (SB.MAX_LINE_CHARS + 500) + "\n", encoding="utf-8")
    (runtime / "launcher.json").write_text(json.dumps({"pid": 4, "ui_url": "http://127.0.0.1:17654/"}), encoding="utf-8")
    environ = {"LOCALAPPDATA": str(local), "USERPROFILE": str(user_home), "USERNAME": "Jean.Dupont",
               "TEMP": str(local / "Temp")}
    sources = SB.BundleSources(data_root=data, runtime_root=runtime, config_dir=config, environ=environ,
                               installation={"mode": "installed"},
                               package=lambda: {"version": "0.2.0", "intact": True, "problems": []})
    return sources, environ


async def _fresh_state(path: Path) -> None:
    repository = SQLiteStateRepository(path)
    await repository.initialize()
    await repository.close()


def read_zip(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as bundle:
        return {name: bundle.read(name).decode("utf-8") for name in bundle.namelist()}


def test_the_bundle_carries_bounded_redacted_diagnostics_and_no_content(tmp_path):
    sources, _env = profile(tmp_path)
    before = {p: p.read_bytes() for p in sources.data_root.rglob("*") if p.is_file()}
    path = SB.write_bundle(sources)
    assert path.parent == sources.runtime_root / SB.SUPPORT_DIR and path.name.startswith("jarvis-support-")
    files = read_zip(path)
    assert set(files) == {"bundle.json", "logs/errors.jsonl", "logs/trace-events.jsonl", "logs/core.log", "config-keys.json"}
    everything = "\n".join(files.values())
    for leak in (FAKE_KEY, "tok-FAKE", ROOM_WORDS, "circoe.com", "Jean.Dupont", str(tmp_path)):
        assert leak not in everything, leak
    summary = json.loads(files["bundle.json"])
    assert summary["package"]["version"] == "0.2.0" and summary["installation"] == {"mode": "installed"}
    state = summary["databases"]["state/jarvis.sqlite3"]
    assert state["versions"] and state["backups"] == []
    assert summary["data_folders"]["CONTEXT_GLOBAL"] == {"files": 1, "bytes": len(f"Préférences privées : {ROOM_WORDS}".encode())}
    assert summary["launcher"]["launcher.json"]["pid"] == 4
    errors = [json.loads(line) for line in files["logs/errors.jsonl"].splitlines()]
    assert len(errors) == SB.ERROR_LINES
    assert errors[0]["data"]["code"] == 42 and errors[0]["data"]["authorization"] == "[secret masqué]"
    assert "%LOCALAPPDATA%" in errors[0]["message"] and "<email>" in errors[0]["message"]
    assert [json.loads(line) for line in files["logs/trace-events.jsonl"].splitlines()] == [
        {"ts": "t", "kind": "presentation.room.transcript", "level": "info"}]
    core_lines = files["logs/core.log"].splitlines()
    assert len(core_lines) == SB.LOG_LINES and len(core_lines[-1]) < SB.MAX_LINE_CHARS + 20
    assert json.loads(files["config-keys.json"]) == {"config_env_keys": ["ANTHROPIC_API_KEY", "GOOGLE_DRIVE_TOKEN"]}
    # Lecture seule : rien du profil n'a changé, et aucun temporaire ne reste.
    assert {p: p.read_bytes() for p in sources.data_root.rglob("*") if p.is_file()} == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_two_bundles_in_the_same_second_never_overwrite_each_other(tmp_path):
    sources, _env = profile(tmp_path)
    first, second = SB.write_bundle(sources), SB.write_bundle(sources)
    assert first != second and first.exists() and second.exists()


def test_an_unwritable_destination_is_said_with_its_cause(tmp_path):
    sources, _env = profile(tmp_path)
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(SB.SupportBundleError) as refused:
        SB.write_bundle(sources, blocker / "sub")
    assert "Paquet de support non écrit" in str(refused.value)


def test_a_missing_profile_still_gives_a_bundle_that_says_what_is_missing(tmp_path):
    sources = SB.BundleSources(data_root=tmp_path / "nope" / "data", runtime_root=tmp_path / "nope" / "runtime",
                               config_dir=None, environ={}, package=lambda: (_ for _ in ()).throw(OSError("manifest gone")))
    files = read_zip(SB.write_bundle(sources, tmp_path / "out"))
    summary = json.loads(files["bundle.json"])
    assert summary["package"] == {"error": "OSError: manifest gone"}
    assert summary["databases"]["state/jarvis.sqlite3"] is None and summary["data_folders"]["state"] is None
    assert files["logs/errors.jsonl"] == ""


def test_an_unreadable_database_is_reported_not_raised(tmp_path):
    sources, _env = profile(tmp_path)
    broken = sources.data_root / "state" / "scene.sqlite3"
    broken.write_bytes(b"not a database at all" * 100)
    summary = json.loads(read_zip(SB.write_bundle(sources))["bundle.json"])
    assert "error" in summary["databases"]["state/scene.sqlite3"]
    with sqlite3.connect(sources.data_root / "state" / "jarvis.sqlite3") as conn:  # la vraie base reste lisible
        assert conn.execute("SELECT count(*) FROM schema_version").fetchone()[0] >= 1


def test_the_cli_command_is_declared():
    from jarvis.app import _parser

    args = _parser().parse_args(["support-bundle", "--out", "X"])
    assert args.command == "support-bundle" and args.out == "X"
