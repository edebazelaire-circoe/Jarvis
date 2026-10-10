"""Persisted engine identity of existing documents (handoff jarvis-remotion-presentation-integration, Slice 20).

Real-looking v1 / v2 documents (the frozen fixtures the earlier Slices pinned) are copied into a throwaway store, never a live data
root. A document that names no engine reads as `slidecar` (not a fallback: Remotion was never asked of it); the file is left
byte-identical by every read; the first save keeps the exact old bytes once (`presentation.json.v<N>.bak`, CLAUDE.md) and writes
`"engine": "slidecar"`; a later save never touches the copy; nothing converts it.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from jarvis.adapters.file_presentation_studio_store import FilePresentationStudioStore
from jarvis.core.presentation_studio_engine_gate import StudioEngineGate
from jarvis.core.presentation_studio_service import PresentationStudioService
from jarvis.domain.presentation_studio import PresentationStudioError
from jarvis.domain.presentation_studio_engine import Engine, EngineAvailability

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio"
PID = "pst_00000000000000000000000000000001"
PARENT, CHILD = "psv_00000000000000000000000000000001", "psv_00000000000000000000000000000002"


class Sink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None, **_):
        self.rows.append({"kind": kind, "level": level, "data": dict(data or {})})


def lay_out(root: Path, manifest: str, parent: str, child: str) -> Path:
    folder = root / "presentations" / PID
    (folder / "variants").mkdir(parents=True)
    shutil.copyfile(FIXTURES / manifest, folder / "presentation.json")
    shutil.copyfile(FIXTURES / parent, folder / "variants" / f"{PARENT}.json")
    shutil.copyfile(FIXTURES / child, folder / "variants" / f"{CHILD}.json")
    return folder


def snapshot(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


CASES = [("presentation.v1.json", "variant.parent.v1.json", "variant.v1.json", 1),
         ("presentation.v2.json", "variant.parent.v1.json", "variant.v2.json", 2)]


@pytest.mark.parametrize("manifest, parent, child, old_version", CASES)
async def test_a_legacy_document_reads_as_slidecar_is_listed_with_its_badge_and_stays_byte_identical_until_the_first_save(
        tmp_path, manifest, parent, child, old_version):
    folder = lay_out(tmp_path, manifest, parent, child)
    original = snapshot(folder)
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path))
    listing = await service.list_presentations()
    assert [row["engine"] for row in listing.presentations] == ["slidecar"] and listing.problems == ()
    view = await service.get(PID)
    assert view.presentation.engine is Engine.SLIDECAR
    assert snapshot(folder) == original, "a read must never rewrite a legacy document"
    assert not list(folder.glob("*.bak"))

    saved = await service.save_presentation(PID, {"expected_revision": view.presentation.revision, "title": "Bilan",
                                                  "active_variant_id": view.presentation.active_variant_id,
                                                  "resources": json.loads(original["presentation.json"])["resources"]})
    assert saved.engine is Engine.SLIDECAR
    written = json.loads((folder / "presentation.json").read_text(encoding="utf-8"))
    assert written["schema_version"] == 3 and written["engine"] == "slidecar"
    backup = folder / f"presentation.json.v{old_version}.bak"
    assert backup.read_bytes() == original["presentation.json"], "the first rewrite keeps the exact old bytes"
    for name, content in original.items():
        if name.startswith("variants/"):
            assert (folder / name).read_bytes() == content, "the variant files are not touched by a manifest save"

    again = await service.save_presentation(PID, {"expected_revision": saved.revision, "title": "Bilan 2",
                                                  "active_variant_id": saved.active_variant_id, "resources": []})
    assert again.engine is Engine.SLIDECAR and backup.read_bytes() == original["presentation.json"], "the copy is kept once"


async def test_a_save_that_names_an_engine_is_refused_and_the_legacy_file_is_untouched(tmp_path):
    folder = lay_out(tmp_path, *CASES[0][:3])
    original = snapshot(folder)
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path))
    with pytest.raises(PresentationStudioError) as caught:
        await service.save_presentation(PID, {"expected_revision": 3, "title": "x", "active_variant_id": CHILD, "resources": [],
                                              "engine": "remotion"})
    assert "engine" in caught.value.message
    assert snapshot(folder) == original


async def test_a_future_engine_name_in_a_stored_document_is_refused_not_guessed(tmp_path):
    folder = lay_out(tmp_path, "presentation.v2.json", "variant.parent.v1.json", "variant.v2.json")
    document = json.loads((folder / "presentation.json").read_text(encoding="utf-8"))
    document.update(schema_version=3, engine="powerpoint")
    (folder / "presentation.json").write_text(json.dumps(document), encoding="utf-8")
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path))
    listing = await service.list_presentations()
    assert listing.presentations == () and listing.problems, "a document with an unknown engine is a visible problem, not a Slidecar one"


# ------------------------------------------------------------------ observability of the use of a stored Slidecar document

async def test_every_play_edit_or_preview_of_a_slidecar_document_is_journaled_and_throttled_and_remotion_is_not(tmp_path):
    lay_out(tmp_path, *CASES[1][:3])
    sink = Sink()
    gate = StudioEngineGate(lambda: {Engine.SLIDECAR: EngineAvailability(True),
                                     Engine.REMOTION: EngineAvailability(False, "no runtime", "install it")})
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path), diagnostics=sink, engine_gate=gate)
    for action in ("play", "edit", "play", "preview"):
        await service.require_engine(PID, action)
    used = [row for row in sink.rows if row["kind"].endswith(".slidecar_used")]
    assert [row["data"]["action"] for row in used] == ["play", "edit", "preview"], "the repeat within a minute is not re-journaled"
    assert all(row["data"]["engine"] == "slidecar" and row["data"]["presentation_id"] == PID and row["data"]["reason"] for row in used)
    overview = service.engine_overview()
    assert overview["engines"]["slidecar"]["ready"] is True
    assert overview["engines"]["remotion"] == {"ready": False, "reason": "no runtime", "repair": "install it"}
    assert [e["action"] for e in overview["slidecar"]["events"]] == ["preview", "edit", "play"]
    assert overview["slidecar"]["total"] == 3


async def test_a_broken_remotion_is_reported_by_the_overview_and_never_answered_with_slidecar(tmp_path):
    sink = Sink()
    gate = StudioEngineGate(lambda: {Engine.SLIDECAR: EngineAvailability(True),
                                     Engine.REMOTION: EngineAvailability(False, "runtime missing", "install Remotion")})
    service = PresentationStudioService(FilePresentationStudioStore(tmp_path), diagnostics=sink, engine_gate=gate)
    made = await service.create({"title": "Plan"})
    with pytest.raises(PresentationStudioError) as caught:
        await service.require_engine(made.presentation.presentation_id, "play")
    assert caught.value.code.value == "presentation_studio_engine_unavailable"
    assert "runtime missing" in caught.value.message
    assert not [row for row in sink.rows if row["kind"].endswith(".slidecar_used")]
    assert service.engine_overview()["slidecar"]["total"] == 0
