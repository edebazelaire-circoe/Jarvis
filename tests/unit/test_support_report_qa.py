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


# ------------------------------------------------------------------ seconde reprise (contre-relecture `qa/rework-review.md`)


def CR(n: int) -> str:
    return f"CRZ{n}q7Lm2Vx9Pw4Tn8Bk3"  # the counter-review's canary shape (`v12s07cr/probe_redact.py`)


@pytest.mark.parametrize("source, canary", [
    (f'$env:OPENAI_API_KEY="{CR(62)}"', CR(62)),
    (f'$env:DEEPGRAM_API_KEY = "{CR(63)}"', CR(63)),
    (f"$env:GITHUB_TOKEN={CR(64)}", CR(64)),
    (f'setx ANTHROPIC_API_KEY "{CR(65)}"', CR(65)),
    (f"setx ELEVENLABS_API_KEY {CR(66)}", CR(66)),
    (f"set OPENAI_API_KEY={CR(6)}", CR(6)),
    (f'set "ELEVENLABS_API_KEY={CR(61)}"', CR(61)),
    (f"export ELEVENLABS_API_KEY={CR(67)}", CR(67)),
    (json.dumps([{"name": "OPENAI_API_KEY", "value": CR(3)}, {"name": "LANG", "value": "fr"}]), CR(3)),
    (json.dumps({"headers": [{"name": "X-Api-Key", "value": CR(31)}]}), CR(31)),
    (json.dumps([{"key": "DB_PASSWORD", "value": CR(32)}]), CR(32)),
    ('env: [{"name": "GITHUB_TOKEN", "value": "' + CR(33) + '"}]', CR(33)),
    (json.dumps([{"value": CR(34), "name": "client_secret"}]), CR(34)),
    (json.dumps({"out": json.dumps([{"name": "API_TOKEN", "value": CR(35)}])}), CR(35)),
    (json.dumps({"sessionKey": CR(36), "privateKey": CR(37)}), CR(36)),
    (json.dumps({"sessionKey": CR(36), "privateKey": CR(37)}), CR(37)),
    (json.dumps({"a": json.dumps({"b": json.dumps({"GITHUB_TOKEN": CR(1)})})}), CR(1)),
])
def test_shell_prefixes_and_name_value_pairs_are_masked(source, canary):
    r = DiagnosticRedactor({})
    assert canary not in r.text(source) and canary not in r.cell(source)
    assert canary not in json.dumps(r.structured({"x": source}))


def test_a_powershell_secret_never_reaches_the_zip_nor_the_prompt(tmp_path):
    sources = seeded(tmp_path)
    secret, setx = CR(80), CR(81)
    sources.description = f'$env:OPENAI_API_KEY="{secret}" puis setx GITHUB_TOKEN "{setx}"'
    with sqlite3.connect(sources.data_root / "state" / "jarvis.sqlite3") as conn:
        conn.execute("INSERT INTO conversations(id, updated_at, data) VALUES (?,?,?)",
                     ("ps", "t", json.dumps({"cmd": f'$env:OPENAI_API_KEY="{secret}"',
                                             "pairs": [{"name": "X-Api-Key", "value": setx}]})))
    conn.close()
    path = SB.write_bundle(sources, tmp_path / "out")
    with zipfile.ZipFile(path) as bundle:
        for name in bundle.namelist():
            body = bundle.read(name)
            assert secret.encode() not in body and setx.encode() not in body, name
    collected = SB.collect_bundle(sources, Path(tempfile.mkdtemp(dir=tmp_path)))
    prompt = collected.redact("".join(SR.build_prompt(collected.evidence)))
    assert secret not in prompt and setx not in prompt


#: Échantillons de la contre-relecture (`probe_fp.py`, base réelle) qui doivent ressortir à l'identique.
ORDINARY = [
    json.dumps({"token_count": 1234, "max_tokens": 4096, "input_tokens": 812, "output_tokens": 90}),
    json.dumps({"board_id": "brd_7f3a9c21e4", "session_id": "ses_01HZX8Q2", "ts": "2026-10-27T10:11:12Z"}),
    json.dumps({"key": "ui.theme", "value": "dark"}),
    json.dumps({"key": "presentation.default_layout", "value": "16:9"}),
    json.dumps({"idempotency_key": "req-2026-10-27-abc123", "dedupe_key": "board:42:msg:7"}),
    json.dumps({"sort_key": "2026-10-27#0007", "partition_key": "boards"}),
    json.dumps({"supersedes_key": "evt_2026_0001_abcdef", "output_key": "out_9f8e7d6c5b"}),
    json.dumps({"public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabc"}),
    json.dumps({"error": "KeyError: 'board_id'", "path": "boards/brd_1/memory/summary.md"}),
    json.dumps({"credential_ref": "cred_0123456789abcdef", "key_id": "kid_2026abc"}),
    "Traceback: KeyError: 'presentation_slides'",
    "InvalidTokenError: Signature has expired",
    "Primary key: board_id must be unique",
    "pass: first_attempt",
    "settings key=ui.theme changed",
    "tokens=512 used of max_tokens=4096",
    json.dumps({"password_set": True, "has_token": False, "token_expires_at": "2026-10-28T00:00:00Z"}),
    json.dumps({"keyboard_layout": "fr-FR", "hotkey": "ctrl+alt+j", "passage": "intro"}),
    json.dumps({"cache_key": "slides:v3:abcd1234", "primary_key": "board_id"}),
    "Using model claude-sonnet with key_id=kid_2026abc",
]


