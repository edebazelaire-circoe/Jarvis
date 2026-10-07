"""API d'edition semantique du Studio contre le vrai `PrefabService` (jarvis-interactive-presentation-studio, Slice 05).

Magasin de fichiers et catalogue reels sous `tmp_path` : equivalence voix/interface, apercu qui ne persiste jamais, base
perimee, controles invalides, transaction tout-ou-rien avec panne injectee, annulation (rejouer l'inverse), concurrence,
demandes de source, evenements sans contenu, propositions de controles, validation hors verrou.
Contrat : `docs/presentation-studio.md` > *Semantic edit contract*.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading

import pytest

from jarvis.core.presentation_studio_edit import MAX_SOURCE_REQUESTS, PresentationStudioEditService
from jarvis.core.presentation_studio_events import StudioEditEvents
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.prefab import PrefabInstanceRef, canonical_json, parse_manifest
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import EditStatus
from jarvis.ports.prefabs import PrefabStoreErrorCode
from tests.fakes.prefabs import candidate
from tests.unit.test_presentation_studio_scene_service import CONTROLS, SID, SID2, Clock, Env, Sink, scene_body

NO_DEFAULT = [c for c in CONTROLS if c["control_id"] != "start_count"] + [
    {"control_id": "start_count", "path": "data.count", "label": "Valeur", "group": "content",
     "bounds": {"min": 0, "max": 100}}]


def op_set(scene_id, control_id, value, **extra):
    return {"op": "control.set", "scene_id": scene_id, "control_id": control_id, "value": value, **extra}


def request(revision, *ops, actor="user", mode="commit"):
    return {"actor": actor, "mode": mode, "basis": {"variant_revision": revision}, "ops": list(ops)}


class Events:
    """Faux emetteur de Core : garde ce que `StudioEditEvents` lui donne."""

    def __init__(self) -> None:
        self.recorded: list[tuple[T, tuple[str, ...], dict]] = []

    def record(self, event_type, *, producer, conversation_id, source_ids, occurred_at, attributes, **_):
        self.recorded.append((event_type, source_ids, dict(attributes)))
        return "cev-" + "0" * 64


class Rig:
    def __init__(self, env: Env, *, conversation: str | None = "conv-1") -> None:
        self.env = env
        self.emitter = Events()
        self.events = StudioEditEvents(self.emitter, lambda: conversation)

    async def open(self, scenes=None, *, catalog=True):
        self.studio = await self.env.service(catalog=catalog)
        self.sink = self.env.sink
        self.edit = PresentationStudioEditService(self.studio, diagnostics=self.sink, events=self.events,
                                                  new_id=lambda: "pss_0000000000f1")
        self.pid, self.vid = await self.env.presentation(
            self.studio, [scene_body(), scene_body(SID2, title="Milieu")] if scenes is None else scenes)
        return self

    @property
    def path(self):
        return self.env.variant_file(self.pid, self.vid)

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    async def variant(self):
        return await self.studio.get_variant(self.pid, self.vid)

    async def run(self, revision, *ops, **kw):
        return await self.edit.edit(self.pid, self.vid, request(revision, *ops, **kw))

    def scenes_json(self, variant) -> str:
        return canonical_json([s.to_dict() for s in variant.scenes])


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


@pytest.fixture
async def rig(env) -> Rig:
    return await Rig(env).open()


# ------------------------------------------------------------------ commit et apercu

async def test_a_commit_goes_through_the_same_validation_as_save_and_updates_the_canonical_state(rig):
    before = await rig.variant()
    result = await rig.run(before.revision, op_set(SID, "headline", "Bonjour"), op_set(SID, "start_count", 42))
    assert (result.status, result.committed, result.changed, result.revision) == (EditStatus.APPLIED, True, True,
                                                                                 before.revision + 1)
    after = await rig.variant()
    assert after.revision == before.revision + 1 and after.scenes[0].props["label"] == "Bonjour"
    assert after.scenes[0].data["count"] == 42 and after.scenes[1] == before.scenes[1]
    stored = json.loads(rig.path.read_text(encoding="utf-8"))
    assert stored["scenes"][0]["props"]["label"] == "Bonjour" and stored["revision"] == after.revision
    # the validation is the save validation: PrefabService was asked about the changed scene
    assert rig.env.catalog.instances > 0 and rig.sink.of("core.presentation_studio.edit_committed")


async def test_a_preview_computes_the_result_and_persists_nothing_at_all(rig):
    before_digest, before = rig.digest(), await rig.variant()
    saved_before = len(rig.sink.of("core.presentation_studio.saved"))
    result = await rig.run(before.revision, op_set(SID, "headline", "Apercu"), op_set(SID2, "start_count", 7),
                           {"op": "scene.source_request", "scene_id": SID, "intent": "glow"}, mode="preview")
    assert result.status is EditStatus.APPLIED and result.committed is False and result.changed is True
    assert result.revision == before.revision and result.undo is None
    assert result.ops[0]["after"] == "Apercu" and result.tier.value == "source"
    assert rig.digest() == before_digest  # not a byte
    assert (await rig.variant()).revision == before.revision
    assert len(rig.sink.of("core.presentation_studio.saved")) == saved_before
    assert rig.emitter.recorded == [] and rig.edit.pending_source_requests() == ()
    assert rig.sink.of("core.presentation_studio.edit_previewed") and not rig.sink.of("core.presentation_studio.edit_committed")
    assert result.to_dict()["source_requests"] == [{"request_id": result.ops[2]["request_id"], "scene_id": SID, "recorded": False}]


async def test_a_preview_is_validated_like_a_commit(rig):
    revision = (await rig.variant()).revision
    refused = await rig.run(revision, op_set(SID, "start_count", 999), mode="preview")
    assert refused.status is EditStatus.REFUSED and refused.code == C.VALUE_REFUSED.value
    stale = await rig.run(revision + 5, op_set(SID, "headline", "x"), mode="preview")
    assert stale.status is EditStatus.STALE


async def test_a_no_op_commit_writes_nothing_and_keeps_the_revision(rig):
    before = await rig.variant()
    digest = rig.digest()
    result = await rig.run(before.revision, op_set(SID, "headline", "Visiteurs"))
    assert (result.status, result.changed, result.committed, result.undo) == (EditStatus.APPLIED, False, True, None)
    assert result.revision == before.revision and rig.digest() == digest


# ------------------------------------------------------------------ equivalence voix / interface

async def test_the_same_operations_from_either_actor_give_the_same_canonical_state(env, tmp_path):
    ops = [op_set(SID, "headline", "Equivalence"), op_set(SID2, "start_count", 33),
           {"op": "control.reset", "scene_id": SID, "control_id": "density"},
           {"op": "scene.rename", "scene_id": SID2, "title": "Renomme"},
           {"op": "scene.reorder", "scene_id": SID2, "to_index": 0},
           {"op": "scene.add", "scene": scene_body("pss_0000000000b1", title="Ajout"), "index": 1},
           {"op": "scene.remove", "scene_id": SID}]
    outcome = {}
    for actor in ("user", "brain"):
        (tmp_path / actor).mkdir()
        rig = await Rig(Env(tmp_path / actor)).open()
        revision = (await rig.variant()).revision
        result = await rig.run(revision, *ops, actor=actor)
        assert result.status is EditStatus.APPLIED, result.message
        variant = await rig.variant()
        wire = result.to_dict()
        outcome[actor] = (rig.scenes_json(variant), variant.revision, wire["ops"], wire["undo"]["ops"], wire["tier"],
                          {k: v for k, v in wire.items() if k not in ("actor", "presentation_id", "variant_id", "undo", "ops")})
    assert outcome["user"] == outcome["brain"]


async def test_the_actor_is_recorded_on_the_event_not_in_the_state(rig):
    revision = (await rig.variant()).revision
    await rig.run(revision, op_set(SID, "headline", "A"), actor="brain")
    ((event_type, _, attributes),) = rig.emitter.recorded
    assert event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED and attributes["source"] == "brain"
    assert "actor" not in json.loads(rig.path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ base perimee, ids, controles

async def test_a_stale_basis_is_rejected_and_nothing_is_written(rig):
    revision = (await rig.variant()).revision
    first = await rig.run(revision, op_set(SID, "headline", "Premier"))
    assert first.status is EditStatus.APPLIED
    digest = rig.digest()
    stale = await rig.run(revision, op_set(SID, "headline", "Perime"))
    assert stale.status is EditStatus.STALE and stale.code == C.STALE_REVISION.value
    assert stale.revision == revision + 1 and "read it again" in stale.message
    assert stale.http_status == 409 and rig.digest() == digest
    assert len(rig.emitter.recorded) == 1  # only the first commit made an event
    assert rig.sink.of("core.presentation_studio.edit_stale")


async def test_a_precondition_on_the_current_value_makes_the_edit_stale(rig):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, op_set(SID, "headline", "X", if_current="Quelqu'un d'autre"))
    assert result.status is EditStatus.STALE and result.failed_index == 0 and rig.digest() == digest
    ok = await rig.run(revision, op_set(SID, "headline", "X", if_current="Visiteurs"))
    assert ok.status is EditStatus.APPLIED


@pytest.mark.parametrize("operation, code", [
    (op_set("pss_00000000ffff", "headline", "x"), C.UNKNOWN_SCENE),
    (op_set(SID, "inconnu", "x"), C.UNKNOWN_CONTROL),
    (op_set(SID, "start_count", 101), C.VALUE_REFUSED),
    (op_set(SID, "start_count", True), C.VALUE_REFUSED),
    (op_set(SID, "start_count", 1.0), C.VALUE_REFUSED),
    (op_set(SID, "density", "full"), C.VALUE_REFUSED),  # outside the curated choices
    (op_set(SID, "headline", "x" * 41), C.VALUE_REFUSED),
    ({"op": "scene.remove", "scene_id": "pss_00000000ffff"}, C.UNKNOWN_SCENE),
    ({"op": "scene.add", "scene": scene_body(SID)}, C.INVALID_PRESENTATION),
])
async def test_an_invalid_operation_is_refused_with_its_code_and_writes_nothing(rig, operation, code):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, operation)
    assert result.status is EditStatus.REFUSED and result.code == code.value and result.failed_index == 0
    assert rig.digest() == digest and rig.emitter.recorded == []
    assert result.to_dict()["error"]["code"] == code.value


async def test_an_added_scene_that_does_not_fit_its_prefab_is_refused_by_the_save_validation(rig):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    bad = scene_body("pss_0000000000b1", prefab=("lab.counter", 9))
    with pytest.raises(PresentationStudioError) as caught:
        await rig.run(revision, {"op": "scene.add", "scene": bad})
    assert caught.value.code is C.PREFAB_UNAVAILABLE and rig.digest() == digest
    incompatible = scene_body("pss_0000000000b2", data={})  # `count` is required by the manifest
    result = await rig.run(revision, {"op": "scene.add", "scene": incompatible})
    assert result.status is EditStatus.REFUSED and result.code == C.SCENE_INCOMPATIBLE.value
    assert result.failed_index is None and rig.digest() == digest


async def test_unknown_ids_and_malformed_bodies_raise_the_coded_envelope_errors(rig):
    revision = (await rig.variant()).revision
    good = request(revision, op_set(SID, "headline", "x"))
    for pid, vid, code in (("pst_" + "0" * 32, rig.vid, C.UNKNOWN_VARIANT),  # the store answers "variant not stored" for an absent folder
                           (rig.pid, "psv_" + "0" * 32, C.UNKNOWN_VARIANT),
                           ("nope", rig.vid, C.UNKNOWN_PRESENTATION)):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.edit.edit(pid, vid, good)
        assert caught.value.code is code
    for body in ({**good, "actor": "system"}, {**good, "basis": {}}, {**good, "ops": []}, [], None):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.edit.edit(rig.pid, rig.vid, body)
        assert caught.value.code is C.INVALID_PRESENTATION


async def test_reserved_keys_never_reach_the_stored_state(env):
    rig = await Rig(env).open([scene_body(anchors=[])])
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, op_set(SID, "start_count", {"__proto__": {"polluted": True}}))
    assert result.status is EditStatus.REFUSED and rig.digest() == digest
    history = await rig.run(revision, {"op": "scene.set_controls", "scene_id": SID, "controls": [
        {"control_id": "h", "path": "data.history", "label": "H", "group": "content"}]})
    assert history.status is EditStatus.APPLIED
    revision = history.revision
    sneaky = await rig.run(revision, op_set(SID, "h", [{"delta": 1, "constructor": {"prototype": 1}}]))
    assert sneaky.status is EditStatus.REFUSED and sneaky.code == C.INVALID_PRESENTATION.value
    assert "polluted" not in rig.path.read_text(encoding="utf-8") and "constructor" not in rig.path.read_text(encoding="utf-8")


async def test_reset_without_a_default_on_a_required_input_is_refused_by_the_prefab_and_cancels_the_batch(env):
    rig = await Rig(env).open([scene_body(controls=NO_DEFAULT)])
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, {"op": "scene.rename", "scene_id": SID, "title": "Jamais ecrit"},
                           {"op": "control.reset", "scene_id": SID, "control_id": "start_count"})
    assert result.status is EditStatus.REFUSED and result.code == C.SCENE_INCOMPATIBLE.value
    assert rig.digest() == digest and (await rig.variant()).scenes[0].title == "Ouverture"


# ------------------------------------------------------------------ transaction

async def test_a_refusal_in_the_middle_of_a_batch_writes_nothing_of_the_earlier_operations(rig):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, op_set(SID, "headline", "A"), {"op": "scene.rename", "scene_id": SID2, "title": "B"},
                           op_set(SID, "start_count", -5), {"op": "scene.remove", "scene_id": SID2})
    assert result.status is EditStatus.REFUSED and result.failed_index == 2
    assert rig.digest() == digest and (await rig.variant()).revision == revision and rig.emitter.recorded == []


async def test_a_storage_failure_during_the_write_leaves_the_old_state_and_records_nothing(rig, monkeypatch):
    revision = (await rig.variant()).revision
    digest = rig.digest()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(rig.studio._store, "write_variant", boom)
    with pytest.raises(PresentationStudioError) as caught:
        await rig.run(revision, op_set(SID, "headline", "Perdu"), {"op": "scene.source_request", "scene_id": SID, "intent": "glow"})
    assert caught.value.code is C.STORAGE_IO and "disk full" in caught.value.message
    assert rig.digest() == digest and rig.edit.pending_source_requests() == ()
    assert [e[0] for e in rig.emitter.recorded] == [T.SYSTEM_FAILURE]
    assert rig.emitter.recorded[0][2]["code"] == C.STORAGE_IO.value
    assert any(level == "error" for _, level, _ in rig.sink.rows)  # visible in the Error Logs
    monkeypatch.undo()
    assert (await rig.run(revision, op_set(SID, "headline", "Reprise"))).status is EditStatus.APPLIED


async def test_a_failure_injected_while_the_catalog_validates_leaves_the_state_untouched(rig, env, monkeypatch):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    calls = {"n": 0}
    real = env.prefabs.validate_instance

    async def flaky(ref):
        calls["n"] += 1
        raise RuntimeError("catalog fell over")

    monkeypatch.setattr(env.prefabs, "validate_instance", flaky)
    with pytest.raises(RuntimeError):
        await rig.run(revision, op_set(SID, "headline", "Jamais"))
    assert calls["n"] == 1 and rig.digest() == digest
    monkeypatch.setattr(env.prefabs, "validate_instance", real)
    assert (await rig.run(revision, op_set(SID, "headline", "Apres"))).status is EditStatus.APPLIED


# ------------------------------------------------------------------ annulation

async def test_the_undo_record_restores_the_scenes_byte_for_byte_through_the_same_api(rig):
    start = await rig.variant()
    result = await rig.run(start.revision, op_set(SID, "headline", "Nouveau"), op_set(SID2, "start_count", 5),
                           {"op": "scene.reorder", "scene_id": SID2, "to_index": 0},
                           {"op": "scene.remove", "scene_id": SID})
    middle = await rig.variant()
    undo = result.undo
    assert undo["available"] and undo["applies_at_revision"] == middle.revision and undo["restores_revision"] == start.revision
    assert rig.scenes_json(middle) != rig.scenes_json(start)
    back = await rig.edit.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit",
                                                  "basis": {"variant_revision": undo["applies_at_revision"]},
                                                  "ops": json.loads(json.dumps(undo["ops"]))})
    assert back.status is EditStatus.APPLIED
    assert rig.scenes_json(await rig.variant()) == rig.scenes_json(start)
    redo = await rig.edit.edit(rig.pid, rig.vid, {"actor": "brain", "mode": "commit",
                                                  "basis": {"variant_revision": back.revision},
                                                  "ops": back.undo["ops"]})
    assert rig.scenes_json(await rig.variant()) == rig.scenes_json(middle) and redo.status is EditStatus.APPLIED


async def test_an_undo_applied_on_a_moved_state_is_stale_not_forced(rig):
    start = await rig.variant()
    result = await rig.run(start.revision, op_set(SID, "headline", "A"))
    await rig.run(result.revision, op_set(SID, "headline", "B"))
    late = await rig.edit.edit(rig.pid, rig.vid, {"actor": "user", "mode": "commit",
                                                  "basis": {"variant_revision": result.undo["applies_at_revision"]},
                                                  "ops": result.undo["ops"]})
    assert late.status is EditStatus.STALE


# ------------------------------------------------------------------ concurrence

async def test_concurrent_edits_of_the_same_scene_lose_no_update_and_all_but_one_are_stale(rig):
    revision = (await rig.variant()).revision
    results = await asyncio.gather(*[rig.run(revision, op_set(SID, "headline", f"Auteur {i}")) for i in range(8)])
    applied = [r for r in results if r.status is EditStatus.APPLIED]
    stale = [r for r in results if r.status is EditStatus.STALE]
    assert len(applied) == 1 and len(stale) == 7
    final = await rig.variant()
    assert final.revision == revision + 1 and final.scenes[0].props["label"] == applied[0].ops[0]["after"]


async def test_two_threads_editing_the_same_scene_one_wins_the_other_is_stale(rig):
    revision = (await rig.variant()).revision
    loop = asyncio.get_running_loop()
    gate = threading.Barrier(2)
    answers: dict[str, object] = {}

    def client(name: str) -> None:
        gate.wait()
        future = asyncio.run_coroutine_threadsafe(rig.run(revision, op_set(SID, "headline", name), actor="user" if name == "a" else "brain"), loop)
        answers[name] = future.result(timeout=20)

    threads = [threading.Thread(target=client, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    while any(t.is_alive() for t in threads):
        await asyncio.sleep(0.01)
    assert sorted(r.status.value for r in answers.values()) == ["applied", "stale"]
    winner = next(r for r in answers.values() if r.status is EditStatus.APPLIED)
    assert (await rig.variant()).scenes[0].props["label"] == winner.ops[0]["after"]


async def test_retrying_after_stale_converges_with_no_lost_update(rig):
    start = (await rig.variant()).revision

    async def editor(i: int):
        for _ in range(40):
            variant = await rig.variant()
            target = SID if i % 2 == 0 else SID2
            result = await rig.run(variant.revision, op_set(target, "start_count", i + 1))
            if result.status is EditStatus.APPLIED:
                return i
            assert result.status is EditStatus.STALE
        raise AssertionError("never converged")

    done = await asyncio.gather(*[editor(i) for i in range(6)])
    assert sorted(done) == list(range(6))
    final = await rig.variant()
    assert final.revision == start + 6  # six writes, six revisions: nothing was swallowed
    assert {final.scenes[0].data["count"], final.scenes[1].data["count"]} <= set(range(1, 7))


# ------------------------------------------------------------------ source (niveau 3)

async def test_a_source_request_is_classified_and_recorded_only_at_commit(rig):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, {"op": "scene.source_request", "scene_id": SID, "intent": "make the number glow"}, actor="brain")
    assert result.status is EditStatus.APPLIED and result.tier.value == "source" and result.changed is False
    assert result.revision == revision and rig.digest() == digest and result.undo is None
    ((record,)) = rig.edit.pending_source_requests()
    assert (record.scene_id, record.actor, record.basis_revision, record.intent) == (SID, "brain", revision, "make the number glow")
    assert result.source_requests[0]["request_id"] == record.request_id and "intent" not in result.source_requests[0]
    ((event_type, source_ids, attributes),) = rig.emitter.recorded
    assert attributes["status"] == "recorded_in_memory" and attributes["tier"] == "source" and source_ids[2] == record.request_id
    assert result.source_requests[0]["durable"] is False  # nothing claims durability until Slice 06
    # the intent is in no diagnostic row and no event
    everything = json.dumps(rig.sink.rows, default=str) + json.dumps(rig.emitter.recorded, default=str)
    assert "glow" not in everything and "number" not in everything


async def test_source_requests_are_bounded_and_scoped_by_presentation(rig):
    revision = (await rig.variant()).revision
    for i in range(MAX_SOURCE_REQUESTS + 5):
        await rig.run(revision, {"op": "scene.source_request", "scene_id": SID, "intent": f"change {i}"})
    pending = rig.edit.pending_source_requests()
    assert len(pending) == MAX_SOURCE_REQUESTS and pending[0].intent == "change 5"
    assert rig.edit.pending_source_requests("pst_" + "9" * 32) == ()


# ------------------------------------------------------------------ evenements

async def test_the_committed_event_carries_ids_and_tokens_and_never_content(rig):
    revision = (await rig.variant()).revision
    result = await rig.run(revision, op_set(SID, "headline", "Titre confidentiel"),
                           {"op": "scene.rename", "scene_id": SID, "title": "Nom prive"})
    ((event_type, source_ids, attributes),) = rig.emitter.recorded
    assert event_type is T.SYSTEM_PRESENTATION_STUDIO_EDIT_COMMITTED
    assert source_ids == (rig.pid, rig.vid, str(result.revision))
    assert attributes == {"presentation_id": rig.pid, "variant_id": rig.vid, "scene_id": SID,
                          "op": ["control.set", "scene.rename"], "tier": "structure", "source": "user",
                          "revision": result.revision, "status": "applied"}
    everything = json.dumps(rig.emitter.recorded, default=str) + json.dumps(rig.sink.rows, default=str)
    assert "confidentiel" not in everything and "prive" not in everything


async def test_no_live_conversation_means_no_event_but_the_edit_and_its_journal_stand(env):
    rig = Rig(env, conversation=None)
    await rig.open()
    revision = (await rig.variant()).revision
    result = await rig.run(revision, op_set(SID, "headline", "Seul"))
    assert result.status is EditStatus.APPLIED and rig.emitter.recorded == []
    ((_, row),) = rig.sink.of("core.presentation_studio.edit_committed")
    assert row["event_recorded"] is False  # the journal row says it, nobody has to read a counter


async def test_the_journal_row_says_when_the_event_was_recorded(rig):
    revision = (await rig.variant()).revision
    await rig.run(revision, op_set(SID, "headline", "Avec"))
    ((_, row),) = rig.sink.of("core.presentation_studio.edit_committed")
    assert row["event_recorded"] is True


async def test_an_event_sink_that_raises_never_undoes_the_edit(env):
    rig = Rig(env)
    await rig.open()
    rig.emitter.record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("journal down"))
    revision = (await rig.variant()).revision
    result = await rig.run(revision, op_set(SID, "headline", "Tient"))
    assert result.status is EditStatus.APPLIED and (await rig.variant()).scenes[0].props["label"] == "Tient"
    assert rig.sink.of("core.presentation_studio.event_failed")


# ------------------------------------------------------------------ propositions de controles

async def test_suggest_controls_proposes_without_writing_and_apply_is_a_ready_operation(env):
    rig = await Rig(env).open([scene_body(controls=CONTROLS[:1], anchors=[])])
    variant = await rig.variant()
    digest = rig.digest()
    suggestion = await rig.edit.suggest_controls(rig.pid, rig.vid, SID)
    assert rig.digest() == digest and suggestion["basis"] == {"variant_revision": variant.revision}
    paths = {p["path"] for p in suggestion["proposals"]}
    assert "props.label" not in paths and {"props.accent", "props.mode", "data.count"} <= paths
    assert suggestion["declared"] == 1 and suggestion["apply"]["op"] == "scene.set_controls"
    applied = await rig.edit.edit(rig.pid, rig.vid, {"actor": "brain", "mode": "commit",
                                                    "basis": suggestion["basis"], "ops": [suggestion["apply"]]})
    assert applied.status is EditStatus.APPLIED and applied.tier.value == "structure"
    assert {c.path for c in (await rig.variant()).scenes[0].controls} >= paths | {"props.label"}
    again = await rig.edit.suggest_controls(rig.pid, rig.vid, SID)
    assert not [p for p in again["proposals"] if p["path"] in paths]


async def test_suggest_controls_errors(env):
    rig = await Rig(env).open()
    with pytest.raises(PresentationStudioError) as caught:
        await rig.edit.suggest_controls(rig.pid, rig.vid, "pss_00000000ffff")
    assert caught.value.code is C.UNKNOWN_SCENE
    (env.tmp / "bare").mkdir()
    bare = await Rig(Env(env.tmp / "bare")).open(catalog=False)
    with pytest.raises(PresentationStudioError) as caught:
        await bare.edit.suggest_controls(bare.pid, bare.vid, SID)
    assert caught.value.code is C.PREFAB_UNAVAILABLE


class StubPrefabs:
    """Un catalogue dont le manifeste declare `__proto__` (le nom passe la grammaire des prefabs)."""

    def __init__(self) -> None:
        data = candidate()["manifest"]
        data["id"] = "lab.counter"
        data["inputs"]["props"]["properties"]["__proto__"] = {"type": "string", "max_length": 10}
        self.manifest_value = parse_manifest(data)

    async def manifest(self, prefab_id, version):
        return self.manifest_value

    async def validate_instance(self, ref: PrefabInstanceRef):
        class Verdict:
            ok = True
            code = None
            detail = ""
        return Verdict()


async def test_suggest_controls_never_proposes_a_reserved_property_name(env):
    store = FilePresentationStudioStore(env.studio_root)
    studio = PresentationStudioService(store, clock=Clock(), prefabs=StubPrefabs())
    edit = PresentationStudioEditService(studio)
    pid, vid = await env.presentation(studio, [scene_body(controls=CONTROLS[:1], anchors=[])])
    suggestion = await edit.suggest_controls(pid, vid, SID)
    assert suggestion["proposals"] and not any("__proto__" in p["path"] for p in suggestion["proposals"])


# ------------------------------------------------------------------ sans catalogue, verrou

async def test_without_a_catalog_a_control_edit_is_refused_but_structure_still_works(env):
    rig = await Rig(env).open(catalog=False)
    revision = (await rig.variant()).revision
    refused = await rig.run(revision, op_set(SID, "headline", "x"))
    assert refused.status is EditStatus.REFUSED and refused.code == C.PREFAB_UNAVAILABLE.value
    renamed = await rig.run(revision, {"op": "scene.rename", "scene_id": SID, "title": "Sans catalogue"})
    assert renamed.status is EditStatus.APPLIED


class SlowPrefabs:
    """Enveloppe du vrai catalogue dont `validate_instance` attend qu'on le libere."""

    def __init__(self, inner) -> None:
        self.inner, self.entered, self.release = inner, asyncio.Event(), asyncio.Event()

    async def manifest(self, prefab_id, version):
        return await self.inner.manifest(prefab_id, version)

    async def validate_instance(self, ref):
        self.entered.set()
        await self.release.wait()
        return await self.inner.validate_instance(ref)


