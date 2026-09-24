"""`SceneSelection` du domaine (handoff jarvis-mcp-semantic-batch-inspector, Slice 02).

Contrat : `docs/scene-selection-batch.md` §1 et §3 (résolution, indépendante de
l'opération). Prouve : décodage strict et erreurs de validation (§1.5), modes
exclusifs, pluriels, chaque filtre, composition ET/OU, `exclude` en dernier,
ordre canonique (§1.3), borne unique (§1.4), refus des références et des ids
explicites (tous listés, ordre canonique), ids archivés rangés à part, écarts
des membres de filtre non placés, décompte des masqués.
"""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.domain.scene import (
    DEFAULT_LAYERS,
    MAX_SCENE_OBJECTS,
    ExecState,
    PlacedBy,
    RelationKind,
    SceneActor,
    SceneConstraints,
    SceneGeometry,
    SceneObject,
    SceneObjectKind,
    ScenePayload,
    SceneRefusal,
    SceneRelation,
    SceneSnapshot,
    Visibility,
    WorkRef,
)
from jarvis.domain.scene_selection import (
    MAX_SELECTION_IDS,
    ConstellationScope,
    NearScope,
    SceneSelection,
    SelectionMode,
    SelectionRefusal,
    SelectionResolution,
    SelectionSkip,
    constellation_of,
    resolve_selection,
)


def _obj(object_id: str, kind: str, *, origin: str = "runtime", exec_state: str = "unknown", geometry=None,
         visibility: str = "visible", work=None, category: str | None = None, title: str = "",
         annotation: str = "") -> SceneObject:
    return SceneObject(
        object_id=object_id, kind=SceneObjectKind(kind), category=category or kind,
        constraints=SceneConstraints(placed_by=PlacedBy(origin)), origin=SceneActor(origin),
        exec_state=ExecState(exec_state), geometry=None if geometry is None else SceneGeometry(*geometry),
        layer=DEFAULT_LAYERS[SceneObjectKind(kind)], visibility=Visibility(visibility),
        work_ref=None if work is None else WorkRef(*work), payload=ScenePayload(title=title, annotation=annotation),
    )


def _rel(relation_id: str, kind: str, a: str, b: str) -> SceneRelation:
    return SceneRelation(relation_id=relation_id, kind=RelationKind(kind), from_id=a, to_id=b)


SCENE = SceneSnapshot(
    scene_id="scene",
    revision=9,
    objects=(
        _obj("claude:a", "agent", exec_state="running", geometry=(0, 0, 10, 10), work=("claude", "a", "w-a"),
             title="Sous-agent A"),
        _obj("claude:b", "agent", exec_state="completed", work=("claude", "b")),
        _obj("job:c", "job", exec_state="failed", geometry=(100, 0, 10, 10), visibility="hidden", work=("job", "c")),
        _obj("art-1", "artifact", origin="brain", geometry=(15, 0, 5, 5), category="Report", title="Rapport final"),
        _obj("art-2", "artifact", origin="user", geometry=(12, 0, 2, 2), category="notes", visibility="hidden",
             annotation="À relire"),
        _obj("attention!claude:a", "attention", exec_state="failed", work=("claude", "a")),
        _obj("grp", "group", origin="user", geometry=(-50, -50, 10, 10)),
        _obj("win", "window", origin="brain", geometry=(0, 20, 10, 10), title="Notes"),
        _obj("win-2", "window", origin="brain", geometry=(20, 0, 10, 10)),
    ),
    relations=(
        _rel("r-e1", "explains", "art-1", "claude:a"),
        _rel("r-e2", "explains", "art-2", "claude:a"),
        _rel("attention!claude:a", "explains", "attention!claude:a", "claude:a"),
        _rel("r-g1", "groups", "grp", "art-1"),
        _rel("r-g2", "groups", "grp", "job:c"),
        _rel("r-p", "parent_of", "claude:a", "claude:b"),
    ),
    archived_ids=("old", "older"),
)
SNAPSHOT_ORDER = [item.object_id for item in SCENE.objects]


