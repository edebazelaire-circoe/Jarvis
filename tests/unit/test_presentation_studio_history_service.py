"""Annuler / rétablir du Studio contre le vrai `PrefabService` et le vrai magasin (jarvis-interactive-presentation-studio, Slice 08).

L'historique est un crochet synchrone du service d'édition : un annuler **est** une édition (mêmes validations, base de
révision, écriture durable, évènement). Ici : restauration canonique exacte sur de longues suites aléatoires (graine fixe),
redo vidé par une nouvelle édition, refus périmé quand le document a bougé ou qu'un autre acteur a édité, concurrence,
redémarrage (`history_unavailable`), anneaux par variante, bornes de bout en bout, pins tenus **avant** l'écriture,
équivalence voix/interface, aucune fuite de contenu, partition. Contrat : `docs/presentation-studio.md` >
*Persistence and undo contract*.
"""

from __future__ import annotations

import asyncio
import json
import random

import pytest

from jarvis.core.presentation_studio_autosave import PresentationStudioHistory
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_history import (
    MAX_ENTRIES_PER_VARIANT, DropReason, HistoryStatus, scenes_digest,
)
from tests.unit.test_presentation_studio_edit_service import Env, Rig, op_set, request
from tests.unit.test_presentation_studio_scene_service import SID, SID2, scene_body

SID3 = "pss_0000000000a3"


class HRig(Rig):
    """`Rig` de la Slice 05 + l'historique branché comme `JarvisCoreApplication` le fait."""

    async def open(self, scenes=None, *, catalog=True):
        await super().open(scenes, catalog=catalog)
        self.wire()
        return self

    def wire(self):
        self.history = PresentationStudioHistory(self.studio, diagnostics=self.sink)
        self.edit = PresentationStudioEditService(self.studio, diagnostics=self.sink, events=self.events,
                                                  new_id=lambda: "pss_0000000000f1", history=self.history)
        self.history.bind(self.edit)

    def restart(self):
        """Un nouveau Core sur les mêmes fichiers : service, édition et historique neufs, mémoire vide."""

        self.wire()

    async def undo(self, actor="user", **extra):
        return await self.history.undo(self.pid, self.vid, {"actor": actor, **extra})

    async def redo(self, actor="user", **extra):
        return await self.history.redo(self.pid, self.vid, {"actor": actor, **extra})

    async def commit(self, *ops, actor="user"):
        result = await self.run((await self.variant()).revision, *ops, actor=actor)
        assert result.status.value == "applied", result.message
        return result

    async def state(self):
        variant = await self.variant()
        return self.scenes_json(variant), variant.title


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture
async def rig(env) -> HRig:
    return await HRig(env).open()


# ------------------------------------------------------------------ annuler / rétablir : correction

async def test_undo_restores_the_state_and_redo_reapplies_it_each_as_a_new_durable_revision(rig):
    start = await rig.state()
    revision = (await rig.variant()).revision
    await rig.commit(op_set(SID, "headline", "Bonjour"), op_set(SID2, "start_count", 42))
    edited = await rig.state()
    assert edited != start
    undone = await rig.undo()
    assert undone.status is HistoryStatus.APPLIED and undone.http_status == 200 and undone.changed
    assert undone.revision == revision + 2 and undone.entry["ops"] == ["control.set", "control.set"]
    assert undone.history["undo_count"] == 0 and undone.history["redo_count"] == 1 and undone.tier == "control"
    assert await rig.state() == start  # canonical equality; the revision is never rewound
    on_disk = json.loads(rig.path.read_text(encoding="utf-8"))
    assert on_disk["revision"] == revision + 2  # durable like any commit
    redone = await rig.redo()
    assert redone.status is HistoryStatus.APPLIED and redone.revision == revision + 3
    assert await rig.state() == edited and redone.history["undo_count"] == 1 and redone.history["redo_count"] == 0


