# 05 - Event Contracts

All cross-process Core events remain `ProtocolEnvelope` objects. Every brain event must carry `conversation_id`; work/speech events should also carry a stable `correlation_id` and explicit `work_id` / `speech_id` where relevant.

## `brain.turn.accepted`

Purpose: acknowledge that Core persisted and accepted an authoritative completed user turn for brain processing.

Suggested payload:

```json
{
  "turn_id": "...",
  "provider_item_id": "...",
  "revision": 7,
  "interrupted_speech_id": null
}
```

## `brain.state.updated`

Purpose: publish a safe structured state revision for diagnostics/UI/rehydration.

Suggested payload:

```json
{
  "revision": 8,
  "current_user_intent": "Restrict the search to Paul's emails",
  "active_work_ids": ["work-1"],
  "unresolved_question_count": 0,
  "completed_work_count": 2
}
```

Do not put raw hidden reasoning in this event.

## `brain.speech.requested`

Purpose: request natural-language speech from the currently active voice surface.

Suggested payload:

```json
{
  "speech_id": "speech-123",
  "text": "I found the relevant thread. I am checking which messages still need a reply.",
  "kind": "progress",
  "priority": "normal",
  "work_id": "work-1",
  "supersedes_key": "work-1-progress",
  "interruptible": true,
  "expires_at": "2026-09-08T20:15:00+00:00",
  "provenance": "brain"
}
```

## `brain.work.started`

Suggested payload:

```json
{
  "work_id": "work-1",
  "job_id": "job-1",
  "kind": "mail_search",
  "public_label": "Search relevant email"
}
```

## `brain.work.progress`

Suggested payload:

```json
{
  "work_id": "work-1",
  "job_id": "job-1",
  "phase": "cross_checking_calendar",
  "fraction": null,
  "public_summary": "Relevant messages found; cross-checking meetings"
}
```

`public_summary` is optional and must already be safe for user-facing use. Workers should not automatically create speech; the brain decides whether progress merits speech.

## `brain.work.completed`

Suggested payload:

```json
{
  "work_id": "work-1",
  "job_id": "job-1",
  "result_ref": "...",
  "public_summary": "Three messages need a reply"
}
```

## `brain.work.failed`

Suggested payload:

```json
{
  "work_id": "work-1",
  "job_id": "job-1",
  "error_class": "provider_unavailable",
  "public_summary": "I could not reach the mail source."
}
```

Do not place secrets or raw exception dumps in user-facing fields.

## `brain.intent.revised`

Purpose: tell downstream consumers that previous queued speech/work interpretation may be stale.

Suggested payload:

```json
{
  "revision": 9,
  "previous_revision": 8,
  "superseded_work_ids": [],
  "cancelled_work_ids": [],
  "retained_work_ids": ["work-1"]
}
```

## Voice delivery telemetry

These can remain local journal events unless Core needs them:

- `voice.speech.queued`
- `voice.speech.started`
- `voice.speech.completed`
- `voice.speech.interrupted`
- `voice.speech.expired`
- `voice.speech.superseded`

If assistant speech is persisted, use the normal conversation-turn API with provenance metadata rather than inventing a second transcript store.

2026-09-16: the conversation timeline projection of these events (and of the `brain.*` events above) is specified in [`docs/conversation-events.md`](../../conversation-events.md). It references the heard history; it does not replace it.