def sel(**wire: Any) -> SceneSelection:
    return SceneSelection.from_payload(wire)


def matched(**wire: Any) -> list[str]:
    resolution = resolve_selection(SCENE, sel(**wire))
    assert resolution.refused == ()
    return list(resolution.matched_ids)


# ------------------------------------------------------------------ décodage


def test_wire_examples_of_the_contract_decode_and_round_trip():
    one = sel(constellation={"object_id": "codex:42"}, kinds=["artifact", "attention"])
    assert one.mode is SelectionMode.FILTER
    assert one.constellation == ConstellationScope("codex:42") and one.kinds == (SceneObjectKind.ARTIFACT, SceneObjectKind.ATTENTION)
    two = sel(ids=["brain-artifact-1a2b", "codex:42"])
    assert two.mode is SelectionMode.EXPLICIT and two.ids == ("brain-artifact-1a2b", "codex:42")
    full = sel(kinds=["job"], category="Report", origin="brain", visibility="hidden", exec_states=["failed", "completed"],
               text="rapport", work="claude:a", explains="claude:a", constellation={"object_id": "claude:a", "depth": 2},
               group="grp", near={"object_id": "claude:a", "radius": 5}, include_hidden=True, exclude=["win"])
    for selection in (one, two, full):
        assert SceneSelection.from_payload(selection.to_payload()) == selection
    assert full.to_payload()["near"] == {"object_id": "claude:a", "radius": 5.0}


def test_singular_kind_and_exec_state_are_sugar_for_a_one_element_list():
    assert sel(kind="job") == sel(kinds=["job"])
    assert sel(exec_state="failed") == sel(exec_states=["failed"])
    # Forme canonique : le pluriel.
    assert sel(kind="job").to_payload() == {"kinds": ["job"]}
    assert matched(kind="agent") == matched(kinds=["agent"]) == ["claude:a", "claude:b"]


