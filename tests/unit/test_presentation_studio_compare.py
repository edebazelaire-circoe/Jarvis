"""Comparaison de variantes : ensemble 2 / 4, paire en focus 50/50, scene logique synchronisee, structures divergentes, liens
manuels, navigation independante (jarvis-interactive-presentation-studio, Slice 19).

Vrai magasin et vraie API de branche sous `tmp_path`. L'etat de comparaison est de l'etat d'interface : il ne s'ecrit nulle part
(aucun fichier ne change) et il se perd avec le processus. Contrat : `docs/presentation-studio.md` > *Comparison and semantic
composition contract*.
"""

from __future__ import annotations

import pytest

from jarvis.core import presentation_studio_compare as compare_module
from jarvis.core.presentation_studio_compare import PresentationStudioCompare
from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from jarvis.domain.presentation_studio_compare import parse_body, parse_select
from tests.unit.test_presentation_studio_score_service import S1, S2, scene_body
from tests.unit.test_presentation_studio_variants_service import Rig

S9 = "pss_0000000000a9"
NO_VARIANT = "psv_" + "0" * 32


async def edit_scenes(rig, variant_id, scene_ids):
    variant = await rig.studio.get_variant(rig.pid, variant_id)
    await rig.studio.save_variant(rig.pid, variant_id, {
        "expected_revision": variant.revision, "title": variant.title, "scenes": [scene_body(s) for s in scene_ids],
        "art_direction_id": None, "score_id": None})


async def world(tmp_path):
    """r (S1, S2) | b = copy of r | c = r reordered (S2, S1) | d = divergent (S1, S9, no S2)."""

    rig = await Rig(tmp_path).open()
    ids = {"r": rig.root_id}
    for name in "bcd":
        ids[name] = (await rig.branch(name.upper()))["variant"]["variant_id"]
    await edit_scenes(rig, ids["c"], [S2, S1])
    await edit_scenes(rig, ids["d"], [S1, S9])
    return rig, PresentationStudioCompare(rig.studio), ids


def ref(variant_id, scene_id):
    return {"variant_id": variant_id, "scene_id": scene_id}


def rows(view, variant_id):
    return {s["scene_id"]: s for s in next(v for v in view["variants"] if v["variant_id"] == variant_id)["scenes"]}


async def refused(awaitable, code):
    with pytest.raises(PresentationStudioError) as caught:
        await awaitable
    assert caught.value.code is code, caught.value
    return caught.value


# ------------------------------------------------------------------ 2 / 4 and the focused pair

