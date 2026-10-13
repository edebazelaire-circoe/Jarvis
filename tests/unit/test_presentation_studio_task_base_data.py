"""Presentations saved before native-studio-playback-fix still open and play (Slice 15, migration safety).

The fixture `tests/fixtures/presentation_studio_task_base_a8377529/` was WRITTEN BY THE TASK BASE CODE (`a8377529`), not by hand and
not from a user's data: in a detached worktree at that commit, the real authoring door (`assemble_deck`, 3 Remotion scenes, score,
art direction) and `presentation_with_score` (3 window scenes) ran against a real Core, then a branch was made; the files Core wrote
under `presentations/` and `prefabs/` were copied as they were (SQLite bases left out, repo rule). `state/presentation-studio-stage-
ledger.json` is the id-list ledger the retired run stage window wrote (format of `a8377529`'s `file_presentation_studio_stage_ledger`).

Here the CURRENT Core opens that data root as it is: the presentations, variants, branch, scores and art directions read; a run plays in
the Variants run surface (Slice 09), never a Board window; the old ledger is read once and kept aside, never deleted. Nothing is migrated
in place: the stored documents are byte-identical after the run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

from jarvis.protocol.presentation_studio_playback_routes import PLAYBACK
from tests.unit.test_presentation_studio_playback_routes import get, start_body
from tests.unit.test_presentation_studio_routes import Core

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "presentation_studio_task_base_a8377529"
SMALL = ("pst_eaf773f3a32c8360758a76d54fc5398a", "psv_ff1d369bc1f1e187f99dbf77a47965e1")
DECK = ("pst_5ba11edc8ea08575b8397379859af675", "psv_cdd730b75bda3a1bea77e7d3b38343a4")
BRANCH = "psv_4a68694f2f6ae13a13aaed5f7a57b7e0"
DECK_SCENES = ["pss_fb9142fbddda", "pss_b05de78187bf", "pss_618942a263dd"]
LEDGER = "presentation-studio-stage-ledger.json"


def _seed(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    shutil.copytree(FIXTURE, data)
    return data


def _digests(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


async def test_presentations_saved_by_the_task_base_open_unchanged(tmp_path):
    data = _seed(tmp_path)
    before = _digests(data / "presentations")
    async with Core(tmp_path) as core:
        status, listing = await core.call("GET", "")
        assert status == 200, listing
        ids = {row["presentation_id"] for row in listing["presentations"]}
        assert {SMALL[0], DECK[0]} <= ids
        status, graph = await core.call("GET", f"/{DECK[0]}/graph")
        assert status == 200, graph
        assert {n["variant_id"] for n in graph["nodes"]} >= {DECK[1], BRANCH}
        for pid, vid in (SMALL, DECK, (DECK[0], BRANCH)):
            status, variant = await core.call("GET", f"/{pid}/variants/{vid}")
            assert status == 200 and len(variant["scenes"]) == 3, variant
            status, score = await core.call("GET", f"/{pid}/variants/{vid}/score")
            assert status == 200 and score["problems"] == [], score
        status, deck = await core.call("GET", f"/{DECK[0]}/variants/{DECK[1]}")
        assert [s["scene_id"] for s in deck["scenes"]] == DECK_SCENES
        # The one composition clock (Slice 04) maps the old variant: its three 10 s scenes back to back.
        status, clock = await core.call("GET", f"/{DECK[0]}/variants/{DECK[1]}/composition-clock")
        assert status == 200 and clock["problem"] is None, clock
        assert [s["scene_id"] for s in clock["clock"]["scenes"]] == DECK_SCENES and clock["clock"]["total_frames"] == 900
    assert _digests(data / "presentations") == before, "opening must not rewrite a stored presentation"


async def test_an_old_presentation_plays_in_the_variants_run_surface_and_the_old_ledger_is_kept_aside(tmp_path):
    data = _seed(tmp_path)
    before = _digests(data / "presentations")
    async with Core(tmp_path) as core:
        state = data / "state"
        assert not (state / LEDGER).exists(), "Core start reads the retired ledger once"
        kept = [p.name for p in state.iterdir() if p.name.startswith(LEDGER + ".retired-")]
        assert len(kept) == 1, sorted(p.name for p in state.iterdir())
        client = core.client
        for pid, first, second in ((SMALL[0], "Un", "Deux"), (DECK[0], None, None)):
            started = await client.presentation_studio_playback("start", start_body(pid))
            assert started["status"] == "applied" and started["state"]["phase"] == "playing", started
            stage_id = started["state"]["stage_object_id"]
            assert stage_id.startswith("variants-run-")
            status, surface = await get(core, f"{PLAYBACK}/surface")
            assert status == 200 and surface["surface"]["surface_id"] == stage_id
            moved = await client.presentation_studio_playback("next", {"actor": "user"})
            if first is None:
                assert started["state"]["scene"]["scene_id"] == DECK_SCENES[0]
                assert moved["state"]["scene"]["scene_id"] == DECK_SCENES[1]
            else:
                assert started["state"]["scene"]["title"] == first and moved["state"]["scene"]["title"] == second
            assert (await core.stack.core.scene.snapshot()).objects == (), "never a Board window"
            stopped = await client.presentation_studio_playback("stop", {"actor": "user"})
            assert stopped["state"]["phase"] == "stopped"
    assert _digests(data / "presentations") == before, "playing must not rewrite a stored presentation"