@pytest.mark.parametrize("sample", ORDINARY)
def test_ordinary_identifiers_named_key_stay_readable(sample):
    assert DiagnosticRedactor({}).cell(sample) == sample


def test_secret_names_are_an_explicit_tested_list():
    from jarvis.domain.diagnostic_redaction import sensitive_name
    secret = ["OPENAI_API_KEY", "api_key", "apiKey", "x-api-key", "client_secret", "refreshToken", "access_token",
              "DB_PASSWORD", "private_key", "privateKey", "sessionKey", "Ocp-Apim-Subscription-Key", "ELEVENLABS_KEY",
              "elevenlabs_key", "PRIVATE-TOKEN", "x-auth-token", "GITHUB_TOKEN", "passphrase", "Authorization", "cookie",
              "APIKEY", "clientSecret"]
    ordinary = ["key", "supersedes_key", "output_key", "idempotency_key", "cache_key", "public_key", "primary_key",
                "token_count", "max_tokens", "token_type", "KeyError", "InvalidTokenError", "credential_ref", "key_id",
                "keyboard_layout", "pass", "has_token", "password_set", "tokens", "monkey", "signature"]
    assert [name for name in secret if not sensitive_name(name)] == []
    assert [name for name in ordinary if sensitive_name(name)] == []


@pytest.mark.parametrize("marker, times", [("-----BEGIN A PRIVATE KEY-----", 8000), ("Private-Lines: ", 16000),
                                           ("PuTTY-User-Key-File-2: ", 8000)], ids=["pem", "putty_lines", "putty_header"])
def test_repeated_key_start_markers_stay_linear(marker, times):
    started = time.process_time()
    DiagnosticRedactor({}).text(marker * times)
    assert time.process_time() - started < 2.0


def test_a_key_block_without_end_followed_by_another_is_still_masked():
    out = DiagnosticRedactor({}).text("-----BEGIN PRIVATE KEY-----\nFirstBody123\n-----BEGIN RSA PRIVATE KEY-----\n"
                                      "SecondBody456\n-----END RSA PRIVATE KEY-----\nfin")
    assert "FirstBody123" not in out and "SecondBody456" not in out and out.endswith("fin")


def test_key_files_are_excluded_whatever_the_case_of_their_extension(tmp_path):
    sources, _env = profile(tmp_path)
    memory = sources.data_root / "boards" / "b1" / "memory"
    memory.mkdir(parents=True)
    for name in ("ID_RSA.PEM", "client.Key", "vault.P12"):
        (memory / name).write_text("x", encoding="utf-8")
    files, entries = SNAP.board_memory(sources.data_root, "b1", str)
    assert files == {} and sorted(e.reason for e in entries) == ["key_file_never_included"] * 3


def test_the_masked_cell_count_is_exact_and_untouched_cells_are_not_rewritten(tmp_path):
    base = tmp_path / "c.sqlite3"
    with sqlite3.connect(base) as conn:
        conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, data TEXT)")
        conn.executemany("INSERT INTO t(data) VALUES (?)", [(json.dumps({"a": i, "b": "texte ordinaire"}, indent=1),)
                                                             for i in range(50)])
        conn.execute("INSERT INTO t(data) VALUES (?)", (json.dumps({"api_key": "Zq7Lm2Vx9Kp4Rt8W"}),))
    conn.close()
    report = SNAP.snapshot_database(base, tmp_path / "s.sqlite3", DiagnosticRedactor({}).cell)
    assert report["text_values_masked"] == 1
    with sqlite3.connect(tmp_path / "s.sqlite3") as snap:
        first = snap.execute("SELECT data FROM t WHERE id = 1").fetchone()[0]
    snap.close()
    assert first == json.dumps({"a": 0, "b": "texte ordinaire"}, indent=1), "an untouched cell keeps its exact text"


def test_a_send_in_progress_blocks_a_send_of_another_bundle(tmp_path, monkeypatch):
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
        first_name = (await svc.create({"consent": True}))["bundle"]["name"]
        await asyncio.sleep(1.1)  # another second: another bundle name
        second_name = (await svc.create({"consent": True, "description": "autre"}))["bundle"]["name"]
        assert first_name != second_name
        await svc.send(first_name)
        preview = await svc.preview()
        with pytest.raises(SupportRouteError) as refused:
            await svc.send(second_name)
        release.set()
        await asyncio.sleep(0.3)
        return preview, refused.value, await svc.preview()

    during, refused, after = asyncio.run(run())
    assert during["send_in_progress"] is True and refused.code == "support_send_in_progress"
    assert after["send_in_progress"] is False
