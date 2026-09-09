# Jarvis Realtime + Async Brain - Implementation TODO

## Orchestration mode

A fresh implementation agent must start with Task 00 and remain in orchestration mode for this handoff. Do not jump directly to a coding slice.

Before every coding task:

1. load `/caveman`;
2. load `/coding-guideline`;
3. inspect the current repository state rather than assuming this snapshot is still exact;
4. run the narrow pre-change tests for the layer being modified;
5. make one focused architectural change;
6. run the specified tests and relevant regression gates;
7. update this TODO/status and any raw task plan if discoveries require a safer split;
8. only then move to the next task.

Skills are expected under `~/ai/skills/`.

## Locked project intent

- Realtime is the fast mouth/ears/reflex surface.
- Core owns the asynchronous brain, truth, intent, work state, and task orchestration.
- A completed Realtime response does not end continuous LIVE mode.
- `Jarvis Mute` stops/suspends Voice, not Core work.
- Ambient noise never counts as useful activity.
- User interruption stops speech quickly but does not auto-cancel work.
- No raw chain-of-thought is stored or exposed.
- Single brain/orchestrator now; multi-agent later.
- Keep ports/adapters and provider-neutral Core boundaries.

## Snapshot verification result (Task 00, 2026-09-09)

Verified against the working tree, not HEAD: 22 modified files and 14 untracked
files exist on top of `062f835`. All twelve snapshot files still exist and the
twelve behavioural claims hold, with four material divergences:

1. A second `RealtimeSession` implementation exists (`jarvis/adapters/gemini_live.py`)
   plus a voice stack registry (`jarvis/runtime/voice_stack.py`) that, not
   `v2_config.py`, now decides model/voice/turn mode/VAD. -> Decisions 21, 22.
2. The strong agent is no longer "Claude" but a Claude/Codex selector behind
   `POST /api/agent/ask` in the Control Center. -> Decision 23.
3. Provider item ids are almost absent from normalized Realtime events, so
   deduplication by provider item id is not yet possible. -> Decision 24.
4. No playback cursor exists, so Task 09's truncate-to-played requirement needs
   preparatory work. -> plan adjustment at the end of the decision log.

Two latent hazards were also recorded: `CoreEventBus` silently evicts saturated
subscribers (Decision 25), and the architecture gate is too narrow to protect Core
once a brain backend is injected (Decision 26).

## Source snapshot to verify before edits

The handoff was built from these inspected files on `main`:

- `jarvis/runtime/voice_v2.py` - response completion currently calls `mute()`.
- `jarvis/runtime/realtime_audio.py` - blocking `claude_task`, closes mic after auto-turn commit.
- `jarvis/adapters/openai_realtime.py` - direct WebSocket, completed transcript only, current `send_context()` behavior.
- `jarvis/runtime/claude_gateway.py` - final-response HTTP call to Control Center.
- `jarvis/domain/v2.py` - conversations/jobs/protocol envelope/lifecycle.
- `jarvis/ports/v2.py` - provider-neutral ports.
- `jarvis/core/v2_services.py` - CoreEventBus, ConversationService, JobService.
- `jarvis/core/v2_app.py` - Core composition root.
- `jarvis/protocol/server.py` - loopback API and `/v1/events` WebSocket.
- `jarvis/protocol/client.py` - local API client/event consumer.
- `jarvis/v2_config.py` - Realtime model/voice/turn config.
- `tests/unit/test_v2_voice_toggle.py` - current one-response-to-background assertions.

If these files have materially changed, update the plan before coding. Do not force stale line-level assumptions.

## Task order

- [x] Task 00 - Orchestrate the handoff
  - Path: `tasks/00-orchestrate-handoff/TASK.md`
  - Depends on: none
  - Status: DONE 2026-09-09. Snapshot verified against the live working tree.
    Baseline: 395 passed, 3 skipped, 0 failed (skips: opt-in live OpenAI test,
    POSIX-only signals, symlinks unavailable). Divergences resolved as
    Decisions 21-27 in `docs/01-decision-log.md`.
