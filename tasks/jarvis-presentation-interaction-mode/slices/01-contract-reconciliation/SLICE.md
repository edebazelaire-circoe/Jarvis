# Slice 01 — Reconcile Presentation contracts with current Jarvis

## Goal

Establish the exact canonical boundaries Presentation must use before behavior implementation.

## Context

Existing Jarvis work already references `presentation-audio-capture`, `presentation-ambient-lane`, `presentation-working-set`, interaction-mode persistence, conversation observability, Session/Context, Tool Brain and Scene/Prefab concepts. The task must consolidate rather than duplicate them.

## Canonical Concepts

Interaction mode, ambient lane, addressed turn, Session, Context, working set, Tool Brain intent, scene/prefab instance, conversation event.

## Scope

### In Scope

- Identify current owners/APIs/events for each concept.
- Mark which Presentation pieces already exist and which are missing/incomplete.
- Define canonical authority boundary between ambient speech and addressed Jarvis turns.
- Define integration seams for Tool Brain and Scene/Prefab without reimplementing them.
- Upgrade/repair dedicated Presentation docs where contracts are ambiguous.

### Out of Scope

- Implementing behavior beyond minimal contract/schema scaffolding required to make the boundaries testable.

## Dependencies

- `00-project-manager`

## Implementation Steps

1. Audit current Presentation and interaction-mode docs/source/tests.
2. Audit existing ambient transcription and explicit-address routing.
3. Audit canonical event/timeline contract.
4. Audit Tool Brain and Scene/Prefab public contracts or current task output.
5. Produce a single source-of-truth Presentation contract map.
6. Add/repair schemas/enums/events only where ambiguity would block later Slices.

## Files Likely Touched

Presentation docs/contracts, shared interaction-mode/event schemas, focused contract tests.

## Architecture Constraints

Do not create parallel Session, recording, UI-tool, scene or event models.

## Automated Validation

Schema/contract tests; static checks that no duplicate Presentation settings/event registries were introduced; documentation link checks where available.

## Acceptance Criteria

A fresh implementer can identify the canonical owner and API/event path for every dependency used by Slices 02–10.

## Documentation Updates

Bring Presentation contract docs to at least Level 2, and Level 3 where reusable validators/schemas already exist.

## Handoff Notes

If a dependency contract is still being implemented elsewhere, record the exact required public shape and gate only the affected adapter Slice.


## Slice 00 contract (binding)

Scope in:
- Fix `DisplaySceneStager.reveal` (`jarvis/runtime/presentation_staging.py:100`). It now calls `self._tools.update_object(object_id=object_id, visibility=Visibility.VISIBLE.value)`, which exists at `display_mcp.py:863`.
- Make the stager's fakes unable to hide drift: `tests/unit/test_presentation_speculative.py:189` and `tests/unit/test_presentation_integration.py:218` become specced against `SceneDisplayTools`.
- Fix the stale `scene_set_visibility` / `set_visibility` names in comments: `presentation_staging.py:26`, `domain/presentation_speculative.py:36,155,182`, `core/presentation_speculative.py:557,1148`, `runtime/presentation_runtime.py:149`.
- Write `docs/presentation-mode.md`, the index page. It holds:
  - the R0 owner map (links, not copies);
  - the HD↔D mapping (R1);
  - the gap→Slice table;
  - links from the 7 `docs/presentation-*.md` pages and `docs/interaction-mode.md`.
- Update `docs/presentation-speculative-preparation.md` (reveal path) and the `ACCEPTANCE_STATUS.md` row.

Scope out: any behavior beyond reveal; renaming; the timeline; Tool Brain/prefab code.

Files: `jarvis/runtime/presentation_staging.py`, the domain/core/runtime presentation modules (comments only), the two test fakes, the new `tests/unit/test_presentation_staging_contract.py`, `docs/presentation-mode.md`, `docs/presentation-speculative-preparation.md`, `docs/ACCEPTANCE_STATUS.md`.

Acceptance:
- `test_presentation_staging_contract.py::test_every_scene_tool_the_stager_calls_exists_on_scene_display_tools`:
  - AST-collect every `self._tools.<attr>(...)` in `presentation_staging.py`;
  - assert `hasattr(SceneDisplayTools, attr)`, that it is a coroutine function, and that each keyword passed is in `inspect.signature`.
  - Proven red on the pre-fix file.
- `::test_reveal_makes_the_hidden_object_visible_through_real_scene_tools`: real `SceneDisplayTools` over the in-process Core fixture used by `tests/unit/test_display_mcp.py`. Stage hidden, then reveal; the snapshot object's visibility is `visible`. Discard archives it.
- `::test_stager_fakes_are_specced`: both fakes are `create_autospec(SceneDisplayTools)`-based (or assert parity), so a removed method fails them.
- `::test_presentation_modules_do_not_name_removed_visibility_tool`: grep `jarvis/{domain,core,runtime}/presentation_*.py` for `scene_set_visibility` / `.set_visibility(` → none.
- All `tests/unit/test_presentation_*.py` and `test_display_mcp.py` green, unchanged otherwise.

QA tier: glue. Passes: qa-verification + code-review.

Not yours:
- the baseline failure list agent 0 hands over;
- the CRLF-only change in `tests/unit/test_interaction_mode_contract.py` (do not commit it);
- the prefab branch's Issue file (09 records it).

Depends on: 00.

Documentation: `docs/presentation-mode.md` reaches Level 2 (index + map); the reveal contract is Level 3 with the contract test.
