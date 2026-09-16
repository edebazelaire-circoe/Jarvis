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

## 2026-09-16 — Slice 01 implementation (conversation event contract)

- Contract: `docs/conversation-events.md`; implementation `jarvis/domain/conversation_events.py` (pure domain, schema_version 1, strict codec modeled on `voice_event_codec.py`, IDs reuse `voice_state.state_id`).
- Vocabulary: actors `user, mouth, brain, subagent, tool, system`; 23 event types (24 after rework) grounded in existing journal kinds / bus envelopes (mapping table in the contract doc).
- Identity: `cev-` + sha256 of `["conversation-event", producer, event_type, conversation_id, *source_ids]`. Duplicate identical = no-op; same id different payload = `ConversationEventConflictError`.
- Time: UTC ISO-8601 ms on the wire; canonical order = store sequence (Slice 02), `(occurred_at, event_id)` fallback. Spans pair by `(open type, span_id)`, `span_id` = speech_id / work_id / task_id / call id.
- `trace_id` not introduced: `trace_ref {source, journal_kind, join_keys}` join contract + `data.conversation_event_id` (to be written by Slice 03). `agent.event` rejected as a trace source.
- Redaction: allowlisted attribute keys + recursive forbidden-key scan (reasoning/thinking/prompt/secret/audio/bytes/arguments...), bounded content/attributes.
- Deviations from SLICE.md: `generation_id` and `channel` not added (no such id/concept in producers; `producer` + `actor` cover channel). `jarvis/protocol/*` untouched (no HTTP in this Slice). Added `brain.work.cancelled` and `subagent.stopped` so real terminal states close spans.
- Documentation level: canonical conversation event envelope 0 → 3; trace correlation 1 → 2 (contract + pure join helper; producers not instrumented).

### 2026-09-16 — Slice 01 rework (QA APPROVE_WITH_ISSUES, PM should-fix items)

1. Trace join: `outcome_id` added as optional envelope id + `TRACE_JOIN_FIELDS`; required on `brain.message.published` (several `core.brain.outcome_retained` lines per correlation). Removed from attribute allowlist. Tool events: `trace_ref` with `join_keys` rejected (lines carry only `{call_id, arguments}`); Slice 04 obligation: never render raw `tool.call`/`tool.result` lines unredacted. `agent.subagent.*` has no `conversation_id`: Slice 03 maps task → conversation.
2. Hygiene: lone surrogates in content / attribute strings / ids / source_ids raise `ConversationEventError`; message field names escaped. Redaction scan capped at `MAX_PAYLOAD_DEPTH = 8` (5000-deep and cyclic payloads raise `ConversationEventError`, not `RecursionError`).
3. Retry semantics documented and tested: `occurred_at` = fact time; retry with emission time conflicts; duplicate admissions (`duplicate: true`) are not re-emitted; store conflict policy = keep first, diagnostic, producer not failed (Slice 02).
4. `mouth.speech.failed` (close, diagnostic) ← `voice.speech.speak_failed`. Unknown sub-agent statuses → `subagent.failed` with raw `attributes.status`. Reflex stays instant (no terminal journal kind).
5. `content` forbidden on `brain.turn.failed` and `system.failure`.
6. `reconstruct_conversation` never raises on data: earliest open/close kept, close-before-open clamped, first copy of a conflict kept, `ConversationItem.anomalies` (`duplicate_span_open|duplicate_span_close|close_before_open|conflicting_duplicate:<event_id>`). Raises only on non-event input / mixed conversations.
7. `attributes` is a `MappingProxyType` (lists → tuples); events hash by `event_id`. Doc: exact id comparison (no Unicode normalization), consumers cannot verify `event_id`. Both user-turn sources listed (`voice.brain_turn_submitted` live; `core.voice.turn_admitted` 0 live lines); fixture uses one of each.

PM answers to Slice 01 open questions:
- Q1: mouth `content` stays sent-for-playback text; Slice 06 readable transcript must use the heard projection (documented).
- Q2: single `user.transcript.accepted` producer, Core admission preferred, decided in Slice 03 with live evidence.
- Q3: Slice 03 must pick a stable sub-agent source id.
- Q4: resolved by item 6.
- Q5: documentation-levels update owned by PM.