- [x] Task 01 - Add typed brain and speech contracts
  - Path: `tasks/01-brain-speech-contracts/TASK.md`
  - Depends on: Task 00
  - Status: DONE. Contracts added in domain/ports. RealtimeSession left untouched per
    Decision 22; output control lives in the separate `RealtimeOutputControl` port
    with a `supports_output_control()` capability probe. Suite: 435 passed.
- [x] Task 02 - Add Core-owned BrainOrchestrator skeleton
  - Path: `tasks/02-core-brain-orchestrator/TASK.md`
  - Depends on: Task 01
  - Status: DONE. `jarvis/core/brain_service.py` owns turns, state revisions and async
    backend tasks; `NullBrainBackend` is the headless default. Also fixed a wire-form
    divergence in `jsonable()` (incl. the `asdict()` nesting defect) and wired the
    bus diagnostics sink. Suite: 475 passed.
- [x] Task 03 - Add authoritative brain-turn protocol ingress
  - Path: `tasks/03-brain-turn-protocol/TASK.md`
  - Depends on: Task 02
  - Status: DONE. `POST /v1/conversations/{id}/brain-turns` + `submit_brain_turn()`.
    202 new / 200 duplicate / 404 / 503. Crash window documented per Decision 29.
    Suite: 490 passed.
- [x] Task 04 - Extend Realtime event and output-control adapter
  - Path: `tasks/04-realtime-controls/TASK.md`
  - Depends on: Task 01
  - Status: DONE. Provider ids exposed, transcript deltas mapped, faithful `speak()` with
    no fake user turn, semantic cancel/truncate. Gemini untouched per Decision 21.
    Suite: 458 passed at the time. See open questions 9 and 10.
- [x] Task 05 - Introduce continuous LIVE lifecycle
  - Path: `tasks/05-continuous-live/TASK.md`
  - Depends on: Task 04
  - Status: DONE. `JARVIS_VOICE_ARCH=legacy|continuous_brain`, default legacy. Mic capture
    now spans the session; `SoundDeviceRealtimeAudio` byte-identical, PortAudio
    invariants untouched. Continuous mode refuses manual turn mode and any stack
    without output control. Suite: 506 passed.
- [x] Task 06 - Enforce strict Realtime reflex policy
  - Path: `tasks/06-surface-reflex-policy/TASK.md`
  - Depends on: Task 04, Task 05
  - Status: DONE. Continuous prompt forbids result/progress/success/failure claims;
    the continuous surface receives an **empty** Core tool catalogue (Decision 34);
    surface assistant turns are persisted with `surface.reflex` provenance; the
    surface model stays a setting. Gemini keeps the legacy rule set (Decision 21).
    Suite at the time: 593 passed.
- [x] Task 07 - Move Claude/strong brain ownership into Core
  - Path: `tasks/07-migrate-claude-brain/TASK.md`
  - Depends on: Task 02, Task 03, Task 05
  - Status: DONE. `ControlCenterBrainBackend` (agent-agnostic, Decision 23) is built in
    `app.py` and injected into Core; Core still defaults to the null backend and
    imports no adapter. In continuous mode the bridge never waits on Claude and
    `append_turn(kind="user")` raises (Decision 30, mechanical exclusivity).
    `claude_gateway.py` stays for the legacy path only.
- [x] Task 08 - Add Voice SpeechScheduler for brain output
  - Path: `tasks/08-speech-scheduler/TASK.md`
  - Depends on: Task 03, Task 04, Task 07
  - Status: DONE. `jarvis/runtime/speech_scheduler.py` consumes `/v1/events`, filters by
    conversation, orders by priority then FIFO, expires TTL, honours `supersedes_key`,
    resubscribes after a silent close without replaying (Decision 31), stays silent in
    BACKGROUND (Decision 33) and persists spoken text with `brain.speech` provenance.
