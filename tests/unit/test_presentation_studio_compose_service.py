"""Composition semantique de variantes contre le vrai magasin, le vrai `PrefabService` et la vraie API de branche
(jarvis-interactive-presentation-studio, Slice 19).

Une nouvelle variante enfant dont chaque dimension (scenes, narration, mouvement, direction artistique) vient d'une source nommee ;
provenance explicite ecrite avec elle ; sources **octet pour octet** identiques ; conflits types rendus ensemble avant toute ecriture
(ni fichier ni numero depense) ; revisions (CAS) ; plan a blanc ; arret brutal ; redemarrage. Contrat : `docs/presentation-studio.md` >
*Comparison and semantic composition contract*.
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.presentation_studio_composition import PresentationStudioComposition
from jarvis.domain.prefab import canonical_json
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_composition import (
    CompositionRefused, ConflictCode as K, DIMENSIONS, parse_composition, parse_provenance,
)
from tests.fakes import presentation_studio_art_direction as fx
from tests.unit.test_presentation_studio_score_service import I1, I2, I3, S1, S2, scene_body, score_body
from tests.unit.test_presentation_studio_variants_service import Rig

NO_VARIANT = "psv_" + "0" * 32


async def build(tmp_path, *, art=True, score=True):
    rig = await Rig(tmp_path).open(score=score)
    comp = PresentationStudioComposition(rig.studio, rig.variants)
    if art:
        root = await rig.studio.get_variant(rig.pid, rig.root_id)
        await rig.studio.create_art_direction(rig.pid, rig.root_id, {"expected_variant_revision": root.revision, "profile": fx.base_dict()})
    return rig, comp


async def retext(rig, variant_id, **texts):
    """Change le texte dit de quelques items d'une partition (par `item_id`)."""

    doc = (await rig.studio.get_score(rig.pid, variant_id))["score"]
    items = [dict(item) for item in doc["items"]]
    for item in items:
        if item["item_id"] in texts:
            item["text"] = texts[item["item_id"]]
    content = {k: doc[k] for k in ("start_item_id", "items", "cues", "sequences", "recovery_points")}
    await rig.studio.save_score(rig.pid, variant_id, {"expected_revision": doc["revision"], **content, "items": items})


async def branch(rig, title, **extra):
    return (await rig.branch(title, **extra))["variant"]["variant_id"]


def body(base, **extra):
    return {"title": "Composition", "base": base, **extra}


def stored_variant(rig, variant_id):
    return json.loads((rig.folder / "variants" / f"{variant_id}.json").read_text(encoding="utf-8"))


def stored_score(rig, variant_id):
    return json.loads((rig.folder / "scores" / f"{stored_variant(rig, variant_id)['score_id']}.json").read_text(encoding="utf-8"))


def stored_art(rig, variant_id):
    return json.loads((rig.folder / "art_directions" / f"{stored_variant(rig, variant_id)['art_direction_id']}.json").read_text(encoding="utf-8"))


def untouched(before, after, *, allowed=("presentation.json",)):
    """Chaque fichier qui existait est identique, sauf ceux nommes : seuls des fichiers neufs sont apparus."""

    changed = {name for name, digest in before.items() if after.get(name) != digest}
    assert changed <= set(allowed), f"a source file changed: {sorted(changed - set(allowed))}"
    return sorted(set(after) - set(before))


async def refusal(awaitable) -> CompositionRefused:
    with pytest.raises(CompositionRefused) as caught:
        await awaitable
    assert caught.value.code is C.COMPOSITION_REFUSED and caught.value.status == 409
    return caught.value


def codes(refused) -> list[str]:
    return [c["code"] for c in refused.conflicts]


# ------------------------------------------------------------------ borrowing, one dimension at a time

