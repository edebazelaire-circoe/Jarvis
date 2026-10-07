# ISSUE-01 - `BrainOrchestrator.publish_ui_intent` was lost on main (Tool Brain `ui_intent_publish` channel is broken)

Discovered in Slice 00 (BASELINE), root-caused in Slice 01 (`docs/07-integration-map.md` section 10). Outside the studio Slices: **not caused by this task, do not mask, do not fix inside a studio Slice.**

## Symptom
`tests/unit/test_tool_brain_intents.py`: 3 failed, 32 passed (re-run 2026-10-07 in worktree `bips`):
`AttributeError: 'BrainOrchestrator' object has no attribute 'publish_ui_intent'` raised from `jarvis/protocol/server.py:662`.
Also broken: `GET /v1/ui-intents` (`server.py:676` calls `core.brain.list_ui_intents`), MCP tool `ui_intent_publish` (answers `display_internal_error`),
and `jarvis/runtime/tool_brain_wiring.py:180` (`core.brain.list_ui_intents`) as soon as `JARVIS_TOOL_BRAIN` is `shadow` or `active`.

## Root cause
- `33b3fea9` (S4 of the Tool Brain handoff) added to `jarvis/core/brain_service.py`: imports `UiIntentRefused, UiIntentRegistry` and `UiIntentDraft`, `self.ui_intents = UiIntentRegistry(clock=utc_now)` in `__init__`, and the methods `publish_ui_intent` and `list_ui_intents` (+46 lines).
- All of it is present through `5ee43450` (merge of `task/jarvis-tool-brain-ui-orchestrator`), `73144880`, `d53c0bd4`.
- Commit **`9721b3ca`** ("no message", `edebaze <e.debaze@gmail.com>`, 2026-10-07 16:54, single parent `d53c0bd4`) rewrote `brain_service.py` for the agenda-reminders feature and, at exactly the S4 insertion points, removed those imports, the registry line and both methods
  (it replaced the block by `last_user_turn_at` / `wake_for_agenda`). No other S4 file was touched by it. Pattern = a file derived from a base that predates S4/the Tool Brain merge (stale-copy overwrite or lost merge side). Intent unknown; inference only.
- The method still exists on `feat/mik-s02..s10a`, `task/jarvis-memory-intelligence-knowledge` and `task/jarvis-tool-brain-ui-orchestrator`. **Merging those into main will not restore it** (main's side deleted the lines after their merge base).

## Proposed repair (small, one commit, on a `fix/` branch from the current main, by the PM; both capabilities must coexist)
1. Re-apply the S4 hunks of `git show 33b3fea9 -- jarvis/core/brain_service.py` next to the agenda code: the two imports, `self.ui_intents = UiIntentRegistry(clock=utc_now)`, `publish_ui_intent`, `list_ui_intents`. Keep `wake_for_agenda` / `last_user_turn_at` untouched.
2. Run, one file at a time: `tests/unit/test_tool_brain_intents.py`, `tests/unit/test_tool_brain_contracts.py`, `tests/unit/test_tool_brain_wiring.py`, `tests/unit/test_conversation_events.py`, `tests/unit/test_agenda_reminders.py`, `tests/integration/test_agenda_reminders_core.py`, `tests/unit/test_mcp_catalog.py`.
3. Add a guard so a silent loss cannot recur: a unit test asserting that `BrainOrchestrator` exposes `publish_ui_intent` and `list_ui_intents` with the signatures `jarvis/protocol/server.py` calls (the current symptom is detected only by the three integration-style tests).
4. Tell the Human: the live checkout has the same defect, and the agenda commit came from a second author identity/machine (stale base risk for other files: `git diff 5ee43450 9721b3ca --stat` shows 13 files, only `brain_service.py` lost Tool Brain code).

## Impact on the studio task
Slice 21 must not route anything essential through `ui_intent_publish`; it still closes only after this repair (it owns the trace evidence for the display tool surface and runs the catalog). No other studio Slice depends on it.
