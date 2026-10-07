"""Service Core de la partition (jarvis-interactive-presentation-studio, Slice 10).

Vrai magasin de fichiers et vrai `PrefabService` sous `tmp_path` (`lab.counter`) : création qui donne son `score_id` à la
variante, lecture après redémarrage, révisions périmées, validation contre la variante et contre le manifeste, rien d'écrit
quand c'est refusé, fichiers corrompus ou plus récents, panne entre les deux écritures, concurrence. Contrat :
`docs/presentation-studio.md` › *Score and cue contract*.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR, FilePrefabLibrary
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.prefab_service import PrefabService
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.ports.prefabs import PrefabStoreError, PrefabStoreErrorCode
from tests.fakes.prefabs import install_version

S1, S2 = "pss_0000000000a1", "pss_0000000000a2"
I1, I2, I3 = ("psi_00000000000%d" % n for n in (1, 2, 3))
CUE = "psc_000000000001"


def scene_body(scene_id=S1) -> dict:
    return {
        "scene_id": scene_id, "prefab": {"id": "lab.counter", "version": 1}, "title": "Chiffre",
        "props": {"label": "Visiteurs", "mode": "full"}, "data": {"count": 12},
        "controls": [
            {"control_id": "headline", "path": "props.label", "label": "Titre", "group": "content"},
            {"control_id": "accent", "path": "props.accent", "label": "Accent", "group": "visual"},
            {"control_id": "density", "path": "props.mode", "label": "Densite", "group": "motion"},
            {"control_id": "count", "path": "data.count", "label": "Valeur", "group": "content"},
            {"control_id": "limited", "path": "data.notes", "label": "Notes", "group": "content",
             "bounds": {"max_length": 10}}],
        "anchors": [{"anchor_id": "reveal", "label": "Reveler", "control_id": "count"},
                    {"anchor_id": "marker", "label": "Repere"}]}


def score_body(**changes) -> dict:
    body = {
        "start_item_id": I1,
        "items": [
            {"item_id": I1, "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": "Bonjour.",
             "visual": [{"kind": "reveal", "scene_id": S1, "anchor_id": "reveal"}], "next_item_id": I2},
            {"item_id": I2, "scene_id": S1, "presenter": "user", "kind": "speech", "note": "Explain", "cue_id": CUE,
             "motion": [{"kind": "control_set", "scene_id": S1, "control_id": "density", "value": "compact"}],
             "next_item_id": I3},
            {"item_id": I3, "scene_id": S1, "presenter": "none", "kind": "silence"}],
        "cues": [{"cue_id": CUE, "label": "Go", "armable": True, "predicate": {"phrases": ["passons a la suite"]}}],
        "sequences": [], "recovery_points": []}
    return {**body, **changes}


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict]] = []

    def emit(self, kind, message, *, level="info", data=None) -> None:
        self.rows.append((kind, level, dict(data or {})))

    def of(self, kind: str) -> list[tuple[str, dict]]:
        return [(level, data) for k, level, data in self.rows if k == kind]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Env:
    def __init__(self, tmp_path: Path) -> None:
        package, self.data = tmp_path / "package", tmp_path / "data"
        package.mkdir()
        self.data.mkdir()
        install_version(package, "jarvis.counter", title="Base")
        install_version(self.data / LIBRARY_DIR, "lab.counter", 1)
        self.sink = Sink()
        self.prefabs = PrefabService(FilePrefabLibrary(package, self.data))
        self.root = tmp_path / "studio"
        self.root.mkdir()
        self.store = FilePresentationStudioStore(self.root)

    async def service(self, *, catalog=True) -> PresentationStudioService:
        await self.prefabs.start()
        return PresentationStudioService(self.store, diagnostics=self.sink, clock=Clock(),
                                         prefabs=self.prefabs if catalog else None)

    async def presentation(self, service, scenes=(S1,)):
        view = await service.create({"title": "Atelier"})
        pid, vid = view.presentation.presentation_id, view.presentation.active_variant_id
        variant = await service.get_variant(pid, vid)
        await service.save_variant(pid, vid, {"expected_revision": variant.revision, "title": variant.title,
                                              "scenes": [scene_body(s) for s in scenes], "art_direction_id": None,
                                              "score_id": None})
        return pid, vid

    def folder(self, pid) -> Path:
        return self.root / "presentations" / pid

    def snapshot(self, pid) -> dict[str, bytes]:
        return {str(p.relative_to(self.folder(pid))): p.read_bytes() for p in sorted(self.folder(pid).rglob("*")) if p.is_file()}


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


async def refused(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


async def with_score(env, service=None, **changes):
    service = service or await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    answer = await service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **score_body(**changes)})
    return service, pid, vid, answer


# ------------------------------------------------------------------ création, lecture, redémarrage

async def test_creating_a_score_gives_the_variant_its_score_id_and_survives_a_restart(env):
    service, pid, vid, answer = await with_score(env)
    score = answer["score"]
    assert answer["problems"] == [] and score["revision"] == 1 and score["variant_id"] == vid
    variant = await service.get_variant(pid, vid)
    assert variant.score_id == score["score_id"] and variant.revision == 3  # create (1), scenes (2), score link (3)
    assert (env.folder(pid) / "scores" / f"{score['score_id']}.json").is_file()

    restarted = await env.service()  # a new service on the same files: the disk is the truth
    loaded = await restarted.get_score(pid, vid)
    assert loaded == {"score": score, "problems": []}
    assert (await restarted.get(pid)).variants[0].score_id == score["score_id"]


async def test_a_variant_without_a_score_says_so_with_a_404_code(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    error = await refused(service.get_score(pid, vid), C.UNKNOWN_SCORE)
    assert error.status == 404 and "create it" in error.message


async def test_the_score_is_created_once_then_saved(env):
    service, pid, vid, answer = await with_score(env)
    before = env.snapshot(pid)
    variant = await service.get_variant(pid, vid)
    await refused(service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **score_body()}),
                  C.ALREADY_EXISTS)
    assert env.snapshot(pid) == before


async def test_creating_with_a_stale_variant_revision_writes_nothing(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    before = env.snapshot(pid)
    await refused(service.create_score(pid, vid, {"expected_variant_revision": 1, **score_body()}), C.STALE_REVISION)
    assert env.snapshot(pid) == before and not (env.folder(pid) / "scores").exists()


async def test_saving_replaces_the_content_under_expected_revision_and_never_touches_the_variant(env):
    service, pid, vid, answer = await with_score(env)
    variant_before = (env.folder(pid) / "variants" / f"{vid}.json").read_bytes()
    body = score_body()
    body["items"][2] = {**body["items"][2], "label": "Respiration", "target_duration_ms": 3000}
    saved = await service.save_score(pid, vid, {"expected_revision": 1, **body})
    assert saved["score"]["revision"] == 2 and saved["score"]["items"][2]["label"] == "Respiration"
    assert saved["score"]["created_at"] == answer["score"]["created_at"] and saved["score"]["updated_at"] > answer["score"]["updated_at"]
    assert saved["score"]["score_id"] == answer["score"]["score_id"]
    assert (env.folder(pid) / "variants" / f"{vid}.json").read_bytes() == variant_before  # identity of the link is stable


async def test_a_stale_save_is_refused_and_changes_no_byte(env):
    service, pid, vid, _ = await with_score(env)
    await service.save_score(pid, vid, {"expected_revision": 1, **score_body()})
    before = env.snapshot(pid)
    error = await refused(service.save_score(pid, vid, {"expected_revision": 1, **score_body()}), C.STALE_REVISION)
    assert error.status == 409 and "reload, then retry" in error.message and "revision 2, not 1" in error.message
    assert env.snapshot(pid) == before


async def test_exactly_one_of_many_same_revision_saves_wins(env):
    service, pid, vid, _ = await with_score(env)
    results = await asyncio.gather(*(service.save_score(pid, vid, {"expected_revision": 1, **score_body()})
                                     for _ in range(10)), return_exceptions=True)
    wins = [r for r in results if isinstance(r, dict)]
    stale = [r for r in results if isinstance(r, PresentationStudioError) and r.code is C.STALE_REVISION]
    assert len(wins) == 1 and len(stale) == 9
    assert (await service.get_score(pid, vid))["score"]["revision"] == 2


# ------------------------------------------------------------------ validation contre la variante

@pytest.mark.parametrize(("mutate", "needle"), [
    (lambda b: b["items"][0].update(scene_id="pss_0000000000ff"), "is not a scene of this variant"),
    (lambda b: b["items"][0]["visual"].__setitem__(0, {"kind": "reveal", "scene_id": S1, "anchor_id": "nope"}),
     "anchor nope is not declared"),
    (lambda b: b["items"][1]["motion"].__setitem__(0, {"kind": "control_set", "scene_id": S1, "control_id": "nope", "value": 1}),
     "control nope is not declared"),
    (lambda b: b["items"][1]["motion"].__setitem__(0, {"kind": "control_set", "scene_id": S1, "control_id": "count", "value": 1}),
     "belongs on the visual track"),
    (lambda b: b["items"][0]["visual"].__setitem__(0, {"kind": "control_set", "scene_id": S1, "control_id": "limited",
                                                       "value": "far too long a text"}), "exceeds 10 characters"),
])
async def test_an_unresolved_reference_or_value_is_refused_whole_and_nothing_is_written(env, mutate, needle):
    service = await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    body = score_body()
    mutate(body)
    before = env.snapshot(pid)
    error = await refused(service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **body}),
                          C.SCORE_INCOMPATIBLE)
    assert needle in error.message and error.status == 400
    assert env.snapshot(pid) == before and not (env.folder(pid) / "scores").exists()
    assert env.sink.of("core.presentation_studio.refused")[-1][0] == "info"


async def test_a_save_that_breaks_a_reference_is_refused_and_the_stored_score_is_untouched(env):
    service, pid, vid, _ = await with_score(env)
    before = env.snapshot(pid)
    bad = score_body()
    bad["items"][0]["scene_id"] = "pss_0000000000ff"
    await refused(service.save_score(pid, vid, {"expected_revision": 1, **bad}), C.SCORE_INCOMPATIBLE)
    assert env.snapshot(pid) == before


async def test_values_are_checked_against_the_pinned_prefab_manifest_not_only_the_curated_bounds(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)

    def with_value(control, value, track="visual"):
        body = score_body()
        body["items"][0]["visual"] = [{"kind": "control_set", "scene_id": S1, "control_id": control, "value": value}]
        if track == "motion":
            body["items"][0].update(motion=body["items"][0].pop("visual"), visual=[])
        return {"expected_variant_revision": variant.revision, **body}

    # passes the shape checks (a string / a number) but the manifest says colour and integer
    error = await refused(service.create_score(pid, vid, with_value("accent", "red")), C.SCORE_INCOMPATIBLE)
    assert "props.accent" in error.message
    error = await refused(service.create_score(pid, vid, with_value("count", 1.5)), C.SCORE_INCOMPATIBLE)
    assert "data.count" in error.message
    await refused(service.create_score(pid, vid, with_value("density", "huge", "motion")), C.SCORE_INCOMPATIBLE)
    ok = await service.create_score(pid, vid, with_value("accent", "#ff8800"))
    assert ok["score"]["items"][0]["visual"][0]["value"] == "#ff8800"


async def test_without_a_catalog_only_the_shape_and_curated_bounds_are_checked(env):
    service = await env.service(catalog=False)
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    body = score_body()
    body["items"][0]["visual"] = [{"kind": "control_set", "scene_id": S1, "control_id": "accent", "value": "red"}]
    answer = await service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **body})
    assert answer["score"]["revision"] == 1  # no manifest source wired: never claimed validated against one


async def test_a_pin_the_catalog_cannot_answer_for_is_a_visible_prefab_failure_not_a_pass(env, monkeypatch):
    service = await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    body = score_body()
    body["items"][0]["visual"] = [{"kind": "control_set", "scene_id": S1, "control_id": "accent", "value": "#fff000"}]

    async def tampered(prefab_id, version):
        raise PrefabStoreError(PrefabStoreErrorCode.TAMPERED, "files differ from publication.json")

    monkeypatch.setattr(env.prefabs, "manifest", tampered)
    error = await refused(service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **body}),
                          C.PREFAB_UNAVAILABLE)
    assert "tampered" in error.message and "lab.counter" in error.message and not (env.folder(pid) / "scores").exists()


async def test_reading_after_a_scene_was_removed_reports_the_dangling_references(env):
    service = await env.service()
    pid, vid = await env.presentation(service, scenes=(S1, S2))
    variant = await service.get_variant(pid, vid)
    body = score_body()
    body["items"][1]["scene_id"] = S2
    created = await service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **body})
    variant = await service.get_variant(pid, vid)
    await service.save_variant(pid, vid, {"expected_revision": variant.revision, "title": variant.title,
                                          "scenes": [scene_body(S1)], "art_direction_id": None,
                                          "score_id": variant.score_id})
    answer = await service.get_score(pid, vid)
    assert answer["score"] == created["score"]  # the stored score is not rewritten or hidden
    assert any(S2 in problem for problem in answer["problems"])


async def test_once_a_variant_has_a_score_a_variant_save_cannot_detach_or_swap_it(env):
    service, pid, vid, answer = await with_score(env)
    variant = await service.get_variant(pid, vid)
    update = {"expected_revision": variant.revision, "title": variant.title,
              "scenes": [scene_body(S1)], "art_direction_id": None}
    for other in (None, "psr_0000000000ee"):
        error = await refused(service.save_variant(pid, vid, {**update, "score_id": other}), C.INVALID_PRESENTATION)
        assert "cannot attach, swap or clear" in error.message
    saved = await service.save_variant(pid, vid, {**update, "score_id": answer["score"]["score_id"]})
    assert saved.score_id == answer["score"]["score_id"]


# ------------------------------------------------------------------ pannes et fichiers

async def test_a_crash_between_the_two_writes_leaves_an_orphan_score_and_an_unchanged_variant(env, monkeypatch):
    service = await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    real = env.store.write_variant

    def fail_once(*args):
        raise OSError("disk went away")

    monkeypatch.setattr(env.store, "write_variant", fail_once)
    error = await refused(service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **score_body()}),
                          C.STORAGE_IO)
    assert "disk went away" in error.message and env.sink.of("core.presentation_studio.failed")[-1][0] == "error"
    monkeypatch.setattr(env.store, "write_variant", real)
    assert (await service.get_variant(pid, vid)).score_id is None and len(list((env.folder(pid) / "scores").glob("*.json"))) == 1
    await refused(service.get_score(pid, vid), C.UNKNOWN_SCORE)  # the orphan is never referenced
    answer = await service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **score_body()})
    assert (await service.get_variant(pid, vid)).score_id == answer["score"]["score_id"]


async def test_a_corrupt_score_file_is_a_data_fault_and_is_not_overwritten(env):
    service, pid, vid, answer = await with_score(env)
    path = env.folder(pid) / "scores" / f"{answer['score']['score_id']}.json"
    path.write_text("{not json", encoding="utf-8")
    snapshot = path.read_bytes()
    await refused(service.get_score(pid, vid), C.CORRUPT_DOCUMENT)
    await refused(service.save_score(pid, vid, {"expected_revision": 1, **score_body()}), C.CORRUPT_DOCUMENT)
    assert path.read_bytes() == snapshot
    assert env.sink.of("core.presentation_studio.failed")[-1][0] == "error"


async def test_a_newer_score_document_is_refused_and_left_untouched(env):
    service, pid, vid, answer = await with_score(env)
    path = env.folder(pid) / "scores" / f"{answer['score']['score_id']}.json"
    path.write_text(json.dumps({**answer["score"], "schema_version": 2}), encoding="utf-8")
    snapshot = path.read_bytes()
    error = await refused(service.save_score(pid, vid, {"expected_revision": 1, **score_body()}), C.UNSUPPORTED_SCHEMA_VERSION)
    assert error.status == 409 and "schema_version 2" in error.message and path.read_bytes() == snapshot
    await refused(service.get_score(pid, vid), C.UNSUPPORTED_SCHEMA_VERSION)


async def test_a_score_file_that_names_another_variant_is_corrupt(env):
    service, pid, vid, answer = await with_score(env)
    path = env.folder(pid) / "scores" / f"{answer['score']['score_id']}.json"
    path.write_text(json.dumps({**answer["score"], "variant_id": "psv_" + "9" * 32}), encoding="utf-8")
    error = await refused(service.get_score(pid, vid), C.CORRUPT_DOCUMENT)
    assert "another score, variant or presentation" in error.message


async def test_a_made_up_score_id_cannot_be_attached_through_a_variant_save(env):
    """QA B1: a well-formed id with no file used to lock the variant out of its own score."""

    service = await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    before = env.snapshot(pid)
    error = await refused(service.save_variant(pid, vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body(S1)],
        "art_direction_id": None, "score_id": "psr_0000000000aa"}), C.INVALID_PRESENTATION)
    assert "cannot attach, swap or clear" in error.message
    assert env.snapshot(pid) == before and (await service.get_variant(pid, vid)).score_id is None


async def test_the_variant_write_path_itself_guards_the_score_link(env):
    """The guard lives in `_persist_variant`, so every writer (this Slice's, Slice 05's) is covered."""

    service = await env.service()
    pid, vid = await env.presentation(service)
    variant = await service.get_variant(pid, vid)
    other = dataclasses.replace(variant, score_id="psr_0000000000aa")
    with pytest.raises(PresentationStudioError) as caught:
        await service._persist_variant("test", pid, variant, other)
    assert caught.value.code is C.INVALID_PRESENTATION
    assert (await service.get_variant(pid, vid)).score_id is None
    await service._persist_variant("test", pid, variant, other, relink=True)  # only the score routes pass relink
    assert (await service.get_variant(pid, vid)).score_id == "psr_0000000000aa"


async def test_a_dangling_score_link_is_repaired_by_creating_the_score_again(env):
    """Score file gone (hand-deleted, restored backup): the four calls that used to be dead ends, and the repair."""

    service, pid, vid, first = await with_score(env)
    old_id = first["score"]["score_id"]
    (env.folder(pid) / "scores" / f"{old_id}.json").unlink()
    variant = await service.get_variant(pid, vid)
    assert variant.score_id == old_id

    await refused(service.get_score(pid, vid), C.UNKNOWN_SCORE)                                           # 1. GET
    await refused(service.save_score(pid, vid, {"expected_revision": 1, **score_body()}), C.UNKNOWN_SCORE)  # 2. PUT
    update = {"expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body(S1)],
              "art_direction_id": None}
    for other in (None, "psr_0000000000ee"):                                                              # 3. clear / swap
        await refused(service.save_variant(pid, vid, {**update, "score_id": other}), C.INVALID_PRESENTATION)

    answer = await service.create_score(pid, vid, {"expected_variant_revision": variant.revision, **score_body()})  # 4. POST repairs
    assert answer["relinked_from"] == old_id and answer["score"]["score_id"] != old_id and answer["score"]["revision"] == 1
    repaired = await service.get_variant(pid, vid)
    assert repaired.score_id == answer["score"]["score_id"] and repaired.revision == variant.revision + 1
    level, data = env.sink.of("core.presentation_studio.score_relinked")[-1]
    assert level == "warning" and data["missing_score_id"] == old_id and data["score_id"] == answer["score"]["score_id"]
    assert (await service.get_score(pid, vid))["score"] == answer["score"]
    assert "relinked_from" not in (await service.save_score(pid, vid, {"expected_revision": 1, **score_body()}))


async def test_creating_never_replaces_a_link_whose_file_exists_even_if_unusable(env):
    service, pid, vid, first = await with_score(env)
    path = env.folder(pid) / "scores" / f"{first['score']['score_id']}.json"
    variant = await service.get_variant(pid, vid)
    body = {"expected_variant_revision": variant.revision, **score_body()}
    await refused(service.create_score(pid, vid, body), C.ALREADY_EXISTS)
    path.write_text("{not json", encoding="utf-8")
    snapshot = path.read_bytes()
    await refused(service.create_score(pid, vid, body), C.CORRUPT_DOCUMENT)  # kept for a human, never overwritten
    assert path.read_bytes() == snapshot and (await service.get_variant(pid, vid)).score_id == first["score"]["score_id"]


async def test_the_missing_score_file_of_a_variant_without_repair_yet_is_unknown_score(env):
    service, pid, vid, first = await with_score(env)
    (env.folder(pid) / "scores" / f"{first['score']['score_id']}.json").unlink()
    error = await refused(service.get_score(pid, vid), C.UNKNOWN_SCORE)
    assert error.status == 404


async def test_unknown_and_malformed_ids_never_touch_the_disk(env):
    service = await env.service()
    pid, vid = await env.presentation(service)
    await refused(service.get_score("pst_" + "0" * 32, vid), C.UNKNOWN_PRESENTATION)
    await refused(service.get_score("../x", vid), C.UNKNOWN_PRESENTATION)
    await refused(service.get_score(pid, "psv_" + "0" * 32), C.UNKNOWN_VARIANT)
    await refused(service.create_score(pid, "..\\x", {}), C.UNKNOWN_VARIANT)
    await refused(service.save_score(pid, "psv_" + "0" * 32, {"expected_revision": 1, **score_body()}), C.UNKNOWN_VARIANT)
    await refused(service.create_score(pid, "psv_" + "0" * 32, {"expected_variant_revision": 1, **score_body()}),
                  C.UNKNOWN_VARIANT)


@pytest.mark.parametrize("body", [[], {}, {"expected_revision": 1}, {"expected_revision": 1, **score_body(), "extra": 1},
                                  {"expected_revision": 1, **score_body(), "position": 3}])
async def test_malformed_save_bodies_are_refused_before_anything_is_read(env, body):
    service, pid, vid, _ = await with_score(env)
    before = env.snapshot(pid)
    with pytest.raises(PresentationStudioError) as caught:
        await service.save_score(pid, vid, body)
    assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED)
    assert env.snapshot(pid) == before


# ------------------------------------------------------------------ trace

async def test_the_normal_path_and_the_refusals_are_traced_without_content(env):
    service, pid, vid, answer = await with_score(env)
    await service.get_score(pid, vid)
    level, data = env.sink.of("core.presentation_studio.score_loaded")[-1]
    assert level == "info" and data == {"presentation_id": pid, "variant_id": vid, "score_id": answer["score"]["score_id"],
                                        "revision": 1, "items": 3, "problems": 0}
    level, data = env.sink.of("core.presentation_studio.saved")[-1]
    assert level == "info" and data["part"] == "score" and data["items"] == 3
    flat = json.dumps(env.sink.rows)
    assert "Bonjour" not in flat and "passons a la suite" not in flat  # no speech and no phrase in the journal
    await refused(service.save_score(pid, vid, {"expected_revision": 9, **score_body()}), C.STALE_REVISION)
    level, data = env.sink.of("core.presentation_studio.refused")[-1]
    assert level == "info" and data["code"] == C.STALE_REVISION.value
