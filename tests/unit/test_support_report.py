"""« Signaler un problème » : paquet complet, rapport, envoi, rétention (V1.2 Slice 07, `docs/support-report.md`).

Profil jetable (celui de `test_support_bundle.profile`), Board, bases et journaux semés, CANARIS de secrets : clé
d'API, jeton OAuth, clé privée PEM, jeton opaque de `.env`, clé scellée des réglages et identifiant du coffre MCP. Aucun
ne doit apparaître dans un membre du zip (bases SQLite comprises, octets décompressés) ni dans le prompt du rapport.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile

import pytest

from jarvis.runtime import support_bundle as SB
from jarvis.runtime import support_report as SR
from jarvis.runtime import support_send as SS
from jarvis.runtime import support_snapshot as SNAP
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.local_secrets import seal_value
from jarvis.runtime.support_routes import SupportReportService, SupportRouteError
from tests.unit.test_support_bundle import FAKE_KEY, FakeSealer, profile

BOARD = "board_0123abcd"
OPAQUE = "Zq7Lm2Vx9Kp4Rt8Wn3Hs"            # .env value of a sensitive name, no recognisable shape
OAUTH = "ya29.a0AfH6SMBfakeOAuthTokenValue1234567890"
SEALED = "dg-Qm4Xr8Lp2Vn6Tz1Kw9"            # API key of the local settings, DPAPI-sealed in the product
VAULT = "mcpVaultTok3nH7Jd2Lq9Pz5Rw1"        # credential inside the MCP vault blob
PEM = ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7fakefakefake\n"
       "Zm9vYmFyYmF6cXV4ZmFrZWtleWJvZHkxMjM0NTY3ODkw\n-----END PRIVATE KEY-----")
PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7fakefakefake"
CANARIES = (FAKE_KEY, OPAQUE, OAUTH, SEALED, VAULT, PEM_BODY)
PROJECT_WORDS = "Objectif : présenter le budget 2027 au comité"


def seeded(tmp_path: Path) -> SB.BundleSources:
    sources, _env = profile(tmp_path)
    data, runtime = sources.data_root, sources.runtime_root
    with open(sources.config_dir / ".env", "a", encoding="utf-8") as env:
        env.write(f"INFOMANIAK_TOKEN={OPAQUE}\n")
    sealer = FakeSealer()
    (runtime / "control-center-settings.json").write_text(json.dumps({
        "agent_cli": "claude", "voice_stack": "openai_realtime",
        "credentials": [{"provider": "deepgram", "sealed": seal_value(SEALED, sealer), "hint": "dg-…kw9"}]}), encoding="utf-8")
    body = {"v": 1, "plugin_id": "circuit", "kind": "static", "static": {"api_token": VAULT}}
    leak = f"clé {FAKE_KEY} oauth {OAUTH} opaque {OPAQUE} scellée {SEALED} coffre {VAULT}\n{PEM}"
    with sqlite3.connect(data / "state" / "jarvis.sqlite3") as conn:
        conn.execute("INSERT INTO mcp_credentials(credential_ref,plugin_id,scheme,created_at,updated_at,blob) VALUES (?,?,?,?,?,?)",
                     ("cred_" + "0" * 32, "circuit", "dpapi-user-v1", "t", "t", sealer.seal(json.dumps(body).encode())))
        conn.execute("INSERT INTO conversations(id, updated_at, data) VALUES (?,?,?)",
                     ("conv1", "2026-10-27T10:00:00Z", json.dumps({"text": leak, "access_token": OAUTH, "note": PROJECT_WORDS})))
        conn.execute("INSERT INTO work_boards(board_id,status,created_at,updated_at,data) VALUES (?,?,?,?,?)",
                     (BOARD, "active", "t", "t", json.dumps({"title": "Budget 2027", "board_kind": "presentation"})))
        conn.execute("INSERT INTO jarvis_sessions(jarvis_session_id,status,started_at,active_board_id,data) VALUES (?,?,?,?,?)",
                     ("sess1", "open", "2026-10-27T09:00:00Z", BOARD, "{}"))
    conn.close()
    with sqlite3.connect(data / "state" / "scene.sqlite3") as scene:
        scene.execute("CREATE TABLE scene_objects (object_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, data TEXT NOT NULL)")
        scene.execute("INSERT INTO scene_objects VALUES ('o1', 1, ?)", (json.dumps({"label": f"note {FAKE_KEY}"}),))
    scene.close()
    memory = data / "boards" / BOARD / "memory"
    (memory / "documents" / "research").mkdir(parents=True)
    (memory / "summary.md").write_text(f"# Finalité\n{PROJECT_WORDS}\nclé collée : {FAKE_KEY}\n{PEM}\n", encoding="utf-8")
    (memory / "documents" / "research" / "sources.md").write_text(f"jeton {OPAQUE} et {SEALED}\n", encoding="utf-8")
    (memory / "documents" / "image.png").write_bytes(b"\x89PNG\x00\x01binary")
    (memory / "documents" / "huge.md").write_text("x" * (SNAP.MAX_MEMORY_FILE_BYTES + 10), encoding="utf-8")
    with open(runtime / "errors.jsonl", "a", encoding="utf-8") as errors:
        errors.write(json.dumps({"ts": "2026-10-27T10:05:00Z", "kind": "presentation.render.failed", "level": "error",
                                 "message": f"render failed: ffmpeg exit 1 (token {OPAQUE})", "data": {"code": "render_ffmpeg_failed"}}) + "\n")
    sources.credentials_sealer = sources.mcp_sealer = lambda: sealer
    sources.full = True
    sources.description = f"La vidéo ne s'exporte plus. Ma clé est {FAKE_KEY}"
    return sources


def zip_bytes(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


def assert_no_canary(blobs: dict[str, bytes] | str) -> None:
    items = {"prompt": blobs.encode("utf-8")} if isinstance(blobs, str) else blobs
    for name, content in items.items():
        for canary in CANARIES:
            assert canary.encode("utf-8") not in content, f"{canary[:10]}… in {name}"


# ------------------------------------------------------------------ contenu et canaris


def test_the_full_bundle_carries_masked_bases_board_memory_settings_and_a_manifest(tmp_path):
    sources = seeded(tmp_path)
    before = {p: p.read_bytes() for p in sources.data_root.rglob("*") if p.is_file()}
    path = SB.write_bundle(sources)
    files = zip_bytes(path)
    assert_no_canary(files)
    assert {"report.md", "manifest.json", "state/jarvis.sqlite3", "state/scene.sqlite3", "context/description.txt",
            "settings/control-center-settings.json", "board/board.json", "board/memory/summary.md",
            "board/memory/documents/research/sources.md"} <= set(files)
    assert PROJECT_WORDS in files["board/memory/summary.md"].decode("utf-8"), "consented project context is kept"
    assert "[secret masqué]" in files["board/memory/summary.md"].decode("utf-8")
    settings = json.loads(files["settings/control-center-settings.json"])
    assert "credentials" not in settings and settings["credentials_removed"] == 1 and settings["agent_cli"] == "claude"
    manifest = json.loads(files["manifest.json"])
    assert manifest["schema"] == SB.MANIFEST_SCHEMA and manifest["mode"] == "full"
    assert manifest["active_board"]["board_id"] == BOARD and manifest["active_board"]["title"] == "Budget 2027"
    by_path = {entry["path"]: entry for entry in manifest["files"]}
    assert by_path["board/memory/documents/image.png"]["status"] == "omitted"
    assert by_path["board/memory/documents/image.png"]["reason"] == "binary_or_not_utf8"
    assert by_path["board/memory/documents/huge.md"]["reason"] == "too_large"
    assert by_path["credential_vault"]["status"] == "excluded" and by_path["data/local_capabilities"]["status"] == "omitted"
    snapshot = json.loads(by_path["state/jarvis.sqlite3"]["reason"])
    assert snapshot["vault_rows_removed"] == 1 and snapshot["triggers_removed"] > 0
    assert by_path["report.md"]["status"] == "included"
    # The snapshot is a valid base, without the vault and with masked text.
    db = tmp_path / "snap.sqlite3"
    db.write_bytes(files["state/jarvis.sqlite3"])
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM mcp_credentials").fetchone()[0] == 0
        data = json.loads(conn.execute("SELECT data FROM conversations WHERE id='conv1'").fetchone()[0])
    conn.close()
    assert PROJECT_WORDS in data["note"] and data["access_token"] == "[secret masqué]"
    # Read-only on the profile: nothing changed, nothing created next to a base; only the zip in the support folder.
    assert {p: p.read_bytes() for p in sources.data_root.rglob("*") if p.is_file()} == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_the_report_prompt_never_carries_a_secret_and_the_ai_report_is_grounded(tmp_path):
    sources = seeded(tmp_path)
    seen: dict[str, str] = {}

    class Model:
        last_cost_usd = 0.0123

        async def complete(self, system: str, prompt: str, *, timeout_s: float) -> str:
            seen["prompt"] = system + prompt
            return (f"## Symptôme\nLa vidéo ne s'exporte plus [D].\n## Faits observés\n- `presentation.render.failed` [E{SR.MAX_ERRORS}].\n"
                    f"- `voice.crash_xyz` [E999].\n## Hypothèses\nHypothèse : ffmpeg (confiance moyenne) [E{SR.MAX_ERRORS}].\n"
                    "## Incertitudes\nAucune autre preuve.\n")

    work = tmp_path / "work"
    work.mkdir()
    collected = SB.collect_bundle(sources, work)
    result = asyncio.run(SR.generate_report(collected.evidence, Model(), redact=collected.redact, model_label="fake"))
    assert_no_canary(seen["prompt"])
    assert "presentation.render.failed" in seen["prompt"], "the recent error reaches the model"
    assert result.kind == "ai" and result.meta["cost_usd"] == 0.0123
    assert "voice.crash_xyz" in result.meta["unknown_mentions"] and "[E999]" in result.meta["unknown_mentions"]
    assert "presentation.render.failed" not in result.meta["unknown_mentions"]
    assert "**Attention**" in result.text and "`voice.crash_xyz`" in result.text
    assert "Rapport de diagnostic JARVIS (factuel, sans IA)" in result.text, "the factual annex always follows"
    assert_no_canary(result.text)


@pytest.mark.parametrize("behaviour, status", [("raise", "failed"), ("garbage", "invalid"), ("slow", "timeout")])
def test_a_failing_model_still_gives_a_factual_report(tmp_path, behaviour, status):
    sources = seeded(tmp_path)

    class Model:
        async def complete(self, system: str, prompt: str, *, timeout_s: float) -> str:
            if behaviour == "raise":
                raise RuntimeError("no CLI")
            if behaviour == "slow":
                await asyncio.sleep(5)
            return "hello"

    work = tmp_path / "w"
    work.mkdir()
    collected = SB.collect_bundle(sources, work)
    result = asyncio.run(SR.generate_report(collected.evidence, Model(), redact=collected.redact, timeout_s=0.2,
                                            model_label="fake"))
    assert result.kind == "factual" and result.meta["ai_status"] == status
    assert "presentation.render.failed" in result.text and "ne propose aucune cause" in result.text
    path = SB.write_archive(tmp_path / "out", collected, result.text, report_kind=result.kind, report_meta=result.meta)
    assert json.loads(zip_bytes(path)["manifest.json"])["report"]["ai_status"] == status


def test_the_factual_report_invents_nothing_on_an_empty_profile(tmp_path):
    evidence = SR.build_evidence({"bundle.json": b"{}"}, board=None, full=True)
    text = SR.factual_report(evidence, ai_status="unavailable")
    assert "Aucune erreur dans le journal" in text and "Aucune description fournie" in text
    assert SR.unknown_mentions("rien", SR._evidence_json(evidence)) == []


# ------------------------------------------------------------------ bases


def test_the_sqlite_snapshot_is_consistent_while_core_writes(tmp_path):
    base = tmp_path / "live.sqlite3"
    with sqlite3.connect(base) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, v TEXT)")
    conn.close()
    stop = threading.Event()

    def writer() -> None:
        w = sqlite3.connect(base, timeout=5)
        i = 0
        while not stop.is_set():
            with w:  # one transaction: a and b always move together
                w.execute("INSERT INTO a(v) VALUES (?)", (f"row {i} {FAKE_KEY}",))
                w.execute("INSERT INTO b(v) VALUES (?)", (f"row {i}",))
            i += 1
        w.close()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        time.sleep(0.2)
        for n in range(5):
            target = tmp_path / f"snap{n}.sqlite3"
            report = SNAP.snapshot_database(base, target, lambda text: text.replace(FAKE_KEY, "[secret masqué]"))
            with sqlite3.connect(target) as snap:
                a, b = (snap.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("a", "b"))
                assert a == b and a > 0, (a, b)
                assert snap.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            snap.close()
            assert FAKE_KEY.encode() not in target.read_bytes() and report["text_values_masked"] >= a
            assert not target.with_name(target.name + ".work").exists()
    finally:
        stop.set()
        thread.join()


def test_a_too_large_or_absent_base_is_omitted_and_said(tmp_path, monkeypatch):
    sources = seeded(tmp_path)
    monkeypatch.setattr(SNAP, "MAX_DATABASE_BYTES", 10)
    (sources.data_root / "state" / "scene.sqlite3").unlink(missing_ok=True)
    work = tmp_path / "w"
    work.mkdir()
    collected = SB.collect_bundle(sources, work)
    entries = {e.path: e for e in collected.manifest}
    assert entries["state/jarvis.sqlite3"].status == "omitted" and entries["state/jarvis.sqlite3"].reason.startswith("too_large:")
    assert entries["state/scene.sqlite3"].reason == "absent"
    assert "state/jarvis.sqlite3" not in collected.files and list(work.iterdir()) == []


def test_unique_values_that_collide_once_masked_stay_masked_and_distinct(tmp_path):
    base = tmp_path / "u.sqlite3"
    with sqlite3.connect(base) as conn:
        conn.execute("CREATE TABLE p(id INTEGER PRIMARY KEY, endpoint TEXT UNIQUE)")
        conn.executemany("INSERT INTO p(endpoint) VALUES (?)", [("a@example.com",), ("b@example.com",)])
    conn.close()
    from jarvis.domain.diagnostic_redaction import DiagnosticRedactor
    SNAP.snapshot_database(base, tmp_path / "s.sqlite3", DiagnosticRedactor({}).text)
    with sqlite3.connect(tmp_path / "s.sqlite3") as snap:
        rows = [row[0] for row in snap.execute("SELECT endpoint FROM p ORDER BY id")]
    snap.close()
    assert all(row.startswith("<email>") for row in rows) and len(set(rows)) == 2


# ------------------------------------------------------------------ confinement


def _junction(link: Path, target: Path) -> None:
    if sys.platform != "win32":
        os.symlink(target, link, target_is_directory=True)
        return
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def test_board_ids_that_try_to_leave_the_data_root_are_refused(tmp_path):
    sources = seeded(tmp_path)
    for bad in ("../state", "..", "a/b", "C:\\Windows", ""):
        files, entries = SNAP.board_memory(sources.data_root, bad, str)
        assert files == {} and entries[0].status == "refused" and entries[0].reason == "invalid_board_id", bad


def test_a_junction_is_never_followed_in_or_to_the_board_memory(tmp_path):
    sources = seeded(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(f"hors racine {FAKE_KEY}", encoding="utf-8")
    memory = sources.data_root / "boards" / BOARD / "memory"
    _junction(memory / "escape", outside)
    files, entries = SNAP.board_memory(sources.data_root, BOARD, str)
    assert not any("secret.md" in name for name in files)
    assert any(e.path.endswith("/escape") and e.status == "refused" and e.reason == "link_or_junction_not_followed" for e in entries)
    other = sources.data_root / "boards" / "board_jump"
    other.mkdir()
    _junction(other / "memory", outside)
    files, entries = SNAP.board_memory(sources.data_root, "board_jump", str)
    assert files == {} and entries[0].reason == "link_refused"


# ------------------------------------------------------------------ rétention


def test_retention_keeps_the_newest_bundles_and_sweeps_old_work_files(tmp_path):
    folder = tmp_path / "support"
    folder.mkdir()
    now = time.time()
    names = [f"jarvis-support-2026102{i}T100000Z.zip" for i in range(8)]
    for age, name in enumerate(reversed(names)):
        path = folder / name
        path.write_bytes(b"z")
        os.utime(path, (now - age * 3600, now - age * 3600))
    old = folder / "jarvis-support-20250101T000000Z.zip"
    old.write_bytes(b"z")
    os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    stale = folder / "jarvis-support-x.zip.tmp"
    stale.write_bytes(b"t")
    os.utime(stale, (now - 7200, now - 7200))
    fresh = folder / "jarvis-support-y.zip.tmp"
    fresh.write_bytes(b"t")
    keep = folder / "notes.txt"
    keep.write_text("mine", encoding="utf-8")
    removed = SB.prune_support_folder(folder, now=now)
    left = sorted(p.name for p in folder.iterdir())
    assert sorted(names[-5:]) == [n for n in left if n.startswith("jarvis-support-2026")]
    assert old.name in removed and stale.name in removed
    assert fresh.exists() and keep.exists()


# ------------------------------------------------------------------ envoi


def test_destination_comes_from_the_setting_then_the_environment_then_the_default():
    assert SS.resolve_destination({}, {}) == SS.DEFAULT_SUPPORT_EMAIL == "e.debazelaire@circoe.com"
    assert SS.resolve_destination({}, {"JARVIS_SUPPORT_EMAIL": "ops@example.org"}) == "ops@example.org"
    assert SS.resolve_destination({"support_email": "qa@example.org"}, {"JARVIS_SUPPORT_EMAIL": "ops@example.org"}) == "qa@example.org"
    assert SS.resolve_destination({"support_email": "not an address"}, {}) == SS.DEFAULT_SUPPORT_EMAIL


def test_the_support_address_literal_lives_in_one_place():
    root = Path(__file__).resolve().parents[2] / "jarvis"
    hits = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.suffix in (".py", ".js", ".html")
            and "e.debazelaire@circoe.com" in p.read_text(encoding="utf-8", errors="replace")]
    assert hits == ["runtime/support_send.py"]


def test_mapi_transport_outcomes():
    bundle = Path("jarvis-support-20261027T100000Z.zip")
    calls = []
    ok = SS.MapiTransport(api=lambda to, subject, body, path: calls.append((to, path)) or 0, client=lambda: "Outlook")
    assert ok.send(bundle, to="a@b.co", subject="s", body="b").status == "draft_opened" and calls == [("a@b.co", bundle)]
    with pytest.raises(SS.SupportSendError) as missing:
        SS.MapiTransport(api=lambda *a: 0, client=lambda: None).send(bundle, to="a@b.co", subject="s", body="b")
    assert missing.value.code == "support_mail_client_missing"
    with pytest.raises(SS.SupportSendError) as refused:
        SS.MapiTransport(api=lambda *a: 2, client=lambda: "Outlook").send(bundle, to="a@b.co", subject="s", body="b")
    assert refused.value.code == "support_mapi_failed" and "MAPI_E_FAILURE" in refused.value.detail
    with pytest.raises(SS.SupportSendError) as aborted:
        SS.MapiTransport(api=lambda *a: 1, client=lambda: "Outlook").send(bundle, to="a@b.co", subject="s", body="b")
    assert aborted.value.code == "support_send_cancelled"


class FailingTransport:
    name = "fake"

    def describe(self) -> dict:
        return {"name": "fake", "available": True, "label": "faux transport"}

    def send(self, bundle: Path, *, to: str, subject: str, body: str) -> SS.SendOutcome:
        raise SS.SupportSendError("support_mapi_failed", "La messagerie a refusé le brouillon.", "MAPISendMail = 2")


def service(tmp_path: Path, sources: SB.BundleSources, *, transport=None, model=None, settings=None) -> SupportReportService:
    store = settings if settings is not None else {}

    def update(apply) -> None:
        apply(store)

    async def board():
        return {"board_id": BOARD, "title": "Budget 2027", "board_kind": "presentation"}

    async def health():
        return {"items": [{"item_id": "brain", "state": "action_needed", "summary": "Connectez-vous à Claude."}]}

    def fresh() -> SB.BundleSources:
        sources.full = False  # the service sets full mode itself
        return sources

    return SupportReportService(runtime_root=sources.runtime_root, journal=RuntimeJournal(sources.runtime_root),
                                settings=lambda: store, update_settings=update, active_board=board, health=health,
                                model_factory=(lambda cwd: (model, "fake")) if model else None,
                                transport=transport or SS.OutboxTransport(sources.runtime_root / "support" / "outbox"),
                                sources_factory=fresh, environ=sources.environ)


def journal_kinds(sources: SB.BundleSources) -> list[str]:
    path = sources.runtime_root / "trace.jsonl"
    return [json.loads(line)["kind"] for line in path.read_text(encoding="utf-8").splitlines() if '"support.' in line]


def test_consent_is_required_and_a_created_bundle_is_sent_to_the_test_outbox(tmp_path):
    sources = seeded(tmp_path)
    svc = service(tmp_path, sources)
    with pytest.raises(SupportRouteError) as refused:
        asyncio.run(svc.create({"description": "x"}))
    assert refused.value.status == 400 and refused.value.code == "support_consent_required"
    preview = asyncio.run(svc.preview())
    assert preview["destination"] == SS.DEFAULT_SUPPORT_EMAIL and preview["active_board"]["title"] == "Budget 2027"
    assert {item["id"] for item in preview["included"]} >= {"state_databases", "board_memory", "logs", "settings"}
    assert preview["approx_bytes"] > 0 and preview["transport"]["name"] == "outbox"
    created = asyncio.run(svc.create({"consent": True, "description": f"Export bloqué {FAKE_KEY}"}))
    name = created["bundle"]["name"]
    assert created["bundle"]["report_kind"] == "factual" and created["bundle"]["ai_status"] == "unavailable"
    files = zip_bytes(svc.support_dir / name)
    assert_no_canary(files)
    assert json.loads(files["health/readiness.json"])["items"][0]["item_id"] == "brain"
    sent = asyncio.run(svc.send(name))
    assert sent["status"] == "delivered_to_outbox" and sent["destination"] == SS.DEFAULT_SUPPORT_EMAIL
    outbox = svc.support_dir / "outbox"
    assert (outbox / name).is_file() and "To: e.debazelaire@circoe.com" in (outbox / (Path(name).stem + ".eml.txt")).read_text(encoding="utf-8")
    kinds = journal_kinds(sources)
    assert "support.report.created" in kinds and "support.report.sent" in kinds
    assert not any(p.name.startswith(".work-") for p in svc.support_dir.iterdir()), "no work folder left"


def test_a_failed_send_keeps_the_bundle_and_says_why(tmp_path):
    sources = seeded(tmp_path)
    svc = service(tmp_path, sources, transport=FailingTransport())
    name = asyncio.run(svc.create({"consent": True}))["bundle"]["name"]
    with pytest.raises(SupportRouteError) as failed:
        asyncio.run(svc.send(name))
    assert failed.value.status == 502 and failed.value.code == "support_mapi_failed"
    assert "conservé" in str(failed.value) and (svc.support_dir / name).is_file()
    errors = [json.loads(line) for line in (sources.runtime_root / "errors.jsonl").read_text(encoding="utf-8").splitlines()]
    assert errors[-1]["kind"] == "support.report.send_failed" and errors[-1]["data"]["code"] == "support_mapi_failed"


def test_an_oversized_bundle_is_not_mailed_and_unknown_names_are_refused(tmp_path, monkeypatch):
    sources = seeded(tmp_path)
    svc = service(tmp_path, sources)
    name = asyncio.run(svc.create({"consent": True}))["bundle"]["name"]
    monkeypatch.setattr(SS, "MAX_SEND_BYTES", 10)
    with pytest.raises(SupportRouteError) as big:
        asyncio.run(svc.send(name))
    assert big.value.code == "support_bundle_too_large" and (svc.support_dir / name).is_file()
    for bad in ("../x.zip", "jarvis-support-x.zip", "jarvis-support-20261027T100000Z.zip"):
        with pytest.raises(SupportRouteError) as refused:
            svc.bundle_path(bad)
        assert refused.value.code in ("support_bundle_name_invalid", "support_bundle_missing")


def test_save_copies_into_the_export_root_without_overwriting(tmp_path):
    sources = seeded(tmp_path)
    export = tmp_path / "Documents" / "Jarvis"
    export.parent.mkdir()
    sources.environ = {**sources.environ, "JARVIS_EXPORT_ROOT": str(export)}
    svc = service(tmp_path, sources)
    name = asyncio.run(svc.create({"consent": True}))["bundle"]["name"]
    first = asyncio.run(svc.save(name))
    assert first["status"] == "saved" and (export / first["file_name"]).read_bytes() == (svc.support_dir / name).read_bytes()


def test_the_destination_setting_is_validated_and_reset(tmp_path):
    sources = seeded(tmp_path)
    store: dict = {}
    svc = service(tmp_path, sources, settings=store)
    with pytest.raises(SupportRouteError):
        svc.set_destination({"support_email": "pas une adresse"})
    assert svc.set_destination({"support_email": "qa@example.org"})["destination"] == "qa@example.org"
    assert store["support_email"] == "qa@example.org"
    assert svc.set_destination({"support_email": ""})["destination"] == SS.DEFAULT_SUPPORT_EMAIL and "support_email" not in store


def test_the_service_writes_an_ai_report_when_a_model_answers(tmp_path):
    sources = seeded(tmp_path)

    class Model:
        last_cost_usd = 0.02

        async def complete(self, system: str, prompt: str, *, timeout_s: float) -> str:
            return f"## Symptôme\nExport [D].\n## Faits observés\n- `presentation.render.failed` [E{SR.MAX_ERRORS}].\n## Hypothèses\nAucune.\n"

    svc = service(tmp_path, sources, model=Model())
    created = asyncio.run(svc.create({"consent": True}))
    assert created["bundle"]["report_kind"] == "ai" and created["bundle"]["unknown_mentions"] == []
    report = zip_bytes(svc.support_dir / created["bundle"]["name"])["report.md"].decode("utf-8")
    assert report.startswith("# Rapport de diagnostic JARVIS\n") and f"[E{SR.MAX_ERRORS}]" in report


def test_the_cli_full_flag_is_declared():
    from jarvis.app import _parser
    args = _parser().parse_args(["support-bundle", "--full", "--description", "x"])
    assert args.full is True and args.description == "x"


def test_the_support_routes_are_guarded_like_the_product_routes():
    from jarvis.runtime import control_center as CC
    assert CC.SUPPORT_ROUTE_PREFIX in CC.READ_GUARDED_ROUTES
    assert subprocess.run([sys.executable, "-c", "import jarvis.runtime.support_routes"], check=False).returncode == 0
