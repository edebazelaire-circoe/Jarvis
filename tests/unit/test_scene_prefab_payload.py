"""Bloc `prefab` de la charge d'une fenêtre (handoff jarvis-scene-window-prefab-foundation, Slice 04).

Contrat : `docs/scene-model.md` › *Prefab windows*. Ce qui doit tenir :

- un objet sans bloc garde exactement son fil d'avant (octet pour octet) ;
- le bloc fait l'aller-retour du fil, copié (aucun partage avec l'appelant) ;
- seule une `window` en porte un : refus de construction, et refus du
  réducteur (`invalid/prefab_invalid` avec `detail`) plutôt qu'une exception ;
- JSON pur, profondeur ≤ 8, clés ≤ 64, pas de contrôle C0, charge entière ≤ 16 Kio ;
- `SceneUpdate.detail` n'existe qu'avec un refus, ≤ 300 caractères.
"""

from __future__ import annotations

import json

import pytest

from jarvis.domain.scene import (
    MAX_PAYLOAD_BYTES, MAX_UPDATE_DETAIL_CHARS, PlacedBy, Representation, SceneActor, SceneCommand, SceneCommandOutcome,
    SceneConstraints, SceneGeometry, SceneObject, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
    ScenePayloadItem, ScenePrefabRef, SceneRefusal, SceneSnapshot, SceneUpdate, apply_scene_command,
)

#: Fil d'un objet de fenêtre legacy, figé avant la Slice 04 : il ne doit pas bouger d'un octet.
LEGACY_WIRE = (
    '{"object_id":"win-1","kind":"window","category":"note","constraints":{"placed_by":"brain","pinned_by_user":false},'
    '"origin":"brain","exec_state":"unknown","representation":"window","geometry":{"x":1.0,"y":2.0,"w":40.0,"h":24.0},'
    '"layer":100,"order":0,"visibility":"visible","disposition":"active","work_ref":null,'
    '"payload":{"title":"Note","summary":"Texte","items":[{"label":"a","ref":"","url":""}],"annotation":"vu"}}'
)


def legacy_window(**payload) -> SceneObject:
    return SceneObject(
        object_id="win-1", kind=SceneObjectKind.WINDOW, category="note",
        constraints=SceneConstraints(placed_by=PlacedBy.BRAIN), origin=SceneActor.BRAIN,
        representation=Representation.WINDOW, geometry=SceneGeometry(1, 2, 40, 24),
        payload=ScenePayload(title="Note", summary="Texte", items=(ScenePayloadItem("a"),), annotation="vu", **payload),
    )


def counter(**changes) -> ScenePrefabRef:
    return ScenePrefabRef(**{"prefab_id": "test.counter", "version": 1, "props": {"label": "Clics"},
                             "data": {"count": 3}, **changes})


def wire(value) -> str:
    return json.dumps(value.to_payload(), ensure_ascii=False, separators=(",", ":"))


def test_a_legacy_object_serializes_byte_identically():
    obj = legacy_window()
    assert wire(obj) == LEGACY_WIRE
    assert "prefab" not in obj.payload.to_payload()
    assert SceneObject.from_payload(json.loads(LEGACY_WIRE)) == obj


def test_the_block_round_trips_and_is_emitted_only_when_present():
    block = counter(data={"count": 3, "history": [{"delta": 1, "ratio": 0.5}], "notes": "a\nb\tc", "link": None})
    obj = SceneObject(object_id="win-2", kind=SceneObjectKind.WINDOW, category="note",
                      constraints=SceneConstraints(placed_by=PlacedBy.USER), origin=SceneActor.USER,
                      representation=Representation.WINDOW, payload=ScenePayload(title="Compteur", prefab=block))
    raw = obj.to_payload()
    assert raw["payload"]["prefab"] == {"id": "test.counter", "version": 1, "props": {"label": "Clics"},
                                        "data": {"count": 3, "history": [{"delta": 1, "ratio": 0.5}],
                                                 "notes": "a\nb\tc", "link": None}}
    again = SceneObject.from_payload(json.loads(json.dumps(raw)))
    assert again == obj and again.payload.prefab.key == "test.counter@1"
    # props/data facultatifs au décodage, toujours émis.
    assert ScenePrefabRef.from_payload({"id": "test.counter", "version": 2}).to_payload() == {
        "id": "test.counter", "version": 2, "props": {}, "data": {}}


def test_the_block_is_copied_in_and_out():
    data = {"count": 1, "history": []}
    block = counter(data=data)
    data["count"] = 99
    data["history"].append({"delta": 1})
    assert block.data == {"count": 1, "history": []}
    out = block.to_payload()
    out["data"]["count"] = 7
    assert block.data["count"] == 1
    hash(ScenePayload(prefab=block))  # props/data hors hachage : la charge reste hachable


