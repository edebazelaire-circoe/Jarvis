"""Replay / evaluation harness of the Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S10). Contrat : §18.

Deterministic CI layer: every recorded scenario runs through the real runtime -> queue -> executor -> owner stack with a
fake clock and a scripted decider; the invariants must hold and the scenario's exact expectations must match. The
oracle itself is tested (a harness that cannot fail proves nothing).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tool_brain_queue import ActionRecord, Trigger, preconditions_from
from jarvis.runtime.tool_brain_choices import read_ui_state
from tests.replay import tool_brain_replay as replay

SCENARIOS = replay.load_scenarios()
#: docs/04-testing-and-quality.md "Agent trace scenarios": the eight that must exist as fixtures.
DOC_TRACES = {"show-and-analyze", "long-response", "interruption", "stale-object", "board-switch", "browser-display",
              "invalid-choice", "decider-outage"}


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


def test_the_eight_documented_traces_exist_as_fixtures_with_unique_ids():
    ids = [item["id"] for item in SCENARIOS]
    assert DOC_TRACES <= set(ids) and len(ids) == len(set(ids))
    assert all(item["schema"] == replay.SCHEMA for item in SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[item["id"] for item in SCENARIOS])
async def test_a_scenario_holds_its_invariants_and_its_exact_expectations(scenario, catalog):
    report = await replay.run_scenario(scenario, catalog)
    assert report["violations"] == [], report["violations"]
    assert report["expectation_mismatches"] == [], report["expectation_mismatches"]


async def test_replay_is_deterministic_apart_from_wall_time(catalog):
    def stable(report):
        report = json.loads(json.dumps(report))
        report.pop("wall_ms", None)
        report["metrics"].pop("step_ms_max", None)
        for step in report["steps"]:
            step.pop("wall_ms", None)
        return report

    for scenario in SCENARIOS[:6]:
        first = stable(await replay.run_scenario(scenario, catalog))
        second = stable(await replay.run_scenario(scenario, catalog))
        assert first == second, scenario["id"]


async def test_the_safety_scenarios_never_mutate_what_they_must_not(catalog):
    by_id = {item["id"]: item for item in SCENARIOS}
    interruption = await replay.run_scenario(by_id["interruption"], catalog)
    assert interruption["metrics"]["executed"] == 0 and interruption["metrics"]["final_x"]["brain-note-a"] == 0
    outage = await replay.run_scenario(by_id["decider-outage"], catalog)
    assert outage["metrics"]["outcomes"][0] == "failed"
    assert outage["decisions"][0]["actions"] == []  # nothing proposed, nothing queued during the outage
    invalid = await replay.run_scenario(by_id["invalid-choice"], catalog)
    assert invalid["metrics"]["rejected_codes"].get("unknown_object", 0) >= 1
    archived = [a for d in invalid["decisions"] for a in d["actions"] if a["tool"] == "scene_archive"]
    assert archived and archived[0]["queued"]["outcome"] == "queued"  # admitted, then refused by the guard at execution
    assert invalid["metrics"]["queue"].get("invalidated") == 1 and invalid["metrics"]["final_x"]["brain-note-a"] == 0


# ------------------------------------------------------------------ the oracle can fail


async def _rig(catalog, scenario_id="stale-object"):
    scenario = next(item for item in SCENARIOS if item["id"] == scenario_id)
    tmp = tempfile.TemporaryDirectory(prefix="tb-replay-test-")
    rig = await replay.build_rig(scenario, Path(tmp.name), catalog, replay.scripted_factory)
    return rig, tmp


async def test_a_write_outside_the_queue_is_reported(catalog):
    rig, tmp = await _rig(catalog)
    try:
        await rig.scene.apply(replay._note_command({"id": "brain-note-x", "title": "sneaky"}))
        report = await replay.score(rig)
        assert {item["invariant"] for item in report["violations"]} == {"write_outside_queue"}
    finally:
        await replay.close_rig(rig)
        tmp.cleanup()


async def test_an_action_that_reached_the_owner_without_a_would_apply_verdict_is_reported(catalog):
    rig, tmp = await _rig(catalog)
    try:
        state = await read_ui_state(rig.scene, rig.boards)
        observed = state.ref()
        rig.queue.add(ActionRecord("hand-made", "jarvis-display", "scene_move",
                                   {"object_ids": ["brain-note-a"], "dx": 1, "dy": 0}, trigger=Trigger.from_payload(None),
                                   planned_from=observed, preconditions=preconditions_from(observed)))
        await rig.runtime._executor.execute("hand-made")  # noqa: SLF001 - bypassing the runtime on purpose
        report = await replay.score(rig)
        assert "executed_without_would_apply" in {item["invariant"] for item in report["violations"]}
    finally:
        await replay.close_rig(rig)
        tmp.cleanup()


async def test_the_obsolete_speech_oracle_distinguishes_a_cut_chain_from_a_live_one(catalog):
    rig, tmp = await _rig(catalog)
    try:
        record = ActionRecord("a1", "jarvis-display", "scene_move", {}, trigger=Trigger.from_payload(
            {"type": "speech_chunk", "chunk_id": "k3"}))
        await replay.run_step(rig, {"do": "speech", "state": "playing", "phases": "Pp",
                                    "chunks": [{"id": "k3", "i": 1, "ph": "playing"}]})
        assert replay._speech_dead(rig, record) is False
        await replay.run_step(rig, {"do": "speech", "state": "interrupted", "phases": "hi", "chunks": []})
        assert replay._speech_dead(rig, record) is True
        await replay.run_step(rig, {"do": "speech", "state": "playing", "phases": "Pp", "obsolete": ["k3"],
                                    "chunks": [{"id": "k3", "i": 1, "ph": "obsolete"}]})
        assert replay._speech_dead(rig, record) is True
    finally:
        await replay.close_rig(rig)
        tmp.cleanup()


def test_a_wrong_expectation_is_a_mismatch_not_a_pass(catalog):
    scenario = dict(next(item for item in SCENARIOS if item["id"] == "board-switch"))
    scenario["expect"] = {"executed": 5, "active_board": "default"}
    report = asyncio.run(replay.run_scenario(scenario, catalog))
    assert len(report["expectation_mismatches"]) == 2


def test_the_documented_command_runs_and_writes_a_report(tmp_path, capsys):
    assert replay.main(["--out", str(tmp_path)]) == 0
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert written["summary"]["failed"] == [] and written["summary"]["invariant_violations"] == 0
    assert "invalid_proposal_rate" in written["reports"][0]["metrics"]
    assert replay.main(["--scenario", "no-such-scenario"]) == 2