async def test_nothing_is_selected_until_a_comparison_is_opened(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    view = await cmp.view(rig.pid)
    assert view["active"] is False and view["revision"] == 0 and view["layout"] == "empty" and view["variants"] == []


async def test_two_variants_are_compared_two_up_with_their_structure_and_equivalences(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    view = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"]]})
    assert view["active"] and view["layout"] == "two_up" and view["shown"] == [ids["r"], ids["b"]] and view["pair"] is None
    assert view["mode"] == "sync" and view["revision"] == 1 and view["anchors"] == {ids["r"]: S1, ids["b"]: S1}
    assert [v["variant_number"] for v in view["variants"]] == [1, 2] and view["variants"][0]["active"] is True
    assert rows(view, ids["r"])[S2]["equivalents"] == {ids["b"]: S2} and rows(view, ids["r"])[S2]["mapping"] == "identity"
    assert view["structure"]["relation"] == "identical" and view["unmapped"] == {ids["r"]: [], ids["b"]: []}
    assert rows(view, ids["r"])[S1]["prefab"] == {"id": "lab.counter", "version": 1}
    assert await cmp.view(rig.pid) == view


async def test_four_variants_are_compared_four_up(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    view = await cmp.select(rig.pid, {"variant_ids": list(ids.values())})
    assert view["layout"] == "four_up" and view["shown"] == list(ids.values()) and len(view["variants"]) == 4
    assert rows(view, ids["r"])[S1]["equivalents"] == {ids["b"]: S1, ids["c"]: S1, ids["d"]: S1}


async def test_three_one_none_or_a_variant_twice_is_refused(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    for chosen in ([ids["r"]], [ids["r"], ids["b"], ids["c"]], [], [ids["r"], ids["r"]], list(ids.values()) + [ids["r"]]):
        await refused(cmp.select(rig.pid, {"variant_ids": chosen}), C.INVALID_PRESENTATION)
    assert (await cmp.view(rig.pid))["active"] is False


async def test_an_unknown_or_archived_variant_cannot_be_compared(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await refused(cmp.select(rig.pid, {"variant_ids": [ids["r"], NO_VARIANT]}), C.UNKNOWN_VARIANT)
    await rig.archive(ids["d"])
    error = await refused(cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]}), C.UNKNOWN_VARIANT)
    assert "restored" in error.message
    await refused(cmp.select("pst_" + "0" * 32, {"variant_ids": [ids["r"], ids["b"]]}), C.UNKNOWN_PRESENTATION)
    await refused(cmp.select("nope", {"variant_ids": [ids["r"], ids["b"]]}), C.UNKNOWN_PRESENTATION)


async def test_a_pair_is_focused_at_50_50_and_released(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": list(ids.values())})
    view = await cmp.set_pair(rig.pid, {"pair": [ids["c"], ids["b"]]})
    assert view["layout"] == "focus" and view["pair"] == [ids["c"], ids["b"]] and view["shown"] == [ids["c"], ids["b"]]
    assert view["variant_ids"] == list(ids.values()), "the other two stay in the set"
    view = await cmp.set_pair(rig.pid, {"pair": None})
    assert view["layout"] == "four_up" and view["pair"] is None and view["shown"] == list(ids.values())
    for pair in ([ids["r"]], [ids["r"], ids["r"]], [ids["r"], NO_VARIANT], "rb"):
        await refused(cmp.set_pair(rig.pid, {"pair": pair}), C.INVALID_PRESENTATION)
    picked = await cmp.select(rig.pid, {"variant_ids": list(ids.values()), "pair": [ids["r"], ids["d"]], "mode": "independent"})
    assert picked["layout"] == "focus" and picked["mode"] == "independent"
    await refused(cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"]], "pair": [ids["r"], ids["c"]]}), C.INVALID_PRESENTATION)


async def test_pair_mode_navigate_and_links_need_an_open_comparison(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await refused(cmp.set_pair(rig.pid, {"pair": None}), C.INVALID_PRESENTATION)
    await refused(cmp.set_mode(rig.pid, {"mode": "sync"}), C.INVALID_PRESENTATION)
    await refused(cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "next"}), C.INVALID_PRESENTATION)
    await refused(cmp.link(rig.pid, {"a": ref(ids["r"], S1), "b": ref(ids["b"], S1)}), C.INVALID_PRESENTATION)


# ------------------------------------------------------------------ synchronized logical scenes

async def test_navigating_one_variant_moves_the_equivalent_scene_of_the_others_even_when_the_order_differs(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"], ids["c"]][:2] + [ids["c"], ids["d"]]})
    view = await cmp.navigate(rig.pid, {"variant_id": ids["r"], "scene_id": S2})
    assert view["navigation"]["origin"] == ref(ids["r"], S2)
    assert view["navigation"]["results"] == {
        ids["r"]: {"scene_id": S2, "status": "origin"}, ids["b"]: {"scene_id": S2, "status": "synced"},
        ids["c"]: {"scene_id": S2, "status": "synced"}, ids["d"]: {"scene_id": S1, "status": "unmapped"}}
    assert view["anchors"] == {ids["r"]: S2, ids["b"]: S2, ids["c"]: S2, ids["d"]: S1}, "the divergent variant did not move"
    view = await cmp.navigate(rig.pid, {"variant_id": ids["c"], "step": "next"})  # c is (S2, S1): next of S2 is S1
    assert view["navigation"]["origin"] == ref(ids["c"], S1) and view["anchors"][ids["r"]] == S1 and view["anchors"][ids["d"]] == S1
    view = await cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "last"})
    assert view["anchors"][ids["r"]] == S2 and (await cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "next"}))["anchors"][ids["r"]] == S2
    assert (await cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "first"}))["anchors"][ids["r"]] == S1
    assert (await cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "previous"}))["anchors"][ids["r"]] == S1