@pytest.mark.parametrize("changes, message", [
    ({"prefab_id": "Test.Counter"}, "not a valid prefab id"),
    ({"prefab_id": "counter"}, "not a valid prefab id"),
    ({"version": 0}, "integer 1..9999"),
    ({"version": 10000}, "integer 1..9999"),
    ({"version": True}, "integer 1..9999"),
    ({"version": 1.0}, "integer 1..9999"),
    ({"props": []}, "must be an object"),
    ({"data": {"x": float("nan")}}, "finite"),
    ({"data": {"x": float("inf")}}, "finite"),
    ({"data": {"x": (1, 2)}}, "JSON values only"),
    ({"data": {1: "x"}}, "keys must be strings"),
    ({"data": {"k" * 65: 1}}, "at most 64"),
    ({"data": {"x": "bell\x07"}}, "control characters"),
    ({"data": {"x": "cr\r"}}, "control characters"),
])
def test_invalid_blocks_are_refused(changes, message):
    with pytest.raises((TypeError, ValueError), match=message):
        counter(**changes)


def test_depth_is_bounded_at_eight():
    def nested(depth):
        value = 1
        for _ in range(depth):
            value = {"n": value}
        return value
    counter(data=nested(7))  # data (1) + 7 niveaux = 8
    with pytest.raises(ValueError, match="deeper than 8"):
        counter(data=nested(8))


def test_the_whole_payload_stays_within_16_kib():
    room = MAX_PAYLOAD_BYTES - len(json.dumps(ScenePayload(prefab=counter(data={"notes": ""})).to_payload(),
                                              separators=(",", ":")).encode())
    ScenePayload(prefab=counter(data={"notes": "x" * room}))
    with pytest.raises(ValueError, match="payload exceeds"):
        ScenePayload(prefab=counter(data={"notes": "x" * (room + 1)}))


def test_unknown_block_keys_are_refused_on_the_wire():
    with pytest.raises(ValueError, match="unknown fields"):
        ScenePrefabRef.from_payload({"id": "test.counter", "version": 1, "state": {}})
    with pytest.raises(ValueError, match="missing fields"):
        ScenePrefabRef.from_payload({"id": "test.counter"})


@pytest.mark.parametrize("kind", [k for k in SceneObjectKind if k is not SceneObjectKind.WINDOW])
def test_only_a_window_carries_a_block(kind):
    origin = SceneActor.RUNTIME if kind.value in ("agent", "job") else SceneActor.BRAIN
    with pytest.raises(ValueError, match="only on a window"):
        SceneObject(object_id="o", kind=kind, category="note", constraints=SceneConstraints(placed_by=PlacedBy.BRAIN),
                    origin=origin, payload=ScenePayload(prefab=counter()))


def snapshot_with(*objects) -> SceneSnapshot:
    return SceneSnapshot(scene_id="scene-1", revision=4, objects=tuple(objects))


def test_the_reducer_refuses_a_block_on_another_kind_with_a_detail():
    command = SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="art-1",
                           fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note",
                                                    payload=ScenePayload(prefab=counter())))
    update = apply_scene_command(snapshot_with(), command)
    assert update.outcome is SceneCommandOutcome.INVALID and update.reason is SceneRefusal.PREFAB_INVALID
    assert update.detail == "a prefab block lives only on a window object" and update.snapshot.revision == 4
    # Même règle en patch d'un objet existant d'une autre nature.
    art = SceneObject(object_id="art-2", kind=SceneObjectKind.ARTIFACT, category="note",
                      constraints=SceneConstraints(placed_by=PlacedBy.BRAIN), origin=SceneActor.BRAIN)
    patch = SceneCommand(op=SceneOp.PATCH_OBJECT, actor=SceneActor.USER, object_id="art-2",
                         fields=SceneObjectFields(payload=ScenePayload(prefab=counter())))
    update = apply_scene_command(snapshot_with(art), patch)
    assert (update.outcome, update.reason) == (SceneCommandOutcome.INVALID, SceneRefusal.PREFAB_INVALID)


def test_the_reducer_accepts_a_window_block_and_puts_it_in_the_patch():
    command = SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.USER, object_id="win-9",
                           fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="note",
                                                    payload=ScenePayload(title="Compteur", prefab=counter())))
    update = apply_scene_command(snapshot_with(), command)
    assert update.outcome is SceneCommandOutcome.APPLIED and update.detail == ""
    [op] = update.patch.ops
    assert op.object.payload.prefab == counter()


def test_scene_update_detail_invariant():
    snap = snapshot_with()
    SceneUpdate(SceneCommandOutcome.INVALID, snap, reason=SceneRefusal.PREFAB_INVALID, detail="x" * MAX_UPDATE_DETAIL_CHARS)
    with pytest.raises(ValueError, match="at most 300"):
        SceneUpdate(SceneCommandOutcome.INVALID, snap, reason=SceneRefusal.PREFAB_INVALID, detail="x" * 301)
    with pytest.raises(ValueError, match="only with a refusal"):
        SceneUpdate(SceneCommandOutcome.DUPLICATE, snap, detail="nope")
    assert SceneUpdate(SceneCommandOutcome.DUPLICATE, snap).detail == ""
