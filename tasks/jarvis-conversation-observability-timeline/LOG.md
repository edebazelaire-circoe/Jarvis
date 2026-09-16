# Execution Log

Reserved for durable notes written by the Project Manager and implementation/QA agents during execution. Do not treat this file as evidence until entries are added during implementation.

## 2026-09-16 — Slice 00 readiness audit

Readiness state: `READY` (after Human waiver of the Task Type gate, see below).

### Live repository

- Audited branch: `main` = `origin/main` = `7ed67bb09f4f9e1d63df793a23777904f6c63d13`. Task branch `task/jarvis-conversation-observability-timeline` created from it (no `dev` branch exists in this repository).
- Handoff snapshot `c33207281a5b` is stale: the 09-16 merge added `jarvis/runtime/background_events.py` (trace follower + notification pastilles) and the Barehands test mode.
- Worktrees: `.claude/worktrees/agent-a61c9d34042ce8a60` (`fix/wave-amplitude-orchestration-color`) and `../sub-agents/jarvis-agent-01` (`agent/jarvis-agent-01`); both branches are fully merged into `main` (no commits ahead). No conflict.
- Parallel handoffs: `tasks/handoffs/voice-speech-self-interruption.md` (voice arbitration) is paused since 09-16; it consumes `voice.speech.*` trace evidence and should adopt this task's contract later. `jarvis-settings-model-catalog-ux` is released (shares `control_center.html`).
- Drive: the connector cannot move folders; the `to-do` → `current` move must be done by the Human.

### Blind audit findings (independent of `docs/05-documentation-levels.md`)

- `RuntimeJournal` (`jarvis/runtime/journal.py`): `{ts, kind, level, message, data}`, no version/sequence/event id/`trace_id`, no fsync, no lock, no rotation. Written concurrently by UI, Voice, Core, Claude/Codex adapters and back-brain workers into one `runtime/trace.jsonl` (live: 14.4 MB, 15 interleaved/unparseable lines). Unsuitable as canonical record, confirmed.
- `agent.event` (`claude_local.py`) journals raw provider stream events **including thinking blocks** (Decision 43, `docs/OPERATIONS.md:411-435`). The conversation log must use an explicit allowlist and never ingest `agent.event`.
- Durable persistence already exists and is canonical: `jarvis/adapters/sqlite_state.py` (WAL, `schema_version` = 1, `quick_check`, `conversations`/`turns`/`brain_outcomes`/`voice_history_projections`…) and `jarvis/adapters/jsonl_history.py` (fsync daily JSONL of user + heard assistant turns, written by `ConversationService.append_turn`).
- Transport: in-memory `CoreEventBus` (`core/v2_services.py`, no replay/sequence) over Core WS `/v1/events`. Control Center (aiohttp, plain JS, no build, no prefab system) is **polling only** (1 s / 250 ms). `WorkStateStore`, `AgentTaskTracker`, `BackgroundEventLedger` are memory-only.
- IDs present: `conversation_id`, `session_id`, `correlation_id`, `turn_id`, `work_id`, `speech_id`, `output_id`, `segment_id`, `provider_item_id`, `outcome_id`, `task_id`, `tool_use_id`, `parent_id`, `call_id`, `job_id`. No `trace_id`/span concept. `ProtocolEnvelope` (`domain/v2.py:295`, `protocol_version=1`) and strict `voice_event_codec.py` are the envelope/codec patterns to follow.
- Producers: user (`voice.transcript`, `voice.brain_turn_submitted`, `core.voice.turn_admitted`), Brain (`core.brain.*` in `brain_service.py:63-90`, public `brain.*` bus envelopes; `BrainEvent` has no reasoning field by Decision 12), Mouth (`voice.speech.{queued,dispatched,started,completed,interrupted,expired,superseded}`, `voice.reflex.*` in `speech_scheduler.py:48-63`), sub-agents (`agent.subagent.started/finished` in `agent_tasks.py`, `core.work.updated`), tools (`tool.call`/`tool.result`, realtime only, raw args).
- Transcripts under `transcript/*.md` are hand-written, no producer.

### Reconciliation / planning corrections

- Documentation levels corrected: durable conversation history (SQLite `turns` + JSONL history) is level 3, not 0/1; speech lifecycle and sub-agent lifecycle contracts are level 3 (sub-agents memory-only). Conversation event envelope, trace correlation, live timeline UI remain 0–1.
- Slice 01: model the envelope on `ProtocolEnvelope` / `voice_event_codec.py` strict-codec style in `jarvis/domain/`; reuse existing IDs; `trace_id` is new and must be defined as a join contract to `RuntimeJournal` (journal entries may carry the conversation `event_id`). Visibility/redaction via allowlist.
- Slice 02: substrate = existing `sqlite_state.py` (new table(s) + schema migration 1→2 through the existing `schema_version` mechanism). No new storage technology. Monotonic store sequence is the cursor. JSONL history stays untouched.
- Slice 03: add `jarvis/core/voice_admission.py`, `jarvis/core/brain_service.py`, `jarvis/core/v2_services.py` to likely-touched files. Must resolve cross-process ownership: Core owns the store; non-Core producers (voice runtime, Control Center agent tracker) must reach it through existing Core protocol/client paths rather than opening the DB ad hoc. Never ingest `agent.event`; tool arguments redacted.
- Slice 04: Control Center has no push transport today. Cursor-based incremental query is mandatory; a push channel (SSE) is optional and must converge on the same cursor. New routes must be documented (guard `tests/unit/test_documented_routes.py`).
- Slice 05: plain-JS UMD module alongside `control_center_{work,catalog,barehands,live}.js`; `/impeccable` applies; `refacto-ui-prefab` does not (no prefab system).
- Slice order and dependencies unchanged.

### Workspace Task Type

- No Workspace Task Type vocabulary exists in the repository (`task_type` only appears as Claude CLI runtime kinds). Declared `HUMAN_DECISION_REQUIRED`.
- 2026-09-16 — Human decision: gate waived for this task, same as `jarvis-settings-model-catalog-ux`. `task_type` stays `null`; no fabricated values. Slice 00 → `READY`.

### Baseline validation

- Full gate (README/CI): `.venv/Scripts/python.exe -W error::ResourceWarning -m pytest -q` then `.venv/Scripts/python.exe scripts/verify_release.py`. `docs/BUILD_VERIFICATION.md` is stale (08-31) — not authoritative.
- Targeted baseline on `7ed67bb` (`PYTHONDONTWRITEBYTECODE=1`, no cache): trace summary, background events, error reporting, logging, event bus, agent tasks, work ingress/state/view, speech scheduler (+races), voice ledger/state, persistence, documented routes, all Control Center unit tests, work UI projection, async conversation → **519 passed, 0 failed**.
- Full suite deferred to the final integration gate and to every Slice touching shared runtime.

### Out-of-scope discoveries

- See `Issues/` for the trace.jsonl concurrent-write corruption and the stale BUILD_VERIFICATION doc.