@pytest.mark.parametrize("wire", [
    pytest.param({}, id="neither mode"),
    pytest.param({"exclude": ["win"]}, id="exclude alone is not a filter"),
    pytest.param({"ids": ["a"], "kinds": ["job"]}, id="both modes"),
    pytest.param({"ids": ["a"], "exclude": ["b"]}, id="exclude in explicit mode"),
    pytest.param({"connected": {"object_id": "a"}}, id="old key connected has no alias"),
    pytest.param({"kinds": ["job"], "all": True}, id="unknown key"),
    pytest.param({"ids": []}, id="empty ids"),
    pytest.param({"ids": ["a", "a"]}, id="duplicate ids"),
    pytest.param({"ids": "a"}, id="ids not a list"),
    pytest.param({"ids": [" a"]}, id="id with surrounding space"),
    pytest.param({"ids": ["x" * 129]}, id="id too long"),
    pytest.param({"ids": [f"o{i}" for i in range(MAX_SELECTION_IDS + 1)]}, id="ids over the single bound"),
    pytest.param({"kind": "job", "kinds": ["job"]}, id="kind with kinds"),
    pytest.param({"exec_state": "failed", "exec_states": ["failed"]}, id="exec_state with exec_states"),
    pytest.param({"kinds": []}, id="empty kinds"),
    pytest.param({"kinds": ["job", "job"]}, id="duplicate kinds"),
    pytest.param({"kinds": ["star"]}, id="unknown kind"),
    pytest.param({"kind": "star"}, id="unknown singular kind"),
    pytest.param({"exec_states": ["done"]}, id="unknown exec_state"),
    pytest.param({"exec_states": ["failed"] * 9}, id="exec_states over bound"),
    pytest.param({"origin": "resolver"}, id="origin not an actor"),
    pytest.param({"visibility": "shown"}, id="unknown visibility"),
    pytest.param({"category": ""}, id="empty category"),
    pytest.param({"category": "a b"}, id="category not a token"),
    pytest.param({"category": "c" * 33}, id="category too long"),
    pytest.param({"text": ""}, id="empty text"),
    pytest.param({"text": "t" * 161}, id="text too long"),
    pytest.param({"work": ""}, id="empty work"),
    pytest.param({"work": "w" * 161}, id="work too long"),
    pytest.param({"explains": ""}, id="empty explains"),
    pytest.param({"group": 3}, id="group not a string"),
    pytest.param({"constellation": {"object_id": "a", "depth": 0}}, id="depth 0"),
    pytest.param({"constellation": {"object_id": "a", "depth": 7}}, id="depth 7"),
    pytest.param({"constellation": {"object_id": "a", "depth": True}}, id="depth bool"),
    pytest.param({"constellation": {"object_id": "a", "depth": 2.0}}, id="depth float"),
    pytest.param({"constellation": {"object_id": "a", "hops": 2}}, id="constellation unknown key"),
    pytest.param({"constellation": "a"}, id="constellation not an object"),
    pytest.param({"near": {"object_id": "a"}}, id="near without radius"),
    pytest.param({"near": {"object_id": "a", "radius": float("nan")}}, id="radius nan"),
    pytest.param({"near": {"object_id": "a", "radius": float("inf")}}, id="radius inf"),
    pytest.param({"near": {"object_id": "a", "radius": -1}}, id="radius negative"),
    pytest.param({"near": {"object_id": "a", "radius": 100_001}}, id="radius over bound"),
    pytest.param({"near": {"object_id": "a", "radius": True}}, id="radius bool"),
    pytest.param({"near": {"object_id": "a", "radius": 10**400}}, id="radius huge int"),
    pytest.param({"kinds": ["job"], "include_hidden": True}, id="include_hidden without near"),
    pytest.param({"kinds": ["job"], "include_hidden": False}, id="include_hidden false without near"),
    pytest.param({"near": {"object_id": "a", "radius": 1}, "include_hidden": 1}, id="include_hidden not strict bool"),
    pytest.param({"kinds": ["job"], "exclude": []}, id="empty exclude"),
    pytest.param({"kinds": ["job"], "exclude": ["a", "a"]}, id="duplicate exclude"),
    pytest.param({"kinds": ["job"], "exclude": [f"o{i}" for i in range(33)]}, id="exclude over 32"),
])
def test_invalid_selections_are_refused_at_decode(wire):
    with pytest.raises((TypeError, ValueError)):
        SceneSelection.from_payload(wire)


def test_decode_never_reads_the_scene_references_are_checked_at_resolution():
    # Références inexistantes : bien formées, donc décodées.
    selection = sel(constellation={"object_id": "nowhere"}, exclude=["nobody"])
    assert selection.constellation.object_id == "nowhere"


def test_the_single_bound_accepts_exactly_512_ids():
    assert MAX_SELECTION_IDS == MAX_SCENE_OBJECTS == 512
    assert len(sel(ids=[f"o{i}" for i in range(512)]).ids) == 512
    with pytest.raises(ValueError, match="at most 512"):
        sel(ids=[f"o{i}" for i in range(513)])


def test_direct_construction_validates_like_the_wire():
    with pytest.raises(ValueError):
        SceneSelection()
    with pytest.raises(ValueError):
        SceneSelection(ids=("a",), kinds=(SceneObjectKind.JOB,))
    with pytest.raises(ValueError):
        SceneSelection(kinds=(SceneObjectKind.JOB,), include_hidden=True)
    with pytest.raises(TypeError):
        SceneSelection(near={"object_id": "a", "radius": 1})  # type: ignore[arg-type]
    assert SceneSelection(near=NearScope("claude:a", 3), include_hidden=True).include_hidden is True


