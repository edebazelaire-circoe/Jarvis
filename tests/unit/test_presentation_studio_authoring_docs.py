"""Code/documentation parity of the authoring contract (jarvis-interactive-presentation-studio, Slice 11).

The pages say what the code does: the rule table (all 40 rules, three levels), the thresholds, the schema keys, the workflow and
question tables, the routes, the error code, the owner modules, the OPERATIONS note, the canonical names (section 18), the carry-forward
sections of Slices 21 and 22, and the statement that the real-model trace is NOT done here.
"""

from __future__ import annotations

from pathlib import Path
import re

from jarvis.domain import presentation_studio_authoring as authoring
from jarvis.domain import presentation_studio_authoring_gate as gate
from jarvis.domain import presentation_studio_authoring_policy as policy

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks" / "jarvis-interactive-presentation-studio"


def studio_page() -> str:
    return (ROOT / "docs" / "presentation-studio.md").read_text(encoding="utf-8")


def section() -> str:
    text = studio_page()
    start = text.index("## Authoring contract (Slice 11)")
    return text[start:text.index("\n## ", start + 10)]


def test_the_rule_table_in_the_page_is_the_rule_table_in_the_code():
    rows = re.findall(r"^\| `([a-z_]+)` \| (error|warning|off) \| (error|warning|off) \| (error|warning|off) \| (.+) \|$",
                      section(), flags=re.MULTILINE)
    documented = {code: (one, directed, exploratory, summary) for code, one, directed, exploratory, summary in rows}
    assert len(documented) == len(rows) == len(gate.RULES) == 40
    for rule in gate.RULES:
        assert documented[rule.code] == (rule.one_shot, rule.directed, rule.exploratory, rule.summary), rule.code


def test_the_page_states_every_threshold_and_bound_the_gate_and_the_schema_enforce():
    text = section()
    for needle in (f"`MAX_CONTROLS_PER_SCENE` {gate.MAX_CONTROLS_PER_SCENE}", f"`MAX_SCENE_WORDS` {gate.MAX_SCENE_WORDS}",
                   f"`LONG_FORM_WORDS` {gate.LONG_FORM_WORDS}", f"`DURATION_TOLERANCE` {gate.DURATION_TOLERANCE}",
                   f"`HEADROOM` {gate.HEADROOM}", "`CUE_WINDOW` = `ARM_LOOKAHEAD` + 2", f"`MAX_FINDINGS_PER_RULE` {gate.MAX_FINDINGS_PER_RULE}",
                   f"(<= {authoring.MAX_DRAFT_BUNDLES})", f"(<= {authoring.MAX_DRAFT_SCENES}, 1..)", f"(<= {authoring.MAX_DRAFT_ITEMS}, ordered)",
                   f"{authoring.MIN_CANDIDATES}..{authoring.MAX_CANDIDATES}",
                   f"integer {authoring.MIN_DURATION_S}..{authoring.MAX_DURATION_S:,}".replace(",", " "),
                   f"<= {authoring.MAX_CANDIDATE_RATIONALE}", "4 MiB", authoring.BUNDLE_NAMESPACE,
                   f"{policy.PROMPT_BUDGET_CHARS:,}".replace(",", " ") + " characters"):
        assert needle in text, needle
    assert authoring.MAX_AUTHORING_BODY_BYTES == 4 * 1024 * 1024


def test_every_workflow_speech_role_mode_and_topic_is_documented():
    text = section()
    for enum in (authoring.Workflow, authoring.Speech, authoring.SceneRole, authoring.DaMode, policy.QuestionTopic):
        for member in enum:
            assert f"`{member.value}`" in text, (enum.__name__, member.value)
    for rule in ("W1", "W2", "W3", "W4", "Q0", "Q1", "Q2", "Q3", "Q4", "Q5"):
        assert f"| {rule} |" in text, rule


def test_every_brief_and_draft_key_is_documented():
    text = section()
    for key in ("title", "workflow", *authoring._BRIEF_OPTIONAL):
        assert f"`{key}`" in text, key
    for key in ("prefabs", "scenes", "score.items", "art_direction", "candidates", "scenes_patch", "bundle"):
        assert f"`{key}" in text, key
    for flag in ("`long_form: true`", "`cut: true`"):
        assert flag in text, flag
    assert "locked sequences and loops are not authored in a first draft" in text


