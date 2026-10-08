"""Variantes locales : la taille ne fait jamais échouer un choix, bornes du paquet et du document, marge d'annulation, provenance
forgée (jarvis-interactive-presentation-studio, Slice 17, reprise QA-1).

Règle : `select` est une permutation (les octets totaux, stocké + vivant, sont conservés), donc il, son annulation et un `restore_set`
n'échouent jamais pour la taille ; seul `create` (et un renommage qui fait grossir un ensemble déjà trop gros) la refuse, en nommant
la cause et la sortie. Contrat : `docs/presentation-studio.md` › *Scene-local variant contract*, Size and limits.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_edit import (
    ALLOWED_EDIT_OPS, MAX_UNDO_BYTES, EditRefusal, SceneRemove, SceneVariantCreate, SceneVariantDelete, SceneVariantRename,
    SceneVariantRestoreSet, SceneVariantSelect, StudioActor, parse_op, undo_record,
)
from jarvis.domain.presentation_studio_scene import StudioScene
from jarvis.domain.presentation_studio_scene_variants import (
    MAX_DECK_VARIANTS, MAX_SCENE_VARIANTS, MAX_SET_BYTES, deck_stored_variants,
)
from tests.unit.test_presentation_studio_scene_variants_domain import S1, refused, run, scene, stored, two_variants


def fat(kb: int) -> StudioScene:
    """Une scène dont le contenu vivant pèse ~`kb` Kio (valeurs de `props`, sous le plafond de 16 Kio d'une charge de scène)."""

    return scene(props={"pad": "x" * (kb * 1024)})


def with_three_copies():
    plan = run([scene(props={"pad": "x" * 6000})], *[SceneVariantCreate(S1, f"V{n}") for n in range(3)])
    assert plan.scenes[0].scene_variants.total_bytes(plan.scenes[0].live_content()) <= MAX_SET_BYTES
    return plan.scenes[0]


def test_select_never_fails_for_size_even_when_the_live_scene_grew_past_the_set_cap():
    # QA-1 repro: stored copies near the cap, the live scene then edited much bigger, then a select moves the big live content to the stored side
    grown = replace(with_three_copies(), props={"pad": "y" * 14000})  # a normal edit of the live scene
    total = grown.scene_variants.total_bytes(grown.live_content())
    assert total > MAX_SET_BYTES, "the live scene grew past the cap by itself: allowed, the document cap is the limit"
    target = grown.scene_variants.items[1].variant_id
    chosen = run([grown], SceneVariantSelect(S1, target))  # a permutation: it must not be refused
    after = chosen.scenes[0]
    assert after.scene_variants.total_bytes(after.live_content()) == total  # total bytes conserved exactly
    back = run(chosen.scenes, *[parse_op(o) for o in chosen.inverse])  # and so is its undo
    assert stored(back.scenes) == stored([grown])
    there_and_back = run(chosen.scenes, SceneVariantSelect(S1, grown.scene_variants.current_id), SceneVariantSelect(S1, target))
    assert there_and_back.scenes[0].scene_variants.current_id == target
    # an undo/redo-shaped restore_set of an over-the-cap set, a delete from it and a promote-into-current all work too
    assert run([after], SceneVariantRestoreSet(S1, after.scene_variants.to_dict())).scenes[0] == after
    assert run([after], SceneVariantDelete(S1, after.scene_variants.items[2].variant_id)).scenes[0].scene_variants is not None
    dropped = run([after], SceneVariantSelect(S1, after.scene_variants.items[0].variant_id, drop_others=True))
    assert dropped.scenes[0].scene_variants is None


def test_create_is_the_operation_that_refuses_a_grown_scene_and_says_the_cause_and_the_way_out():
    grown = replace(with_three_copies(), props={"pad": "y" * 14000})
    refusal = refused([grown], SceneVariantCreate(S1, "Encore"))
    assert refusal.code is C.LIMIT_REACHED and refusal.index == 0
    for needle in ("stored contents plus the live scene", f"{MAX_SET_BYTES}", "delete a variant", "promote one to a presentation variant"):
        assert needle in refusal.message, needle
    # a rename never changes the contents total (labels are metadata): it is never refused for size, even on a scene over the cap
    other = grown.scene_variants.items[1]
    assert run([grown], SceneVariantRename(S1, other.variant_id, other.label)).outcomes[0]["changed"] is False
    renamed = run([grown], SceneVariantRename(S1, other.variant_id, "x" * 40)).scenes[0]
    assert renamed.scene_variants.get(other.variant_id).label == "x" * 40
    assert renamed.scene_variants.total_bytes(renamed.live_content()) == grown.scene_variants.total_bytes(grown.live_content())


def test_a_set_that_fits_is_only_refused_by_create_when_the_total_would_pass_the_cap():
    plan = run([fat(6)], SceneVariantCreate(S1, "A"), SceneVariantCreate(S1, "B"))  # 3 x 6 KiB
    assert plan.scenes[0].scene_variants.total_bytes(plan.scenes[0].live_content()) < MAX_SET_BYTES
    refusal = refused(plan.scenes, SceneVariantCreate(S1, "C"), SceneVariantCreate(S1, "D"), SceneVariantCreate(S1, "E"))
    assert refusal.code is C.LIMIT_REACHED and refusal.index in (0, 1, 2)


def test_the_whole_deck_bound_refuses_the_49th_stored_variant_and_names_the_cause():
    scenes = [scene("pss_%012x" % (n + 1)) for n in range(7)]
    made = 0
    for original in list(scenes):
        for n in range(MAX_SCENE_VARIANTS - 1):
            if made == MAX_DECK_VARIANTS:
                break
            scenes = list(run(scenes, SceneVariantCreate(original.scene_id, f"V{n}")).scenes)
            made += 1
    assert made == MAX_DECK_VARIANTS == deck_stored_variants(scenes)
    spare = next(s for s in scenes if s.scene_variants is None or len(s.scene_variants.items) < MAX_SCENE_VARIANTS)
    refusal = refused(scenes, SceneVariantCreate(spare.scene_id, "Trop"))
    assert refusal.code is C.LIMIT_REACHED
    for needle in (str(MAX_DECK_VARIANTS), "across its scenes", "256 KiB", "delete a variant", "promote one"):
        assert needle in refusal.message, needle
    victim = next(s for s in scenes if s.scene_variants)
    freed = run(scenes, SceneVariantDelete(victim.scene_id, victim.scene_variants.items[1].variant_id)).scenes
    assert run(freed, SceneVariantCreate(spare.scene_id, "Ok")).scenes  # deleting makes room again
    assert run(scenes, SceneVariantSelect(victim.scene_id, victim.scene_variants.items[1].variant_id)).scenes  # a select never counts


def test_the_undo_record_of_removing_a_maxed_out_scene_with_its_full_set_keeps_a_comfortable_margin():
    """Worst case: a scene at its payload cap with 32 controls and 16 anchors, a set created at the cap with a small live scene, the live
    scene then grown to the maximum and moved to the stored side by a select. `scene.remove` carries the whole scene and its set."""

    controls = [{"control_id": f"c{n}", "path": f"props.p{n}", "label": "Controle " + "x" * 20, "group": "content",
                 "meaning": "m" * 150} for n in range(32)]
    anchors = [{"anchor_id": f"a{n}", "label": "Repere " + "y" * 20} for n in range(16)]

    def maxed(pad: int) -> StudioScene:
        return scene(props={"pad": "é" * pad}, controls=controls, anchors=anchors, title="T" * 80, section="s" * 40)

    low, high = 0, 20000
    while low < high:
        mid = (low + high + 1) // 2
        try:
            maxed(mid)
            low = mid
        except PresentationStudioError:
            high = mid - 1
    biggest = maxed(low)
    scenes: list[StudioScene] = [maxed(200)]
    while True:
        try:
            count = len(scenes[0].scene_variants.items) if scenes[0].scene_variants else 0
            scenes = list(run(scenes, SceneVariantCreate(S1, f"V{count}")).scenes)
        except EditRefusal as refusal:
            assert refusal.code is C.LIMIT_REACHED
            break
    grown = replace(scenes[0], props=biggest.props)
    other = next(i.variant_id for i in grown.scene_variants.items if i.variant_id != grown.scene_variants.current_id)
    moved = run([grown], SceneVariantSelect(S1, other)).scenes[0]
    margins = []
    for candidate in (grown, moved):
        record = undo_record(run([candidate], SceneRemove(S1)), presentation_id="pst_" + "0" * 32, variant_id="psv_" + "0" * 32,
                             restores_revision=1, applies_at_revision=2)
        assert record["available"] is True, record
        margins.append(MAX_UNDO_BYTES - record["bytes"])
        victim = next(i.variant_id for i in candidate.scene_variants.items if i.variant_id != candidate.scene_variants.current_id)
        delete = undo_record(run([candidate], SceneVariantDelete(S1, victim)), presentation_id="p", variant_id="v",
                             restores_revision=1, applies_at_revision=2)
        assert delete["available"] is True and MAX_UNDO_BYTES - delete["bytes"] > 8 * 1024
    assert min(margins) > 8 * 1024, ("remove(scene + full set) must keep a comfortable margin in the 64 KiB record", margins)


def test_a_forged_restore_set_is_refused_like_a_forged_create_for_both_actors():
    scenes, original, other = two_variants()
    good = scenes[0].scene_variants.to_dict()

    def forged(mutate):
        wire = copy.deepcopy(good)
        mutate(wire)
        return wire

    attempts = {
        "created_by system": forged(lambda w: w["items"][1].__setitem__("created_by", "system")),
        "created_by empty": forged(lambda w: w["items"][1].__setitem__("created_by", "")),
        "source not an id": forged(lambda w: w["items"][1].__setitem__("source", "somewhere")),
        "bad id": forged(lambda w: w["items"][1].__setitem__("variant_id", "psx_ZZZ")),
        "bad stamp": forged(lambda w: w["items"][1].__setitem__("created_at", "yesterday")),
        "label with newline": forged(lambda w: w["items"][1].__setitem__("label", "a\nb")),
        "label too long": forged(lambda w: w["items"][1].__setitem__("label", "x" * 41)),
        "rationale too long": forged(lambda w: w["items"][1].__setitem__("rationale", "x" * 161)),
        "unknown key": forged(lambda w: w["items"][1].__setitem__("trusted", True)),
        "runtime key": forged(lambda w: w["items"][1].__setitem__("selected", True)),
        "duplicate id": forged(lambda w: w["items"].append(copy.deepcopy(w["items"][1]))),
        "duplicate label": forged(lambda w: w["items"][1].__setitem__("label", "original")),
        "stored entry without content": forged(lambda w: w["items"][1].pop("content")),
        "selected entry with content": forged(lambda w: w["items"][0].__setitem__("content", w["items"][1]["content"])),
        "unknown selected": forged(lambda w: w.__setitem__("current_id", "psx_ffffffffffff")),
        "nine variants": forged(lambda w: w["items"].extend(
            {**copy.deepcopy(w["items"][1]), "variant_id": "psx_%012x" % n, "label": f"L{n}"} for n in range(8))),
    }
    for actor in StudioActor:
        assert "scene_variant.restore_set" in {str(o) for o in ALLOWED_EDIT_OPS[actor]}  # open to both actors, by design
        for name, wire in attempts.items():
            with pytest.raises((EditRefusal, PresentationStudioError)):
                run(scenes, SceneVariantRestoreSet(S1, wire), actor=actor)
                pytest.fail(f"forged restore_set accepted: {name}")
    # a well-formed set is validated exactly like a create's: provenance of either actor is a legal value, nothing more is believed
    ok = forged(lambda w: w["items"][1].__setitem__("created_by", "brain"))
    assert run(scenes, SceneVariantRestoreSet(S1, ok)).scenes[0].scene_variants.get(other).created_by == "brain"


async def test_a_refusing_transform_spends_no_variant_number_and_writes_nothing(tmp_path):
    """The mutant 'the transform runs after the number is allocated': a promote refused by its transform must leave `variant_counter`
    and every file as they were (hash-checked), and the next branch takes the next number with no hole."""

    from tests.unit.test_presentation_studio_scene_variants_service import World

    world = await World(tmp_path).open()
    await world.make(S1, "B")
    counter = (await world.studio.get(world.pid)).presentation.variant_counter
    before = world.tree()

    def refusing(source):
        raise PresentationStudioError(C.UNKNOWN_SCENE_VARIANT, "gone since the check")

    with pytest.raises(PresentationStudioError) as caught:
        await world.variants.create_branch(world.pid, {"title": "Promue"}, transform=refusing)
    assert caught.value.code is C.UNKNOWN_SCENE_VARIANT
    assert (await world.studio.get(world.pid)).presentation.variant_counter == counter and world.tree() == before
    again = await world.variants.create_branch(world.pid, {"title": "Suivante"})
    assert again["node"]["variant_number"] == counter + 1  # no hole: the number was never spent