# ------------------------------------------------------------------ filtres


def test_each_filter_matches_its_contracted_rule():
    assert matched(kinds=["artifact", "window"]) == ["art-1", "art-2", "win", "win-2"]  # OU dans la liste
    assert matched(category="report") == ["art-1"]  # égalité sans casse
    assert matched(category="REPORT") == ["art-1"]
    assert matched(origin="user") == ["art-2", "grp"]
    assert matched(visibility="hidden") == ["job:c", "art-2"]
    assert matched(exec_states=["failed", "completed"]) == ["claude:b", "job:c", "attention!claude:a"]
    # text : titre, id ou annotation, sans casse, sous-chaîne.
    assert matched(text="RAPPORT") == ["art-1"]
    assert matched(text="claude:") == ["claude:a", "claude:b", "attention!claude:a"]
    assert matched(text="à relire") == ["art-2"]
    # work : source, external_id, work_id ou source:external_id, à l'identique.
    assert matched(work="claude") == ["claude:a", "claude:b", "attention!claude:a"]
    assert matched(work="w-a") == ["claude:a"]
    assert matched(work="claude:a") == ["claude:a", "attention!claude:a"]
    assert matched(work="c") == ["job:c"]
    assert matched(work="clau") == []
    # explains : ce qui explique la référence (sens du lien), signal compris.
    assert matched(explains="claude:a") == ["art-1", "art-2", "attention!claude:a"]
    assert matched(explains="art-1") == []
    # group : les membres, jamais le groupe lui-même.
    assert matched(group="grp") == ["job:c", "art-1"]
    assert "grp" not in matched(group="grp")


def test_filters_never_exclude_hidden_objects_except_near():
    assert "job:c" in matched(kinds=["job"])
    assert "art-2" in matched(constellation={"object_id": "claude:a"})
    assert "job:c" in matched(group="grp")


def test_constellation_scope_is_the_canonical_constellation():
    assert matched(constellation={"object_id": "claude:a"}) == list(constellation_of(SCENE, "claude:a"))
    assert matched(constellation={"object_id": "claude:b", "depth": 1}) == ["claude:b", "claude:a"]
    # Le groupe relie job:c (masqué) à la figure de claude:a.
    assert matched(constellation={"object_id": "claude:a"}) == [
        "claude:a", "art-1", "art-2", "attention!claude:a", "claude:b", "grp", "job:c"]


def test_near_orders_by_distance_and_follows_the_rendering_rule():
    # Référence exclue, non placés exclus, masqués exclus par défaut ; plus proche d'abord.
    assert matched(near={"object_id": "claude:a", "radius": 10}) == ["art-1", "win", "win-2"]
    assert matched(near={"object_id": "claude:a", "radius": 10}, include_hidden=True) == ["art-2", "art-1", "win", "win-2"]
    assert matched(near={"object_id": "claude:a", "radius": 1000}, visibility="hidden") == ["art-2", "job:c"]
    assert matched(near={"object_id": "claude:a", "radius": 0}) == []
    # Égalité de distance (win et win-2 à 10) : ordre de la scène.
    assert SNAPSHOT_ORDER.index("win") < SNAPSHOT_ORDER.index("win-2")


def test_near_ties_keep_snapshot_order_not_id_order():
    """Deux objets à même distance, rangés dans la scène à l'inverse de l'ordre de leurs ids."""

    scene = SceneSnapshot(scene_id="scene", objects=(
        _obj("ref", "window", origin="brain", geometry=(0, 0, 10, 10)),
        _obj("zz-tie", "window", origin="brain", geometry=(15, 0, 5, 5)),
        _obj("near-first", "window", origin="brain", geometry=(11, 0, 2, 2)),
        _obj("aa-tie", "window", origin="brain", geometry=(-10, 0, 5, 5)),
    ))
    resolution = resolve_selection(scene, sel(near={"object_id": "ref", "radius": 10}))
    # near-first à 1 ; zz-tie et aa-tie à 5 : zz-tie d'abord (scène), pas aa-tie (tri par id).
    assert resolution.matched_ids == ("near-first", "zz-tie", "aa-tie")
    assert sorted(["zz-tie", "aa-tie"]) == ["aa-tie", "zz-tie"]


