"""Export after an edit (presentation-edition-v1, Slice 09): the edited deck is exported from Core's canonical state, never from a page.

Real world (`tests/fakes/presentation_world.py`: real Studio store, prefab library, packager, artifact service) and the real semantic edit
service (the same door as the editor and the voice); only the render PROCESS is the fake runner of the other render tests. Proved:

- a committed edit is what the next frozen copy and its whole-video render carry (the props of the package);
- the copy frozen BEFORE the edit keeps the old value (an export is a frozen copy, not a link to the live deck);
- after the export the live variant still holds the edit and reopens with it (nothing is written back from an export);
- an undo after the export changes the live variant only, never the exported copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_edit import PresentationStudioEditService
from jarvis.core.presentation_studio_service import PresentationStudioService
from tests.fakes.presentation_world import SCENE_ID
from tests.unit.test_presentation_render_master import deck, finished, rig  # noqa: F401 - `rig` is the shared fixture

pytestmark = pytest.mark.asyncio

#: The control the editor shows for the title (declared by the same edit, the way an authored scene declares its controls).
TITLE = {"control_id": "title", "path": "props.title", "label": "Titre", "group": "content", "meaning": "Le titre de la scène."}


async def _edit(service, world, pid, vid, title: str) -> dict:
    variant = next(v for v in (await world.studio.get(pid)).variants if v.variant_id == vid).to_document()
    result = await service.edit(pid, vid, {"actor": "user", "mode": "commit", "basis": {"variant_revision": variant["revision"]},
                                           "ops": [{"op": "scene.set_controls", "scene_id": SCENE_ID, "controls": [TITLE]},
                                                   {"op": "control.set", "scene_id": SCENE_ID, "control_id": "title", "value": title}]})
    assert result.status.value == "applied", result
    return result


def _package_text(rig, job_id: str) -> str:
    return "\n".join(v.decode("utf-8", "replace") for k, v in rig.runner.files[job_id].items() if k.endswith((".json", ".tsx", ".ts")))


def _carries(text: str, title: str) -> bool:
    """The props are written into the generated master as `JSON.parse("<json>")` (an ASCII title reads as is)."""
    return title in text


async def test_an_edited_deck_exports_its_edit_and_reopens_from_the_canonical_state(rig):  # noqa: F811
    world = rig.world
    pid, vid, before = await deck(rig)
    # Core wires the Studio with the prefab catalogue (the edit API reads the pins' manifests there): the same store, wired the same way.
    edits = PresentationStudioEditService(PresentationStudioService(FilePresentationStudioStore(world.root / "studio"), prefabs=world.prefabs))
    await _edit(edits, world, pid, vid, "Titre S09 apres edition")
    after = (await world.freeze(pid, vid))["artifact_id"]
    assert after != before, "the edit makes a new frozen copy"

    old = await finished(rig.service, (await rig.service.submit(before, "mp4", {"scope": "master"}))["job_id"])
    new = await finished(rig.service, (await rig.service.submit(after, "mp4", {"scope": "master"}))["job_id"])
    assert old["state"] == new["state"] == "complete", (old, new)
    assert _carries(_package_text(rig, new["job_id"]), "Titre S09 apres edition"), "the export carries the committed edit"
    assert not _carries(_package_text(rig, old["job_id"]), "Titre S09 apres edition"), "a copy frozen before the edit keeps its old value"

    # Reopened from Core: the live variant still holds the edit; nothing came back from the export.
    live = next(v for v in (await world.studio.get(pid)).variants if v.variant_id == vid).to_document()
    scene = next(s for s in live["scenes"] if s["scene_id"] == SCENE_ID)
    assert scene["props"]["title"] == "Titre S09 apres edition"

    # An undo-like change after the export moves the live variant only; the exported Artifact's bytes stay.
    exported = await world.artifacts.get(new["artifact_id"])
    payload_before = Path(world.artifacts.payload_path(exported)).read_bytes()
    await _edit(edits, world, pid, vid, "Un")
    assert Path(world.artifacts.payload_path(await world.artifacts.get(new["artifact_id"]))).read_bytes() == payload_before


async def test_a_branch_made_by_new_variant_exports_like_the_active_one(rig):  # noqa: F811
    """« Nouvelle variante… » records its lineage (`sources`) in the live index; the frozen copy holds one variant only, so it must not
    carry that lineage (the package check refused every such export: `source psv_… is not a variant of this presentation`, Slice 09 QA)."""

    from jarvis.core.presentation_studio_variants import PresentationStudioVariants

    world = rig.world
    pid, vid, _ = await deck(rig, freeze=False)
    variants = PresentationStudioVariants(world.studio)
    branch = (await variants.create_branch(pid, {"title": "Autre piste", "source_variant_id": vid}))["node"]
    view = await world.studio.get(pid)
    entry = next(e for e in view.presentation.to_document()["variants"] if e["variant_id"] == branch["variant_id"])
    assert entry["sources"] == [vid], "the live index keeps the lineage"
    live = next(v for v in view.variants if v.variant_id == branch["variant_id"])
    frozen = await world.packager.freeze(pid, live.variant_id, expected_presentation_revision=view.presentation.revision,
                                         expected_variant_revision=live.revision, authorised_boards=frozenset({"default"}))
    package = await world.packager.read_snapshot(frozen["artifact_id"])
    import json
    doc = json.loads(package.files["presentation/presentation.json"])
    assert [(e["variant_id"], e["sources"]) for e in doc["variants"]] == [(live.variant_id, [])]
    done = await finished(rig.service, (await rig.service.submit(frozen["artifact_id"], "mp4", {"scope": "master"}))["job_id"])
    assert done["state"] == "complete", done