async def test_the_prefab_catalog_is_awaited_outside_the_service_lock(env):
    await env.prefabs.start()
    slow = SlowPrefabs(env.prefabs)
    studio = PresentationStudioService(FilePresentationStudioStore(env.studio_root), clock=Clock(), prefabs=slow)
    edit = PresentationStudioEditService(studio)
    pid, vid = (await studio.create({"title": "Atelier"})).presentation.presentation_id, None
    vid = (await studio.get(pid)).presentation.active_variant_id
    slow.release.set()
    variant = await studio.get_variant(pid, vid)
    await studio.save_variant(pid, vid, {"expected_revision": variant.revision, "title": variant.title,
                                         "scenes": [scene_body()], "art_direction_id": None, "score_id": None})
    slow.release.clear()
    slow.entered.clear()
    revision = (await studio.get_variant(pid, vid)).revision
    task = asyncio.create_task(edit.edit(pid, vid, request(revision, op_set(SID, "headline", "Lent"))))
    await asyncio.wait_for(slow.entered.wait(), 5)
    # the edit is blocked inside the catalog; reads and listing are not
    assert (await asyncio.wait_for(studio.get_variant(pid, vid), 2)).revision == revision
    assert (await asyncio.wait_for(studio.list_presentations(), 2)).presentations
    slow.release.set()
    assert (await asyncio.wait_for(task, 5)).status is EditStatus.APPLIED


