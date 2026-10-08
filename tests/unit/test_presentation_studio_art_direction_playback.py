"""Slice 09 <-> Slice 12: the REAL art direction gate in front of a playback run (jarvis-interactive-presentation-studio).

The gate is `PresentationStudioService.require_art_direction` itself (Slice 09), not a fake: a serious run of a variant with an
art direction starts and says `checked` (`fallback` for a generated fallback); without one it is refused with the typed
`presentation_studio_art_direction_required` and nothing changes; a rehearsal (exploratory) may run without one. A run never
writes an art direction, a score or the variant (hashes), including across the playback commit listener.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jarvis.domain.presentation_studio import PresentationStudioError, PresentationStudioErrorCode as C
from tests.fakes import presentation_studio_art_direction as fx
from tests.unit.test_presentation_studio_playback_service import S1, Rig, applied


class RealGateRig(Rig):
    """The playback rig, with the studio service itself as the gate."""

    async def open(self, **kwargs):
        await super().open(**kwargs)
        self.gate = self.studio
        self.build()
        return self

    async def variant_now(self):
        return await self.studio.get_variant(self.pid, self.vid)

    async def attach(self, profile=None, *, fallback=False):
        revision = (await self.variant_now()).revision
        if fallback:
            return await self.studio.create_fallback_art_direction(self.pid, self.vid, {"expected_variant_revision": revision})
        return await self.studio.create_art_direction(self.pid, self.vid, {
            "expected_variant_revision": revision, "profile": profile or fx.base_dict()})

    def folder(self) -> Path:
        return self.env.root / "presentations" / self.pid

    def link_digest(self) -> dict[str, str]:
        """sha256 of every art direction and score file (the documents a run must never touch)."""

        out = {}
        for sub in ("art_directions", "scores"):
            for path in sorted((self.folder() / sub).glob("*.json")) if (self.folder() / sub).is_dir() else []:
                out[f"{sub}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return out


@pytest.fixture
async def rig(tmp_path) -> RealGateRig:
    rig = await RealGateRig(tmp_path).open()
    yield rig
    await rig.close()


async def test_a_serious_variant_with_an_art_direction_starts_and_is_checked(rig):
    await rig.attach(fx.full_dict())
    state = applied(await rig.service.start(rig.start_body()))
    assert state["art_direction"] == "checked" and state["phase"] == "playing"
    assert rig.env.sink.of("core.presentation_studio.art_direction_resolved")[-1][1]["status"] == "resolved"
    applied(await rig.run("stop"))
    applied(await rig.service.start(rig.start_body("jarvis_presenter", jarvis_speaks=True)))
    applied(await rig.run("stop"))


async def test_a_generated_fallback_art_direction_starts_and_says_fallback(rig):
    await rig.attach(fallback=True)
    state = applied(await rig.service.start(rig.start_body()))
    assert state["art_direction"] == "fallback"


async def test_a_serious_variant_without_an_art_direction_is_refused_with_a_typed_error_and_nothing_changes(rig):
    mode_before, revision_before = rig.mode.mode, rig.mode.revision
    for role, extra in (("user_presenter", {}), ("jarvis_presenter", {"jarvis_speaks": True})):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.service.start(rig.start_body(role, **extra))
        assert caught.value.code is C.ART_DIRECTION_REQUIRED and caught.value.status == 409
        assert "art direction" in caught.value.message
    assert (rig.mode.mode, rig.mode.revision) == (mode_before, revision_before)
    assert await rig.stage_object() is None and rig.service.where() == {"phase": "idle", "running": False}
    refused = [row for row in rig.env.sink.rows if row[0] == "core.presentation_studio.refused"
               and row[2].get("code") == "presentation_studio_art_direction_required"]
    assert refused and refused[0][1] == "info"                                # visible in the journal with its code


async def test_a_dangling_art_direction_link_is_refused_for_a_serious_run(rig):
    created = await rig.attach()
    (rig.folder() / "art_directions" / f"{created['art_direction']['art_direction_id']}.json").unlink()
    with pytest.raises(PresentationStudioError) as caught:
        await rig.service.start(rig.start_body())
    assert caught.value.code is C.UNKNOWN_ART_DIRECTION
    assert await rig.stage_object() is None


async def test_a_corrupt_art_direction_is_a_hard_error_even_for_a_rehearsal(rig):
    created = await rig.attach()
    path = rig.folder() / "art_directions" / f"{created['art_direction']['art_direction_id']}.json"
    path.write_text("{broken", encoding="utf-8")
    for role in ("user_presenter", "rehearsal"):
        with pytest.raises(PresentationStudioError) as caught:
            await rig.service.start(rig.start_body(role))
        assert caught.value.code is C.CORRUPT_DOCUMENT


async def test_an_exploratory_rehearsal_may_run_without_an_art_direction(rig):
    state = applied(await rig.service.start(rig.start_body("rehearsal")))
    assert state["phase"] == "playing" and state["art_direction"] == "none"      # the gate answered `missing` for a draft: said so
    assert rig.env.sink.of("core.presentation_studio.art_direction_resolved")[-1][1]["serious"] is False
    assert (await rig.variant_now()).art_direction_id is None                    # and nothing was created behind its back


async def test_a_run_never_writes_an_art_direction_a_score_or_the_variant(rig):
    await rig.attach()
    files = rig.link_digest()
    assert len(files) == 2                                                       # one art direction and one score
    variant_bytes = rig.variant_file.read_bytes()
    applied(await rig.service.start(rig.start_body()))
    for verb in ("next", "pause", "resume", "next", "previous"):
        applied(await rig.run(verb))
    applied(await rig.run("stop"))
    assert rig.link_digest() == files and rig.variant_file.read_bytes() == variant_bytes


async def test_the_playback_commit_listener_keeps_both_links_and_never_touches_their_files(rig):
    """An edit made during a run goes edit service -> `write_variant` -> `_persist_variant`: the links survive, the files are byte-equal."""

    created = await rig.attach()
    before = await rig.variant_now()
    files = rig.link_digest()
    applied(await rig.service.start(rig.start_body()))
    result = await rig.service.edit({"actor": "user", "ops": [
        {"op": "control.set", "scene_id": S1, "control_id": "headline", "value": "Nouveau titre"}]})
    assert result.to_dict()["edit"]["committed"] is True
    after = await rig.variant_now()
    assert after.revision == before.revision + 1
    assert (after.score_id, after.art_direction_id) == (before.score_id, created["art_direction"]["art_direction_id"])
    assert rig.link_digest() == files                                            # the documents behind the links are untouched
    applied(await rig.run("resume"))
    applied(await rig.run("stop"))
    assert rig.link_digest() == files


async def test_a_da_saved_during_a_pause_is_noticed_by_its_own_revision_not_the_variant_revision(rig):
    await rig.attach()
    applied(await rig.service.start(rig.start_body()))
    applied(await rig.run("pause"))
    variant_revision = (await rig.variant_now()).revision
    await rig.studio.save_art_direction(rig.pid, rig.vid, {
        "expected_revision": 1, "profile": fx.set_path(fx.base_dict(), "shapes.radius_px", 20)})
    assert (await rig.variant_now()).revision == variant_revision                # the variant did not move
    applied(await rig.run("resume"))
    assert "art_direction_changed" in rig.service.where()["notices"]


def test_core_wiring_makes_the_real_gate_mandatory_and_the_single_variant_write_path_holds():
    root = Path(__file__).resolve().parents[2]
    wiring = (root / "jarvis/core/v2_app.py").read_text(encoding="utf-8")
    assert "gate=self.presentation_studio," in wiring and "hasattr(self.presentation_studio" not in wiring
    assert "must provide require_art_direction" in wiring                        # a Core without the gate does not start
    # every variant file is written by `_persist_variant`, the one place that guards `score_id` and `art_direction_id`
    callers = []
    for path in (root / "jarvis").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name != "file_presentation_studio_store.py":
            callers += [path.name for line in text.splitlines() if "store.write_variant(" in line or "_store.write_variant," in line]
    assert callers == ["presentation_studio_service.py"], callers
    service = (root / "jarvis/core/presentation_studio_service.py").read_text(encoding="utf-8")
    assert service.count("self._store.write_variant,") == 1 and "async def _persist_variant" in service
