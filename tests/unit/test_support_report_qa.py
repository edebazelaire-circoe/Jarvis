"""Reprise QA de la Slice 07 (V1.2) : non-régression des canaris et sondes de la QA (`slices/07-…/qa/qa-report.md`).

B1 : JSON imbriqué et échappé, clés de style variable d'environnement, `refreshToken` ; M1 : `.env` du dépôt en mode
développement ; M2 : noms de fichiers ; M3 : PGP, PuTTY, PEM chiffrée, fichiers de clé ; m1 : lien dur ; m2 : BLOB
non vidés et pages libérées ; m3 : second envoi pendant une attente ; m4 : copies brutes orphelines ; m5 : rétention
d'un paquet dont l'envoi a échoué.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import zipfile

import pytest

from jarvis.domain.diagnostic_redaction import DiagnosticRedactor
from jarvis.runtime import support_bundle as SB
from jarvis.runtime import support_report as SR
from jarvis.runtime import support_send as SS
from jarvis.runtime import support_snapshot as SNAP
from jarvis.runtime.local_secrets import seal_value
from jarvis.runtime.support_routes import SupportRouteError
from tests.unit.test_support_bundle import FakeSealer, profile
from tests.unit.test_support_report import seeded, service

#: Canaris de la QA (`v12s07qa/scripts/probe_canaries.py`), plus ceux des points M1 et M3.
C = {
    "env_quoted": "QaEnvQuoted7Hh2Kk9Mm4Pp1", "env_plain_comment": "QaEnvPlain3Rr8Tt5Yy2Uu6",
    "core_token": "QaCoreTok9Vv1Bb6Nn3Xx8", "sealed": "QaSealedKey4Jj7Ll2Ww5Zz", "vault": "QaVaultSecret8Gg3Ff6Dd1",
    "plain_legacy": "sk-proj-QaLegacyPlainOpenAI1234567890", "nested_json": "QaNestedOpaque5Cc2Aa9Ee7",
    "xapikey": "QaXApiKeyHdr6Ss3Qq8Oo1", "env_in_json": "QaOpenAiEnvJson2Ii7Uu4", "url_pw": "QaUrlPassw0rd9Kk1",
    "cookie": "QaCookieSess7Yy2Tt5", "pgp": "QaPgpBodyLmNoPqRsTuVwXyZ0123456789",
    "pem_enc": "QaPemEncryptedBodyAbCdEfGh0123456789", "openssh": "QaOpenSshBodyb3BlbnNzaC1rZXktdjE",
    "fts": "sk-ant-api03-QaFtsCanary0123456789abcdefXYZ", "freed": "sk-ant-api03-QaFreedPageCanary0123456789abc",
    "blob": "QaBlobSecretInPlainBytes4Gg", "filename": "sk-ant-api03-QaFileNameCanary0123456789",
    "camel": "QaCamelRefresh8Pp3Ll6", "github_env_json": "QaGithubTok1Ww4Ee7Rr0", "settings_custom": "QaSettingsCustom5Mm8Nn2",
    "basic_auth": "QaBasicAuthB64xyz123", "ppk": "QaPuttyPrivLinesAAAAgQC0123456789",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJxYSJ9.QaJwtSig0123456789",
    "board_title": "sk-ant-api03-QaBoardTitleCanary0123456789", "desc_pair": "QaDescPassw0rdZz",
    "export_env": "QaExportEleven5Lb7Vv2", "double_nested": "QaDoubleNested9Xx4Zz1", "key_file": "QaKeyFileBody7Pp2Mm8",
}


def seed(tmp: Path) -> SB.BundleSources:
    sources, _env = profile(tmp)
    data, runtime, config = sources.data_root, sources.runtime_root, sources.config_dir
    with open(config / ".env", "a", encoding="utf-8") as env:
        env.write(f'SERVICE_TOKEN="{C["env_quoted"]}"  # quoted with comment\n')
        env.write(f'WEBHOOK_SECRET={C["env_plain_comment"]} # trailing comment\n')
    (runtime / "core.token").write_text(C["core_token"], encoding="utf-8")
    sealer = FakeSealer()
    (runtime / "control-center-settings.json").write_text(json.dumps({
        "agent_cli": "claude", "openai_api_key": C["plain_legacy"],
        "credentials": [{"provider": "deepgram", "sealed": seal_value(C["sealed"], sealer)}],
        "webhook": {"url": "https://hooks.example/x", "elevenlabs_key": C["settings_custom"]}}), encoding="utf-8")
    vault = {"v": 1, "plugin_id": "circuit", "kind": "static", "static": {"api_token": C["vault"]}}
    with sqlite3.connect(data / "state" / "jarvis.sqlite3") as conn:
        conn.execute("INSERT INTO mcp_credentials VALUES (?,?,?,?,?,?)",
                     ("cred_" + "1" * 32, "circuit", "dpapi-user-v1", "t", "t", sealer.seal(json.dumps(vault).encode())))
        inner = json.dumps({"access_token": C["nested_json"], "refreshToken": C["camel"]})
        double = json.dumps({"tool_output": json.dumps({"result": json.dumps({"refresh_token": C["double_nested"]})})})
        payload = {"wrapped": inner, "double": double,
                   "headers": {"X-Api-Key": C["xapikey"], "Authorization": f"Basic {C['basic_auth']}"},
                   "env": {"OPENAI_API_KEY": C["env_in_json"], "GITHUB_TOKEN": C["github_env_json"]},
                   "url": f"postgres://bob:{C['url_pw']}@db.example:5432/x", "log": f"Cookie: sid={C['cookie']}",
                   "jwt": C["jwt"], "paste": f"export ELEVENLABS_API_KEY={C['export_env']}",
                   "mention": f"vault {C['vault']} core {C['core_token']} env {C['env_quoted']} {C['env_plain_comment']} "
                              f"sealed {C['sealed']} legacy {C['plain_legacy']}"}
        conn.execute("INSERT INTO conversations(id, updated_at, data) VALUES (?,?,?)", ("qa-conv", "t", json.dumps(payload)))
        conn.execute("INSERT INTO conversations(id, updated_at, data) VALUES (?,?,?)", ("qa-conv-flat", "t", inner))
        conn.execute("INSERT INTO devices(id, data) VALUES (?, ?)", ("qa-dev", C["blob"].encode()))
        conn.execute("INSERT INTO jobs(id,status,created_at,data) VALUES (?,?,?,?)", ("qa-freed", "x", "t", (C["freed"] + " ") * 400))
        conn.execute("DELETE FROM jobs WHERE id='qa-freed'")
        conn.execute("CREATE VIRTUAL TABLE qa_fts USING fts5(body)")
        conn.execute("INSERT INTO qa_fts(body) VALUES (?)", (f"memo {C['fts']} fin",))
        board = "board_qa77"
        conn.execute("INSERT INTO work_boards(board_id,status,created_at,updated_at,data) VALUES (?,?,?,?,?)",
                     (board, "active", "t", "t", json.dumps({"title": f"Projet {C['board_title']}", "board_kind": "presentation"})))
        conn.execute("INSERT INTO jarvis_sessions VALUES (?,?,?,?,?)", ("qa-sess", "open", "2026-10-27T09:00:00Z", board, "{}"))
    conn.close()
    mem = data / "boards" / board / "memory" / "documents"
    mem.mkdir(parents=True)
    (mem / "keys.md").write_text(
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\n\n" + C["pgp"] + "\n=abcd\n-----END PGP PRIVATE KEY BLOCK-----\n\n"
        "-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,0123456789ABCDEF\n\n" + C["pem_enc"]
        + "\n-----END RSA PRIVATE KEY-----\n\n-----BEGIN OPENSSH PRIVATE KEY-----\n" + C["openssh"]
        + "\n-----END OPENSSH PRIVATE KEY-----\nPuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\nPrivate-Lines: 1\n"
        + C["ppk"] + "\nPrivate-MAC: 00\nexport ELEVENLABS_API_KEY=" + C["export_env"] + "\n", encoding="utf-8")
    (mem / f"{C['filename']}.md").write_text("nom de fichier piégé\n", encoding="utf-8")
    (mem / f"notes-{C['env_quoted']}.md").write_text("nom de fichier avec secret connu\n", encoding="utf-8")
    (mem / "deploy.ppk").write_text(f"PuTTY {C['key_file']}\n", encoding="utf-8")
    (mem / "server.key").write_text(f"raw {C['key_file']}\n", encoding="utf-8")
    sources.credentials_sealer = sources.mcp_sealer = lambda: sealer
    sources.full = True
    sources.description = f"Plantage. password: {C['desc_pair']} et cle {C['plain_legacy']}"
    sources.health = {"items": [{"item_id": "brain", "state": "failed", "summary": f"token={C['nested_json']}"}]}
    return sources


def leaks(path: Path) -> dict[str, list[str]]:
    with zipfile.ZipFile(path) as bundle:
        blobs = {name: bundle.read(name) for name in bundle.namelist()}
    names = "\n".join(blobs).encode()
    found = {}
    for key, value in C.items():
        hits = [name for name, body in blobs.items() if value.encode() in body or value[-14:].encode() in body]
        if value.encode() in names or value[-14:].encode() in names:
            hits.append("<member name>")
        if hits:
            found[key] = hits
    return found


def test_every_qa_canary_is_absent_from_every_member_name_and_the_prompt(tmp_path):
    sources = seed(tmp_path)
    path = SB.write_bundle(sources, tmp_path / "out")
    assert leaks(path) == {}
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        bundle.extract("state/jarvis.sqlite3", tmp_path / "x")
    by_reason = {entry["reason"] for entry in manifest["files"] if entry.get("reason")}
    assert "key_file_never_included" in by_reason
    excluded = [e["path"] for e in manifest["files"] if e.get("reason") == "key_file_never_included"]
    assert sorted(excluded) == ["board/memory/documents/deploy.ppk", "board/memory/documents/server.key"]
    snap = sqlite3.connect(tmp_path / "x" / "state" / "jarvis.sqlite3")
    try:
        assert snap.execute("PRAGMA freelist_count").fetchone()[0] == 0
        assert snap.execute("SELECT length(data) FROM devices WHERE id='qa-dev'").fetchone()[0] == 0, "BLOB emptied"
        assert snap.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'qa_fts%'").fetchone()[0] == 0
        row = json.loads(snap.execute("SELECT data FROM conversations WHERE id='qa-conv'").fetchone()[0])
    finally:
        snap.close()
    assert json.loads(row["wrapped"])["refreshToken"] == "[secret masqué]"
    assert "[secret masqué]" in row["double"] and row["env"]["GITHUB_TOKEN"] == "[secret masqué]"
    work = Path(tempfile.mkdtemp(dir=tmp_path))
    collected = SB.collect_bundle(sources, work)
    _system, prompt = SR.build_prompt(collected.evidence)
    prompt = collected.redact(prompt)
    assert [key for key, value in C.items() if value in prompt or value[-14:] in prompt] == []


def test_masked_file_names_are_stable_and_keep_their_extension():
    mask = DiagnosticRedactor({}).cell
    name = f"{C['filename']}.md"
    assert SNAP.masked_name(name, mask) == SNAP.masked_name(name, mask)
    assert SNAP.masked_name(name, mask).startswith("masque-") and SNAP.masked_name(name, mask).endswith(".md")
    assert SNAP.masked_name("summary.md", mask) == "summary.md"


def test_key_shapes_of_the_qa_are_masked_in_free_text():
    r = DiagnosticRedactor({})
    out = r.text("-----BEGIN PGP PRIVATE KEY BLOCK-----\n\nAbCdEf123\n-----END PGP PRIVATE KEY BLOCK-----\n"
                 "-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,00\n\nEncBody99\n"
                 "-----END RSA PRIVATE KEY-----\nPuTTY-User-Key-File-2: ssh-rsa\nPrivate-Lines: 1\nPpkBody77\nPrivate-MAC: 0\n"
                 "export ELEVENLABS_API_KEY=Eleven5Lb7\nGITHUB_TOKEN: 'Ghp1Ww4Ee7'\nKEYBOARD_LAYOUT=azerty")
    for secret in ("AbCdEf123", "EncBody99", "PpkBody77", "Eleven5Lb7", "Ghp1Ww4Ee7"):
        assert secret not in out, secret
    assert "KEYBOARD_LAYOUT=azerty" in out
    assert r.cell('{"id": "board_0123abcd", "at": "2026-10-27T10:00:00Z", "refreshToken": "abcdef12"}') == \
        '{"id": "board_0123abcd", "at": "2026-10-27T10:00:00Z", "refreshToken": "[secret masqué]"}'


def test_in_development_the_repository_env_values_are_known_secrets(tmp_path, monkeypatch):
    from jarvis.environment import PROJECT_ROOT
    from jarvis.installation import Installation, InstallMode
    assert SB._config_dir(Installation(InstallMode.DEVELOPMENT, tmp_path)) == PROJECT_ROOT
    sources, _env = profile(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("QA_SERVICE_TOKEN=Op4queDevT0kenZz\n", encoding="utf-8")
    sources.config_dir = repo
    sources.full = True
    sources.description = "le jeton Op4queDevT0kenZz apparaît"
    sources.active_board = {"board_id": "board_dev"}
    memory = sources.data_root / "boards" / "board_dev" / "memory"
    memory.mkdir(parents=True)
    (memory / "summary.md").write_text("copié : Op4queDevT0kenZz\n", encoding="utf-8")
    path = SB.write_bundle(sources, tmp_path / "out")
    with zipfile.ZipFile(path) as bundle:
        assert all(b"Op4queDevT0kenZz" not in bundle.read(name) for name in bundle.namelist())


def test_a_hard_link_in_the_board_memory_is_refused(tmp_path):
    sources, _env = profile(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("hors racine", encoding="utf-8")
    memory = sources.data_root / "boards" / "b1" / "memory"
    memory.mkdir(parents=True)
    os.link(outside, memory / "hard.md")
    files, entries = SNAP.board_memory(sources.data_root, "b1", str)
    assert files == {} and entries[0].reason == "hard_link_not_followed"


def test_non_vault_blobs_and_freed_pages_never_reach_the_snapshot(tmp_path):
    base = tmp_path / "b.sqlite3"
    with sqlite3.connect(base) as conn:
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, data BLOB, note TEXT)")
        conn.execute("INSERT INTO t(data, note) VALUES (?, 'x')", (b"BlobCanary-1234567",))
        conn.execute("INSERT INTO t(data, note) VALUES (NULL, ?)", ("FreedCanary-7654321 " * 500,))
        conn.execute("DELETE FROM t WHERE note LIKE 'Freed%'")
    conn.close()
    assert b"FreedCanary-7654321" in base.read_bytes(), "the freed page still holds the text in the source"
    report = SNAP.snapshot_database(base, tmp_path / "s.sqlite3", str)
    raw = (tmp_path / "s.sqlite3").read_bytes()
    assert b"BlobCanary" not in raw and b"FreedCanary" not in raw and report["blob_values_emptied"] == 1


def test_a_second_send_while_the_mail_client_waits_is_refused(tmp_path, monkeypatch):
    sources = seeded(tmp_path)
    release = threading.Event()

    class Slow:
        name = "fake"

        def describe(self):
            return {"name": "fake", "available": True, "label": "lent"}

        def send(self, bundle, *, to, subject, body):
            release.wait(10)
            return SS.SendOutcome("draft_opened", "Brouillon ouvert.")

    import jarvis.runtime.support_routes as routes
    monkeypatch.setattr(routes, "SEND_TIMEOUT_S", 0.2)
    svc = service(tmp_path, sources, transport=Slow())

    async def run():
        name = (await svc.create({"consent": True}))["bundle"]["name"]
        first = await svc.send(name)
        with pytest.raises(SupportRouteError) as second:
            await svc.send(name)
        release.set()
        await asyncio.sleep(0.3)
        third = await svc.send(name)
        return first, second.value, third

    first, second, third = asyncio.run(run())
    assert first["status"] == "waiting" and second.status == 409 and second.code == "support_send_in_progress"
    assert third["status"] == "draft_opened"


def test_orphan_work_folders_are_swept_when_the_service_opens_and_before_a_creation(tmp_path):
    sources = seeded(tmp_path)
    support = sources.runtime_root / SB.SUPPORT_DIR
    (support / ".work-orphan").mkdir(parents=True)
    (support / ".work-orphan" / "jarvis.sqlite3.work").write_bytes(b"raw copy")
    svc = service(tmp_path, sources)
    assert not (support / ".work-orphan").exists()
    (support / ".work-again").mkdir()
    asyncio.run(svc.create({"consent": True}))
    assert not any(p.name.startswith(".work-") for p in support.iterdir())


def test_a_bundle_whose_send_failed_is_kept_until_saved_or_thirty_days(tmp_path):
    folder = tmp_path / "support"
    folder.mkdir()
    now = time.time()
    names = [f"jarvis-support-2026102{i}T100000Z.zip" for i in range(8)]
    for age, name in enumerate(reversed(names)):
        (folder / name).write_bytes(b"z")
        os.utime(folder / name, (now - age * 3600, now - age * 3600))
    failed = names[0]  # the oldest, would be pruned by the count rule
    SB.set_pending(folder, failed, True)
    SB.prune_support_folder(folder, now=now)
    left = sorted(p.name for p in folder.glob("jarvis-support-*.zip"))
    assert failed in left and len(left) == 6 and sorted(names[-5:]) == [n for n in left if n != failed]
    SB.set_pending(folder, failed, False)
    SB.prune_support_folder(folder, now=now)
    assert failed not in [p.name for p in folder.iterdir()]
    SB.set_pending(folder, names[-1], True)
    os.utime(folder / names[-1], (now - 40 * 86400, now - 40 * 86400))
    SB.prune_support_folder(folder, now=now)
    assert not (folder / names[-1]).exists() and SB.pending_bundles(folder) == set()


def test_the_service_marks_a_failed_send_pending_and_clears_it_on_save(tmp_path):
    from tests.unit.test_support_report import FailingTransport
    sources = seeded(tmp_path)
    export = tmp_path / "Documents" / "Jarvis"
    export.parent.mkdir()
    sources.environ = {**sources.environ, "JARVIS_EXPORT_ROOT": str(export)}
    svc = service(tmp_path, sources, transport=FailingTransport())
    name = asyncio.run(svc.create({"consent": True}))["bundle"]["name"]
    with pytest.raises(SupportRouteError) as failed:
        asyncio.run(svc.send(name))
    assert "30 jours" in str(failed.value) and SB.pending_bundles(svc.support_dir) == {name}
    asyncio.run(svc.save(name))
    assert SB.pending_bundles(svc.support_dir) == set()