# ------------------------------------------------------------------ composition et ordre


def test_fields_compose_with_and_lists_with_or():
    assert matched(kinds=["artifact", "agent"], origin="runtime") == ["claude:a", "claude:b"]
    assert matched(kinds=["artifact"], visibility="visible") == ["art-1"]
    assert matched(explains="claude:a", kinds=["artifact"], origin="brain") == ["art-1"]
    assert matched(kinds=["window"], text="absent") == []


def test_scopes_are_computed_on_the_whole_scene_then_intersected():
    # Le chemin vers job:c passe par grp (non retenu) : job:c reste membre.
    assert matched(constellation={"object_id": "claude:a"}, kinds=["job", "artifact"]) == ["art-1", "art-2", "job:c"]
    assert matched(group="grp", constellation={"object_id": "claude:b", "depth": 2}) == ["art-1"]


def test_exclude_applies_last():
    assert matched(kinds=["artifact", "window"], exclude=["art-1", "win"]) == ["art-2", "win-2"]
    assert matched(constellation={"object_id": "claude:a"}, exclude=["claude:a"])[0] == "art-1"
    # Exclure un objet qu'aucun filtre ne retient ne change rien.
    assert matched(kinds=["window"], exclude=["grp"]) == ["win", "win-2"]


def test_canonical_order_by_mode():
    # 1. explicite : ordre de l'appelant.
    ids = ["win", "claude:a", "grp"]
    assert matched(ids=ids) == ids
    # 2. near l'emporte sur constellation.
    assert matched(near={"object_id": "claude:a", "radius": 10}, constellation={"object_id": "claude:a"}) == ["art-1"]
    # 3. constellation : ordre de la constellation, pas celui de la scène.
    by_constellation = matched(constellation={"object_id": "grp"}, kinds=["artifact", "job"])
    assert by_constellation == ["art-1", "job:c", "art-2"]
    assert by_constellation != [object_id for object_id in SNAPSHOT_ORDER if object_id in by_constellation]
    # 4. sinon : ordre de la scène.
    assert matched(kinds=["window", "agent"]) == ["claude:a", "claude:b", "win", "win-2"]


def test_order_follows_the_snapshot_insertion_order_not_ids_or_hashing():
    """Mêmes objets, insérés à l'envers : le mode filtres suit la nouvelle
    insertion ; la constellation, qui ne dépend que de l'ordre des relations, ne bouge pas."""

    reversed_scene = SceneSnapshot(scene_id="scene", revision=SCENE.revision, objects=tuple(reversed(SCENE.objects)),
                                   relations=SCENE.relations, archived_ids=SCENE.archived_ids)
    plain = sel(kinds=["window", "agent"])
    assert resolve_selection(SCENE, plain).matched_ids == ("claude:a", "claude:b", "win", "win-2")
    assert resolve_selection(reversed_scene, plain).matched_ids == ("win-2", "win", "claude:b", "claude:a")
    scoped = sel(constellation={"object_id": "claude:a"}, kinds=["artifact", "job", "agent"])
    assert (resolve_selection(reversed_scene, scoped).matched_ids == resolve_selection(SCENE, scoped).matched_ids
            == ("claude:a", "art-1", "art-2", "claude:b", "job:c"))
    # Relations réordonnées : l'ordre de la constellation change avec elles.
    swapped = SceneSnapshot(scene_id="scene", revision=SCENE.revision, objects=SCENE.objects,
                            relations=(SCENE.relations[1], SCENE.relations[0], *SCENE.relations[2:]),
                            archived_ids=SCENE.archived_ids)
    assert resolve_selection(swapped, scoped).matched_ids == ("claude:a", "art-2", "art-1", "claude:b", "job:c")


