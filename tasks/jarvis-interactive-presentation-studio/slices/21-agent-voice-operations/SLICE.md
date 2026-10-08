# Slice 21 - Agent, Voice and UI Operations for Presentation Studio

## Goal
Expose the complete Presentation Studio through stable semantic operations so natural voice requests and GUI actions manipulate the same model.

## Context
Jarvis remains the center of the interaction. The user should be able to say "show all variants", "open 37", "make a variant", "compare these four", "make the purple colder", "rehearse from the product scene", etc.

## Canonical Concepts
Stable runtime IDs, constrained choices, semantic operation, Tool Brain seam, voice/UI parity.

## Scope
### In Scope
- Agent/tool operations for artifact open/present/edit.
- Fullscreen enter/exit.
- Scene/score navigation.
- Semantic edits.
- Variant/tree/compare/mix operations.
- Scene-local variant operations.
- Rehearsal and presenter-role commands.
- Promotion to template/prefab.
- Dynamic valid choices/current-state introspection.
- Integrate canonical Tool Brain intent path when available.

### Out of Scope
- New generic natural-language router architecture.

## Dependencies
- `05-semantic-edit-api`
- `12-playback-runtime`
- `16-presentation-variants-domain`
- `17-scene-local-variants`
- `19-variant-compare-mix`
- `20-template-prefab-promotion`

## Implementation Steps
1. Reuse the repository's semantic MCP/tool catalog conventions.
2. Prefer stable IDs/enums supplied from current state.
3. Keep destructive branch deletion behind canonical confirmation policy.
4. Ensure visual commands are silent by default under PRESENTATION policy unless speech adds value.
5. Add targeted inspect/read operations instead of bloating every tool payload.
6. Correlate operations with canonical observability/timeline events.

## Files Likely Touched
Agent tool/MCP schema, Presentation policy adapters, Tool Brain integration, tests.

## Architecture Constraints
Do not make the model invent scene/variant IDs. Do not create a second UI tool scheduler.

## Automated Validation
Tool schema tests, dynamic-choice tests, natural-language/trace scenarios, destructive confirmation, voice/GUI parity, Presentation silence-policy regression.

## Acceptance Criteria
All major Presentation Studio operations are accessible to Jarvis with stable semantic contracts and without bypassing existing UI/authority policies.

## Documentation Updates
Agent/MCP operation reference and examples.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; agent runtime changes require real trace evidence.


## Slice 11 carry-forward (added by Slice 11, binding for this Slice)

Slice 11 delivered the deterministic authoring planner (`docs/presentation-studio.md` > *Authoring contract (Slice 11)*): the draft schema, the first-draft quality gate, the atomic assembly, the workflow choice, the question budget and the registered planner prompt `presentation_studio.authoring.planner`. **It could not and did not measure the real model**: its evidence is a scripted rig (`slices/11-authoring-planner-first-draft/evidence/`). This Slice owns the MCP tools, so the real-model trace is its gate.

1. **Expose the two operations** Core already serves: `POST /v1/presentation-studio/authoring/check` (dry run, `presentation_draft_check`) and `.../assemble` (`presentation_draft_assemble`); `OP_CHECK` / `OP_ASSEMBLE` in `presentation_studio_authoring_policy.py` are the proposed names (amend `09-canonical-names.md` section 6 if you rename them and pin the mapping in the catalogue parity test). `LocalCoreClient.presentation_studio_authoring_*` returns a refused draft as a result with its complete `report`, not as an exception: the tool must hand that report to the model verbatim.
2. **Be the only `brain` door.** Core accepts `actor: "brain"` on these routes (it is recorded as the creator of the variants); the Control Center relay forces `user`. The tool layer sets `brain`.
3. **Append the planner prompt to the program** that declares the presentation tools (`default_prompt_registry()` registers it today with no program step), keep the byte budget of the new server in view (prompt <= 9 000 characters, the schemas are the larger cost), and add the prompt-parity test for that attachment.
4. **Real-model trace analysis (agent-trace-analysis), required before this Slice closes**, with a real Claude brain and the real tools. Record: prompts, tool calls and arguments, results, retries, questions asked, final answer, call count and latency. Scenarios: rich brief; missing context; linked DA source (the model inspects, passes `mode: signals`, asks nothing about colours); vague exploratory prompt (2 to 6 genuinely different candidates, shown as drafts); one-shot report (no question, one transaction); serious final deliverable (`directed`, near-presentable, the quality gate passes in at most `MAX_FIX_ROUNDS` rounds); no DA found (the `fallback` is announced); two conflicting brands (one question, with the options found); a refused draft and the single correcting round; hostile text in a project file or a reference title (kept as data, never obeyed, never copied into a style or an action).
5. **Slice 09 trace scenarios** (inspect then derive without asking; fallback created and announced when the project has nothing; one question when two brands conflict; a serious variant with no DA handled by the fallback and said; hostile reference text) and **the untrusted-title line**: a prompt that interpolates a reference `title`, a score `text` / `note` or a project file's text must fence it as data (possibly multi-line, possibly instruction-looking or CSS-looking) and give that turn no tool authority.
6. **Never let the model invent ids.** Scenes, variants, controls and prefab pins come from tool results (`assemble` returns every id it allocated; a pin comes from a prefab search); keep trace evidence that none was typed from memory.
7. **Questions stay inside `question_budget`** (0 for `one_shot`, 1 for `exploratory`, 3 for `directed`, none before the sources were inspected): count them in the trace.
