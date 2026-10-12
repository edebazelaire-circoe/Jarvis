"""The retired run stage: one last reclaim of what an older Core left (native-studio-playback-fix Slice 09), against a real
`SceneService` and the real file ledger.

Since Slice 09 a run never writes a Board object (it plays inside Variants, `test_presentation_studio_run_surface.py`). Proved here:
the Board windows of the retired floating viewer (`studio_stage` / `studio_aux`) are archived by id list (old ledger) AND by a
namespaced scan (category and id prefix: a brain object of the same category but another id survives), an id already gone is not
a failure, the old ledger is read once and then kept aside (never deleted, never rewritten), an unreadable ledger is an error row
kept aside and the scan still runs, a scene that refuses the archive is said and never blocks a run.
"""

from __future__ import annotations

import json

import pytest

from jarvis.adapters.file_presentation_studio_stage_ledger import LEDGER_FILE, SCHEMA, FileStageLedger
from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_stage import LEGACY_CATEGORIES, LegacyStageReclaimer, StageError, StageLedger
from jarvis.domain.scene import (
    Representation, SceneActor, SceneCommand, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload, ScenePrefabRef,
)
from tests.unit.test_presentation_studio_playback_service import MemoryLedgerStore, Rig, applied
from tests.unit.test_presentation_studio_scene_service import Sink


async def window(scene, object_id: str, category: str, actor: SceneActor = SceneActor.USER) -> None:
    await scene.apply(SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=actor, object_id=object_id,
                                   fields=SceneObjectFields(kind=SceneObjectKind.WINDOW, category=category,
                                                            payload=ScenePayload(title=object_id, prefab=ScenePrefabRef(
                                                                "lab.counter", 1, {"label": "x"}, {"count": 1})),
                                                            representation=Representation.WINDOW)))


@pytest.fixture
async def rig(tmp_path):
    made = await Rig(tmp_path).open()
    yield made
    await made.close()


def test_the_retired_categories_are_the_two_of_the_floating_viewer():
    assert LEGACY_CATEGORIES == {"studio_stage", "studio_aux"}


# ------------------------------------------------------------------ the reclaim

async def test_reclaim_archives_ledger_ids_and_namespaced_leftovers_and_spares_look_alikes(rig):
    await window(rig.scene, "studio-stage-r1", "studio_stage")
    await window(rig.scene, "studio-stage-r2-1", "studio_stage")                 # a reopened generation, not in the ledger
    await window(rig.scene, "studio-aux-r1-a1", "studio_aux")
    await window(rig.scene, "brain-look-alike", "studio_aux", SceneActor.BRAIN)  # same category, not our id: survives
    await window(rig.scene, "studio-stage-note", "note")                         # our prefix, another category: survives
    store = MemoryLedgerStore(["studio-stage-r1", "studio-aux-r1-a1", "studio-stage-gone"])
    reclaimer = LegacyStageReclaimer(rig.scene, StageLedger(store, diagnostics=rig.env.sink), diagnostics=rig.env.sink)
    taken = await reclaimer.reclaim()
    assert set(taken) == {"studio-stage-r1", "studio-stage-r2-1", "studio-aux-r1-a1"}   # the unknown id is already gone
    assert {o.object_id for o in await rig.objects()} == {"brain-look-alike", "studio-stage-note"}
    assert store.ids is None and store.retired == ["studio-stage-r1", "studio-aux-r1-a1", "studio-stage-gone"]
    [(level, data)] = rig.env.sink.of("core.presentation_studio.legacy_stage_reclaimed")
    assert level == "warning" and data == {"count": 3, "from_ledger": 3}
    assert await reclaimer.reclaim() == ()                                        # nothing left: a second pass writes nothing


async def test_reclaim_with_nothing_to_take_back_writes_nothing(rig):
    revision = (await rig.scene.snapshot()).revision
    reclaimer = LegacyStageReclaimer(rig.scene, StageLedger(MemoryLedgerStore()), diagnostics=rig.env.sink)
    assert await reclaimer.reclaim() == ()
    assert (await rig.scene.snapshot()).revision == revision and rig.env.sink.of("core.presentation_studio.legacy_stage_reclaimed") == []


async def test_a_scene_that_refuses_the_archive_is_said_and_never_blocks_a_run(rig):
    await window(rig.scene, "studio-stage-r1", "studio_stage")

    class Refusing:
        def __init__(self, scene):
            self._scene = scene

        async def apply_if(self, plan):
            raise ValueError("scene store refused")

    reclaimer = LegacyStageReclaimer(Refusing(rig.scene), StageLedger(MemoryLedgerStore()))
    with pytest.raises(StageError) as caught:
        await reclaimer.reclaim()
    assert caught.value.code == "stage_invalid"
    rig.stage._reclaimer = reclaimer
    await rig.service.start_service()                                             # Core starts regardless: an error row
    assert rig.env.sink.of("core.presentation_studio.playback_reclaim_failed")[0][0] == "error"
    applied(await rig.service.start(rig.start_body()))                            # and a run still starts (on the surface)
    assert rig.service.where()["stage_object_id"].startswith("variants-run-")


def test_an_unreadable_ledger_is_an_error_row_kept_aside_not_nothing_to_do():
    class Broken(MemoryLedgerStore):
        def read(self):
            raise ValueError("not a stage ledger")

        def quarantine(self):
            return "ledger.corrupt-1"

    sink = Sink()
    ledger = StageLedger(Broken(), diagnostics=sink)
    assert ledger.load() == ()
    assert sink.of("core.presentation_studio.stage_ledger_unreadable")[0][0] == "error"
    assert sink.of("core.presentation_studio.stage_ledger_quarantined")[0][1] == {"file": "ledger.corrupt-1"}


# ------------------------------------------------------------------ the file adapter (read once, then kept aside)

def test_the_file_ledger_is_read_then_kept_aside_beside_the_scene_database_never_deleted(tmp_path):
    ledger = FileStageLedger(tmp_path)
    assert ledger.read() is None and ledger.retire() is None                     # no ledger: the normal state, not an error
    (tmp_path / "state").mkdir()
    path = tmp_path / "state" / LEDGER_FILE
    text = json.dumps({"schema": SCHEMA, "object_ids": ["studio-stage-r1", "studio-aux-r1-a1"]})
    path.write_text(text, encoding="utf-8")
    assert ledger.read() == ["studio-stage-r1", "studio-aux-r1-a1"]
    name = ledger.retire()
    assert name.startswith(LEDGER_FILE + ".retired-") and not path.exists()
    assert (tmp_path / "state" / name).read_text(encoding="utf-8") == text        # kept as it was, byte for byte
    assert ledger.read() is None
    assert not (tmp_path / "presentations").exists(), "never inside the Presentations tree (backup / move)"
    scan = FilePresentationStudioStore(tmp_path).scan()
    assert scan.presentation_ids == () and scan.problems == ()


@pytest.mark.parametrize("content", ["not json", '{"schema":"other","object_ids":[]}', '{"schema":"%s","object_ids":"x"}' % SCHEMA, "[]"])
def test_a_foreign_or_corrupt_ledger_raises_instead_of_reading_as_empty(tmp_path, content):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / LEDGER_FILE).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        FileStageLedger(tmp_path).read()
    kept = FileStageLedger(tmp_path).quarantine()
    assert kept.startswith(LEDGER_FILE + ".corrupt-") and (tmp_path / "state" / kept).read_text(encoding="utf-8") == content
