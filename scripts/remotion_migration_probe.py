"""Migration réelle d'une racine de données d'AVANT la tâche Remotion (Slice 22 de jarvis-remotion-presentation-integration).

    python scripts/remotion_migration_probe.py --work-dir <dossier jetable> --evidence <fichier.json>

Construit deux racines de données jetables « d'avant » à partir des fixtures committées (jamais `~/.jarvis`, jamais le JARVIS vivant) :
- `v7` : `jarvis.sqlite3` au schéma 7 (`tests/fixtures/sqlite_state/state_v7_real_shaped.sql`, 2 Sessions, 4 Boards, 3 Artifacts) ;
- `v8` : la même base déjà au schéma 8 (la version que livraient `main` et ce handoff) ;
et dans chacune : `scene.sqlite3` au schéma 1, quatre Presentations (manifeste v1 / v2, variantes v1 à v4, scènes HTML), une bibliothèque de
prefabs avec un prefab HTML utilisateur. Puis lance un VRAI Core isolé (`jarvis.app._run_core_v2`, ports libres, comme le fait le harnais du
Studio) sur chaque racine et constate : migrations appliquées ou non, sauvegardes `.bak` (CLAUDE.md), lignes conservées, empreintes des fichiers
de Presentations avant/après lecture et lecture, moteur lu (`slidecar`), lecture jouée (Slidecar) sans conversion, création d'un document neuf
(`remotion`) refusée à la lecture faute de runtime (aucun repli), arrêt propre. Enfin, ce que fait un build D'AVANT (`main` de7b9c59, extrait
de git dans un dossier jetable) de la racine laissée par le nouveau : l'énoncé honnête du retour arrière.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import asyncio
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIX = ROOT / "tests" / "fixtures"
OLD_COMMIT = "de7b9c59"
PIDS = {1: "pst_00000000000000000000000000000001", 2: "pst_00000000000000000000000000000002",
        3: "pst_00000000000000000000000000000003", 4: "pst_00000000000000000000000000000004"}
PARENT, CHILD = "psv_00000000000000000000000000000001", "psv_00000000000000000000000000000002"


def load_harness():
    spec = importlib.util.spec_from_file_location("studio_harness", ROOT / "scripts" / "remotion_studio_harness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def rows(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: conn.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()


def version(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT version FROM schema_version").fetchone()[0]
    finally:
        conn.close()


async def init_scene(path: Path) -> None:
    from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
    repository = SQLiteSceneRepository(path)
    await repository.initialize()
    await repository.close()


async def init_state(path: Path) -> None:
    from jarvis.adapters.sqlite_state import SQLiteStateRepository
    repository = SQLiteStateRepository(path)
    await repository.initialize()
    await repository.close()


def build_pre_task_root(root: Path, state_version: int) -> None:
    """Une racine telle qu'un PC l'avait avant la tâche : bases, Presentations HTML, bibliothèque de prefabs."""

    from tests.fakes.prefabs import install_version
    state = root / "state"
    state.mkdir(parents=True)
    conn = sqlite3.connect(state / "jarvis.sqlite3")
    conn.executescript((FIX / "sqlite_state" / "state_v7_real_shaped.sql").read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    assert version(state / "jarvis.sqlite3") == 7
    if state_version == 8:  # la base migrée par le code précédent : le .bak de cette étape n'est pas celui qu'on mesure
        asyncio.run(init_state(state / "jarvis.sqlite3"))
        for bak in state.glob("*.bak"):
            bak.unlink()
    asyncio.run(init_scene(state / "scene.sqlite3"))
    install_version(root / "prefabs", "lab.counter", 1)  # un prefab HTML utilisateur, publié
    (root / "history").mkdir()
    (root / "history" / "2026-10-07.jsonl").write_text('{"turn": 1, "text": "synthetic"}\n', encoding="utf-8")
    ps = FIX / "presentation_studio"
    layouts = {1: ("presentation.v1.json", "variant.v1.json"), 2: ("presentation.v2.json", "variant.v2.json"),
               3: ("presentation.v2.json", "variant.v3.json"), 4: ("presentation.v2.json", "variant.v4.json")}
    for number, (manifest_name, variant_name) in layouts.items():
        pid = PIDS[number]
        folder = root / "presentations" / pid
        (folder / "variants").mkdir(parents=True)
        manifest = json.loads((ps / manifest_name).read_text(encoding="utf-8"))
        manifest["presentation_id"] = pid
        manifest["title"] = f"Bilan {number}"
        parent = json.loads((ps / "variant.parent.v1.json").read_text(encoding="utf-8"))
        child = json.loads((ps / variant_name).read_text(encoding="utf-8"))
        for variant in (parent, child):
            variant["presentation_id"] = pid
        # des scènes HTML qui existent vraiment dans la bibliothèque : une du prefab utilisateur, une du prefab de base livré
        child["scenes"][0]["prefab"] = {"id": "lab.counter", "version": 1}
        child["scenes"][1]["prefab"] = {"id": "jarvis.window", "version": 1}
        child["scenes"][0]["props"], child["scenes"][0]["data"] = {"label": "Total"}, {"count": 3}
        child["art_direction_id"] = "psd_000000000001"
        art = json.loads((ps / "art_direction.v1.json").read_text(encoding="utf-8"))
        art["presentation_id"], art["variant_id"] = pid, child["variant_id"]
        (folder / "art_directions").mkdir()
        (folder / "art_directions" / "psd_000000000001.json").write_text(json.dumps(art, indent=2, ensure_ascii=False), encoding="utf-8")
        child["score_id"] = "psr_000000000001"
        score = {"schema": "jarvis.presentation_studio.score", "schema_version": 1, "score_id": "psr_000000000001", "presentation_id": pid,
                 "variant_id": child["variant_id"], "start_item_id": "psi_000000000001", "cues": [], "sequences": [], "recovery_points": [],
                 "revision": 1, "created_at": "2026-10-07T09:00:00.000000Z", "updated_at": "2026-10-07T09:00:00.000000Z", "items": [
                     {"item_id": f"psi_00000000000{i}", "scene_id": f"pss_00000000000{i}", "presenter": "user", "kind": "speech", "label": "", "text": "",
                      "note": f"scene {i}", "cue_id": None, "visual": [{"kind": "scene_goto", "scene_id": f"pss_00000000000{i}"}], "motion": [],
                      "target_duration_ms": None, "timing": "soft", "interruption": "allow", "recovery": "continue_item", "recovery_point_id": None,
                      "next_item_id": "psi_000000000002" if i == 1 else None, "loop": None} for i in (1, 2)]}
        (folder / "scores").mkdir()
        (folder / "scores" / "psr_000000000001.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
        (folder / "presentation.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        for variant in (parent, child):
            (folder / "variants" / f"{variant['variant_id']}.json").write_text(json.dumps(variant, indent=2, ensure_ascii=False), encoding="utf-8")


def run_core(work: Path, harness, label: str, checks: dict) -> dict:
    """Démarre un Core isolé sur `work/root`, lit et joue les Presentations d'avant, l'arrête proprement."""

    core = harness.IsolatedCore(work)
    out: dict = {"label": label}
    core.start()
    try:
        status, listed = core.call("GET", "/v1/presentation-studio/presentations")
        out["list_status"] = status
        out["listed"] = [{"id": p["presentation_id"][-2:], "engine": p.get("engine"), "schema": p.get("schema_version")} for p in listed.get("presentations", [])]
        out["list_problems"] = listed.get("problems", [])
        views = {}
        for number, pid in PIDS.items():
            status, view = core.call("GET", f"/v1/presentation-studio/presentations/{pid}")
            views[number] = (status, view)
        out["get_status"] = {n: s for n, (s, _) in views.items()}
        status, engine = core.call("GET", "/v1/presentation-studio/engine")
        out["engine_overview"] = {"default_engine": engine.get("default_engine"), "remotion_ready": (engine.get("engines", {}).get("remotion") or {}).get("ready"),
                                  "remotion_reason": (engine.get("engines", {}).get("remotion") or {}).get("reason"),
                                  "slidecar_used_total": engine.get("slidecar", {}).get("total")}
        # un document d'avant se JOUE (Slidecar) : rien n'est converti
        status, started = core.call("POST", "/v1/presentation-studio/playback/start", {"actor": "user", "presentation_id": PIDS[4], "role": "user_presenter"})
        out["legacy_play"] = {"status": status, "phase": (started.get("state") or {}).get("phase"), "error": started.get("error")}
        status, snapshot = core.call("GET", "/v1/scene/snapshot")
        stage = [o for o in snapshot.get("snapshot", {}).get("objects", []) if str(o.get("object_id", "")).startswith("studio-stage-")]
        out["legacy_stage_objects"] = len(stage)
        out["legacy_stage_prefab"] = (stage[0].get("payload", {}).get("prefab", {}) or {}).get("id") if stage else None
        core.call("POST", "/v1/presentation-studio/playback/stop", {"actor": "user"})
        # un document NEUF : Remotion par défaut, refusé à la lecture sans runtime (jamais rejoué en Slidecar)
        status, created = core.call("POST", "/v1/presentation-studio/presentations", {"title": "Neuf"})
        out["new_document"] = {"status": status, "engine": (created.get("presentation") or {}).get("engine")}
        new_id = (created.get("presentation") or {}).get("presentation_id")
        status, refused = core.call("POST", "/v1/presentation-studio/playback/start", {"actor": "user", "presentation_id": new_id, "role": "user_presenter"})
        out["new_document_play"] = {"status": status, "code": (refused.get("error") or {}).get("code")}
    finally:
        out["clean_stop"] = core.stop()
        out["core_log_tail"] = (work / "core.log").read_text(encoding="utf-8", errors="replace")[-600:] if (work / "core.log").exists() else ""
    return out


async def add_new_kind_artifacts(db: Path) -> None:
    """Dans la COPIE, une ligne de chaque nature d'Artifact que ce handoff ajoute, écrite par le code NOUVEAU (ce que ferait un gel et un rendu)."""

    from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
    from jarvis.adapters.sqlite_state import SQLiteStateRepository
    from jarvis.domain.artifacts import ArtifactKind, new_artifact
    state = SQLiteStateRepository(db)
    await state.initialize()
    repository = SQLiteArtifactRepository(state)
    now = datetime.now(timezone.utc)
    for kind in (ArtifactKind.SCREENSHOT, ArtifactKind.PRESENTATION_SNAPSHOT, ArtifactKind.PRESENTATION_VIDEO, ArtifactKind.PRESENTATION_STILL,
                 ArtifactKind.PRESENTATION_PDF):
        await repository.create_artifact(new_artifact(kind=kind, source="migration-probe", now=now))
    await state.close()


