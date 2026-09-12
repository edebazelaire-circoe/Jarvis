# Final Implementation Report - Jarvis Realtime + Async Brain

> Rapport historique du 2026-09-09. Pour la reprise et la validation du code
> actuel le 2026-09-12, voir
> [ORCHESTRATION.md](../../tasks/jarvis-realtime-brain-orchestration/ORCHESTRATION.md).
> Les travaux ultérieurs du dépôt ont notamment ajouté le duplex et Solo Owner ;
> les limitations énumérées ici décrivent la livraison initiale.

Date: 2026-09-09. Covers Tasks 00 to 12 of `docs/handoff-realtime-brain/`.
Written from `templates/final-implementation-report-template.md`.

Read the three "not verified" statements in *Tests Run* before treating anything
here as released. They are not caveats added for form: no hardware recipe, no
live provider run, and no confirmation of the brain's calendar/reminder access
was ever executed in this handoff.

## Summary

The handoff asked for one thing: stop letting a small realtime model own the
truth, and give Jarvis a brain that survives the voice surface. That landed.

Core now owns a long-lived `BrainOrchestrator` with typed turns, public working
state, work identifiers and intent revisions. The realtime surface, in the new
mode, is reduced to a mouth and a pair of ears: it holds no tools at all, it may
only acknowledge, repair a mishearing or ask what it heard, and every completed
user turn is submitted to Core, which decides and speaks back through typed
speech requests. Interruption stops the sound without cancelling the work; mute
stops the voice without stopping Core.

None of that is the default. `JARVIS_VOICE_ARCH=continuous_brain` is opt-in, and
the default `legacy` path is unchanged and still shipped, because the acoustics
of holding the microphone open while the speakers play were never measured on
real hardware, and because the new mode removes calendar and reminder tools from
the surface without proof that the brain can replace them.

