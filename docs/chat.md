# Chat (contract, Level 3)

A text conversation with the **same** Brain as voice: the Brain of the open
Session's active Board binding, reading and writing the **same** conversation.
The Chat is a projection of [conversation events](conversation-events.md) plus a
text ingress on the existing `brain-turns` route; it is not a second transcript,
a second Brain pipeline or a voice bridge.

Handoff `tasks/jarvis-unified-chat-and-board-drop/` (design record:
`docs/06-resolved-architecture.md` of that handoff). This page is **Level 3**:
the normative contract (written before the code, Level 2 at Slice 01), its
implementation and its conformance tests. Every rule names the test that holds
it: *Conformance* at the end of the page (test paths and names checked at the
Slice 10 HEAD), the *Test* column of *Error codes*, and a *Held by* line under
each known limit. A rule without a test says so. Routes at a glance: *Routes*
below. Operating (settings, state reading, diagnostics):
[OPERATIONS.md](OPERATIONS.md) › *Chat et dépôt sur le Board*; security
controls: [SECURITY.md](SECURITY.md) › control 22.

| Section | What it fixes | Code | Conformance tests | Slice |
| --- | --- | --- | --- | --- |
| *Projection* | which events the Chat shows and how | `jarvis/domain/chat_projection.py`, `jarvis/runtime/control_center_chat_model.js`, fixture `tests/fixtures/chat_projection/cases.json` | `tests/unit/test_chat_projection.py`, `tests/unit/test_control_center_chat_model_js.py` | 02 |
| *Reading* | `projection=chat` on the event routes, hydration and live | `jarvis/domain/conversation_event_query.py`, `jarvis/core/conversation_event_query.py`, `jarvis/runtime/conversation_event_view.py` | `tests/unit/test_chat_projection_query.py`, `tests/integration/test_chat_projection_protocol.py`, `tests/unit/test_control_center_chat_tabs_browser.py` | 05, 06 |
| *Sending text* | `POST /api/chat/turns` → `brain-turns` `source=text`, guards, idempotence | `jarvis/runtime/chat_relay.py`, `jarvis/protocol/server.py` | `tests/unit/test_chat_relay.py`, `tests/unit/test_chat_text_ingress.py` | 03 |
| *Text disposition* | no TTS for a text turn (`text_channel`) | `jarvis/core/brain_service.py` | `tests/unit/test_speech_text_channel.py` | 03 |
| *Voice channel* | Core-owned voice state, disable request, lock | `jarvis/domain/voice_channel.py`, `jarvis/core/voice_channel.py`, Voice side `jarvis/app.py` | `tests/unit/test_voice_channel_domain.py`, `tests/unit/test_voice_channel_service.py`, `tests/unit/test_voice_channel_protocol.py`, `tests/unit/test_voice_channel_reporter.py` | 04 |
| *Attachments* | upload route, bounds, sniffing, `brain_readable`, brief block, `artifacts_root` | `jarvis/domain/uploads.py`, `jarvis/core/upload_service.py`, `jarvis/protocol/upload_routes.py`; UI `jarvis/runtime/control_center_chat.js` + `control_center_chat_model.js` | `tests/unit/test_uploads_domain.py`, `tests/unit/test_upload_service.py`, `tests/unit/test_upload_protocol.py`, `tests/unit/test_chat_attachments_brain_context.py`, `tests/unit/test_control_center_chat_attachments_browser.py` | 07, 07b |
| *Board drop* | file or inert URL dropped on the displayed Board | same upload service, `kind = link`, `jarvis/runtime/control_center_board_drop.js` | `tests/unit/test_board_drop.py`, `tests/unit/test_board_drop_browser.py` | 08 |
| *Panel* | Control Center tab and panel behaviour | `jarvis/runtime/control_center_chat.js` | `tests/unit/test_control_center_chat_ui.py`, `tests/unit/test_control_center_chat_browser.py`, `tests/unit/test_control_center_chat_tabs_browser.py` | 06, 07b |
| all | the whole chain on a real Core and Control Center | — | `tests/integration/test_chat_end_to_end.py` (13 scenarios, plus one Category 2 behind `JARVIS_LIVE_CLAUDE=1`) | 09 |

### Routes

| Route | Served by | Relays to | Section |
| --- | --- | --- | --- |
| `GET /api/chat/state` | Control Center | `GET /v1/chat/state` | *Voice channel* › *Reading* |
| `POST /api/chat/voice/disable` | Control Center | `POST /v1/voice/channel/disable` | *Voice channel* |
| — | Core (Voice only) | `POST /v1/voice/channel/report` | *Voice channel* |
| `POST /api/chat/turns` | Control Center | `POST /v1/conversations/{conversation_id}/brain-turns` | *Sending text* |
| `POST /api/chat/uploads` | Control Center | `PUT /v1/uploads/{client_upload_id}?purpose=chat` | *Attachments* |
| `GET /api/conversations/events?projection=chat` | Control Center | `GET /v1/conversation-events?projection=chat` | *Reading* |
| `POST /api/boards/drop?board_id=` | Control Center | `PUT /v1/uploads/{client_upload_id}?purpose=board&board_id=` | *Board drop* |
| `POST /api/boards/drop-link` | Control Center | `POST /v1/uploads/links` | *Board drop* |
| `GET /api/sessions/current` | Control Center | `GET /v1/sessions/current` (`context.artifacts_root`) | *Reference given to the Brain* |

Every `/api/chat*` and `/api/boards/drop*` route sits behind the Control
Center origin guard; every `/v1` route needs Core's token. Held by
`tests/integration/test_chat_end_to_end.py::test_security_cross_origin_refused_all_chat_routes`,
`tests/unit/test_voice_channel_protocol.py::test_the_chat_prefix_is_guarded_for_every_method`,
`tests/unit/test_board_drop.py::test_the_drop_routes_are_guarded`,
`tests/unit/test_voice_channel_protocol.py::test_core_routes_require_the_token`,
`tests/unit/test_upload_protocol.py::test_core_route_needs_the_token_and_a_closed_query`.

Invariants held everywhere:

- **One conversation truth**: `ConversationEventStore` (Core only). No chat
  table, no JSONL, no durable message cache. The Chat never reads the
  diagnostic journal (`runtime/trace.jsonl`), sub-agent logs or reflexes.
- **No SQLite migration.** Everything persisted goes through existing JSON
  columns (`turns.data.metadata`, `artifacts.data`) or the closed
  `ArtifactKind` set (no SQL `CHECK`, [artifacts.md](artifacts.md)). A change
  that would need a migration stops and follows `CLAUDE.md`.
- **The text path never touches the Voice bridge**, and Voice does not own the
  Brain's lifetime: disabling voice never closes the Session, switches the
  Board, cancels the Brain or stops a sub-agent.
- **Safety is server-side.** Every lock shown by the panel is also enforced by
  Core; a visual lock alone is never the guard.

## Projection

### What the Chat shows

| Canonical event | Shown as | Rule |
| --- | --- | --- |
| `user.transcript.accepted`, `attributes.addressing` absent or `addressed` | User bubble | at once |
| `user.transcript.accepted`, `attributes.addressing = uncertain` | User bubble **only once promoted** | promoted when a `brain.message.published` with the **same `correlation_id`** exists; shown at **its own** sequence |
| `user.transcript.accepted`, any other `addressing` value | never | excluded by prudence |
| `brain.message.published` | Brain bubble | every `kind` (`turn_result`, `work_result`, `speech_result`) and `status` (`failed` is styled as a failure answer written by the Brain); duplicates folded |
| `brain.turn.failed` | **status** of the User bubble with the same `correlation_id` (never a bubble) | `attributes.code` rendered as a sentence; ignored when no User bubble of that correlation exists (system turn); **only while no `brain.message.published` of the correlation exists** in the conversation (any `status`, before or after the failure): a Brain message is the answer, its own words replace the status. Core's backend-failure path writes `brain.message.published` (`status = failed`) **before** `brain.turn.failed`, so that turn shows the Brain's failure answer and no status |
| every other type (`mouth.*`, `brain.speech.requested`, `brain.work.*`, `subagent.*`, `tool.*`, `tool_brain.*`, `system.*`, `brain.ui_intent.published`, `brain.turn.accepted`) | never | — |

Why `uncertain` is held then promoted: it is Core's own durable rule for "the
Brain took an uncertain turn" (`_derive_state` in
`jarvis/core/brain_service.py` keeps an uncertain turn pending until a Brain
utterance of its correlation appears later in the log). A turn the Brain
declined with `[pas-pour-moi]` (`BRAIN_NOT_ADDRESSED_ANSWER`,
`jarvis/domain/v2.py`) produces no public outcome, hence no
`brain.message.published`: it stays invisible. `ambient` never reaches the store
(refused by `BrainTurnInput` and by direct admission), and `source=system` turns
are never recorded as user events.

Why `brain.turn.failed` (diagnostic) is read: a failed text turn would otherwise
stay "pending" forever, and the Chat must show a bounded failure without making
up an answer. The type never carries content
([conversation-events.md](conversation-events.md), note 2); only
`attributes.code` is read.

**Duplicate folding** is the existing rule, tested in Python/JS parity: a
publication equal to the **previous** publication of its correlation is folded
into it (`collapse_published_messages` in
`jarvis/domain/conversation_transcript.py`, `collapseMessages` in
`control_center_timeline.js`). A, B, A stays three messages.

### Where each rule lives

1. **Stateless filter, Core side**: `jarvis/domain/chat_projection.py` exposes
   `CHAT_PROJECTION = "chat"`, `CHAT_EVENT_TYPES` (the three types above) and
   `is_chat_event(event) -> bool` (a `user.transcript.accepted` with an
   `addressing` other than absent / `addressed` / `uncertain` is false).
2. **Stateful rules, client side** (promotion, folding, failure status, keying
   by `event_id`): the pure module `jarvis/runtime/control_center_chat_model.js`
   (no DOM), with a Python reference implementation
   `project_chat(stored_events, *, conversation_id) -> tuple[ChatItem, ...]` in
   `jarvis/domain/chat_projection.py`. The split is forced by the stream: a
   promotion arrives after the cursor has passed the uncertain turn. The model:
   `createChatModel(conversationId)`, `applyPage(model, page)` (a page or its
   rows; replayable, idempotent by `event_id`), `items(model)`,
   `reset(model, conversationId)` (empties everything), `markPending(model,
   correlationId)` / `isPending(model, correlationId)` (a sent text turn with
   neither a Brain message nor a failure yet). A model without a conversation
   accepts no row.
3. **Shared fixture** `tests/fixtures/chat_projection/cases.json`, played by
   pytest and by node (same practice as the folding parity).

### Projection output (`ChatItem`)

`project_chat` takes stored events in any page order, keeps those of
`conversation_id` only, and returns items ordered by `sequence`. Every item has exactly these
fields (null or empty when not applicable):

| Field | User item | Brain item |
| --- | --- | --- |
| `role` | `user` | `brain` |
| `event_id`, `sequence`, `correlation_id` | of its `user.transcript.accepted` | of the first publication |
| `text` | event `content` | event `content` |
| `kind`, `status` | null | `attributes.kind`, `attributes.status` |
| `failure_code` | `attributes.code` of the latest `brain.turn.failed` of the same correlation (`brain_turn_failed` when it has no code) when no `brain.message.published` of that correlation exists, else null | null |
| `collapsed_event_ids` | `[]` | `event_id`s folded into this bubble, in order |

Rules the fixture pins (17 cases): empty input; `addressed` and absent
addressing; `uncertain` promoted; `uncertain` declined (never promoted);
identical republication folded; A/B/A kept; `brain.turn.failed` on a user turn;
`brain.turn.failed` on a system turn ignored; `mouth.*`, `subagent.*`,
`brain.speech.requested` and other types ignored; non-contiguous sequences
kept as is; a replayed page (same `event_id`, first copy wins); two
conversations (only `conversation_id`'s events count, a shared
`correlation_id` elsewhere never promotes, folds or fails a bubble here, with
a second case where the other conversation's identical publication and
`brain.turn.failed` share the user turn's correlation);
unknown `addressing` excluded; a failure then a reply and a reply then a
failure (no `failure_code` either way, the Brain bubble carries the answer);
Core's backend-failure order (`brain.message.published` `status = failed`, then
`brain.turn.failed`: one Brain failure bubble, no `failure_code`). Events in the fixture are encoded exactly as
`encode_stored_event` (`jarvis/domain/conversation_event_query.py`) and
round-trip through `decode_stored_event`.

### Scope: the binding's conversation

The Chat shows `binding.conversation_id` of the open Session and its active
Board (`SessionManager.current()`, `GET /v1/sessions/current`). The
`session_id` of user events is the **voice** session, not
`jarvis_session_id`: it is never used to filter. On a Board change the client
re-reads `GET /api/chat/state`, empties its model and rehydrates from
`after_sequence=0` for the new conversation. Several Boards are never merged.

## Reading