async def test_the_narrative_comes_from_another_branch_while_motion_and_art_stay_with_the_base(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    await retext(rig, beta, **{I1: "Salut a tous."})
    before = rig.snapshot()
    answer = await comp.compose(rig.pid, body(rig.root_id, narrative=beta, rationale="le ton de Beta"))
    new = answer["variant"]["variant_id"]
    new_files = untouched(before, rig.snapshot())
    assert len(new_files) == 4 and f"variants/{new}.json" in new_files  # the variant, its score and art direction copies, its provenance
    score, base_score = stored_score(rig, new), stored_score(rig, rig.root_id)
    assert next(i for i in score["items"] if i["item_id"] == I1)["text"] == "Salut a tous."
    assert score["score_id"] != base_score["score_id"] and score["variant_id"] == new and score["revision"] == 1
    assert [i["item_id"] for i in score["items"]] == [I1, I2, I3] and score["cues"] == base_score["cues"]
    assert next(i for i in score["items"] if i["item_id"] == I2)["motion"] == next(i for i in base_score["items"] if i["item_id"] == I2)["motion"]
    node = answer["node"]
    assert node["variant_number"] == 3 and node["parent_variant_id"] == rig.root_id and node["created_by"] == "user"
    assert node["sources"] == [rig.root_id, beta] and node["rationale"].startswith("composed on #1; narrative #2.") and node["rationale"].endswith("le ton de Beta")
    assert stored_variant(rig, new)["parent_variant_id"] == rig.root_id and answer["activated"] is False


async def test_the_motion_comes_from_another_branch_and_keeps_the_base_narration(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    doc = (await rig.studio.get_score(rig.pid, beta))["score"]
    items = [dict(i) for i in doc["items"]]
    items[1]["motion"] = [{"kind": "control_set", "scene_id": S1, "control_id": "density", "value": "full"}]  # I2: another motion value
    await rig.studio.save_score(rig.pid, beta, {"expected_revision": doc["revision"], "start_item_id": doc["start_item_id"], "items": items,
                                                  "cues": doc["cues"], "sequences": doc["sequences"], "recovery_points": doc["recovery_points"]})
    await retext(rig, beta, **{I1: "Texte de Beta."})
    answer = await comp.compose(rig.pid, body(rig.root_id, motion=beta))
    score = stored_score(rig, answer["variant"]["variant_id"])
    by_id = {i["item_id"]: i for i in score["items"]}
    assert by_id[I2]["motion"][0]["value"] == "full", "the motion is Beta's"
    assert by_id[I1]["text"] == "Bonjour.", "the narrative is the base's: the text Beta wrote is not borrowed"
    provenance = (await comp.provenance(rig.pid, answer["variant"]["variant_id"]))["composition"]
    narrative = {d["dimension"]: d for d in provenance["dimensions"]}["narrative"]
    assert narrative["inherited"] is True and narrative["sources"][0]["variant_id"] == rig.root_id


async def test_the_art_direction_is_a_deep_copy_of_the_chosen_branch(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    art = (await rig.studio.get_art_direction(rig.pid, beta))["art_direction"]
    await rig.studio.save_art_direction(rig.pid, beta, {"expected_revision": art["revision"], "profile": fx.full_dict()})
    before = rig.snapshot()
    answer = await comp.compose(rig.pid, body(rig.root_id, art_direction=beta))
    untouched(before, rig.snapshot())
    new_art, beta_art = stored_art(rig, answer["variant"]["variant_id"]), stored_art(rig, beta)
    assert new_art["profile"] == beta_art["profile"] != stored_art(rig, rig.root_id)["profile"]
    assert new_art["art_direction_id"] not in (beta_art["art_direction_id"], stored_art(rig, rig.root_id)["art_direction_id"])
    assert new_art["variant_id"] == answer["variant"]["variant_id"] and new_art["revision"] == 1
    assert stored_score(rig, answer["variant"]["variant_id"])["items"] == stored_score(rig, rig.root_id)["items"]


async def test_the_scenes_can_come_from_several_branches_in_the_order_of_the_segments(tmp_path):
    rig, comp = await build(tmp_path, score=False, art=False)
    beta = await branch(rig, "Beta")
    variant = await rig.studio.get_variant(rig.pid, beta)
    changed = {**scene_body(S1), "title": "Titre de Beta"}
    await rig.studio.save_variant(rig.pid, beta, {"expected_revision": variant.revision, "title": variant.title, "scenes": [changed, scene_body(S2)],
                                                  "art_direction_id": None, "score_id": None})
    before = rig.snapshot()
    answer = await comp.compose(rig.pid, body(rig.root_id, scenes=[{"from": beta, "scene_ids": [S1]}, {"from": rig.root_id, "scene_ids": [S2]}]))
    untouched(before, rig.snapshot())
    scenes = stored_variant(rig, answer["variant"]["variant_id"])["scenes"]
    assert [s["scene_id"] for s in scenes] == [S1, S2] and scenes[0]["title"] == "Titre de Beta"
    assert canonical_json(scenes[1]) == canonical_json(stored_variant(rig, rig.root_id)["scenes"][1])
    assert answer["node"]["sources"] == [rig.root_id, beta]
    # a single source given as a bare id takes all of its scenes, reordered scenes keep the order asked
    only = await comp.compose(rig.pid, body(rig.root_id, title="Tout Beta", scenes=beta))
    assert [s["title"] for s in stored_variant(rig, only["variant"]["variant_id"])["scenes"]][0] == "Titre de Beta"
    reordered = await comp.compose(rig.pid, body(rig.root_id, title="Inverse", scenes=[{"from": rig.root_id, "scene_ids": [S2, S1]}]))
    assert [s["scene_id"] for s in stored_variant(rig, reordered["variant"]["variant_id"])["scenes"]] == [S2, S1]


async def test_all_four_dimensions_from_four_different_branches(tmp_path):
    rig, comp = await build(tmp_path)
    a, b, c = await branch(rig, "A"), await branch(rig, "B"), await branch(rig, "C")
    await retext(rig, b, **{I1: "Texte de B."})
    art = (await rig.studio.get_art_direction(rig.pid, c))["art_direction"]
    await rig.studio.save_art_direction(rig.pid, c, {"expected_revision": art["revision"], "profile": fx.full_dict()})
    before = rig.snapshot()
    request = body(rig.root_id, scenes=a, narrative=b, motion=a, art_direction=c, source_revisions={a: 1, b: 1, c: 1})
    answer = await comp.compose(rig.pid, request)
    untouched(before, rig.snapshot())
    new = answer["variant"]["variant_id"]
    assert answer["node"]["sources"] == [rig.root_id, a, b, c]
    document = (await comp.provenance(rig.pid, new))["composition"]
    assert [d["dimension"] for d in document["dimensions"]] == list(DIMENSIONS) and document["base_variant_id"] == rig.root_id
    rows = {d["dimension"]: d for d in document["dimensions"]}
    assert [rows[d]["sources"][0]["variant_id"] for d in DIMENSIONS] == [a, b, a, c]
    assert not any(rows[d]["inherited"] for d in DIMENSIONS)
    assert rows["art_direction"]["sources"][0]["document_id"] == stored_variant(rig, c)["art_direction_id"]
    assert rows["narrative"]["sources"][0]["source_revision"] == 1 and rows["scenes"]["sources"][0]["scene_ids"] == [S1, S2]
    assert {k: v for k, v in answer["composition"].items() if k != "result"} == document
    assert answer["composition"]["result"]["sources"] == [rig.root_id, a, b, c]


async def test_nothing_named_is_a_plain_branch_of_the_base_with_every_dimension_inherited(tmp_path):
    rig, comp = await build(tmp_path)
    answer = await comp.compose(rig.pid, body(rig.root_id))
    document = (await comp.provenance(rig.pid, answer["variant"]["variant_id"]))["composition"]
    assert all(d["inherited"] for d in document["dimensions"]) and answer["node"]["sources"] == [rig.root_id]
    base, new = stored_variant(rig, rig.root_id), stored_variant(rig, answer["variant"]["variant_id"])
    assert canonical_json(new["scenes"]) == canonical_json(base["scenes"])
    assert [i for i in stored_score(rig, answer["variant"]["variant_id"])["items"]] == stored_score(rig, rig.root_id)["items"]


# ------------------------------------------------------------------ immutability, plan, activation

async def test_the_sources_are_byte_identical_after_composition_and_the_graph_gains_exactly_one_node(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    await retext(rig, beta, **{I1: "B."})
    before = rig.snapshot()
    answer = await comp.compose(rig.pid, body(rig.root_id, narrative=beta, art_direction=beta, scenes=beta))
    created = untouched(before, rig.snapshot())
    assert all(name.split("/")[0] in ("variants", "scores", "art_directions", "compositions") for name in created)
    assert f"compositions/{answer['variant']['variant_id']}.json" in created
    manifest = json.loads((rig.folder / "presentation.json").read_text(encoding="utf-8"))
    assert manifest["variant_counter"] == 3 and len(manifest["variants"]) == 3 and manifest["active_variant_id"] == rig.root_id
    node = next(n for n in manifest["variants"] if n["variant_id"] == answer["variant"]["variant_id"])
    assert node["sources"] == [rig.root_id, beta] and node["created_by"] == "user"


async def test_the_plan_judges_like_the_commit_and_writes_nothing_and_spends_no_number(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    before = rig.snapshot()
    planned = await comp.plan(rig.pid, body(rig.root_id, narrative=beta, art_direction=beta))
    assert planned["ok"] is True and planned["dry_run"] is True and planned["conflicts"] == []
    assert planned["composition"]["result"]["parent_variant_id"] == rig.root_id and planned["composition"]["result"]["sources"] == [rig.root_id, beta]
    assert rig.snapshot() == before, "a plan writes nothing"
    answer = await comp.compose(rig.pid, body(rig.root_id, narrative=beta, art_direction=beta))
    assert answer["node"]["variant_number"] == 3, "the plan spent no number"


async def test_a_plan_with_a_conflict_answers_200_shaped_ok_false_and_still_writes_nothing(tmp_path):
    rig, comp = await build(tmp_path, art=False)
    beta = await branch(rig, "Beta")
    before = rig.snapshot()
    refused = await comp.plan(rig.pid, body(rig.root_id, art_direction=beta))
    assert refused["ok"] is False and refused["composition"] is None and refused["dry_run"] is True
    assert [c["code"] for c in refused["conflicts"]] == [K.SOURCE_HAS_NO_ART_DIRECTION.value] and rig.snapshot() == before


async def test_activate_makes_the_composed_variant_active_in_the_same_manifest_write(tmp_path):
    rig, comp = await build(tmp_path)
    answer = await comp.compose(rig.pid, body(rig.root_id, activate=True, actor="brain"))
    assert answer["activated"] and answer["node"]["active"] and answer["node"]["created_by"] == "brain"
    assert (await rig.variants.graph(rig.pid))["active_variant_id"] == answer["variant"]["variant_id"]


async def test_the_composed_variant_carries_the_scenes_exactly_as_the_sources_had_them_and_is_a_pin_source(tmp_path):
    rig, comp = await build(tmp_path, score=False, art=False)
    beta = await branch(rig, "Beta")
    answer = await comp.compose(rig.pid, body(rig.root_id, scenes=beta))
    new = answer["variant"]["variant_id"]
    assert canonical_json(stored_variant(rig, new)["scenes"]) == canonical_json(stored_variant(rig, beta)["scenes"])
    index = await rig.variants.pin_index()
    assert index[(rig.pid, new)] == index[(rig.pid, beta)] == frozenset({("lab.counter", 1)})


# ------------------------------------------------------------------ conflicts and refusals

async def test_every_conflict_is_typed_actionable_and_listed_together_with_nothing_written(tmp_path):
    rig, comp = await build(tmp_path, art=False)
    plain = await branch(rig, "Sans partition")
    variant = await rig.studio.get_variant(rig.pid, plain)
    await rig.studio.save_variant(rig.pid, plain, {"expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body(S2)],
                                                   "art_direction_id": None, "score_id": variant.score_id})
    before = rig.snapshot()
    spent = (await rig.variants.graph(rig.pid))["variant_counter"]
    refused = await refusal(comp.compose(rig.pid, body(rig.root_id, scenes=plain, art_direction=plain)))
    assert set(codes(refused)) == {K.SCORE_SCENE_MISSING.value, K.SOURCE_HAS_NO_ART_DIRECTION.value}
    assert all(c["fix"] and c["message"] and c["dimension"] in DIMENSIONS for c in refused.conflicts)
    missing = next(c for c in refused.conflicts if c["code"] == K.SCORE_SCENE_MISSING.value)
    assert missing["details"]["scene_ids"]["items"] == [S1] and missing["details"]["item_ids"]["total"] == 3
    assert rig.snapshot() == before and (await rig.variants.graph(rig.pid))["variant_counter"] == spent
    planned = await comp.plan(rig.pid, body(rig.root_id, scenes=plain, art_direction=plain))
    assert planned["ok"] is False and [c["code"] for c in planned["conflicts"]] == codes(refused)


async def test_a_source_without_a_score_refuses_motion_and_narrative_borrowing_explicitly(tmp_path):
    rig, comp = await build(tmp_path, score=False, art=False)
    refused = await refusal(comp.compose(rig.pid, body(rig.root_id, motion=rig.root_id)))
    assert codes(refused) == [K.SOURCE_HAS_NO_SCORE.value] and refused.conflicts[0]["dimension"] == "motion"
    refused = await refusal(comp.compose(rig.pid, body(rig.root_id, narrative=rig.root_id)))
    assert codes(refused) == [K.SOURCE_HAS_NO_SCORE.value] and refused.conflicts[0]["dimension"] == "narrative"


async def test_scene_conflicts_missing_duplicate_and_too_many_sources(tmp_path):
    rig, comp = await build(tmp_path, score=False, art=False)
    beta, gamma, delta, epsilon = [await branch(rig, name) for name in "BCDE"]
    r = await refusal(comp.compose(rig.pid, body(rig.root_id, scenes=[{"from": beta, "scene_ids": ["pss_" + "9" * 12]}])))
    assert codes(r) == [K.SCENE_NOT_IN_SOURCE.value]
    r = await refusal(comp.compose(rig.pid, body(rig.root_id, scenes=[{"from": beta, "scene_ids": [S1]}, {"from": gamma, "scene_ids": [S1, S2]}])))
    assert codes(r) == [K.DUPLICATE_SCENE.value] and r.conflicts[0]["details"]["scene_ids"]["items"] == [S1]
    r = await refusal(comp.compose(rig.pid, body(rig.root_id, scenes=[{"from": beta, "scene_ids": [S1]}, {"from": gamma, "scene_ids": [S2]}],
                                               narrative=delta, motion=epsilon)))
    assert codes(r) == [K.TOO_MANY_SOURCES.value] and len(r.conflicts[0]["details"]["variant_ids"]) == 5


async def test_the_narrative_of_an_unrelated_score_is_refused_unless_the_caller_keeps_the_motion_narration(tmp_path):
    rig, comp = await build(tmp_path, art=False)
    other = await branch(rig, "Autre")
    doc = (await rig.studio.get_score(rig.pid, other))["score"]
    one = {"item_id": "psi_0000000000f1", "scene_id": S1, "presenter": "jarvis", "kind": "speech", "text": "Seule phrase."}
    await rig.studio.save_score(rig.pid, other, {"expected_revision": doc["revision"], "start_item_id": one["item_id"], "items": [one],
                                                   "cues": [], "sequences": [], "recovery_points": []})
    before = rig.snapshot()
    r = await refusal(comp.compose(rig.pid, body(rig.root_id, narrative=other)))
    assert codes(r) == [K.NARRATIVE_UNMAPPED_ITEMS.value] and r.conflicts[0]["details"]["item_ids"]["total"] >= 1
    assert "keep_motion" in r.conflicts[0]["fix"] and rig.snapshot() == before
    answer = await comp.compose(rig.pid, body(rig.root_id, narrative=other, on_unmapped="keep_motion"))
    items = stored_score(rig, answer["variant"]["variant_id"])["items"]
    assert [i.get("text") for i in items if i["item_id"] == I1] == ["Seule phrase."], "matched by scene and rank"
    assert [i for i in items if i["item_id"] == I2][0]["note"] == "Explain", "the unmatched item keeps its own narration"
    detail = {d["dimension"]: d for d in (await comp.provenance(rig.pid, answer["variant"]["variant_id"]))["composition"]["dimensions"]}["narrative"]["detail"]
    assert detail["matched"] == {"item_id": 0, "scene_ordinal": 1} and detail["kept_from_motion_total"] == 2 and detail["dropped_source_items"] == 0


async def test_a_narration_the_motion_item_cannot_speak_is_a_named_conflict(tmp_path):
    rig, comp = await build(tmp_path, art=False)
    other = await branch(rig, "Silencieuse")
    doc = (await rig.studio.get_score(rig.pid, other))["score"]
    items = [dict(i) for i in doc["items"]]
    items[0] = {"item_id": I1, "scene_id": S1, "presenter": "none", "kind": "silence", "next_item_id": I2}
    await rig.studio.save_score(rig.pid, other, {"expected_revision": doc["revision"], "start_item_id": I1, "items": items, "cues": doc["cues"],
                                                   "sequences": [], "recovery_points": []})
    r = await refusal(comp.compose(rig.pid, body(rig.root_id, narrative=other)))
    assert codes(r) == [K.NARRATIVE_ITEM_INCOMPATIBLE.value] and r.conflicts[0]["details"]["item_ids"]["items"] == [I1]


async def test_a_stale_source_revision_or_presentation_revision_is_a_stale_revision_error_not_a_conflict(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    await rig.variants.rename(rig.pid, beta, {"title": "Beta bis"})  # the variant moves on: revision 2
    before = rig.snapshot()
    with pytest.raises(PresentationStudioError) as caught:
        await comp.compose(rig.pid, body(rig.root_id, narrative=beta, source_revisions={beta: 1}))
    assert caught.value.code is C.STALE_REVISION and "reload" in caught.value.message
    with pytest.raises(PresentationStudioError) as caught:
        await comp.compose(rig.pid, body(rig.root_id, expected_revision=1))
    assert caught.value.code is C.STALE_REVISION
    with pytest.raises(PresentationStudioError) as caught:
        await comp.compose(rig.pid, body(rig.root_id, source_revisions={NO_VARIANT: 1}))
    assert caught.value.code is C.INVALID_PRESENTATION
    assert rig.snapshot() == before
    root = await rig.studio.get_variant(rig.pid, rig.root_id)
    revision = (await rig.variants.graph(rig.pid))["revision"]
    ok = await comp.compose(rig.pid, body(rig.root_id, narrative=beta, source_revisions={beta: 2, rig.root_id: root.revision},
                                          expected_revision=revision))
    assert ok["presentation_revision"] > revision


async def test_unknown_and_archived_sources_are_unknown_variant(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    await rig.archive(beta)
    for extra in ({"narrative": beta}, {"scenes": beta}, {"art_direction": NO_VARIANT}):
        with pytest.raises(PresentationStudioError) as caught:
            await comp.compose(rig.pid, body(rig.root_id, **extra))
        assert caught.value.code is C.UNKNOWN_VARIANT, extra
    with pytest.raises(PresentationStudioError) as caught:
        await comp.compose(rig.pid, body(beta))
    assert caught.value.code is C.UNKNOWN_VARIANT


def test_a_malformed_request_is_a_400_before_anything_is_read():
    base = "psv_" + "1" * 32
    bad = [{}, {"title": "x"}, {"base": base}, {"title": "x", "base": "nope"}, {"title": "x", "base": base, "number": 3},
           {"title": "x", "base": base, "narrative": "nope"}, {"title": "x", "base": base, "scenes": []},
           {"title": "x", "base": base, "scenes": [{"from": base, "scene_ids": []}]},
           {"title": "x", "base": base, "scenes": [{"from": base, "scene_ids": [S1, S1]}]},
           {"title": "x", "base": base, "scenes": [{"from": base}] * 5}, {"title": "x", "base": base, "on_unmapped": "guess"},
           {"title": "x", "base": base, "actor": "root"}, {"title": "x", "base": base, "activate": "yes"},
           {"title": "x", "base": base, "rationale": "a\nb"}, {"title": "x", "base": base, "rationale": "r" * 401},
           {"title": "x", "base": base, "source_revisions": {base: 0}}, {"title": "x", "base": base, "selected": base}]
    for raw in bad:
        with pytest.raises(PresentationStudioError) as caught:
            parse_composition(raw)
        assert caught.value.code in (C.INVALID_PRESENTATION, C.RUNTIME_STATE_REFUSED), raw
    request = parse_composition({"title": "x", "base": base, "scenes": base})
    assert [s.variant_id for s in request.segments()] == [base] and request.sources() == (base,)


# ------------------------------------------------------------------ provenance, restart, crash

async def test_the_provenance_survives_a_restart_and_a_variant_that_is_not_composed_has_none(tmp_path):
    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    answer = await comp.compose(rig.pid, body(rig.root_id, narrative=beta))
    new = answer["variant"]["variant_id"]
    first = await comp.provenance(rig.pid, new)
    rig.wire()
    again = PresentationStudioComposition(rig.studio, rig.variants)
    assert await again.provenance(rig.pid, new) == first
    parsed = parse_provenance(first["composition"])
    assert parsed.sources() == (rig.root_id, beta) and parsed.to_document() == first["composition"]
    with pytest.raises(PresentationStudioError) as caught:
        await again.provenance(rig.pid, beta)
    assert caught.value.code is C.UNKNOWN_COMPOSITION and caught.value.status == 404
    with pytest.raises(PresentationStudioError) as caught:
        await again.provenance(rig.pid, "nope")
    assert caught.value.code is C.UNKNOWN_VARIANT


async def test_archiving_a_composed_variant_keeps_its_provenance_and_restoring_it_reads_it_again(tmp_path):
    rig, comp = await build(tmp_path)
    new = (await comp.compose(rig.pid, body(rig.root_id)))["variant"]["variant_id"]
    await rig.archive(new)
    assert (await comp.provenance(rig.pid, new))["composition"]["variant_id"] == new
    await rig.variants.restore(rig.pid, new)
    assert (await comp.provenance(rig.pid, new))["composition"]["variant_id"] == new


async def test_a_corrupt_provenance_is_a_data_fault_not_a_silent_empty_answer(tmp_path):
    rig, comp = await build(tmp_path)
    new = (await comp.compose(rig.pid, body(rig.root_id)))["variant"]["variant_id"]
    path = rig.folder / "compositions" / f"{new}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["dimensions"] = document["dimensions"][:3]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PresentationStudioError) as caught:
        await comp.provenance(rig.pid, new)
    assert caught.value.code is C.CORRUPT_DOCUMENT


@pytest.mark.parametrize("stop", ["allocated", "linked:score", "linked:art_direction", "composition_written", "variant_written"])
async def test_a_hard_stop_at_any_step_leaves_the_sources_untouched_and_no_node(tmp_path, stop):
    class Boom(BaseException):
        pass

    armed = []

    def checkpoint(step):
        if armed and step == stop:
            raise Boom

    rig = Rig(tmp_path, checkpoint=checkpoint)
    await rig.open(score=True)
    comp = PresentationStudioComposition(rig.studio, rig.variants)
    root = await rig.studio.get_variant(rig.pid, rig.root_id)
    await rig.studio.create_art_direction(rig.pid, rig.root_id, {"expected_variant_revision": root.revision, "profile": fx.base_dict()})
    beta = await branch(rig, "Beta")
    before = rig.snapshot()
    armed.append(True)
    with pytest.raises(Boom):
        await comp.compose(rig.pid, body(rig.root_id, narrative=beta, art_direction=beta))
    created = untouched(before, rig.snapshot(), allowed=("presentation.json",))
    manifest = json.loads((rig.folder / "presentation.json").read_text(encoding="utf-8"))
    assert len(manifest["variants"]) == 2, "the manifest is written last: the interrupted composition never became a node"
    assert all(name.split("/")[0] in ("variants", "scores", "art_directions", "compositions") for name in created)
    armed.clear()
    rig.wire()
    again = PresentationStudioComposition(rig.studio, rig.variants)
    report = await rig.variants.reconcile(rig.pid)
    retry = await again.compose(rig.pid, body(rig.root_id, narrative=beta, art_direction=beta))
    assert retry["node"]["variant_number"] == 4 and (await again.provenance(rig.pid, retry["variant"]["variant_id"]))["composition"]
    assert report is not None


async def test_two_compositions_at_once_get_distinct_numbers_and_neither_touches_a_source(tmp_path):
    import asyncio

    rig, comp = await build(tmp_path)
    beta = await branch(rig, "Beta")
    before = rig.snapshot()
    one, two = await asyncio.gather(comp.compose(rig.pid, body(rig.root_id, title="Un", narrative=beta)),
                                    comp.compose(rig.pid, body(rig.root_id, title="Deux", art_direction=beta)))
    assert {one["node"]["variant_number"], two["node"]["variant_number"]} == {3, 4}
    untouched(before, rig.snapshot())
