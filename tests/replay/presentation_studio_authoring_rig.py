"""The scripted fake-author rig of Slice 11, run end to end, and its redacted evidence file.

`python -m tests.replay.presentation_studio_authoring_rig` writes
`tasks/jarvis-remotion-presentation-integration/slices/15-remotion-one-shot-authoring/evidence/fake-author-rig.{json,md}`
(Slice 15 moved the rig to Remotion scenes: the Slice 11 files of the original handoff record the HTML rig and are left as that history).
`tests/unit/test_presentation_studio_authoring_rig.py` runs the same scenarios and compares the result with the committed JSON, so the
evidence cannot drift from the code (regenerate it deliberately when a rule, the prompt or the fixtures change).

**This is not a trace of Claude.** It records what the deterministic side does with four scripted authors: a good one-shot, a good
12-scene directed deck, a careless author who breaks each gate rule in turn, and an exploratory request with three candidates. Whether
the real model follows `PLANNER_PROMPT` is the gate of Slices 21 and 22. Redacted by construction: rule codes, counts and states only;
no id, no timestamp, no text the author wrote.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from jarvis.domain.presentation_studio_authoring_gate import RULES
from jarvis.domain.presentation_studio_authoring_policy import (
    OP_ASSEMBLE, OP_CHECK, OP_FINALIZE, PLANNER_PROMPT, PROMPT_FINGERPRINT, PROMPT_ID, QUESTION_CAP, RequestSignals, choose_workflow,
)
from tests.fakes import presentation_studio_fake_author as fa
from tests.fakes.presentation_studio_authoring_env import AuthoringEnv

EVIDENCE = (Path(__file__).resolve().parents[2] / "tasks" / "jarvis-remotion-presentation-integration" / "slices"
            / "15-remotion-one-shot-authoring" / "evidence")
#: Rules the careless author does not break one by one: they need their own set-up (see the unit tests) or are warnings.
NOT_IN_THE_TABLE = ("brief_invalid", "draft_schema", "document_invalid", "scene_unbound", "candidates_count",
                    "candidates_not_divergent", "placeholder_allowed", "motion_unguarded", "behavior_risky", "tsx_live_ref_invalid",
                    "tsx_live_ref_unresolved", "tsx_inspiration_unconfirmed", "tsx_static_scene", "tsx_props_undeclared",
                    "tsx_interpolate_unclamped", "tsx_monolith", "tsx_color_hardcoded", "tsx_layout_monotone", "tsx_compile_budget", "tsx_lint_budget")


def _attached_programs() -> list[str]:
    from jarvis.runtime.prompt_catalog import default_prompt_registry

    return sorted(p.program_id for p in default_prompt_registry().programs if any(step.prompt_id == PROMPT_ID for step in p.steps))


def _codes(report: dict[str, Any], key: str) -> list[str]:
    return sorted({f["code"] for f in report[key]})


async def _scenario(env: AuthoringEnv, name: str, brief: dict, draft: dict) -> dict[str, Any]:
    checked = (await env.check(brief, draft)).body["report"]
    outcome = await env.assemble(brief, draft)
    row: dict[str, Any] = {"scenario": name, "workflow": brief["workflow"], "check_ok": checked["ok"],
                           "assemble": outcome.status, "http": outcome.http_status,
                           "errors": _codes(checked, "failures"), "warnings": _codes(checked, "warnings"),
                           "rules_checked": checked["rules"]["checked"], "skipped": checked["skipped"], "stats": checked["stats"]}
    if outcome.status == "delivered":
        body = outcome.to_dict()
        row.update(variants=len(body["variants"]), draft_variants=sum(v["draft"] for v in body["variants"]),
                   scenes=len(body["scenes"]), published_prefabs=len(body["prefabs"]),
                   da_origins=[a["origin"] for a in body["provenance"]["art_directions"]],
                   da_fallback=[a["fallback"] for a in body["provenance"]["art_directions"]])
    return row


def _attested(prefab_id: str) -> dict[str, Any]:
    """A library Remotion source whose upstream provenance Core verified (what the Slice 18 importer writes, saved with `verified_import`)."""

    candidate = fa.candidate(prefab_id)
    candidate["manifest"]["schema_version"] = 3
    candidate["manifest"]["catalog"] = {
        "type": "composition", "compatibility": {"remotion": "native", "slidecar": "unsupported"}, "stack": ["react", "remotion", "typescript"],
        "license": "MIT", "upstream": {"name": "someone/demo", "url": "https://github.com/someone/demo", "license": "MIT", "commit": "a" * 40,
                                       "archive_sha256": "b" * 64, "imported_at": "2026-10-10T12:00:00Z", "changes": ["entry generated"],
                                       "source_sha256": "c" * 64}}
    return candidate


async def remotion_context(root: Path) -> dict[str, Any]:
    """Slice 15, scripted: the Board context an agent fetches before asking (the active Board), a draft with live references authorised from it,
    an inspiration with verified provenance, and the compile refusal. Redacted: codes, states and counts only."""

    from tests.fakes.remotion_authoring import ScriptedLiveRefs

    live = ScriptedLiveRefs(present=frozenset({"kpi.json"}))

    async def active_board() -> frozenset[str]:
        return frozenset({"default"})            # what `JarvisCoreApplication._authorised_boards` returns: the Board the user works with

    env = await AuthoringEnv(root / "ctx").start(live_refs=live, boards=active_board)
    await env.prefabs.save(_attested("lab.upstream-demo"), actor="user", verified_import=True)
    env.sink.rows.clear()

    def refs(board: str) -> tuple[dict, dict]:
        brief, draft = fa.good_one_shot()
        draft["prefabs"][0]["remotion"]["live_refs"] = [{"name": "kpi", "ref": f"board:{board}/memory/kpi.json"}]
        return brief, draft

    rows: dict[str, Any] = {}
    delivered = await env.assemble(*refs("default"))
    rows["live_refs_active_board"] = {"assemble": delivered.status, "authorised_boards_seen": [sorted(b) for b in live.authorised_seen],
                                      "references_resolved": len(live.asked)}
    other = await env.assemble(*refs("board_other"))
    rows["live_refs_other_board"] = {"assemble": other.status, "errors": _codes(other.body["report"], "failures"),
                                     "states": [m.split("(")[-1].rstrip(")") for f in other.body["report"]["failures"] for m in f["message"].split(", ")][:2]}
    brief, draft = fa.good_one_shot()
    draft["prefabs"][0]["remotion"]["inspiration"] = {"id": "lab.upstream-demo", "version": 1}
    inspired = await env.assemble(brief, draft)
    body = inspired.to_dict()
    rows["inspiration_verified"] = {"assemble": inspired.status, "published_origin": body["prefabs"][0]["origin"],
                                    "inspirations": [{k: row[k] for k in ("upstream", "license", "verified_intact")} for row in body["provenance"]["inspirations"]]}
    brief, draft = fa.good_one_shot()
    draft["prefabs"][0]["remotion"]["inspiration"] = {"id": "lab.remotion", "version": 1}
    unverified = await env.assemble(brief, draft)
    rows["inspiration_unverified"] = {"assemble": unverified.status, "errors": _codes(unverified.body["report"], "failures")}
    before = (env.folders(), env.prefab_versions())
    brief, draft = fa.violate("tsx_compile")
    refused = await env.assemble(brief, draft)
    failure = next(f for f in refused.body["report"]["failures"] if f["code"] == "tsx_compile")
    rows["compile_refusal"] = {"assemble": refused.status, "http": refused.http_status, "code": failure["message"].split(":")[0],
                               "diagnostic_fields": sorted(failure["diagnostics"][0]), "written_by_this_draft": (env.folders(), env.prefab_versions()) != before}
    return rows


async def run() -> dict[str, Any]:
    root = Path(tempfile.gettempdir()) / "s11rig"
    shutil.rmtree(root, ignore_errors=True)
    scenarios: list[dict[str, Any]] = []
    try:
        for name, (brief, draft) in (("good one-shot (report display)", fa.good_one_shot()),
                                     ("good 12-scene directed deck", (fa.brief("directed"), fa.good_deck())),
                                     ("exploratory, 3 divergent candidates", fa.exploratory(3))):
            env = await AuthoringEnv(root / f"s{len(scenarios)}").start()
            scenarios.append(await _scenario(env, name, brief, draft))
        careless = []
        for code, _ in fa.VIOLATIONS:
            env = await AuthoringEnv(root / f"v{len(careless)}").start()
            brief, draft = fa.violate(code)
            outcome = await env.assemble(brief, draft)
            report = outcome.body["report"]
            careless.append({"violated": code, "assemble": outcome.status, "http": outcome.http_status,
                             "errors": _codes(report, "failures"), "caught": code in _codes(report, "failures"),
                             "written": bool(env.folders() or env.prefab_versions())})
        context = await remotion_context(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return {
        "remotion_context": context,
        "disclaimer": "Scripted rig, not a model trace. The real-model trace analysis (does Claude follow the policy, how many tool calls, "
                      "do the questions stay in the budget, is the first draft respectable) is a required gate of Slices 21 and 22, "
                      "re-run for Remotion scenes by Slice 15 (see the real-trace evidence of that Slice).",
        "prompt": {"id": PROMPT_ID, "fingerprint": PROMPT_FINGERPRINT, "characters": len(PLANNER_PROMPT),
                   "operations": [OP_CHECK, OP_ASSEMBLE, OP_FINALIZE],
                   # Slice 21 attached it to the conversation programs that declare `jarvis-presentation` (the `studio` ones).
                   "attached_to_a_program": bool(_attached_programs()), "attached_programs": len(_attached_programs())},
        "rules": len(RULES), "question_cap": {w.value: n for w, n in QUESTION_CAP.items()},
        "workflow_choice": {name: choose_workflow(signals).workflow.value for name, signals in (
            ("vague + asks for ideas", RequestSignals(asks_inspiration=True)),
            ("well briefed deck", RequestSignals(has_audience=True, has_purpose=True, has_content=True, has_duration=True)),
            ("report to display now", RequestSignals(is_info_display=True)))},
        "scenarios": scenarios, "careless_author": careless,
        "careless_author_covers": sorted(c for c, _ in fa.VIOLATIONS),
        "rules_exercised_elsewhere": sorted(NOT_IN_THE_TABLE),
        "kill_drills": "see tests/unit/test_presentation_studio_authoring_crash.py (real Popen.kill at: before publication, after a "
                       "published bundle, documents built, inside the store write x3, right after the commit)",
    }


def render(result: dict[str, Any]) -> str:
    lines = ["# Slice 15 - fake-author rig evidence, Remotion scenes (redacted)", "", f"> {result['disclaimer']}", "",
             f"Planner prompt `{result['prompt']['id']}`: {result['prompt']['characters']} characters, content fingerprint `{result['prompt']['fingerprint'][:16]}...` (path-independent: the registry's own `default_revision` also hashes the source path), "
             f"operations `{'`, `'.join(result['prompt']['operations'])}`, attached to a prompt program: {result['prompt']['attached_to_a_program']}.",
             f"Gate: {result['rules']} rules. Question cap: {result['question_cap']}.", "", "## Scripted authors", "",
             "| Scenario | Workflow | Check ok | Assemble | Errors | Warnings | Variants (draft) | Scenes | Prefabs | DA origin |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in result["scenarios"]:
        lines.append(f"| {row['scenario']} | {row['workflow']} | {row['check_ok']} | {row['assemble']} ({row['http']}) | "
                     f"{', '.join(row['errors']) or '-'} | {', '.join(row['warnings']) or '-'} | "
                     f"{row.get('variants', '-')} ({row.get('draft_variants', '-')}) | {row.get('scenes', '-')} | "
                     f"{row.get('published_prefabs', '-')} | {', '.join(row.get('da_origins', [])) or '-'} |")
    lines += ["", "## The careless author: one rule broken at a time", "",
              "| Violated rule | Assemble | Errors raised | Caught | Anything written |", "| --- | --- | --- | --- | --- |"]
    for row in result["careless_author"]:
        lines.append(f"| `{row['violated']}` | {row['assemble']} ({row['http']}) | {', '.join(row['errors'])} | {row['caught']} | {row['written']} |")
    ctx = result["remotion_context"]
    lines += ["", "## Remotion context (Slice 15): Board context, inspiration, compile refusal", "",
              "| Scenario | Result |", "| --- | --- |"]
    for name, row in ctx.items():
        lines.append(f"| {name} | {', '.join(f'{k}: {v}' for k, v in row.items())} |")
    lines += ["", f"Rules exercised by their own unit tests rather than by this table: {', '.join(result['rules_exercised_elsewhere'])}, "
              "and every warning-level rule.", "", f"Kill drills: {result['kill_drills']}.", ""]
    return "\n".join(lines)


def main() -> None:
    result = asyncio.run(run())
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "fake-author-rig.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (EVIDENCE / "fake-author-rig.md").write_text(render(result), encoding="utf-8")
    print(f"wrote {EVIDENCE}", file=sys.stderr)


if __name__ == "__main__":
    main()