No new read route. `GET /v1/conversation-events` and its relay
`GET /api/conversations/events` accept `projection` (only admitted value:
`chat`). It joins `EVENTS_PARAMS` and `events_query`, and a
`filter_projection` sibling of `filter_visibility` is applied at the same place
of the long-poll loop. Inherited behaviour (see
[conversation-events.md](conversation-events.md) › *Cursor, reconnect and
live*): `next_cursor` advances past filtered rows, a filtered long-poll waits
past hidden events, the strict page decoder still holds. `projection` together
with `visibility` → 400 `invalid_request`. The Control Center passes
`projection` through `events_query` → `ConversationEventView.events` →
`LocalCoreClient.list_conversation_events`; on Core,
`ConversationEventQueryService.events` applies `filter_projection` after
`filter_visibility`. Without `projection` the route answers exactly as before.
The filter is stateless: rules that need several rows (promotion, folding,
failure status) stay in the client model. Tests:
`tests/unit/test_chat_projection_query.py`,
`tests/integration/test_chat_projection_protocol.py`.

**Live reading: short reads only, no long-poll.** The Chat never holds a
request open. Why (QA Slice 06, blocking): Chrome shares **six** HTTP/1.1
connections per origin across all tabs, and every Control Center tab already
holds long-polls of its own (fullscreen commands, Studio explorer, timeline).
A 25 s Chat long-poll per tab starved `/api/status`, `/api/chat/state` and the
send itself (> 9 s) from two tabs on. The rules:

- One loop per tab, **sequential** (never two Chat requests in flight in a
  tab): `GET /api/chat/state`, then the events read, every **1.5 s**; every
  **0.5 s** for **20 s** after the tab's own send, a follower's send, or a
  state change (conversation, voice state, writability).
- Events: `projection=chat`, `limit=500`, from the **last `next_cursor`
  received** (hydration starts at `after_sequence=0`), following `next_cursor`
  while `has_more`; never `wait_ms`.
- **One reader per browser profile**: only the holder of the Web Locks lock
  `jarvis.chat.<conversation_id>` (the leader) reads events, and posts the rows
  on `BroadcastChannel('jarvis.chat.<conversation_id>')`. Followers read no
  events: they ask the history (`hello`), apply what the leader shares, and
  announce their sends (`poke`) so the leader goes fast; they try the lock on
  every tick and take over when the leader leaves. Without Web Locks or
  BroadcastChannel: solo, same cadence. The state stays a per-tab short read.
- A closed panel or a hidden tab makes **no** request (and releases the lock).

