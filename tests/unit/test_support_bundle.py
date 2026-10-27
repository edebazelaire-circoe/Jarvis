"""Paquet de support du produit (presentation-edition-v1 Slice 10, `docs/release.md` › *Support bundle*).

Profil jetable sous `tmp_path`, faux secrets, fausses paroles : le paquet ne doit emporter ni secret, ni chemin
personnel, ni contenu (paroles, présentations, `CONTEXT_GLOBAL`, bases), et rester borné.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
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


def test_an_opaque_token_of_the_env_or_of_core_token_is_masked_wherever_a_log_prints_it(tmp_path):
    """QA S10 M2 : un jeton sans forme reconnaissable (Infomaniak, Circuit Toolbox, jeton local) n'est masqué que parce
    que le masqueur le CONNAÎT ; un réglage ordinaire de `.env` reste lisible."""

    sources, _env = profile(tmp_path)
    opaque, unnamed, local = "Zq7Xv2Lm9Pw4Rt8Ks1Hd6Fn3", "a1b2c3d4e5f6g7h8", "tok-FAKE-0123456789"
    with open(sources.config_dir / ".env", "a", encoding="utf-8") as env:
        env.write(f'INFOMANIAK_TOKEN="{opaque}"\nCIRCUIT_TOOLBOX_ENDPOINT_ID={unnamed}\nJARVIS_PRODUCT_EDITION=presentation\n'
                  "JARVIS_LAUNCH_VOICE=0\n")
    with open(sources.runtime_root / "logs" / "core.log", "a", encoding="utf-8") as log:
        log.write(f"connecting upstream with {opaque} then endpoint {unnamed} edition presentation\n")
        log.write(f"local session {local}\n")
    with open(sources.runtime_root / "errors.jsonl", "a", encoding="utf-8") as errors:
        errors.write(json.dumps({"ts": "t", "kind": "k", "level": "error", "message": f"upstream refused {opaque}",
                                 "data": {"detail": f"with {local}"}}) + "\n")
    secrets = SB.known_secrets(sources)
    assert opaque in secrets and unnamed in secrets and "tok-FAKE-0123456789" in secrets
    assert "presentation" not in secrets and "0" not in secrets
    everything = "\n".join(read_zip(SB.write_bundle(sources)).values())
    for leak in (opaque, unnamed, local):
        assert leak not in everything, leak
    assert "edition presentation" in everything, "an ordinary setting value stays readable"


def test_error_data_keeps_diagnostics_by_allowlist_and_drops_user_text(tmp_path):
    """QA S10 m3 : `data` passe par une liste blanche (titres, requêtes, mots de l'utilisateur n'entrent pas)."""

    sources, _env = profile(tmp_path)
    row = {"ts": "t", "kind": "studio.failed", "level": "error", "message": "m" * 3000,
           "data": {"title": "Plan secret de fusion", "query": "chiffres du trimestre", "words": ["mot un", "deux"],
                    "error": "OSError: [Errno 22] Invalid argument", "presentation_id": "pres_0123", "count": 3,
                    "ok": False, "nested": {"reason": "disk full", "label": "Bilan secret"}}}
    (sources.runtime_root / "errors.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    kept = json.loads(read_zip(SB.write_bundle(sources))["logs/errors.jsonl"].splitlines()[-1])
    data = kept["data"]
    assert data["title"] == "<21 caractères retirés>" and data["query"] == "<21 caractères retirés>"
    assert data["words"] == ["<6 caractères retirés>", "deux"] and data["nested"]["label"] == "<12 caractères retirés>"
    assert data["error"] == "OSError: [Errno 22] Invalid argument" and data["nested"]["reason"] == "disk full"
    assert data["presentation_id"] == "pres_0123" and data["count"] == 3 and data["ok"] is False
    assert len(kept["message"]) < SB.MESSAGE_CHARS + 20


def test_a_base_with_a_wal_but_no_shm_is_read_without_creating_anything(tmp_path):
    """QA S10 m9 : `mode=ro` créerait un `-shm` à côté d'un `-wal` orphelin de son `-shm` ; rien ne doit apparaître."""

    sources, _env = profile(tmp_path)
    state = sources.data_root / "state"
    live = tmp_path / "live"
    live.mkdir()
    base = live / "jarvis.sqlite3"
    shutil.copyfile(state / "jarvis.sqlite3", base)
    holder = sqlite3.connect(base)
    try:
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute("PRAGMA wal_autocheckpoint=0")
        holder.execute("CREATE TABLE IF NOT EXISTS qa_wal (x)")
        holder.execute("INSERT INTO qa_wal VALUES (1)")
        holder.commit()
        for name in ("jarvis.sqlite3", "jarvis.sqlite3-wal"):  # a copy of a running base: base and -wal, no -shm
            shutil.copyfile(live / name, state / name)
    finally:
        holder.close()
    for leftover in state.glob("jarvis.sqlite3-shm"):
        leftover.unlink()
    assert (state / "jarvis.sqlite3-wal").exists() and not (state / "jarvis.sqlite3-shm").exists()
    before = {name: (state / name).read_bytes() for name in ("jarvis.sqlite3", "jarvis.sqlite3-wal")}
    summary = json.loads(read_zip(SB.write_bundle(sources))["bundle.json"])
    entry = summary["databases"]["state/jarvis.sqlite3"]
    assert entry["versions"] and entry["wal_not_read"] is True
    assert not (state / "jarvis.sqlite3-shm").exists(), "nothing created next to the base"
    assert {name: (state / name).read_bytes() for name in before} == before, "base and -wal byte-identical, never replayed"


def test_the_cli_command_is_declared():
    from jarvis.app import _parser

    args = _parser().parse_args(["support-bundle", "--out", "X"])
    assert args.command == "support-bundle" and args.out == "X"