async def test_the_structure_says_identical_reordered_or_divergent_per_pair_and_overall(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    reordered = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["c"]]})
    assert reordered["structure"]["relation"] == "reordered" and reordered["structure"]["pairs"][0]["order_preserved"] is False
    divergent = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"], ids["c"], ids["d"]]})
    relations = {(p["a"], p["b"]): p["relation"] for p in divergent["structure"]["pairs"]}
    assert divergent["structure"]["relation"] == "divergent" and relations[(ids["r"], ids["b"])] == "identical"
    assert relations[(ids["r"], ids["c"])] == "reordered" and relations[(ids["r"], ids["d"])] == "divergent"
    pair = next(p for p in divergent["structure"]["pairs"] if p["b"] == ids["d"] and p["a"] == ids["r"])
    assert (pair["shared"], pair["only_a"], pair["only_b"]) == (1, 1, 1)


async def test_a_scene_without_an_equivalent_is_unmapped_and_offers_same_prefab_suggestions(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    view = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]})
    only_in_d = rows(view, ids["d"])[S9]
    assert only_in_d["mapping"] == "none" and only_in_d["equivalents"] == {}
    assert only_in_d["suggestions"] == [ref(ids["r"], S2)] and view["unmapped"] == {ids["r"]: [S2], ids["d"]: [S9]}
    assert rows(view, ids["r"])[S2]["suggestions"] == [ref(ids["d"], S9)]


async def test_independent_navigation_moves_only_the_variant_asked(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]})
    assert (await cmp.set_mode(rig.pid, {"mode": "independent"}))["mode"] == "independent"
    view = await cmp.navigate(rig.pid, {"variant_id": ids["r"], "scene_id": S2})
    assert view["navigation"]["results"][ids["d"]] == {"scene_id": S1, "status": "held"} and view["anchors"][ids["d"]] == S1
    view = await cmp.navigate(rig.pid, {"variant_id": ids["d"], "scene_id": S9})
    assert view["anchors"] == {ids["r"]: S2, ids["d"]: S9}
    await refused(cmp.navigate(rig.pid, {"variant_id": ids["d"], "scene_id": S2}), C.UNKNOWN_SCENE)
    await refused(cmp.navigate(rig.pid, {"variant_id": ids["b"], "scene_id": S2}), C.INVALID_PRESENTATION)
    assert (await cmp.set_mode(rig.pid, {"mode": "sync"}))["mode"] == "sync"


# ------------------------------------------------------------------ manual mapping