# ------------------------------------------------------------------ références et ids explicites


@pytest.mark.parametrize("field_wire, field_name", [
    ({"constellation": {"object_id": "{}"}}, "constellation"),
    ({"near": {"object_id": "{}", "radius": 5}}, "near"),
    ({"explains": "{}"}, "explains"),
    ({"group": "{}"}, "group"),
    ({"kinds": ["job"], "exclude": ["{}"]}, "exclude"),
])
@pytest.mark.parametrize("target, reason", [
    ("ghost", SceneRefusal.UNKNOWN_OBJECT),
    ("old", SceneRefusal.OBJECT_ARCHIVED),
])
def test_an_unknown_or_archived_reference_refuses_the_whole_selection(field_wire, field_name, target, reason):
    wire = {key: (value.replace("{}", target) if isinstance(value, str) else
                  [v.replace("{}", target) for v in value] if isinstance(value, list) else
                  {k: (v.replace("{}", target) if isinstance(v, str) else v) for k, v in value.items()})
            for key, value in field_wire.items()}
    resolution = resolve_selection(SCENE, sel(**wire))
    assert resolution.refused == (SelectionRefusal(target, reason, field_name),)
    assert resolution.matched_ids == () and resolution.skipped == () and resolution.hidden_count == 0
    assert resolution.reason(archived_ok=True) is reason and resolution.reason(archived_ok=False) is reason


def test_near_reference_must_be_placed_and_group_must_be_a_group():
    unplaced = resolve_selection(SCENE, sel(near={"object_id": "claude:b", "radius": 5}))
    assert unplaced.refused == (SelectionRefusal("claude:b", SceneRefusal.UNPLACED, "near"),)
    not_group = resolve_selection(SCENE, sel(group="claude:a"))
    assert not_group.refused == (SelectionRefusal("claude:a", SceneRefusal.INVALID_SELECTION, "group"),)
    assert not_group.matched_ids == ()


def test_every_offending_reference_is_listed_in_canonical_order():
    selection = sel(constellation={"object_id": "old"}, near={"object_id": "claude:b", "radius": 1}, explains="ghost",
                    group="win", exclude=["art-1", "gone", "older"])
    resolution = resolve_selection(SCENE, selection)
    assert [(entry.object_id, entry.reason, entry.field) for entry in resolution.refused] == [
        ("old", SceneRefusal.OBJECT_ARCHIVED, "constellation"),
        ("claude:b", SceneRefusal.UNPLACED, "near"),
        ("ghost", SceneRefusal.UNKNOWN_OBJECT, "explains"),
        ("win", SceneRefusal.INVALID_SELECTION, "group"),
        ("gone", SceneRefusal.UNKNOWN_OBJECT, "exclude"),
        ("older", SceneRefusal.OBJECT_ARCHIVED, "exclude"),
    ]
    assert resolution.reason(archived_ok=False) is SceneRefusal.OBJECT_ARCHIVED
    assert resolution.refused[0].to_payload() == {"id": "old", "reason": "object_archived", "field": "constellation"}


def test_explicit_ids_unknown_refuse_all_archived_are_set_aside_for_the_operation():
    resolution = resolve_selection(SCENE, sel(ids=["win", "old", "ghost", "claude:a", "older", "nobody"]))
    # Inconnus : refus quelle que soit l'opération, tous listés, ordre de l'appelant.
    assert resolution.refused == (SelectionRefusal("ghost", SceneRefusal.UNKNOWN_OBJECT, "ids"),
                                  SelectionRefusal("nobody", SceneRefusal.UNKNOWN_OBJECT, "ids"))
    assert resolution.archived_ids == ("old", "older")
    assert resolution.matched_ids == ()
    # Opération qui refuse l'archivé : archivés fusionnés à leur place.
    assert [entry.object_id for entry in resolution.refusals(archived_ok=False)] == ["old", "ghost", "older", "nobody"]
    assert resolution.reason(archived_ok=False) is SceneRefusal.OBJECT_ARCHIVED
    assert resolution.reason(archived_ok=True) is SceneRefusal.UNKNOWN_OBJECT


