"""The retired run stage: one last reclaim of what an older Core left (native-studio-playback-fix Slice 09), against a real
`SceneService` and the real file ledger.

Since Slice 09 a run never writes a Board object (it plays inside Variants, `test_presentation_studio_run_surface.py`). Proved here:
the Board windows of the retired floating viewer (`studio_stage` / `studio_aux`) are archived by id list (old ledger) AND by a scan
of the retired categories whatever the id (Slice 09 rework: an object of a retired category is never drawn and refused to the Tool
Brain, so it would be an unreachable orphan; our id prefix on another category survives), an id already gone is not a failure, the
old ledger is read once and then kept aside (never deleted, never rewritten; an empty id list included), an unreadable ledger is an
error row kept aside and the scan still runs, a scene that refuses the archive is said and never blocks a run.
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

async def test_reclaim_archives_ledger_ids_and_every_retired_category_object_and_spares_other_categories(rig):
    await window(rig.scene, "studio-stage-r1", "studio_stage")
    await window(rig.scene, "studio-stage-r2-1", "studio_stage")                 # a reopened generation, not in the ledger
    await window(rig.scene, "studio-aux-r1-a1", "studio_aux")
    await window(rig.scene, "brain-look-alike", "studio_aux", SceneActor.BRAIN)  # retired category, another id: an orphan, archived
    await window(rig.scene, "stage-without-prefix", "studio_stage")              # the same for the stage category
    await window(rig.scene, "studio-stage-note", "note")                         # our prefix, another category: not ours, survives
    store = MemoryLedgerStore(["studio-stage-r1", "studio-aux-r1-a1", "studio-stage-gone"])
    reclaimer = LegacyStageReclaimer(rig.scene, StageLedger(store, diagnostics=rig.env.sink), diagnostics=rig.env.sink)
    taken = await reclaimer.reclaim()
    assert set(taken) == {"studio-stage-r1", "studio-stage-r2-1", "studio-aux-r1-a1", "brain-look-alike",
                          "stage-without-prefix"}                                   # the unknown id is already gone
    assert {o.object_id for o in await rig.objects()} == {"studio-stage-note"}
    assert store.ids is None and store.retired == ["studio-stage-r1", "studio-aux-r1-a1", "studio-stage-gone"]
    [(level, data)] = rig.env.sink.of("core.presentation_studio.legacy_stage_reclaimed")
    assert level == "warning" and data == {"count": 5, "from_ledger": 3}
    assert await reclaimer.reclaim() == ()                                        # nothing left: a second pass writes nothing


async def test_an_orphan_of_a_retired_category_is_archived_not_deleted_and_the_brain_still_cannot_touch_it(rig):
    """Slice 09 rework, the safer of the two choices: a `studio_aux` object without the `studio-aux-` prefix is archived (reversible,
    the scene keeps it), rather than handed to the Tool Brain (which keeps refusing the retired categories as `studio_owned`)."""

    from jarvis.runtime.tool_brain_executor import studio_owned_targets
    from jarvis.domain.scene_selection import SceneSelection

    await window(rig.scene, "old-brain-aux", "studio_aux", SceneActor.BRAIN)
    snapshot = await rig.scene.snapshot()
    touch = SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.BRAIN, selection=SceneSelection(ids=("old-brain-aux",)))
    assert studio_owned_targets(snapshot, touch) == ["old-brain-aux"], "the Tool Brain still refuses it"
    taken = await LegacyStageReclaimer(rig.scene, StageLedger(MemoryLedgerStore())).reclaim()
    assert taken == ("old-brain-aux",)
    after = await rig.scene.snapshot()
    assert "old-brain-aux" in after.archived_ids and after.get_object("old-brain-aux") is None, "archived, never deleted"


async def test_a_ledger_whose_id_list_is_empty_is_set_aside_all_the_same(rig, tmp_path):
    store = MemoryLedgerStore([])
    taken = await LegacyStageReclaimer(rig.scene, StageLedger(store, diagnostics=rig.env.sink), diagnostics=rig.env.sink).reclaim()
    assert taken == () and store.ids is None and store.retired == [], "an existing ledger is retired even when it lists nothing"
    assert rig.env.sink.of("core.presentation_studio.stage_ledger_retired")[0][1] == {"file": "ledger.retired"}
    # The real file adapter: an empty list on disk becomes `.retired-<time>`, kept byte for byte.
    (tmp_path / "state").mkdir(exist_ok=True)
    path = tmp_path / "state" / LEDGER_FILE
    text = json.dumps({"schema": SCHEMA, "object_ids": []})
    path.write_text(text, encoding="utf-8")
    await LegacyStageReclaimer(rig.scene, StageLedger(FileStageLedger(tmp_path))).reclaim()
    kept = [p for p in (tmp_path / "state").iterdir() if p.name.startswith(LEDGER_FILE + ".retired-")]
    assert not path.exists() and len(kept) == 1 and kept[0].read_text(encoding="utf-8") == text


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