async def test_a_manual_link_maps_scenes_whose_ids_differ_and_is_transitive_through_identity(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"], ids["c"], ids["d"]]})
    view = await cmp.link(rig.pid, {"a": ref(ids["d"], S9), "b": ref(ids["r"], S2)})
    assert len(view["links"]) == 1 and view["links"][0]["stale"] is False
    assert {(l["variant_id"], l["scene_id"]) for l in (view["links"][0]["a"], view["links"][0]["b"])} == {(ids["d"], S9), (ids["r"], S2)}
    assert rows(view, ids["d"])[S9]["mapping"] == "manual"
    assert rows(view, ids["d"])[S9]["equivalents"] == {ids["r"]: S2, ids["b"]: S2, ids["c"]: S2}
    moved = await cmp.navigate(rig.pid, {"variant_id": ids["d"], "scene_id": S9})
    assert moved["navigation"]["results"][ids["b"]] == {"scene_id": S2, "status": "synced"}
    pair = next(p for p in moved["structure"]["pairs"] if {p["a"], p["b"]} == {ids["r"], ids["d"]})
    assert pair["relation"] == "identical" and pair["shared"] == 2, "once S9 is linked to S2 the two structures line up"
    assert moved["structure"]["relation"] == "reordered", "the reordered variant remains"
    again = await cmp.link(rig.pid, {"a": ref(ids["r"], S2), "b": ref(ids["d"], S9)})
    assert len(again["links"]) == 1 and again["revision"] == moved["revision"], "the same link twice changes nothing"
    removed = await cmp.unlink(rig.pid, {"a": ref(ids["r"], S2), "b": ref(ids["d"], S9)})
    assert removed["links"] == [] and rows(removed, ids["d"])[S9]["mapping"] == "none"
    await refused(cmp.unlink(rig.pid, {"a": ref(ids["r"], S2), "b": ref(ids["d"], S9)}), C.UNKNOWN_SCENE)


async def test_a_link_that_would_put_two_scenes_of_one_variant_in_one_logical_scene_is_refused(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]})
    error = await refused(cmp.link(rig.pid, {"a": ref(ids["d"], S9), "b": ref(ids["r"], S1)}), C.COMPARE_MAPPING_CONFLICT)
    assert error.status == 409 and "same logical scene" in error.message
    await cmp.link(rig.pid, {"a": ref(ids["d"], S9), "b": ref(ids["r"], S2)})
    await refused(cmp.link(rig.pid, {"a": ref(ids["d"], S1), "b": ref(ids["r"], S2)}), C.COMPARE_MAPPING_CONFLICT)
    assert len((await cmp.view(rig.pid))["links"]) == 1


async def test_a_link_must_name_two_compared_variants_and_real_scenes(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]})
    await refused(cmp.link(rig.pid, {"a": ref(ids["r"], S1), "b": ref(ids["r"], S2)}), C.INVALID_PRESENTATION)
    await refused(cmp.link(rig.pid, {"a": ref(ids["r"], S1), "b": ref(ids["b"], S1)}), C.INVALID_PRESENTATION)
    await refused(cmp.link(rig.pid, {"a": ref(ids["d"], S2), "b": ref(ids["r"], S1)}), C.UNKNOWN_SCENE)
    await refused(cmp.link(rig.pid, {"a": {"variant_id": ids["d"]}, "b": ref(ids["r"], S1)}), C.INVALID_PRESENTATION)


async def test_a_link_survives_a_new_selection_that_keeps_both_ends_and_is_dropped_when_it_does_not(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]})
    await cmp.link(rig.pid, {"a": ref(ids["d"], S9), "b": ref(ids["r"], S2)})
    kept = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"], ids["c"], ids["d"]]})
    assert len(kept["links"]) == 1
    dropped = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"]]})
    assert dropped["links"] == []


async def test_a_link_to_a_scene_that_was_since_removed_is_reported_stale_and_not_applied(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["d"]]})
    await cmp.link(rig.pid, {"a": ref(ids["d"], S9), "b": ref(ids["r"], S2)})
    await edit_scenes(rig, ids["d"], [S1])
    view = await cmp.view(rig.pid)
    assert len(view["links"]) == 1 and view["links"][0]["stale"] is True  # (a, b) is canonical order, not the order of the request
    assert {l["scene_id"] for l in (view["links"][0]["a"], view["links"][0]["b"])} == {S9, S2}
    assert rows(view, ids["r"])[S2]["mapping"] == "none"


# ------------------------------------------------------------------ state: revision, volatility, no write

async def test_the_expected_revision_guards_every_operation(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    first = await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"]], "expected_revision": 0})
    await cmp.set_mode(rig.pid, {"mode": "independent", "expected_revision": first["revision"]})
    for call in (cmp.set_mode(rig.pid, {"mode": "sync", "expected_revision": first["revision"]}),
                 cmp.set_pair(rig.pid, {"pair": None, "expected_revision": 0}),
                 cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "next", "expected_revision": 1}),
                 cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["c"]], "expected_revision": 0}),
                 cmp.clear(rig.pid, {"expected_revision": 1})):
        error = await refused(call, C.STALE_REVISION)
        assert "reload" in error.message
    assert (await cmp.view(rig.pid))["mode"] == "independent"


