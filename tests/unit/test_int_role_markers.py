"""Integration step (jarvis-memory-intelligence-knowledge, Slice 09): the brain is taught the role markers."""
from __future__ import annotations

from jarvis.runtime import routing_hook
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT


def test_rule_and_brain_prompt_teach_qa_and_research():
    # Slice 07 (jarvis-organic-agent-orchestration) : la relecture s'enseigne [qa] ; [reviewer] n'est plus
    # enseigné mais reste lu (alias, docs/legacy/subagent-role-aliases.md).
    for role in ("qa", "research"):
        assert f"[{role}]" in routing_hook.PROFILE_RULE
        assert f"[{role}]" in BRAIN_SYSTEM_PROMPT
    assert "[reviewer]" not in routing_hook.PROFILE_RULE and "[reviewer]" not in BRAIN_SYSTEM_PROMPT


def test_hook_reads_back_what_the_rule_teaches():
    assert routing_hook.read_role({"description": "[code] [qa] Relire le diff"}) == "qa"
    # L'alias historique garde son loadout (`code:reviewer`) : qa et reviewer lisent les mêmes savoirs.
    assert routing_hook.read_loadout_role({"description": "[code] [qa] Relire le diff"}) == "reviewer"
    assert routing_hook.read_role({"description": "[code] [reviewer] Relire le diff"}) == "reviewer"
    assert routing_hook.read_role({"description": "[general] [research] Chercher la doc"}) == "research"
    assert routing_hook.read_profile({"description": "[code] [reviewer] Relire"}) == "code"


def test_prompt_catalog_serves_the_markers_to_the_brain_session():
    from jarvis.domain.prompt_registry import PromptTarget
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    result = default_prompt_registry().resolve(PromptTarget(
        "backend", provider="claude", model="configured", compatibility="legacy", invocation="conversation_session"))
    text = next(i for i in result.channels if i["channel"] == "cli.append_system_prompt")["text"]
    assert "[qa]" in text and "[research]" in text