- [x] Task 09 - Implement barge-in and intent revision
  - Path: `tasks/09-barge-in-intent-revision/TASK.md`
  - Depends on: Task 05, Task 08
  - Status: DONE. Suite: 650 passed, 3 skipped, rerun by the orchestrator.
    Acceptance criteria 2 and 3 are proven by automated tests; criterion 1 is proven
    only up to the local stop / cancel / truncate ordering - that the sound actually
    stops in the speakers, and how fast, is a workstation gate (Task 12).
    Was IN PROGRESS below. Only the Task 04/08 prerequisites exist (`PlaybackCursor`,
    `cancel_output`/`truncate`, `interrupted_speech_id` in the contract, stale-speech
    drop on revision gap). Nothing of the barge-in sequence is wired:
    `realtime.speech_started` only emits a trace, no playback accounting exists, and
    `_submit_brain_turn()` never passes `interrupted_speech_id`.
    Split by the orchestrator per the decision-log plan adjustment:
    - 09a - playback cursor accounting in the audio output path. DONE.
      `set_active_output()` / `playback_cursor()` / `written_output_ms` /
      `played_output_ms` on `SoundDeviceRealtimeAudio`, reusing the existing
      `PlaybackCursor`. Two never-nested locks: the PortAudio critical section is
      byte-for-byte unchanged, counters live under a separate lock and a block is
      credited only after `write()` returns, so an aborted block is never counted.
      Verified by the orchestrator by reading the code, not only the report.
    - 09b - intent revision semantics + scheduler invalidation (Core side). DONE.
      `BrainIntentRevision`, `BrainEventKind.SUPERSEDED`/`.CANCELLED` (both require a
      `work_id`), `WorkCanceller` port, `JobService.cancel_work()`, and
      `brain.intent.revised` published on every authoritative turn with all active work
      in `retained_work_ids`. Nothing is ever cancelled automatically. -> Decision 35.
    - 09c - barge-in wiring (needs 09a and 09b). DONE.
      `stop_output()` aborts under `_output_lock` and restarts the stream without
      touching the input, so the microphone stays open through the barge-in. Order is
      local stop -> freeze cursor -> `cancel_output` -> `truncate`, so the user stops
      hearing Jarvis before any network round trip. `interrupted_speech_id` rides the
      next authoritative turn; truncated speech is persisted `delivery=partial` with
      `played_ms` and excluded from public facts. -> Decision 36.
      Found and fixed a real race on the way: a flag released at the end of
      `stop_output()` let the writer thread retake the lock after `abort()` and resume
      audio; replaced by a playback epoch distinct from the accounting epoch.
- [x] Task 10 - Add structured work progress and public brain state
  - Path: `tasks/10-progress-working-state/TASK.md`
  - Depends on: Task 07, Task 08
  - Status: DONE (landed before Task 09; dependencies 07/08 were satisfied).
    `JobProgressSink` + optional `ProgressReportingJobWorker` capability, coalesced and
    throttled progress channel, `brain.work.*` events and public `BrainWorkingState`
    revisions. Workers never decide speech (spec 13). Known nuances: jobs still publish
    `job.completed`/`job.failed` rather than `brain.work.completed/failed`, and a
    job-sourced progress event does not update `BrainWorkingState`. Suite: 594 passed.
- [x] Task 11 - Add end-to-end async conversation scenarios
  - Path: `tasks/11-integration-scenarios/TASK.md`
  - Depends on: Tasks 05-10
  - Status: DONE. `tests/integration/async_conversation_harness.py` +
    `test_v2_async_conversation.py` cover the six scenarios with fakes only: long task
    with fast ack then spoken progress then result, barge-in with intent revision,
    `Jarvis Mute` with work surviving in Core, ambient noise not counting as activity,
    event-stream disconnect without replay, and several turns in one session.
    No production file was changed: the task escalated its finding instead of hiding it
    in the test slice, as its handoff notes require. Suite: 665 passed, 3 skipped.
    -> raised Decision 37, ruled on by the orchestrator as Decision 38.