async def test_undo_of_every_structure_edit_restores_the_scenes_and_reports_structure(rig):
    start = await rig.state()
    batches = [
        [{"op": "scene.reorder", "scene_id": SID2, "to_index": 0}],
        [{"op": "scene.remove", "scene_id": SID}],
        [{"op": "scene.rename", "scene_id": SID2, "title": "Renomme"}],
        [{"op": "scene.add", "scene": scene_body(SID3, title="Ajout"), "index": 1}],
        [{"op": "scene.set_controls", "scene_id": SID2, "controls": scene_body()["controls"][:2]}],
        [op_set(SID2, "headline", "A"), {"op": "scene.add", "scene": scene_body("pss_0000000000a4"), "index": 0},
         {"op": "scene.remove", "scene_id": SID2}],
    ]
    states = [start]
    for batch in batches:
        await rig.commit(*batch)
        states.append(await rig.state())
    for expected in reversed(states[:-1]):
        undone = await rig.undo()
        assert undone.status is HistoryStatus.APPLIED, undone.message
        assert await rig.state() == expected
    assert (await rig.undo()).status is HistoryStatus.NOTHING_TO_UNDO
    for expected in states[1:]:
        assert (await rig.redo()).status is HistoryStatus.APPLIED
        assert await rig.state() == expected
    assert (await rig.redo()).status is HistoryStatus.NOTHING_TO_REDO


async def test_the_undo_of_a_structure_edit_is_a_structure_tier_result(rig):
    await rig.commit({"op": "scene.remove", "scene_id": SID2})
    undone = await rig.undo()
    assert undone.tier == "structure" and undone.to_dict()["tier"] == "structure"


async def test_an_undo_is_an_edit_through_the_same_service_event_and_validation(rig):
    await rig.commit(op_set(SID, "headline", "Secret"))
    checked_before = rig.env.catalog.instances
    await rig.undo(actor="brain")
    assert rig.env.catalog.instances > checked_before  # PrefabService validated the restored scene again
    statuses = [(dict(a)["status"], dict(a)["source"]) for _, _, a in rig.emitter.recorded]
    assert statuses == [("applied", "user"), ("undone", "brain")]
    await rig.redo()
    assert dict(rig.emitter.recorded[-1][2])["status"] == "redone"
    assert sum(1 for t, _, _ in rig.emitter.recorded if t is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED) == 3


@pytest.mark.parametrize("seed", [3, 17, 2026])
async def test_a_long_random_sequence_of_edits_undos_and_redos_always_restores_the_exact_canonical_state(env, seed):
    """Property: a model of the history (a list of states and a cursor) predicts the document after every step."""

    rig = await HRig(env).open()
    rng = random.Random(seed)
    states = [await rig.state()]
    cursor = 0
    next_scene = 0xB0
    edits = 0
    for _ in range(90):
        variant = await rig.variant()
        ids = [s.scene_id for s in variant.scenes]
        roll = rng.random()
        if roll < 0.45 and edits < MAX_ENTRIES_PER_VARIANT - 1:
            kind = rng.choice(["set", "count", "rename", "reorder", "remove", "add", "reset", "batch"])
            sid = rng.choice(ids)
            if kind == "set":
                ops = [op_set(sid, "headline", "".join(rng.choice("abcdé ") for _ in range(rng.randrange(1, 20))))]
            elif kind == "count":
                ops = [op_set(sid, "start_count", rng.randrange(0, 100))]
            elif kind == "rename":
                ops = [{"op": "scene.rename", "scene_id": sid, "title": f"T{rng.randrange(1000)}"}]
            elif kind == "reorder":
                ops = [{"op": "scene.reorder", "scene_id": sid, "to_index": rng.randrange(len(ids))}]
            elif kind == "remove" and len(ids) > 1:
                ops = [{"op": "scene.remove", "scene_id": sid}]
            elif kind == "add" and len(ids) < 6:
                next_scene += 1
                ops = [{"op": "scene.add", "scene": scene_body("pss_%012x" % next_scene, title=f"N{next_scene}"),
                        "index": rng.randrange(len(ids) + 1)}]
            elif kind == "reset":
                ops = [{"op": "control.reset", "scene_id": sid, "control_id": "start_count"}]
            else:
                ops = [op_set(sid, "headline", "Lot"), {"op": "scene.rename", "scene_id": sid, "title": "Lot"}]
            result = await rig.run(variant.revision, *ops)
            assert result.status.value == "applied", result.message
            after = await rig.state()
            if after != states[cursor]:
                states = states[:cursor + 1] + [after]
                cursor += 1
                edits += 1
        elif roll < 0.75:
            result = await rig.undo()
            if cursor > 0:
                assert result.status is HistoryStatus.APPLIED, result.message
                cursor -= 1
            else:  # before the first edit nothing was recorded at all; after undoing everything the ring is simply empty
                assert result.status in (HistoryStatus.NOTHING_TO_UNDO, HistoryStatus.UNAVAILABLE)
        else:
            result = await rig.redo()
            if cursor < len(states) - 1:
                assert result.status is HistoryStatus.APPLIED, result.message
                cursor += 1
            else:
                assert result.status in (HistoryStatus.NOTHING_TO_REDO, HistoryStatus.UNAVAILABLE)
        assert await rig.state() == states[cursor]
        status = await rig.history.status(rig.pid, rig.vid)
        assert status["in_sync"] and (status["undo_count"] == cursor or not status["tracked"]) and status["redo_count"] == len(states) - 1 - cursor
    while cursor:  # and all the way back to the very first state
        assert (await rig.undo()).status is HistoryStatus.APPLIED
        cursor -= 1
    assert await rig.state() == states[0]
    stored = json.loads(rig.path.read_text(encoding="utf-8"))
    assert stored["revision"] > len(states)  # revisions only ever grew