Suite at the end of Task 12b: **686 passed, 4 skipped, 0 failed**, and
`scripts/verify_release.py` reported `Release verification passed.` An independent
critique then ran in a fresh context and found three real gaps; the corrections that
followed - the second Decision 34 barrier, the routing of uncertain turns (Decision 44,
the user's own call), and the brain context payload (Decision 45) - bring the suite to
**706 passed, 4 skipped, 0 failed**, verification still green.

## Implemented Architecture

Three processes, unchanged in shape from the existing repository:

| Process | Command | Owns |
| --- | --- | --- |
| Core | `python -m jarvis core` | conversations, jobs, tools, confirmation policy, the brain; loopback HTTP + `/v1/events` |
| Voice | `python -m jarvis voice` | wake word, audio devices, the Realtime session, speech scheduling |
| Control Center | `python -m jarvis control-center` | browser panel, trace/error console, settings, the local Claude/Codex agent |

```text
microphone ──► Realtime surface (reflexes only, empty tool catalogue)
                    │  completed user turn
                    ▼
        POST /v1/conversations/{id}/brain-turns
                    ▼
              Core BrainOrchestrator ──► BrainBackend ──► POST /api/agent/ask
                    │                                     (Claude or Codex CLI)
                    │  brain.* envelopes over /v1/events
                    ▼
              Voice SpeechScheduler ──► session.speak() ──► speakers
```

Nothing new was invented at the transport layer: brain events reuse the existing
`ProtocolEnvelope` and `CoreEventBus`, and Voice subscribes through the existing
`/v1/events` WebSocket. No second IPC server, no parallel event framework.

New provider-neutral ports live in `jarvis/ports/v2.py`: `BrainBackend`,
`RealtimeOutputControl` (`speak` / `cancel_output` / `truncate`), `WorkCanceller`,
`JobProgressSink`. Output control is a **separate** port with a capability probe
rather than a widening of `RealtimeSession`, so the second realtime
implementation and the test fakes were not dragged into scope.

## Key Decisions Changed During Implementation

Twenty decisions arrived locked with the handoff; twenty more were taken during
implementation and recorded in `docs/01-decision-log.md`. The ones that changed
the shape of the result:

- **21/22** - Gemini Live stays on the legacy path, and the semantic output
  controls go into a new port instead of widening `RealtimeSession`. Reaching
  parity would have roughly doubled four tasks for a surface that is not the
  target of this architecture.
- **23** - the strong agent is no longer "Claude" but a Claude/Codex selector
  behind one Control Center route, so the `BrainBackend` adapter is
  agent-agnostic and `aiohttp` stays out of Core.
- **24** - deduplication is on `correlation_id`; the provider item id is an
  optional secondary key, because provider ids are almost absent from normalized
  realtime events today.
- **28** - `BrainBackend` is injected as a parameter with a null default defined
  inside Core, rather than extending the architecture gate's exception list.
- **34** - the decision with the largest user-visible consequence. In continuous
  mode the surface receives an **empty** Core tool catalogue, not merely a
  narrower one. A completed turn is already on its way to the brain while the
  surface still holds `drive_delete` and `calendar_invite`; prompt wording cannot
  prevent a double execution, only the absence of the tool can. The cost is that
  continuous mode now depends on the brain having equivalent access, which is the
  blocking gate below.
- **35/36** - work is removed only by an explicit, named brain decision
  (`superseded` keeps the work and retires the stale sentence; `cancelled` stops
  it), and a truncated sentence is persisted with its full text plus
  `delivery=partial` and `played_ms`, so the brain knows it spoke without
  claiming the user heard.
- **38, corrected by 42** - narrowed a proposal from Task 11. Its conclusions
  stand; its stated basis was wrong and is corrected here. The recovery path after
  a mute does exist, but **not** through the state handed to the backend: the port
  `BrainBackend.run_turn(turn, state, emit)` receives the public working state, and
  the only production backend threw it away - it did `del state` and sent nothing but
  `turn.text` to `/api/agent/ask`. **That gap is now closed** (Decision 45): the backend
  sends `context: {addressing, state}`, the Control Center renders the public state as a
  short brief ahead of the request, and Core's truth reaches the brain on every turn.
  Continuity is therefore no longer carried only by the local CLI agent's own session,
  resumed with `--resume <session_id>` (`jarvis/runtime/claude_local.py:181,316`):
  a result produced while the user was muted is in that agent's memory, and the
  user gets it by asking on the next turn. The real defect fixed was that a cold
  Core started the first turn from an empty state (`brain_service.py:_ensure_state`),
  which stands regardless of what today's backend does with the state. Feeding the
  realtime surface the public working state was **refused**: handing results to a
  surface forbidden from stating them would rebuild the hazard Decision 34 removed.
- **39** - the rollout gate is a list in code, not a sentence in a document.
- **40** - the pre-existing local trace keeps its truncated text. Stripping it to
  satisfy a privacy sentence would have broken the debug console the user built.

## Files / Modules Added or Changed

Added by this handoff:

- `jarvis/core/brain_service.py` - `BrainOrchestrator`, turns, public state,
  revisions, work links, cold-state derivation.
- `jarvis/core/latency.py` - `LatencyTracker` and the six measure names.
- `jarvis/runtime/speech_scheduler.py` - the Voice-side consumer of brain speech.
- `jarvis/adapters/control_center_brain.py` - the `BrainBackend` HTTP adapter.

Changed by this handoff:

- `jarvis/domain/v2.py`, `jarvis/ports/v2.py` - brain/speech/work contracts,
  intent revision, speech delivery, playback cursor, and a wire-form fix in
  `jsonable()`.
- `jarvis/core/v2_app.py`, `jarvis/core/v2_services.py` - backend injection,
  diagnostics sink on the bus, `cancel_work()`, progress channel.
- `jarvis/protocol/server.py`, `jarvis/protocol/client.py` - the
  `brain-turns` ingress and its client method.
- `jarvis/adapters/openai_realtime.py` - provider ids, transcript deltas,
  faithful `speak()`, semantic cancel/truncate, the continuous rule set.
- `jarvis/runtime/voice_v2.py` - the continuous lifecycle and its refusals.
- `jarvis/runtime/realtime_audio.py` - playback cursor accounting, barge-in
  sequence, brain-turn submission, surface latency marks.
- `jarvis/runtime/realtime_tools.py` - `tools_for(continuous_brain=...)`.
- `jarvis/v2_config.py` - `VoiceArchitecture`, `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS`,
  `default_voice_arch()`.
- `jarvis/app.py` - composition of both paths, and the loud refusals.
- `tests/unit/test_v2_architecture.py` - the widened Core import gate.

Tests added: `test_v2_brain_contracts`, `test_v2_brain_orchestrator`,
`test_v2_brain_migration`, `test_v2_wire_form`, `test_v2_event_bus`,
`test_realtime_output_control`, `test_v2_continuous_live`,
`test_surface_reflex_policy`, `test_v2_speech_scheduler`,
`test_v2_playback_cursor`, `test_v2_intent_revision`, `test_v2_barge_in`,
`test_v2_work_progress`, `test_v2_latency_telemetry`,
`tests/integration/test_v2_brain_protocol.py`,
`tests/integration/async_conversation_harness.py`,
`tests/integration/test_v2_async_conversation.py`.

Documentation updated in Task 12b: `README.md`, `docs/ARCHITECTURE.md`,
`docs/OPERATIONS.md`, `docs/SECURITY.md`, `docs/ACCEPTANCE_STATUS.md`.

The working tree also carries unrelated work that predates Task 00 (Google Drive,
Gemini Live, the Codex CLI agent, the settings workbench). It is not part of this
handoff and is not claimed here.

## Runtime Behavior

### Continuous LIVE

`response.done` no longer implies `mute()`. One ACTIVE session spans several
turns; only an explicit mute, the useful-activity timeout, or an unrecoverable
failure returns to BACKGROUND. Brain lifecycle events count as useful activity
and rearm the timeout, but the timeout still runs from the *last* brain event, so
a hung brain eventually releases the session instead of pinning it open. Ambient
noise never counts.

### Surface Reflex Boundary

The surface may autonomously produce only a short acknowledgement from a fixed
list, a hearing repair from a fixed list, or a clarification strictly about what
it heard. It is forbidden from announcing a result, a progress, a success or a
failure, and it receives an empty tool catalogue. The empty catalogue is the
first barrier; a second one was added after the independent review: in continuous
mode the bridge refuses any Core tool call outright
(`realtime_audio.py:_surface_tools_are_closed`), journals it at `error` level as
`tool.refused` with the code `surface_tool_forbidden_in_continuous`, and returns a
tool error to the provider. A tool name the model invents, replays or inherits
from a stale catalogue therefore executes nothing. Surface assistant turns are
persisted with `surface.reflex` provenance so they are never mistaken for the
brain's word. Legacy mode keeps the full catalogue and the previous rule set,
byte for byte.

### Brain Orchestration

Turns are accepted, deduplicated on `correlation_id`, persisted, and dispatched
once. The acknowledgement is returned before the backend runs. Public working
state carries intent, known public facts, asked questions and active work ids,
with a monotonic revision. The deduplication index is in memory: a Core restart
leaves a documented replay window, deliberately not closed.

### Speech Scheduling

The scheduler filters by conversation, orders by priority then FIFO, expires TTL,
honours `supersedes_key`, drops speech whose work the brain superseded or
cancelled, resubscribes after a silent stream close without replaying, and stays
silent in BACKGROUND. Its lifetime is that of the ACTIVE voice transport, not of
the work.

### Spoken Progress - mechanism delivered, producer missing

Requalified after the independent review. The *mechanism* ships and is tested end
to end: `BrainEventKind.PROGRESS` updates the public working state and publishes
`brain.work.progress`, `SpeechKind.PROGRESS` is scheduled, superseded and expired
by the scheduler, and `ProgressReportingJobWorker` is the port a job reports
through. The *producer* does not ship: no worker in `jarvis/` implements
`ProgressReportingJobWorker`, and `ControlCenterBrainBackend` emits only
`ACCEPTED`, `SPEECH`, `COMPLETED` and `FAILED` - never `PROGRESS`. So the
"fast ack, then spoken progress, then the result" sequence runs today only under
the scripted backend of `tests/integration/test_v2_async_conversation.py`. On a
real installation the user hears the acknowledgement and then the result, with
nothing in between. What is delivered is the plumbing, not the behaviour.

### Interruption / Intent Revision

Order is fixed and is the whole point: local stop into PortAudio, freeze the
playback cursor, then `cancel_output`, then `truncate`. The user stops hearing
Jarvis before any network round trip. Nothing is cancelled; the next
authoritative turn carries `interrupted_speech_id` and the brain decides. Every
authoritative turn publishes `brain.intent.revised` listing all active work in
`retained_work_ids`, so retention is observable rather than implicit.

A race found and fixed along the way: a flag released at the end of
`stop_output()` let the writer thread retake the PortAudio lock after `abort()`
and resume audio a few milliseconds after the user spoke. It was replaced by a
playback epoch, kept distinct from the accounting epoch so the block that really
played is still credited and the truncation point stays exact.

### Background / Mute

`Jarvis Mute` stops or suspends Voice and returns wake-word handling; Core jobs
continue. Nothing auto-wakes the surface to speak a result the user muted
through - that speech expires. The result stays in Core, and since Decision 45 it
also travels back to the brain: the production backend posts
`context: {addressing, state}` alongside `turn.text`
(`control_center_brain.py:_turn_context`), where `state` is
`BrainWorkingState.to_rehydration_payload()` - completed and active work ids,
known public facts, unresolved questions - and the Control Center renders it as a
short brief ahead of the request. Two things therefore carry the missed result to
the next turn: Core's public state in that brief, and the CLI agent's own resumed
session (`--resume`, `claude_local.py:181,316`). What was the residual gap of
Decision 42 is closed; what remains is prompt-level, since a model may ignore a
brief.

## Configuration and Rollback

`JARVIS_VOICE_ARCH` selects the path: `legacy` or `continuous_brain`. It lives in
`jarvis/v2_config.py`, not in the Control Center settings file, because it is a
deployment switch and must be reversible with one line of `.env` and a restart.

The default is computed, not hard-coded. `default_voice_arch()` returns `legacy`
while `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` is non-empty, and `parse_voice_arch()`
is its only consumer - so **removing the variable is the rollback**, mechanically.
A test pins both directions.

Continuous mode fails loudly rather than degrading: it refuses manual turn mode
at construction, refuses the Gemini stack at composition, and refuses any session
that does not advertise output control, logging `voice.arch_unsupported` and
returning to BACKGROUND.

**Blocking rollout gate (Decision 34).** The blocker tuple currently holds
`brain_calendar_access_unverified` and `brain_reminder_access_unverified`. In
continuous mode the surface can no longer create a calendar event or a reminder,
and the brain's own access to them is **not verified**. Only Drive is reachable
by the brain, and only if the operator registered `python -m jarvis drive-mcp` in
the CLI agent's own MCP configuration - Jarvis does not register it. Emptying the
tuple is the deliberate act that flips the default, and it requires either wiring
the missing access or accepting the gap in writing.

## Tests Run

Executed in Task 12b on the Windows workstation, with
`./.venv/Scripts/python.exe`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 706 passed, 4 skipped, 0 failed
.\.venv\Scripts\python.exe scripts\verify_release.py   # Release verification passed.
```

### Unit

Contracts, orchestrator, migration exclusivity, wire form, event bus eviction,
output control, continuous lifecycle, surface reflex policy, speech scheduler,
playback cursor, intent revision, barge-in, work progress, latency telemetry and
the rollout gate. The architecture gate that keeps provider types out of Core was
widened before any backend was injected, and an anti-loosening test keeps its
exception list frozen.

### Integration

`tests/integration/test_v2_async_conversation.py` runs six scenarios on the real
stack - local HTTP protocol, `/v1/events`, orchestrator, scheduler, voice runtime,
conversation bridge - doubling only the provider session, PortAudio and the strong
backend: long task with a fast ack then spoken progress then the result (that
spoken progress comes from the scripted backend - see *Spoken Progress* above);
interruption with intent revision; `Jarvis Mute` with work surviving in Core;
ambient noise not keeping the session alive; event-stream disconnect without
replay; several turns in one session. Plus guards on Decision 34 and on duplicate
speech. The three concurrency scenarios are each replayed three times.

### Live Provider

**NOT VERIFIED.** `tests/integration/test_live_openai.py` was extended to the
continuous path - realtime session, empty catalogue, `speak()`, first audio,
`cancel_output` - but it is opt-in, it is skipped by default, and it was **not
run**. Its status is "not executed", never "passed". Nothing in this handoff ever
talked to the real OpenAI Realtime service.

### Workstation / Hardware

**NOT VERIFIED.** No hardware recipe was run at any point: no microphone, no
speakers, no headphones, no echo measurement, no VAD-retrigger measurement, no
audibly interrupted sentence. The milliseconds the telemetry can record have
never been compared with what an ear hears.

Be exact about what the automated barge-in tests prove: the ordering local stop →
`cancel_output` → `truncate`, and that history does not claim the user heard what
was truncated. They do **not** prove that the sound stops in the speakers, nor how
fast. In the harness, `abort()` is called on a double and the cursor is byte
accounting.

The checklist for this gate is in `docs/ACCEPTANCE_STATUS.md`.

## Latency / Diagnostics Observations

Six measures, defined once in `jarvis/core/latency.py`, emitted through
`DiagnosticSink` / `RuntimeJournal` into `runtime/trace.jsonl` and therefore
visible in the Control Center **TRC** panel. Each event carries `measure` and
`elapsed_ms` in `data`, so a single filter finds all six.

| Measure | Event kind | Join key | Process |
| --- | --- | --- | --- |
| `speech_started -> surface_first_audio` | `voice.latency.surface_first_audio` | `segment_id` | Voice |
| `transcript_completed -> brain_turn_accepted` | `voice.latency.brain_turn_accepted` | `correlation_id` | Voice |
| `brain_speech_requested -> first_brain_audio` | `voice.latency.first_brain_audio` | `speech_id` | Voice |
| `user_interrupt_detected -> local_output_stopped` | `voice.barge_in` (`stop_latency_ms`) | `speech_id` | Voice |
| `brain_work_started -> first_public_progress` | `core.brain.latency.first_public_progress` | `work_id` | Core |
| `brain_work_started -> completed` | `core.brain.latency.work_completed` | `work_id` | Core |

Both bounds of a measure are taken in the same process on a monotonic clock, so
no measure silently includes the Core↔Voice transport. The last one is not
emitted for failed or cancelled work: a failure is not a duration. No numbers are
reported here, because no run produced any - the instrument exists, it has not
been read.

## Security and Privacy Checks

- The Core import gate was widened (aiohttp, openai, adapter and runtime
  packages) before any brain backend was injected, and its exception list is
  frozen by a test.
- The realtime surface holds no tools in continuous mode, which is the strongest
  privacy and safety property added by this handoff: no irreversible external
  action can originate from the fast model.
- Latency telemetry is identifier-only by construction: `LatencyTracker` builds
  its own message from the measure name, so a caller cannot smuggle transcript
  content into it. Tests enforce this.
- **Raw reasoning: what the boundary actually covers (Decision 43).** No reasoning
  field exists in Core's domain state, none is persisted in conversation turns,
  none is carried by `brain.state.updated` or by any speech request, and none
  reaches the Realtime surface - only structured public working state does.
  `tests/unit/test_v2_brain_contracts.py` pins that boundary. It is *not* true
  that no raw reasoning is stored or exposed anywhere: by design, the local CLI
  agent's own reasoning is journaled and shown on this machine.
  `jarvis/runtime/claude_local.py:477` writes every raw stream-json event -
  `thinking` blocks included - into `runtime/trace.jsonl`, and
  `claude_local.py:284` renders those blocks as `[réflexion] ...` in the Control
  Center console (same for Codex, `codex_local.py:156`). That is a pre-existing
  diagnostic feature the user built to watch the agent work; Decision 43 keeps it
  and corrects the claim instead. A reader who cares can open
  `runtime/trace.jsonl` and check.
- Deliberate deviation, recorded as Decision 40: the pre-existing runtime journal
  still writes up to 300 characters of transcripts and answers into
  `runtime/trace.jsonl`, because the Control Center debug console reads it back.
  `JARVIS_LOG_CONTENT` does not gate it. This was previously described
  incorrectly in `README.md`, `docs/SECURITY.md` and `docs/OPERATIONS.md`, which
  claimed content was redacted by default; those documents were corrected in Task
  12b to describe the code as it is. The trace is local and leaves the machine
  nowhere.

## Known Limitations

- **Acoustic echo is not handled.** In continuous mode the microphone stays open
  while the speakers play. Nothing in this repository cancels echo; `legacy` is
  the half-duplex fallback and remains the default. Whether Jarvis' own voice
  retriggers the VAD is unknown.
- **The brain's calendar and reminder access is unverified**, and continuous mode
  removes those tools from the surface. This is the blocking gate.
- **No live-provider validation**: OpenAI's server VAD turn segmentation, the
  fidelity of `speak()` to the brain's text and the exact semantics of
  `conversation.item.truncate` are unvalidated against the real service.
- **Named single point of failure: the `response.metadata` round-trip.** Every
  link between a brain speech and its provider response hangs on one assumption
  that has never been observed against the real service. `speak()` puts the local
  `output_id` and the `speech_id` into `response.metadata`
  (`jarvis/adapters/openai_realtime.py:455-467`), and `_bind_response()`
  (`jarvis/adapters/openai_realtime.py:235`) correlates by that metadata **and by
  nothing else**: a `response.created` that does not echo `metadata` back gets a
  fresh local output with `speech_id=None`, silently. Open question 9 in
  `docs/handoff-realtime-brain/docs/07-open-questions.md` opened this on the
  strength of secondary sources - the field set of `response.created` could not be
  read from the API reference. What it costs if the assumption is wrong, in order:
  1. `realtime.output_started` carries `speech_id: null`, so the conversation
     bridge takes the *else* branch of
     `jarvis/runtime/realtime_audio.py:1367-1395` and persists the sentence as a
     surface reflex, `provenance=surface.reflex`;
  2. the speech scheduler persists the very same sentence in parallel, with
     `provenance=brain.speech` (`jarvis/runtime/speech_scheduler.py:715`) -
     the double persistence, one copy under a false provenance, that spec
     section 15 exists to prevent;
  3. barge-in loses its target: `cancel_output()` falls back to the active
     output, and the truncation point is no longer attributable.
  No fallback correlation is invented here on purpose: without the real provider
  nobody can say which one would be right, and a guessed one would mask the
  failure instead of exposing it. **First check of the first live session**: in
  `runtime/trace.jsonl`, a `voice.output_started` event for a brain speech must
  carry a non-null `speech_id`. It is the first item of the workstation checklist
  in `docs/ACCEPTANCE_STATUS.md`.
- Gemini Live cannot run continuous mode.
- Deduplication is in memory, so a Core restart leaves a replay window.
- `/v1/events` is live-only; a consumer that missed events expires stale speech
  and rehydrates instead of replaying.
- Jobs still publish `job.completed`/`job.failed` rather than
  `brain.work.completed/failed`, and a job-sourced progress event does not update
  `BrainWorkingState`.
- **Core context now reaches the brain, but only as a prompt (Decisions 42 and 45).**
  The gap recorded by Decision 42 - `ControlCenterBrainBackend` conveying no public
  working state, no known facts and no work list - is closed: the backend sends
  `context: {addressing, state}` built from `BrainWorkingState.to_rehydration_payload()`
  (`jarvis/adapters/control_center_brain.py:_turn_context`), and the Control Center
  renders a whitelisted brief - current intent, goal, active work, known public facts,
  unresolved questions - ahead of the request. A brain whose CLI session is lost or taken
  over by the debug console no longer starts blind. What remains is a real limit: the
  brief is a prompt, so a model may ignore it, and what the agent does with an
  `uncertain` turn is a prompt-level guarantee, not a mechanical one.
- **Spoken progress has no production producer.** The mechanism is delivered and
  tested; nothing in `jarvis/` emits `BrainEventKind.PROGRESS` or implements
  `ProgressReportingJobWorker`. See *Spoken Progress* above.
- The public working state has no read-only `/v1` route. This was a deliberate
  refusal, not an omission: `brain.state.updated` already streams the payload.
- The bounded event bus still evicts a saturated subscriber; eviction is now
  observable and the consumer reconnects, but the eviction itself remains.

## Deferred Work

- **Multi-agent orchestration.** Explicitly out of scope from Decision 03 and
  never started. The contracts carry correlation and work identifiers, and
  `brain.intent.revised` already partitions work into superseded / cancelled /
  retained, so the seams for several agents exist - but there is no agent pool, no
  scheduler, no ownership or merge policy, and nothing in this codebase should be
  read as a partial implementation of one. It is the natural next architecture
  step once the single brain has passed a hardware recipe.
- WebRTC plus a sideband control transport, replacing the direct WebSocket. The
  adapter contracts were kept transport-neutral enough for it.
- Acoustic echo cancellation. Not implemented in any form.
- Gemini Live adopting the output-control port.
- Restart-persistent deduplication, and a durable event log, if replay across a
  Core restart ever proves necessary.
- A configuration switch to redact journal message bodies - a product decision
  about the debug console, not a migration decision.

## Release Recommendation

**Ship the code, keep `legacy` as the default, do not flip the switch.**

The automated evidence is complete for what automation can prove, and the
rollback path is one environment variable and a restart. What is missing is not
code; it is three unrun gates. Until a workstation recipe says that Jarvis'
speakers do not retrigger its own microphone, and until the brain can create a
calendar event and a reminder, `continuous_brain` is an opt-in mode for the
developer of this repository, not a default for anyone.

The blocker tuple in `jarvis/v2_config.py` enforces exactly that, and emptying it
should stay a deliberate act with a written justification.

## Exact Next Steps

1. Run the `continuous_brain` workstation checklist in
   `docs/ACCEPTANCE_STATUS.md`, on the target Windows machine, with headphones
   first and then normal speakers. Its first item is the `response.metadata`
   round-trip - a brain speech must produce a `voice.output_started` carrying a
   non-null `speech_id`; if it does not, stop there, because nothing measured
   afterwards is trustworthy. Then record whether the speakers retrigger the VAD.
   If they do, keep `legacy` and say so in writing rather than masking it.
2. Run the opt-in live smoke test:
   `JARVIS_LIVE_OPENAI=1 OPENAI_API_KEY=... python -m pytest -q tests/integration/test_live_openai.py`.
3. Wire the brain's calendar and reminder access - the most direct route being an
   MCP surface for the Core tools, mirroring what `python -m jarvis drive-mcp`
   already does for Drive - or accept the gap in writing as Decision 34 allows.
4. Only then remove the corresponding entries from
   `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS`, and let the test that pins both directions
   confirm the default flipped for the reason intended.
5. Compare the recorded `elapsed_ms` values against what the ear hears,
   particularly `voice.barge_in`. The instrument has never been read against
   reality.