def test_explicit_archived_ids_alone_are_not_refused_for_archive():
    resolution = resolve_selection(SCENE, sel(ids=["win", "old", "claude:a"]))
    assert resolution.refused == () and resolution.refusals(archived_ok=True) == ()
    assert resolution.matched_ids == ("win", "claude:a") and resolution.archived_ids == ("old",)
    assert resolution.refusals(archived_ok=False) == (SelectionRefusal("old", SceneRefusal.OBJECT_ARCHIVED, "ids"),)
    assert resolution.reason(archived_ok=True) is None


def test_placement_rule_refuses_explicit_ids_but_skips_filter_members():
    explicit = resolve_selection(SCENE, sel(ids=["claude:a", "claude:b", "attention!claude:a"]), require_placed=True)
    assert explicit.refused == (SelectionRefusal("claude:b", SceneRefusal.UNPLACED, "ids"),
                                SelectionRefusal("attention!claude:a", SceneRefusal.UNPLACED, "ids"))
    assert explicit.matched_ids == ()
    # Sans la règle (patch, archive), les mêmes ids sont retenus.
    assert resolve_selection(SCENE, sel(ids=["claude:a", "claude:b"])).matched_ids == ("claude:a", "claude:b")

    filtered = resolve_selection(SCENE, sel(constellation={"object_id": "claude:a", "depth": 1}), require_placed=True)
    assert filtered.refused == ()
    assert filtered.matched_ids == ("claude:a", "art-1", "art-2", "attention!claude:a", "claude:b")
    assert filtered.skipped == (SelectionSkip("attention!claude:a", SceneRefusal.UNPLACED),
                                SelectionSkip("claude:b", SceneRefusal.UNPLACED))
    assert filtered.eligible_ids == ("claude:a", "art-1", "art-2")
    assert filtered.skipped[0].to_payload() == {"id": "attention!claude:a", "reason": "unplaced"}


def test_hidden_members_are_counted():
    assert resolve_selection(SCENE, sel(constellation={"object_id": "claude:a"})).hidden_count == 2
    assert resolve_selection(SCENE, sel(constellation={"object_id": "claude:b", "depth": 1})).hidden_count == 0
    assert resolve_selection(SCENE, sel(ids=["job:c", "win"])).hidden_count == 1


def test_a_filter_matching_nothing_is_an_empty_truthful_result():
    resolution = resolve_selection(SCENE, sel(text="introuvable"))
    assert resolution.refused == () and resolution.matched_ids == () and resolution.reason(archived_ok=False) is None


def test_resolution_arguments_are_typed():
    with pytest.raises(TypeError):
        resolve_selection(SCENE, {"kinds": ["job"]})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        resolve_selection(SCENE.to_payload(), sel(kinds=["job"]))  # type: ignore[arg-type]


def test_a_hand_built_resolution_cannot_drop_archived_refusals():
    with pytest.raises(TypeError):
        SelectionResolution(SelectionMode.EXPLICIT, archived_ids=("old",))  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        SelectionResolution(SelectionMode.EXPLICIT, refused_with_archived=(), archived_ids=("old",))
    kept = SelectionResolution(SelectionMode.EXPLICIT, archived_ids=("old",),
                               refused_with_archived=(SelectionRefusal("old", SceneRefusal.OBJECT_ARCHIVED, "ids"),))
    assert kept.reason(archived_ok=False) is SceneRefusal.OBJECT_ARCHIVED and kept.reason(archived_ok=True) is None
