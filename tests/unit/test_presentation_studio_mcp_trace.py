"""The scripted tool traces and their committed, redacted evidence (jarvis-interactive-presentation-studio, Slice 21).

`python -m tests.replay.presentation_studio_mcp_rig` regenerates the evidence deliberately; these tests fail when the tools moved without it,
and when the evidence claims more than a scripted brain can prove. Not a model trace: see `real-model-traces.md` for those.
"""

from __future__ import annotations

import json
import re

from tests.replay.presentation_studio_mcp_rig import EVIDENCE, ID_PATTERN, render, run


async def test_the_committed_evidence_is_what_the_rig_produces_now():
    result = json.loads(json.dumps(await run(), sort_keys=True))
    committed = json.loads((EVIDENCE / "scripted-tool-traces.json").read_text(encoding="utf-8"))
    assert result == committed, "regenerate: python -m tests.replay.presentation_studio_mcp_rig"
    assert (EVIDENCE / "scripted-tool-traces.md").read_text(encoding="utf-8") == render(result)


async def test_the_scripted_scenarios_prove_what_they_claim():
    result = json.loads(json.dumps(await run(), sort_keys=True))
    by_name = {row["scenario"]: row for row in result["scenarios"]}
    assert result["totals"]["ids_typed_from_memory"] == 0, "every id argument was returned by an earlier call"
    # visual gestures are silent; only the facts that are new, a click expected, a question or a refusal are said
    show = by_name["show all variants"]
    assert show["said_aloud"] == 0 and [c["speech"] for c in show["calls"]] == ["silent"] and show["explorer_command"] == "open"
    assert by_name["compare these four"]["said_aloud"] == 0 and by_name["compare these four"]["layout"] == "four_up"
    assert by_name["compare these four"]["writes_to_core"] == 0, "comparing writes nothing"
    assert by_name["semantic edit of a control"]["said_aloud"] == 0
    opened = by_name["open variant 2 (fullscreen needs a click)"]
    assert opened["needs_gesture"] is True and opened["told_the_user_to_click"] is True and opened["said_aloud"] == 1
    assert by_name["make a variant"]["variant_number"] == 2 and by_name["make a variant"]["said_aloud"] == 1
    # the destructive gesture asks first, and Core is not asked to archive before the user's yes
    delete = by_name["delete a branch (archive with the canonical confirmation)"]
    assert [c["op"] for c in delete["calls"]] == ["presentation", "archive_plan", "archive"]
    assert delete["core_archive_calls_before_the_yes"] == 0 and delete["remaining_numbers"] == [1, 2] and delete["said_aloud"] == 2
    # the start origin is the Control Center's attestation of the real turn, and the model never wrote it
    rehearse = by_name["rehearse from the second scene"]
    assert rehearse["origin_sent"] == "explicit_user_request" and rehearse["role"] == "rehearsal" and rehearse["phase_before_stop"] == "playing"
    assert rehearse["said_aloud"] == 0 and all(not c["arguments"].get("origin") for c in rehearse["calls"])
    undo = by_name["undo the user's own edit"]
    assert (undo["asked_first"], undo["final"], undo["expected_entry_id_sent"]) == ("confirmation_required", "applied", True)
    hostile = by_name["hostile text in a title"]
    assert hostile["title_reported_as_untrusted"] is True and hostile["archive_calls"] == 0 and hostile["said_aloud"] == 0


def test_the_evidence_is_redacted_and_states_that_it_is_not_a_model_trace():
    text = (EVIDENCE / "scripted-tool-traces.md").read_text(encoding="utf-8") + (EVIDENCE / "scripted-tool-traces.json").read_text(encoding="utf-8")
    assert "not a model trace" in text and "real-model-traces.md" in text
    assert not ID_PATTERN.search(text), "no raw id"
    for pattern in (r"pst_[0-9a-f]{6}", r"psv_[0-9a-f]{6}", r"\d{4}-\d{2}-\d{2}T", "IGNORE TOUT", "Version sobre", "A la main", "Users", "bips"):
        assert not re.search(pattern, text), pattern
