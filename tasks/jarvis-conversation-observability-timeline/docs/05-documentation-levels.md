# Documentation Levels

| Concept | Current observed level | Required level | Action |
|---|---:|---:|---|
| Runtime diagnostic journal (`trace.jsonl`) | 3 | 3 | Reuse; do not redefine as transcript truth. |
| Canonical conversation event envelope | 0/1 | 3 | Define schema, serializer, validator, producer API. |
| Conversation persistence/replay | 0/1 | 3 | Durable adapter + recovery + indexes/query contract. |
| Trace correlation from conversation events | 1 | 3 | Stable IDs and join contract. |
| Live transcript/timeline UI | 0 | 3 | Query/stream API + reusable timeline renderer + runtime QA. |

Slice 00 must correct these levels if the live repository has gained equivalent contracts since the inspected snapshot.

## Slice 00 live correction (2026-09-16, `main` 7ed67bb)

| Concept | Corrected observed level | Evidence |
|---|---:|---|
| Runtime diagnostic journal (`trace.jsonl`) | 2 | No schema/version/lock/rotation; concurrent writers corrupt lines. Still reuse as telemetry only. |
| Durable conversation history (`sqlite_state.turns`, `jsonl_history.py`) | 3 | WAL + schema_version, fsync JSONL; source for user / heard-assistant turns. |
| Canonical conversation event envelope | 0 (patterns at 2–3: `ProtocolEnvelope`, `voice_event_codec.py`) | No conversation event type exists. |
| Conversation event persistence/replay | 0 (substrate at 3: `sqlite_state.py`) | Reuse SQLite + schema migration. |
| Trace correlation | 1 | Many IDs, no `trace_id` / span. |
| Live transcript/timeline UI | 0 | Control Center is polling-only, plain JS. |

## After Slice 01 (2026-09-16)

| Concept | Level | Evidence |
|---|---:|---|
| Canonical conversation event envelope | 3 | `docs/conversation-events.md` + `jarvis/domain/conversation_events.py` + `tests/unit/test_conversation_events.py` (strict codec, redaction, fixtures). |
| Trace correlation | 2 | `trace_ref` join contract tested against real `trace.jsonl` lines; producer-side `conversation_event_id` pending Slice 03. |

## After Slice 02 (2026-09-16)

| Concept | Level | Evidence |
|---|---:|---|
| Conversation event persistence/replay | 3 | `ConversationEventStore` port, `sqlite_conversation_events.py`, schema v2 migration with `.v1.bak`, crash/restart/migration/retention tests, storage section in `docs/conversation-events.md` + `docs/state-model.md`. |

## After Slice 03 (2026-09-16)

| Concept | Level | Evidence |
|---|---:|---|
| Trace correlation from conversation events | 3 | Every emitting site writes `conversation_event_id` into its journal line; end-to-end test asserts each `trace_ref` joins exactly one line across Core, voice and Control Center journals. |
| Producer ownership (User/Brain/Mouth/tools/sub-agents) | 3 | Ownership table + forwarder/emitter guarantees and known limits in `docs/conversation-events.md`; producer, forwarder, backfill, attribution and timeline tests. |

## After Slice 04 (2026-09-16)

| Concept | Level | Evidence |
|---|---:|---|
| Conversation query / live API | 3 | Core + Control Center routes, cursor/long-poll/reconnect semantics, redacted drill-down allowlist, errors table in `docs/conversation-events.md` + ARCHITECTURE; 139 Slice 04 tests incl. reconnect, long-poll bounds, redaction with planted secrets. |