async def test_a_save_that_lands_while_the_catalog_validates_makes_the_slow_edit_stale(env):
    await env.prefabs.start()
    slow = SlowPrefabs(env.prefabs)
    studio = PresentationStudioService(FilePresentationStudioStore(env.studio_root), clock=Clock(), prefabs=slow)
    edit = PresentationStudioEditService(studio)
    pid = (await studio.create({"title": "Atelier"})).presentation.presentation_id
    vid = (await studio.get(pid)).presentation.active_variant_id
    slow.release.set()
    variant = await studio.get_variant(pid, vid)
    await studio.save_variant(pid, vid, {"expected_revision": variant.revision, "title": variant.title,
                                         "scenes": [scene_body()], "art_direction_id": None, "score_id": None})
    slow.release.clear()
    slow.entered.clear()
    revision = (await studio.get_variant(pid, vid)).revision
    task = asyncio.create_task(edit.edit(pid, vid, request(revision, op_set(SID, "headline", "Lent"))))
    await asyncio.wait_for(slow.entered.wait(), 5)
    other = await studio.get_variant(pid, vid)
    await studio.write_variant(pid, vid, type("U", (), {"expected_revision": revision, "title": "Concurrent",
                                                         "scenes": other.scenes, "art_direction_id": None,
                                                         "score_id": None})())
    slow.release.set()
    result = await asyncio.wait_for(task, 5)
    assert result.status is EditStatus.STALE and (await studio.get_variant(pid, vid)).title == "Concurrent"
    assert (await studio.get_variant(pid, vid)).scenes[0].props["label"] == "Visiteurs"


