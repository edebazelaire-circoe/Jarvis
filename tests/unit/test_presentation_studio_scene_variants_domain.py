"""Variantes locales d'une scène : modèle pur et moteur d'édition (jarvis-interactive-presentation-studio, Slice 17).

La scène vivante est toujours le contenu de la variante locale choisie ; choisir est une permutation. Ces tests tiennent
l'exactitude (JSON canonique **et** octets), la réversibilité par l'inverse enregistré, l'isolation entre scènes, les bornes
et la forme canonique (« une seule variante = pas d'ensemble »). Contrat : `docs/presentation-studio.md` ›
*Scene-local variant contract*.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import replace

import pytest

from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import (
    ALLOWED_EDIT_OPS, EditRefusal, EditTier, OpName, SceneAdd, SceneVariantCreate, SceneVariantDelete, SceneVariantRename,
    SceneVariantRestoreSet, SceneVariantSelect, StudioActor, apply_ops, classify_op, parse_op,
)
from jarvis.domain.presentation_studio_history import pins_of
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.presentation_studio_scene_variants import (
    MAX_SCENE_VARIANTS, MAX_SET_BYTES, SceneVariantSet, is_scene_variant_id, new_scene_variant_id,
)

S1, S2 = "pss_0000000000a1", "pss_0000000000a2"
NOW = "2026-10-08T10:00:00.000000Z"


def body(scene_id=S1, **changes) -> dict:
    return {"scene_id": scene_id, "prefab": {"id": "lab.counter", "version": 1}, "title": "Chiffre",
            "props": {"zeta": 1, "label": "Visiteurs", "mode": "full"}, "data": {"count": 12, "list": [3, 1, 2]},
            "controls": [{"control_id": "headline", "path": "props.label", "label": "Titre", "group": "content"},
                         {"control_id": "count", "path": "data.count", "label": "Valeur", "group": "content"}],
            "anchors": [{"anchor_id": "reveal", "label": "Reveler", "control_id": "count"}], **changes}


def scene(scene_id=S1, **changes) -> StudioScene:
    return StudioScene.from_dict(body(scene_id, **changes))


class Ids:
    """Identifiants `psx_` déterministes pour un test."""

    def __init__(self, start: int = 1) -> None:
        self.n = start

    def __call__(self) -> str:
        self.n += 1
        return "psx_%012x" % self.n


SHARED_IDS = Ids(100)  # one generator for the whole module: two runs never mint the same id (a real generator does not either)


def run(scenes, *ops, ids=None, actor=StudioActor.USER):
    return apply_ops(tuple(scenes), list(ops), {}, presentation_id="pst_" + "0" * 32, variant_id="psv_" + "0" * 32,
                     actor=actor, basis_revision=1, now=lambda: NOW, new_scene_variant_id=ids or SHARED_IDS)


def stored(scenes) -> str:
    return json.dumps([s.to_dict() for s in scenes])  # insertion order: the bytes of the document


def canon(scenes) -> str:
    return canonical_json([s.to_dict() for s in scenes])


def refused(*args, **kwargs) -> EditRefusal:
    with pytest.raises(EditRefusal) as caught:
        run(*args, **kwargs)
    return caught.value


def two_variants():
    """Une scène avec « Original » (choisie) et « B » rangée ; rend (scènes, id Original, id B)."""

    plan = run([scene()], SceneVariantCreate(S1, "B", "plus sobre"))
    original, other = plan.scenes[0].scene_variants.items
    return plan.scenes, original.variant_id, other.variant_id


# ------------------------------------------------------------------ forme canonique

def test_a_scene_without_local_variants_stores_nothing_new():
    assert "scene_variants" not in scene().to_dict()
    assert StudioScene.from_dict(scene().to_dict()) == scene()
    assert scene().held_pins() == {("lab.counter", 1)}


def test_the_first_create_makes_the_scene_the_original_and_stores_only_the_copy():
    plan = run([scene()], SceneVariantCreate(S1, "B", "plus sobre"), ids=Ids())
    after = plan.scenes[0]
    original, other = after.scene_variants.items
    assert after.scene_variants.current_id == original.variant_id == "psx_000000000002"
    assert (original.label, original.source, original.content) == ("Original", "current", None)
    assert (other.label, other.rationale, other.source, other.created_by, other.created_at) == (
        "B", "plus sobre", original.variant_id, "user", NOW)
    assert set(other.content) == {"prefab", "props", "data", "controls", "anchors"}  # what differs: never the deck, the title...
    assert other.content == scene().live_content()
    # the live scene is untouched: its fields ARE the content of the selected variant
    assert {k: v for k, v in after.to_dict().items() if k != "scene_variants"} == scene().to_dict()
    assert plan.outcomes[0]["scene_variant_id"] == other.variant_id and plan.tiers == [EditTier.STRUCTURE]


def test_a_copy_of_another_local_variant_records_it_as_its_source_and_a_set_never_holds_one_entry():
    scenes, original, other = two_variants()
    third = run(scenes, SceneVariantCreate(S1, "C", "", from_variant=other)).scenes[0].scene_variants.items[2]
    assert third.source == other and third.content == scenes[0].scene_variants.get(other).content
    assert run(scenes, SceneVariantCreate(S1, "D")).scenes[0].scene_variants.items[2].source == original  # the live scene
    only_one = run(scenes, SceneVariantDelete(S1, other)).scenes[0]
    assert only_one.scene_variants is None and "scene_variants" not in only_one.to_dict()
    with pytest.raises(PresentationStudioError):
        SceneVariantSet(original, scenes[0].scene_variants.items[:1])


def test_ids_are_psx_and_generated_when_not_injected():
    assert is_scene_variant_id(new_scene_variant_id()) and not is_scene_variant_id("psx_ZZZ") and not is_scene_variant_id(5)
    plan = apply_ops((scene(),), [SceneVariantCreate(S1, "B")], {}, presentation_id="p", variant_id="v",
                     actor=StudioActor.BRAIN, basis_revision=1)
    items = plan.scenes[0].scene_variants.items
    assert all(is_scene_variant_id(i.variant_id) for i in items) and {i.created_by for i in items} == {"brain"}
    assert items[0].created_at.endswith("Z") and len(items[0].created_at) == len(NOW)


# ------------------------------------------------------------------ choisir : permutation exacte

def test_select_swaps_the_contents_and_select_back_restores_the_exact_bytes():
    scenes, original, other = two_variants()
    live = scene(props={"label": "Autre", "zeta": 2}, data={"count": 99}).live_content()
    fixed = replace(scenes[0], props=live["props"], data=live["data"])
    edited = (replace(fixed, scene_variants=scenes[0].scene_variants),)
    # the author edited the live scene (the selected "Original"): its content is now the live fields
    before = stored(edited)
    plan = run(edited, SceneVariantSelect(S1, other))
    chosen = plan.scenes[0]
    assert chosen.scene_variants.current_id == other and chosen.props == scene().props  # B's content is the scene now
    assert chosen.scene_variants.get(original).content == edited[0].live_content()  # the previous content is saved back
    assert chosen.scene_variants.get(other).content is None
    back = run(plan.scenes, *[parse_op(op) for op in plan.inverse])
    assert stored(back.scenes) == before and canon(back.scenes) == canon(edited)


def test_select_of_the_selected_changes_nothing_and_records_no_inverse():
    scenes, original, _ = two_variants()
    plan = run(scenes, SceneVariantSelect(S1, original))
    assert stored(plan.scenes) == stored(scenes) and plan.inverse == [] and plan.outcomes[0]["changed"] is False


def test_unknown_ids_and_a_scene_without_a_set_are_typed_refusals():
    scenes, _, _ = two_variants()
    assert refused(scenes, SceneVariantSelect(S1, "psx_ffffffffffff")).code is C.UNKNOWN_SCENE_VARIANT
    assert refused(scenes, SceneVariantDelete(S1, "psx_ffffffffffff")).code is C.UNKNOWN_SCENE_VARIANT
    assert refused(scenes, SceneVariantRename(S1, "psx_ffffffffffff", "x")).code is C.UNKNOWN_SCENE_VARIANT
    assert refused(scenes, SceneVariantCreate(S1, "C", from_variant="psx_ffffffffffff")).code is C.UNKNOWN_SCENE_VARIANT
    assert refused([scene()], SceneVariantSelect(S1, "psx_ffffffffffff")).code is C.UNKNOWN_SCENE_VARIANT
    assert refused([scene()], SceneVariantCreate(S1, "C", from_variant="psx_ffffffffffff")).code is C.UNKNOWN_SCENE_VARIANT
    assert refused(scenes, SceneVariantSelect("pss_ffffffffffff", "psx_000000000002")).code is C.UNKNOWN_SCENE


def test_the_selected_variant_cannot_be_deleted_and_the_message_says_what_to_do():
    scenes, original, other = two_variants()
    refusal = refused(scenes, SceneVariantDelete(S1, original))
    assert refusal.code is C.SCENE_VARIANT_PROTECTED and "select another" in refusal.message
    chosen = run(scenes, SceneVariantSelect(S1, other)).scenes
    assert refused(chosen, SceneVariantDelete(S1, other)).code is C.SCENE_VARIANT_PROTECTED
    assert run(chosen, SceneVariantDelete(S1, original)).scenes[0].scene_variants is None  # the unselected one goes


def test_delete_is_exactly_undone_by_its_inverse_and_the_last_deletion_returns_to_the_plain_scene():
    scenes, original, other = two_variants()
    third = run(scenes, SceneVariantCreate(S1, "C")).scenes
    plan = run(third, SceneVariantDelete(S1, other))
    assert len(plan.scenes[0].scene_variants.items) == 2
    assert stored(run(plan.scenes, *[parse_op(o) for o in plan.inverse]).scenes) == stored(third)
    last = run(scenes, SceneVariantDelete(S1, other))
    assert stored(last.scenes) == stored([scene()])  # byte for byte the scene before any local variant
    assert stored(run(last.scenes, *[parse_op(o) for o in last.inverse]).scenes) == stored(scenes)


def test_create_is_exactly_undone_by_its_inverse_and_the_redo_form_is_exact():
    plan = run([scene()], SceneVariantCreate(S1, "B"))
    undo = run(plan.scenes, *[parse_op(o) for o in plan.inverse])
    assert stored(undo.scenes) == stored([scene()])
    redo = run(undo.scenes, *[parse_op(o) for o in undo.inverse])
    assert stored(redo.scenes) == stored(plan.scenes)


def test_rename_changes_only_the_label_and_a_duplicate_label_is_refused_whatever_the_case():
    scenes, original, other = two_variants()
    plan = run(scenes, SceneVariantRename(S1, other, "Version vidéo"))
    assert plan.scenes[0].scene_variants.get(other).label == "Version vidéo"
    assert {k: v for k, v in plan.scenes[0].to_dict().items() if k != "scene_variants"} == \
        {k: v for k, v in scenes[0].to_dict().items() if k != "scene_variants"}
    assert stored(run(plan.scenes, *[parse_op(o) for o in plan.inverse]).scenes) == stored(scenes)
    assert refused(scenes, SceneVariantRename(S1, other, "ORIGINAL")).code is C.ALREADY_EXISTS
    assert refused(scenes, SceneVariantCreate(S1, "original")).code is C.ALREADY_EXISTS
    assert run(scenes, SceneVariantRename(S1, other, "B")).outcomes[0]["changed"] is False  # same label: no inverse, no change


def test_select_with_drop_others_keeps_one_variant_and_its_inverse_brings_every_other_back_exactly():
    scenes, original, other = two_variants()
    scenes = run(scenes, SceneVariantCreate(S1, "C")).scenes
    before = stored(scenes)
    plan = run(scenes, SceneVariantSelect(S1, other, drop_others=True))
    assert plan.scenes[0].scene_variants is None and plan.scenes[0].props == scene().props
    assert len(plan.inverse) == 2 and plan.inverse[0]["op"] == "scene_variant.restore_set" \
        and plan.inverse[1]["op"] == "scene_variant.select"  # applied in this order: the set back, then the old selection
    assert stored(run(plan.scenes, *[parse_op(o) for o in plan.inverse]).scenes) == before
    same = run(scenes, SceneVariantSelect(S1, original, drop_others=True))  # promote the selected into the scene: just drop the rest
    assert same.scenes[0].scene_variants is None and len(same.inverse) == 1
    assert stored(run(same.scenes, *[parse_op(o) for o in same.inverse]).scenes) == before


# ------------------------------------------------------------------ restore_set : jamais un contenu perdu

def test_restore_set_replaces_the_set_wholesale_but_never_the_selected_variant_nor_the_scene():
    scenes, original, other = two_variants()
    snapshot = scenes[0].scene_variants.to_dict()
    assert run(scenes, SceneVariantRestoreSet(S1, None)).scenes[0].scene_variants is None
    assert stored(run(run(scenes, SceneVariantRestoreSet(S1, None)).scenes, SceneVariantRestoreSet(S1, snapshot)).scenes) == stored(scenes)
    chosen = run(scenes, SceneVariantSelect(S1, other)).scenes
    assert refused(chosen, SceneVariantRestoreSet(S1, snapshot)).code is C.INVALID_PRESENTATION  # would drop the live content
    bad = copy.deepcopy(snapshot)
    bad["items"][1]["content"]["prefab"] = {"id": "lab.counter", "version": 0}
    assert refused(scenes, SceneVariantRestoreSet(S1, bad)).code is C.INVALID_PRESENTATION
    shapeless = copy.deepcopy(snapshot)
    shapeless["items"][1]["content"] = {"props": {}}
    with pytest.raises(PresentationStudioError):
        SceneVariantRestoreSet.parse({"op": "scene_variant.restore_set", "scene_id": S1, "scene_variants": shapeless})


def test_reserved_property_names_are_refused_in_a_restored_set():
    scenes, _, _ = two_variants()
    snapshot = scenes[0].scene_variants.to_dict()
    snapshot["items"][1]["content"]["props"] = {"__proto__": {"x": 1}}
    assert refused(scenes, SceneVariantRestoreSet(S1, snapshot)).code is C.INVALID_PRESENTATION
    snapshot = scenes[0].scene_variants.to_dict()
    snapshot["items"][1]["content"]["controls"][0]["path"] = "props.constructor"
    assert refused(scenes, SceneVariantRestoreSet(S1, snapshot)).code is C.INVALID_PRESENTATION


# ------------------------------------------------------------------ bornes

def test_a_scene_holds_at_most_eight_local_variants_and_the_ninth_is_a_limit_reached():
    plan = run([scene()], *[SceneVariantCreate(S1, f"V{n}") for n in range(MAX_SCENE_VARIANTS - 1)])
    assert len(plan.scenes[0].scene_variants.items) == MAX_SCENE_VARIANTS
    refusal = refused(plan.scenes, SceneVariantCreate(S1, "Trop"))
    assert refusal.code is C.LIMIT_REACHED and str(MAX_SCENE_VARIANTS) in refusal.message
    assert refused([scene()], *[SceneVariantCreate(S1, f"V{n}") for n in range(MAX_SCENE_VARIANTS)]).index == MAX_SCENE_VARIANTS - 1


def test_the_bytes_of_one_set_are_bounded_so_that_its_undo_record_always_fits():
    heavy = scene(data={"count": 1, **{f"k{n}": "x" * 1500 for n in range(8)}})  # ~12 KB: inside the 16 KiB payload cap of a scene
    with pytest.raises(EditRefusal) as caught:
        run([heavy], *[SceneVariantCreate(S1, f"V{n}") for n in range(MAX_SCENE_VARIANTS - 1)])
    assert caught.value.code is C.LIMIT_REACHED and f"{MAX_SET_BYTES}" in caught.value.message
    assert 0 < caught.value.index < MAX_SCENE_VARIANTS - 1  # a few fit, then the bound says so, with the way out


def test_labels_and_rationales_are_one_bounded_printable_line():
    for label in ("", " pad", "pad ", "a\nb", "x" * 41, "‮RTL", 5, None):
        with pytest.raises(PresentationStudioError):
            SceneVariantCreate.parse({"op": "scene_variant.create", "scene_id": S1, "label": label})
    for rationale in ("a\nb", "x" * 161, " pad", 5):
        with pytest.raises(PresentationStudioError):
            SceneVariantCreate.parse({"op": "scene_variant.create", "scene_id": S1, "label": "ok", "rationale": rationale})
    ok = SceneVariantCreate.parse({"op": "scene_variant.create", "scene_id": S1, "label": "Révélation émoji 🎬 " + "x" * 5})
    assert ok.label.startswith("Révélation")


def test_a_stored_variant_is_a_scene_in_its_own_right_so_the_payload_cap_and_the_pin_grammar_apply_to_it():
    scenes, _, other = two_variants()
    wire = scenes[0].to_dict()
    wire["scene_variants"]["items"][1]["content"]["data"] = {"huge": "x" * 20000}
    with pytest.raises(PresentationStudioError) as caught:
        StudioScene.from_dict(wire)
    assert caught.value.code is C.INVALID_PRESENTATION
    wire = scenes[0].to_dict()
    wire["scene_variants"]["items"][1]["content"]["prefab"] = {"id": "not a prefab", "version": 1}
    with pytest.raises(PresentationStudioError):
        StudioScene.from_dict(wire)
    wire = scenes[0].to_dict()
    wire["scene_variants"]["items"][1]["content"]["extra"] = 1
    with pytest.raises(PresentationStudioError):
        StudioScene.from_dict(wire)
    wire = scenes[0].to_dict()
    wire["scene_variants"]["items"][0]["content"] = scenes[0].live_content()  # the selected one must not store a second copy
    with pytest.raises(PresentationStudioError):
        StudioScene.from_dict(wire)


def test_runtime_state_names_are_refused_as_keys_of_the_stored_set():
    scenes, _, _ = two_variants()
    wire = scenes[0].to_dict()
    wire["scene_variants"]["selected"] = wire["scene_variants"].pop("current_id")  # `selected` is a runtime-only name (RUNTIME_KEYS)
    with pytest.raises(PresentationStudioError) as caught:
        StudioScene.from_dict(wire)
    assert caught.value.code is C.RUNTIME_STATE_REFUSED


# ------------------------------------------------------------------ isolation

def test_operations_on_one_scene_never_touch_another_scene_hash_checked():
    a, b = scene(S1), scene(S2, title="Autre")
    created = run([a, b], SceneVariantCreate(S1, "B")).scenes
    assert created[1] is b and hashlib.sha256(json.dumps(created[1].to_dict()).encode()).digest() ==         hashlib.sha256(json.dumps(b.to_dict()).encode()).digest()
    both = run(created, SceneVariantCreate(S2, "B2"))
    picked = both.outcomes[0]["scene_variant_id"]
    final = run(both.scenes, SceneVariantSelect(S2, picked), SceneVariantRename(S2, picked, "Renamed"))
    assert stored([final.scenes[0]]) == stored([created[0]])  # scene A: byte for byte, whatever happens to scene B
    assert final.scenes[1].scene_variants.current_id == picked and created[0].scene_variants.current_id != picked


def test_a_failing_operation_cancels_the_whole_batch_and_writes_nothing_anywhere():
    scenes, original, other = two_variants()
    before = stored(scenes)
    refusal = refused(scenes, SceneVariantSelect(S1, other), SceneVariantDelete(S1, other))  # the second one is now protected
    assert refusal.code is C.SCENE_VARIANT_PROTECTED and refusal.index == 1
    assert stored(scenes) == before  # apply_ops works on a copy


def test_a_scene_added_with_its_set_keeps_it_and_a_reserved_name_inside_it_is_refused():
    scenes, _, _ = two_variants()
    added = run([scene(S2)], SceneAdd(scenes[0], 0))
    assert stored([added.scenes[0]]) == stored([scenes[0]])
    hostile = copy.deepcopy(scenes[0].to_dict())
    hostile["scene_variants"]["items"][1]["content"]["data"] = {"constructor": 1}
    assert refused([scene(S2)], SceneAdd(StudioScene.from_dict(hostile), 0)).code is C.INVALID_PRESENTATION


# ------------------------------------------------------------------ vocabulaire, autorité, classement

def test_the_five_operations_round_trip_their_wire_form_and_are_structure_tier_for_both_actors():
    snapshot = two_variants()[0][0].scene_variants.to_dict()
    ops = [SceneVariantCreate(S1, "B", "r", "psx_000000000002"), SceneVariantRename(S1, "psx_000000000002", "C"),
           SceneVariantSelect(S1, "psx_000000000002", True), SceneVariantDelete(S1, "psx_000000000002"),
           SceneVariantRestoreSet(S1, snapshot), SceneVariantRestoreSet(S1, None)]
    assert {op.NAME for op in ops} == {n for n in OpName if n.value.startswith("scene_variant.")}
    for op in ops:
        assert parse_op(json.loads(json.dumps(op.to_dict()))) == op
        assert classify_op(op) is EditTier.STRUCTURE
    for actor in StudioActor:
        assert {o for o in ALLOWED_EDIT_OPS[actor] if o.value.startswith("scene_variant.")} == \
            {n for n in OpName if n.value.startswith("scene_variant.")}


def test_malformed_operations_are_refused_naming_what_is_wrong():
    for raw in ({"op": "scene_variant.select", "scene_id": S1}, {"op": "scene_variant.select", "scene_id": S1, "variant_id": "x"},
                {"op": "scene_variant.select", "scene_id": S1, "variant_id": "psx_000000000002", "drop_others": "yes"},
                {"op": "scene_variant.create", "scene_id": S1, "label": "B", "from_variant": "nope"},
                {"op": "scene_variant.delete", "scene_id": "bad", "variant_id": "psx_000000000002"},
                {"op": "scene_variant.rename", "scene_id": S1, "variant_id": "psx_000000000002", "label": "B", "extra": 1},
                {"op": "scene_variant.restore_set", "scene_id": S1},
                {"op": "scene_variant.create", "scene_id": S1, "label": "B", "selected": "psx_000000000002"}):
        with pytest.raises(PresentationStudioError) as caught:
            parse_op(raw)
        assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED), raw


# ------------------------------------------------------------------ pins

def test_the_pins_of_a_scene_include_every_stored_local_variant_and_the_undo_pins_do_too():
    scenes, original, other = two_variants()
    wire = scenes[0].to_dict()
    wire["scene_variants"]["items"][1]["content"]["prefab"] = {"id": "lab.counter", "version": 7}
    carrying = StudioScene.from_dict(wire)
    assert carrying.held_pins() == {("lab.counter", 1), ("lab.counter", 7)}
    selected = run([carrying], SceneVariantSelect(S1, other)).scenes[0]
    assert selected.held_pins() == {("lab.counter", 1), ("lab.counter", 7)}  # the pin moved into the slot, never out of the document
    assert pins_of([SceneAdd(carrying, 0).to_dict()]) == {("lab.counter", 1), ("lab.counter", 7)}
    snapshot = carrying.scene_variants.to_dict()
    assert pins_of([SceneVariantRestoreSet(S1, snapshot).to_dict()]) == {("lab.counter", 7)}  # the live scene's own pin is already in the document
    assert pins_of([SceneVariantRestoreSet(S1, None).to_dict(), SceneVariantSelect(S1, other).to_dict()]) == frozenset()


# ------------------------------------------------------------------ hasard gouverné : rien ne se perd, tout se défait

def model_of(scene_: StudioScene) -> dict[str, str]:
    """`{id: contenu canonique}` de **toutes** les variantes locales : la scène pour la choisie, le rangé pour les autres."""

    if scene_.scene_variants is None:
        return {}
    return {item.variant_id: canonical_json(scene_.live_content() if item.content is None else item.content)
            for item in scene_.scene_variants.items}


@pytest.mark.parametrize("seed", range(12))
def test_random_sequences_never_lose_a_content_and_every_step_is_exactly_reversible(seed):
    rng = random.Random(seed)
    ids = Ids(seed * 1000)
    current = scene()
    history: list[tuple[str, list[dict]]] = []  # (bytes before, inverse ops)
    known: dict[str, str] = {}  # content of every variant ever seen, by id: it must never change by itself
    for step in range(60):
        items = current.scene_variants.items if current.scene_variants else ()
        pick = rng.choice([i.variant_id for i in items]) if items else None
        choice = rng.choice(["create", "create", "rename", "select", "select", "delete", "edit", "drop"])
        if choice == "create":
            op = SceneVariantCreate(S1, f"V{step}", from_variant=rng.choice([None, pick]) if pick else None)
        elif choice == "rename" and pick:
            op = SceneVariantRename(S1, pick, f"R{step}")
        elif choice == "select" and pick:
            op = SceneVariantSelect(S1, pick)
        elif choice == "drop" and pick and rng.random() < 0.3:
            op = SceneVariantSelect(S1, pick, drop_others=True)
        elif choice == "delete" and pick:
            op = SceneVariantDelete(S1, pick)
        elif choice == "edit":  # the author edits the live scene: it changes the content of the SELECTED variant only
            live = rng.randint(0, 10_000)
            current = replace(current, props={**current.props, "n": live}, data={**current.data, "list": [live, 1, 2]})
            if current.scene_variants:
                known[current.scene_variants.current_id] = model_of(current)[current.scene_variants.current_id]
            continue
        else:
            continue
        before_model, before_bytes = model_of(current), stored([current])
        try:
            plan = run([current], op, ids=ids)
        except EditRefusal as refusal:
            assert refusal.code in (C.LIMIT_REACHED, C.SCENE_VARIANT_PROTECTED, C.ALREADY_EXISTS), refusal.code
            continue
        after = plan.scenes[0]
        after_model = model_of(after)
        if isinstance(op, (SceneVariantSelect, SceneVariantRename, SceneVariantCreate)) and not getattr(op, "drop_others", False):
            # a permutation: every pre-existing variant keeps exactly its content, nothing is lost or duplicated
            assert {k: v for k, v in after_model.items() if k in before_model} == before_model
        if isinstance(op, SceneVariantSelect) and not op.drop_others:
            assert after.scene_variants.current_id == op.variant_id
        if isinstance(op, SceneVariantDelete):
            assert set(before_model) - set(after_model) == {op.variant_id} or not after_model
        # the inverse restores the bytes, and the redo (inverse of the inverse) restores the result
        if plan.inverse:
            back = run([after], *[parse_op(o) for o in plan.inverse], ids=ids)
            assert stored(back.scenes) == before_bytes and canon(back.scenes) == canon([current])
            again = run(back.scenes, *[parse_op(o) for o in back.inverse], ids=ids)
            assert stored(again.scenes) == stored([after])
        current = after
        for variant_id, content in after_model.items():
            known.setdefault(variant_id, content) if variant_id != (after.scene_variants.current_id if after.scene_variants else None) else None
        assert after.scene_variants is None or len(after.scene_variants.items) >= 2
        assert StudioScene.from_dict(json.loads(json.dumps(after.to_dict()))) == after  # the stored form re-reads to itself
