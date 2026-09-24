"""Constellation canonique (handoff jarvis-mcp-semantic-batch-inspector, Slice 02).

Contrat : `docs/scene-selection-batch.md` §2. Les mêmes fixtures
(`tests/fixtures/scene_constellation_cases.json`) sont jouées contre le
domaine (`constellation_of`, tous les cas) et contre la copie de la page
(`constellationOf` de `control_center_scene_interact.js`, exécuté par node,
cas sans profondeur : la page n'en a pas). Premier test de `constellationOf`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jarvis.domain.scene import (
    DEFAULT_LAYERS,
    ExecState,
    PlacedBy,
    RelationKind,
    SceneActor,
    SceneConstraints,
    SceneObject,
    SceneObjectKind,
    ScenePayload,
    SceneRelation,
    SceneSnapshot,
    Visibility,
    WorkRef,
    signal_owners,
)
from jarvis.domain.scene_selection import MAX_CONSTELLATION_DEPTH, constellation_of
from tests.unit.test_scene_interaction_logic import run_node

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "scene_constellation_cases.json"
CORPUS = json.loads(FIXTURE.read_text(encoding="utf-8"))
RUNTIME_KINDS = {"agent", "job", "attention"}


def build_scene(spec: dict[str, Any]) -> SceneSnapshot:
    """Forme compacte de la fixture → instantané du domaine (défauts décrits dans `contract`)."""

    objects = []
    for entry in spec["objects"]:
        kind = SceneObjectKind(entry["kind"])
        origin = SceneActor(entry.get("origin", "runtime" if entry["kind"] in RUNTIME_KINDS else "brain"))
        work = entry.get("work")
        objects.append(SceneObject(
            object_id=entry["id"], kind=kind, category=entry["kind"],
            constraints=SceneConstraints(placed_by=PlacedBy(origin.value)), origin=origin,
            exec_state=ExecState.RUNNING if kind.value in RUNTIME_KINDS else ExecState.UNKNOWN,
            layer=DEFAULT_LAYERS[kind], visibility=Visibility(entry.get("visibility", "visible")),
            work_ref=None if work is None else WorkRef(source=work[0], external_id=work[1]),
            payload=ScenePayload(title=entry["id"]),
        ))
    relations = tuple(SceneRelation(relation_id=rid, kind=RelationKind(kind), from_id=a, to_id=b)
                      for rid, kind, a, b in spec["relations"])
    return SceneSnapshot(scene_id="scene", revision=3, objects=tuple(objects), relations=relations,
                         archived_ids=tuple(spec["archived_ids"]))


SCENES = {name: build_scene(spec) for name, spec in CORPUS["scenes"].items()}
CASES = CORPUS["cases"]


def test_the_fixture_covers_every_mandatory_case():
    """§2.5 : cas obligatoires présents dans le corpus partagé (et donc joués des deux côtés)."""

    figure = SCENES["figure"]
    owners = signal_owners(figure)
    # Signal vivant, signal retiré trouvé par le travail, orphelin.
    assert owners["attention!claude:root"] == "claude:root"
    assert figure.get_relation("attention!claude:child") is None and owners["attention!claude:child"] == "claude:child"
    assert owners["attention!claude:ghost"] is None
    # Chaque nature de lien apparaît, et chaque cas a une racine d'un côté et de l'autre du lien.
    kinds = {relation.kind for relation in figure.relations}
    assert kinds == set(RelationKind)
    roots = {case["root"] for case in CASES}
    for relation in figure.relations:
        assert relation.from_id in roots or relation.to_id in roots
    depths = {case["depth"] for case in CASES}
    assert {None, 1, 2} <= depths
    assert any(figure.get_object(case["root"]) is not None and figure.get_object(case["root"]).visibility is Visibility.HIDDEN
               for case in CASES)
    assert any(figure.is_archived(case["root"]) for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_domain_constellation_matches_the_shared_fixture(case):
    assert constellation_of(SCENES[case["scene"]], case["root"], case["depth"]) == tuple(case["expected"])


def test_page_constellation_matches_the_shared_fixture(tmp_path):
    """Parité : la copie de la page rend exactement la même liste, dans le même ordre."""

    cases = [case for case in CASES if case["depth"] is None]
    assert len(cases) >= 8
    data = {"scenes": {name: scene.to_payload() for name, scene in SCENES.items()},
            "cases": [{"scene": case["scene"], "root": case["root"]} for case in cases]}
    result = run_node(tmp_path, r"""
      const states=Object.fromEntries(Object.entries(D.scenes).map(([name,snapshot])=>
        [name,S.fromSnapshot({scene_id:snapshot.scene_id,epoch:'e',revision:snapshot.revision,snapshot}).state]));
      return D.cases.map(c=>I.constellationOf(states[c.scene],c.root));
    """, data)
    assert result == [case["expected"] for case in cases]


def test_the_page_uses_the_same_algorithm_after_the_domain_on_a_rich_scene(tmp_path):
    """Au-delà des fixtures : chaque objet d'une scène de cycle de vie réelle, domaine = page."""

    from tests.unit.test_scene_user_lifecycle import lifecycle_scene, with_orphan

    scene = with_orphan(lifecycle_scene())
    expected = {item.object_id: list(constellation_of(scene, item.object_id)) for item in scene.objects}
    result = run_node(tmp_path, r"""
      const st=S.fromSnapshot({scene_id:D.snapshot.scene_id,epoch:'e',revision:D.snapshot.revision,snapshot:D.snapshot}).state;
      return Object.fromEntries([...st.objects.keys()].map(id=>[id,I.constellationOf(st,id)]));
    """, {"snapshot": scene.to_payload()})
    assert result == expected
    assert any(len(members) > 2 for members in expected.values())


def test_depth_is_validated():
    figure = SCENES["figure"]
    for bad in (0, MAX_CONSTELLATION_DEPTH + 1, -1):
        with pytest.raises(ValueError):
            constellation_of(figure, "claude:root", bad)
    for bad in (True, 1.0, "2"):
        with pytest.raises(TypeError):
            constellation_of(figure, "claude:root", bad)  # type: ignore[arg-type]
    # Au maximum, toute la figure (elle a 3 anneaux).
    assert constellation_of(figure, "claude:root", MAX_CONSTELLATION_DEPTH) == constellation_of(figure, "claude:root")


def test_bounded_depth_is_a_prefix_of_the_whole_component():
    """BFS : borner la profondeur coupe la liste, ne la réordonne jamais."""

    for name, scene in SCENES.items():
        for item in scene.objects:
            whole = constellation_of(scene, item.object_id)
            for depth in range(1, MAX_CONSTELLATION_DEPTH + 1):
                bounded = constellation_of(scene, item.object_id, depth)
                assert whole[: len(bounded)] == bounded, (name, item.object_id, depth)