async def test_a_save_variant_also_awaits_the_catalog_outside_the_lock(env):
    await env.prefabs.start()
    slow = SlowPrefabs(env.prefabs)
    studio = PresentationStudioService(FilePresentationStudioStore(env.studio_root), clock=Clock(), prefabs=slow)
    pid = (await studio.create({"title": "Atelier"})).presentation.presentation_id
    vid = (await studio.get(pid)).presentation.active_variant_id
    variant = await studio.get_variant(pid, vid)
    task = asyncio.create_task(studio.save_variant(pid, vid, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body()],
        "art_direction_id": None, "score_id": None}))
    await asyncio.wait_for(slow.entered.wait(), 5)
    assert (await asyncio.wait_for(studio.get_variant(pid, vid), 2)).revision == variant.revision
    # a second save lands while the first waits for the catalogue: the first becomes a stale_revision, nothing is lost
    other = await studio.write_variant(pid, vid, type("U", (), {
        "expected_revision": variant.revision, "title": "Concurrent", "scenes": (), "art_direction_id": None,
        "score_id": None})())
    slow.release.set()
    with pytest.raises(PresentationStudioError) as caught:
        await asyncio.wait_for(task, 5)
    assert caught.value.code is C.STALE_REVISION
    assert (await studio.get_variant(pid, vid)).title == "Concurrent" and other.revision == variant.revision + 1


