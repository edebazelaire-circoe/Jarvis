"""The draft guide the model reads before its first submission (jarvis-interactive-presentation-studio, Slice 22 release gate).

Found by the first real-model authoring run: without the key names the brain guessed `flow`/`objective` and was refused three times. The
guide's example must stay a VALID submission (real gate, real assembly), its key lists must be the parsers' own, and it must travel through
the real tool without touching Core.
"""

from __future__ import annotations

import json

from jarvis.domain.presentation_studio_authoring import _BRIEF_OPTIONAL, parse_brief
from jarvis.domain.presentation_studio_authoring_guide import DRAFT_KEYS, draft_guide, example
from jarvis.domain.presentation_studio_authoring_policy import PLANNER_PROMPT
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv
from tests.unit.presentation_studio_mcp_world import open_world


async def test_the_example_passes_the_real_gate_and_the_real_assembly(tmp_path):
    env = await AuthoringEnv(tmp_path / "g").start()
    pair = example()
    checked = (await env.check(pair["brief"], pair["draft"])).body["report"]
    assert checked["ok"] is True and checked["failures"] == [] and checked["warnings"] == []
    outcome = await env.assemble(pair["brief"], pair["draft"])
    assert outcome.status == "delivered" and len(outcome.to_dict()["scenes"]) == 1


def test_the_key_lists_are_the_parsers_own_and_the_example_uses_no_other_key():
    guide = draft_guide()
    assert guide["brief"]["optional"] == sorted(_BRIEF_OPTIONAL) and guide["brief"]["required"] == ["title", "workflow"]
    assert set(example()["brief"]) <= set(guide["brief"]["required"]) | set(guide["brief"]["optional"])
    assert set(example()["draft"]) <= set(DRAFT_KEYS["required"]) | set(DRAFT_KEYS["optional"])
    assert parse_brief(example()["brief"]).workflow.value == "one_shot"
    assert len(json.dumps(guide, ensure_ascii=False).encode("utf-8")) < 6_000, "read on demand, but still bounded"


def test_a_returned_guide_is_a_copy_and_the_planner_prompt_names_it():
    first = draft_guide()
    first["example"]["brief"]["title"] = "changed"
    assert draft_guide()["example"]["brief"]["title"] == "Contenu du dossier"
    assert "draft_guide" in PLANNER_PROMPT


async def test_the_tool_serves_the_guide_without_calling_core(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        before = len(world.spy.calls)
        out = await world.tools.inspect("draft_guide")
        assert out["brief"]["optional"] == sorted(_BRIEF_OPTIONAL) and out["example"]["draft"]["scenes"][0]["key"] == "rapport"
        assert out["speech"] == "silent" and len(world.spy.calls) == before
        # the guide's own example is accepted by the real tool end to end
        made = await world.tools.draft("assemble", brief=out["example"]["brief"], draft=out["example"]["draft"])
        assert made["status"] == "delivered"
    finally:
        await core.__aexit__(None, None, None)


async def test_an_unknown_brief_key_is_refused_with_the_allowed_keys_and_without_echoing_the_names(tmp_path):
    core, world = await open_world(tmp_path)
    try:
        brief = {"title": "Un titre", "flow": "one_shot", "objective": "ZORGLUB-SECRET"}
        out = await world.tools.draft("assemble", brief=brief, draft={})
        message = json.dumps(out["report"]["failures"], ensure_ascii=False)
        assert out["status"] == "refused" and "brief_invalid" in message
        assert "ZORGLUB" not in message and "objective" not in message, "the author's key names are not echoed"
        assert "purpose" in message and "workflow" in message, "the vocabulary the model needs is"
    finally:
        await core.__aexit__(None, None, None)