def old_build_checks(work: Path, left_by_new: Path, saved_variant_id: str) -> dict:
    """Ce que fait le build D'AVANT (`main` de7b9c59, extrait de git) d'une racine laissée par le nouveau. Lecture seule sur une COPIE."""

    old = work / "old-build"
    shutil.rmtree(old, ignore_errors=True)
    old.mkdir(parents=True)
    tar_path = work / "old-jarvis.tar"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "-o", str(tar_path), OLD_COMMIT, "jarvis"], check=True)
    with tarfile.open(tar_path) as tar:
        tar.extractall(old, filter="data")
    copy = work / "old-copy"
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(left_by_new, copy, ignore=shutil.ignore_patterns("local_capabilities"))
    asyncio.run(add_new_kind_artifacts(copy / "state" / "jarvis.sqlite3"))
    code = r"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import jarvis
assert Path(jarvis.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()), jarvis.__file__
root = Path(sys.argv[2])
out = {"jarvis_from": str(Path(jarvis.__file__).resolve().parent.parent.name)}
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.domain.presentation_studio import parse_presentation, parse_variant
store = FilePresentationStudioStore(root)
rows = {}
async def main():
    for number in (1, 2, 3, 4):
        pid = "pst_0000000000000000000000000000000%d" % number
        for name, reader in (("manifest", lambda: parse_presentation(json.loads(store.read_manifest(pid)))),
                             ("variant", lambda: parse_variant(json.loads(store.read_variant(pid, sys.argv[3]))))):
            try:
                reader()
                rows.setdefault("P%d" % number, {})[name] = "read"
            except Exception as exc:
                rows.setdefault("P%d" % number, {})[name] = type(exc).__name__ + ": " + str(exc)[:140]
    from jarvis.adapters.sqlite_state import SQLiteStateRepository
    repo = SQLiteStateRepository(root / "state" / "jarvis.sqlite3")
    try:
        await repo.initialize()
        rows["state"] = {"open": "ok"}
        from jarvis.adapters.sqlite_artifacts import SQLiteArtifactRepository
        from jarvis.domain.artifacts import ArtifactQuery
        try:
            page = await SQLiteArtifactRepository(repo).query_artifacts(ArtifactQuery())
            rows["state"]["query_artifacts"] = "read %d" % len(page.items)
        except Exception as exc:
            rows["state"]["query_artifacts"] = type(exc).__name__ + ": " + str(exc)[:160]
    except Exception as exc:
        rows["state"] = {"open": type(exc).__name__ + ": " + str(exc)[:200]}
    finally:
        try:
            await repo.close()
        except Exception:
            pass