async def test_an_unavailable_prefab_during_an_edit_is_logged_with_its_code(rig):
    revision = (await rig.variant()).revision
    with pytest.raises(PresentationStudioError):
        await rig.run(revision, {"op": "scene.add", "scene": scene_body("pss_0000000000b1", prefab=("lab.counter", 9))})
    rows = rig.sink.of("core.presentation_studio.refused") + rig.sink.of("core.presentation_studio.failed")
    assert any(data.get("op") == "edit_manifests" and data.get("code") == C.PREFAB_UNAVAILABLE.value for _, data in rows)


async def test_value_type_changes_are_validated_never_compared_with_python_equality(rig):
    revision = (await rig.variant()).revision
    ok = await rig.run(revision, op_set(SID, "start_count", 1))
    assert ok.status is EditStatus.APPLIED
    for lookalike in (True, 1.0):
        bad = await rig.run(ok.revision, op_set(SID, "start_count", lookalike))
        assert bad.status is EditStatus.REFUSED
    saved = await rig.studio.get_variant(rig.pid, rig.vid)
    assert saved.scenes[0].data == {"count": 1} and type(saved.scenes[0].data["count"]) is int


# ------------------------------------------------------------------ rework QA-1

def op_restore(scene_id, props, data):
    return {"op": "scene.restore_values", "scene_id": scene_id, "props": props, "data": data}