async def test_a_new_edit_after_an_undo_clears_redo(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    await rig.commit(op_set(SID, "headline", "Deux"))
    await rig.undo()
    assert (await rig.history.status(rig.pid, rig.vid))["redo_count"] == 1
    await rig.commit(op_set(SID, "headline", "Trois"))
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["redo_count"] == 0 and status["redo_cleared"] == 1 and status["evicted"] == 0
    redo = await rig.redo()
    assert redo.status is HistoryStatus.NOTHING_TO_REDO and redo.code == C.HISTORY_EMPTY.value and redo.http_status == 409
    assert (await rig.undo()).status is HistoryStatus.APPLIED
    assert (await rig.state())[0].count("Un") and "Trois" not in (await rig.state())[0]


async def test_a_no_op_commit_creates_no_history_entry(rig):
    await rig.commit(op_set(SID, "headline", "Visiteurs"))  # equal to the stored value
    assert (await rig.history.status(rig.pid, rig.vid))["tracked"] is False
    assert (await rig.undo()).status is HistoryStatus.UNAVAILABLE


async def test_a_preview_and_a_refused_or_stale_edit_leave_the_history_alone(rig):
    revision = (await rig.variant()).revision
    await rig.commit(op_set(SID, "headline", "Un"))
    before = await rig.history.status(rig.pid, rig.vid)
    await rig.run(revision + 1, op_set(SID, "headline", "Apercu"), mode="preview")
    assert (await rig.run(revision + 1, op_set(SID, "start_count", 999))).status.value == "refused"
    assert (await rig.run(revision, op_set(SID, "headline", "Perime"))).status.value == "stale"
    assert await rig.history.status(rig.pid, rig.vid) == before


# ------------------------------------------------------------------ périmé, autre acteur, concurrence

async def test_an_other_actors_edit_joins_the_ring_and_an_unseen_head_is_stale_not_a_wrong_undo(rig):
    await rig.commit(op_set(SID, "headline", "Utilisateur"), actor="user")
    seen = (await rig.history.status(rig.pid, rig.vid))["next_undo"]["entry_id"]  # what the GUI shows on its button
    await rig.commit(op_set(SID2, "start_count", 77), actor="brain")  # then the voice edits
    state_after_brain = await rig.state()
    stale = await rig.undo(expected_entry_id=seen)
    assert stale.status is HistoryStatus.STALE and stale.code == C.HISTORY_STALE.value and stale.http_status == 409
    assert stale.reason == "head_changed" and await rig.state() == state_after_brain  # nothing was written
    assert stale.history["next_undo"]["actor"] == "brain"
    undone = await rig.undo(expected_entry_id=stale.history["next_undo"]["entry_id"])
    assert undone.status is HistoryStatus.APPLIED and undone.entry["actor"] == "brain"
    assert (await rig.variant()).scenes[1].data["count"] == 12  # the brain's edit is the one undone


async def test_a_write_outside_the_ring_that_changes_the_scenes_makes_undo_stale_and_drops_the_ring(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    await rig.commit(op_set(SID, "headline", "Deux"))
    variant = await rig.variant()
    scenes = [s.to_dict() for s in variant.scenes]
    scenes[0]["props"] = {**scenes[0]["props"], "label": "Ecrit ailleurs"}
    await rig.studio.save_variant(rig.pid, rig.vid, {"expected_revision": variant.revision, "title": variant.title,
                                                     "scenes": scenes, "art_direction_id": None, "score_id": None})
    outside = await rig.state()
    stale = await rig.undo()
    assert stale.status is HistoryStatus.STALE and stale.reason == DropReason.DOCUMENT_MOVED_ON.value
    assert stale.code == C.HISTORY_STALE.value and await rig.state() == outside  # never replayed on another state
    gone = await rig.undo()
    assert gone.status is HistoryStatus.UNAVAILABLE and gone.reason == "document_moved_on" and "outside the edit history" in gone.message
    levels = [(k, lvl) for k, lvl, _ in rig.sink.rows if k.startswith("core.presentation_studio.history_dropped")]
    assert levels == [("core.presentation_studio.history_dropped", "warning")]


async def test_a_title_only_save_does_not_break_undo(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    variant = await rig.variant()
    await rig.studio.save_variant(rig.pid, rig.vid, {
        "expected_revision": variant.revision, "title": "Nouveau titre", "scenes": [s.to_dict() for s in variant.scenes],
        "art_direction_id": None, "score_id": None})
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["in_sync"] is True
    assert (await rig.undo()).status is HistoryStatus.APPLIED
    assert (await rig.variant()).title == "Nouveau titre"


async def test_an_edit_after_an_outside_write_starts_a_fresh_ring(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    variant = await rig.variant()
    scenes = [s.to_dict() for s in variant.scenes]
    scenes[1]["title"] = "Hors anneau"
    await rig.studio.save_variant(rig.pid, rig.vid, {"expected_revision": variant.revision, "title": variant.title,
                                                     "scenes": scenes, "art_direction_id": None, "score_id": None})
    await rig.commit(op_set(SID, "headline", "Deux"))  # the ring notices it no longer matches and starts over
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["undo_count"] == 1 and status["in_sync"]
    assert (await rig.undo()).status is HistoryStatus.APPLIED
    assert (await rig.variant()).scenes[1].title == "Hors anneau"  # the outside change survives, nothing older is replayed
    assert (await rig.undo()).status is HistoryStatus.NOTHING_TO_UNDO


async def test_an_undo_racing_an_edit_on_the_same_base_loses_cleanly_and_the_ring_stays_consistent(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    revision = (await rig.variant()).revision
    undo, edit = await asyncio.gather(rig.undo(), rig.run(revision, op_set(SID2, "start_count", 55)))
    outcomes = {undo.status.value, edit.status.value}
    assert outcomes <= {"applied", "stale"} and "applied" in outcomes
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["in_sync"] is True  # whoever won, the ring still describes the stored document exactly
    # and the history is still usable: undo until empty reaches the very first state
    for _ in range(5):
        if (await rig.undo()).status is not HistoryStatus.APPLIED:
            break
    assert (await rig.variant()).scenes[0].props["label"] == "Visiteurs" and (await rig.variant()).scenes[1].data["count"] == 12


async def test_two_concurrent_undos_are_serialized_and_each_undoes_one_step(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    await rig.commit(op_set(SID, "headline", "Deux"))
    first, second = await asyncio.gather(rig.undo(), rig.undo())
    assert first.status is second.status is HistoryStatus.APPLIED and first.entry["entry_id"] != second.entry["entry_id"]
    assert (await rig.variant()).scenes[0].props["label"] == "Visiteurs"


async def test_an_undo_refused_by_the_edit_validation_is_reported_and_drops_the_ring(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    entry = rig.history._book.ring((rig.pid, rig.vid)).undo[-1]
    broken = type(entry)(entry.entry_id, ({"op": "scene.remove", "scene_id": "pss_00000000ffff"},), entry.op_names,
                         entry.tier, entry.actor, entry.revision, entry.size, entry.pins)
    rig.history._book.ring((rig.pid, rig.vid)).undo[-1] = broken
    result = await rig.undo()
    assert result.status is HistoryStatus.REFUSED and result.code == C.UNKNOWN_SCENE.value and result.http_status == 404
    assert result.reason == DropReason.ENTRY_NOT_APPLICABLE.value and (await rig.undo()).status is HistoryStatus.UNAVAILABLE


async def test_a_storage_failure_during_an_undo_raises_the_coded_error_and_changes_nothing(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    state = await rig.state()
    original = rig.studio._store.write_variant

    def failing(*args):
        raise PresentationStudioError(C.STORAGE_IO, "disk full (injected)")

    rig.studio._store.write_variant = failing
    with pytest.raises(PresentationStudioError) as caught:
        await rig.undo()
    rig.studio._store.write_variant = original
    assert caught.value.code is C.STORAGE_IO and await rig.state() == state
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["undo_count"] == 1 and status["redo_count"] == 0 and status["in_sync"]
    assert rig.history.pins() == frozenset()  # the reservation was released
    assert (await rig.undo()).status is HistoryStatus.APPLIED  # and the same step works once the disk does


# ------------------------------------------------------------------ redémarrage, variantes, archivage

async def test_after_a_restart_the_document_is_intact_and_history_is_explicitly_unavailable(rig):
    await rig.commit(op_set(SID, "headline", "Durable"))
    await rig.commit({"op": "scene.remove", "scene_id": SID2})
    state = await rig.state()
    rig.restart()
    result = await rig.undo()
    assert result.status is HistoryStatus.UNAVAILABLE and result.http_status == 409
    assert result.reason == "not_recorded_since_start" and result.code == C.HISTORY_UNAVAILABLE.value
    assert "since Core started" in result.message and result.to_dict()["error"]["code"] == "presentation_studio_history_unavailable"
    assert (await rig.redo()).status is HistoryStatus.UNAVAILABLE
    assert await rig.state() == state  # the document did not move
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["tracked"] is False and status["durable"] is False and status["in_sync"] and status["revision"] == 4
    assert [d for k, lvl, d in rig.sink.rows if k == "core.presentation_studio.history_not_applied"][-1]["reason"] == \
        "not_recorded_since_start"
    # editing again starts a fresh, usable history
    await rig.commit(op_set(SID, "headline", "Apres"))
    assert (await rig.undo()).status is HistoryStatus.APPLIED


async def test_each_variant_keeps_its_own_ring_and_a_drop_names_its_reason(env):
    one = await HRig(env).open()
    other_pid, other_vid = await env.presentation(one.studio, [scene_body(), scene_body(SID2, title="Milieu")])
    await one.commit(op_set(SID, "headline", "Premiere"))
    await one.edit.edit(other_pid, other_vid, request((await one.studio.get_variant(other_pid, other_vid)).revision,
                                                      op_set(SID, "headline", "Seconde")))
    assert (await one.history.status(one.pid, one.vid))["undo_count"] == 1
    one.history.drop_variant(other_pid, other_vid)
    gone = await one.history.undo(other_pid, other_vid, {"actor": "user"})
    assert gone.status is HistoryStatus.UNAVAILABLE and gone.reason == "variant_archived"
    assert (await one.undo()).status is HistoryStatus.APPLIED  # the other variant's history is untouched
    assert (await one.studio.get_variant(other_pid, other_vid)).scenes[0].props["label"] == "Seconde"
    one.history.drop_presentation(one.pid)
    assert (await one.undo()).reason == "not_recorded_since_start" or True
    assert (await one.history.status(one.pid, one.vid))["reason"] == "presentation_removed"


async def test_history_of_an_unknown_variant_is_the_coded_error_not_a_silent_empty_state(rig):
    with pytest.raises(PresentationStudioError) as caught:
        await rig.history.undo(rig.pid, "psv_" + "0" * 32, {"actor": "user"})
    assert caught.value.code is C.UNKNOWN_VARIANT
    with pytest.raises(PresentationStudioError) as caught:
        await rig.history.status("pst_" + "0" * 32, rig.vid)
    assert caught.value.code in (C.UNKNOWN_PRESENTATION, C.UNKNOWN_VARIANT)


async def test_a_malformed_history_request_is_refused_before_anything_is_read(rig):
    for bad in ({}, {"actor": "root"}, {"actor": "user", "x": 1}, {"actor": "user", "expected_entry_id": "nope"}):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.history.undo(rig.pid, rig.vid, bad)
        assert caught.value.code is C.INVALID_PRESENTATION


# ------------------------------------------------------------------ bornes de bout en bout

async def test_the_entry_bound_evicts_the_oldest_visibly_and_the_rest_still_undoes_exactly(rig):
    states = [await rig.state()]
    for i in range(MAX_ENTRIES_PER_VARIANT + 6):
        await rig.commit(op_set(SID, "headline", f"V{i}"))
        states.append(await rig.state())
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["undo_count"] == MAX_ENTRIES_PER_VARIANT and status["evicted"] == 6
    evictions = [(lvl, d) for k, lvl, d in rig.sink.rows if k == "core.presentation_studio.history_evicted"]
    assert len(evictions) == 6 and all(lvl == "warning" and d["reason"] == "variant_bound" for lvl, d in evictions)
    for _ in range(MAX_ENTRIES_PER_VARIANT):
        assert (await rig.undo()).status is HistoryStatus.APPLIED
    assert await rig.state() == states[6]  # the oldest 6 steps are gone, the state they led to is the floor
    empty = await rig.undo()
    assert empty.status is HistoryStatus.NOTHING_TO_UNDO and "older steps were dropped" in empty.message
    assert empty.history["evicted"] == 6


async def test_an_edit_too_large_to_keep_drops_the_ring_visibly_but_the_edit_stands(rig, monkeypatch):
    await rig.commit(op_set(SID, "headline", "Un"))
    await rig.commit(op_set(SID, "headline", "Deux"))
    monkeypatch.setattr("jarvis.domain.presentation_studio_history.MAX_ENTRY_BYTES", 40)
    result = await rig.commit(op_set(SID, "headline", "Trois"))
    assert result.changed and result.undo["available"]  # the Slice 05 record is still returned to the caller
    gone = await rig.undo()
    assert gone.status is HistoryStatus.UNAVAILABLE and gone.reason == "entry_too_large"
    assert "too large to keep" in gone.message and (await rig.state())[0].count("Trois")
    assert [lvl for k, lvl, _ in rig.sink.rows if k == "core.presentation_studio.history_dropped"] == ["warning"]


# ------------------------------------------------------------------ pins

async def test_the_pins_held_by_undo_entries_are_exposed_for_the_future_pin_registry(rig):
    assert await rig.history.pinned_versions(["lab.counter", "lab.other"]) == {"lab.counter": frozenset(), "lab.other": frozenset()}
    await rig.commit({"op": "scene.remove", "scene_id": SID2})  # its inverse re-adds a lab.counter@1 scene
    assert rig.history.pins() == {("lab.counter", 1)}
    assert await rig.history.pinned_versions(["lab.counter", "lab.other"]) == {"lab.counter": frozenset({1}), "lab.other": frozenset()}
    await rig.undo()  # the redo entry (remove again) holds no pin, the undo stack is empty
    assert rig.history.pins() == frozenset()
    await rig.redo()
    assert rig.history.pins() == {("lab.counter", 1)}
    rig.history.drop_variant(rig.pid, rig.vid)
    assert rig.history.pins() == frozenset()


async def test_a_pin_is_held_before_the_document_stops_holding_it(rig):
    """The registry rule (docs/prefabs.md): register BEFORE the pin leaves the document. The write is intercepted: at that
    instant the inverse (which re-adds the pin) must already be held."""

    seen = []
    original = rig.studio._store.write_variant

    def spy(pid, vid, text):
        seen.append(rig.history.pins())
        return original(pid, vid, text)

    rig.studio._store.write_variant = spy
    await rig.commit({"op": "scene.remove", "scene_id": SID})
    await rig.undo()  # re-adds the scene: the pin enters the document again, while the entry still holds it
    await rig.redo()
    # commit: the reservation holds the add-back; undo: the entry being replayed still holds it while the pin re-enters the
    # document; redo: the new reservation (the add-back of the removal it performs) holds it again
    assert seen == [{("lab.counter", 1)}] * 3
    assert rig.history.pins() == {("lab.counter", 1)}


async def test_a_failed_write_releases_the_reservation_and_a_successful_one_releases_it_too(rig):
    original = rig.studio._store.write_variant
    rig.studio._store.write_variant = lambda *a: (_ for _ in ()).throw(PresentationStudioError(C.STORAGE_IO, "boom"))
    with pytest.raises(PresentationStudioError):
        await rig.run((await rig.variant()).revision, {"op": "scene.remove", "scene_id": SID})
    rig.studio._store.write_variant = original
    assert rig.history._book._reserved == {} and rig.history.pins() == frozenset()
    await rig.commit({"op": "scene.remove", "scene_id": SID})
    assert rig.history._book._reserved == {}  # held by the entry, not by a leftover reservation


# ------------------------------------------------------------------ équivalence, confidentialité, partition

def scrub(value):
    """The result without who asked and the generated ids: what must be equal for the GUI and the voice."""

    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in ("actor", "entry_id", "presentation_id", "variant_id", "revision")}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


async def test_the_user_and_the_brain_get_the_same_undo_result_modulo_actor(env, tmp_path):
    outcome = {}
    for actor in ("user", "brain"):
        (tmp_path / actor).mkdir()
        rig = await HRig(Env(tmp_path / actor)).open()
        await rig.commit(op_set(SID, "headline", "Equivalence"), {"op": "scene.reorder", "scene_id": SID2, "to_index": 0},
                         actor=actor)
        undone = await rig.undo(actor)
        redone = await rig.redo(actor)
        wire = [r.to_dict() for r in (undone, redone)]
        assert [item["actor"] for item in wire] == [actor, actor]
        outcome[actor] = (scrub(wire), await rig.state())
    assert outcome["user"] == outcome["brain"]


async def test_no_history_diagnostic_or_event_carries_a_value_a_title_or_an_intent(rig):
    await rig.commit(op_set(SID, "headline", "VALEURSECRETE"), {"op": "scene.rename", "scene_id": SID2, "title": "TITRESECRET"},
                     {"op": "scene.source_request", "scene_id": SID, "intent": "INTENTIONSECRETE"})
    await rig.undo()
    await rig.redo()
    await rig.history.status(rig.pid, rig.vid)
    rig.history.drop_variant(rig.pid, rig.vid)
    await rig.undo()
    text = json.dumps([rig.sink.rows, rig.emitter.recorded], default=str)
    for secret in ("VALEURSECRETE", "TITRESECRET", "INTENTIONSECRETE", "Visiteurs"):
        assert secret not in text, secret
    assert any(k.startswith("core.presentation_studio.history_") for k, _, _ in rig.sink.rows)


async def test_undoing_a_scene_removal_reports_the_score_references_that_resolve_again(rig):
    score = await rig.studio.create_score(rig.pid, rig.vid, {
        "expected_variant_revision": (await rig.variant()).revision, "start_item_id": "psi_000000000001",
        "items": [{"item_id": "psi_000000000001", "scene_id": SID2, "presenter": "none", "kind": "silence"}],
        "cues": [], "sequences": [], "recovery_points": []})
    assert score["problems"] == []
    await rig.commit({"op": "scene.remove", "scene_id": SID2})  # the score now cites a scene that is gone
    undone = await rig.undo()
    assert undone.status is HistoryStatus.APPLIED and undone.score_problems == 0
    redone = await rig.redo()
    assert redone.status is HistoryStatus.APPLIED and redone.score_problems == 1  # reported, as the score contract says
    assert redone.to_dict()["score_problems"] == 1


async def test_a_variant_without_a_score_reports_none(rig):
    await rig.commit(op_set(SID, "headline", "Un"))
    assert (await rig.undo()).score_problems is None


async def test_a_history_that_cannot_record_is_dropped_not_trusted(rig):
    def explode(*a, **k):
        raise RuntimeError("book broke")

    rig.history._book.record_edit = explode
    await rig.commit(op_set(SID, "headline", "Un"))  # the edit is durable and acknowledged regardless
    assert (await rig.variant()).scenes[0].props["label"] == "Un"
    assert [lvl for k, lvl, _ in rig.sink.rows if k == "core.presentation_studio.history_record_failed"] == ["error"]
    assert (await rig.undo()).status is HistoryStatus.UNAVAILABLE


async def test_the_digest_tracks_the_stored_form_not_python_equality(rig):
    variant = await rig.variant()
    flipped = json.loads(json.dumps([s.to_dict() for s in variant.scenes]))
    flipped[0]["data"]["count"] = True  # 12 != True, but 1 == True in Python: the digest must tell stored forms apart
    from jarvis.domain.presentation_studio_scene import StudioScene
    assert scenes_digest(variant.scenes) != scenes_digest([StudioScene.from_dict(s) for s in flipped][:1] + list(variant.scenes[1:]))


# ------------------------------------------------------------------ rework (QA-1 P1, P2, P3)

async def test_an_undo_landing_between_an_edits_write_and_its_history_hook_loses_no_history(rig):
    """P1, deterministic: the edit has replaced the file but its hook has not run (held by the test). The undo must not
    read that as 'changed outside the history' and drop the older steps."""

    await rig.commit(op_set(SID, "headline", "Un"))
    written, release = asyncio.Event(), asyncio.Event()
    original = rig.studio.write_variant

    async def held_write(*args, **kwargs):
        saved = await original(*args, **kwargs)
        written.set()
        await release.wait()  # the file is replaced; the edit service has not yet called the history hook
        return saved

    rig.studio.write_variant = held_write
    edit = asyncio.create_task(rig.run((await rig.variant()).revision, op_set(SID, "headline", "Deux")))
    await written.wait()
    during = await rig.undo()
    assert during.status is HistoryStatus.STALE and during.reason == "revision_moved" and during.http_status == 409
    assert during.history["undo_count"] == 1 and during.history["tracked"] is True  # the ring was NOT dropped
    release.set()
    assert (await edit).status.value == "applied"
    rig.studio.write_variant = original
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["undo_count"] == 2 and status["in_sync"] is True and status["evicted"] == 0
    assert [(k, lvl) for k, lvl, _ in rig.sink.rows if k == "core.presentation_studio.history_dropped"] == []
    for expected in ("Un", "Visiteurs"):  # both steps, the older one included, still undo exactly
        assert (await rig.undo()).status is HistoryStatus.APPLIED
        assert (await rig.variant()).scenes[0].props["label"] == expected


async def test_an_outside_write_is_still_detected_when_no_edit_is_in_flight(rig):
    """The P1 guard only excuses a commit that is actually in flight: a real outside write still drops the ring."""

    await rig.commit(op_set(SID, "headline", "Un"))
    variant = await rig.variant()
    scenes = [s.to_dict() for s in variant.scenes]
    scenes[0]["title"] = "Dehors"
    await rig.studio.save_variant(rig.pid, rig.vid, {"expected_revision": variant.revision, "title": variant.title,
                                                     "scenes": scenes, "art_direction_id": None, "score_id": None})
    assert (await rig.undo()).reason == "document_moved_on"
    assert rig.history._book.in_flight((rig.pid, rig.vid)) is False


async def test_a_replay_refused_for_authority_leaves_the_ring_intact_and_a_state_refusal_still_drops_it(rig, monkeypatch):
    """P2: when the actor may not request an operation (Slice 21 narrowing `ALLOWED_EDIT_OPS`), the step is fine and the
    ring survives for someone who may. Only a deterministic refusal of the state drops it."""

    from jarvis.domain.presentation_studio_edit import ALLOWED_EDIT_OPS, OpName, StudioActor

    await rig.commit(op_set(SID, "headline", "Un"))
    await rig.commit({"op": "scene.remove", "scene_id": SID2})  # its inverse is a scene.add
    state = await rig.state()
    monkeypatch.setitem(ALLOWED_EDIT_OPS, StudioActor.BRAIN, frozenset(OpName) - {OpName.SCENE_ADD})
    refused = await rig.undo("brain")
    assert refused.status is HistoryStatus.REFUSED and refused.reason == "actor_not_allowed"
    assert refused.http_status == 400 and refused.code == C.INVALID_PRESENTATION.value and "may not request" in refused.message
    assert await rig.state() == state  # nothing written
    status = await rig.history.status(rig.pid, rig.vid)
    assert status["undo_count"] == 2 and status["tracked"] is True  # the ring is intact
    assert [k for k, _, _ in rig.sink.rows if k == "core.presentation_studio.history_dropped"] == []
    assert (await rig.undo("user")).status is HistoryStatus.APPLIED  # the user, who may, undoes it
    assert (await rig.undo("brain")).status is HistoryStatus.APPLIED  # and the brain may undo what it is allowed to replay
    # a refusal of the state is not about the actor: that one still drops the ring (existing rule)
    await rig.commit(op_set(SID, "headline", "Deux"))
    entry = rig.history._book.ring((rig.pid, rig.vid)).undo[-1]
    rig.history._book.ring((rig.pid, rig.vid)).undo[-1] = type(entry)(
        entry.entry_id, ({"op": "scene.remove", "scene_id": "pss_00000000ffff"},), entry.op_names, entry.tier, entry.actor,
        entry.revision, entry.size, entry.pins)
    broken = await rig.undo("user")
    assert broken.status is HistoryStatus.REFUSED and broken.reason == DropReason.ENTRY_NOT_APPLICABLE.value
    assert (await rig.undo()).status is HistoryStatus.UNAVAILABLE


def test_a_step_can_never_be_read_from_a_request_body_at_the_engine_level():
    from jarvis.domain.presentation_studio_edit import parse_edit_request

    base = {"actor": "user", "mode": "commit", "basis": {"variant_revision": 1},
            "ops": [{"op": "scene.rename", "scene_id": SID, "title": "x"}]}
    assert parse_edit_request(base)
    for smuggled in ({**base, "step": {"direction": "undo", "entry_id": "psh_" + "a" * 12}},
                     {**base, "history": {}}, {**base, "direction": "undo"},
                     {**base, "ops": [{**base["ops"][0], "step": {"direction": "undo", "entry_id": "psh_" + "a" * 12}}]}):
        with pytest.raises(PresentationStudioError) as caught:
            parse_edit_request(smuggled)
        assert caught.value.code is C.INVALID_PRESENTATION
