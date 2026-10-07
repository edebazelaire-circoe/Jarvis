"""Reprise au demarrage : la variante active, les restes d'ecritures et les documents malformes (jarvis-interactive-presentation-studio, Slice 08).

Le magasin est ecrit par le vrai service puis abime a la main (tronque, mauvaise version de schema, variante manquante,
fichier vide, octets invalides, temporaire orphelin plus recent) : `start()` ne leve jamais, le bilan `last_recovery` dit
quoi est illisible avec son code, la trace `recovery_failed` est en `error` (visualiseur d'erreurs), une lecture suivante
leve le meme code type, **rien n'est reecrit** et aucun contenu plus ancien ou temporaire n'est jamais adopte en silence.
Contrat : `docs/presentation-studio.md` > *Persistence and undo contract*.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C

SCENE = {"scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}, "title": "Ouverture"}


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def of(self, kind):
        return [(level, data) for k, level, data in self.rows if k == kind]


def service(root: Path, sink: Sink | None = None) -> PresentationStudioService:
    return PresentationStudioService(FilePresentationStudioStore(root), diagnostics=sink)


async def seed(root: Path, title: str = "Atelier", *, revisions: int = 2) -> tuple[str, str, Path]:
    """Une Presentation saine dont la variante active a `revisions` revisions (donc un historique de fichiers remplaces)."""

    studio = service(root)
    view = await studio.create({"title": title})
    pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
    for index in range(revisions):
        variant = await studio.get_variant(pid, vid)
        await studio.save_variant(pid, vid, {
            "expected_revision": variant.revision, "title": f"v{index}", "scenes": [{**SCENE, "title": f"R{index}"}],
            "art_direction_id": None, "score_id": None})
    return pid, vid, root / "presentations" / pid


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_a_healthy_store_is_reloaded_and_the_report_says_so(tmp_path):
    pid, vid, _ = await seed(tmp_path)
    await seed(tmp_path, "Deuxieme")
    sink = Sink()
    studio = service(tmp_path, sink)
    assert studio.last_recovery is None  # before start: nothing claimed
    await studio.start()
    recovery = studio.last_recovery
    assert (recovery.presentations, recovery.active_loaded, recovery.unreadable, recovery.swept) == (2, 2, (), 0)
    assert recovery.to_dict()["unreadable"] == []
    ((level, data),) = sink.of("core.presentation_studio.recovered")
    assert level == "info" and data == {"presentations": 2, "active_loaded": 2, "unreadable": 0, "swept": 0, "sweep_failed": 0}
    assert (await studio.get_variant(pid, vid)).scenes[0].title == "R1"  # the latest revision, from disk


async def test_an_empty_store_is_a_first_run_not_an_error(tmp_path):
    sink = Sink()
    studio = service(tmp_path, sink)
    await studio.start()
    assert studio.last_recovery.presentations == 0 and studio.last_recovery.unreadable == ()
    assert not [r for r in sink.rows if r[1] == "error"]


MALFORMED = {
    "truncated": lambda text: text[: len(text) // 2],
    "empty": lambda text: "",
    "not-json": lambda text: "<<<not json>>>",
    "wrong-top-level-type": lambda text: "[1, 2, 3]",
    "string-schema-version": lambda text: text.replace('"schema_version": 2', '"schema_version": "2"'),
    "zero-schema-version": lambda text: text.replace('"schema_version": 2', '"schema_version": 0'),
    "wrong-schema-name": lambda text: text.replace("jarvis.presentation_studio.variant", "something.else"),
    "missing-scenes": lambda text: json.dumps({k: v for k, v in json.loads(text).items() if k != "scenes"}),
    "other-variant-id": lambda text: json.dumps({**json.loads(text), "variant_id": "psv_" + "9" * 32}),
}


@pytest.mark.parametrize("name", sorted(MALFORMED))
async def test_a_malformed_active_variant_is_a_typed_visible_error_and_never_replaced_by_older_content(tmp_path, name):
    pid, vid, folder = await seed(tmp_path)
    other_pid, other_vid, _ = await seed(tmp_path, "Saine")
    path = folder / "variants" / f"{vid}.json"
    path.write_text(MALFORMED[name](path.read_text(encoding="utf-8")), encoding="utf-8")
    before = sha(path)
    sink = Sink()
    studio = service(tmp_path, sink)
    await studio.start()  # never raises
    recovery = studio.last_recovery
    assert recovery.presentations == 2 and recovery.active_loaded == 1
    (row,) = recovery.unreadable
    assert row["presentation_id"] == pid and row["variant_id"] == vid
    assert row["code"] == C.CORRUPT_DOCUMENT.value and row["message"]
    ((level, data),) = sink.of("core.presentation_studio.recovery_failed")
    assert level == "error" and data == {"presentation_id": pid, "variant_id": vid, "code": C.CORRUPT_DOCUMENT.value}
    with pytest.raises(PresentationStudioError) as caught:
        await studio.get_variant(pid, vid)  # the same typed code at the next read: no silent fallback
    assert caught.value.code is C.CORRUPT_DOCUMENT
    assert (await studio.get_variant(other_pid, other_vid)).scenes[0].title == "R1"  # the others are untouched
    listing = await studio.list_presentations()  # the listing reads manifests only: the variant fault is the recovery report's
    assert len(listing.presentations) == 2 and listing.problems == ()
    assert sha(path) == before  # recovery writes nothing, and never repairs by guessing


async def test_a_variant_written_by_a_newer_jarvis_is_refused_with_its_own_code_and_left_byte_for_byte(tmp_path):
    pid, vid, folder = await seed(tmp_path)
    path = folder / "variants" / f"{vid}.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"schema_version": 2', '"schema_version": 99'), encoding="utf-8")
    before = sha(path)
    studio = service(tmp_path, sink := Sink())
    await studio.start()
    (row,) = studio.last_recovery.unreadable
    assert row["code"] == C.UNSUPPORTED_SCHEMA_VERSION.value
    assert [d["code"] for _, d in sink.of("core.presentation_studio.recovery_failed")] == [C.UNSUPPORTED_SCHEMA_VERSION.value]
    with pytest.raises(PresentationStudioError) as caught:
        await studio.save_variant(pid, vid, {"expected_revision": 1, "title": "x", "scenes": [], "art_direction_id": None,
                                             "score_id": None})
    assert caught.value.code is C.UNSUPPORTED_SCHEMA_VERSION and sha(path) == before  # never overwritten


async def test_a_missing_active_variant_file_is_a_torn_state_not_an_unknown_variant(tmp_path):
    pid, vid, folder = await seed(tmp_path)
    (folder / "variants" / f"{vid}.json").unlink()
    studio = service(tmp_path, sink := Sink())
    await studio.start()
    (row,) = studio.last_recovery.unreadable
    assert row["code"] == C.CORRUPT_DOCUMENT.value and row["variant_id"] == vid
    assert sink.of("core.presentation_studio.recovery_failed")[0][0] == "error"


async def test_a_manifest_that_is_truncated_or_absent_is_reported_with_its_presentation(tmp_path):
    pid, vid, folder = await seed(tmp_path)
    manifest = folder / "presentation.json"
    manifest.write_text(manifest.read_text(encoding="utf-8")[:40], encoding="utf-8")
    studio = service(tmp_path)
    await studio.start()
    (row,) = studio.last_recovery.unreadable
    assert row["presentation_id"] == pid and row["code"] == C.CORRUPT_DOCUMENT.value
    manifest.unlink()
    again = service(tmp_path)
    await again.start()
    assert again.last_recovery.unreadable[0]["code"] == C.CORRUPT_DOCUMENT.value  # "a folder without manifest is a torn state"


async def test_an_orphan_temporary_is_swept_and_never_adopted_even_when_it_is_newer_and_valid(tmp_path):
    pid, vid, folder = await seed(tmp_path)
    path = folder / "variants" / f"{vid}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    newer = {**stored, "revision": stored["revision"] + 5, "title": "FROM-THE-TEMPORARY"}
    orphan = folder / "variants" / f"{vid}.json.0123abcd.tmp"
    orphan.write_text(json.dumps(newer), encoding="utf-8")
    other = folder / "presentation.json.89abcdef.tmp"
    other.write_text("half a manifest", encoding="utf-8")
    stranger = folder / "variants" / "notes.txt"  # not ours: never touched
    stranger.write_text("keep me", encoding="utf-8")
    before = sha(path)
    studio = service(tmp_path, sink := Sink())
    await studio.start()
    assert studio.last_recovery.swept == 2 and studio.last_recovery.sweep_failed == 0 and studio.last_recovery.unreadable == ()
    assert not orphan.exists() and not other.exists() and stranger.read_text(encoding="utf-8") == "keep me"
    variant = await studio.get_variant(pid, vid)
    assert variant.title == "v1" and variant.revision == stored["revision"] and sha(path) == before
    assert "FROM-THE-TEMPORARY" not in path.read_text(encoding="utf-8")
    ((level, data),) = sink.of("core.presentation_studio.swept")
    assert level == "info" and data["count"] == 2


async def test_leftover_staging_of_a_killed_creation_is_swept_and_never_listed(tmp_path):
    pid, vid, _ = await seed(tmp_path)
    staging = tmp_path / "presentations" / ".staging-0123456789abcdef"
    (staging / "variants").mkdir(parents=True)
    (staging / "variants" / f"{vid}.json").write_text("{}", encoding="utf-8")
    studio = service(tmp_path)
    await studio.start()
    assert not staging.exists() and studio.last_recovery.swept == 1
    assert [p["presentation_id"] for p in (await studio.list_presentations()).presentations] == [pid]


async def test_a_backup_or_an_older_copy_beside_the_document_is_never_used(tmp_path):
    pid, vid, folder = await seed(tmp_path)
    path = folder / "variants" / f"{vid}.json"
    older = json.loads(path.read_text(encoding="utf-8"))
    older.update(revision=1, title="OLDER-COPY")
    (folder / "variants" / f"{vid}.json.bak").write_text(json.dumps(older), encoding="utf-8")
    path.write_text("not json", encoding="utf-8")
    studio = service(tmp_path)
    await studio.start()
    assert studio.last_recovery.unreadable[0]["code"] == C.CORRUPT_DOCUMENT.value
    with pytest.raises(PresentationStudioError):
        await studio.get_variant(pid, vid)  # the .bak is not a fallback; restoring it is a human decision (OPERATIONS.md)


async def test_a_failing_store_never_stops_start_and_says_why(tmp_path):
    class Broken(FilePresentationStudioStore):
        def scan(self):
            raise PermissionError("denied (injected)")

    sink = Sink()
    studio = PresentationStudioService(Broken(tmp_path), diagnostics=sink)
    await studio.start()  # never raises
    assert studio.last_recovery is None
    ((level, data),) = sink.of("core.presentation_studio.recovery_failed")
    assert level == "error" and "PermissionError" in data["error"] or "denied" in data["error"]
    assert sink.of("core.presentation_studio.started")