@pytest.mark.parametrize("props, data, path", [
    ({"label": "Visiteurs", "accent": "#ff0000"}, {"count": 12}, "props.accent"),  # the QA repro: no control for accent
    ({"label": "Visiteurs"}, {"count": 12, "link": "https://evil.example/x"}, "data.link"),
])
@pytest.mark.parametrize("actor", ["brain", "user"])
@pytest.mark.parametrize("mode", ["commit", "preview"])
async def test_restore_values_cannot_write_a_path_no_declared_control_covers(rig, props, data, path, actor, mode):
    revision = (await rig.variant()).revision
    digest = rig.digest()
    result = await rig.run(revision, op_restore(SID, props, data), actor=actor, mode=mode)
    assert result.status is EditStatus.REFUSED and result.code == C.UNKNOWN_CONTROL.value and result.failed_index == 0
    assert path in result.message and "scene.source_request" in result.message
    assert rig.digest() == digest and rig.emitter.recorded == []
    # the declared door refuses the same undeclared path, so the vocabulary is closed again
    assert (await rig.run(revision, op_set(SID, "accent", "#ff0000"))).code == C.UNKNOWN_CONTROL.value


async def test_restore_values_may_still_change_declared_paths_and_cannot_drop_an_undeclared_one(env):
    rig = await Rig(env).open([scene_body(props={"label": "Visiteurs", "accent": "#00ff00"})])
    revision = (await rig.variant()).revision
    ok = await rig.run(revision, op_restore(SID, {"label": "Autre", "accent": "#00ff00"}, {"count": 3}))
    assert ok.status is EditStatus.APPLIED and ok.tier.value == "control"
    dropped = await rig.run(ok.revision, op_restore(SID, {"label": "Autre"}, {"count": 3}))
    assert dropped.status is EditStatus.REFUSED and "props.accent" in dropped.message