## 2026-09-16 — Slice 02 implementation (durable event store)

- Substrate as decided in Slice 00: `conversation_events` table in the Core state DB, state `schema_version` 1 → 2 via new `sqlite_state._MIGRATIONS` (forward-only, one `BEGIN IMMEDIATE` transaction per step, version re-read under the write lock; fresh files take the same path). No new DB file, no new connection: `SQLiteConversationEventStore` (`jarvis/adapters/sqlite_conversation_events.py`) runs on the repository connection/lock through new seam `SQLiteStateRepository.run_serialized`.
- Port `ConversationEventStore` in `jarvis/ports/v2.py` (next to `StateRepository`/`HistoryStore`); storage-neutral types, limits and retention policy in `jarvis/domain/conversation_event_store.py`. Contract addition: public `format_event_time` in `conversation_events.py` (wire formatting reused for query bounds and `recorded_at`).
- Schema: `sequence INTEGER PRIMARY KEY AUTOINCREMENT` (never reused, even after retention deletes the newest rows), `event_id UNIQUE`, extracted `conversation_id, session_id, event_type, actor, visibility, occurred_at, recorded_at, span_id, turn_id, correlation_id, task_id, work_id, speech_id, outcome_id`, `data` = encoded canonical JSON. Indexes `(conversation_id, sequence)`, `(occurred_at, sequence)`, partial `(<id>, sequence) WHERE <id> IS NOT NULL` for the 8 lookup ids (query plans checked). No FK to `conversations`.
- Append: codec-validated before storage; one transaction per batch (≤ 32); `appended | duplicate | conflict` result with stored sequence; conflict (and unreadable stored copy) keeps first + diagnostic `core.conversation_events.append_conflict` (warning, no content); storage error → rollback + `ConversationEventStoreError` (not acknowledged).
- Durability: WAL (existing) + `PRAGMA synchronous=FULL` now set explicitly (was the build default 2, so no behaviour change). Busy timeout = sqlite3 default 5 s.
- Reads: every row decoded through the codec + column cross-check; bad rows skipped, counted (`skipped_rows`, `unreadable_rows`), diagnosed once per sequence (`core.conversation_events.row_unreadable`). Cursor = last scanned sequence. Limits: events 1..500 (default 100), summaries 1..100 (default 50), batch 32, retention ≤ 64 conversations/run.
- Retention: `ConversationEventRetentionPolicy` disabled by default, not scheduled; prunes only `closed` conversations, idle by Core `recorded_at`, all spans closed, no new activity (re-checked in the delete transaction), optional archive hook (failure keeps events). Never touches other tables.
- Composition: `JarvisCoreApplication.conversation_events` constructed only. `tests/unit/test_v2_architecture.py` `CORE_ADAPTER_IMPORT_EXCEPTIONS` for `v2_app.py` extended with `jarvis.adapters.sqlite_conversation_events` (deliberate, PM-sanctioned wiring).
- Side improvement: `_initialize_sync` now closes its connection when initialization fails (newer schema, quick_check, migration error) instead of leaking it.
- Tests: `tests/unit/test_conversation_event_store.py` (35), `tests/integration/test_conversation_event_store_recovery.py` (2: child process `os._exit` inside the 3rd INSERT of a batch; read-only backup copy of `data/state/jarvis.sqlite3` migrated with row counts preserved), fixture `tests/fixtures/sqlite_state/state_v1.sql` (v1 DDL dumped verbatim from the real DB + synthetic rows), helpers `tests/fakes/conversation_events.py`. Mutation check: dropping `AUTOINCREMENT` fails the sequence-reuse test.
- Validation (`PYTHONDONTWRITEBYTECODE=1`, `-W error::ResourceWarning -p no:cacheprovider`): new + contract + persistence + architecture + integration async-conversation/core-recovery/recovery-notifications → 204 passed; full suite → 3549 passed, 5 skipped (302 s); `scripts/verify_release.py` → 3549 passed, 5 skipped, "Release verification passed.".
- Deviations: none from PM decisions. Additions: `run_serialized` seam, `format_event_time`, `recorded_at` column (Core clock for retention age). Not done: summary table (aggregates are computed per query), time-range overlap semantics (range matches `occurred_at` instants only; documented).
- Operational note: `data/state/jarvis.sqlite3` is git-tracked and live. The next Core start with this code migrates it to v2 in place (the file will show as modified); an older Core binary then refuses it (`newer than supported`).
- Open for Slice 03/04: cross-process access only via Core (voice runtime and Control Center must go through Core protocol; the DB file must not be opened by them — concurrent connections are safe but ownership is Core's); producer policy on `ConversationEventStoreError` (retry/drop + diagnostic) is Slice 03's; Slice 04 routes map `ValueError` → 400 and should expose `skipped_rows`/`has_more`/`next_cursor`; `get_event` returns None for an unreadable row (diagnosed); retention scheduling and archive destination undecided.

### 2026-09-16 — Slice 02 rework (QA APPROVE_WITH_ISSUES, PM items S1–S3, N1–N6)

1. S1 summaries: `_summary` parses aggregated times with the strict `parse_event_time`; a group that does not parse is skipped, counted in new `ConversationEventSummaryPage.skipped_summaries` and diagnosed once per `(conversation_id, session_id)` as `core.conversation_events.summary_unreadable` (error, no value). Cursor comes from the integer sequence columns, so paging passes the skipped group. `event_count` documented as raw row count. Retention treats unparseable times as blocked (never deleted).
2. S2 retention starvation: one SQL predicate `_CANDIDATES` computes per closed conversation the `open_span` flag (open event without a matching close type for its span_id) and `unreadable` flag (unknown event_type, invalid JSON, non-wire occurred_at/recorded_at). Blocked conversations are excluded before the per-run budget and counted in new `RetentionReport.blocked_open_span` / `blocked_unreadable`; an unparseable calendar time is also blocked without consuming budget. The delete transaction re-evaluates the same predicate (new skip reason `unreadable`). Orphaned spans stay blocking forever: documented known limit, never auto-closed.
3. S3 pre-migration backup: `_backup_before_migration` copies an existing (non-fresh) DB with `Connection.backup` to `<db>.v1.bak` (via `.partial` + rename) before any schema statement; an existing `.bak` is kept; failure raises `RuntimeError` and leaves the file v1. Rollback procedure and the git-tracked `data/state/jarvis.sqlite3` / untracked `.v1.bak` implication documented in `docs/state-model.md`.
4. N1: `list_conversations` walk can omit conversations that receive events between pages (documented). N2: `run_serialized` rolls back after a failing callback and rolls back + raises `RuntimeError` when a callback returns inside a transaction. N3: `recorded_at` = clock at `append*` call, not commit. N4: adapter `_parse_wire_time` removed; public `parse_event_time` in `conversation_events.py`. N5: real-DB copy test gated by `JARVIS_TEST_REAL_STATE_DB=1` (skipped by default; passes when opted in). N6: new `sqlite_state.rollback_after_failure` attaches a failing ROLLBACK as a note to the original exception (used by `_migrate`, `run_serialized`, store append and retention).
5. Tests added (store unit file now 48 cases, integration 2): strict time parse; summary skip/cursor/diagnose-once; retention blocked by 4 unreadable kinds; starvation (3 orphaned spans + 3 prunable, budget 3 → 3 pruned, stable on rerun); in-transaction re-check (`unreadable`, `open_span`); backup created once / not for fresh DB / never overwritten / failure aborts with v1 intact; `run_serialized` transaction guard; failing ROLLBACK does not mask the migration error. Mutation checks: budget-before-blocker and removing the transaction guard each fail their test.
6. Validation: store unit + integration + contract + `test_v2_persistence` + `test_v2_architecture` + `test_v2_core_recovery` → 199 passed, 1 skipped (opt-in real DB). Full `-W error::ResourceWarning` suite: first run 3560 passed, 6 skipped, 1 failed (`test_v2_async_conversation.py::test_three_turns_run_in_one_session_without_a_second_wake`, its 10 s harness wait expired on a slow run: 404 s vs 302 s before; the file, untouched by this Slice, then passed 16/16 three times); `scripts/verify_release.py` → 3561 passed, 6 skipped, "Release verification passed."; clean rerun of the full `-W error::ResourceWarning` suite → 3561 passed, 6 skipped (485 s). Timing-sensitive test noted, not a regression of this Slice.
