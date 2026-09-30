# Slice 04b - Board switch transaction, speech authority, and Voice rebind

## Goal
Implement the atomic `switch_board` transaction in Core with rollback, the authoritative single-speech-authority gate, Board-scoped work context, and a live Voice rebind to the target Board's conversation. Voice binds directly to the active Board Brain; inactive Boards keep working but never speak.

## Dependencies
03, 04a

## Contract (from Slice 00; architecture `docs/06-resolved-architecture.md` sections D, F)
- `jarvis/core/board_service.py`: switch transaction under a lock: validate -> get/create binding (`session_manager`) -> `host.activate(target)` via the optional `ControlCenterBrainBackend` capability calling CC `POST /api/agent/bindings/activate` (failure: abort, nothing committed) -> apply target Board mode `source="board_switch"` (failure: re-activate previous, abort) -> one SQLite transaction -> in-memory speech authority -> publish `board.switched` and `board.voice_binding.changed`. Routes `POST /v1/boards/switch`; CC proxies `/api/boards*`, `/api/sessions*`.
- `jarvis/core/brain_service.py`: speech gate at `_emit_speech` (:1865) and `select_outcome` (:361) against the active conversation; refusal traced `core.brain.speech_withheld_inactive_board {board_id}`. `announce_notice` (:755) and `wake_for_work_attention` (~:870) target the active binding, not `_last_conversation_id`.
- Work context: `board_id` on `WorkItem`/`WorkObservation` (`domain/work_state.py`), set by each pool agent's observer (`work_ingress.py`); `BrainContextBuilder` keeps active-Board + untagged work; wakes only for active-Board work. Back-brain jobs tagged by resolving their conversation through bindings.
- `control_center_brain.py` `_turn_context` adds a bounded `board` block (title, summary, refs, ~2 KB).
- Voice: `SpeechScheduler` forwards `board.voice_binding.changed` before the conversation filter; `voice_v2.py` drains the current utterance, `mute(reason="board_switch")`, sets the conversation id, re-`activate()` (no Voice restart). Live path same close/reopen, respecting the one-unresolved-live-session index.
- Brain-originated switch/new session: `origin=brain` deferred by CC until the pending ask resolves.
- No low-level model-controlled bind_voice / attach_brain / speech-authority tools.

## Architecture Constraints
No global LLM Brain. No dual speech authority, including during rebind. No task cancellation from Board/session changes. UI/MCP never bypass runtime invariants.

## Automated Validation
qa-verification, code-review, runtime-validation, agent-trace-analysis with real traces. Tests: exactly one Board speaks (Core-level with stubbed voice + scheduler test), rollback on host failure and on mode failure, inactive notice/wake withheld and traced, work context filtered, voice rebind without restart, A/B/A with background work on A. Gate: `test_v2_speech_scheduler.py`, `test_v2_brain_orchestrator.py`, `test_live_*`, `test_voice_*`, `test_interaction_mode_*`, `test_brain_work_context.py`.

## Acceptance Criteria
Switching Boards while Voice is live moves speech authority atomically; the outgoing Board's work continues and never speaks; failures roll back with nothing committed; traces show exactly one authority at every instant.

## Documentation Updates
`docs/boards.md` switch/authority section; `docs/ARCHITECTURE.md` voice ownership; `docs/interaction-mode.md` if touched.

## Handoff Notes
Coding work loads /caveman and /coding-guideline.
