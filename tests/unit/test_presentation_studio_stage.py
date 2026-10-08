"""Stage window, auxiliary windows and the id-list ledger (Slice 12), against a real `SceneService` and the real file ledger.

Proved: one window created then patched (a payload already shown writes nothing), an aux window hidden at birth, archive by id
only (a look-alike object of the brain survives), a ledger that is ids and nothing else, an unreadable / foreign ledger that is
an error row rather than "nothing to do", overflow said loudly, the file adapter's atomic write and its invisibility to the
store listing, and the leak-then-reclaim paths of the service (a failed retire is taken back at the next start).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_stage_ledger import LEDGER_FILE, SCHEMA, FileStageLedger
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.adapters.sqlite_scene import SQLiteSceneRepository
from jarvis.core.presentation_studio_stage import MAX_LEDGER_IDS, SceneStage, StageError, StageLedger
from jarvis.core.scene_service import SceneService
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, ScenePrefabRef,
)
from tests.unit.test_presentation_studio_playback_service import AUX_BLOCK, MemoryLedgerStore, Rig, applied
from tests.unit.test_presentation_studio_scene_service import Sink


def payload(title: str, label: str = "x") -> ScenePayload:
    return ScenePayload(title=title, prefab=ScenePrefabRef("lab.counter", 1, {"label": label}, {"count": 1}))


@pytest.fixture
async def stage_rig(tmp_path):
    rig = await Rig(tmp_path).open()
    yield rig
    await rig.close()


# ------------------------------------------------------------------ the stage window

async def test_show_creates_once_then_patches_and_an_identical_payload_writes_nothing(stage_rig):
    stage = stage_rig.stage
    stage.begin("rx")
    assert await stage.show(payload("Un")) is True
    first = stage.stage_object_id
    revision = (await stage_rig.scene.snapshot()).revision
    assert await stage.show(payload("Un")) is False                 # nothing to write: the frame's own state survives
    assert (await stage_rig.scene.snapshot()).revision == revision
    assert await stage.show(payload("Deux", "y")) is True
    assert stage.stage_object_id == first == "studio-stage-rx"
    assert [o.payload.title for o in await stage_rig.objects("presentation_studio_stage")] == ["Deux"]
    await stage.release()
    assert stage.stage_object_id is None and await stage_rig.stage_object() is None


async def test_show_without_a_run_is_a_coded_error(stage_rig):
    with pytest.raises(StageError) as caught:
        await stage_rig.stage.show(payload("Un"))
    assert caught.value.code == "stage_not_begun"


async def test_a_payload_the_scene_refuses_is_the_scenes_own_reason(stage_rig):
    stage_rig.stage.begin("rx")
    bad = ScenePayload(title="x", prefab=ScenePrefabRef("lab.nothing", 1, {}, {}))
    with pytest.raises(StageError) as caught:
        await stage_rig.stage.show(bad)
    assert caught.value.code == "prefab_invalid" and "lab.nothing" in caught.value.message
    assert stage_rig.stage.stage_object_id is None and stage_rig.stage_ledger.ids == ()


async def test_an_aux_window_is_hidden_at_birth_revealed_and_archived_by_id_only(stage_rig):
    stage = stage_rig.stage
    stage.begin("rx")
    object_id = await stage.stage_aux("a1", "Annexe", ScenePrefabRef("lab.counter", 1, {"label": "A"}, {"count": 1}))
    [aux] = await stage_rig.objects("presentation_studio_aux")
    assert aux.visibility.value == "hidden"                         # never visible between create and reveal
    await stage.reveal_aux(object_id)
    assert (await stage_rig.objects("presentation_studio_aux"))[0].visibility.value == "visible"
    # an object of the same shape that the brain made is NOT ours: the id list cannot reach it
    await stage_rig.scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id="brain-look-alike",
                                             fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category="presentation_studio_aux",
                                                                      payload=payload("Brain"), representation=Representation.WINDOW)))
    await stage.retire([object_id])
    assert [o.object_id for o in await stage_rig.objects("presentation_studio_aux")] == ["brain-look-alike"]
    assert stage_rig.stage_ledger.ids == ()


async def test_retiring_an_object_that_is_already_gone_is_not_a_failure(stage_rig):
    stage = stage_rig.stage
    stage.begin("rx")
    object_id = await stage.stage_aux("a1", "Annexe", ScenePrefabRef("lab.counter", 1, {"label": "A"}, {"count": 1}))
    await stage.retire([object_id])
    await stage.retire([object_id])                                 # the user (or an earlier try) already removed it
    await stage.retire(["never-existed"])
    assert stage_rig.stage_ledger.ids == ()


# ------------------------------------------------------------------ the ledger

def test_the_ledger_holds_ids_only_is_bounded_and_says_when_it_overflows():
    sink = Sink()
    store = MemoryLedgerStore()
    ledger = StageLedger(store, diagnostics=sink)
    for index in range(MAX_LEDGER_IDS + 3):
        ledger.add(f"studio-aux-r-{index}")
    assert len(ledger.ids) == MAX_LEDGER_IDS and ledger.ids[-1] == f"studio-aux-r-{MAX_LEDGER_IDS + 2}"
    [(level, data)] = sink.of("core.presentation_studio.stage_ledger_overflow")[-1:]
    assert level == "error" and data["dropped"] == 1
    ledger.remove([f"studio-aux-r-{index}" for index in range(MAX_LEDGER_IDS + 3)])
    assert ledger.ids == () and store.ids is None                   # empty -> erased, not an empty file


def test_an_unreadable_ledger_is_an_error_row_not_nothing_to_do():
    class Broken(MemoryLedgerStore):
        def read(self):
            raise ValueError("not a stage ledger")

        def write(self, ids):
            raise OSError("disk full")

    sink = Sink()
    ledger = StageLedger(Broken(), diagnostics=sink)
    assert ledger.load() == ()
    assert sink.of("core.presentation_studio.stage_ledger_unreadable")[0][0] == "error"
    ledger.add("studio-stage-r")                                     # the run goes on, the leak risk is said
    assert sink.of("core.presentation_studio.stage_ledger_unwritable")[0][1]["ids"] == 1
    assert ledger.ids == ("studio-stage-r",)


# ------------------------------------------------------------------ the file adapter

def test_the_file_ledger_round_trips_atomically_beside_the_scene_database_not_in_the_presentations_tree(tmp_path):
    ledger = FileStageLedger(tmp_path)
    assert ledger.read() is None                                     # first run: no ledger, not an error
    ledger.write(["studio-stage-r1", "studio-aux-r1-a1"])
    path = tmp_path / "state" / LEDGER_FILE
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema": SCHEMA, "object_ids": ["studio-stage-r1", "studio-aux-r1-a1"]}
    assert ledger.read() == ["studio-stage-r1", "studio-aux-r1-a1"]
    assert [p.name for p in (tmp_path / "state").iterdir()] == [LEDGER_FILE], "no temporary left behind"
    assert not (tmp_path / "presentations").exists(), "never inside the Presentations tree (backup / move)"
    scan = FilePresentationStudioStore(tmp_path).scan()
    assert scan.presentation_ids == () and scan.problems == ()
    ledger.erase()
    ledger.erase()                                                   # erasing what is gone is the goal
    assert ledger.read() is None


@pytest.mark.parametrize("content", ["not json", '{"schema":"other","object_ids":[]}', '{"schema":"%s","object_ids":"x"}' % SCHEMA, "[]"])
def test_a_foreign_or_corrupt_ledger_raises_instead_of_reading_as_empty(tmp_path, content):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / LEDGER_FILE).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        FileStageLedger(tmp_path).read()


# ------------------------------------------------------------------ leak, then reclaim

async def test_a_retire_that_failed_leaves_the_id_in_the_ledger_and_the_next_run_takes_it_back(tmp_path):
    rig = await Rig(tmp_path).open()
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("detour", title="Annexe", prefab=AUX_BLOCK))
    [aux] = await rig.objects("presentation_studio_aux")
    real_retire = rig.stage.retire

    async def failing(ids):
        raise StageError("scene_unavailable", "the scene store is down")

    rig.stage.retire = failing
    result = await rig.run("stop")
    assert result.status.value == "stage_failed" and result.reason == "aux_retire_failed" and "store is down" in result.message
    assert rig.service.where()["phase"] == "stopped" and rig.service.where()["last_run"]["problems"] == ["aux_retire_failed"]
    assert aux.object_id in rig.stage_ledger.ids                      # kept: it can still be taken back
    rig.stage.retire = real_retire
    rig.build()
    applied(await rig.service.start(rig.start_body()))                # the next run reclaims the leftovers first
    assert [o.object_id for o in await rig.objects("presentation_studio_aux")] == []
    assert aux.object_id not in rig.stage_ledger.ids
    await rig.close()