async def test_comparing_writes_nothing_and_the_comparison_dies_with_the_process(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    before = rig.snapshot()
    await cmp.select(rig.pid, {"variant_ids": list(ids.values())})
    await cmp.set_pair(rig.pid, {"pair": [ids["r"], ids["b"]]})
    await cmp.set_mode(rig.pid, {"mode": "independent"})
    await cmp.navigate(rig.pid, {"variant_id": ids["r"], "scene_id": S2})
    await cmp.link(rig.pid, {"a": ref(ids["d"], S9), "b": ref(ids["r"], S2)})
    assert rig.snapshot() == before, "not a file changed: the comparison is interface state"
    restarted = PresentationStudioCompare(rig.studio)
    assert (await restarted.view(rig.pid))["active"] is False
    cleared = await cmp.clear(rig.pid)
    assert cleared["cleared"] is True and (await cmp.view(rig.pid))["active"] is False
    assert (await cmp.clear(rig.pid))["cleared"] is False and rig.snapshot() == before


async def test_a_variant_archived_after_the_selection_is_a_visible_problem_and_blocks_navigation(tmp_path):
    rig, cmp, ids = await world(tmp_path)
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"]]})
    await rig.archive(ids["b"])
    view = await cmp.view(rig.pid)
    assert view["problems"] == [{"variant_id": ids["b"], "code": "variant_unavailable"}] and [v["variant_id"] for v in view["variants"]] == [ids["r"]]
    await refused(cmp.navigate(rig.pid, {"variant_id": ids["r"], "step": "next"}), C.UNKNOWN_VARIANT)
    assert (await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["c"]]}))["problems"] == []


async def test_only_the_most_recent_presentations_keep_a_comparison(tmp_path, monkeypatch):
    rig, cmp, ids = await world(tmp_path)
    monkeypatch.setattr(compare_module, "MAX_TRACKED", 1)
    other = (await rig.studio.create({"title": "Autre"})).presentation.presentation_id
    other_root = (await rig.studio.get(other)).presentation.active_variant_id
    other_branch = (await rig.variants.create_branch(other, {"title": "B"}))["variant"]["variant_id"]
    await cmp.select(rig.pid, {"variant_ids": [ids["r"], ids["b"]]})
    await cmp.select(other, {"variant_ids": [other_root, other_branch]})
    assert (await cmp.view(rig.pid))["active"] is False and (await cmp.view(other))["active"] is True


def test_malformed_bodies_are_refused_before_anything_is_read():
    a, b = "psv_" + "1" * 32, "psv_" + "2" * 32
    bad_select = [{}, {"variant_ids": [a]}, {"variant_ids": "ab"}, {"variant_ids": [a, b], "layout": "grid"}, {"variant_ids": [a, b], "mode": "both"},
                  {"variant_ids": [a, b], "pair": [a]}, {"variant_ids": [a, b], "expected_revision": -1},
                  {"variant_ids": [a, b], "selected": a}, {"variant_ids": [a, "nope"]}]
    for raw in bad_select:
        with pytest.raises(PresentationStudioError):
            parse_select(raw)
    for kind, raw in (("pair", {}), ("mode", {"mode": "x"}), ("navigate", {"variant_id": a}), ("navigate", {"variant_id": a, "step": "next", "scene_id": "pss_" + "1" * 12}),
                      ("navigate", {"variant_id": a, "step": "up"}), ("link", {"a": 1, "b": 2}), ("clear", {"x": 1})):
        with pytest.raises(PresentationStudioError):
            parse_body(raw, kind)
    assert parse_select({"variant_ids": [a, b]})["variant_ids"] == (a, b)