def test_the_routes_the_error_code_and_the_owner_modules_are_documented_and_exist():
    text = section()
    for needle in ("presentation_studio_draft_refused", "/v1/presentation-studio/authoring/check", "/v1/presentation-studio/authoring/assemble",
                   "/v1/presentation-studio/authoring/reconcile", "**not relayed**", "`actor` forced to `user`"):
        assert needle in text, needle
    for module in ("jarvis/domain/presentation_studio_authoring.py", "jarvis/domain/presentation_studio_authoring_build.py",
                   "jarvis/domain/presentation_studio_authoring_gate.py", "jarvis/domain/presentation_studio_authoring_policy.py",
                   "jarvis/core/presentation_studio_authoring.py", "jarvis/protocol/presentation_studio_authoring_routes.py",
                   "jarvis/runtime/presentation_studio_authoring_relay.py"):
        assert module in text and (ROOT / module).is_file(), module
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "presentation_studio_authoring.py" in architecture and "authoring/{check,assemble}" in architecture
    assert "Presentation Studio authoring planner (Slice 11)" in (ROOT / "docs" / "prefabs.md").read_text(encoding="utf-8")


def test_the_crash_states_and_the_decisions_are_written():
    text = section()
    for needle in ("`Popen.kill()`", "ONE folder rename", "`PrefabService.save` and not the Slice 01a coalescer", "unreferenced_prefabs",
                   "never adopted, never deleted", "`.staging-*`", "Gate refuses, never repairs", "Provenance is self-declared",
                   "reported, not rolled back", "created_by"):
        assert needle in text, needle


def test_the_page_says_the_real_model_trace_is_not_done_here_and_names_who_owns_it():
    text = section()
    heading = text[text.index("### What is NOT verified here"):]
    for needle in ("not a trace of Claude", "required gate of Slices 21 and 22", "carry-forward", "rich brief", "no DA found",
                   "two conflicting brands", "hostile text", "a refused draft"):
        assert needle in heading, needle
    for slice_dir in ("21-agent-voice-operations", "22-end-to-end-hardening"):
        body = (TASK / "slices" / slice_dir / "SLICE.md").read_text(encoding="utf-8")
        assert "## Slice 11 carry-forward" in body, slice_dir
        assert "real-model" in body.lower() or "real model" in body.lower(), slice_dir
    twenty_one = (TASK / "slices" / "21-agent-voice-operations" / "SLICE.md").read_text(encoding="utf-8")
    for needle in ("untrusted-title line", "Slice 09 trace scenarios", "inspect then derive", "Never let the model invent ids",
                   "only `brain` door", "question_budget", "presentation_draft_check", "presentation_draft_assemble"):
        assert needle in twenty_one, needle
    twenty_two = (TASK / "slices" / "22-end-to-end-hardening" / "SLICE.md").read_text(encoding="utf-8")
    assert "presentation_studio.authoring.planner" in twenty_two and "release gate" in twenty_two


def test_the_canonical_names_have_a_section_18_for_this_slice():
    names = (TASK / "docs" / "09-canonical-names.md").read_text(encoding="utf-8")
    start = names.index("## 18. Slice 11 amendments")
    block = names[start:]
    for code in (rule.code for rule in gate.RULES):
        assert f"`{code}`" in block, code
    for needle in ("presentation_studio_draft_refused", "PLANNER_PROMPT", "presentation_studio.authoring.planner", "presentation_draft_check",
                   "/v1/presentation-studio/authoring/check", "create_assembled", "**none**"):
        assert needle in block, needle
    assert re.search(r"^## 17\. ", names, flags=re.MULTILINE) and not re.search(r"^## 19\. ", names, flags=re.MULTILINE)


def test_the_operations_note_exists_and_makes_no_claim_the_code_does_not_keep():
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    note = operations[operations.index("### Assemblage d'une présentation (studio, Slice 11)"):]
    note = note[:note.index("\n### ", 10)]
    for needle in ("40 règles", "une seule transaction", "`.staging-*`", "presentation_studio_draft_refused",
                   "/api/presentation-studio/authoring/check", "/v1/presentation-studio/authoring/reconcile",
                   "authoring_unreferenced", "jamais adoptées ni supprimées", "ne prouvent pas"):
        assert needle in note, needle
    assert "40" in note and len(gate.RULES) == 40


def test_the_concept_and_levels_rows_say_slice_11_is_implemented_and_the_policy_items_are_updated():
    page = studio_page()
    row = next(line for line in page.splitlines() if line.startswith("| Authoring planner |"))
    assert "**implemented (Level 3)**" in row and "Slices 21, 22" in row and "40 coded rules" in row
    assert "| Authoring planner (brief, draft, workflows, question budget, quality gate, atomic assembly, planner prompt) | 0-1 | 3 (**done**, Slice 11;" in page
    assert "`require_art_direction` has callers" in page and "has no caller yet" not in page
    assert "`presentation_studio_draft_refused` | 400 |" in page
    assert "the Authoring contract" in page.split("## Not to be confused with", 1)[0] or "*Authoring contract*" in page.split("## Not to be confused with", 1)[0]


def test_the_tool_contract_page_is_untouched_until_slice_21():
    contract = (ROOT / "docs" / "mcp" / "tool-contract.md").read_text(encoding="utf-8")
    assert "presentation_draft" not in contract and "authoring" not in contract.lower().replace("authoring agent", "")