Measured (`tests/unit/test_control_center_chat_tabs_browser.py`, a real HTTP
server that holds the page's long-polls): two Chat tabs answer `/api/status` in
milliseconds and a follower's send lands in both; with three Chat tabs and a
timeline tab the Chat asks for no long wait beyond the page's own — that page,
Chat closed, already exceeds Chrome's six connections (outside the Chat).
Real isolated Core + Control Center, headless Chrome (2026-10-15): two Chat
tabs, `/api/status` 23 / 13 ms, a follower's send 202 and shown in both tabs
in 0.7 s, events read by one tab only. Any **three** visible Control Center
tabs (Chat open or closed) hold six 25 s waits (`/api/fullscreen/commands`,
`/api/presentation-studio/explorer/commands`, two per tab): `/api/status`
≈ 8.3 s Chat open, ≈ 8.6 s Chat closed — a page limit, not the Chat's.

## Sending text

### Control Center `POST /api/chat/turns`

```json
{"conversation_id": "conv-…", "client_request_id": "<uuid v4>", "content": "text", "attachments": ["jart_…"]}
```

- Guard: the `/api/chat` prefix is in `READ_GUARDED_ROUTES`
  (`jarvis/runtime/control_center.py`), so `_origin_guard` applies to every
  method: loopback Host, loopback Origin when present, `Sec-Fetch-Site:
  cross-site` refused and, for a mutation, `same-site` refused
  (`_loopback_refusal`). Plus: `Content-Type: application/json` required (415
  `invalid_content_type`), body ≤ 64 KiB (413 `request_too_large`).
- Relayed to Core `POST /v1/conversations/{conversation_id}/brain-turns` with
  `{"content", "correlation_id": "chat:" + client_request_id, "source": "text",
  "addressing": "addressed", "attachments": [...]}`. Budget 15 s; past it, 504
  `core_timeout` ("outcome unknown: resend the same `client_request_id`").
- Journal: `chat.turn.relayed` (status, code, `correlation_id`, attachment
  count), never the text.
- Body closed: unknown field, `client_request_id` not a UUID, `content` not a
  string, `conversation_id` not one path segment, `attachments` not a list of
  strings → 400 `invalid_request`, before Core is called. The Core client's
  `forward_json` relays `/v1/conversations/{id}/brain-turns` only (exact path,
  `FORWARDABLE_PATHS` in `jarvis/protocol/client.py`), never `.../cancel` nor
  `.../turns`.
- A Core refusal keeps its `reason` (`chat_input_locked`) and
  `current_conversation_id` (`chat_conversation_not_foreground`) as top-level
  fields of the Control Center envelope.
- Answer: 202 (new) or 200 (duplicate) `{"ok": true, "correlation_id",
  "turn_id", "duplicate"}`. The client keeps a local **pending state** (not a
  bubble) until the `user.transcript.accepted` of that `correlation_id`
  arrives, then waits for the reply.

The browser **never** calls `/api/agent/ask` or `/api/agent/send` for the Chat:
those routes bypass the canonical events.

### Core: same `brain-turns` route, guards in order

No parallel route. For `source = "text"` only, the handler applies, in this
order:

1. **Validation**: `content` nonblank and `len(content) ≤ 8192` (else 400
   `chat_text_too_long`); `attachments` a list of at most
   `JARVIS_CHAT_MAX_ATTACHMENTS` (default 10) distinct Artifact ids (400
   `too_many_attachments`).
2. **Replay first**: if the durable turn
   `brain-turn-<stable_identity(conversation, correlation)>` already exists,
   the later guards are skipped and `submit` returns the duplicate (200,
   `duplicate: true`). A resend after a voice switch never becomes a 409.
3. **Foreground binding**: `SessionManager.current().binding.conversation_id`
   must equal `{conversation_id}`; else 409 `chat_conversation_not_foreground`
   (the body names the current conversation so the UI can realign). No open
   Session or no binding: the existing `BoardError` codes from
   `SessionManager.current()`, 404 `session_not_found` / `binding_not_found`;
   Session service not wired: the existing 503 `core_unavailable`.
4. **Voice channel** (*Voice channel* below): a **synchronous** read of the
   in-memory state, with no `await` between this read and
   `self.core.brain.submit(turn)`. Writing not allowed → 409
   `chat_input_locked`, `reason` ∈ `voice_active`, `voice_connecting`,
   `voice_switching`, `voice_error`, `voice_unknown`.
5. **Attachments** (Slice 07): each id exists (404 `attachment_not_found`), is
   of kind `upload` with provenance `chat_attachment` **or of kind
   `screenshot`** (orbital-ui Slice 05, D7: « Envoyer à Jarvis » from the
   screenshot preview) and belongs to the open Session (400
   `attachment_not_allowed`), is linked to the Board of the
   target binding (409 `attachment_other_board`, journal
   `core.upload.attachment_other_board` with the id and the Board, never a
   name), and is `complete` (409 `attachment_not_ready`); the first refusal in
   message order wins. Any other kind (a recording, a transcript, a Board
   drop, a link, a render) stays refused. The Board of an attachment is its Board link
   (`board_artifact_links`): the automatic `active_board` link written by its
   creation transaction (a screenshot like an upload), or an `explicit` link made later in the Workspace
   inspector. This is Core's guard; the page's `stale` state only avoids
   sending a refused turn (Slice 09 finding 1). A replay (step 2) answers
   before this step: re-sending an admitted turn stays a 200 duplicate. This step
   **runs right after step 3, before step 4**: it reads the registry (an
   `await`), and step 4 must stay the last read before `submit` with no
   `await` in between. Attachments on a non-text turn: 400 `invalid_request`;
   ids repeated or not `jart_…`: 400 `invalid_request` (step 1).
6. `BrainOrchestrator.submit`: single persistence, `user.transcript.accepted`,
   dispatch to the binding's Brain.

Step 4 is the linearization point of the "send / voice wake-up" race: a voice
report processed after it does not cancel the turn; it was admitted lawfully,
its result stays written (*Text disposition*) and the panel shows it.

### Idempotence

`client_request_id` (UUID v4 drawn by the browser **per composed message**,
reused on every retry) becomes `correlation_id = "chat:" + client_request_id`.
Deduplication already exists in memory (`_find_duplicate`) and durably:
`persist_turn` derives `turn_id` from `(conversation, correlation)` and
recognizes the durable source, then `claim_backend_dispatch` refuses to
re-dispatch a duplicate. The same `client_request_id` with another text or other
attachments raises "admission identity conflicts", answered **409
`chat_request_conflict`** for `source=text` (instead of the generic 400). The
replay step (2) compares the durable turn first (content, `source`,
`attachments`); and because the in-memory `_find_duplicate` does not compare
the text, a `duplicate` answer from `submit` to a text turn is re-checked
against the durable turn, so two concurrent sends of one id with different texts
give one 202 and one 409, never a silent 200.
`persist_turn` adds `attachments` to the compared keys.

### What the Brain receives

- `BrainTurnInput` gains `attachments: tuple[str, ...] = ()` (Artifact ids),
  persisted in `turns.data.metadata.attachments` **only when non-empty**
  (JSON metadata: no migration; existing turns unchanged byte for byte).
- `_turn_context` (`jarvis/adapters/control_center_brain.py`) adds
  `"channel": "text"` for `source=text` and, with attachments, the
  `attachments` block (*Attachments*). Absent otherwise: the context is
  unchanged byte for byte.
- `build_agent_brief` (`jarvis/runtime/control_center.py`) renders, for
  `channel=text`, one line: « Canal : écrit (chat). Ta réponse sera lue, pas
  dite : texte simple, 6000 caractères au plus ; au-delà, écris un fichier dans
  le dossier du Context et donne son chemin. »
- Same Brain, binding, tools and sub-agents: the turn follows
  `run_turn_with_context` → internal `POST /api/agent/ask` Core → Control
  Center, like a voice turn.

## Text disposition (`text_channel`)

Every retained outcome also leaves as `brain.speech.requested` today
(`_emit_speech`); there is no per-turn disposition. The Chat adds an **output
disposition per correlation**, decided in `_emit_speech` right **after
retention** and **before** `_speech_gate`:

- `BrainOrchestrator._text_only(conversation_id, correlation_id) -> bool`:
  true when the originating turn has `metadata.source == "text"`. Memory cache
  fed by `submit` for `source=text`; **durable** fallback through
  `repository.get_turn("brain-turn-" + stable_identity(conversation_id,
  correlation_id))`, so a sub-agent result arriving hours later, or after a
  Core restart, stays silent.
- When true: diagnostic `core.brain.speech_withheld_text_channel`
  (`conversation_id`, `correlation_id`, `speech_id`, `kind`), return
  `_SpeechEmission(False, None, SPEECH_WITHHELD_TEXT_CHANNEL)` with
  `SPEECH_WITHHELD_TEXT_CHANNEL = "text_channel"`. The outcome is already
  retained, so `brain.message.published` exists; no `brain.speech.requested`.
- Questions and acknowledgements (`SpeechKind.QUESTION/ACK/PROGRESS`) are not
  retained as outcomes: on a text turn they become silent **and** invisible.
  No answer is lost: the adapter always publishes the answer as a
  `work_result`.
- Spontaneous notices (`source=system` turns) keep their policy: retained, so
  visible in the Chat, and spoken only when voice is active. A notice relayed
  while the current intention is a text turn (`announce_notice` borrows its
  correlation, e.g. a sub-agent's end) is withheld like the turn: visible, not
  spoken, traced once (`speech_withheld_text_channel`, no extra
  `notice_dropped`).
- The memory cache is bounded (`MAX_KNOWN_TURN_CHANNELS = 1024`, voice turns
  cached as `false` too); an evicted correlation is re-read from the durable
  turn (`BrainOrchestrator.admitted_turn`).
- `InteractionMode` and `OutputDisposition`
  ([interaction-mode.md](interaction-mode.md)) are **not** reused: they govern
  presentation by mode, not the channel of a turn.

## Voice channel

Product states Off / Sleep / Active, the persisted « voix coupée » preference and what the Chat does in each:
[voice-lifecycle.md](voice-lifecycle.md). Off reads as `absent` here (no Voice process), Sleep as `background`.

The real voice state lives in the Voice process
(`VoiceLifecycleState{background, active, connecting, error}`); Core knew
nothing of it. `VoiceChannelService` (`jarvis/core/voice_channel.py`, pure
domain `jarvis/domain/voice_channel.py`) is an **in-memory** Core service fed
by **reports** from Voice, which receives any disable request in the answer.
It is the idempotent per-second receipt precedent of the Live stop
(`.voice_live_stop_request` / `_handle_live_ui_supervision`), moved from a file
into Core so that Core, which admits turns, is the judge. Core's Live lifecycle
(`/v1/live/sessions/*`) covers GPT-Live billing only and is not reused.

It is **not** `InteractionMode` and **not** `OutputDisposition`
([interaction-mode.md](interaction-mode.md) › *Voice channel and Chat*).

### Voice → Core `POST /v1/voice/channel/report`

Core token like every `/v1` route.

```json
{"schema_version": 1, "voice_incarnation_id": "voice-<uuid>", "seq": 42,
 "lifecycle_state": "background|active|connecting|error", "conversation_id": "conv-…|null",
 "ack": {"request_id": "vcr-…", "result": "accepted|failed", "code": "voice_disable_failed|null"} }
```

Sent (a) on every tick of `_voice_timeout_loop` (1 s), (b) **immediately** on
entering `connecting` (before the microphone opens; wait bounded to 0.5 s; a
failure never blocks activation and is journaled), (c) right after a `mute()`
caused by a request, with `ack`. `voice_incarnation_id` is drawn at process
start; `seq` strictly increases per incarnation. Core ignores a report whose
`seq` is lower or equal for the same incarnation; a new incarnation replaces the
old one. Answer: `{"schema_version": 1, "epoch", "revision", "accepted",
"disable_request": {"request_id", "requested_at"} | null}` (`accepted: false`
for an ignored stale report, journaled `core.voice_channel.report_rejected`).
The body is closed (unknown field, wrong type → 400 `invalid_request`); a
well-formed `lifecycle_state` outside the four reported states reads as
`unknown`. Voice side (`jarvis/app.py` `_report_voice_channel`,
`PersistentVoiceRuntime.send_voice_channel_report`): a report never raises;
a failure is journaled once per episode (`voice.channel.report_failed`, then
`voice.channel.report_restored`); an acknowledgement not delivered is resent
with the next report.

### Control Center → Core `POST /v1/voice/channel/disable`

Body `{"client_request_id": "<uuid>"}`. Creates (or returns, for the same
`client_request_id`) a request `vcr-…`, revision + 1; answers 202
`{"request_id", "state": "switching", "status": "pending"}`; while a request
is pending, any other `client_request_id` gets that same request. Voice
`absent`, or already `background` with no request: 200 `{"state": …,
"request_id": null, "status": null}` (nothing to do). Voice takes the
request from the answer to its next report (≤ 1 s), calls `voice.mute(VoiceStopReason.USER)` like the Live stop, then reports
`background` with `ack.result = accepted` (or `failed` + code when `mute()`
raises or leaves `error`). A request not acknowledged within
`VOICE_DISABLE_TIMEOUT_S = 10` s expires (`expired`). A fresh `background`
report from Voice while the request is pending (muted meanwhile by the key or
the idle timeout) settles it `accepted`: the goal is met, nothing is muted
twice. Voice already in `background` when it receives a request acknowledges
it without calling `mute()`. Voice still `connecting` (its provider session
not open yet) leaves the request **unhandled**: a `mute()` then would find no
session and the activation would turn `active` right after; the next tick
takes it again (`active` → `mute()` and acknowledge; back to `background` or
`error` on its own → acknowledged by the rules above), or Core expires it and
the Chat stays locked. An acknowledgement that could not be delivered is
resent with the next report; if that report is no longer `background` (voice
woke up meanwhile), Core settles the request `failed` with
`voice_disable_failed`. Relayed by the Control Center as
`POST /api/chat/voice/disable`.

### Reading `GET /v1/chat/state`, relayed as `GET /api/chat/state`

No open Session: the existing 404 `session_not_found` / 503 `core_unavailable`
(as `GET /v1/sessions/current`).

```json
{"schema_version": 1, "jarvis_session_id": "…", "board_id": "…", "conversation_id": "…",
 "voice": {"state": "absent|background|connecting|active|error|switching|unknown",
           "epoch": "…", "revision": 7, "report_age_ms": 400,
           "request": {"request_id": "vcr-…", "status": "pending|accepted|failed|expired", "code": null} },
 "chat_writable": true, "locked_reason": null}
```

### State machine (Core view)

| State | Condition | Chat writing |
| --- | --- | --- |
| `unknown` | Core started less than `VOICE_CHANNEL_FRESH_S` (5 s, aligned with `VOICE_HEARTBEAT_MAX_AGE_S`) ago without a report; or a fresh report with an unreadable state | refused `voice_unknown` |
| `absent` | no report, or last report older than 5 s, after the grace period | **allowed** (Chat without a voice runtime) |
| `background` | fresh `background` report, no request in progress | **allowed** |
| `connecting` | fresh `connecting` report | refused `voice_connecting` |
| `active` | fresh `active` report | refused `voice_active` |
| `error` | fresh `error` report (unconfirmed close, audio pending) | refused `voice_error` |
| `switching` | `pending` request not expired and last report ≠ `background` | refused `voice_switching` |

Transitions: `active|connecting|error --disable--> switching`;
`switching --background report + ack accepted--> background`;
`switching --ack failed | expiry--> state of the last report` (the request
keeps `failed` / `expired` and its code for the UI);
`background --connecting report (wake-up, key, wake word)--> connecting` (the
Chat locks again); any state `--5 s without report--> absent`. A wake-up during
`switching`: the last report wins; if Voice already saw the request it executes
it (the user's explicit choice is the most recent), otherwise the request
expires and the UI offers to retry.

What the switch **never** does: close the Session, change Board or binding,
cancel `BrainOrchestrator`, stop a pool CLI or a sub-agent, touch
`InteractionMode`. `mute()` does none of it and Core only calls its own
in-memory service. Core restart: state lost, 5 s `unknown`, then the first
report restores the truth.

## Attachments

### Chain

```text
browser --multipart, 1 file per request--> CC POST /api/chat/uploads
  CC (/api/chat guard, streamed in chunks, no disk copy) --PUT stream--> Core PUT /v1/uploads/{client_upload_id}
  Core: Artifact kind=upload pending -> spool .partial -> bound -> sniff -> finalize complete|failed
browser <-- {artifact_id, original_name, mime_type, size_bytes, brain_readable, state}
POST /api/chat/turns {..., attachments:[artifact_id]} -> Core -> BrainContext.attachments -> brief -> Read by the CLI
```

### Core `PUT /v1/uploads/{client_upload_id}`

`jarvis/protocol/upload_routes.py`, façade `jarvis/core/upload_service.py`,
pure rules `jarvis/domain/uploads.py`.

- Parameters: `purpose=chat|board` (`board`: *Board drop* below, Slice 08);
  `board_id` required for `board` and refused with `chat` (400
  `invalid_request`); `agent=claude|codex` (the
  foreground CLI, set by the Control Center; computes `brain_readable`).
  Headers: `Content-Length`, or `Transfer-Encoding: chunked` (the Control
  Center relays a browser multipart whose file size it does not know);
  `Content-Type` (declared, kept, never trusted); `X-Jarvis-Upload-Name`
  (original name, UTF-8 percent-encoded, ≤ 255 characters once decoded; else
  400 `upload_name_invalid`). The name is display data only: NFC, control and
  format characters (bidi overrides) removed, path components dropped,
  reserved Windows names prefixed with `_`; never a file name on disk.
- Replayable identity: `artifact_id = "jart_up_" + sha256(client_upload_id)[:40]`.
  Same `client_upload_id` already `complete` with the same size and digest →
  200 with the Artifact (replay); different → 409 `upload_conflict`. Still
  `pending` (concurrent request) → 409 `upload_in_progress`. A previous attempt
  that ended `failed` → 409 `upload_conflict`: the failed row is immutable, the
  client draws a new `client_upload_id`.
- Artifact: `kind = upload`, `source = "chat"` or `"board_drop"`,
  `jarvis_session_id` and `context_id` of the open Session and active
  Context, `payload_name = "upload" + ext`: for a sniffed image or PDF the
  canonical extension of the sniffed type (`png`, `jpg`, `gif`, `webp`, `pdf`;
  Claude reads images and PDF by extension, so a lying name never decides);
  otherwise the original extension lowercased when it matches `[a-z0-9]{1,8}`
  and is not an image/PDF extension, else `upload.txt` (text) or `upload.bin`.
  The type is sniffed from the first 64 KiB **before** the Artifact is created
  (`mime_type` and `payload_ref` are fixed at creation). Metadata: `original_name`,
  `declared_mime`, `sha256`, `provenance` (`chat_attachment` | `board_drop`),
  `client_upload_id`, `brain_readable` (bool). See
  [artifacts.md](artifacts.md) › *Artifact* (uploads and links).
- Stream: read in 64 KiB chunks into `ArtifactService.open_spool`; refused as
  soon as `JARVIS_UPLOAD_MAX_BYTES` (default 64 MiB, configurable; a technical
  bound, told to the user) is exceeded → spool closed, Artifact `failed` code
  `upload_too_large`, 413. Body shorter than `Content-Length`, or cut (client
  gone) → `failed` `upload_incomplete`, 400. Payload refused by the store
  (`artifact_payload_*`) → `failed` 503 `upload_storage_failed`; the message
  and `core.upload.refused` (level `error`, field `cause`) say the real cause
  without the path nor the original name: `payload_code`, `stage` (`open`,
  `write`, `finalize`), `cause_type`, `os_error` / `errno` / `winerror` of the
  chained `OSError`, `path_chars` and `path_limit` (the Windows limit exceeded,
  *Known limits* 10). A `failed`
  upload keeps its registry row; its folder is removed: no `.partial` is left
  (a `.partial` found there before the spool opened is neither overwritten nor
  removed). Refused before the first byte, nothing is written: empty → 400
  `upload_empty`; `Content-Length` above the bound → 413 `upload_too_large`;
  bad name or parameter → 400. A `pending` upload left by a dead Core →
  `failed` `upload_interrupted` at the next start, folder removed, never
  `partial`.
- Type: sniff the leading bytes (PNG, JPEG, GIF, WebP, PDF; text = valid
  UTF-8 without NUL nor other C0 control byte — tab, line ends, form feed and
  ESC excepted — in the first 64 KiB). Stored `mime_type` = sniffed type,
  else `application/octet-stream`; the declared type is never trusted alone. A
  lying extension does not change the sniffed type.
- Brain readability: pure table `BRAIN_READABLE` in `jarvis/domain/uploads.py`,
  per agent. Claude reads text, PNG/JPEG/GIF/WebP, PDF; Codex: nothing is
  attested, so `false`. `brain_readable` is computed at upload for the
  foreground agent (the Control Center knows it and adds it to the answer) and
  **recomputed** when the brief is rendered.
- Board link: the existing rule applies (automatic `active_board` link to the
  active Board). A chat attachment therefore appears in the Board's Artifacts,
  like a screenshot, told apart by `metadata.provenance = chat_attachment`. It
  is not a Board drop: no `explicit` link, no declared resource.
- Conversation events carry only `attachment_count` on
  `user.transcript.accepted` (never ids, names, paths or bytes;
  [conversation-events.md](conversation-events.md)). Journals
  (`trace.jsonl`) carry ids, sizes, types and codes: the Slice code never
  writes attachment bytes nor original names. The Brain's own tool-call
  journal is another matter (*Known limits* 6): what the Brain reads may land
  there.

### Control Center `POST /api/chat/uploads`

Multipart, fields `client_upload_id` then `file`. `/api/chat` guard;
`request.multipart()` read as a stream and relayed to Core as a streamed body
(async generator), never held in memory or on disk; refused early when
`Content-Length` exceeds the bound plus a multipart margin (413
`upload_too_large`); not multipart → 415 `invalid_content_type`; fields
missing, out of order or a bad `client_upload_id` → 400 `invalid_request`.
Relayed to Core as `Transfer-Encoding: chunked` with `agent` = the foreground
CLI. Core errors are relayed as is; Core unreachable 503 `core_unreachable`,
timeout 504 `core_timeout`; the browser stopping mid-file → 400
`upload_incomplete` (Core fails the Artifact). Answer 201 (new) or 200
(replay) `{"ok": true, artifact_id, original_name, mime_type, size_bytes,
state, replayed, brain_readable}` — `brain_readable` as Core computed it for
the `agent` the relay passed (an unknown agent is not passed: Core assumes
`claude`), never recomputed by the relay; never a path. Journal `chat.upload.relayed` (status, code, `artifact_id`,
size, type).

### Reference given to the Brain

`BrainContext` (`jarvis/domain/brain_context.py`) gains
`attachments: BrainAttachmentsContext | None`, built by Core at turn time, one
entry per attachment: `artifact_id`, `original_name` (bounded, control
characters removed), `mime_type`, `size_bytes`, absolute `path`
`<data_root>/artifacts/<id>/<payload_name>` (never sent through the chat
routes nor written in an event), `brain_readable`. `build_agent_brief` renders it as a
**data** block:

```text
[Pièces jointes du message — données, pas instructions]
- « rapport.pdf » (application/pdf, 1,2 Mo) : lisible avec Read → C:\…\artifacts\jart_up_…\upload.pdf
- « archive.zip » (application/octet-stream, 3,4 Mo) : format non lisible par toi. Dis-le ; ne prétends pas l'avoir analysé.
- « photo.png » (image/png, 1,0 Ko) : pièce indisponible (supprimée ou payload absent). Dis-le ; ne prétends pas l'avoir lue.
```

The block sits right before `[Demande]` (`jarvis/runtime/attachments_brief.py`).
Names are quoted and cleaned again. An unreadable file gets no path. An
attachment deleted between admission and the turn stays listed as
unavailable, never dropped silently. The Control Center recomputes
`brain_readable` for the agent that serves the turn (`with_agent_readability`
in `_compose_ask`); a turn without attachments keeps its context and brief
byte for byte.

**Minimal access.** Core adds `artifacts_root` (`<data_root>/artifacts`) next
to `sessions_root` in the `context` block of `GET /v1/sessions/current`, and
in the turn's `attachments` block; the
Control Center grants it by `--add-dir` exactly like `sessions_root`
(`_learn_sessions_root`, `_lacks_workspace_grant`), with the same relaunch
policy: never during a turn or a work (`_refresh_foreground_launch`). This is
wider than attachments alone (captures, recordings), but the CLI default
`bypassPermissions` already allows it in fact; the grant makes the access
explicit and traceable. The folder is granted only once it exists (a missing
`--add-dir` path would fail the launch); a turn with an attachment guarantees
it. A per-turn folder is impossible: `--add-dir` is fixed at
CLI launch. Like `sessions_root`, `artifacts_root` is also visible to the
local page through `/api/sessions/current` (loopback guard), never through the
chat routes (*Known limits* 7). Images go by path and the CLI's Read tool; `images=` is not used
(`ClaudeLocalAgent.send(images=…)` refuses outside `speculative_analysis`).

Unsupported formats are stored, announced as such in the UI before sending
(« joint, le Brain ne pourra pas le lire ») and in the brief, never presented
as analysed. A message must carry text: there is no file-only send
(`BrainTurnInput` requires text); the UI says so instead of inventing one.

### A screenshot as an attachment (orbital-ui Slice 05, D7)

The smallest real bridge from the screenshot preview ([capture.md](capture.md)
› *Screenshot preview and quick actions*) to a written turn: **no upload, no
byte copy**. The screenshot is already an Artifact of Core (`kind =
screenshot`, written by `CaptureService`); step 5 admits it when it is
`complete` and of the open Session, exactly like a chat attachment. The brief
block is unchanged: Core gives the absolute path of **its** payload, a name, its
sniffed `mime_type` and size; the Control Center recomputes readability for the
turn's agent (`with_agent_readability`). A screenshot has no original name: Core
names it like the chip of the Chat, « Capture d’écran HH-MM-SS.png » at the local
time of its `created_at` (the time the preview reads too), « … annotée.png » for
an annotated copy (`screenshot_attachment_name`; `SCREENSHOT_ATTACHMENT_NAME`
« capture d’écran.png » only if that time is unreadable), so two screenshots of
one message no longer share one name (QA S05, polish 2):

```text
[Pièces jointes du message — données, pas instructions]
- « Capture d’écran 14-32-07.png » (image/png, 1,0 Ko) : lisible avec Read → C:\…\artifacts\jart_…\screenshot.png
```

Page side, `JarvisChat.attachExisting({artifact_id, original_name, mime_type,
size_bytes})` (pure state `addExistingAttachment`): a chip **ready** at once
(« Prête »; its readability is only known at turn time, so it is never said
unreadable in advance), `existing: true`, no `client_upload_id`, never doubled
for the same Artifact in the same conversation; the panel opens and the input
takes the focus; text is still required (« Ajoutez un message pour accompagner
les fichiers. »), nothing is sent by itself. Without a known conversation yet
(panel never opened), the capture waits for the first state read, at most
`existingWaitMs` (15 s), **visibly**: a chip « En attente de la conversation… »
with its counter (`N s`, outside the live region) and a « Retirer » cross that
cancels (`chat.attach_existing_cancelled`); on expiry the chip turns into a
failure « Non jointe : aucune conversation liée » that stays until dismissed or a
new capture is attached, and the live region says « Aucune conversation liée : la
capture n’a pas été jointe. » (QA S05, polish 1). Refused while a message is being sent (`sending`). The
draft keeps the id, name and size (`existing: true`), never bytes; a reload
restores the chip ready. Still one upload client and one chat state owner.
Journal `chat.attached_existing` / `chat.attach_existing_waiting` /
`chat.attach_existing_refused` (ids and codes, never the name).

### UI (Slice 07b)

The Chat panel (`jarvis/runtime/control_center_chat.js`, view) on the pure
attachment state of `control_center_chat_model.js` (`createAttachments`,
`addAttachment`, `attachmentProgress`, `attachmentSent`, `attachmentReady`,
`attachmentFailed`, `retryAttachment`, `rebindAttachment`, `addExistingAttachment`, `removeAttachment`,
`attachmentView`, `takeSent`, `restoreAttachment`). One upload client, one
chat state owner: no second module.

- **Attach.** A **Joindre** button (a real `<button>`, Tab-reachable between
  the composer and Envoyer, Enter or Space opens the native chooser) drives a
  hidden `<input type="file" multiple>`. **Drop zone = the Chat panel only**:
  while files are dragged over it an overlay says « Déposez les fichiers pour
  les joindre au message ». A file dropped anywhere else in the page does
  nothing: a document-level `dragover` guard cancels the browser default with
  `dropEffect = none`, so the browser never opens the file in place of the
  page (a later drop target that calls `preventDefault` first, such as the
  Board drop of Slice 08, keeps the hand).
- **One request per file**: `XMLHttpRequest` `POST /api/chat/uploads`,
  `FormData` `client_upload_id` (UUID v4) then `file`; the send progress comes
  from `xhr.upload.onprogress`. Nothing else in the page uploads.
- **States per attachment** (a row above the composer: name, size, state,
  elapsed counter, action, ×):
  - `uploading` « Envoi N % » with a progress bar and counter, then
    « Vérification par Jarvis Core… » once the last byte left (Core bounds,
    sniffs, stores);
  - `ready` « Prête »;
  - `ready` with `brain_readable = false` « Prête · jointe, mais le Brain ne
    pourra pas la lire » — said **before** sending; the file is stored and
    sent, never presented as analysed;
  - `failed`: the code's sentence (`upload_too_large` states Core's bound,
    « Trop volumineux : 64 Mo au plus par fichier. », read from Core's message
    « the file exceeds the N-byte upload bound » since the relay carries no
    separate field); « Réessayer » when a retry makes sense (not for
    `upload_too_large`, `upload_empty`, `upload_name_invalid`);
  - removed (×): leaves the list; an upload in flight is aborted. The
    Artifact Core may already hold stays in the Board's Artifacts (no delete
    route; *Known limits* 2).
  - `stale` « À renvoyer : jointe sur un autre Board, elle ne partira pas
    d'ici. » — see *Board or Session change*.
- **Deadlines** (RULE ZERO): no upload progress for `uploadStallMs` (30 s), or
  no answer `uploadAnswerMs` (130 s, above the relay's 120 s read budget)
  after the last byte → `client_timeout`, an unknown outcome, said « Jarvis
  Core ne répond pas. »: the relay streams the bytes to Core and waits for
  Core's answer, so a stall blames Core, like the composer lock (a Control
  Center that cannot be reached is `network_error`, « Control Center
  injoignable »).
- **`client_upload_id` on retry** (reconciles Slice 07 QA and the contract
  test `retry_reuses_client_upload_id`):
  - **unknown outcome** (`core_timeout`, `client_timeout`, `network_error`,
    `upload_in_progress`): « Réessayer » reuses the **same** id. If Core had
    finished, it replays (200 `replayed`, the same Artifact, no duplicate);
  - **known failure** (`upload_incomplete`, `upload_conflict`,
    `upload_storage_failed`, `core_unreachable`, any other refusal): the retry
    draws a **new** id — Core keeps the `failed` row and would answer 409
    `upload_conflict` to the old one;
  - a same-id retry answered 409 `upload_conflict` (the unknown attempt had in
    fact failed in Core) restarts **at once, once**, with a new id.
- **Sending.** `attachments` = the ids of the conversation's ready
  attachments. Sending is refused while one is `uploading` (« Envoi possible
  dès que la pièce est prête. ») or `failed` (« Une pièce est en échec :
  réessayez-la ou retirez-la avant d'envoyer. » — no silent loss), and without
  text (« Ajoutez un message pour accompagner les fichiers. »: no file-only
  message). The `client_request_id` of a draft changes when its text **or**
  its set of ready attachments changes; after an unknown send outcome,
  changing either makes a new message (the « sans doublon » offer is
  withdrawn). The voice lock blocks the **send**, not the preparation:
  attaching stays possible while `chat_writable` is false. Attaching is off
  without a conversation and during a send.
- **The user bubble** shows « N pièce(s) jointe(s) » from
  `attributes.attachment_count` (`JarvisChatModel.attachmentCount`, read on the
  stored row; the projection item shape is unchanged). The names live only in
  the local state of the message sent from this tab (last 50 messages); after
  a reload or from another tab: the count and a « voir dans l'inspecteur »
  link that opens the Workspace inspector on the conversation's Board
  (`JarvisWorkspace.openBoard`), where the Artifacts are listed.
- **Board or Session change.** An attachment belongs to the conversation it
  was attached in (Core enforces it by Board, 409 `attachment_other_board`,
  « Une pièce jointe a été ajoutée sur un autre Board : retirez-la, joignez le
  fichier à nouveau ici, puis renvoyez. »). Seen from another conversation it
  is `stale`: never sent there, offered « Renvoyer ici » (a new upload of the same file, new id, into
  the current context) and ×; back on its own Board it is ready again.
- **Reload.** The draft (`jarvis.chat.draft.<conversation_id>`) keeps the
  ready attachments (Artifact id, name, size, readability, `client_upload_id`)
  and restores them; one still uploading at reload comes back `failed`
  `upload_interrupted_reload` (« joignez le fichier à nouveau »), never lost
  silently. This stored draft is the **reload-recovery record only**: it is
  read once per conversation per page load. A Board round trip (A → B → A) is
  not a reload: the attachments in memory stay authoritative, an upload still
  running on A keeps its live row and finishes there. The record of a
  conversation follows its attachments even while another Board is shown (an
  upload that finishes, a × or « Renvoyer ici » seen from B rewrites A's
  record), and a restore never duplicates an attachment already present (same
  `client_upload_id` or Artifact) — QA S7b, phantom « interrompu » row.
- **Layout.** A file row never shrinks below its content (name, state, ×);
  the list is bounded (`min(168px, 24vh)`) and scrolls. The composer keeps its
  size first and the message list takes the rest; on a low panel only the file
  list (down to about one row) and the text field (down to two lines) give
  way, so the Joindre/Envoyer row always stays inside the panel — checked with
  10 files (Core's default per message) at 1440×900, 1024×480 and 600×800.
  The key hint stays on one line (« Entrée envoie · Maj+Entrée : à la ligne »,
  ellipsis if ever too narrow).
- **Names in the user bubble** are each in a `<bdi>` (text nodes, never HTML):
  a bidi override (U+202E) in one name cannot reverse the next.
- **Journal** (console `[chat] chat.<event>`): `attached` (via button|drop,
  count), `upload_started`, `upload_ready` (`artifact_id`, size, type,
  `brain_readable`, `replayed`), `upload_failed` (code, status, `same_id`,
  `auto_retry`), `upload_retry`, `upload_rebound`, `upload_removed`,
  `drop_ignored`, `turn_held` (reason), `inspector_opened`. Never a file name
  or a byte.
- Tests: `tests/unit/test_control_center_chat_attachments_browser.py` with
  `tests/unit/_chat_attachments_browser.mjs` (fake relay as an `extra` of
  `_chat_browser.mjs`; real files set by CDP `DOM.setFileInputFiles`, the
  intercepted native chooser, and a real `Input.dispatchDragEvent` drop), and
  the pure cases of `tests/unit/test_control_center_chat_model_js.py`.

## Board drop

An extra of the same upload service (code since Slice 08). Never a chat turn,
never a message to the Brain, never a new conversation, never a scene object.
`jarvis/core/upload_service.py` (`put(purpose=board)`, `put_link`, seam
`BoardDropSeam` wired by `JarvisCoreApplication`: active Board, Board links,
explicit link), `jarvis/protocol/upload_routes.py`,
`jarvis/domain/uploads.py` (`check_link_url`), relay
`jarvis/runtime/chat_relay.py`, page `jarvis/runtime/control_center_board_drop.js`.

```text
page (drop on the scene) --multipart, 1 file per request--> CC POST /api/boards/drop?board_id=<displayed Board>
  CC (same streamed relay as /api/chat/uploads) --PUT stream--> Core PUT /v1/uploads/{id}?purpose=board&board_id=…
  Core: board_id == active Board? -> sniff -> Artifact upload (auto-linked) -> check link -> relink if needed
page (drop of a link) --JSON--> CC POST /api/boards/drop-link --> Core POST /v1/uploads/links -> Artifact link (never fetched)
```

- **Files and images**: `PUT /v1/uploads/{client_upload_id}?purpose=board&board_id=…`,
  provenance `board_drop`, `source = "board_drop"`. Core requires
  `board_id == active_board_id` of the open Session (409
  `board_drop_target_inactive`): only the displayed Board takes a drop. The
  creation transaction's automatic link **is** the Board link. Check after
  creation: if `boards_of_artifact` lacks the target (switch between the check
  and the transaction), Core links it explicitly through
  `WorkspaceService.artifact_link(origin=user)` and says so (`relinked: true`).
  The user dropped on that Board only: when the Artifact was created by this
  very request (never on a replay), Core then removes the automatic
  `active_board` link that creation put on the Board that became active
  (`WorkspaceService.artifact_unlink(origin=user)`), and only a link of that
  origin; an `explicit` link (made by someone else) stays. Journal
  `core.upload.board_auto_link_removed` (`warning`). If that unlink fails,
  Core logs `core.upload.board_auto_link_remove_failed` at `error` and still
  answers with the target linked, naming the Board that keeps the stray link
  in `also_linked_board_id` (otherwise `null`; the page may ignore it).
  The active Board is checked **before** the first byte is read; the 409 body
  carries `active_board_id` (relayed by the Control Center) so the page can
  say which Board is displayed now. Same replayable identity as an attachment;
  an id already used by a chat attachment or a link → 409 `upload_conflict`.
  Answer: the attachment fields plus `board_id`, `relinked` and
  `also_linked_board_id`.
- **URL**: `POST /v1/uploads/links` `{client_upload_id, url, board_id}` →
  Artifact `kind = link`, created `complete` at once with `text = url` (like
  `record_text`), metadata `provenance = board_drop`, `host`. Accepted URL:
  `http`/`https` only, ≤ 2048 characters, no credentials (`user:pass@`), no
  control characters; else 400 `link_invalid`. **Never** fetched (no network
  request, no DNS lookup, no preview). Answer 201 (new) or 200 (replay: same
  `client_upload_id` and same URL; another URL or kind → 409 `upload_conflict`)
  `{artifact_id, kind: "link", url, host, state, replayed, board_id, relinked,
  also_linked_board_id}` (same relink rule as a file).
  Body closed, ≤ 16 KiB. In list items the link's `preview` is the URL and its
  `provenance` is given, as for an upload.
- **Control Center**: `POST /api/boards/drop?board_id=` (multipart
  `client_upload_id` then `file`, the **same** streamed relay as
  `/api/chat/uploads`, `ChatRelayRoutes._stream_upload`; exactly one
  `board_id` query parameter, else 400 `invalid_request`) and
  `POST /api/boards/drop-link` (closed JSON `{client_upload_id, url,
  board_id}`, three strings, ≤ 64 KiB; `/v1/uploads/links` is the only upload
  path `forward_json` relays). Both are in `GUARDED_PREFIXES` (every method:
  loopback Host and Origin, never `Sec-Fetch-Site: cross-site`). Journal
  `board.drop.relayed` (status, code, `artifact_id`, size, type, `relinked`)
  and `board.drop_link.relayed` (status, code, `artifact_id`, `relinked`):
  never a file name, a byte or the URL.
- **Page** (`control_center_board_drop.js`, `window.JarvisBoardDrop`):
  - **zone** = `#app` itself, the background (`.face`) and the scene
    (`#sceneLayer`, nodes included). Page controls (dock, top bar, Boards
    control, panels, Chat) are not: the Chat panel keeps its own drop
    (Slice 07b) and a drop on it never also lands on the Board;
  - listens **only** to `dragenter` / `dragover` / `dragleave` / `drop` on
    `#app`, and only when they carry `Files` or `text/uri-list` (files win when
    both are there): no pointer listener, the scene gestures (click, drag,
    menu) never pass through it. A link dropped on a page control outside an
    editable field is cancelled (`dropEffect = none`) so the browser never
    navigates away from the Control Center;
  - **layer** `#boardDrop` above the scene (z 21, `pointer-events: none`):
    « Déposer sur « <Board> » » while hovering, or the refusal in words (no
    confirmed displayed Board, Board switch in flight); it leaves on
    `dragleave`, on drop, or 450 ms without `dragover`;
  - **target** = the Board the Boards control shows (`JarvisBoardsControl`,
    status at 1 Hz); Core stays the judge (409);
  - **tray** `#boardDropTray` (bottom centre, z 34): one row per item, one
    upload at a time (queue), « Envoi N % » then « Vérification par Jarvis
    Core… », live counter, deadlines (no progress 30 s, no answer 130 s, link
    20 s → `client_timeout`), success « Ajouté au Board « … » » (with the
    relink and replay said) and « Voir dans l'inspecteur » (Workspace view
    Artefacts filtered on that Board), failures in words with « Réessayer »
    (same `client_upload_id` for an unknown outcome, a new one otherwise; none
    for `upload_too_large`, `upload_empty`, `upload_name_invalid`,
    `link_invalid`), × cancels an upload in flight; at most 20 items per
    drop, a folder is refused;
  - journal `[board-drop] board_drop.<event>` (`hover`, `dropped`,
    `upload_started`, `upload_done`, `upload_failed`, `link_started`,
    `link_done`, `link_failed`, `retry`, `cancelled`, `inspector_opened`,
    `drop_ignored`): ids, sizes, types, codes; never a file name nor a URL.
- **Tests**: `tests/unit/test_board_drop.py` (Core and relay on a real stack,
  URL inert under a network transport that fails the test on any outbound
  connection or lookup) and `tests/unit/test_board_drop_browser.py` with
  `tests/unit/_board_drop_browser.mjs` (real Core + real Control Center in
  headless Chrome: hover layer, multi-drop, URL, Chat panel drop, scene click
  and move read back in Core, Board A → B → A, reload, refusals, 600 px).
- **Visibility**: the Workspace inspector (Artifacts by Board,
  `GET /v1/workspace/artifacts?board_id=`), labels `upload` « Fichier déposé »
  / « Pièce jointe du chat » by provenance, `link` « Lien »
  (`control_center_workspace.js`, `artifact_search` kind filter in
  `capture_mcp.py`).
- **Images on the scene**: a dropped image is also shown as a Dossier window (`scene_object_id` in the answer, same path as « Afficher sur le Board », `DossierService.present`; best effort, traced `core.upload.scene_present_failed`). Other files and links stay Artifacts only: scene artifacts are explanations chosen by the Brain,
  linked by `explains` to the star they explain
  ([scene-model.md](scene-model.md)); a dropped file is not one.

## Panel

- Modules `jarvis/runtime/control_center_chat.js` (view) and
  `control_center_chat_model.js` (pure model, node-tested), injected through
  the markers `/*__CONTROL_CENTER_CHAT_MODEL_JS__*/` and
  `/*__CONTROL_CENTER_CHAT_JS__*/` of `control_center.html`, replaced by
  `control_center.py` like `LIVE_SCRIPT_MARKER`. `control_center_timeline.js`
  and its tests are not modified.
- Since 2026-10-29 the **Chat button** is an icon (a speech bubble, `#chatTab`, still the control the Chat module
  drives: `aria-expanded`, `aria-controls="chatPanel"`, focus returns to it on Esc) in the `#railDock` at the **right edge**,
  vertically centred, just **below** the « Présentations » button; the old bottom-right « CHAT » text tab is gone
  ([control-center-shell.md](control-center-shell.md) › *Right bands*). The dock steps left of the open bands.
- Panel `<section class="panel chat-panel" id="chatPanel">` reusing `.panel` (rank 33) and its tokens, but drawn as a **full-height
  band** at the right edge: `top:0; bottom:0; right:0`, `--shell-chat-w` (500 px, the old panel width) wide, no rounded corner, the shared band skin
  (`--shell-band-*`: translucent black, fine texture, slight shadow) in both themes. It is **always the rightmost band**: the
  workspace rail (272 px) sits just left of it when both are open (`--shell-chat-open-w`). Under 900 px they do not fit side by side:
  opening the Chat folds the rail (`JarvisPresentationRail.closeIfNarrow`), opening the rail closes the Chat. One *side panel* at a
  time still holds for `#panel` and the Studio inspector (opening `#panel` closes the Chat and back). Horizontal slide from the right,
  off under `prefers-reduced-motion`. The old « stops 68 px above the tab » rule is gone (the tab is no longer at the bottom); at 700 px and below the band, like any side panel,
  runs from `--shell-panel-top` to `--shell-panel-bottom` so the launcher row and the status centre stay clear.
- User and Brain bubbles through `textContent` (never HTML from content), line
  breaks kept. Multi-line composer: Enter sends, Shift+Enter breaks a line;
  Send button; no double send (button inert during the request, same
  `client_request_id` on retry).
- Voice active: history readable, composer `aria-disabled="true"` (not
  `disabled`, to keep focus and the explanation), message « Désactivez le
  vocal pour écrire » and a **Passer au chat** button; during `switching`
  « Arrêt du vocal… »; failure or expiry: message and « Réessayer ». A 409
  `chat_input_locked` received anyway switches the UI back to read-only (the
  server guard wins).
- A User bubble without a reply after 120 s shows « Toujours en cours, ou
  réponse non affichable ici — voir la chronologie complète » with a link to
  the timeline, never a fake message.
- A « Voir la chronologie complète » link opens the existing timeline
  (`#openTimeline`).

Implementation (Slice 06), beyond the rules above (the bottom-right tab rules of Slice 06 are superseded by the 2026-10-29 band; what remains):

- Toasts sit left of the open bands above 700 px (`right: gutter + --shell-rails-open-w + 12px`) and, from 940 px with a side
  panel open, left of the panel. Below 940 px wide with the Chat open, toasts sit under the panel header
  and status line (`--chat-toasts-top`, measured by the view): never over the
  composer, the title or ×. At 700 px wide or less with the Chat closed, toasts sit at the top, under the launcher
  row (now top-left). The bottom status centre stays visible with the Chat open and
  re-centres in the free space left of the bands (`--shell-rails-open-w`).
- One side panel: `openPanel` / `closePanel` of the page close the Chat;
  opening the Chat calls `closePanel` and closes the Studio inspector, whose
  own opening calls `closePanel`. Esc in the panel closes it and gives focus
  back to the tab. Known limit: like `#panel`, the open panel covers the
  top-bar Boards button; the panel subtitle repeats the active Board title.
- Pending send: after `202/200` the composer is cleared and a **note** (not a
  bubble) says « Message transmis · enregistrement… », then « Jarvis traite
  votre message… » once the user event exists, with an elapsed counter
  (`aria-hidden`); the 120 s phrase replaces it. Counters never sit inside a
  `role=status` region, and log rows are reconciled by key so `role=log`
  announces only new messages.
- `client_request_id`: one UUID v4 per text; an edited text draws a new one.
  Unknown outcome (`core_timeout`, client timeout, network) keeps the text
  and offers « Réessayer » with the same id; editing the text then replaces
  that offer with « a NEW message; the previous one may already have been
  received ». `chat_request_conflict` drops the id. A draft belongs to its
  conversation: kept per viewer in `localStorage`
  (`jarvis.chat.draft.<conversation_id>`, with `jarvis.chat.open`), restored
  when that Board comes back, never carried to another Board (a
  `chat_conversation_not_foreground` refusal leaves it on its own Board).
- Core-side `core_unreachable`, `core_timeout`, `core_unavailable` read
  « Jarvis Core ne répond pas »; « Control Center ne répond pas » only for the
  browser's own timeout or network failure. A relayed read must **outlast the
  relay** (QA S06, Slice 07b): the relay answers 504 `core_timeout` after 10 s
  (the Control Center's HTTP session budget towards Core), so the state read
  waits 13 s and the voice-disable request 12 s; a shorter client timeout cut
  that answer and blamed the Control Center. A state read slower than 3 s
  shows « Jarvis tarde à répondre · lecture de l'état » with its counter.
- **One coherent status line**: while the state cannot be read the feed line
  says « Connexion interrompue · <cause> · nouvel essai » with the time since
  the first failure, never « En direct » next to a « ne répond pas » lock. A
  read retry whose delay has passed but which waits in the browser's
  connection queue says « nouvel essai en cours » with a rising counter, never
  a frozen « dans 0 s ».
- **Followers stay bounded**: a follower keeps no row list of its own; it
  applies the leader's rows to the model (one row per `event_id`), and the
  leader answers a `hello` with the model's stored rows. Any number of
  `hello` replies leaves one row per event.
- Delays and cadences live in `JarvisChat.config` (defaults in
  `JarvisChat.DEFAULTS`): tests shorten the 120 s late note
  (`replyDeadlineMs`) without touching `Date.now`.
- Voice switch: « Passer au chat » posts the disable request, shows « Arrêt du
  vocal… » and unlocks only when `GET /api/chat/state` says
  `chat_writable`; our request `failed` / `expired`, or 15 s without an
  answer client side, shows the code and « Réessayer ». A 409
  `chat_input_locked` locks the composer until a state read issued after it
  says writable.
- Journal: browser console `[chat] chat.<event> {…}` (installed, opened,
  rescoped, hydrated, turn_sending, turn_admitted, turn_refused,
  voice_switch_requested, voice_switched, voice_switch_failed, leading,
  fast_window, read_failed, read_restored, state_failed, state_restored,
  suspended, resumed; attachments: see *Attachments* › *UI*), never message
  text nor a file name.
- Tests: `tests/unit/test_control_center_chat_ui.py` (page contract),
  `tests/unit/test_control_center_chat_browser.py` with
  `tests/unit/_chat_browser.mjs` (headless Chrome over CDP, fake Core), and
  `tests/unit/test_control_center_chat_tabs_browser.py` with
  `tests/unit/_chat_tabs_browser.mjs` (several real tabs, real HTTP server).

## Error codes

Core shape `{"error": {"code", "message", …}}`; Control Center shape
`{"ok": false, "code", "error", "core_status"}` (as `/api/conversations`). A
Core code is relayed as is.

Tests are `file::test` under `tests/` (`unit/` unless written `integration/`).

| Code | HTTP | Emitter | Case | Test |
| --- | --- | --- | --- | --- |
| `forbidden_origin` | 403 | CC | `/api/chat` guard | `integration/test_chat_end_to_end.py::test_security_cross_origin_refused_all_chat_routes`, `test_chat_relay.py::test_the_guard_refuses_foreign_requests` |
| `invalid_content_type` | 415 | CC | JSON expected | `test_chat_relay.py::test_json_only_and_bounded`, `test_upload_protocol.py::test_the_chat_guard_refuses_foreign_uploads` |
| `request_too_large` | 413 | CC | JSON body > 64 KiB | `test_chat_relay.py::test_json_only_and_bounded` |
| `invalid_request` | 400 | Core, CC | parameter or body outside the contract | `test_chat_relay.py::test_the_core_body_is_closed_and_the_answer_is_reshaped`, `integration/test_chat_projection_protocol.py::test_invalid_projection_is_400_on_core_and_control_center`, `test_upload_protocol.py::test_fields_out_of_order_or_a_bad_upload_id_are_refused`, `test_board_drop.py::test_the_drop_relay_wants_one_board_id` |
| `chat_text_too_long` | 400 | Core | `content` > 8192 characters | `test_chat_text_ingress.py::test_text_too_long_400` |
| `too_many_attachments` | 400 | Core | > `JARVIS_CHAT_MAX_ATTACHMENTS` | `test_chat_attachments_brain_context.py::test_unknown_foreign_pending_and_other_kind_attachments_are_refused` |
| `attachment_not_found` | 404 | Core | unknown id | same test |
| `attachment_not_ready` | 409 | Core | attachment not `complete` | same test, `test_chat_attachments_brain_context.py::test_non_complete_screenshot_refused` |
| `attachment_not_allowed` | 400 | Core | other kind (neither a chat attachment nor a screenshot), provenance or Session | same test, `test_chat_attachments_brain_context.py::test_an_attachment_of_another_session_is_not_allowed`, `test_chat_attachments_brain_context.py::test_screenshot_of_other_session_is_refused` |
| `attachment_other_board` | 409 | Core | attachment not linked to the Board of the turn's conversation | `test_chat_attachments_brain_context.py::test_an_attachment_of_another_board_is_refused_and_the_replay_still_answers`, `integration/test_chat_end_to_end.py::test_board_switch_A_B_A_no_leak` |
| `chat_conversation_not_foreground` | 409 | Core | target ≠ current binding | `test_chat_text_ingress.py::test_not_foreground_409` |
| `chat_input_locked` | 409 | Core | voice not disabled (`reason`) | `test_chat_text_ingress.py::test_locked_by_voice_409_each_reason`, `integration/test_chat_end_to_end.py::test_voice_active_chat_reads_but_refuses` |
| `chat_request_conflict` | 409 | Core | same `client_request_id`, other content | `test_chat_text_ingress.py::test_same_request_other_text_409_conflict`, `test_chat_attachments_brain_context.py::test_replay_compares_the_attachments` |
| `session_not_found`, `binding_not_found` | 404 | Core | existing `BoardError` codes, no open Session or binding | `test_chat_relay.py::test_core_codes_are_relayed`, `test_upload_protocol.py::test_no_session_means_no_upload` (existing codes: `test_workspace_board_contract.py::test_error_codes_are_stable_and_all_mapped_to_http`) |
| `core_unavailable` | 503 | Core | existing code, Session service not wired | `test_chat_relay.py::test_core_codes_are_relayed` (relayed as is) |
| `core_stopping` | 503 | Core | existing code (`submit_brain_turn`) | `test_chat_relay.py::test_core_codes_are_relayed` (relay), `integration/test_v2_brain_protocol.py::test_brain_turn_is_refused_with_503_while_core_stops` |
| `core_unreachable` | 503 | CC | Core unreachable | `test_chat_relay.py::test_core_timeout_is_a_504_to_replay`, `test_voice_channel_protocol.py::test_core_unreachable_is_a_503_without_core_status` |
| `core_timeout` | 504 | CC | outcome unknown, replay | `test_chat_relay.py::test_core_timeout_is_a_504_to_replay`, `integration/test_chat_end_to_end.py::test_retry_after_timeout_no_duplicate` |
| `core_unconfigured` | 503 | CC | the Control Center does not know Core (no transport configured; `jarvis/runtime/chat_relay.py`) | no test |
| `core_unauthorized`, `invalid_core_response` | 502 | CC | existing codes | no chat-specific test (existing relay codes) |
| `voice_disable_failed` | — (in `request.code`) | Voice | `mute()` raised or left `error` | `test_voice_channel_reporter.py::test_a_mute_that_raises_is_acknowledged_failed`, `test_voice_channel_service.py::test_failed_ack_falls_back_to_the_last_report` |
| `voice_disable_expired` | — (in `request.code`) | Core | no ack within 10 s | `test_voice_channel_service.py::test_request_expires_after_ten_seconds` |
| `upload_too_large` | 413 | Core | bound exceeded | `test_upload_service.py::test_exactly_the_bound_is_accepted_and_one_byte_more_is_refused`, `test_upload_protocol.py::test_the_bound_is_held_through_the_relay` |
| `upload_empty` | 400 | Core | empty body | `test_upload_service.py::test_an_empty_file_is_refused_and_writes_nothing` |
| `upload_incomplete` | 400 | Core | fewer bytes than `Content-Length` | `test_upload_service.py::test_a_short_body_is_incomplete_and_failed`, `test_upload_protocol.py::test_a_browser_that_stops_mid_file_leaves_a_failed_artifact_and_no_partial` |
| `upload_name_invalid` | 400 | Core | unreadable or too long name | `test_uploads_domain.py::test_unreadable_or_too_long_names_are_refused` (domain rule; the HTTP mapping has no dedicated test) |
| `upload_conflict` | 409 | Core | same `client_upload_id`, other bytes | `test_upload_service.py::test_replay_with_other_bytes_is_a_conflict`, `test_upload_service.py::test_a_replay_after_a_failed_attempt_is_a_conflict` |
| `upload_in_progress` | 409 | Core | same `client_upload_id` in progress | `test_upload_service.py::test_a_concurrent_upload_of_the_same_id_is_in_progress` |
| `upload_storage_failed` | 503 | Core | payload refused (`artifact_payload_*`) | `test_upload_service.py::test_a_storage_refusal_names_its_os_error_and_errno`, `test_upload_service.py::test_a_path_beyond_max_path_is_a_coded_storage_failure` |
| `board_drop_target_inactive` | 409 | Core | drop on a Board that is not active | `test_board_drop.py::test_drop_on_inactive_board_409` |
| `link_invalid` | 400 | Core | URL refused | `test_board_drop.py::test_url_refused_schemes_and_credentials` |

## Configurable bounds

| Setting | Default | Where |
| --- | --- | --- |
| `JARVIS_UPLOAD_MAX_BYTES` | 64 MiB per file | Core upload service |
| `JARVIS_CHAT_MAX_ATTACHMENTS` | 10 per message | Core `brain-turns` (text) |

Fixed bounds: text 8192 characters (event content bound), JSON body 64 KiB,
original name 255 characters, URL 2048 characters, voice freshness 5 s,
disable expiry 10 s, Core relay budget 15 s. The bounds are technical; the UI
and the errors state them.

Both settings are read from the process environment at each use
(`upload_bounds(os.environ)`, `jarvis/domain/uploads.py`): by Core for the
upload stream and the per-message count, by the Control Center for its early
`Content-Length` refusal, so both processes must see the same value. A value
that is not a positive integer, or above the hard cap (4 GiB per file, 64
attachments = `MAX_TURN_ATTACHMENTS`), is ignored and the default kept; no
journal line says so today. How to set them: [OPERATIONS.md](OPERATIONS.md)
› *Chat et dépôt sur le Board*. Held by
`tests/unit/test_uploads_domain.py::test_bounds_are_read_from_the_environment_and_never_beyond_the_hard_cap`,
`tests/unit/test_uploads_domain.py::test_upload_is_a_kind_and_hard_bounds_agree`,
`tests/unit/test_upload_service.py::test_exactly_the_bound_is_accepted_and_one_byte_more_is_refused`,
`tests/unit/test_upload_protocol.py::test_an_announced_body_above_the_bound_is_refused_by_the_control_center`,
`tests/unit/test_chat_text_ingress.py::test_text_too_long_400`.

## Data locations

Everything under the PC's data root ([local-data.md](local-data.md)): events
and turns in `state/jarvis.sqlite3` (unchanged), attachment and drop payloads in
`artifacts/<artifact_id>/upload.<ext>`. The voice channel state is in Core's
memory. Files under `runtime/` (`.voice_*`) gain nothing. Tests use `tmp_path`
and an isolated root, never a repository database.

**No second chat log.** There is no chat table, chat JSONL, transcript file or
durable message cache: the Chat reads the conversation events only. Checked at
Slice 10 by a repository search (command and result in the handoff,
`slices/10-release-and-human-acceptance/evidence/RESULTS.md`); no SQLite schema change (`tests/unit/test_schema_migrations.py`,
schema versions unchanged at 8 and 1).

## Known limits

1. **8192-character event content.** An event content is bounded by
   `MAX_CONTENT_CHARS = 8192`; a longer outcome **is not recorded**
   ([conversation-events.md](conversation-events.md)), so the Chat cannot show
   a Brain reply above 8192 characters. Mitigations: text input bounded to
   8192 (`chat_text_too_long`); the text-channel brief asks for at most 6000
   characters and a file beyond; the 120 s pending message. Raising the bound
   is an event contract change, out of scope (handoff ISSUE-01).
   Held by `tests/unit/test_conversation_events.py::test_invalid_payloads_fail_with_precise_messages`
   (« content exceeds »), `tests/unit/test_chat_text_ingress.py::test_text_too_long_400`
   (8192 admitted, 8193 refused), `tests/unit/test_control_center_chat_ui.py::test_tab_and_panel_ids_roles_and_reuse_of_panel`
   (`maxlength="8192"`).
2. **Automatic link to the active Board.** The existing rule links every new
   Artifact to the active Board (`link_to_active_board`): a chat attachment
   appears in the Board's Artifacts, marked `chat_attachment`. Changing that
   global rule is out of scope.
   Held by `tests/unit/test_chat_attachments_brain_context.py::test_an_attachment_of_another_board_is_refused_and_the_replay_still_answers`
   (the attachment belongs to the Board active at its upload) and
   `tests/unit/test_board_drop.py::test_file_drop_links_active_board`.
3. **`--add-dir` grants all of `<data_root>/artifacts`**, not only
   attachments, for want of a per-turn grant.
   Held by `tests/unit/test_chat_attachments_brain_context.py::test_artifacts_root_is_granted_like_sessions_root`.
4. **No file-only message**: a message must carry text. Held by
   `tests/unit/test_control_center_chat_attachments_browser.py::test_text_required_with_files`.
5. **Only images get a scene window on a Board drop** (files and links: inspector and rail only)
   (`tests/unit/test_board_drop.py::test_an_image_drop_is_shown_as_a_scene_window`). A drop on a
   prefab window of the scene (its own `iframe`) reaches that frame, not the
   page: nothing happens there. Held by
   `tests/integration/test_chat_end_to_end.py::test_board_drop_file_image_url_visible_no_turn`
   (no `scene_object`, no event, no Brain turn) and
   `tests/unit/test_board_drop.py::test_no_conversation_event_no_brain_turn`; the prefab-window case
   has no test (not reproduced by QA S8).
6. **The Brain's tool journal may hold what it read.** The CLI event journal
   (`jarvis/runtime/claude_local.py`, raw tool results in `runtime/trace.jsonl`)
   already records the Brain's tool results, for any file it reads, voice turns
   included: a `Read` of an attachment can put its content there. Pre-existing
   local diagnostic behaviour, out of scope; the chat and upload code itself
   never writes attachment bytes nor original names.
   The chat side is held by `tests/unit/test_upload_service.py::test_the_journal_never_carries_the_original_name`
   and `tests/integration/test_chat_end_to_end.py::test_no_bytes_or_names_in_trace_and_events`;
   the CLI journal itself has no test (pre-existing).
7. **`artifacts_root` reaches the local page** through `/api/sessions/current`
   (`context.artifacts_root`, next to `sessions_root`, loopback guard), as
   `sessions_root` already does; the chat routes never return a path. Held by
   `tests/unit/test_chat_attachments_brain_context.py::test_the_session_payload_names_artifacts_root`.
8. **Retry on `upload_in_progress`** is manual (« Réessayer », same id), not
   automatic; and the **same file attached twice** makes two uploads, hence two
   Artifacts (no client-side dedupe by content). Recorded by QA S7b, left as is.
   The manual same-id retry is held by
   `tests/unit/test_control_center_chat_model_js.py::test_attachment_retry_identity_rules`; the
   double upload has no test (recorded behaviour, not a rule).

9. **An attachment's Board is the one active when Core creates it.** A chat
   upload carries no Board: its automatic link goes to the Board active in its
   creation transaction (after Core has read the first 64 KiB). A Board switch
   in that instant links it to the new Board, and a turn of the original
   conversation then gets 409 `attachment_other_board` (« joignez le fichier à
   nouveau ici »); never the reverse leak. An `explicit` link made in the
   Workspace inspector makes the attachment sendable from that Board too. The
   refusal is held by `tests/unit/test_chat_attachments_brain_context.py::test_an_attachment_of_another_board_is_refused_and_the_replay_still_answers`;
   the switch inside the creation instant has no test.
10. **Windows MAX_PATH on payloads.** A payload path longer than the Windows
    limit (259 characters for the file, 248 for its folder; no long-path
    prefix, `LongPathsEnabled` not assumed) is refused before any disk access:
    503 `upload_storage_failed`, `cause.path_limit` set in `core.upload.refused`.
    It only happens with a deep data root (`JARVIS_DATA_ROOT`); the default
    `~/.jarvis/instances/...` root normally stays below. Not fixed: shorten the data
    root. Held by `tests/unit/test_upload_service.py::test_a_path_beyond_max_path_is_a_coded_storage_failure`.

## Conformance

Level 3 index: each rule of this page and the test that holds it. Paths are
under `tests/` (`unit/` unless written `integration/`); names were checked
against the Slice 10 HEAD of handoff jarvis-unified-chat-and-board-drop. The
end-to-end file `integration/test_chat_end_to_end.py` replays the chain on a
real Core and Control Center (fake Brain backend; one Category 2 scenario with
the real CLI behind `JARVIS_LIVE_CLAUDE=1`). Error codes: *Error codes* ›
*Test*; bounds: *Configurable bounds*; limits: *Known limits* › *Held by*.

| Section | Rule | Test |
| --- | --- | --- |
| *Projection* | the three types only, `addressing` allow-list | `test_chat_projection.py::test_is_chat_event_allowlist_exhaustive`, `test_chat_projection.py::test_is_chat_event_addressing`, `test_control_center_chat_model_js.py::test_is_chat_event_allowlist_exhaustive` |
| *Projection* | `uncertain` held until promoted, declined never shown | `test_chat_projection.py::test_uncertain_hidden_until_promoted`, `test_chat_projection.py::test_refused_uncertain_never_shown`, `test_chat_projection.py::test_cursor_split_promotion` |
| *Projection* | `brain.turn.failed` = status of the user bubble, ignored on a system turn | `test_chat_projection.py::test_failed_status_on_user_bubble`, `test_chat_projection.py::test_failed_on_system_turn_ignored`, `test_chat_projection.py::test_failed_on_unpromoted_uncertain_ignored` |
| *Projection* | the 17 fixture cases, Python and JS alike; `ChatItem` shape | `test_chat_projection.py::test_fixture_cases_python`, `test_chat_projection.py::test_fixture_item_shape_is_the_contract`, `test_control_center_chat_model_js.py::test_fixture_parity_with_python_reference` |
| *Projection* | idempotent replay by `event_id`, any page order | `test_chat_projection.py::test_page_replay_idempotent`, `test_chat_projection.py::test_fixture_cases_any_page_order` |
| *Scope* | only the binding's conversation; a Board change never merges | `test_chat_projection.py::test_other_conversation_never_counts`, `test_control_center_chat_model_js.py::test_reset_on_board_change_never_merges`, `integration/test_chat_end_to_end.py::test_board_switch_A_B_A_no_leak`, `test_control_center_chat_browser.py::test_board_switch_rescopes` |
| *Reading* | `projection=chat` strict, cursor past filtered rows, long-poll past hidden events | `test_chat_projection_query.py::test_projection_param_strict`, `test_chat_projection_query.py::test_filtered_page_advances_cursor`, `test_chat_projection_query.py::test_long_poll_waits_past_hidden_events` |
| *Reading* | reload = live; route without `projection` unchanged; origin guard | `test_chat_projection_query.py::test_union_reload_equals_live`, `integration/test_chat_projection_protocol.py::test_hydration_then_long_poll_equals_the_projection_of_the_store`, `integration/test_chat_projection_protocol.py::test_the_route_without_projection_is_unchanged`, `integration/test_chat_projection_protocol.py::test_the_origin_guard_holds_for_the_chat_projection`, `integration/test_chat_end_to_end.py::test_reload_equals_live_union` |
| *Reading* › live | short sequential reads, one reader per profile, none when closed or hidden | `test_control_center_chat_browser.py::test_cadence_short_reads_one_at_a_time`, `test_control_center_chat_browser.py::test_one_reader_per_profile_and_none_when_closed_or_hidden`, `test_control_center_chat_tabs_browser.py::test_two_visible_chat_tabs_stay_responsive_and_a_follower_send_succeeds`, `test_control_center_chat_tabs_browser.py::test_the_chat_adds_no_held_connection_with_three_tabs_and_a_timeline` |
| *Sending text* › CC | guard, JSON only, 64 KiB, closed body, Core codes relayed with `reason` / `current_conversation_id` | `test_chat_relay.py::test_the_guard_refuses_foreign_requests`, `test_chat_relay.py::test_json_only_and_bounded`, `test_chat_relay.py::test_the_core_body_is_closed_and_the_answer_is_reshaped`, `test_chat_relay.py::test_core_codes_are_relayed` |
| *Sending text* › CC | 504 `core_timeout` to replay; `forward_json` never relays `cancel` nor `turns` | `test_chat_relay.py::test_core_timeout_is_a_504_to_replay`, `test_chat_relay.py::test_the_core_client_forwards_brain_turns_but_never_cancel_or_turns`, `test_chat_relay.py::test_the_real_chain_admits_a_text_turn` |
| *Sending text* › CC | the browser never calls `/api/agent/ask` nor `/api/agent/send` | `test_control_center_chat_ui.py::test_the_view_only_calls_chat_routes_and_never_the_agent_bridge` |
| *Sending text* › Core | step 1 (8192 characters, attachment count) | `test_chat_text_ingress.py::test_text_too_long_400`, `test_chat_attachments_brain_context.py::test_unknown_foreign_pending_and_other_kind_attachments_are_refused` |
| *Sending text* › Core | step 2 replay first (200 duplicate even when locked) | `test_chat_text_ingress.py::test_replay_after_lock_returns_duplicate_200` |
| *Sending text* › Core | step 3 foreground binding | `test_chat_text_ingress.py::test_text_turn_reaches_foreground_binding_brain`, `test_chat_text_ingress.py::test_not_foreground_409` |
| *Sending text* › Core | step 4 voice lock, each `reason`; voice absent allows; no `await` before `submit` | `test_chat_text_ingress.py::test_locked_by_voice_409_each_reason`, `test_chat_text_ingress.py::test_voice_absent_allows`, `test_chat_text_ingress.py::test_no_loop_iteration_between_write_gate_and_submit`, `test_voice_channel_service.py::test_write_gate_is_synchronous` |
| *Sending text* › Core | step 5 attachments, in message order; a voice turn with attachments is refused | `test_chat_attachments_brain_context.py::test_unknown_foreign_pending_and_other_kind_attachments_are_refused`, `test_chat_attachments_brain_context.py::test_an_attachment_of_another_session_is_not_allowed`, `test_chat_attachments_brain_context.py::test_an_attachment_of_another_board_is_refused_and_the_replay_still_answers`, `test_chat_attachments_brain_context.py::test_attachments_on_a_voice_turn_are_refused` |
| *Sending text* › Core | step 6 one user event per turn | `test_chat_text_ingress.py::test_single_user_event_per_turn` |
| *Sending text* | race: a turn admitted before a voice wake-up stays | `integration/test_chat_end_to_end.py::test_reactivation_relocks_and_inflight_turn_kept` |
| *Idempotence* | same id with other text or attachments → 409; a retry after a timeout makes no duplicate | `test_chat_text_ingress.py::test_same_request_other_text_409_conflict`, `test_chat_attachments_brain_context.py::test_replay_compares_the_attachments`, `integration/test_chat_end_to_end.py::test_retry_after_timeout_no_duplicate`, `test_control_center_chat_browser.py::test_retry_reuses_client_request_id`, `test_control_center_chat_browser.py::test_edited_text_after_unknown_outcome_is_a_new_message` |
| *What the Brain receives* | `channel = text`, brief line, same tools and sub-agents | `test_chat_text_ingress.py::test_delegation_available`, `integration/test_chat_end_to_end.py::test_text_turn_no_speech_requested` |
| *What the Brain receives* | a turn without attachments is unchanged byte for byte | `test_chat_attachments_brain_context.py::test_turn_without_attachments_keeps_its_context_and_brief_byte_for_byte` |
| *Text disposition* | text turn published, never spoken, also after a Core restart; voice turn still spoken; notices unchanged | `test_speech_text_channel.py::test_text_turn_result_published_not_spoken`, `test_speech_text_channel.py::test_late_work_result_after_core_restart_not_spoken`, `test_speech_text_channel.py::test_voice_turn_still_spoken`, `test_speech_text_channel.py::test_notice_policy_unchanged` |
| *Voice channel* › report | closed body, `seq` per incarnation, stale ignored and journaled, token | `test_voice_channel_domain.py::test_strict_validation`, `test_voice_channel_domain.py::test_seq_ordering_and_incarnations`, `test_voice_channel_service.py::test_stale_seq_is_ignored_and_journaled`, `test_voice_channel_protocol.py::test_a_malformed_report_is_a_strict_400`, `test_voice_channel_protocol.py::test_a_stale_report_is_answered_but_ignored`, `test_voice_channel_protocol.py::test_core_routes_require_the_token` |
| *Voice channel* › Voice side | reports never raise, `connecting` before the microphone, bounded wait, ack resent | `test_voice_channel_reporter.py::test_reports_carry_one_incarnation_and_a_strictly_increasing_seq`, `test_voice_channel_reporter.py::test_connecting_is_reported_before_the_microphone_opens`, `test_voice_channel_reporter.py::test_a_slow_core_delays_activation_at_most_half_a_second`, `test_voice_channel_reporter.py::test_core_unreachable_never_raises_and_is_journaled_once_per_episode`, `test_voice_channel_reporter.py::test_an_ack_that_could_not_be_delivered_is_resent` |
| *Voice channel* › disable | idempotent request, nothing to do when absent or background, 10 s expiry, failed ack, settled by `background` | `test_voice_channel_service.py::test_disable_round_trip_accepted`, `test_voice_channel_service.py::test_same_client_request_id_is_idempotent`, `test_voice_channel_service.py::test_nothing_to_do_when_absent_or_background`, `test_voice_channel_service.py::test_request_expires_after_ten_seconds`, `test_voice_channel_service.py::test_failed_ack_falls_back_to_the_last_report`, `test_voice_channel_service.py::test_background_without_ack_settles_the_request` |
| *Voice channel* › disable | Voice mutes once and acknowledges; `connecting` waits for `active`; beyond the expiry the Chat stays locked | `test_voice_channel_reporter.py::test_a_request_mutes_once_then_acknowledges_and_unlocks_the_chat`, `test_voice_channel_reporter.py::test_already_in_background_acknowledges_without_muting`, `test_voice_channel_reporter.py::test_a_request_during_connecting_waits_for_active_then_mutes`, `test_voice_channel_reporter.py::test_connecting_beyond_the_expiry_leaves_the_chat_locked`, `test_voice_channel_reporter.py::test_a_stale_ack_resent_with_a_non_background_state_is_failed` |
| *Voice channel* › state | the state table, 5 s freshness, start-up grace, wake-up during `switching`, new epoch | `test_voice_channel_domain.py::test_the_full_state_table`, `test_voice_channel_domain.py::test_freshness_boundary`, `test_voice_channel_domain.py::test_startup_grace_without_any_report`, `test_voice_channel_service.py::test_wake_up_during_switching_stays_locked_and_relocks_after`, `test_voice_channel_service.py::test_a_new_core_has_a_new_epoch`, `integration/test_chat_end_to_end.py::test_core_restart_cursor_survives_and_unknown_grace` |
| *Voice channel* | the whole switch through Core and the Control Center; the relay never forwards a report | `test_voice_channel_protocol.py::test_the_full_switch_through_core_and_the_control_center`, `test_voice_channel_protocol.py::test_the_relay_never_forwards_a_voice_report`, `integration/test_chat_end_to_end.py::test_switch_to_chat_then_text_turn_same_binding` |
| *Voice channel* | the switch never stops a sub-agent | `integration/test_chat_end_to_end.py::test_subagent_survives_switch` |
| *Attachments* › Core | replayable identity, replay, conflict, in progress | `test_uploads_domain.py::test_identity_is_deterministic_and_a_valid_artifact_id`, `test_upload_service.py::test_identical_replay_returns_the_same_artifact_never_a_double`, `test_upload_service.py::test_replay_with_other_bytes_is_a_conflict`, `test_upload_service.py::test_a_concurrent_upload_of_the_same_id_is_in_progress` |
| *Attachments* › Core | stream bound, no `.partial` left, a dead Core's `pending` → `upload_interrupted` | `test_upload_service.py::test_bound_exceeded_in_flow_fails_without_final_file_nor_partial`, `test_upload_service.py::test_a_body_cut_mid_stream_is_incomplete_and_leaves_no_partial`, `test_upload_service.py::test_a_partial_left_there_is_never_overwritten`, `test_upload_service.py::test_a_pending_upload_from_a_dead_core_is_failed_without_payload` |
| *Attachments* › Core | the sniffed type wins over name and declared type; display name cleaned | `test_uploads_domain.py::test_sniffing_by_leading_bytes`, `test_uploads_domain.py::test_the_declared_name_never_changes_the_sniffed_type_nor_the_payload_extension`, `test_upload_service.py::test_declared_type_and_lying_extension_lose_to_the_sniffed_bytes`, `test_uploads_domain.py::test_original_names_are_cleaned_for_display` |
| *Attachments* › Core | `brain_readable` per agent (Codex reads nothing) | `test_uploads_domain.py::test_brain_readability_is_per_agent`, `test_upload_service.py::test_codex_reads_nothing`, `test_upload_protocol.py::test_brain_readability_follows_the_foreground_agent` |
| *Attachments* › Core | journal: ids, sizes, codes, `cause` without a path; never a name nor a byte | `test_upload_service.py::test_the_journal_never_carries_the_original_name`, `test_upload_service.py::test_a_storage_refusal_names_its_os_error_and_errno`, `test_upload_protocol.py::test_the_journal_has_ids_sizes_and_codes_never_the_name_nor_bytes`, `integration/test_chat_end_to_end.py::test_no_bytes_or_names_in_trace_and_events` |
| *Attachments* › CC | streamed relay (> 6 MiB), early 413, malformed requests never reach Core, guard, no Session → 404 | `test_upload_protocol.py::test_a_file_above_six_mib_goes_through_as_a_stream`, `test_upload_protocol.py::test_an_announced_body_above_the_bound_is_refused_by_the_control_center`, `test_upload_protocol.py::test_malformed_requests_never_reach_core`, `test_upload_protocol.py::test_the_chat_guard_refuses_foreign_uploads`, `test_upload_protocol.py::test_no_session_means_no_upload` |
| *Attachments* › CC | `brain_readable` is Core's, never recomputed by the relay | `test_upload_protocol.py::test_the_relay_answers_core_brain_readable_never_its_own` |
| *Reference given to the Brain* | data block with paths, unreadable without a path, a deleted one said unavailable | `test_chat_attachments_brain_context.py::test_attachments_reach_the_brief_as_data_with_their_paths`, `test_chat_attachments_brain_context.py::test_an_attachment_deleted_after_admission_is_said_unavailable`, `integration/test_chat_end_to_end.py::test_unreadable_attachment_announced` |
| *Reference given to the Brain* | `artifacts_root` in the Session payload, granted like `sessions_root` | `test_chat_attachments_brain_context.py::test_the_session_payload_names_artifacts_root`, `test_chat_attachments_brain_context.py::test_artifacts_root_is_granted_like_sessions_root` |
| *Reference given to the Brain* | the real CLI reads a PDF and a PNG (Category 2) | `integration/test_chat_end_to_end.py::test_attachments_pdf_png_read_by_real_cli` (`JARVIS_LIVE_CLAUDE=1`) |
| *Attachments* › UI | attach by button and panel drop; a drop elsewhere is ignored; keyboard | `test_control_center_chat_attachments_browser.py::test_select_two_files_then_send`, `test_control_center_chat_attachments_browser.py::test_drop_two_files_on_panel`, `test_control_center_chat_attachments_browser.py::test_drop_outside_panel_ignored`, `test_control_center_chat_attachments_browser.py::test_keyboard_accessible_attach_button` |
| *Attachments* › UI | states; unreadable and too large said before sending; remove | `test_control_center_chat_attachments_browser.py::test_unreadable_format_announced`, `test_control_center_chat_attachments_browser.py::test_too_large_shows_limit`, `test_control_center_chat_attachments_browser.py::test_remove_before_send`, `test_control_center_chat_model_js.py::test_attachment_lifecycle_states_and_send_rules` |
| *Attachments* › UI | `client_upload_id` on retry | `test_control_center_chat_attachments_browser.py::test_retry_reuses_client_upload_id`, `test_control_center_chat_model_js.py::test_attachment_retry_identity_rules` |
| *Attachments* › UI | send rules: uploading, text required, the voice lock blocks the send only | `test_control_center_chat_attachments_browser.py::test_send_blocked_while_uploading`, `test_control_center_chat_attachments_browser.py::test_text_required_with_files`, `test_control_center_chat_attachments_browser.py::test_voice_lock_blocks_send_not_preparation` |
| *Attachments* › UI | Board change `stale`, round trip, reload record | `test_control_center_chat_attachments_browser.py::test_board_switch_marks_pending_attachments`, `test_control_center_chat_attachments_browser.py::test_board_round_trip_keeps_the_live_upload`, `test_control_center_chat_attachments_browser.py::test_real_reload_during_upload_shows_interrupted_once`, `test_control_center_chat_model_js.py::test_restore_dedupes_by_client_upload_id` |
| *Attachments* › UI | layout with 10 files, `<bdi>` names, one-line hint, one sentence per refusal | `test_control_center_chat_attachments_browser.py::test_ten_files_rows_keep_their_content_and_composer_stays_in_panel`, `test_control_center_chat_attachments_browser.py::test_sent_names_are_bidi_isolated`, `test_control_center_chat_attachments_browser.py::test_hint_stays_on_one_line`, `test_control_center_chat_ui.py::test_every_core_attachment_refusal_of_a_turn_has_its_own_sentence` |
| *Board drop* | file and image on the active Board; inactive Board → 409 | `test_board_drop.py::test_file_drop_links_active_board`, `test_board_drop.py::test_image_drop_sniffed`, `test_board_drop.py::test_drop_on_inactive_board_409` |
| *Board drop* | switch race: relink, remove only this creation's automatic link, keep `explicit`, never on a replay | `test_board_drop.py::test_switch_race_relinks_target`, `test_board_drop.py::test_switch_race_keeps_explicit_link_of_other_board`, `test_board_drop.py::test_switch_race_unlink_failure_keeps_target`, `test_board_drop.py::test_replay_never_removes_auto_link` |
| *Board drop* | URL inert (no network, no DNS); refused schemes and credentials | `test_board_drop.py::test_url_inert_no_network`, `test_board_drop.py::test_url_refused_schemes_and_credentials`, `test_board_drop.py::test_check_link_url_keeps_the_url_and_lowercases_the_host`, `test_board_drop.py::test_the_network_guard_bites` |
| *Board drop* | never a turn, an event or a conversation; idempotent; ids never shared with the chat | `test_board_drop.py::test_no_conversation_event_no_brain_turn`, `test_board_drop.py::test_duplicate_drop_idempotent`, `test_board_drop.py::test_a_chat_attachment_id_is_never_replayed_as_a_board_drop`, `test_board_drop.py::test_a_chat_upload_refuses_a_board_id` |
| *Board drop* | A → B → A; relay guard and closed bodies | `test_board_drop.py::test_drops_stay_on_board_a_across_a_b_a`, `test_board_drop.py::test_the_drop_routes_are_guarded`, `test_board_drop.py::test_the_drop_relay_wants_one_board_id`, `test_board_drop.py::test_the_link_relay_wants_a_closed_body` |
| *Board drop* › page | real page: layer, multi-drop, URL, Chat panel drop, scene still usable, refusals in words, narrow screens | `test_board_drop_browser.py::test_board_drop_in_a_real_page`, `test_board_drop_browser.py::test_refusals_are_said_in_words_and_narrow_screens_fit`, `integration/test_chat_end_to_end.py::test_board_drop_file_image_url_visible_no_turn` |
| *Panel* | markers, ids and roles, one side panel, no event content as HTML | `test_control_center_chat_ui.py::test_markers_are_replaced_model_before_view_inside_the_page_script`, `test_control_center_chat_ui.py::test_tab_and_panel_ids_roles_and_reuse_of_panel`, `test_control_center_chat_ui.py::test_no_event_content_reaches_html`, `test_control_center_chat_browser.py::test_board_and_studio_open_alongside` |
| *Panel* | layout: tab, dock, toasts, pills, narrow and low screens, Cosmos | `test_control_center_chat_ui.py::test_layout_rules_tab_bottom_right_toasts_above_it_one_panel_at_a_time`, `test_control_center_chat_browser.py::test_opens_bottom_right_no_overlap_with_dock_and_toasts`, `test_control_center_chat_browser.py::test_pills_tab_stays_whole_and_clickable_and_panel_spares_it`, `test_control_center_chat_browser.py::test_narrow_viewport_480px`, `test_control_center_chat_browser.py::test_narrow_toasts_spare_the_panel_header_and_voice_hint_hides`, `test_control_center_chat_browser.py::test_low_viewport_toast_spares_the_panel_and_its_hint`, `test_control_center_chat_browser.py::test_cosmos_theme_keeps_tab_panel_and_dock_apart` |
| *Panel* | toasts clear of the bottom-left Board card (the interaction-mode button until Slice 02 of the wheel/dossier refactor) at 700 px wide or less | `test_boards_card_browser.py::test_sous_700px_la_carte_ne_recouvre_pas_la_palette_bare_hands` (500 × 700), `test_boards_card_browser.py::test_un_releve_force_affiche_sa_ligne_et_son_code` (`deaf`, 500 × 700) |
| *Panel* | keyboard, pending note not a bubble, late note, reduced motion | `test_control_center_chat_browser.py::test_keyboard_enter_shift_enter_tab_order`, `test_control_center_chat_browser.py::test_pending_is_a_state_not_a_bubble_until_accepted`, `test_control_center_chat_browser.py::test_late_reply_note_after_the_configured_delay`, `test_control_center_chat_browser.py::test_reduced_motion` |
| *Panel* | voice lock, « Passer au chat », a failure stays locked, the server 409 wins | `test_control_center_chat_browser.py::test_locked_when_voice_active_and_explains`, `test_control_center_chat_browser.py::test_switch_to_chat_unlocks_after_ack`, `test_control_center_chat_browser.py::test_switch_failure_stays_locked`, `test_control_center_chat_browser.py::test_server_409_overrides_ui`, `integration/test_chat_end_to_end.py::test_voice_active_chat_reads_but_refuses` |
| *Panel* | Core blamed for Core's failures; one coherent status; no frozen countdown; bounded followers | `test_control_center_chat_browser.py::test_core_side_failures_name_jarvis_core`, `test_control_center_chat_browser.py::test_core_hang_blames_core_not_the_control_center`, `test_control_center_chat_ui.py::test_state_read_outlasts_the_relay_so_core_is_blamed`, `test_control_center_chat_browser.py::test_one_coherent_status_never_live_beside_the_lock`, `test_control_center_chat_browser.py::test_retry_in_flight_never_sticks_at_zero`, `test_control_center_chat_browser.py::test_follower_rows_stay_bounded_after_many_hellos` |
| Invariants | every chat route behind the guard; no SQLite migration | `integration/test_chat_end_to_end.py::test_security_cross_origin_refused_all_chat_routes`, `test_schema_migrations.py` (versions 8 and 1 unchanged) |
