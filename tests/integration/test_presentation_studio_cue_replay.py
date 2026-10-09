"""Slice 13 : the rehearsed-run replay through the real lane, the real follower and the real Core playback service.

Asserts the story (what moved, what did not), the efficiency of the trace (no call that was not needed) and the privacy of
every trace row; then re-checks the committed evidence directory. No microphone, no network, no model:
see `tests/replay/presentation_studio_cue_replay.py` for exactly what is real and what is not.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from jarvis.audio import input_ownership
from tests.replay import evidence_privacy
from tests.replay.presentation_studio_cue_replay import SCRIPT, run_rehearsal

EVIDENCE = (Path(__file__).resolve().parents[2] / "tasks/jarvis-interactive-presentation-studio/slices/13-user-presenter-sidekick/evidence")


@pytest.fixture(autouse=True)
def clean_input_registry():
    input_ownership.reset_for_test()
    yield
    input_ownership.reset_for_test()


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFD", text.casefold())
    return {w for w in re.findall(r"[a-z0-9]+", "".join(c for c in folded if not unicodedata.combining(c))) if len(w) >= 5}


@pytest.fixture
async def rehearsal(tmp_path):
    return await run_rehearsal(tmp_path)


async def test_the_story_only_the_two_stage_directions_moved_the_presentation(rehearsal) -> None:
    steps = rehearsal["script_steps"]
    assert [s["reports_sent"] for s in steps] == [0, 0, 0, 1, 0, 0, 1]
    assert rehearsal["positions"] == [1, 1, 1, 1, 2, 3, 3, 4]  # 3 is the manual `next`; 2 and 4 are the cues
    assert rehearsal["stage_title"] == "Trois"  # the stage window was patched to the last scene
    assert rehearsal["brain_turns"] == 1  # the vocative went the explicit-address way, once; no ambient text became a turn
    assert steps[2]["counter_delta"] == {"preempted_address": 1, "utterances": 1}
    assert steps[1]["counter_delta"]["vetoed"] == 1 and steps[5]["counter_delta"]["vetoed"] == 1
    assert steps[4]["counter_delta"].get("no_armed") == 1  # the repeated phrase met an empty armed set
    reports = [c for c in rehearsal["calls"] if c["call"] == "report"]
    assert [(c["cue_id"], c["status"], c["code"]) for c in reports] == [(rehearsal["cue_ids"][0], "fired", None),
                                                                        (rehearsal["cue_ids"][1], "fired", None)]
    assert all(c["keys"] == ["run_id", "generation", "cue_id"] for c in reports)


async def test_the_trace_is_efficient(rehearsal) -> None:
    calls = rehearsal["calls"]
    pulls = [c for c in calls if c["call"] == "armed"]
    reports = [c for c in calls if c["call"] == "report"]
    assert len(reports) == 2 and len(reports) == rehearsal["follower"]["counters"]["fired"]  # a report only for a fire
    assert len(pulls) == 3 and len(rehearsal["bus"]) == 4  # one pull at start, then one per CHANGE seen (messages coalesce)
    assert len(pulls) <= 1 + len(rehearsal["bus"]) and rehearsal["follower"]["counters"]["pull_failures"] == 0
    assert rehearsal["follower"]["counters"]["pulls"] == len(pulls)
    assert rehearsal["follower"]["counters"]["reports_failed"] == 0 and rehearsal["follower"]["counters"]["refused"] == {}
    pulled = [(c["generation"], c["count"]) for c in pulls]
    assert len(set(pulled)) == len(pulled)  # never the same (generation, count) pulled twice: no redundant call
    assert rehearsal["follower"]["state"] == "following" and rehearsal["follower"]["counters"]["handler_errors"] == 0
    # the voice trace has a line for each decision that matters and none for the ordinary chatter
    kinds = [r["kind"].rsplit(".", 1)[-1] for r in rehearsal["voice_trace"] if r["kind"].startswith("presentation.studio")]
    assert kinds.count("cue_fired") == 2 and kinds.count("armed_set_changed") == 3
    assert not [k for k in kinds if k in ("cue_ambiguous", "follower_degraded", "follower_handler_failed", "follower_probe_failed")]


async def test_no_ambient_utterance_text_reaches_any_trace_row(rehearsal) -> None:
    """Every row of the Voice trace, the Core diagnostics, the wire log and the bus. The ONE exception is what the existing
    realtime bridge writes for a sentence the user ADDRESSED to Jarvis (step 3: `voice.transcript` and
    `voice.brain_turn_submitted`): not ambient, not ours, and pre-existing behaviour of the explicit-address path."""

    rows = rehearsal["voice_trace_all"]
    explicit = ("voice.transcript", "voice.brain_turn_submitted")
    ours = [r for r in rows if r["kind"] not in explicit]
    blob = json.dumps([ours, rehearsal["core_trace"], rehearsal["calls"], rehearsal["bus"]], ensure_ascii=False, default=repr)
    folded = _words(blob)
    for text in rehearsal["utterances"]:
        for word in _words(text):
            assert word not in folded, f"the speech word {word!r} reached a trace row"
        assert text not in blob
    said = [r["message"] for r in rows if r["kind"] in explicit]
    assert said and set(said) == {SCRIPT[2][0]}  # only the addressed sentence, by the existing path
    assert "psc_" in blob and "whole_phrase" in blob  # what IS recorded: ids and the rule


async def test_the_committed_evidence_is_clean_and_small() -> None:
    if not EVIDENCE.exists():
        pytest.skip("evidence not recorded yet")
    assert evidence_privacy.sweep(EVIDENCE) == []
    files = {p.name: p for p in EVIDENCE.iterdir() if p.is_file()}
    assert {"rehearsal-summary.json", "core-calls.json", "voice-trace.json", "core-trace.json"} <= set(files)
    assert sum(p.stat().st_size for p in files.values()) < 64 * 1024
    blob = "\n".join(p.read_text(encoding="utf-8") for p in files.values() if p.suffix == ".json")
    for text, _, _ in SCRIPT:
        for word in _words(text):
            assert word not in _words(blob), word


async def test_the_whole_rehearsal_never_reaches_a_brain_turn_a_tool_an_action_or_an_intent(tmp_path) -> None:
    """RUNTIME guard (QA-1 P1): the entry points of the brain, the tools, the ActionBroker and the UI intents explode if called
    anywhere during the full replay (lane -> follower -> Core playback). The one brain turn of the replay is the explicit address
    of step 3, which reaches Core through the scenario Core double, not through any of these."""

    from unittest import mock

    from jarvis.core.actions import ActionBroker
    from jarvis.core.tools import ToolRegistry
    from jarvis.domain import v2
    from jarvis.protocol.client import LocalCoreClient

    trip = mock.Mock(side_effect=AssertionError("a forbidden entry point was called during the rehearsal"))
    with mock.patch.object(v2.BrainTurnInput, "__post_init__", trip), mock.patch.object(ActionBroker, "request", trip), \
            mock.patch.object(ToolRegistry, "to_action", trip), mock.patch.object(LocalCoreClient, "publish_ui_intent", trip):
        result = await run_rehearsal(tmp_path)
    assert trip.call_count == 0
    assert result["follower"]["counters"]["fired"] == 2 and result["brain_turns"] == 1
