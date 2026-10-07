"""Choix dynamiques et manifeste du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 2).

Contrat : `docs/tool-brain-contracts.md` §8. Ce qui doit tenir :

- la projection d'interface vit dans `ToolMeta` (seule copie) et reste cohérente avec les schémas annoncés ;
- chaque fournisseur de choix n'offre que des valeurs légales **maintenant** (objets retirés disparus) ;
- les choix annoncés et le réducteur (`apply_scene_command`) s'accordent : tout choix passe, un id fabriqué ou
  archivé est refusé avec le même code des deux côtés ;
- le libellé n'est jamais une autorité ; les paramètres libres sont dits libres ;
- la fraîcheur (`StateRef`) refuse une autre époque ou un autre Board actif, jamais une simple révision plus ancienne.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from jarvis.domain.scene import (
    RelationKind, SceneActor, SceneCommand, SceneCommandOutcome, SceneObjectFields, SceneObjectKind, SceneOp,
    ScenePayload, SceneRelation, SceneSnapshot, Visibility, apply_scene_command,
)
from jarvis.domain.workspace_board import Board, BoardStatus
from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError
from jarvis.runtime import tool_brain_choices as tbc
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.mcp_tool_meta import CHOICE_PROVIDERS, SERVERS, UI_PRECONDITIONS
from jarvis.runtime.tool_brain_choices import (
    MAX_ADVERTISED_CHOICES, PROVIDERS, UiState, build_manifest, read_ui_state, validate_call,
)

AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
DISPLAY, WORKSPACE, SURFACE = "jarvis-display", "jarvis-workspace", "jarvis-surface"


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


# ------------------------------------------------------------------ monde de test


def _apply(snapshot: SceneSnapshot, actor: SceneActor, op: SceneOp, **kw):
    return apply_scene_command(snapshot, SceneCommand(op=op, actor=actor, **kw))


def _applied(snapshot: SceneSnapshot, actor: SceneActor, op: SceneOp, **kw) -> SceneSnapshot:
    update = _apply(snapshot, actor, op, **kw)
    assert update.outcome is SceneCommandOutcome.APPLIED, (update.outcome, update.reason, update.detail)
    return update.snapshot


def _note(snapshot: SceneSnapshot, object_id: str, title: str) -> SceneSnapshot:
    return _applied(snapshot, SceneActor.BRAIN, SceneOp.UPSERT_OBJECT, object_id=object_id, fields=SceneObjectFields(
        kind=SceneObjectKind.ARTIFACT, category="note", payload=ScenePayload(title=title)))


def _world() -> SceneSnapshot:
    snapshot = SceneSnapshot(scene_id="scene-1")
    snapshot = _note(snapshot, "brain-note-000000000001", "Plan du jour")
    snapshot = _note(snapshot, "brain-note-000000000002", "Idées   en   vrac")
    snapshot = _applied(snapshot, SceneActor.RUNTIME, SceneOp.UPSERT_OBJECT, object_id="claude:task-1",
                        fields=SceneObjectFields(kind=SceneObjectKind.AGENT, category="agent"))
    snapshot = _applied(snapshot, SceneActor.RUNTIME, SceneOp.UPSERT_OBJECT, object_id="claude:task-2",
                        fields=SceneObjectFields(kind=SceneObjectKind.JOB, category="job"))
    return snapshot


def _board(board_id: str, title: str, status=BoardStatus.ACTIVE) -> Board:
    return Board(board_id=board_id, title=title, created_at=AT, updated_at=AT, status=status)


def _state(snapshot: SceneSnapshot | None = None, *, active: str = "default", epoch: str | None = "e1") -> UiState:
    boards = (_board("default", "Principal"), _board("board_aaa", "Projet A"),
              _board("board_old", "Ancien", BoardStatus.ARCHIVED))
    return UiState(scene=snapshot if snapshot is not None else _world(), epoch=epoch, boards=boards,
                   active_board_id=active)


# ------------------------------------------------------------------ une seule source


def test_every_provider_id_has_exactly_one_implementation_and_one_description():
    assert set(PROVIDERS) == set(CHOICE_PROVIDERS)
    assert all(provider.provider_id == key for key, provider in PROVIDERS.items())


def test_ui_projection_is_consistent_in_the_single_metadata_copy(catalog):
    descriptors = {(t["server"], t["name"]): t for t in catalog["tools"]}
    seen = 0
    for server in SERVERS:
        for name, meta in server.tools.items():
            if meta.ui_surface is None:
                assert meta.reversibility is None and not meta.choice_providers and not meta.preconditions, name
                continue
            seen += 1
            assert meta.ui_surface in ("scene", "board", "browser"), name
            if meta.side_effect == "read":
                assert meta.reversibility is None, name
            else:
                assert meta.reversibility in ("reversible", "irreversible"), name
            if meta.side_effect == "destructive":
                assert meta.reversibility == "irreversible", name
            assert set(meta.preconditions) <= set(UI_PRECONDITIONS), name
            assert set(meta.choice_providers.values()) <= set(CHOICE_PROVIDERS), name
            # Un paramètre à fournisseur existe vraiment dans le schéma annoncé par le vrai serveur.
            advertised = {p["name"] for p in descriptors[(server.server, name)]["parameters"]}
            assert set(meta.choice_providers) <= advertised, name
    assert seen >= 14


def test_the_ui_surface_covers_scene_and_board_tools_and_nothing_else(catalog):
    ui = {(t["server"], t["name"]) for t in catalog["tools"] if t["ui"] is not None}
    assert {(DISPLAY, "scene_move"), (DISPLAY, "scene_archive"), (DISPLAY, "scene_link"),
            (WORKSPACE, "board_switch"), (WORKSPACE, "board_list")} <= ui
    # Bibliothèque de prefabs, réglages, mémoire, sessions : pas des opérations d'interface en V1.
    assert not ({(DISPLAY, "prefab_save"), (DISPLAY, "prefab_events"), (WORKSPACE, "session_new"),
                 (WORKSPACE, "board_archive"), (WORKSPACE, "board_create")} & ui)
    assert all(t["ui"] is None for t in catalog["tools"] if t["server"] not in (DISPLAY, WORKSPACE, SURFACE))
    archive = next(t for t in catalog["tools"] if t["name"] == "scene_archive")["ui"]
    assert archive["reversibility"] == "irreversible"


# ------------------------------------------------------------------ choix = états légaux


def test_scene_object_choices_are_the_active_objects_with_label_and_compact_meta():
    state = _state()
    choices = PROVIDERS["scene.object"].list_choices(state)
    assert {c.value for c in choices} == {o.object_id for o in state.scene.objects}
    by_id = {c.value: c for c in choices}
    assert by_id["brain-note-000000000002"].label == "Idées en vrac"  # une ligne, espaces normalisés
    assert by_id["claude:task-1"].meta["kind"] == "agent"
    assert set(by_id["claude:task-1"].meta) == {"kind", "category", "representation", "visibility", "exec_state",
                                               "pinned", "placed"}


def test_a_removed_object_disappears_from_choices_and_is_refused_with_the_reducer_code():
    state = _state()
    gone = "brain-note-000000000001"
    after = _applied(state.scene, SceneActor.BRAIN, SceneOp.ARCHIVE, object_id=gone)
    new = _state(after)
    assert gone not in {c.value for c in PROVIDERS["scene.object"].list_choices(new)}
    verdict = validate_call(DISPLAY, "scene_update_object", {"object_id": gone}, new)
    assert [r.code for r in verdict.refusals] == ["object_archived"]
    reducer = _apply(after, SceneActor.BRAIN, SceneOp.SET_VISIBILITY, object_id=gone, visibility=Visibility.HIDDEN)
    assert reducer.outcome is SceneCommandOutcome.INVALID and reducer.reason.value == "object_archived"


def test_every_advertised_object_choice_is_accepted_and_a_fabricated_id_is_refused_by_both_sides():
    state = _state()
    for choice in PROVIDERS["scene.object"].list_choices(state):
        assert validate_call(DISPLAY, "scene_pin", {"object_ids": [choice.value]}, state).ok, choice.value
        reducer = _apply(state.scene, SceneActor.BRAIN, SceneOp.SET_VISIBILITY, object_id=choice.value,
                         visibility=Visibility.HIDDEN)
        assert reducer.outcome is SceneCommandOutcome.APPLIED, choice.value
    verdict = validate_call(DISPLAY, "scene_pin", {"object_ids": ["brain-note-ffffffffffff"]}, state)
    assert [(r.code, r.parameter) for r in verdict.refusals] == [("unknown_object", "object_ids")]
    reducer = _apply(state.scene, SceneActor.BRAIN, SceneOp.SET_VISIBILITY, object_id="brain-note-ffffffffffff",
                     visibility=Visibility.HIDDEN)
    assert reducer.outcome is SceneCommandOutcome.INVALID and reducer.reason.value == "unknown_object"


def test_the_label_is_never_an_authority_only_the_value_counts():
    state = _state()
    assert not validate_call(DISPLAY, "scene_get", {"object_ids": ["Plan du jour"]}, state).ok
    assert validate_call(DISPLAY, "scene_get", {"object_ids": ["brain-note-000000000001"]}, state).ok


def test_every_bad_value_of_a_selection_is_reported_not_just_the_first():
    verdict = validate_call(
        DISPLAY, "scene_move", {"object_ids": ["nope-1", "brain-note-000000000001", "nope-2"], "dx": 5}, _state())
    assert [r.value for r in verdict.refusals] == ["nope-1", "nope-2"]


def test_link_endpoints_and_artifact_target_use_the_object_provider():
    state = _state()
    assert validate_call(DISPLAY, "scene_link", {"from_id": "claude:task-1", "to_id": "brain-note-000000000001",
                                                  "kind": "explains"}, state).ok
    verdict = validate_call(DISPLAY, "scene_link", {"from_id": "x", "to_id": "y", "kind": "explains"}, state)
    assert [r.parameter for r in verdict.refusals] == ["from_id", "to_id"]
    assert not validate_call(DISPLAY, "scene_add_artifact", {"target_id": "x", "category": "note"}, state).ok


def test_unlink_choices_exclude_runtime_owned_relations_and_agree_with_the_reducer():
    snapshot = _world()
    snapshot = _applied(snapshot, SceneActor.RUNTIME, SceneOp.LINK, relation=SceneRelation(
        "parent_of!rt1", RelationKind.PARENT_OF, "claude:task-1", "claude:task-2"))
    snapshot = _applied(snapshot, SceneActor.BRAIN, SceneOp.LINK, relation=SceneRelation(
        "brain-explains-0000000000000001", RelationKind.EXPLAINS, "brain-note-000000000001", "claude:task-1"))
    state = _state(snapshot)
    assert [c.value for c in PROVIDERS["scene.relation"].list_choices(state)] == ["brain-explains-0000000000000001"]
    assert validate_call(DISPLAY, "scene_unlink", {"relation_id": "brain-explains-0000000000000001"}, state).ok
    owned = validate_call(DISPLAY, "scene_unlink", {"relation_id": "parent_of!rt1"}, state)
    assert [r.code for r in owned.refusals] == ["runtime_owned"]
    reducer = _apply(snapshot, SceneActor.BRAIN, SceneOp.UNLINK, relation_id="parent_of!rt1")
    assert reducer.reason.value == "runtime_owned"
    unknown = validate_call(DISPLAY, "scene_unlink", {"relation_id": "brain-explains-zzz"}, state)
    assert [r.code for r in unknown.refusals] == ["unknown_relation"]


def test_board_choices_exclude_archived_for_switch_and_mark_the_active_one():
    state = _state(active="board_aaa")
    switch = {c.value: c for c in PROVIDERS["board.switchable"].list_choices(state)}
    assert set(switch) == {"default", "board_aaa"} and switch["board_aaa"].meta["active"] is True
    assert {c.value for c in PROVIDERS["board.readable"].list_choices(state)} == {"default", "board_aaa", "board_old"}
    assert validate_call(WORKSPACE, "board_switch", {"board_id": "default"}, state).ok
    codes = {value: [r.code for r in validate_call(WORKSPACE, "board_switch", {"board_id": value}, state).refusals]
             for value in ("board_old", "board_zzz")}
    assert codes == {"board_old": ["board_archived"], "board_zzz": ["board_not_found"]}
    assert validate_call(WORKSPACE, "board_get", {"board_id": "board_old"}, state).ok  # lecture d'un archivé : légale


# ------------------------------------------------------------------ fraîcheur et garde


def test_freshness_refuses_another_world_but_only_reports_older_revisions():
    state = _state()
    observed = state.ref()
    args = {"object_ids": ["claude:task-1"]}
    assert validate_call(DISPLAY, "scene_pin", args, state, observed=observed).revision_drift == 0
    later = _state(_note(state.scene, "brain-note-000000000003", "Neuf"))
    drift = validate_call(DISPLAY, "scene_pin", args, later, observed=observed)
    assert drift.ok and drift.revision_drift == 1
    other_epoch = validate_call(DISPLAY, "scene_pin", args, _state(epoch="e2"), observed=observed)
    assert [r.code for r in other_epoch.refusals] == ["stale_scene_epoch"]
    moved = validate_call(WORKSPACE, "board_switch", {"board_id": "default"}, _state(active="board_aaa"),
                          observed=observed)
    assert [r.code for r in moved.refusals] == ["stale_active_board"]


def test_unknown_tool_non_ui_tool_and_missing_scene_are_refused_by_name():
    state = _state()
    assert [r.code for r in validate_call(DISPLAY, "nope", {}, state).refusals] == ["unknown_tool"]
    assert [r.code for r in validate_call(DISPLAY, "prefab_save", {}, state).refusals] == ["not_ui_tool"]
    unserved = UiState(None, None, (), None)
    assert [r.code for r in validate_call(DISPLAY, "scene_move", {"object_ids": ["a"]}, unserved).refusals] \
        == ["scene_unavailable"]
    assert [r.code for r in validate_call(DISPLAY, "scene_pin", {"object_ids": [3]}, state).refusals] \
        == ["invalid_choice_type"]


# ------------------------------------------------------------------ état chez les propriétaires


class _Scene:
    def __init__(self, snapshot=None, epoch="e1", fail=False):
        self._snapshot, self.epoch, self._fail = snapshot, epoch, fail

    async def snapshot(self):
        if self._fail:
            raise SceneUnavailableError(next(iter(SceneStoreErrorCode)), "closed")
        return self._snapshot


class _Boards:
    def __init__(self, boards, active):
        self._boards, self._active, self.include_archived = boards, active, None

    async def list(self, *, include_archived=False):
        self.include_archived = include_archived
        return self._boards

    async def active_board_id(self):
        return self._active


def test_read_ui_state_reads_the_owners_and_maps_an_unserved_scene_to_none():
    boards = _Boards((_board("default", "P"),), "default")
    state = asyncio.run(read_ui_state(_Scene(_world()), boards))
    assert state.scene.revision == 4 and state.epoch == "e1" and state.active_board_id == "default"
    assert boards.include_archived is True
    down = asyncio.run(read_ui_state(_Scene(fail=True), boards))
    assert down.scene is None and down.epoch is None
    assert asyncio.run(read_ui_state(None, None)) == UiState(None, None, (), None)


# ------------------------------------------------------------------ manifeste


def test_manifest_lists_ui_tools_only_with_choices_and_state_reference(catalog):
    state = _state()
    manifest = build_manifest(catalog, state)
    assert manifest["schema"] == "tool_brain.manifest/1"
    assert manifest["state"] == {"scene_id": "scene-1", "epoch": "e1", "revision": 4, "active_board_id": "default"}
    tools = {t["name"]: t for t in manifest["tools"]}
    assert "prefab_save" not in tools and "settings_set" not in tools and "scene_move" in tools
    params = {p["name"]: p for p in tools["scene_move"]["parameters"]}
    assert params["object_ids"]["mode"] == "provider"
    assert params["object_ids"]["choices_ref"] == "scene.object"
    block = manifest["choices"]["scene.object"]
    assert {c["value"] for c in block["items"]} == {o.object_id for o in state.scene.objects}
    assert block["total"] == 4 and block["truncated"] is False
    assert set(manifest["choices"]) == {"scene.object", "scene.relation", "board.switchable", "board.readable",
                                       "surface.browser"}
    assert tools["scene_move"]["reversibility"] == "reversible"
    assert tools["scene_archive"]["reversibility"] == "irreversible"
    assert tools["scene_move"]["preconditions"] == ["scene_available", "object_active"]
    assert manifest["precondition_rules"]["object_active"] == UI_PRECONDITIONS["object_active"]
    switch = {p["name"]: p for p in tools["board_switch"]["parameters"]}["board_id"]
    assert [c["value"] for c in manifest["choices"][switch["choices_ref"]]["items"]] == ["default", "board_aaa"]


def test_free_form_and_bounded_parameters_are_said_so(catalog):
    manifest = build_manifest(catalog, _state())
    by_tool = {t["name"]: {p["name"]: p for p in t["parameters"]} for t in manifest["tools"]}
    create = by_tool["scene_create_object"]
    assert create["title"]["mode"] == "free_form" and "choices" not in create["title"]
    assert create["kind"]["mode"] == "enum" and "artifact" in create["kind"]["constraints"]["enum"]
    assert by_tool["scene_move"]["select"]["mode"] == "free_form"
    # Un paramètre libre ne cache jamais un id d'objet : tout `*_id(s)` hors `relation_id` optionnel a un fournisseur.
    for name, params in by_tool.items():
        for pname, p in params.items():
            if pname.endswith(("_id", "_ids")) and (name, pname) != ("scene_link", "relation_id"):
                # scene_link.relation_id : id **neuf** facultatif (dérivé du lien quand absent), pas une référence.
                assert p["mode"] == "provider", (name, pname)


def test_advertised_choices_are_capped_but_the_validator_sees_the_whole_legal_list(catalog):
    snapshot = SceneSnapshot(scene_id="scene-big")
    for index in range(MAX_ADVERTISED_CHOICES + 5):
        snapshot = _note(snapshot, f"brain-note-{index:012x}", f"N{index}")
    state = _state(snapshot)
    block = build_manifest(catalog, state)["choices"]["scene.object"]
    assert block["total"] == MAX_ADVERTISED_CHOICES + 5 and block["truncated"]
    assert len(block["items"]) == MAX_ADVERTISED_CHOICES
    last = f"brain-note-{MAX_ADVERTISED_CHOICES + 4:012x}"
    assert validate_call(DISPLAY, "scene_get", {"object_ids": [last]}, state).ok


def test_a_scene_not_served_yields_empty_choices_that_say_why(catalog):
    manifest = build_manifest(catalog, UiState(None, None, (), None))
    block = manifest["choices"]["scene.object"]
    assert block["items"] == [] and block["unavailable"] == "scene_unavailable"
    assert manifest["state"]["scene_id"] is None


def test_the_manifest_stays_compact_for_a_model_context(catalog):
    manifest = build_manifest(catalog, _state())
    size = len(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode())
    assert size < 32_000, size  # ~8k tokens pour les 22 outils (S7 : +5 surface_*) ; `include_surfaces` / `include_tools` réduisent
    small = build_manifest(catalog, _state(), include_tools=("scene_move", "board_switch"))
    assert [t["name"] for t in small["tools"]] == ["scene_move", "board_switch"]
    assert set(small["choices"]) == {"scene.object", "board.switchable"}
    assert [t["name"] for t in build_manifest(catalog, _state(), include_surfaces=("board",))["tools"]]         == ["board_list", "board_get", "board_get_active", "board_switch"]
    for tool in manifest["tools"]:
        assert "\n" not in tool["summary"]
        assert all(len(p["description"]) <= tbc.MAX_PARAMETER_DESCRIPTION_CHARS for p in tool["parameters"])


def test_catalog_descriptor_carries_the_ui_projection(catalog):
    move = next(t for t in catalog["tools"] if t["name"] == "scene_move")
    assert move["ui"] == {"surface": "scene", "reversibility": "reversible",
                          "preconditions": ["scene_available", "object_active"],
                          "choice_providers": {"object_ids": "scene.object"}}
    assert next(t for t in catalog["tools"] if t["name"] == "scene_inspect")["ui"]["reversibility"] is None