async def test_undo_still_works_for_every_kind_of_edit_after_the_restore_rule(rig):
    start = await rig.variant()
    edit = await rig.run(start.revision, op_set(SID, "headline", "Z"), op_set(SID2, "start_count", 9),
                         {"op": "control.reset", "scene_id": SID, "control_id": "density"})
    undone = await rig.edit.edit(rig.pid, rig.vid, request(edit.revision, *edit.undo["ops"], actor="brain"))
    assert undone.status is EditStatus.APPLIED
    assert rig.scenes_json(await rig.variant()) == rig.scenes_json(start)


async def test_a_refusal_row_never_quotes_the_refused_value(rig):
    revision = (await rig.variant()).revision
    result = await rig.run(revision, op_restore(SID, {"label": "Visiteurs", "mode": "SECRETVALUE"}, {"count": 12}))
    assert result.status is EditStatus.REFUSED and "SECRETVALUE" in result.message  # the caller may read its own refusal
    assert "SECRETVALUE" not in json.dumps(rig.sink.rows, default=str)
    assert "SECRETVALUE" not in json.dumps(rig.emitter.recorded, default=str)
    rows = rig.sink.of("core.presentation_studio.refused")
    assert rows and all("error" not in data and data["code"] for _, data in rows)  # the row exists, code only


