"""Variantes locales d'une scène contre le vrai magasin, le vrai `PrefabService`, la vraie API d'édition, l'historique et le
graphe des variantes (jarvis-interactive-presentation-studio, Slice 17).

Créer / renommer / choisir / supprimer par l'API d'édition (la porte unique), persistance et redémarrage, isolation par
hachage, graphe de premier niveau inchangé, annuler / rétablir à l'identique, bornes, protections, promotion, branche qui
copie l'ensemble, aperçu qui n'écrit jamais, partition protégée. Lecture (aperçu sur la fenêtre de scène, suivi d'un commit
par la lecture) : `test_presentation_studio_scene_variants_playback.py`. Arrêt brutal : `..._crash.py`.
Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jarvis.adapters.file_prefab_library import LIBRARY_DIR
from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_events import StudioEditEvents
from jarvis.core.presentation_studio_scene_variants import PresentationStudioSceneVariants
from jarvis.core.presentation_studio_variant_events import StudioVariantEvents
from jarvis.core.presentation_studio_variants import PresentationStudioVariants
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditStatus
from jarvis.domain.presentation_studio_history import HistoryStatus
from jarvis.domain.presentation_studio_scene_variants import MAX_SCENE_VARIANTS
from tests.fakes.prefabs import install_version
from tests.unit.test_presentation_studio_edit_service import Events, op_set, request
from tests.unit.test_presentation_studio_scene_variants_domain import Ids
from tests.unit.test_presentation_studio_score_service import Env, S1, S2, score_body, scene_body

SECRET = b"s" * 32


#: The only control B keeps: the anchor `reveal` still resolves, the score's `density` and `headline` no longer do.
COUNT_ONLY = {"control_id": "count", "path": "data.count", "label": "Valeur", "group": "content"}


def create(scene_id, label, **extra):
    return {"op": "scene_variant.create", "scene_id": scene_id, "label": label, **extra}


def select(scene_id, variant_id, **extra):
    return {"op": "scene_variant.select", "scene_id": scene_id, "variant_id": variant_id, **extra}


def rename(scene_id, variant_id, label):
    return {"op": "scene_variant.rename", "scene_id": scene_id, "variant_id": variant_id, "label": label}


def delete(scene_id, variant_id):
    return {"op": "scene_variant.delete", "scene_id": scene_id, "variant_id": variant_id}


class World:
    def __init__(self, tmp_path: Path, *, conversation: str | None = "conv-1") -> None:
        self.env = Env(tmp_path)
        self.emitter = Events()
        self.conversation = conversation
        self.ids = Ids(0)

    async def open(self, scenes=(S1, S2), *, score: bool = False, extra_versions: tuple[int, ...] = ()):
        for version in extra_versions:
            install_version(self.env.data / LIBRARY_DIR, "lab.counter", version)
        self.studio = await self.env.service()
        self.sink = self.env.sink
        self.wire()
        self.pid, self.vid = await self.env.presentation(self.studio, scenes)
        if score:
            variant = await self.studio.get_variant(self.pid, self.vid)
            await self.studio.create_score(self.pid, self.vid, {"expected_variant_revision": variant.revision, **score_body()})
        return self

    def wire(self):
        """Un nouveau Core sur les mêmes fichiers : mémoire vide (anneaux d'annulation compris)."""

        self.history = PresentationStudioHistory(self.studio, diagnostics=self.sink)
        self.edit = PresentationStudioEditService(
            self.studio, diagnostics=self.sink, events=StudioEditEvents(self.emitter, lambda: self.conversation),
            new_id=lambda: "pss_0000000000f1", history=self.history, new_variant_id=self.ids)
        self.history.bind(self.edit)
        self.variants = PresentationStudioVariants(
            self.studio, history=self.history, diagnostics=self.sink, secret=SECRET, epoch=lambda: 1_000_000.0,
            events=StudioVariantEvents(self.emitter, lambda: self.conversation))
        self.sv = PresentationStudioSceneVariants(self.studio, self.edit, self.variants, diagnostics=self.sink)

    @property
    def folder(self) -> Path:
        return self.env.folder(self.pid)

    def file_of(self, variant_id: str) -> Path:
        return self.folder / "variants" / f"{variant_id}.json"

    @property
    def path(self) -> Path:
        return self.file_of(self.vid)

    def stored(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def scenes_bytes(self) -> str:
        """Les scènes telles que le fichier les dit, dans l'ordre d'écriture des clés (les octets du document, moins la révision)."""

        return json.dumps(self.stored()["scenes"], ensure_ascii=False)

    def tree(self) -> dict[str, str]:
        return {p.relative_to(self.folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.folder.rglob("*")) if p.is_file()}

    async def variant(self):
        return await self.studio.get_variant(self.pid, self.vid)

    async def do(self, *ops, mode="commit", actor="user", vid=None):
        vid = vid or self.vid
        revision = (await self.studio.get_variant(self.pid, vid)).revision
        return await self.edit.edit(self.pid, vid, request(revision, *ops, mode=mode, actor=actor))

    async def ok(self, *ops, **kw):
        result = await self.do(*ops, **kw)
        assert result.status is EditStatus.APPLIED, result.to_dict()
        return result

    async def make(self, scene_id, label, headline=None, count=None):
        """Crée la variante locale `label` ; avec `headline` / `count`, son contenu diffère de l'original (on la choisit, on la
        règle, on rechoisit l'original). Rend son id."""

        made = (await self.ok(create(scene_id, label))).ops[0]["scene_variant_id"]
        if headline is not None or count is not None:
            original = (await self.variant_scene(scene_id)).scene_variants.current_id
            await self.ok(select(scene_id, made))
            if headline is not None:
                await self.ok(op_set(scene_id, "headline", headline))
            if count is not None:
                await self.ok(op_set(scene_id, "count", count))
            await self.ok(select(scene_id, original))
        return made

    async def variant_scene(self, scene_id):
        return next(s for s in (await self.variant()).scenes if s.scene_id == scene_id)


@pytest.fixture
async def world(tmp_path) -> World:
    return await World(tmp_path).open()


async def refused(awaitable, code: C) -> PresentationStudioError:
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ créer, renommer, choisir, supprimer

async def test_create_rename_select_delete_are_edit_operations_committed_durably_with_the_tier_structure(world):
    before = await world.variant()
    created = await world.ok(create(S1, "Version sobre", rationale="moins de couleurs"))
    assert (created.committed, created.changed, created.tier.value, created.revision) == (True, True, "structure", before.revision + 1)
    other = created.ops[0]["scene_variant_id"]
    stored = world.stored()
    assert stored["schema_version"] == 4 and stored["revision"] == before.revision + 1
    items = stored["scenes"][0]["scene_variants"]["items"]
    assert [i["label"] for i in items] == ["Original", "Version sobre"] and items[1]["rationale"] == "moins de couleurs"
    assert "scene_variants" not in stored["scenes"][1]
    renamed = await world.ok(rename(S1, other, "Sobre"))
    assert renamed.tier.value == "structure" and world.stored()["scenes"][0]["scene_variants"]["items"][1]["label"] == "Sobre"
    picked = await world.ok(select(S1, other))
    assert picked.committed and world.stored()["scenes"][0]["scene_variants"]["current_id"] == other
    await world.ok(select(S1, items[0]["variant_id"]))
    deleted = await world.ok(delete(S1, other))
    assert deleted.tier.value == "structure"
    assert "scene_variants" not in world.stored()["scenes"][0]  # one variant left: no set


async def test_select_swaps_the_content_into_the_scene_and_the_old_content_is_kept_exactly(world):
    original = (await world.variant_scene(S1))
    other = await world.make(S1, "Sobre", headline="Version sobre", count=99)
    assert (await world.variant_scene(S1)).props["label"] == "Visiteurs"  # creating and setting up B left the scene alone
    await world.ok(select(S1, other))
    scene = await world.variant_scene(S1)
    assert scene.props["label"] == "Version sobre" and scene.data["count"] == 99
    saved = scene.scene_variants.get(original.scene_variants.current_id if original.scene_variants else
                                     scene.scene_variants.items[0].variant_id)
    assert saved.content["props"]["label"] == "Visiteurs" and saved.content["data"]["count"] == 12
    assert scene.title == original.title and scene.section == original.section  # identity is not part of a variant's content
    assert scene.controls == original.controls


async def test_an_unknown_or_protected_target_is_a_typed_refusal_that_writes_nothing(world):
    other = await world.make(S1, "B")
    original = (await world.variant_scene(S1)).scene_variants.current_id
    before = world.tree()
    for op, code in ((select(S1, "psx_ffffffffffff"), C.UNKNOWN_SCENE_VARIANT), (delete(S1, original), C.SCENE_VARIANT_PROTECTED),
                     (delete(S1, "psx_ffffffffffff"), C.UNKNOWN_SCENE_VARIANT), (create(S1, "B"), C.ALREADY_EXISTS),
                     (select("pss_ffffffffffff", other), C.UNKNOWN_SCENE)):
        result = await world.do(op)
        assert result.status is EditStatus.REFUSED and result.code == code.value and result.http_status == {
            C.UNKNOWN_SCENE_VARIANT: 404, C.SCENE_VARIANT_PROTECTED: 409, C.ALREADY_EXISTS: 409, C.UNKNOWN_SCENE: 404}[code]
    assert world.tree() == before


async def test_a_preview_of_any_scene_variant_operation_writes_nothing_and_commits_the_same_result_later(world):
    before = world.tree()
    result = await world.ok(create(S1, "B"), mode="preview")
    assert result.committed is False and result.changed is True and world.tree() == before
    assert not world.emitter.recorded  # no event for a preview


async def test_a_second_edit_on_the_same_basis_is_stale_and_loses_nothing(world):
    other = await world.make(S1, "B")
    revision = (await world.variant()).revision
    first = await world.edit.edit(world.pid, world.vid, request(revision, select(S1, other)))
    second = await world.edit.edit(world.pid, world.vid, request(revision, create(S1, "C")))
    assert first.status is EditStatus.APPLIED and second.status is EditStatus.STALE
    assert [i.label for i in (await world.variant_scene(S1)).scene_variants.items] == ["Original", "B"]


# ------------------------------------------------------------------ persistance, restart, isolation

async def test_the_sets_survive_a_restart_with_a_fresh_core_and_are_read_back_equal(world):
    other = await world.make(S1, "B", headline="Autre")
    await world.make(S2, "C")
    await world.ok(select(S1, other))
    first = await world.variant()
    bytes_before = world.scenes_bytes()
    world.studio = await world.env.service()  # a new Core on the same files
    world.wire()
    again = await world.variant()
    assert again == first and world.scenes_bytes() == bytes_before
    assert [i.label for i in (await world.variant_scene(S2)).scene_variants.items] == ["Original", "C"]


async def test_editing_or_selecting_in_one_scene_never_touches_another_scene_nor_another_variants_file(world):
    other_variant = (await world.variants.create_branch(world.pid, {"title": "Autre direction"}))["variant"]["variant_id"]
    path_other = world.file_of(other_variant)
    s2_before = json.dumps(world.stored()["scenes"][1], ensure_ascii=False)
    other_bytes = hashlib.sha256(path_other.read_bytes()).hexdigest()
    b = await world.make(S1, "B", headline="B headline")
    await world.ok(select(S1, b))
    await world.ok(op_set(S1, "headline", "encore"))
    await world.ok(rename(S1, b, "B2"))
    assert json.dumps(world.stored()["scenes"][1], ensure_ascii=False) == s2_before  # scene 2 byte for byte
    assert hashlib.sha256(path_other.read_bytes()).hexdigest() == other_bytes  # the other presentation variant is not touched


async def test_local_variants_are_invisible_in_the_top_level_graph_until_promoted(world):
    graph = await world.variants.graph(world.pid, include_archived=True)
    manifest_bytes = (world.folder / "presentation.json").read_bytes()
    files = sorted(p.relative_to(world.folder).as_posix() for p in world.folder.rglob("*.json"))
    b = await world.make(S1, "B", headline="B")
    c = await world.make(S2, "C")
    await world.ok(select(S1, b))
    await world.ok(delete(S2, c))
    after = await world.variants.graph(world.pid, include_archived=True)
    # same nodes, same numbers, same counter, same revision: the graph is exactly what it was
    strip = lambda g: {**g, "nodes": [{k: v for k, v in n.items() if k not in ("revision", "updated_at", "scene_count")} for n in g["nodes"]]}
    assert strip(after) == strip(graph) and len(after["nodes"]) == 1 and after["variant_counter"] == graph["variant_counter"]
    assert (world.folder / "presentation.json").read_bytes() == manifest_bytes  # the manifest was never rewritten
    assert sorted(p.relative_to(world.folder).as_posix() for p in world.folder.rglob("*.json")) == files  # no file appeared
    assert not (world.folder / "archive").exists()
    promoted = await world.sv.promote(world.pid, world.vid, S1, b, {"title": "Version B"})
    assert len((await world.variants.graph(world.pid))["nodes"]) == 2 and promoted["node"]["variant_number"] == 2


async def test_describe_lists_the_variants_without_their_content(world):
    assert (await world.sv.describe(world.pid, world.vid, S1))["variants"] == []
    b = await world.make(S1, "B", headline="B headline")
    answer = await world.sv.describe(world.pid, world.vid, S1)
    assert answer["count"] == 2 and answer["selected"] == (await world.variant_scene(S1)).scene_variants.current_id
    assert [row["label"] for row in answer["variants"]] == ["Original", "B"] and answer["variants"][1]["variant_id"] == b
    assert answer["limits"]["variants"] == MAX_SCENE_VARIANTS and answer["limits"]["bytes_used"] > 0
    assert "B headline" not in json.dumps(answer)  # lists, never the content
    assert answer["variants"][0]["selected"] and not answer["variants"][1]["selected"]
    await refused(world.sv.describe(world.pid, world.vid, "pss_ffffffffffff"), C.UNKNOWN_SCENE)


# ------------------------------------------------------------------ annuler / rétablir

async def test_undo_and_redo_of_create_select_and_delete_restore_the_scenes_to_the_byte(world):
    snapshots = [world.scenes_bytes()]
    created = (await world.ok(create(S1, "B"))).ops[0]["scene_variant_id"]
    snapshots.append(world.scenes_bytes())
    await world.ok(select(S1, created))
    snapshots.append(world.scenes_bytes())
    await world.ok(op_set(S1, "headline", "Dans B"))
    snapshots.append(world.scenes_bytes())
    original = next(i.variant_id for i in (await world.variant_scene(S1)).scene_variants.items if i.variant_id != created)
    await world.ok(select(S1, original))
    snapshots.append(world.scenes_bytes())
    await world.ok(delete(S1, created))
    snapshots.append(world.scenes_bytes())
    for expected in reversed(snapshots[:-1]):  # undo every step, newest first
        done = await world.history.undo(world.pid, world.vid, {"actor": "user"})
        assert done.status is HistoryStatus.APPLIED, done.to_dict()
        assert world.scenes_bytes() == expected
    for expected in snapshots[1:]:  # and redo them all
        done = await world.history.redo(world.pid, world.vid, {"actor": "user"})
        assert done.status is HistoryStatus.APPLIED, done.to_dict()
        assert world.scenes_bytes() == expected


async def test_undo_of_select_with_drop_others_brings_every_other_variant_back_exactly(world):
    b = await world.make(S1, "B", headline="B")
    await world.make(S1, "C", headline="C")
    before = world.scenes_bytes()
    await world.ok(select(S1, b, drop_others=True))
    assert "scene_variants" not in world.stored()["scenes"][0] and (await world.variant_scene(S1)).props["label"] == "B"
    assert (await world.history.undo(world.pid, world.vid, {"actor": "user"})).status is HistoryStatus.APPLIED
    assert world.scenes_bytes() == before
    assert (await world.history.redo(world.pid, world.vid, {"actor": "user"})).status is HistoryStatus.APPLIED
    assert "scene_variants" not in world.stored()["scenes"][0]


async def test_removing_a_scene_that_holds_a_set_is_undone_with_its_set(world):
    await world.make(S1, "B", headline="B")
    before = world.scenes_bytes()
    await world.ok({"op": "scene.remove", "scene_id": S1})
    assert (await world.history.undo(world.pid, world.vid, {"actor": "user"})).status is HistoryStatus.APPLIED
    assert world.scenes_bytes() == before


# ------------------------------------------------------------------ bornes

async def test_the_ninth_variant_of_a_scene_is_limit_reached_and_nothing_is_written(world):
    for n in range(MAX_SCENE_VARIANTS - 1):
        await world.ok(create(S1, f"V{n}"))
    before = world.tree()
    result = await world.do(create(S1, "Trop"))
    assert result.status is EditStatus.REFUSED and result.code == C.LIMIT_REACHED.value and "delete one" in result.message
    assert world.tree() == before and (await world.sv.describe(world.pid, world.vid, S1))["count"] == MAX_SCENE_VARIANTS


async def test_the_document_cap_is_a_typed_limit_reached_for_a_preview_and_a_commit_and_the_file_stays_valid(tmp_path):
    world = await World(tmp_path).open(scenes=())
    ids = [f"pss_{n:012x}" for n in range(1, 41)]
    fat = [{**scene_body(scene_id), "controls": scene_body(scene_id)["controls"][:4], "data": {"count": 1, "notes": "n" * 500}}
           for scene_id in ids]
    variant = await world.variant()
    await world.studio.save_variant(world.pid, world.vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": fat, "art_direction_id": None, "score_id": None})
    limit, last_ok = None, None
    for scene_id in ids:
        for n in range(MAX_SCENE_VARIANTS - 1):
            result = await world.do(create(scene_id, f"V{n}"))
            if result.status is EditStatus.REFUSED:
                limit = result
                break
            last_ok = result.revision
        if limit:
            break
    assert limit is not None and limit.code == C.LIMIT_REACHED.value and "256" in limit.message or limit.code == C.LIMIT_REACHED.value
    size = len(world.path.read_bytes())
    assert size <= 256 * 1024 and (await world.variant()).revision == last_ok  # the refused commit wrote nothing; the file parses
    again = await world.do(create(scene_id, "Encore"), mode="preview")  # a preview reports the same refusal as a commit
    assert again.status is EditStatus.REFUSED and again.code == C.LIMIT_REACHED.value
    # the way out is a deletion: it commits, and the same create then fits again
    first = (await world.variant_scene(ids[0])).scene_variants.items[1].variant_id
    await world.ok(delete(ids[0], first))


async def test_a_stored_set_with_a_variant_the_catalog_does_not_know_is_refused_on_save(tmp_path):
    world = await World(tmp_path).open()
    first = await world.ok(create(S1, "B"))
    stored_scene = (await world.variant_scene(S1)).to_dict()
    stored_scene["scene_variants"]["items"][1]["content"]["prefab"] = {"id": "lab.counter", "version": 9}
    current = await world.variant()
    with pytest.raises(PresentationStudioError) as caught:
        await world.studio.save_variant(world.pid, world.vid, {
            "expected_revision": current.revision, "title": current.title, "scenes": [stored_scene],
            "art_direction_id": None, "score_id": None})
    assert caught.value.code is C.PREFAB_UNAVAILABLE and first.committed


async def test_a_stored_variant_pinning_an_existing_other_version_is_accepted_and_selected_with_its_own_values(tmp_path):
    world = await World(tmp_path).open(extra_versions=(2,))
    await world.make(S1, "B")
    stored_scene = (await world.variant_scene(S1)).to_dict()
    stored_scene["scene_variants"]["items"][1]["content"]["prefab"] = {"id": "lab.counter", "version": 2}
    current = await world.variant()
    await world.studio.save_variant(world.pid, world.vid, {
        "expected_revision": current.revision, "title": current.title, "scenes": [stored_scene, scene_body(S2)],
        "art_direction_id": None, "score_id": None})
    other = (await world.variant_scene(S1)).scene_variants.items[1].variant_id
    await world.ok(select(S1, other))
    scene = await world.variant_scene(S1)
    assert scene.prefab.version == 2 and scene.scene_variants.get(
        scene.scene_variants.items[0].variant_id).content["prefab"]["version"] == 1


# ------------------------------------------------------------------ branche : copie fidèle, promotion

async def test_a_branch_carries_the_local_sets_with_the_variant_and_shares_the_pins(world):
    b = await world.make(S1, "B", headline="B headline")
    await world.make(S2, "C")
    published = sorted(p.relative_to(world.env.data / LIBRARY_DIR).as_posix() for p in (world.env.data / LIBRARY_DIR).rglob("*") if p.is_dir())
    answer = await world.variants.create_branch(world.pid, {"title": "Branche"})
    branch = await world.studio.get_variant(world.pid, answer["variant"]["variant_id"])
    source = await world.variant()
    assert [s.to_dict() for s in branch.scenes] == [s.to_dict() for s in source.scenes]  # scenes (sets included) copied
    assert branch.scenes[0].scene_variants.get(b).label == "B"
    assert sorted(p.relative_to(world.env.data / LIBRARY_DIR).as_posix() for p in (world.env.data / LIBRARY_DIR).rglob("*") if p.is_dir()) == published
    # editing the branch's set does not touch the source's
    revision = branch.revision
    result = await world.edit.edit(world.pid, branch.variant_id, request(revision, select(S1, b)))
    assert result.status is EditStatus.APPLIED
    assert (await world.variant_scene(S1)).props["label"] == "Visiteurs"


async def test_archive_and_restore_of_a_variant_with_sets_keep_the_file_to_the_byte(world):
    await world.make(S1, "B", headline="B")
    branch = (await world.variants.create_branch(world.pid, {"title": "Branche"}))["variant"]["variant_id"]
    path = world.file_of(branch)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    plan = await world.variants.plan_archive(world.pid, branch)
    await world.variants.archive(world.pid, branch, {"confirmation": plan["confirmation"]})
    assert not path.exists()
    await world.variants.restore(world.pid, branch)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


async def test_promote_creates_exactly_one_variant_with_provenance_shared_pins_and_leaves_the_source_alone(world):
    b = await world.make(S1, "B", headline="B headline", count=7)
    source_bytes = hashlib.sha256(world.path.read_bytes()).hexdigest()
    published = sorted(p.name for p in (world.env.data / LIBRARY_DIR).rglob("*") if p.is_dir())
    answer = await world.sv.promote(world.pid, world.vid, S1, b, {"title": "Version B", "rationale": "plus direct"})
    assert (answer["scene_id"], answer["scene_variant_id"]) == (S1, b) and answer["activated"] is False
    graph = await world.variants.graph(world.pid)
    assert [n["variant_number"] for n in graph["nodes"]] == [1, 2]  # exactly one new variant
    node = answer["node"]
    assert node["parent_variant_id"] == world.vid and node["sources"] == [world.vid] and node["created_by"] == "user"
    assert b in node["rationale"] and S1 in node["rationale"] and "plus direct" in node["rationale"]
    assert hashlib.sha256(world.path.read_bytes()).hexdigest() == source_bytes  # the original keeps its set, byte for byte
    branch = await world.studio.get_variant(world.pid, node["variant_id"])
    scene = next(s for s in branch.scenes if s.scene_id == S1)
    assert scene.props["label"] == "B headline" and scene.data["count"] == 7 and scene.scene_variants.current_id == b
    assert scene.scene_variants.get(next(i.variant_id for i in scene.scene_variants.items if i.variant_id != b)).content["props"]["label"] == "Visiteurs"
    assert next(s for s in branch.scenes if s.scene_id == S2) == next(s for s in (await world.variant()).scenes if s.scene_id == S2)
    assert sorted(p.name for p in (world.env.data / LIBRARY_DIR).rglob("*") if p.is_dir()) == published  # no prefab published
    assert branch.parent_variant_id == world.vid and branch.revision == 1


async def test_promote_with_activate_and_an_actor_and_the_branch_event_hold_no_label(world):
    b = await world.make(S1, "Secret label", headline="B")
    answer = await world.sv.promote(world.pid, world.vid, S1, b, {"title": "Titre secret", "activate": True, "actor": "brain"})
    assert answer["activated"] is True and answer["node"]["created_by"] == "brain"
    assert (await world.studio.get(world.pid)).presentation.active_variant_id == answer["node"]["variant_id"]
    events = json.dumps([(e[0].value, e[2]) for e in world.emitter.recorded])
    assert "Secret label" not in events and "Titre secret" not in events
    rows = json.dumps(world.sink.rows)
    assert "Secret label" not in rows and "Titre secret" not in rows


async def test_promote_refuses_before_any_write_when_the_target_is_unknown_stale_or_breaks_the_score(tmp_path):
    world = await World(tmp_path).open(score=True)
    b = await world.make(S1, "B")
    before = world.tree()
    await refused(world.sv.promote(world.pid, world.vid, S1, "psx_ffffffffffff", {"title": "X"}), C.UNKNOWN_SCENE_VARIANT)
    await refused(world.sv.promote(world.pid, world.vid, "pss_ffffffffffff", b, {"title": "X"}), C.UNKNOWN_SCENE)
    await refused(world.sv.promote(world.pid, world.vid, S1, b, {"title": "X", "expected_variant_revision": 1}), C.STALE_REVISION)
    await refused(world.sv.promote(world.pid, world.vid, S1, b, {"title": ""}), C.INVALID_PRESENTATION)
    await refused(world.sv.promote(world.pid, world.vid, S1, b, {"title": "X", "bogus": 1}), C.INVALID_PRESENTATION)
    await refused(world.sv.promote(world.pid, world.vid, S1, b, {"title": "X", "actor": "robot"}), C.INVALID_PRESENTATION)
    # B loses the controls the score cites: promoting it would leave the copied score unresolved
    await world.ok(select(S1, b))
    await world.ok({"op": "scene.set_controls", "scene_id": S1, "controls": [COUNT_ONLY]})
    original = next(i.variant_id for i in (await world.variant_scene(S1)).scene_variants.items if i.variant_id != b)
    await world.ok(select(S1, original))
    before = world.tree()
    error = await refused(world.sv.promote(world.pid, world.vid, S1, b, {"title": "X"}), C.SCORE_INCOMPATIBLE)
    assert "score reference" in error.message
    assert world.tree() == before and len((await world.variants.graph(world.pid))["nodes"]) == 1  # no number spent, no file


async def test_selecting_a_variant_that_would_break_the_score_is_refused_but_an_undo_is_never(tmp_path):
    world = await World(tmp_path).open(score=True)
    b = await world.make(S1, "B")
    original = (await world.variant_scene(S1)).scene_variants.current_id
    await world.ok(select(S1, b))
    await world.ok({"op": "scene.set_controls", "scene_id": S1, "controls": [COUNT_ONLY]})  # (the score check is on select, as documented)
    await world.ok(select(S1, original))
    result = await world.do(select(S1, b))
    assert result.status is EditStatus.REFUSED and result.code == C.SCORE_INCOMPATIBLE.value and "select another" in result.message
    # undoing the step that removed the controls is not a "select" and is never blocked by the score
    assert (await world.history.undo(world.pid, world.vid, {"actor": "user"})).status is HistoryStatus.APPLIED


# ------------------------------------------------------------------ événements et traces sans contenu

async def test_the_commit_event_names_the_operation_and_never_a_label_or_a_value(world):
    created = await world.ok(create(S1, "Libellé très privé", rationale="raison privée"))
    await world.ok(select(S1, created.ops[0]["scene_variant_id"]))
    events = [e for e in world.emitter.recorded if e[0] is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED]
    assert [e[2]["op"] for e in events] == [["scene_variant.create"], ["scene_variant.select"]]
    flat = json.dumps([e[2] for e in world.emitter.recorded], default=str)
    assert "privé" not in flat and "psx_" not in flat and all(e[2]["tier"] == "structure" for e in events)
    rows = json.dumps(world.sink.rows, default=str)
    assert "privé" not in rows and "Visiteurs" not in rows


# ------------------------------------------------------------------ protections de pins (01a)

async def test_every_pin_of_a_local_variant_is_in_the_variant_pin_set_and_survives_archive(tmp_path):
    world = await World(tmp_path).open(extra_versions=(2,))
    await world.make(S1, "B")
    stored_scene = (await world.variant_scene(S1)).to_dict()
    stored_scene["scene_variants"]["items"][1]["content"]["prefab"] = {"id": "lab.counter", "version": 2}
    current = await world.variant()
    await world.studio.save_variant(world.pid, world.vid, {
        "expected_revision": current.revision, "title": current.title, "scenes": [stored_scene], "art_direction_id": None,
        "score_id": None})
    index = await world.variants.pin_index()
    assert index[(world.pid, world.vid)] == {("lab.counter", 1), ("lab.counter", 2)}
    branch = (await world.variants.create_branch(world.pid, {"title": "Branche"}))["variant"]["variant_id"]
    plan = await world.variants.plan_archive(world.pid, branch)
    await world.variants.archive(world.pid, branch, {"confirmation": plan["confirmation"]})
    assert (await world.variants.pin_index())[(world.pid, branch)] == {("lab.counter", 1), ("lab.counter", 2)}