asyncio.run(main())
out["rows"] = rows
print(json.dumps(out))
"""
    done = subprocess.run([sys.executable, "-c", code, str(old), str(copy), saved_variant_id], capture_output=True, text=True, timeout=120, cwd=str(old), check=False)
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (done.stderr or done.stdout)[-600:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    work_root = Path(args.work_dir)
    if ".jarvis" in work_root.parts:
        raise SystemExit("refusing to work under ~/.jarvis")
    shutil.rmtree(work_root, ignore_errors=True)
    harness = load_harness()
    report: dict = {"head": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip(),
                    "when": datetime.now(timezone.utc).isoformat(timespec="seconds"), "old_build": OLD_COMMIT, "roots": {}}
    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = None) -> None:
        print(("PASS " if ok else "FAIL ") + name, "" if ok else detail)
        report.setdefault("checks", {})[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(name)

    for state_version in (7, 8):
        label = f"v{state_version}"
        work = work_root / label
        root = work / "root"
        build_pre_task_root(root, state_version)
        before_presentations = tree_hashes(root / "presentations")
        before_prefabs = tree_hashes(root / "prefabs")
        db_before = rows(root / "state" / "jarvis.sqlite3")
        scene_before_hash = sha(root / "state" / "scene.sqlite3")
        entry = {"state_version_before": version(root / "state" / "jarvis.sqlite3"), "scene_version_before": version(root / "state" / "scene.sqlite3"),
                 "rows_before": db_before, "presentation_files": len(before_presentations)}
        entry["core"] = run_core(work, harness, label, report)
        state_dir = root / "state"
        entry["state_version_after"] = version(state_dir / "jarvis.sqlite3")
        entry["scene_version_after"] = version(state_dir / "scene.sqlite3")
        entry["backups"] = sorted(p.name for p in state_dir.glob("*.bak"))
        entry["rows_after"] = rows(state_dir / "jarvis.sqlite3")
        after_presentations = tree_hashes(root / "presentations")
        entry["presentation_files_changed"] = sorted(k for k in before_presentations if before_presentations[k] != after_presentations.get(k))
        entry["presentation_files_added"] = sorted(k for k in after_presentations if k not in before_presentations
                                                   and k.split("/")[0] in PIDS.values())
        entry["new_documents_created_by_the_probe"] = sorted({k.split("/")[0] for k in after_presentations if k.split("/")[0] not in PIDS.values()})
        entry["prefab_files_changed"] = sorted(k for k, v in before_prefabs.items() if tree_hashes(root / "prefabs").get(k) != v)
        report["roots"][label] = entry
        core = entry["core"]
        check(f"{label}: Core started on the pre-task root and stopped cleanly", core["list_status"] == 200 and core["clean_stop"], core)
        check(f"{label}: state database is at schema 8 after start", entry["state_version_after"] == 8, entry["state_version_after"])
        check(f"{label}: scene database stays at schema 1 (no migration, no backup)", entry["scene_version_after"] == 1 and not [b for b in entry["backups"] if "scene" in b], entry)
        if state_version == 7:
            check("v7: the migration made exactly the documented backup jarvis.sqlite3.v7.bak", entry["backups"] == ["jarvis.sqlite3.v7.bak"], entry["backups"])
            backup = state_dir / "jarvis.sqlite3.v7.bak"
            check("v7: the backup holds the OLD schema (7) and the old row counts", version(backup) == 7 and rows(backup) == db_before, version(backup))
        else:
            check("v8: no migration, no backup", entry["backups"] == [], entry["backups"])
        check(f"{label}: every pre-task row survived the migration", all(entry["rows_after"].get(t, -1) >= n for t, n in db_before.items()),
              {t: (n, entry["rows_after"].get(t)) for t, n in db_before.items() if entry["rows_after"].get(t, -1) < n})
        check(f"{label}: four legacy presentations are listed and read as slidecar", sorted(p["engine"] for p in core["listed"]) == ["slidecar"] * 4 + ["remotion"] * 0 or
              [p["engine"] for p in core["listed"] if p["id"] in ("01", "02", "03", "04")] == ["slidecar"] * 4, core["listed"])
        check(f"{label}: no presentation file was rewritten or added by reading and playing them", not entry["presentation_files_changed"] and not [
            f for f in entry["presentation_files_added"] if not f.endswith(".bak")], (entry["presentation_files_changed"], entry["presentation_files_added"]))
        check(f"{label}: the user prefab library is byte-identical", not entry["prefab_files_changed"], entry["prefab_files_changed"])
        check(f"{label}: a legacy presentation still PLAYS (as Slidecar: an HTML prefab on the stage)", core["legacy_play"]["status"] == 200 and core["legacy_stage_objects"] == 1 and
              core["legacy_stage_prefab"], core["legacy_play"])
        check(f"{label}: a brand-new document is Remotion and is refused (typed, no fallback) without a runtime",
              core["new_document"]["engine"] == "remotion" and core["new_document_play"]["status"] == 409 and
              core["new_document_play"]["code"] == "presentation_studio_engine_unavailable", core["new_document_play"])
        check(f"{label}: the Slidecar ledger is read before the play (0): reading legacy documents is not a use", core["engine_overview"]["slidecar_used_total"] == 0, core["engine_overview"])

    # rollback statement, measured: what the build BEFORE the task does with a root the new build has touched
    left = work_root / "v7" / "root"
    pid = PIDS[4]
    # a first SAVE by the new build rewrites the document (manifest v3, variant v5): do it through the real Core, then show the old reader
    core = harness.IsolatedCore(work_root / "v7")
    core.start()
    try:
        status, view = core.call("GET", f"/v1/presentation-studio/presentations/{pid}")
        variant = view["variants"][0]
        status, saved = core.call("PUT", f"/v1/presentation-studio/presentations/{pid}/variants/{variant['variant_id']}", {
            "expected_revision": variant["revision"], "title": variant["title"] + " (édité)", "scenes": variant["scenes"],
            "art_direction_id": variant.get("art_direction_id"), "score_id": variant.get("score_id")})
        p_status, _ = core.call("PUT", f"/v1/presentation-studio/presentations/{pid}", {
            "expected_revision": view["presentation"]["revision"], "title": view["presentation"]["title"] + " (édité)",
            "active_variant_id": view["presentation"]["active_variant_id"], "resources": view["presentation"].get("resources", [])})
        report["first_save_by_new_build"] = {"saved_variant_id": variant["variant_id"], "variant_status": status, "presentation_status": p_status, "variant_schema_version_on_disk": json.loads(
            (left / "presentations" / pid / "variants" / f"{variant['variant_id']}.json").read_text(encoding="utf-8")).get("schema_version"),
            "presentation_schema_version_on_disk": json.loads((left / "presentations" / pid / "presentation.json").read_text(encoding="utf-8")).get("schema_version")}
    finally:
        core.stop()
    report["old_build_on_the_root_left_by_the_new_one"] = old_build_checks(work_root, left, report["first_save_by_new_build"]["saved_variant_id"])
    report["saved_document_backups"] = sorted(str(p.relative_to(left / "presentations" / pid)).replace("\\", "/") for p in (left / "presentations" / pid).rglob("*.bak"))
    old = report["old_build_on_the_root_left_by_the_new_one"].get("rows", {})
    report["rollback_statement"] = {
        "documents_saved_by_the_new_build_are_refused_by_the_old_build": any("future" in str(v).lower() or "Error" in str(v) for v in old.get("P4", {}).values()),
        "untouched_documents_still_read_by_the_old_build": all(old.get(f"P{n}", {}).get("manifest") == "read" for n in (1, 2, 3)),
        "old_build_on_a_database_with_the_new_artifact_kinds": old.get("state", {})}
    report["verdict"] = "PASSED" if not failures else "FAILED"
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(report["verdict"], f"({len(report['checks']) - len(failures)}/{len(report['checks'])} checks)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
