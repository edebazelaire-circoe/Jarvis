"""Perception du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, Slice 3).

Contrat : `docs/tool-brain-contracts.md` §9. Ce qui doit tenir :

- l'instantané reflète l'état canonique (révision, Board actif) et rien d'autre : projection, pas persistance ;
- il reste **borné** (octets) quel que soit le nombre d'objets, avec troncature déterministe et marqueur explicite ;
- même état => mêmes octets (rejeu) ; une révision de plus => un autre condensat ;
- la lecture ciblée d'un id rend plus que l'instantané ; un id inconnu/archivé échoue proprement ;
- les coutures parole/file/surfaces sont vides et typées, sans vérité inventée.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from jarvis.domain.scene import (
    ExecState, RelationKind, Representation, SceneActor, SceneCommand, SceneCommandOutcome, SceneGeometry,
    SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, ScenePayloadItem, SceneRelation, SceneSnapshot,
    Visibility, apply_scene_command,
)
from jarvis.domain.workspace_board import Board, BoardStatus
from jarvis.ports.scene import SceneStoreErrorCode, SceneUnavailableError
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tool_brain_choices import UiState
from jarvis.runtime.tool_brain_perception import (
    INSPECTION_READS, MAX_PERCEPTION_BYTES, QueueSection, SpeechSection, build_perception, get_available_actions,
    get_information_on, get_queue_state, inspectable_ids, list_related, perceive,
)

AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
DISPLAY = "jarvis-display"


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


# ------------------------------------------------------------------ monde de test


def _applied(snapshot: SceneSnapshot, actor: SceneActor, op: SceneOp, **kw) -> SceneSnapshot:
    update = apply_scene_command(snapshot, SceneCommand(op=op, actor=actor, **kw))
    assert update.outcome is SceneCommandOutcome.APPLIED, (update.outcome, update.reason, update.detail)
    return update.snapshot


def _brain(snapshot: SceneSnapshot, object_id: str, **fields) -> SceneSnapshot:
    fields.setdefault("kind", SceneObjectKind.ARTIFACT)
    fields.setdefault("category", "note")
    return _applied(snapshot, SceneActor.BRAIN, SceneOp.UPSERT_OBJECT, object_id=object_id,
                    fields=SceneObjectFields(**fields))


def _star(snapshot: SceneSnapshot, object_id: str, kind=SceneObjectKind.AGENT, state=ExecState.UNKNOWN) -> SceneSnapshot:
    return _applied(snapshot, SceneActor.RUNTIME, SceneOp.UPSERT_OBJECT, object_id=object_id,
                    fields=SceneObjectFields(kind=kind, category=kind.value, exec_state=state))


def _world() -> SceneSnapshot:
    snapshot = SceneSnapshot(scene_id="scene-1")
    snapshot = _brain(snapshot, "brain-note-000000000001", payload=ScenePayload(
        title="Plan du jour", summary="Trois  points\n à voir " + "x" * 900,
        items=tuple(ScenePayloadItem(f"fichier {i}", ref=f"r{i}") for i in range(12))))
    snapshot = _brain(snapshot, "brain-win-000000000001", kind=SceneObjectKind.WINDOW, category="window",
                      representation=Representation.WINDOW, payload=ScenePayload(title="Navigateur"))
    snapshot = _star(snapshot, "claude:task-1", state=ExecState.RUNNING)
    snapshot = _star(snapshot, "claude:task-2", SceneObjectKind.JOB)
    snapshot = _brain(snapshot, "brain-note-000000000002", visibility=Visibility.HIDDEN,
                      payload=ScenePayload(title="Caché"))
    return _applied(snapshot, SceneActor.BRAIN, SceneOp.LINK, relation=SceneRelation(
        "brain-explains-0000000000000001", RelationKind.EXPLAINS, "brain-note-000000000001", "claude:task-1"))


def _board(board_id: str, title: str, status=BoardStatus.ACTIVE) -> Board:
    return Board(board_id=board_id, title=title, created_at=AT, updated_at=AT, status=status)


def _boards() -> tuple[Board, ...]:
    return (_board("default", "Principal"), _board("board_aaa", "Projet A"),
            _board("board_old", "Ancien", BoardStatus.ARCHIVED))


def _state(snapshot: SceneSnapshot | None = None, *, active: str = "default", epoch: str | None = "e1") -> UiState:
    return UiState(scene=_world() if snapshot is None else snapshot, epoch=epoch, boards=_boards(), active_board_id=active)


def _crowd(objects: int, *, relations: bool = True) -> SceneSnapshot:
    snapshot = SceneSnapshot(scene_id="scene-big")
    for index in range(objects):
        snapshot = _brain(snapshot, f"brain-note-{index:012x}", payload=ScenePayload(
            title=f"Note numéro {index} avec un titre assez long pour peser", summary="résumé " * 30))
    if relations:
        for index in range(1, min(objects, 60)):
            snapshot = _applied(snapshot, SceneActor.BRAIN, SceneOp.LINK, relation=SceneRelation(
                f"brain-explains-{index:016x}", RelationKind.EXPLAINS, f"brain-note-{index - 1:012x}", f"brain-note-{index:012x}"))
    return snapshot


# ------------------------------------------------------------------ instantané : contenu


def test_snapshot_reflects_the_canonical_state_reference_and_board():
    state = _state(active="board_aaa")
    data = build_perception(state).data
    assert data["schema"] == "tool_brain.perception/1"
    assert data["state"] == {"scene_id": "scene-1", "epoch": "e1", "revision": state.scene.revision,
                             "active_board_id": "board_aaa"}
    board = data["board"]
    assert board["active"] == "board_aaa" and board["scene_scope"] == "global"
    assert [b["id"] for b in board["items"]] == ["board_aaa", "default"]  # actif d'abord, archivé hors liste
    assert board["archived"] == 1


def test_snapshot_follows_the_scene_revision():
    first = _state()
    second = _state(_brain(first.scene, "brain-note-000000000003", payload=ScenePayload(title="Neuf")))
    one, two = build_perception(first), build_perception(second)
    assert two.data["state"]["revision"] == one.data["state"]["revision"] + 1
    assert one.digest() != two.digest()
    assert "brain-note-000000000003" in {o["id"] for o in two.data["scene"]["objects"]}


def test_snapshot_shows_visible_objects_only_ranked_by_relevance_and_counts_the_hidden():
    data = build_perception(_state()).data
    ids = [o["id"] for o in data["scene"]["objects"]]
    assert "brain-note-000000000002" not in ids  # caché : ni vu ni listé
    assert ids[0] == "claude:task-1"  # nœud en cours d'exécution d'abord
    assert ids.index("brain-win-000000000001") < ids.index("brain-note-000000000001")  # fenêtre avant note
    counts = data["scene"]["counts"]
    assert counts["objects"] == 5 and counts["hidden"] == 1 and counts["by_exec_state"] == {"running": 1}
    assert counts["by_kind"] == {"agent": 1, "artifact": 2, "job": 1, "window": 1}


def test_entries_are_compact_and_omit_defaults_and_bulky_payload():
    objects = {o["id"]: o for o in build_perception(_state()).data["scene"]["objects"]}
    note = objects["brain-note-000000000001"]
    assert note["label"] == "Plan du jour" and note["placed"] is False
    assert len(note["summary"]) <= 80 and "\n" not in note["summary"]
    assert "items" not in note and "geometry" not in note  # la charge se lit par l'inspection ciblée
    assert "state" not in objects["claude:task-2"] and "pinned" not in note


def test_relations_are_kept_only_between_kept_objects():
    data = build_perception(_state()).data
    assert data["scene"]["relations"] == [{"id": "brain-explains-0000000000000001", "kind": "explains",
                                           "from": "brain-note-000000000001", "to": "claude:task-1"}]


def test_empty_scene_snapshot():
    data = build_perception(_state(SceneSnapshot(scene_id="scene-1"))).data
    assert data["scene"]["objects"] == [] and data["scene"]["counts"]["objects"] == 0
    assert data["truncated"] is False and data["omitted"] == {"objects": 0, "relations": 0}


def test_unserved_scene_gives_null_scene_and_is_not_guessed():
    data = build_perception(UiState(scene=None, epoch=None, boards=_boards(), active_board_id="default")).data
    assert data["scene"] is None and data["state"]["scene_id"] is None and data["truncated"] is False


def test_multi_window_multi_agent_world_is_fully_listed_when_small():
    snapshot = SceneSnapshot(scene_id="s")
    for index in range(3):
        snapshot = _brain(snapshot, f"brain-win-{index:012x}", kind=SceneObjectKind.WINDOW, category="window",
                          representation=Representation.WINDOW, payload=ScenePayload(title=f"Fenêtre {index}"))
    for index in range(4):
        snapshot = _star(snapshot, f"claude:t{index}", state=ExecState.RUNNING if index % 2 else ExecState.COMPLETED)
    data = build_perception(_state(snapshot)).data
    assert len(data["scene"]["objects"]) == 7 and data["truncated"] is False


# ------------------------------------------------------------------ bornes et troncature


def test_snapshot_stays_under_the_hard_budget_with_a_huge_scene_and_says_it_is_truncated():
    state = _state(_crowd(400))
    perception = build_perception(state)
    assert perception.size_bytes <= MAX_PERCEPTION_BYTES
    assert len(perception.serialize().encode("utf-8")) == perception.size_bytes
    data = perception.data
    assert data["truncated"] is True and perception.truncated
    kept = len(data["scene"]["objects"])
    assert 0 < kept < 400 and data["omitted"]["objects"] == 400 - kept
    assert data["scene"]["counts"]["objects"] == 400  # le total reste dit même quand on tronque


def test_truncation_is_a_ranked_prefix_and_relations_only_touch_kept_objects():
    snapshot = _crowd(300)
    snapshot = _star(snapshot, "claude:late", state=ExecState.BLOCKED)  # id « tardif » mais pertinent
    data = build_perception(_state(snapshot)).data
    ids = [o["id"] for o in data["scene"]["objects"]]
    assert ids[0] == "claude:late"
    kept = set(ids)
    assert all(r["from"] in kept and r["to"] in kept for r in data["scene"]["relations"])
    assert data["omitted"]["relations"] == len(snapshot.relations) - len(data["scene"]["relations"])


def test_smaller_budget_gives_smaller_output_and_a_too_small_one_fails_loudly():
    state = _state(_crowd(80))
    small = build_perception(state, max_bytes=3000)
    assert small.size_bytes <= 3000 and small.truncated
    assert small.size_bytes < build_perception(state).size_bytes
    with pytest.raises(ValueError, match="skeleton"):
        build_perception(state, max_bytes=100)


def test_an_oversized_wired_section_is_a_loud_error_never_a_silent_overflow():
    huge = SpeechSection("wired", {"text": "x" * (MAX_PERCEPTION_BYTES * 2)})
    with pytest.raises(ValueError):
        build_perception(_state(), speech=huge)


def test_many_boards_are_bounded_and_counted():
    boards = tuple(_board(f"board_{i:03d}", f"Board {i}") for i in range(30))
    state = UiState(scene=_world(), epoch="e1", boards=boards, active_board_id="board_020")
    board = build_perception(state).data["board"]
    assert len(board["items"]) == 8 and board["items"][0]["id"] == "board_020" and board["more"] == 22


# ------------------------------------------------------------------ déterminisme et rejeu


def test_same_state_gives_the_same_bytes_and_digest_and_valid_sorted_json():
    one, two = build_perception(_state()), build_perception(_state())
    assert one.serialize() == two.serialize() and one.digest() == two.digest()
    decoded = json.loads(one.serialize())
    assert decoded == json.loads(json.dumps(one.data))
    assert one.serialize() == json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_object_insertion_order_does_not_change_the_snapshot():
    forward = SceneSnapshot(scene_id="s")
    backward = SceneSnapshot(scene_id="s")
    names = [f"brain-note-{i:012x}" for i in range(6)]
    for name in names:
        forward = _brain(forward, name, payload=ScenePayload(title=name))
    for name in reversed(names):
        backward = _brain(backward, name, payload=ScenePayload(title=name))
    one, two = (build_perception(_state(s)).data for s in (forward, backward))
    # Les révisions diffèrent selon le nombre de commandes : même nombre ici, donc comparables.
    assert one["scene"] == two["scene"]


def test_ids_are_stable_while_the_object_lives():
    state = _state()
    moved = _applied(state.scene, SceneActor.BRAIN, SceneOp.SET_GEOMETRY, object_id="brain-note-000000000001",
                     geometry=SceneGeometry(10, 10, 200, 120))
    before = {o["id"] for o in build_perception(state).data["scene"]["objects"]}
    after = {o["id"] for o in build_perception(_state(moved)).data["scene"]["objects"]}
    assert before == after


# ------------------------------------------------------------------ coutures vides


def test_speech_and_queue_seams_are_typed_and_empty_and_surfaces_follow_the_scene():
    data = build_perception(_state()).data
    assert data["speech"] == {"status": "not_wired"}
    assert data["queue"] == {"status": "not_wired", "count": 0, "items": []}
    # S7 : `surfaces` est dérivé de la scène (fenêtres `jarvis.browser`), aucune ici ; scène non servie : indisponible.
    assert data["surfaces"] == {"status": "available", "total": 0, "truncated": False, "items": []}
    unserved = build_perception(UiState(scene=None, epoch=None, boards=(), active_board_id=None)).data
    assert unserved["surfaces"]["status"] == "unavailable" and unserved["surfaces"]["items"] == []


def test_perception_lists_open_browser_surfaces_without_page_content_and_within_the_cap():
    from jarvis.domain.browser_surface import plan_open
    from jarvis.runtime.tool_brain_perception import MAX_PERCEPTION_SURFACES

    snapshot = _world()
    for number in range(MAX_PERCEPTION_SURFACES + 2):
        update = apply_scene_command(snapshot, plan_open(snapshot, f"https://example.com/{number}",
                                                         new_opaque=f"{number:012d}", note="secret page notes"))
        snapshot = update.snapshot
    surfaces = build_perception(_state(snapshot)).data["surfaces"]
    assert surfaces["status"] == "available" and surfaces["total"] == MAX_PERCEPTION_SURFACES + 2
    assert surfaces["truncated"] is True and len(surfaces["items"]) == MAX_PERCEPTION_SURFACES
    first = surfaces["items"][0]
    assert first["surface_id"].startswith("surf_") and first["host"] == "example.com" and first["pages"] == 1
    assert "secret page notes" not in json.dumps(surfaces)


def test_a_wired_speech_section_is_carried_verbatim_inside_the_budget():
    speech = SpeechSection("wired", {"current": "K1", "played_ms": 1200})
    data = build_perception(_state(), speech=speech).data
    assert data["speech"] == {"status": "wired", "data": {"current": "K1", "played_ms": 1200}}


def test_queue_placeholder_is_empty_until_s6():
    assert get_queue_state() == {"schema": "tool_brain.inspection/1", "ok": True, "kind": "queue",
                                 "status": "not_wired", "count": 0, "items": []}
    wired = get_queue_state(QueueSection("wired", ({"id": "a1"},)))
    assert wired["count"] == 1 and wired["status"] == "wired"


# ------------------------------------------------------------------ lectures ciblées


def test_get_information_on_returns_more_than_the_snapshot_entry_for_the_same_id():
    state = _state()
    entry = next(o for o in build_perception(state).data["scene"]["objects"] if o["id"] == "brain-note-000000000001")
    result = get_information_on(state, "brain-note-000000000001")
    assert result["ok"] and result["kind"] == "object"
    info = result["info"]
    assert set(entry) <= set(info) and len(info) > len(entry)
    assert info["id"] == entry["id"] and info["label"] == entry["label"]
    assert len(info["summary"]) == 600 and info["summary_truncated"] is True
    assert len(info["items"]) == 8 and info["items_total"] == 12
    assert info["related_count"] == 1 and info["origin"] == "brain"


def test_get_information_on_reads_hidden_objects_relations_and_boards():
    state = _state()
    assert get_information_on(state, "brain-note-000000000002")["info"]["visibility"] == "hidden"
    relation = get_information_on(state, "brain-explains-0000000000000001")
    assert relation["kind"] == "relation" and relation["info"]["removable"] is True
    board = get_information_on(state, "board_aaa")
    assert board["kind"] == "board" and board["info"]["status"] == "active" and board["info"]["active"] is False
    assert get_information_on(state, "default")["info"]["active"] is True
    assert get_information_on(state, "board_old")["info"]["status"] == "archived"


def test_unknown_archived_and_malformed_ids_fail_cleanly():
    state = _state()
    unknown = get_information_on(state, "brain-note-ffffffffffff")
    assert unknown["ok"] is False and unknown["code"] == "unknown_id"
    assert get_information_on(state, "")["code"] == "unknown_id"
    gone = _applied(state.scene, SceneActor.BRAIN, SceneOp.ARCHIVE, object_id="brain-note-000000000002")
    archived = get_information_on(_state(gone), "brain-note-000000000002")
    assert archived["ok"] is False and archived["code"] == "object_archived"
    blind = get_information_on(UiState(None, None, _boards(), "default"), "brain-note-000000000001")
    assert blind["code"] == "scene_unavailable"
    assert get_information_on(UiState(None, None, _boards(), "default"), "board_aaa")["ok"] is True
    assert len(get_information_on(state, "x" * 500)["id"]) <= 80


def test_every_snapshot_id_is_inspectable():
    state = _state()
    inspectable = set(inspectable_ids(state))
    for entry in build_perception(state).data["scene"]["objects"]:
        assert entry["id"] in inspectable and get_information_on(state, entry["id"])["ok"]
    for board in build_perception(state).data["board"]["items"]:
        assert get_information_on(state, board["id"])["ok"]


def test_list_related_both_directions_and_clean_failures():
    state = _state()
    out = list_related(state, "brain-note-000000000001")
    assert out["ok"] and out["total"] == 1 and out["items"][0]["direction"] == "out"
    assert out["items"][0]["id"] == "claude:task-1" and out["items"][0]["kind"] == "explains"
    incoming = list_related(state, "claude:task-1")["items"][0]
    assert incoming["direction"] == "in" and incoming["id"] == "brain-note-000000000001"
    assert list_related(state, "claude:task-2")["items"] == []
    assert list_related(state, "board_aaa")["ok"] is False
    assert list_related(state, "nope")["code"] == "unknown_id"


def test_list_related_is_bounded():
    snapshot = SceneSnapshot(scene_id="s")
    snapshot = _brain(snapshot, "brain-note-hub", payload=ScenePayload(title="hub"))
    for index in range(40):
        snapshot = _brain(snapshot, f"brain-note-{index:012x}")
        snapshot = _applied(snapshot, SceneActor.BRAIN, SceneOp.LINK, relation=SceneRelation(
            f"brain-explains-{index:016x}", RelationKind.EXPLAINS, "brain-note-hub", f"brain-note-{index:012x}"))
    out = list_related(_state(snapshot), "brain-note-hub")
    assert out["total"] == 40 and out["truncated"] is True and len(out["items"]) == 24


def test_available_actions_come_from_the_catalog_and_agree_with_the_validator(catalog):
    state = _state()
    out = get_available_actions(catalog, state, "brain-note-000000000001")
    tools = {(row["tool"], row["parameter"]) for row in out["items"]}
    assert ("scene_move", "object_ids") in tools and ("scene_archive", "object_ids") in tools
    assert ("scene_link", "from_id") in tools
    assert not any(t.startswith("board_") for t, _ in tools)
    archive = next(r for r in out["items"] if r["tool"] == "scene_archive")
    assert archive["reversibility"] == "irreversible" and archive["side_effect"] == "destructive"
    assert out["items"] == sorted(out["items"], key=lambda r: (r["tool"], r["parameter"]))


def test_available_actions_for_boards_relations_and_unknown_ids(catalog):
    state = _state()
    board_tools = {(r["tool"]) for r in get_available_actions(catalog, state, "board_aaa")["items"]}
    assert {"board_switch", "board_get"} <= board_tools
    archived_tools = {r["tool"] for r in get_available_actions(catalog, state, "board_old")["items"]}
    assert "board_switch" not in archived_tools and "board_get" in archived_tools
    relation = get_available_actions(catalog, state, "brain-explains-0000000000000001")
    assert {r["tool"] for r in relation["items"]} == {"scene_unlink"}
    assert get_available_actions(catalog, state, "nope")["ok"] is False


def test_inspection_read_names_are_the_ones_documented():
    assert INSPECTION_READS == ("get_information_on", "list_related", "get_available_actions", "get_queue_state")


# ------------------------------------------------------------------ lecture chez les propriétaires


class _Scene:
    def __init__(self, snapshot, *, down=False):
        self._snapshot, self._down, self.epoch = snapshot, down, "e9"

    async def snapshot(self):
        if self._down:
            raise SceneUnavailableError(SceneStoreErrorCode.UNAVAILABLE, "down")
        return self._snapshot


class _Boards:
    async def list(self, *, include_archived=False):
        return _boards()

    async def active_board_id(self):
        return "board_aaa"


def test_perceive_reads_the_canonical_owners_through_read_ui_state():
    perception = asyncio.run(perceive(_Scene(_world()), _Boards()))
    assert perception.data["state"] == {"scene_id": "scene-1", "epoch": "e9", "revision": _world().revision,
                                        "active_board_id": "board_aaa"}
    assert perception.data == build_perception(asyncio.run(_read())).data


async def _read():
    from jarvis.runtime.tool_brain_choices import read_ui_state
    return await read_ui_state(_Scene(_world()), _Boards())


def test_perceive_with_an_unserved_scene_yields_a_null_scene_not_an_exception():
    perception = asyncio.run(perceive(_Scene(None, down=True), _Boards()))
    assert perception.data["scene"] is None
