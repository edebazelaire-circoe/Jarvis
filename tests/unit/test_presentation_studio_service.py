"""Service Core des Presentations (jarvis-interactive-presentation-studio, Slice 02).

Vrai magasin de fichiers sous `tmp_path` : créer, charger, lister, sauvegarder,
valider, redémarrer, et chaque refus avec son code et sa trace. Contrat :
`docs/presentation-studio.md` › *Presentation contract*.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core import presentation_studio_service as service_module
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain import presentation_studio as ps
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio"
SCENES = [{"scene_id": "pss_000000000001", "prefab": {"id": "jarvis.window", "version": 1}},
          {"scene_id": "pss_000000000002", "prefab": {"id": "jarvis.table", "version": 3}}]


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def kinds(self, level: str | None = None) -> list[str]:
        return [kind for kind, row_level, _ in self.rows if level in (None, row_level)]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def make(tmp_path, sink=None, store=None) -> PresentationStudioService:
    return PresentationStudioService(store or FilePresentationStudioStore(tmp_path), diagnostics=sink, clock=Clock())


def variant_update(variant: dict, **changes) -> dict:
    body = {"expected_revision": variant["revision"], "title": variant["title"], "scenes": variant["scenes"],
            "art_direction_id": variant["art_direction_id"], "score_id": variant["score_id"]}
    return {**body, **changes}


async def refused(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ créer / charger / redémarrer

async def test_create_load_and_survive_a_restart(tmp_path):
    first = make(tmp_path)
    created = await first.create({"title": "Atelier"})
    pid = created.presentation.presentation_id
    vid = created.presentation.active_variant_id
    saved = await first.save_variant(pid, vid, variant_update(created.variants[0].to_document(), scenes=SCENES,
                                                              art_direction_id="psd_00000000000a"))
    assert saved.revision == 2 and [s.scene_id for s in saved.scenes] == ["pss_000000000001", "pss_000000000002"]

    restarted = make(tmp_path)  # a new service, same files: the disk is the source of truth
    loaded = await restarted.get(pid)
    assert loaded.presentation == created.presentation  # variant saves never touch presentation.json
    assert loaded.variants == (saved,) and loaded.active_variant() == saved
    assert (await restarted.get_variant(pid, vid)) == saved
    assert saved.scenes[1].prefab.to_dict() == {"id": "jarvis.table", "version": 3}  # exact pin, order kept


async def test_scene_order_is_the_stored_order(tmp_path):
    service = make(tmp_path)
    view = await service.create({"title": "Ordre"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    reversed_scenes = list(reversed(SCENES))
    await service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), scenes=reversed_scenes))
    assert [s.scene_id for s in (await make(tmp_path).get(pid)).variants[0].scenes] == ["pss_000000000002", "pss_000000000001"]


async def test_creation_requires_a_valid_title_and_creates_nothing_otherwise(tmp_path):
    service = make(tmp_path)
    for body in ({"title": ""}, {"title": "x" * 81}, {"title": "a", "extra": 1}, {}, [], {"title": "a\nb"}):
        await refused(service.create(body), C.INVALID_PRESENTATION)
    assert not (tmp_path / "presentations").exists()


async def test_unknown_ids_are_not_found_and_malformed_ids_never_touch_the_disk(tmp_path):
    service = make(tmp_path)
    await refused(service.get("pst_" + "0" * 32), C.UNKNOWN_PRESENTATION)
    await refused(service.get("../../x"), C.UNKNOWN_PRESENTATION)
    created = await service.create({"title": "A"})
    pid = created.presentation.presentation_id
    await refused(service.get_variant(pid, "psv_" + "0" * 32), C.UNKNOWN_VARIANT)
    await refused(service.get_variant(pid, "..\\x"), C.UNKNOWN_VARIANT)
    await refused(service.save_variant(pid, "psv_" + "0" * 32, variant_update(created.variants[0].to_document())),
                  C.UNKNOWN_VARIANT)


# ------------------------------------------------------------------ sauvegarde et révisions

async def test_save_presentation_changes_only_its_own_document(tmp_path):
    service = make(tmp_path)
    view = await service.create({"title": "Avant"})
    p = view.presentation
    resources = [{"kind": "web_page", "locator": "https://example.org/a", "title": "A"}]
    saved = await service.save_presentation(p.presentation_id, {
        "expected_revision": 1, "title": "Apres", "active_variant_id": p.active_variant_id, "resources": resources})
    assert saved.revision == 2 and saved.title == "Apres" and saved.updated_at > p.updated_at
    assert saved.created_at == p.created_at and saved.variant_counter == p.variant_counter
    reloaded = await make(tmp_path).get(p.presentation_id)
    assert reloaded.presentation == saved and reloaded.variants == view.variants


async def test_save_presentation_refuses_an_active_variant_it_does_not_have(tmp_path):
    service = make(tmp_path)
    p = (await service.create({"title": "A"})).presentation
    await refused(service.save_presentation(p.presentation_id, {
        "expected_revision": 1, "title": "A", "active_variant_id": "psv_" + "9" * 32, "resources": []}), C.UNKNOWN_VARIANT)


async def test_a_stale_revision_is_refused_and_changes_nothing(tmp_path):
    service = make(tmp_path)
    view = await service.create({"title": "A"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    await service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), title="B"))
    error = await refused(service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), title="C")),
                          C.STALE_REVISION)
    assert "revision 2" in error.message and error.status == 409
    assert (await service.get_variant(pid, variant.variant_id)).title == "B"
    await refused(service.save_presentation(pid, {"expected_revision": 7, "title": "A", "resources": [],
                                                  "active_variant_id": variant.variant_id}), C.STALE_REVISION)


async def test_two_concurrent_saves_with_the_same_revision_one_wins_one_is_stale(tmp_path):
    service = make(tmp_path)
    view = await service.create({"title": "A"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    results = await asyncio.gather(
        *(service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), title=name))
          for name in ("un", "deux", "trois")), return_exceptions=True)
    stale = [r for r in results if isinstance(r, PresentationStudioError) and r.code is C.STALE_REVISION]
    winners = [r for r in results if not isinstance(r, BaseException)]
    assert len(winners) == 1 and len(stale) == 2
    assert (await service.get_variant(pid, variant.variant_id)).title == winners[0].title


async def test_identity_fields_cannot_be_changed_by_a_save(tmp_path):
    service = make(tmp_path)
    view = await service.create({"title": "A"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    saved = await service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), title="Z"))
    assert (saved.variant_id, saved.variant_number, saved.presentation_id, saved.parent_variant_id, saved.created_at) == (
        variant.variant_id, 1, pid, None, variant.created_at)
    for forbidden in ({"variant_id": "psv_" + "1" * 32}, {"variant_number": 9}, {"presentation_id": pid}, {"created_at": "x"}):
        await refused(service.save_variant(pid, variant.variant_id, {**variant_update(saved.to_document()), **forbidden}),
                      C.INVALID_PRESENTATION)


async def test_runtime_state_in_a_save_is_refused_and_nothing_is_written(tmp_path):
    service = make(tmp_path)
    view = await service.create({"title": "A"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    before = (tmp_path / "presentations" / pid / "variants" / f"{variant.variant_id}.json").read_bytes()
    for key in ("object_id", "playback", "position", "undo_stack"):
        await refused(service.save_variant(pid, variant.variant_id, {**variant_update(variant.to_document()), key: 1}),
                      C.RUNTIME_STATE_REFUSED)
    await refused(service.save_presentation(pid, {"expected_revision": 1, "title": "A", "resources": [
        {"kind": "scene_object", "locator": "obj-1"}], "active_variant_id": variant.variant_id}), C.RUNTIME_STATE_REFUSED)
    assert (tmp_path / "presentations" / pid / "variants" / f"{variant.variant_id}.json").read_bytes() == before


async def test_a_save_over_the_size_bound_is_refused_before_writing(tmp_path, monkeypatch):
    service = make(tmp_path)
    view = await service.create({"title": "A"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    folder = tmp_path / "presentations" / pid
    sizes = [(folder / "presentation.json").stat().st_size, (folder / "variants" / f"{variant.variant_id}.json").stat().st_size]
    monkeypatch.setattr(ps, "MAX_DOCUMENT_BYTES", max(sizes) + 40)  # the stored documents still load; two scenes do not fit
    await refused(service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), scenes=SCENES)),
                  C.LIMIT_REACHED)
    assert (await service.get_variant(pid, variant.variant_id)).scenes == ()


# ------------------------------------------------------------------ documents stockés illisibles

def stored_paths(tmp_path, view):
    folder = tmp_path / "presentations" / view.presentation.presentation_id
    return folder / "presentation.json", folder / "variants" / f"{view.variants[0].variant_id}.json"


async def test_a_newer_stored_document_is_refused_and_never_overwritten(tmp_path):
    sink = Sink()
    service = make(tmp_path, sink)
    view = await service.create({"title": "A"})
    manifest, variant_file = stored_paths(tmp_path, view)
    future = {**json.loads(variant_file.read_text(encoding="utf-8")), "schema_version": 4, "new_in_v4": True}
    variant_file.write_text(json.dumps(future), encoding="utf-8")
    snapshot = variant_file.read_bytes()
    pid, vid = view.presentation.presentation_id, view.variants[0].variant_id
    for call in (service.get(pid), service.get_variant(pid, vid),
                 service.save_variant(pid, vid, variant_update(view.variants[0].to_document()))):
        error = await refused(call, C.UNSUPPORTED_SCHEMA_VERSION)
        assert "schema_version 4" in error.message and "left untouched" in error.message
    assert variant_file.read_bytes() == snapshot
    assert "core.presentation_studio.failed" in sink.kinds("error")


async def test_a_corrupt_or_torn_store_is_a_data_failure_not_a_bad_request(tmp_path):
    sink = Sink()
    service = make(tmp_path, sink)
    view = await service.create({"title": "A"})
    pid = view.presentation.presentation_id
    manifest, variant_file = stored_paths(tmp_path, view)
    good = variant_file.read_bytes()
    variant_file.write_text('{"truncated', encoding="utf-8")
    assert (await refused(service.get(pid), C.CORRUPT_DOCUMENT)).status == 409
    variant_file.write_text(json.dumps({**json.loads(good), "playback": {"state": "running"}}), encoding="utf-8")
    await refused(service.get(pid), C.CORRUPT_DOCUMENT)  # a stored runtime key is corruption, not a 400
    variant_file.unlink()
    error = await refused(service.get(pid), C.CORRUPT_DOCUMENT)
    assert "indexed variant" in error.message
    variant_file.write_bytes(good)
    other = json.loads(good)
    other["presentation_id"] = "pst_" + "7" * 32
    variant_file.write_text(json.dumps(other), encoding="utf-8")
    await refused(service.get(pid), C.CORRUPT_DOCUMENT)
    variant_file.write_bytes(good)
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(pid, "pst_" + "6" * 32), encoding="utf-8")
    await refused(service.get(pid), C.CORRUPT_DOCUMENT)
    assert sink.kinds("error").count("core.presentation_studio.failed") >= 5


async def test_listing_shows_every_readable_presentation_and_names_each_unreadable_one(tmp_path):
    sink = Sink()
    service = make(tmp_path, sink)
    a = await service.create({"title": "Premiere"})
    b = await service.create({"title": "Seconde"})
    broken = await service.create({"title": "Cassee"})
    future = await service.create({"title": "Future"})
    stored_paths(tmp_path, broken)[0].write_text("{nope", encoding="utf-8")
    manifest = stored_paths(tmp_path, future)[0]
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('"schema_version": 1', '"schema_version": 9'),
                        encoding="utf-8")
    (tmp_path / "presentations" / "strange-folder").mkdir()
    listing = await service.list_presentations()
    assert [row["title"] for row in listing.presentations] == ["Seconde", "Premiere"]  # newest first
    problems = {p["presentation_id"]: p["code"] for p in listing.problems}
    assert problems == {"strange-folder": C.CORRUPT_DOCUMENT.value, broken.presentation.presentation_id: C.CORRUPT_DOCUMENT.value,
                        future.presentation.presentation_id: C.UNSUPPORTED_SCHEMA_VERSION.value}
    assert sink.kinds("error").count("core.presentation_studio.unreadable") == 2
    assert listing.presentations[0].keys() == {"presentation_id", "title", "active_variant_id", "variant_count",
                                               "resource_count", "revision", "updated_at"}
    assert a and b


async def test_listing_is_bounded_by_the_limit(tmp_path):
    service = make(tmp_path)
    for i in range(4):
        await service.create({"title": f"P{i}"})
    assert [r["title"] for r in (await service.list_presentations(2)).presentations] == ["P3", "P2"]
    (tmp_path / "empty").mkdir()
    assert (await make(tmp_path / "empty").list_presentations()).presentations == ()  # first run: nothing, not a fault
    await refused(make(tmp_path / "missing-root").list_presentations(), C.STORAGE_IO)  # a missing root is a fault, said so


async def test_the_presentation_count_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "MAX_PRESENTATIONS", 2)
    service = make(tmp_path)
    await service.create({"title": "1"})
    await service.create({"title": "2"})
    await refused(service.create({"title": "3"}), C.LIMIT_REACHED)


# ------------------------------------------------------------------ pannes du magasin

class BrokenStore(FilePresentationStudioStore):
    """Magasin réel dont la lecture ou l'écriture d'une variante échoue sur demande."""

    def __init__(self, root, failure: Exception) -> None:
        super().__init__(root)
        self.failure = failure
        self.fail_reads = False
        self.fail_writes = False

    def read_manifest(self, presentation_id):
        if self.fail_reads:
            raise self.failure
        return super().read_manifest(presentation_id)

    def write_variant(self, presentation_id, variant_id, text):
        if self.fail_writes:
            raise self.failure
        super().write_variant(presentation_id, variant_id, text)


async def test_an_unexpected_store_failure_becomes_a_coded_storage_error_with_the_real_cause(tmp_path):
    sink = Sink()
    store = BrokenStore(tmp_path, OSError(28, "No space left on device"))
    service = make(tmp_path, sink, store)
    view = await service.create({"title": "A"})
    store.fail_reads = True
    error = await refused(service.get(view.presentation.presentation_id), C.STORAGE_IO)
    assert "OSError" in error.message and "No space" in error.message and error.status == 500
    assert any(kind == "core.presentation_studio.failed" and level == "error" and data["code"] == C.STORAGE_IO.value
               for kind, level, data in sink.rows)


async def test_a_failed_write_changes_nothing_and_the_old_revision_stays_valid(tmp_path):
    store = BrokenStore(tmp_path, PermissionError(13, "locked"))
    service = make(tmp_path, None, store)
    view = await service.create({"title": "A"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    first = await service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), title="B"))
    store.fail_writes = True
    await refused(service.save_variant(pid, variant.variant_id, variant_update(first.to_document(), title="C")), C.STORAGE_IO)
    store.fail_writes = False
    assert (await service.get_variant(pid, variant.variant_id)) == first  # same revision, same text: retry possible
    saved = await service.save_variant(pid, variant.variant_id, variant_update(first.to_document(), title="C"))
    assert saved.revision == first.revision + 1


async def test_a_failing_journal_never_undoes_an_operation(tmp_path):
    class Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("journal down")

    service = make(tmp_path, Broken())
    view = await service.create({"title": "A"})
    assert (await service.get(view.presentation.presentation_id)).presentation == view.presentation


# ------------------------------------------------------------------ validation, démarrage, traces

def test_validate_reports_ok_or_the_first_error_and_writes_nothing(tmp_path):
    service = make(tmp_path)
    documents = {"presentation": json.loads((FIXTURES / "presentation.v1.json").read_text(encoding="utf-8")),
                 "variants": [json.loads((FIXTURES / name).read_text(encoding="utf-8"))
                              for name in ("variant.parent.v1.json", "variant.v1.json")]}
    assert service.validate(documents) == {"ok": True, "errors": []}
    future = {**documents, "presentation": json.loads((FIXTURES / "presentation.future.json").read_text(encoding="utf-8"))}
    report = service.validate(future)
    assert report["ok"] is False and report["errors"][0]["code"] == C.UNSUPPORTED_SCHEMA_VERSION.value
    assert service.validate({"presentation": 1, "variants": []})["errors"][0]["code"] == C.INVALID_PRESENTATION.value
    assert service.validate("nope")["ok"] is False
    assert not (tmp_path / "presentations").exists()


async def test_start_sweeps_leftovers_and_traces_it(tmp_path):
    sink = Sink()
    service = make(tmp_path, sink)
    view = await service.create({"title": "A"})
    folder = tmp_path / "presentations"
    (folder / ".staging-0123456789abcdef").mkdir()
    (folder / view.presentation.presentation_id / "presentation.json.0badf00d.tmp").write_text("torn", encoding="utf-8")
    sink.rows.clear()
    await service.start()
    assert not (folder / ".staging-0123456789abcdef").exists()
    assert sink.kinds() == ["core.presentation_studio.swept", "core.presentation_studio.started"]
    assert sink.rows[0][2]["count"] == 2
    assert (await service.get(view.presentation.presentation_id)).presentation == view.presentation


async def test_a_sweep_that_raises_is_traced_as_an_error_and_never_blocks_start(tmp_path):
    class NoSweep(FilePresentationStudioStore):
        def sweep(self):
            raise OSError(5, "disk gone")

    sink = Sink()
    await make(tmp_path, sink, NoSweep(tmp_path)).start()
    assert sink.kinds("error") == ["core.presentation_studio.sweep_failed"] and "disk gone" in sink.rows[0][2]["error"]


async def test_the_normal_path_is_traced_at_info_with_ids_and_never_content(tmp_path):
    sink = Sink()
    service = make(tmp_path, sink)
    view = await service.create({"title": "Titre secret du client"})
    pid, variant = view.presentation.presentation_id, view.variants[0]
    await service.save_variant(pid, variant.variant_id, variant_update(variant.to_document(), scenes=SCENES))
    await service.save_presentation(pid, {"expected_revision": 1, "title": "Autre titre prive", "resources": [
        {"kind": "web_page", "locator": "https://example.org/secret"}], "active_variant_id": variant.variant_id})
    await refused(service.save_variant(pid, variant.variant_id, variant_update(variant.to_document())), C.STALE_REVISION)
    assert sink.kinds() == ["core.presentation_studio.created", "core.presentation_studio.saved",
                            "core.presentation_studio.saved", "core.presentation_studio.refused"]
    assert {level for _, level, _ in sink.rows} == {"info"}
    blob = json.dumps(sink.rows)
    assert "secret" not in blob and "prive" not in blob and "example.org" not in blob
    assert sink.rows[-1][2]["code"] == C.STALE_REVISION.value and sink.rows[1][2]["scenes"] == 2


def test_report_unexpected_records_the_real_cause_at_error(tmp_path):
    sink = Sink()
    make(tmp_path, sink).report_unexpected("GET /x", KeyError("boom"))
    assert sink.rows[0][:2] == ("core.presentation_studio.unexpected", "error") and "KeyError" in sink.rows[0][2]["error"]


# ------------------------------------------------------------------ rework (QA-1 B1)

async def test_readers_hammering_while_saves_land_see_no_false_corruption_and_the_writer_never_fails(tmp_path):
    sink = Sink()
    service = make(tmp_path, sink)
    view = await service.create({"title": "A"})
    pid, vid = view.presentation.presentation_id, view.variants[0].variant_id
    stop = asyncio.Event()
    errors: list[BaseException] = []
    reads = 0

    async def reader(kind: int) -> None:
        nonlocal reads
        while not stop.is_set():
            try:
                if kind % 2:
                    await service.get(pid)
                else:
                    await service.get_variant(pid, vid)
                reads += 1
            except BaseException as exc:  # noqa: BLE001 - collected, asserted empty below
                errors.append(exc)
            await asyncio.sleep(0)

    readers = [asyncio.create_task(reader(i)) for i in range(4)]
    saved = view.variants[0]
    try:
        for n in range(150):
            saved = await service.save_variant(pid, vid, variant_update(saved.to_document(), title=f"v{n}"))
    finally:
        stop.set()
        await asyncio.gather(*readers)
    assert errors == [], errors[:3]
    assert reads > 50 and saved.revision == 151
    assert "core.presentation_studio.failed" not in sink.kinds("error")
    assert (await service.get_variant(pid, vid)).title == "v149"