async def test_the_source_request_ring_never_drops_silently(rig):
    revision = (await rig.variant()).revision
    ops = [{"op": "scene.source_request", "scene_id": SID, "intent": f"change {i}"} for i in range(16)]
    dropped = []
    for _ in range(5):  # 80 requests, room for 64
        result = await rig.run(revision, *ops)
        dropped.append(result.source_requests_dropped)
        assert all(item["durable"] is False for item in result.source_requests)
    assert dropped == [0, 0, 0, 0, 16] and result.to_dict()["source_requests_dropped"] == 16
    warnings = [data for kind, level, data in rig.sink.rows if kind == "core.presentation_studio.source_requests_dropped"]
    assert [(w["dropped"], w["capacity"]) for w in warnings] == [(16, MAX_SOURCE_REQUESTS)]
    assert len(rig.edit.pending_source_requests()) == MAX_SOURCE_REQUESTS


async def test_a_preview_reports_the_document_limit_a_commit_would_hit(rig, monkeypatch):
    start = await rig.variant()
    size = len(rig.path.read_bytes())
    monkeypatch.setattr("jarvis.domain.presentation_studio.MAX_DOCUMENT_BYTES", size + 20)
    big = {"op": "scene.add", "scene": scene_body("pss_0000000000b1", title="t" * 80, controls=CONTROLS)}
    preview = await rig.run(start.revision, big, mode="preview")
    commit = await rig.run(start.revision, big)
    assert preview.status is commit.status is EditStatus.REFUSED
    assert preview.code == commit.code == C.LIMIT_REACHED.value and preview.http_status == 409
    assert (await rig.variant()).revision == start.revision
    ok = await rig.run(start.revision, op_set(SID, "headline", "ok"), mode="preview")
    assert ok.status is EditStatus.APPLIED


async def test_undoing_a_structure_edit_reports_the_structure_tier(env):
    hist = {"control_id": "hist", "path": "data.history", "label": "H", "group": "content"}
    rig = await Rig(env).open([scene_body(controls=[*CONTROLS, hist], anchors=[])])
    revision = (await rig.variant()).revision
    edit = await rig.run(revision, op_set(SID, "hist", [{"delta": 2}]))
    assert edit.tier.value == "structure"
    undo = await rig.edit.edit(rig.pid, rig.vid, request(edit.revision, *edit.undo["ops"], mode="preview"))
    assert undo.status is EditStatus.APPLIED and undo.tier.value == "structure" and undo.ops[0]["tier"] == "structure"
    plain = await rig.run(edit.revision, op_set(SID, "headline", "p"))
    back = await rig.edit.edit(rig.pid, rig.vid, request(plain.revision, *plain.undo["ops"], mode="preview"))
    assert back.tier.value == "control"


async def test_undo_keeps_the_stored_key_order_of_the_edited_scene(rig):
    before = json.loads(rig.path.read_text(encoding="utf-8"))["scenes"]
    start = await rig.variant()
    edit = await rig.run(start.revision, op_set(SID, "headline", "Autre"), op_set(SID, "start_count", 7))
    await rig.edit.edit(rig.pid, rig.vid, request(edit.revision, *edit.undo["ops"]))
    after = json.loads(rig.path.read_text(encoding="utf-8"))["scenes"]
    assert after == before
    assert [list(s["data"]) for s in after] == [list(s["data"]) for s in before]
    assert [list(s["props"]) for s in after] == [list(s["props"]) for s in before]