- [x] Task 12 - Add telemetry, rollout gates, and repository docs
  - Path: `tasks/12-rollout-docs/TASK.md`
  - Depends on: Task 11
  - Status: split by the orchestrator into 12a (code) and 12b (documentation).
    - 12a - latency telemetry + rollout gates. DONE. `jarvis/core/latency.py` carries the
      six measures of `docs/04-testing-and-quality.md`, each joinable by
      `correlation_id` / `speech_id` / `work_id` and id-only by construction. The
      Decision 34 gate became `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` in `v2_config.py`:
      the default stays `legacy` while the tuple is non-empty, and a test pins both
      directions. The opt-in live smoke test was extended to the continuous path and
      stays skipped by default. -> Decisions 39 (ratified) and 40.
      Suite: 686 passed, 4 skipped; `verify_release.py` passed.
    - 12b - repository documentation + final implementation report. DONE.
      `README.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/SECURITY.md` and
      `docs/ACCEPTANCE_STATUS.md` now describe the code that exists, and
      `docs/handoff-realtime-brain/FINAL-REPORT.md` covers tasks 00-12.
      It found that three repository documents claimed transcript redaction as a
      security default that the v0.2 journal does not implement; the documents were
      corrected, the code was not (Decisions 40 and 41).
      Hardware acceptance, live OpenAI and the brain's calendar/reminder access are
      marked UNVERIFIED, not assumed. Suite: 686 passed, 4 skipped.

## Orchestrator notes (2026-09-09, resumed session)

- The mandated skills live under the user's `.codex/skills/` directory, not
  `~/ai/skills/` (see Decision 27). `caveman` and `coding-guideline` both exist there.
- Task 10 landed before Task 09; the numbering is not the execution order.
- `tests/unit/test_v2_work_progress.py` asserted `isinstance(LegacyWorker(), JobWorker)`,
  which Python 3.14 rejects because `JobWorker` is not `@runtime_checkable`. The
  assertion was removed rather than widening the port: the repository reserves
  `@runtime_checkable` for optional capabilities probed at runtime, and `JobService`
  never `isinstance`-checks the ordinary port.

## Post-review corrections (2026-09-09, after the independent critique)

All thirteen tasks were complete and green when a critique agent judged the result in a
fresh context against the human's original intent. Verdict: "yes, with reservations",
and two reservations landed on the non-negotiable boundary itself. Every finding was
re-verified by the orchestrator against the code before being acted on.

- **Uncertain turns were dropped silently** while the surface answered anyway and was
  allowed to say it was taking care of it. Most real requests classify as `UNCERTAIN`.
  The user chose, among four options, to route them to the brain. -> Decision 44, done.
- **Decision 38's stated basis was wrong**: the only production backend did `del state`.
  The conclusion survived for another reason; the reasoning was corrected in writing
  rather than quietly. -> Decision 42.
- **The chain-of-thought claim was false at system level**: the local agent's raw
  `thinking` blocks reach `runtime/trace.jsonl` and the debug console. The claim was
  scoped to what the code guarantees; the feature was kept. -> Decision 43.
- **A second Decision 34 barrier was missing**: any tool name other than `claude_task`
  reached `core.call_tool` unguarded in continuous mode. Now refused loudly, and a test
  exercises a tool that is not `claude_task`.
- **Core's truth never reached the brain.** The backend now sends `context:
  {addressing, state}`, which is what makes Decision 44's safeguard real. -> Decision 45.
- Two tests whose names promised more than their assertions were tightened, and three
  documents that overclaimed were corrected.

Suite after the corrections: **706 passed, 4 skipped, 0 failed**; `verify_release.py`
passed. The blocking gate of Decision 34 is untouched: `legacy` remains the default.

## How to select the next task

Pick the lowest-numbered unchecked task whose dependencies are complete. If implementation discovery makes a task unsafe or too broad, Task 00 authorizes the orchestrator to split/reorder tasks and update this TODO, provided the locked decisions remain intact or an explicit decision change is documented.

## Global testing expectations

- Use fakes for Core/brain/provider unit tests.
- Never require real OpenAI or Claude for the default test suite.
- Preserve/strengthen Core provider-neutral architecture gates.
- Add concurrency tests for mute, interruption, stale speech, and brain completion after Voice disconnect.
- Run relevant existing voice tests whenever Voice/Reatime code changes.
- Do not declare hardware acoustic behavior solved without workstation testing.

## Reporting

At the end of every coding task, record:

- files changed;
- behavior changed;
- tests run and result;
- architectural decisions changed/added;
- remaining risks;
- exact next task.

Use `templates/final-implementation-report-template.md` after Task 12.
