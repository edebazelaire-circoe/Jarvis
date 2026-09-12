# Implementation TODO — JARVIS Solo Owner + Core Work State

## How to use this folder

Start with **Task 00**. The implementing agent must work in orchestration mode, update this TODO as work progresses, and verify each task before moving on.

For every coding task, load and follow:

- `/caveman`
- `/coding-guideline`

from `~/ai/skills/`.

## Global rules

- Baseline is `main` around commit `8fc7a117791f39eba70362cb2acd56ecbc8e44fa`; refresh current `main` before edits and record any drift.
- Do not rewrite working AEC/concurrency code unless a task explicitly requires it.
- Keep `continuous_brain` surface tool-free.
- Keep Core authoritative for long work and intent.
- Add typed ports/results before vendor-specific behavior.
- Do not log raw audio or speaker embeddings.
- Every behavior change requires regression tests.
- Prefer shadow mode and feature flags before enforcement.
- If current code already implements a requested behavior equivalently, update the plan rather than duplicating it.
- If a task reveals a missing prerequisite, add/reorder a task here and document why.
- Do not move to the next task while acceptance criteria for the current one are red.

## Task order

- [x] 00 — Orchestrate the implementation
- [x] 01 — Freeze Solo Owner contracts and configuration
- [x] 02 — Add SpeakerVerifier port, fake, and shadow telemetry
- [x] 03 — Add owner profile lifecycle and first local verifier adapter
- [x] 04 — Integrate rolling owner verification into duplex capture
- [x] 05 — Make owner confirmation authoritative for Solo Owner barge-in
- [x] 06 — Add longer owner-verification ring buffer and provider-advisory flow
- [x] 07 — Gate active input and useful activity by owner identity
- [x] 08 — Expose Solo Owner quality/degraded settings in Control Center
- [x] 09 — Build repeatable speaker-engine benchmark harness
- [x] 10 — Define normalized Core work-state contracts
- [x] 11 — Add Core WorkStateStore and provider observation ingress
- [x] 12 — Feed current work state to the brain and event policy
- [x] 13 — Migrate task UI projection to Core-owned state
- [x] 14 — Run hardware acceptance, benchmark, select defaults, and document rollout (automatable part done; physical workstation protocol PENDING USER)

## Reporting

After each task:

1. mark status here;
2. note commit SHA or changed files;
3. record tests executed and results;
4. record any plan change;
5. leave concise handoff notes for the next task.

At the end, fill `templates/final-implementation-report-template.md` and store the report in the repository docs/fixes or handoff completion location consistent with project conventions.

## Task 00 — Orchestration record (2026-09-11)

### Repository drift since baseline `8fc7a11`

- `HEAD` = `e292784` (« chore: sauvegarde avant refresh »), one commit after the baseline:
  - `openai_realtime.py`: stricter `VERBATIM_SPEECH_INSTRUCTION`; truncate `audio_end_ms` clamped to the audio actually received per item (`item_audio_ms`).
  - `realtime_audio.py`: playback cursor counted from the start of the *current* audio item (`_item_offset_bytes`) when one response carries several items.
  - tests in `test_realtime_output_control.py` / `test_voice_duplex.py`; report `docs/fixes/voice-duplex/resolution-report.md`.
  - Impact on this plan: none on prerequisites. Barge-in/truncate accounting must be reused as-is by Task 05.
- Uncommitted user changes present before this handoff started (NOT part of this work, must be preserved):
  `jarvis/runtime/claude_local.py` (`--chrome` flag), `tests/unit/test_claude_debug_console.py`, untracked `docs/reviews/`.
- Required skills `/caveman` and `/coding-guideline` are **not installed** on this workstation (`~/ai/skills/` absent).
  Substitute rule applied to every coding agent: follow repository conventions (French comments/docstrings like
  surrounding code, typed frozen dataclasses, ports in `jarvis/ports`, third-party libraries only in `jarvis/adapters`
  — enforced by architecture tests), minimal diffs, terse reports.
- Environment: Windows 11, Python 3.14.6 (`.venv`), `livekit` 1.1.18, `numpy` 2.5.2, `sounddevice` 0.5.6.
- Baseline full suite on `e292784` + user changes: **886 passed, 4 skipped** (49 s).
- No commits are created by the orchestration (user did not request them); evidence = changed files + test runs.

### Execution plan

- Voice track (sequential): 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09.
- Work-state track (sequential, in parallel with voice): 10 → 11 → 12 → 13.
- File ownership while both tracks run: voice = `jarvis/audio/*`, `jarvis/runtime/realtime_audio.py`, `voice_stack.py`,
  `voice_v2.py`, `turn_filters.py`, new speaker modules; work-state = new `jarvis/core/work_state*.py`,
  `jarvis/domain/work_state.py`, `agent_tasks.py`, `brain_service.py`. Shared files (`domain/v2.py`, `ports/v2.py`,
  `v2_config.py`, `app.py`, `control_center.*`) get small additive edits only; Tasks 08 and 13 never run concurrently.
- Task 14: automated acceptance + benchmark on synthetic/redistributable fixtures; the physical workstation protocol
  (owner voice, office background speech) needs the user and is delivered as a runnable procedure, never fabricated.

### Resume after interruption (2026-09-11 16:26)

- Orchestration was interrupted by the user while Task 11 was in progress (code + tests written, not verified/reported)
  and before Task 03 started. State at resume: full suite **1194 passed, 4 skipped** (50 s).
- New drift, NOT part of this handoff (parallel "brain availability / delegation" effort, must be preserved):
  `jarvis/core/brain_service.py` (stale-reply supersession, turn budget, `announce_notice`), `jarvis/runtime/claude_local.py`,
  `jarvis/adapters/control_center_brain.py`, `jarvis/app.py::_brain_availability_from_env`,
  `jarvis/core/v2_app.py::_brain_notice_loop`, `tests/unit/test_brain_delegation.py`, user folder `transcript/`.
  Impact: Task 12 edits `brain_service.py` additively only and must keep those tests green.
- Resumed with: Task 11 finish/verify (work-state track) ∥ Task 03 (voice track).

## Progress log

Each task appends its own section below (status, changed files, tests + results, plan changes, handoff notes).

### Task 01 — Freeze Solo Owner contracts and configuration — DONE

- Changed files:
  - new `jarvis/domain/speaker.py`: `ConversationMode` (`open_room` default / `solo_owner`), `SpeakerVerificationMode`
    (`off` / `shadow` / `enforce`), `DEFAULT/MIN/MAX_OWNER_BUFFER_MS` = 2500 / 500 / 5000, frozen
    `ConversationAuthorization` (coherent by construction), `ConversationAuthorizationError(code, message)`,
    readiness contract `VerifierAvailability` + `AuthorizationStatus` (`ready`/`degraded`/`refused`) +
    `AuthorizationAssessment` + pure `assess_authorization(authorization, verifier)`. No vendor names.
  - `jarvis/v2_config.py` (additive): settings keys `conversation_mode`, `speaker_verification`, `owner_buffer_ms`,
    `parse_conversation_authorization(mapping)`, `parse_owner_buffer_ms`, `conversation_authorization_settings`.
  - `jarvis/runtime/control_center.py` (additive): `GET /api/settings` → `voice.authorization`
    (`stored`, `effective`, choices, `owner_buffer_ms_bounds`, `verifier`, `status`, `code`, `problem`);
    `POST /api/settings` accepts `voice.authorization.{conversation_mode,speaker_verification,owner_buffer_ms}`;
    `_SPEAKER_VERIFIER_AVAILABILITY = NOT_INSTALLED` constant (honest today).
  - new `tests/unit/test_conversation_authorization.py` (51 tests); `docs/OPERATIONS.md` (new section « Mode de
    conversation : qui peut parler à JARVIS » + pointer from « Mode vocal »).
- Tests: `tests/unit/test_conversation_authorization.py` 51 passed; with `test_settings_endpoints.py` +
  `test_v2_architecture.py`: 106 passed. Full suite `tests`: **1029 passed, 4 skipped** (includes the work-state
  track's concurrent tests; 937 passed / 4 skipped before those landed).
- Contract decisions:
  - Settings live only in `control-center-settings.json` (flat keys like `voice_arch`), no env var. Absent/empty →
    `open_room` / `off` / 2500 = today's behaviour; old files parse unchanged and are not rewritten.
  - Omitted `speaker_verification` follows the mode (`enforce` in `solo_owner`, `off` otherwise); the Control Center
    stores only touched keys and an empty value removes the key, so leaving `solo_owner` never strands `enforce`.
  - Coherence (blocking, HTTP 400, nothing written): unknown values, non-integer / out-of-bounds buffer,
    `solo_owner`+`off|shadow` (`solo_owner_requires_enforce`), `open_room`+`enforce` (`enforce_requires_solo_owner`).
    The measurement path is `open_room`+`shadow`.
  - Readiness (non-blocking, reported): `open_room`+`shadow` without verifier → `degraded`
    (`speaker_verification_unavailable`, routing unchanged); `solo_owner` without usable verifier/profile →
    `refused` (`solo_owner_unavailable`) — "refuse and explain", never silent open-room fallback. A `solo_owner`
    choice is therefore persisted even though no verifier exists yet. Hand-written invalid file → `status: invalid`
    in GET without blocking unrelated saves.
  - Owner threshold / evidence window / profile path deliberately NOT added: engine-dependent, belong to Tasks 03/08.
- Deviations: no runtime behaviour change — Voice (`app._run_voice_v2`) does not read these settings yet; no visible
  Control Center control (API only), deferred to Task 08.
- Handoff notes:
  - Task 02: reuse `VerifierAvailability` for verifier status rather than a parallel enum; put
    `SpeakerVerification` next to it in `jarvis/domain/speaker.py` if a domain home is wanted.
  - Task 03: replace `_SPEAKER_VERIFIER_AVAILABILITY` in `control_center.py` with a real engine/profile probe; add
    threshold/profile path config there.
  - Task 06: read the buffer via `parse_conversation_authorization(settings).owner_buffer_ms` (bounds already enforced).
  - Task 07: at Voice start call `parse_conversation_authorization(overrides)` (recommend refusing to start on an
    invalid file, like `voice_arch`) then `assess_authorization(...)`; on `REFUSED` do not activate Solo Owner and
    trace the code/message. Open point: duplex capture exists only in `continuous_brain` — decide whether
    `solo_owner` under `legacy` is refused (extend the assessment) or supported.
  - Task 08: render `voice.authorization` (status/problem) and add the controls; the POST shape is already stable.

### Task 10 — Define normalized Core work-state contracts — DONE

- Changed files (working tree, no commit):
  - `jarvis/domain/work_state.py` (new): `WorkStatus` (+ `TERMINAL_WORK_STATUSES`, `ALLOWED_WORK_TRANSITIONS`,
    `can_transition`), `WorkLink`, `WorkObservation`, `WorkItem`, `WorkSnapshot`, pure rules `apply_observation` →
    `WorkUpdate(outcome, item, conflicts)` with `ObservationOutcome`, bounds `MAX_*`, `clip_text`.
  - `jarvis/ports/work_state.py` (new): `WorkObservationSink.observe()`, `WorkStateReader.snapshot()` (async Protocols).
  - `tests/unit/test_work_state_contracts.py` (new, 92 tests).
  - `docs/ARCHITECTURE.md`: new section « État de travail Core (contrats) » + one-line pointer in « Contracts ».
  - No edit to `domain/v2.py`, `ports/v2.py`, `brain_service.py`, `agent_tasks.py` (contract-only, zero shared-file churn).
- Tests: `tests/unit/test_work_state_contracts.py` 92 passed; `test_v2_architecture.py` + `test_surface_reflex_policy.py`
  green; full suite `tests` → **1029 passed, 4 skipped** (61 s; includes the voice track's in-progress tests).
- Design decisions:
  - Identity = `(source, external_id)`; `WorkLink(work_id, correlation_id)` stays `None` unless explicitly asserted,
    first asserted value wins, contradictions reported in `WorkUpdate.conflicts` (same for `parent_external_id`).
  - `BLOCKED` added (non-terminal, "waits for the user") per spec §4.5 / D17. `error_class` only on
    `failed|cancelled|interrupted`; terminal items have no `activity` and always an `ended_at`.
  - Ordering: per-item `observed_at` (observer clock); stale non-terminal ignored; terminal wins even if late; terminal
    never reopened (different terminal status rejected, same status may only enrich description); `running→pending`
    refused; no-op observation = `DUPLICATE`, no revision bump. Global revision +1 per changed item.
  - Validation rejects over-long/typed-wrong values (no silent truncation in the type); `from_payload` reads declared
    keys only, so raw provider JSON (`raw`, `prompt`, `subagent_type`, `tool_use_id`) never enters the domain.
- Deviations: new modules instead of editing `domain/v2.py`/`ports/v2.py` (orchestrator instruction, avoids voice-track
  conflicts). `docs/ARCHITECTURE.md` is otherwise English; the new section is French as instructed.
  Event name constants are not defined yet (documented payload only: `core.work.updated` →
  `{"revision", "item"}`) — Task 11 owns emission and the constant (in `jarvis/core/work_state*.py`).
- Handoff notes for Task 11:
  - Store = fold of `apply_observation(current, obs, revision=snapshot.revision + 1)`; bump revision only when
    `update.changed`; log `conflicts` and non-applied outcomes to `DiagnosticSink` (bounded). Prune oldest terminal
    items first to stay ≤ `MAX_WORK_ITEMS` (64).
  - Claude mapping (runtime side): `AgentTask.status` `running|pending|queued|started` → RUNNING/PENDING,
    `completed` → COMPLETED, `failed` → FAILED, `killed|stopped|cancelled` → CANCELLED, `interrupted` → INTERRUPTED,
    unknown terminal → FAILED with `error_class="unknown_status"`; `description` → `label`, `summary`, `activity`,
    `model`, `tokens`, `tool_uses`, `background` direct; `started_ms`/event time → `started_at`/`observed_at`.
    Use `clip_text` before building observations. `prompt`, trace, `subagent_type`, `last_tool`, `depth` stay runtime-only.
  - External id must be stable per tracker task: `AgentTask.id` switches from `tool_use_id` to `task_id` when
    `task_started` arrives, and `_merge` can fuse two tasks — keep one stable external id per `AgentTask`
    (e.g. first public id seen) in the adapter.
  - Jobs: link only when `JobService.submit(..., work_id=...)` got an explicit `work_id`; the synthetic
    `job:<id>` fallback is NOT a brain link (leave `WorkLink.work_id=None`).
  - `AgentTaskTracker` lives in the Control Center process, Core in another: the Claude sink is an adapter
    (queue + HTTP to Core) and must never block the stream reader.

### Task 02 — Add SpeakerVerifier port, fake, and shadow telemetry — DONE

- Changed files (working tree, no commit):
  - `jarvis/domain/speaker.py` (additive): `VerificationStatus` (`ok` / `insufficient_audio` / `no_profile` /
    `unavailable` / `error`), frozen `SpeakerVerification(status, engine, owner_score, owner_detected, evidence_ms,
    profile_id)` validated by construction, `.availability` → existing `VerifierAvailability`, `OWNER_SCORE_MIN/MAX`
    = 0.0/1.0, `MAX_SPEAKER_ID_CHARS` = 64.
  - new `jarvis/ports/speaker.py`: `SpeakerVerifier` Protocol (`engine`, `availability`, `reset()`,
    `process(pcm, sample_rate)`, `close()`); dedicated module, `ports/v2.py` untouched.
  - new `jarvis/adapters/fake_speaker_verifier.py` (`ScriptedSpeakerVerifier`: one scripted verdict per call — float
    score / `None` = insufficient / status / verdict / exception) and `jarvis/adapters/null_speaker_verifier.py`
    (`NullSpeakerVerifier`: `not_installed`, never a score).
  - new `jarvis/audio/speaker_shadow.py`: `ShadowOwnerTelemetry` (episodes + bounded diagnostics, thread-confined) and
    `SpeakerVerificationWorker` (capture-side hop assembly, bounded queue, dedicated thread).
  - `jarvis/audio/duplex.py`: `CaptureObserver` Protocol; `CaptureProcessor(observer=None)` taps each AEC-cleaned
    frame right after `_cancel_echo()`; `reset()` forwards, new `close()`; observer exception → `observer_failed`.
  - `jarvis/runtime/voice_v2.py`: `PersistentVoiceRuntime.close()` closes the duplex capture after `mute()`
    (`asyncio.to_thread`, idempotent).
  - `jarvis/app.py` (additive): `_speaker_verifier()` returns `None`; `capture_factory` builds a worker only if it
    returns a verifier → today no worker, capture unchanged.
  - Tests: new `tests/unit/test_speaker_verifier.py` (44); `tests/unit/test_voice_duplex.py` +15 (section « 1 bis »);
    `tests/unit/test_app.py` +2.
  - Docs: `docs/ARCHITECTURE.md` new section "Speaker verification (shadow)" (port contract, score semantics,
    threading, event kinds/bounds) + pointer in "Contracts"; `docs/OPERATIONS.md` Task 01 section « Mode de
    conversation » and its « Mode vocal » pointer translated to English (orchestrator request) + one sentence on the
    shadow seam.
- Tests: `test_speaker_verifier.py` 44 passed (5 consecutive runs, no flake); `test_voice_duplex.py` 80 passed;
  targeted set (`test_voice_duplex`, `test_speaker_verifier`, `test_app`, `test_v2_architecture`,
  `test_conversation_authorization`) 191 passed. Full suite `tests`: **1114 passed, 4 skipped** (includes the
  work-state track's concurrent tests; 1090 passed / 4 skipped on my first full run).
- Design decisions:
  - Score: `[0, 1]`, higher = more likely owner, adapter normalizes; decision = `owner_detected` (engine-calibrated
    threshold), never "score > 0.5". Score only when `status == ok`.
  - Threading: `process()` NEVER runs in the PortAudio callback. Callback → `observe(frame)` (append + bounded deque,
    no I/O) → worker thread calls the verifier on fixed 100 ms windows. Queue 2 s; overflow drops oldest, counts
    `dropped_ms`, resets the verifier (non-contiguous input), one `voice.owner.overrun` per session. All verifier calls
    (reset/process/close) happen on the worker thread; `engine` read once at construction.
  - Shadow identity: observer gets an immutable copy, nothing flows back; tested byte-for-byte (PCM, signals, gate,
    near-end latch per block) against a run without verifier for 3 scenarios × {owner, stranger, crashing verifier,
    raising observer}.
  - Diagnostics: `voice.owner.candidate|confirmed|rejected|unavailable|overrun` (dotted like `voice.reflex.*`),
    scalars only (score rounded to 3 decimals, `evidence_ms`, `confirm_ms`, `episode_ms`, engine, profile_id, status,
    availability, code, exception *type* name). Episode = run of `ok` windows closed by `insufficient_audio`; ≤ 2
    events/episode, `unavailable` only on state change, ≤ 30 events per stream-minute, overflow counted in
    `suppressed`. Stream time (audio ms), not wall clock → deterministic tests.
  - Failures: exception / non-`SpeakerVerification` result / failing reset → `availability = failed`, verifier not
    consulted again until the next session (`reset`); journal failure swallowed. Verifier not `ready` at session start
    → one `unavailable` (`verifier_not_ready`) per session, never consulted.
- Deviations: `app._speaker_verifier()` does not read the Task 01 `speaker_verification` setting (Task 07 owns that);
  no rolling state machine / acoustic-candidate anchoring (Task 04). The telemetry sink is called from the worker
  thread; `RuntimeJournal.emit` is a one-line append (no lock) — acceptable while no engine is wired, revisit if
  Task 03/04 emits at high rate (option: hop through `loop.call_soon_threadsafe`).
- Handoff notes:
  - Task 03: implement `SpeakerVerifier` in `jarvis/adapters/` (normalize the native score to [0,1], own the
    threshold → `owner_detected`, `engine` = "name/version"), make `app._speaker_verifier()` return it, and replace
    `_SPEAKER_VERIFIER_AVAILABILITY` in `control_center.py` with the engine's `availability`. `ScriptedSpeakerVerifier`
    stays the test double.
  - Task 04: the seam is `CaptureObserver.observe(frame)` (AEC-cleaned 10 ms frame); extend it (e.g. pass the
    near-end/far-end context) rather than adding a second tap. `ShadowOwnerTelemetry` episodes are verifier-delimited;
    re-anchor on `NearEndDetector` candidates there. Keep all verifier calls on the worker thread.
  - Task 08: read `SpeakerVerificationWorker.availability` and `.dropped_ms` (thread-safe reads).

### Task 11 — Add Core WorkStateStore and provider observation ingress — DONE

- Changed files (working tree, no commit):
  - new `jarvis/core/work_state.py`: `WorkStateStore` (in-memory fold of `apply_observation`, revision +1 per changed
    item, ≤ 64 items, oldest terminal evicted first, `capacity` refusal when all active), `store_id` per Core start,
    event `core.work.updated` → `{store_id, revision, previous_status, item}`; diagnostics
    `core.work.observation_ignored|observation_conflict|producer_restarted`.
  - `jarvis/domain/work_state.py` (additive): `WorkObservationBatch` (strict wire form, unknown key → 400).
  - `jarvis/protocol/server.py` / `client.py`: `POST /v1/work/observations`, `GET /v1/work/snapshot`.
  - `jarvis/core/v2_app.py` / `v2_services.py`: store owned by Core; `JobService` is one observer (link only on explicit
    `work_id`; `_work_error_class` falls back to `error` for non-ASCII exception names).
  - new `jarvis/runtime/work_ingress.py`: `WorkIngressForwarder` + `CoreWorkTransport` (Control Center → Core, bounded
    queue, never blocks the stream reader, full resend on new `store_id` and every 30 s idle, errors journaled once per type).
  - `jarvis/runtime/agent_tasks.py`: `subscribe()` listeners (exception isolated, journaled once), stable `work_key`
    (first public id), retired keys after `_merge`. `control_center.py` / `app.py`: forwarder wiring.
  - Docs: `docs/ARCHITECTURE.md` « Core work state » (Task 10 section rewritten in English: contracts, store, endpoints,
    event payload, diagnostics, failure isolation, lifetime/restart table); `docs/OPERATIONS.md` « Subtask state in Core ».
  - Tests: `tests/unit/test_work_state_store.py`, `tests/unit/test_work_ingress.py`,
    `tests/integration/test_work_state_protocol.py` (real HTTP, Core restart with new token → state relearned).
- Tests: targeted (store, ingress, protocol, contracts, architecture, speech scheduler) **212 passed** (orchestrator
  re-run); agent full suite **1200 passed, 4 skipped**. Timing-based files 5× without flake.
- Design decisions: `JobService` stays job executor/persistence (SQLite is job truth), store is separate and in memory;
  single event kind `core.work.updated` with `previous_status` (no `observed`/`failed` kinds — halves bus traffic);
  no producer lease (killed Control Center → its items stay `running` until it or Core restarts; documented).
  Process death: Claude stop/crash/restart → `interrupted/process_stopped`; Core restart → jobs
  `interrupted/core_restarted` + Claude state resent; Control Center restart → `interrupted/producer_restarted`.
- Deviations: ports in `jarvis/ports/work_state.py` (not `ports/v2.py`); no `claude_local.py` change needed.
- Handoff notes:
  - Task 12: inject `core.work_state` as `WorkStateReader` into a Core-side context builder (`await snapshot()` →
    immutable ≤ 64 items, active first); subscribe to `core.work.updated`; failure = status `failed|interrupted` with
    non-terminal `previous_status`; only `item.link.work_id` ties to brain work (Claude subtasks have no link today —
    never infer from label). `blocked` not produced by any observer yet.
  - Task 13: `GET /v1/work/snapshot` → `{store_id, revision, items, updated_at}`; live `core.work.updated` on
    `/v1/events`; apply event only if revision == last + 1 else re-read; new `store_id` → discard and re-read.
    `external_id` = first public id (tracker `find()` resolves both ids for the trace drill-down).

### Task 12 — Feed current work state to the brain and event policy — DONE

- Changed files (working tree, no commit):
  - new `jarvis/domain/brain_context.py`: `BrainContext` (= `BrainWorkingState` + `BrainWorkContext | None`),
    `BrainWorkContext` (`revision`, `store_id`, `generated_at`, totals, `items`, `attention`), `BrainWorkEntry`,
    `WorkAttention`, pure `needs_attention()` and `build_brain_work_context()` (bounded reduction).
  - `jarvis/ports/v2.py` (additive): optional capability `ContextAwareBrainBackend.run_turn_with_context(turn, context,
    emit)` detected by `supports_brain_context`; `BrainBackend` unchanged.
  - new `jarvis/core/brain_context.py`: `WorkAttentionPolicy` (subscribes to `core.work.updated`, keeps pending
    attention, diagnostic `core.work.attention` ≤ 20/min, optional rate-limited `wake` seam) + `BrainContextBuilder`
    (reads `WorkStateReader.snapshot()`, emits `core.brain.work_context` / `core.brain.work_context_failed`).
  - `jarvis/core/brain_service.py` (additive, parallel brain-delegation code untouched): `work_context=` + `_call_backend()`
    (capability → `BrainContext`; otherwise legacy `run_turn`, store not read).
  - `jarvis/core/v2_app.py`: policy/builder wiring on `core.work_state`, lifecycle (stopped before brain).
  - `jarvis/adapters/control_center_brain.py`: `run_turn_with_context` sends `context.work`; `run_turn` unchanged.
  - new `jarvis/runtime/work_brief.py` + `control_center.py::build_agent_brief`: whitelisted French brief of the work
    context before `[Demande]` (no ids/raw timestamps to the model).
  - tests: new `tests/unit/test_brain_work_context.py` (29), `tests/integration/test_brain_work_context_protocol.py` (1);
    `async_conversation_harness.py` / `test_v2_async_conversation.py` no longer hard-code the bus subscriber count.
  - `docs/ARCHITECTURE.md`: section « Brain work context and event policy » + pointers.
- Tests: agent full suite **1305 passed, 4 skipped** (includes Task 03's concurrent tests); orchestrator re-run of
  targeted set (brain context, delegation, async conversation, speech scheduler, architecture) **104 passed**.
  Watch item: `test_v2_speech_scheduler.py` failed 9× in two loaded full runs (148 s instead of ~60 s), green alone and
  on rerun — timing sensitivity under CPU load, to be examined before closing (not caused by work-state code).
- Design decisions: bounds 12 active (blocked first, oldest first) + 6 recent terminal + 8 attention notes, label/activity
  120 chars, summary 240, whole context ≤ 6000 JSON chars (lowest priority dropped, counted in totals).
  Policy: only an active item → `failed|interrupted|blocked` is retained (progress/completion/cancel ignored; items born
  terminal ignored so a Core-restart resend does not flood); one note per item, latest 8, consumed by the next turn.
  No proactive brain wake wired (single CLI brain session would delay the user's next turn; the Claude CLI already
  self-wakes on sub-agent end; failed jobs already notify) — seam `wake=` exists (≤ 1/60 s, tested with a fake).
  Work-state event never produces speech; cancellation stays explicit by `work_id` (tested).
- Deviations: proactive wake is a seam only; new domain module instead of `domain/v2.py`; two integration tests adjusted.
- Handoff notes:
  - Task 13: UI keeps `GET /v1/work/snapshot` + `core.work.updated`; highlights via `core.work.attention` or
    `needs_attention()`; never call `WorkAttentionPolicy.take_pending()` from the UI; `render_work_brief` is prompt text only.
  - Task 14: in `runtime/trace.jsonl`, `core.brain.work_context` revision/store_id must match `/v1/work/snapshot`; kill a
    Claude subtask → one `core.work.attention`, no speech; ask « où en sont mes tâches ? » → answer names it.

### Task 03 — Add owner profile lifecycle and first local verifier adapter — DONE

- Engine (baseline, NOT the final winner — Task 09): `sherpa-onnx==1.13.8` (+ `sherpa-onnx-core`), Apache-2.0,
  cp314 win_amd64 wheel installed in `.venv`. Model `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`
  (CAM++, 16 kHz, 192-dim), SHA-256 `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`,
  28 281 164 bytes, Apache-2.0 (ModelScope card `iic/speech_campplus_sv_zh_en_16k-common_advanced`), downloaded to
  `runtime/speaker-verification/models/` (git-ignored). Rejected: 512-dim VoxCeleb CAM++ export (no separation).
- Cost (i7-12700H, 1 ONNX thread, loaded machine): 1.5 s window embedding ≈ 90 ms p50 / 135 ms p95; non-scoring hop
  < 1 ms; ≈ 11 % of one core during speech; model SHA check + load ≈ 1.4 s once, on the worker thread.
- Changed files (working tree, no commit):
  - new `jarvis/adapters/sherpa_speaker_embedder.py` (only importer of `sherpa_onnx`, lazy; pinned model spec,
    `download_model`/`verify_model`, `engine_id()` = `sherpa-onnx/1.13.8`).
  - new `jarvis/adapters/owner_voice_profile.py` (JSON profile schema 1, atomic save, 0600 where possible,
    `OwnerProfileError(code)`, embedding excluded from `repr`/`metadata()`).
  - new `jarvis/audio/owner_verifier.py` (engine-neutral `EmbeddingSpeakerVerifier` implementing the port,
    adaptive `SpeechGate`, FFT `resample`, `enroll_embedding`; any `SpeakerEmbedder` plugs in).
  - new `jarvis/runtime/owner_voice.py` (cheap probe never loading the model, `build_owner_verifier`, CLI
    `jarvis owner-voice download-model | enroll --wav…|--mic | show | delete | score WAV`).
  - `jarvis/v2_config.py` (additive): `SpeakerVerifierSettings`, keys `owner_threshold` ]0,1] (default 0.5),
    `owner_evidence_ms` 500–4000 (default 1500), `owner_profile_path` (relative → runtime dir).
  - `jarvis/app.py`: `_speaker_verifier(overrides, runtime_root, journal)` → adapter only when verification ≠ `off` and
    usable; any failure → `voice.owner.unavailable`, duplex capture never lost; `owner-voice` subcommand.
  - `jarvis/runtime/control_center.py`: `_SPEAKER_VERIFIER_AVAILABILITY` replaced by the probe; `verifier_detail`
    (engine, model, code, message, profile metadata — never the voiceprint).
  - `pyproject.toml`: extra `speaker = [numpy, sherpa-onnx>=1.13.8,<2]`; `.gitignore`: `speaker-verification/`,
    `owner-voice-profile*.json`, `*.onnx`.
  - tests: new `tests/unit/test_owner_voice.py` (75, incl. real-engine SAPI TTS smoke test skipped when engine/model/TTS
    absent); `tests/unit/test_app.py` adjusted.
  - Docs: `docs/OPERATIONS.md` « Local speaker verifier: engine, model, enrollment »; `docs/ARCHITECTURE.md`
    « Local verifier adapter and owner profile ».
- Tests: orchestrator re-run (`test_owner_voice`, `test_app`, `test_v2_architecture`, `test_conversation_authorization`,
  `test_speaker_verifier`, `test_voice_duplex`) **266 passed, 0 skipped** (real engine smoke test ran); agent full
  suite **1305 passed, 4 skipped**. `git ls-files` contains no model/profile; `runtime/` ignored; no demo profile left
  at the default path. CLI demo on SAPI voices: Hortense enrolled (16.5 s, consistency 0.77) → 49/49 hops detected,
  mean 0.85; Zira max 0.42, Hazel max 0.32, never detected.
- Design decisions: `owner_score` = cosine clipped to [0,1]; default threshold 0.5 (card 0.33 is for full utterances;
  impostors reach ≈ 0.45 on 1–2 s windows; D07 prefers slower confirmation) — to tune on hardware. Evidence = 1500 ms
  voiced speech = sliding window, re-embedded every 500 ms of new speech, cached verdict between; 600 ms gap clears
  evidence. Enrollment ≥ 10 s voiced (20–30 s recommended), mean of unit embeddings over 3 s segments. Compatibility
  = model SHA + dim + sample rate. Probe codes: `speaker_engine_not_installed`, `speaker_model_missing`,
  `speaker_model_mismatch`, `owner_profile_missing|corrupt|incompatible`.
- Deviations: model/profile under `runtime/` (fully ignored) not `data/`; model pinned (only profile path configurable);
  no UI/POST fields for the new keys (Task 08); profile not encrypted at rest (open question 4); `enforce` also runs the
  verifier as shadow telemetry only until Tasks 05–07.
- USER ACTION (owner enrollment, cannot be done by agents): stop Voice, then
  `.\.venv\Scripts\python.exe -m jarvis owner-voice enroll --mic` and `... owner-voice show`; shadow measurement:
  `open_room` + `speaker_verification=shadow`, restart Voice (`continuous_brain`).
- Handoff notes:
  - Task 04: per 100 ms hop → `insufficient_audio` until 1500 ms voiced (`evidence_ms` = voiced so far), then `ok`
    re-scored every 500 ms; silence/noise never enter the window; 600 ms gap clears it; `reset()` clears evidence +
    gate floor and preloads the model; rate change clears evidence. Adapter knows nothing of acoustic candidates →
    anchor NearEndDetector context through the observer seam. CPU ≈ 90–135 ms per scoring hop.
  - Task 09: plug engines as `SpeakerEmbedder` (`model_id`, `dim`, `sample_rate`, `embed()`) into
    `EmbeddingSpeakerVerifier`/`build_owner_verifier(settings, embedder=…)`; `enroll_embedding`; `owner_voice.score_clip`;
    SAPI TTS fixture script `_TTS_SCRIPT` in the test.

### Task 13 — Migrate task UI projection to Core-owned state — DONE

- Changed files (working tree, no commit):
  - new `jarvis/runtime/work_view.py`: `CoreWorkView` (reads `GET /v1/work/snapshot`, 2 s timeout), pure revision rule
    `accept_snapshot(held, store_id, revision)`, "Core unavailable" payload (codes `not_configured`, `core_unreachable`,
    `core_refused`, `invalid_snapshot`).
  - `jarvis/runtime/work_ingress.py`: read-only `CoreWorkTransport.snapshot()` (re-reads token, one retry after 401).
  - `jarvis/runtime/control_center.py`: optional `work_view=`, GET-only `/api/work` → `{source:"core", core_reachable,
    store_id, revision, items, updated_at, stale, error, now_ms, agent_cli, subtasks_supported}`; `/api/agent/tasks`
    unchanged (diagnostic/compat).
  - `jarvis/runtime/agent_tasks.py`: payload carries `work_key`; `find()` resolves `work_key` as last resort.
  - `jarvis/app.py`: `CoreWorkView` wired with its own transport.
  - `jarvis/runtime/control_center.html`: cards from Core items joined to tracker diagnostics on `provider|work_key`;
    pure `acceptWork()`; statuses `pending|blocked|cancelled` + French `error_class` labels; elapsed only from
    `started_at`/`ended_at` + skew-corrected clock (`lastElapsed` removed); labels « État normalisé · Core (fait foi) » vs
    « Diagnostic fournisseur · brut, non autoritaire »; degraded banner, Codex empty state, « Autres travaux Core » (jobs).
  - tests: new `tests/unit/test_work_view.py` (32), `tests/integration/test_work_ui_projection.py` (2, real Core HTTP);
    `tests/unit/test_agent_tasks.py` key set.
  - Docs: `docs/ARCHITECTURE.md` « Task visualization in the Control Center »; `docs/OPERATIONS.md` « What the Agents
    panel shows » (degraded-state table).
- Tests: orchestrator re-run of targeted set (work view, UI projection, agent tasks, ingress, protocol, architecture,
  brain context, settings endpoints) **222 passed**. Agent full suite 1320 passed / 19 failed (all in voice files being
  edited concurrently by Task 04: `test_speaker_verifier.py`, `test_voice_duplex.py`, `test_owner_voice.py`); without
  those 3 files **1140 passed, 4 skipped**. JS parses under `node --check`.
- Design decisions: panel polls `/api/work` (no `/v1/events`), same revision guard server and page (older revision of
  same store never replaces held one → `stale: true`; new `store_id` replaces all); snapshot decoded with
  `WorkSnapshot.from_payload` and re-serialized (declared fields only). Core unreachable → no items + tracker local view
  under an explicit « Core indisponible … non autoritaire » banner. Brain card (process/PID/session) stays tracker-side.
- Deviations: closed-panel dock badge still uses tracker counts from `/api/status` (poll trigger only); merged
  duplicates shown as `cancelled/merged`; cards appear ≈ 0.5–1.5 s later (relay + poll). No repo JS test harness
  (pure functions checked in a scratch node run only).
- `/api/agent/tasks` deletion: not now — still serves brain card, prompt, `subagent_type`, trace linking, badge. Drop its
  state-source role after the Task 14 parity check (no UI/brain divergence across a session with a Core restart and a
  sub-agent kill) and moving the badge to Core counts; deleting the route needs a diagnostic-only replacement first.
- Handoff notes (Task 14 parity procedure): two background sub-agents from voice → compare panel « révision N » with
  `/v1/work/snapshot`; ask « où en sont mes tâches ? » → `core.brain.work_context` same store_id/revision (or later),
  answer names same labels/statuses/models; kill one → card interrompu/échec + one `core.work.attention`, no speech;
  open trace; stop Core → yellow banner, `/api/agent/tasks` still answers; restart → relearned ≤ 30 s, no terminé→en
  cours flip; Codex → « Aucun sous-agent suivi pour ce CLI. ».

### Task 04 — Integrate rolling owner verification into duplex capture — DONE (shadow only)

- Decision: every AEC-cleaned frame goes to the verifier in contiguous 100 ms windows (adapter energy gate drops
  silence/noise < 1 ms/window; only voiced speech costs an embedding: ≤ 18–27 % of a core worst case, ≈ 11 % measured;
  candidate-only feeding would save ~nothing, add ≥ 120 ms detector latency and lose the sentence start). While JARVIS
  is audible, frames without near-end speech are masked to digital silence (near-end keeps the next 300 ms unmasked) →
  AEC residual never enters evidence, playback alone costs no embedding. Owner state exists only inside an acoustic
  candidate (NearEndDetector latch rule 12/40 frames, 6 consecutive). Capture-thread cost ≈ 3 µs/frame.
- Changed files (working tree, no commit):
  - `jarvis/audio/duplex.py`: frozen `CaptureFrameContext` (`stream_ms`, `sample_rate`, `near_end`, `far_end`,
    `near_end_latched`, `gate_open`); `CaptureObserver.observe(frame, context)` after the echo guard;
    `CaptureProcessor.stream_ms` frame clock reset by `reset()`.
  - `jarvis/audio/speaker_shadow.py`: `OwnerStateMachine`, `OwnerStatePublisher`, candidate-anchored episodes, echo
    masking, sample-rate change handling, `owner_state` + `add_owner_listener`, event `voice.owner.listener_failed`.
  - `jarvis/domain/speaker.py`: `OwnerState`, `OwnerStateSnapshot`; `jarvis/ports/speaker.py`: `OwnerStateSource`.
  - `jarvis/runtime/voice_v2.py`: `mute()` resets the capture after the bridge task is awaited.
  - tests: `test_speaker_verifier.py` 44→56, `test_voice_duplex.py` 80→107 (identity matrix 5 scenarios × 6 verifier
    kinds), `test_owner_voice.py` call site. Docs: `docs/ARCHITECTURE.md` « Rolling owner verification (task 04) » +
    diagnostics table; `docs/OPERATIONS.md` operator paragraph.
- Tests: orchestrator re-run (duplex, speaker verifier, owner voice, app, architecture, authorization, barge-in, output
  control) **348 passed**; agent full suite **1378 passed, 4 skipped** (57 s); thread tests 5× green. Covered: long
  non-owner then owner without silence (confirmed 4100 ms, onset 2600 ms); scripted overlap; echo-only ×3 (guard, AEC
  residual, real AEC3) never owner, verifier receives zeros; keyboard clicks; 20-minute run bounded; session resets;
  rate change; byte-for-byte identical output; crashes in verifier/state machine/listener/observer leave capture intact.
- Design: states `idle` / `candidate` / `owner_confirmed` / `rejected`, no latch (switch either way inside one candidate),
  candidate closes after 600 ms without near-end. Timestamps on capture clock: `candidate_onset_ms`, `confirmed_ms`,
  `owner_onset_ms` (= onset, or `max(onset, confirmed_ms − evidence_ms)` after a non-owner verdict). Bounds: ≤ 1
  published change per window, ≤ 4 listeners, no history, ≤ 2 events/episode, ≤ 30/min.
- Deviations / known limits (for 09/14): `observe()` requires the context (Task 02 tests rewritten); observer after the
  guard; owner state not cleared when the bridge mutes itself (next activation resets); very quiet owner under loud
  conversation may miss the 12 dB floor margin; failed canceller lets echo count as near-end until bridge release;
  owner→stranger handover without silence stays `owner_confirmed` ≤ 500 ms of speech.
- Handoff notes:
  - Task 05: seam `SoundDeviceRealtimeAudio.capture.observer` (`SpeakerVerificationWorker`, `OwnerStateSource`):
    `add_owner_listener(cb)` → unsubscribe; `owner_state` readable from any thread. `cb` runs on the worker thread →
    `loop.call_soon_threadsafe(handler, snapshot)`; never flush/reset/close inside it. Drop snapshots whose
    `session`/`sequence` is not newer; barge-in edge = `OWNER_CONFIRMED` and `far_end`. Latency ≈ 1.7–2.0 s after owner
    onset (+ ≤ 500 ms after non-owner speech); scripted fake ≈ 200 ms.
  - Task 06: replay from `owner_onset_ms` (maybe a small margin earlier), acoustic start `candidate_onset_ms`, both on the
    10 ms frame clock → direct ring indices in `CaptureProcessor`; flush the ring on `session` change.

### Task 05 — Make owner confirmation authoritative for Solo Owner barge-in — DONE

- Changed files (working tree, no commit):
  - `jarvis/runtime/realtime_audio.py`: `BargeInAuthority` (`ACOUSTIC` / `OWNER`), events `voice.barge_in.authority`,
    `voice.barge_in.owner_confirmed`, `voice.barge_in.provider_advisory`; bridge args `barge_in_authority`,
    `owner_source` (`OWNER` without source / outside continuous → `ValueError`); `_barge_in(owner=…)` stays the only
    stop mechanism; helpers `_on_owner_state`, `_owner_authority`, `_interruptible_output`, `_note_owner_candidate`,
    `_note_provider_speech`, `_trace_owner_stop`; owner listener subscribed in `_consume`.
  - `jarvis/runtime/voice_v2.py`: `authorization=`; `_barge_in_policy(capture)` chooses authority per activation via
    `assess_authorization`. `jarvis/app.py`: `_conversation_authorization()` (invalid setting → `voice.authorization_invalid`).
  - `jarvis/ports/speaker.py`: `OwnerStateSource.availability`.
  - tests: new `tests/unit/test_owner_barge_in.py` (22), `tests/unit/test_app.py` +2.
  - Docs: `docs/ARCHITECTURE.md` « Barge-in authority: acoustic vs owner »; `docs/OPERATIONS.md` « Solo Owner barge-in:
    who can interrupt JARVIS » (+ rollback).
- Tests: orchestrator re-run (owner barge-in, v2 barge-in, output control, playback cursor, duplex, app, speaker
  verifier) **256 passed**; agent full suite **1402 passed, 4 skipped**; new file 5× green. Existing barge-in tests untouched.
- Design: policy decides only the trigger; stop mechanics (local stop, cursor, received-outputs blacklist, cancel +
  truncate degraded handling) unchanged. `OWNER`: near-end changes nothing audible (0.8 s acoustic timer kept so the
  echo guard still closes/learns); cut when `OWNER_CONFIRMED` + `far_end` + output still interruptible; snapshots
  marshalled with `call_soon_threadsafe`, stale/foreign session dropped; confirmation while silent stops nothing.
  Provider `speech_started` in Solo Owner never cuts (before/after/never): it only cancels the acoustic timer, logged
  `relation=awaiting_owner` or `after_owner_stop` with lag. `OWNER` only for `solo_owner`+`enforce`+`continuous_brain`+
  verifier `ready`; otherwise current behavior + one warning (`solo_owner_unavailable`,
  `solo_owner_requires_continuous_brain`); verifier failure mid-session → acoustic fallback + `owner_verifier_unavailable`.
  Owner cut never cancels Core work (next turn carries `interrupted_speech_id`, tested).
- Deviations / limits: invalid authorization setting → open room + warning (refusal is Task 07); after a verifier
  failure the next activation may run one acoustic session; owner state publishes changes only — if JARVIS starts
  speaking while the owner is already confirmed and talking, nothing cuts until the verdict changes.
- Handoff notes:
  - Task 06: replay hooks in `_on_owner_state` right after `_barge_in(owner=snapshot)` (local stop done, cancel/truncate
    sent); replay from `snapshot.owner_onset_ms` into the provider input path (`_put_input` / capture), never via
    playout; session must match the ring's; de-duplicate against the existing 400 ms pre-roll + open guard.
  - Task 07: refusal replaces the two acoustic fallbacks in `PersistentVoiceRuntime._barge_in_policy`
    (`TODO(tâche 07)`) and the one in `app._conversation_authorization`; input gate in `_handle_transcript` /
    `speech_started` path or earlier at the capture guard, keyed on `_owner_authority()` + latest owner state; decide
    whether non-owner `speech_started` may still hold the speech scheduler (`_note_user_speech(True)`).

### Task 09 — Build repeatable speaker-engine benchmark harness — DONE

- Changed files (working tree, no commit):
  - new `jarvis/audio/speaker_benchmark.py` (labelling, 100 ms replay through the `SpeakerVerifier` port, accelerated
    or real-time, metrics, sweep, EER, `BenchmarkEngine`, `EmbeddingBenchmarkEngine` reusing the production verifier);
    new `jarvis/runtime/speaker_benchmark.py` (manifest JSON/TOML schema v1 + Audacity labels, engine resolution,
    RSS/CPU/load, one process per engine, JSON/CSV/MD, CLI `models | generate-synthetic | run`); new
    `jarvis/runtime/speaker_benchmark_fixtures.py` (SAPI + OneCore TTS fixtures, runtime-generated, never committed);
    new `jarvis/adapters/sherpa_model_catalog.py` (pinned specs); `scripts/benchmark_speaker_verification.py`;
    `jarvis/adapters/sherpa_speaker_embedder.py` (uses `self.dim` / `self.sample_rate`).
  - tests: new `tests/unit/test_speaker_benchmark.py` (63, incl. real-engine e2e).
  - Docs: new `docs/SPEAKER_BENCHMARK.md`, `docs/speaker-benchmark-manifest.example.json`,
    `docs/results/speaker-benchmark/{README.md, 2026-09-11-synthetic.*, 2026-09-11-synthetic-settled.*}`;
    `docs/OPERATIONS.md` link.
- Engines (sherpa-onnx 1.13.8, SHA-256 pinned vs upstream checksum): CAM++ zh-en advanced (baseline), CAM++ zh-cn,
  CAM++ en-voxceleb, ERes2Net en-voxceleb, ERes2Net base 200k zh-cn, ERes2Net base 3dspeaker, ERes2NetV2 zh-cn
  (all Apache-2.0), WeSpeaker ResNet34 en-voxceleb (CC-BY-4.0). Eagle / SpeechBrain / Vivoka / Sensory: documented
  adapter slots only (not installable/accessible) — no results claimed.
- SYNTHETIC results (7 TTS voices, 39 scenarios, 516 s — NOT evidence for production thresholds):
  baseline EER 5.3 % strict / 1.1 % settled, FAR/FRR @0.5 = 6.6 % / 3.3 %, confirm P50/P95 1600/2330 ms, 34 ms per
  scoring hop, 3.5 % core, load 866 ms; ERes2Net en-voxceleb EER 5.6 % / 1.1 %, 88 ms/hop, 8.6 % core. Both reach zero
  false accept (settled) at threshold 0.65 with ≈ 2 % FRR. At 0.5 the baseline still accepted 4/24 non-owner events
  (closest impostor: another French female TTS voice, up to 0.65). Noise/keyboard: 0/354 false accepts; overlap 9/9
  confirmed. Latency is set by the evidence window (P50 1.6 s for every engine), not by the model.
- Structural finding for Task 07: when a colleague speaks right after the owner, the 1.5 s window still contains the
  owner and scores 0.8–0.9 for up to ≈ 1.5 s → a lingering `owner_confirmed` must not authorize the next speech segment.
- Tests: orchestrator re-run (`test_speaker_benchmark`, `test_owner_voice`, `test_v2_architecture`) **144 passed**;
  agent full suite **1505 passed, 4 skipped**. Private benchmark dir `runtime/speaker-verification/benchmark/private/`
  confirmed git-ignored; result files contain scores/timings/metadata only.
- Design: schema `jarvis.speaker_benchmark.result` v1 (frozen keys, version bump on change); hop classes overlap >
  owner/non-owner (≥ 50 %, tie → owner) > noise > silence; FAR = accepted/judged non-owner-only hops, FRR =
  rejected/judged owner-only hops; owner events merged across ≤ 1 s gaps; EER threshold-free with interpolation; sweep
  re-applies thresholds to one replay; identical preprocessing (24 kHz capture, 100 ms hops, production gate),
  `--ablation` to change; AEC/echo not modelled offline.
- Deviations: added `--transition-guard-ms` + "settled" results and OneCore voices (SAPI has only 3 female voices);
  two large ERes2Net exports (116–220 MB) not catalogued. No production default changed (Task 14).
- Handoff notes (Task 14): record owner enrollment (30 s) + labelled sessions under
  `runtime/speaker-verification/benchmark/private/` (manifest from the example with `"evidence": "real"`), then
  `scripts\benchmark_speaker_verification.py run <manifest> --sherpa-model campplus-zh-en-advanced --sherpa-model
  eres2net-en-voxceleb --threshold-range 0.40:0.85:0.025 --evidence-ms 1000,1500,2000,2500 --out-dir
  docs\results\speaker-benchmark --basename <date>-real` (+ `--transition-guard-ms 1500`, + `--realtime`); choose per
  `docs/SPEAKER_BENCHMARK.md` « Reading the results » (zero-false-accept threshold + one step margin, shortest evidence
  window with acceptable miss rate / P95, ring buffer ≥ that P95, tiebreak EER then CPU).

### Task 06 — Add longer owner-verification ring buffer and provider-advisory flow — DONE

- Changed files (working tree, no commit):
  - `jarvis/audio/duplex.py`: owner-verification ring + sent/not-sent tracking + one-time replay in `CaptureProcessor`
    (`owner_buffer_ms=None`, `owner_replay_margin_ms=150`, `set_owner_gate()`, `open_owner_flow()`,
    `close_owner_flow()`, `take_owner_replays()`, `OwnerReplay`, `OWNER_REPLAY`, `OWNER_REPLAY_MARGIN_MS`).
  - `jarvis/runtime/realtime_audio.py`: gate/flow/replay pass-through; bridge `_set_owner_gate`, `_open_owner_flow`,
    `_on_owner_replay`; `_on_owner_state` opens/closes the flow; `_on_barge_timeout` re-arms while the verifier
    candidate is open (owner-held mode); event `voice.owner.replay`; advisory gains `replay_ms`.
  - `jarvis/app.py`: `owner_buffer_ms` passed only when `solo_owner` is enforced.
  - tests: new `tests/unit/test_owner_replay.py` (39), `tests/unit/test_app.py` +1. Docs: `docs/ARCHITECTURE.md`
    « Owner replay buffer » + tables; `docs/OPERATIONS.md` replay behaviour, memory, tuning, trace table.
- Tests: orchestrator re-run (replay, owner barge-in, duplex, v2 barge-in, output control, playback cursor, app, speaker
  verifier) **296 passed**; agent full suite **1505 passed, 4 skipped** (twice); new file 5× green. Covered: 0.5/1/2/2.3 s
  delays at 16/24/48 kHz with first syllables present; wrap → clamped + `owner_replay_clamped`; earlier non-owner not
  replayed; near-end not forwarded while JARVIS speaks; no re-send of pre-roll/guard frames; exactly-once flush under
  concurrency; session reset; 5-min bound at 48 kHz; open room byte-for-byte identical; bridge order local stop →
  cancel/truncate → replay; e2e with real detector + verifier thread (provider output = mic from 1350 ms).
- Design: ring exists only with `owner_buffer_ms` (open room: none); last `owner_buffer_ms/10` post-AEC 10 ms frames on
  the capture clock (onset/10 = index); 120 KB at 24 kHz / 2.5 s; RAM only. Single `_sent_until` index → no
  duplicates, never behind sent audio; replay marks the acoustic pre-roll sent. Solo Owner gate: while JARVIS is
  audible the provider gets silence unless the owner flow is open (latch only emits `near_end`). Flush request stored
  under the capture lock, applied at the next capture block before its frames, through the normal input path (never
  playout). Margin 150 ms only when owner onset = candidate onset. No pacing (≤ 5 s burst, one append; OpenAI VAD
  segments by audio time).
- Deviations: latch-release change in owner-held mode (timer re-arms while candidate open) — beyond Task 05, documented;
  rate fixed per `CaptureProcessor` (new capture on rate change); margin not a user setting; new event
  `voice.owner.replay` instead of extending `voice.barge_in.owner_confirmed`.
- Handoff notes:
  - Task 07: gate in `CaptureProcessor.process` owner branch `should_open = self._owner_flow or not
    self.detector.far_recent` → drop `or not far_recent` behind a flag; `_on_owner_state` already opens on confirmation /
    closes on idle|rejected and the replay covers silent JARVIS. Blockers: utterances shorter than 1.5 s evidence
    (« oui », « stop ») never confirmed → need a decision (e.g. verdict at candidate end); turn start delayed ≈ 1.7–2 s.
  - Task 14: from `voice.owner.replay` / `voice.barge_in.owner_confirmed` measure P50/P95/max of
    `confirmed_ms − owner_onset_ms` and `clamped_ms > 0` rate; onset error (first owner word present, no non-owner
    leak); provider lag; default ≈ P99 onset→confirmation + 150 ms + ~300 ms headroom.

### Task 07 — Gate active input and useful activity by owner identity — DONE

- Changed files (working tree, no commit): code `jarvis/audio/duplex.py`, `owner_verifier.py`, `speaker_shadow.py`;
  `jarvis/ports/speaker.py` (optional `finish_candidate(judge)`); `jarvis/adapters/fake_speaker_verifier.py`;
  `jarvis/domain/speaker.py`; `jarvis/v2_config.py` (`owner_short_evidence_ms`, `owner_short_margin`);
  `jarvis/runtime/owner_voice.py`, `realtime_audio.py`, `voice_v2.py`, `visual_signals.py`, `control_center.py`;
  `jarvis/app.py`. Tests: new `tests/unit/test_owner_input_gate.py` (51); edits in `test_owner_replay.py`,
  `test_owner_barge_in.py`, `test_app.py`, `test_owner_voice.py`, `test_conversation_authorization.py`,
  `test_v2_speech_scheduler.py`. Docs: `docs/ARCHITECTURE.md` « Owner input gate (Solo Owner, task 07) »;
  `docs/OPERATIONS.md` « Solo Owner: only your voice is a turn » (semantics, refusal table, troubleshooting, rollback).
- Tests: orchestrator full suite **1557 passed, 4 skipped** (54 s); agent: new file 5× green, 14-file voice set 572 passed.
  Root cause of the `test_v2_speech_scheduler.py` flake (seen in Tasks 11/12/13): module-level `ORIGIN = utc_now()` +
  60 s transient-speech TTL → fixtures expired once the suite took > 60 s to reach the file; fixed with an autouse
  fixture resetting `ORIGIN` per test.
- Design:
  - Gate point = capture guard in `CaptureProcessor.process`: with the owner gate on, audio is forwarded only while the
    owner flow is open, JARVIS speaking or silent (gated frames = digital silence). Second line in the bridge: provider
    `speech_started`/transcript accepted only if it starts while the flow is open or ≤ 3 s after it closed; others
    dropped before the `voice.transcript` trace and addressing (text never logged). Filters unchanged behind it.
  - Short replies: at candidate end (600 ms silence) with no verdict, score the voiced audio once if ≥
    `owner_short_evidence_ms` (default 600, 300..window, 0 disables) with threshold + `owner_short_margin` (default
    0.5 + 0.1); owner → whole candidate replayed (a short « stop » still interrupts), else dropped (`short_not_owner` /
    `insufficient_audio`). Turn starts ≈ 0.6–0.8 s after the owner stops; a lone « oui » < ≈ 600 ms voiced is dropped.
  - Lingering confirmation: each ended candidate clears evidence (next one needs a fresh verdict before forwarding);
    no-pause handover closes the flow on the first non-owner verdict, and the most recent 600 ms is re-scored while
    confirmed (below threshold − margin = 0.4 ends the verdict). Worst-case leak ≈ 1.2 s (vs ≈ 2.0 s without), +40 %
    verifier CPU while the owner speaks; leaked audio joins the owner's turn, never forms its own turn.
  - Useful activity: only addressed owner transcripts, JARVIS speech and brain activity reset the timeout. Scheduler
    hold: a candidate without verdict or a confirmed owner holds; non-owner verdict or candidate end releases (another
    voice delays JARVIS ≈ 2 s per utterance at most, can cancel a pending ack, never creates one).
  - Owner addressing unchanged (identity first, then `addressed`/`uncertain`, Decision 44).
  - Refusal (replaces both `TODO(tâche 07)` fallbacks): Solo Owner that cannot apply is refused before anything opens
    (no provider session, no mic). Codes: settings parse code, `solo_owner_requires_continuous_brain` (checked first),
    `solo_owner_unavailable`, `solo_owner_capture_unsupported`; each emits `voice.authorization_refused` (code, French
    message, phase startup|activation|session), shows the alert, writes `runtime/.voice_authorization`;
    `GET /api/settings` uses the same assessment + `runtime` block + `status_source: voice`. Mid-session verifier
    failure: input stays closed (fail closed), session deactivates with an explanation. Rollback: `open_room` + restart Voice.
  - Trace `voice.input.non_owner_dropped` (source `capture` | `provider`, scalars only).
- Deviations: Task 05/06 tests asserting replaced behaviour were edited (open-room tests untouched); two test files set
  `continuous_brain` in setup; benchmark harness does not yet model the short-reply rule. Pre-existing race not fixed:
  wake key pressed while a session shuts itself down after an in-session mute is treated as « stop ».
- Handoff notes:
  - Task 08: render `voice.authorization` (`status`, `code`, `problem`, `status_source`, `runtime.{status, code, problem,
    phase, arch, ts}`); distinguish settings-probe problem vs Voice-seen refusal; show « restart Voice » after changes;
    optional controls `owner_short_evidence_ms`, `owner_short_margin`; counters `voice.input.non_owner_dropped`
    (capture vs provider), worker `availability` / `dropped_ms`.
  - Task 14: tune short-reply rule (`voice.owner.confirmed verdict=candidate_end`, drops `short_not_owner`); measure
    handover leak and mid-sentence false rejections, recent-window CPU; latency per utterance ≈ 1.6–2 s;
    `owner_replay_clamped` on short replies (`owner_buffer_ms` ≥ utterance + ≈ 0.75 s); add end-of-candidate scoring to
    the benchmark harness.

### Task 08 — Expose Solo Owner quality/degraded settings in Control Center — DONE

- Changed files (working tree, no commit):
  - `jarvis/runtime/voice_stack.py`: `Field.option_labels` / `placeholder`; `AUTHORIZATION_FIELDS` (mode, verification,
    owner buffer) and `OWNER_TUNING_FIELDS` (threshold, evidence, short evidence, short margin), bounds from config/domain.
  - `jarvis/runtime/control_center.py`: POST `voice.authorization` accepts the 4 tuning keys via
    `parse_speaker_verifier_settings` (same reader as Voice), canonical storage, `owner_profile_path` ignored, 400 with
    stable code in `X-Jarvis-Error-Code`; GET adds `fields`, `advanced_fields`, `origin`, `verification_modes_by_mode`,
    `verifier_settings`, `verifier_remedy`, `restart_required`, `worker`; shadow without working verifier →
    `degraded` / `status_source: voice`; new GET `voice.echo_cancellation` (`configured`, `applicable`, `installed`,
    `status`, `code`, `problem`, `status_source`, `runtime`, `restart_required`).
  - `jarvis/runtime/voice_v2.py`: `echo_cancellation=` + `_report_capture()` (capture state at wake, factory failure,
    session end; in-session AEC failure traced once `duplex_aec_failed`). `jarvis/runtime/visual_signals.py`:
    `.voice_capture` file. `jarvis/runtime/owner_voice.py`: `effective_verifier_settings()`, `probe_remedy()`.
    `jarvis/adapters/webrtc_echo.py`: `echo_cancellation_installed()`. `jarvis/app.py`: wiring.
  - `jarvis/runtime/control_center.html`: « Qui peut parler à JARVIS » block (Mode vocal tab) + « Annulation d'écho »
    status; `renderField` labels/placeholders.
  - Docs: `docs/OPERATIONS.md` « What the Control Center shows for Solo Owner and echo cancellation » (API-only notes
    removed); `docs/ARCHITECTURE.md` `.voice_capture` paragraph. Tests: new `tests/unit/test_control_center_quality.py` (67).
- Tests: agent full suite **1624 passed, 4 skipped**; regression set 523 passed; `node --check` on the page script is a
  test. Orchestrator: 3 full runs → 1 failure in `test_owner_voice.py::test_probe_without_profile_then_corrupt_then_incompatible_then_ready`
  (not Task 08): root cause reproduced — `owner_voice_profile.save_profile` `os.replace` raises `PermissionError`
  (WinError 5) on Windows when the target is briefly held (AV/indexer), 12 / 3000 in a stress loop → real
  enrollment-reliability defect, fix assigned to Task 14 pre-flight.
- Design: page shows state only (verdicts from `assess_authorization` / Voice reports); sends only touched keys;
  verification dropdown filtered by mode (mode change resets to « Selon le mode »); AEC status via minimal
  `.voice_capture` file (same pattern as `.voice_authorization`, read while heartbeat fresh) — trace-based status
  rejected (6 MB trace read); Voice report overrides the probe only if it matches current settings, else
  `restart_required`.
- Deviations: `voice.input.non_owner_dropped` counters not shown (would need a new counting path; stay in trace);
  `owner_profile_path` read-only; in-session AEC failure visible only after session end / next wake.
- Handoff notes (Task 14 UI checks): red « Solo Owner configuré mais NON appliqué » + enroll command before enrollment,
  green « Solo Owner appliqué » (source Voice) after; profile details without voiceprint (DevTools `/api/settings`);
  shadow grey + worker `ready`, `dropped_ms` ≈ 0 after long session; AEC « active · Constaté par Voice », break LiveKit →
  « dégradée / aec_unavailable »; tuning change → restart notice → origin « réglage »; kill verifier mid-session → red
  banner `status_source: voice`, phase `session`; stop Voice → probe takes over.

### Task 14 — Hardware acceptance, benchmark, defaults, rollout — automatable part DONE / hardware PENDING USER

- Changed files (working tree, no commit): new `jarvis/adapters/file_replace.py`, `jarvis/runtime/trace_summary.py`,
  `scripts/summarize_voice_trace.py`, `docs/HARDWARE_ACCEPTANCE.md`, `docs/fixes/solo-owner-duplex/final-implementation-report.md`,
  `tests/unit/test_solo_owner_acceptance.py` (3), `tests/unit/test_trace_summary.py` (6); edited
  `owner_voice_profile.py`, `sherpa_speaker_embedder.py`, `sherpa_model_catalog.py`, `owner_verifier.py`
  (`last_window_score`), `speaker_benchmark.py` (audio + runtime), `control_center.py`, `scripts/verify_release.py`,
  `test_owner_voice.py` (+4), `test_speaker_benchmark.py` (+5), `test_control_center_quality.py` (+1), docs
  (`SPEAKER_BENCHMARK.md`, `results/speaker-benchmark/*`, `OPERATIONS.md`, `ARCHITECTURE.md`, `ACCEPTANCE_STATUS.md`,
  manifest example).
- Pre-flight fix: `replace_with_retry` (8 attempts, 20→250 ms, ≈ 1 s max), atomicity kept (no in-place write, tmp
  removed, coded error `owner_profile_write_failed`, previous profile intact); same helper for both model downloads
  (`speaker_model_install_failed`) and for `ControlCenter._write_settings` (same WinError-5 flake found during the final
  regression). 4 deterministic tests with monkeypatched `os.replace`. Pre-existing sites (`file_state_bus`,
  `markdown_memory`, `google_oauth`, session token) left alone → residual risk.
- Benchmark harness: production short-reply + handover settings in `VerifierParams`; new gate replay driving the real
  `CaptureProcessor` + `SpeakerVerificationWorker` + `ShadowOwnerTelemetry` + replay ring (bridge role replayed) → what
  the provider would actually receive, per threshold; hop metrics score the full window (`window_score`). Schema **v2**,
  CSV `gate` rows, gate table in the Markdown summary.
- Synthetic re-run (2 engines, 39 scenarios, 516 s — SYNTHETIC, not owner data): baseline EER 5.3 % / 1.1 %;
  gate at 0.5 → 4/24 colleague turns opened (11.1 s leaked); at 0.6 → 1/24 (6.7 s), miss 7.7 %, confirm P50 1.65 s;
  at 0.65 → 0 false opens but miss 10.3 % and 2.8 s of sentence start lost. ERes2Net-VoxCeleb: same EER, 2.4× CPU,
  slightly better gate.
- Defaults decision: `owner_threshold` 0.5 → **0.6** (provisional, 0.55 documented as fallback if real voices are missed);
  `owner_evidence_ms` 1500, `owner_buffer_ms` 2500, `owner_short_evidence_ms` 600, `owner_short_margin` 0.1 and the
  baseline engine unchanged; docs, Control Center bounds/labels and benchmark defaults read the same constants.
- Acceptance matrix (in the report): 12 voice + 9 work-state + 4 extra categories mapped to `file::test`; 3 gaps closed
  by new end-to-end tests (colleague conversation while JARVIS speaks → no duck/cut; owner interrupts → local stop
  before any provider event, prefix replayed once, leak bounded; JARVIS silent → colleague never a turn nor useful
  activity; rollback `open_room` byte-for-byte identical with a verifier attached). 7 Task-14 criteria: 3 automated,
  4 PENDING USER with procedure links.
- Tests: agent full suite ×3 **1643 passed, 4 skipped** (67.5 / 73.6 / 72.8 s); orchestrator re-run ×2 1643 passed
  (66.6 / 67.3 s); `scripts/verify_release.py` passes (it did not before: Task 09 tooling tripped the `subprocess.run(`
  rule — repaired with a named allow-list + an AST check that fails if a production module imports the benchmark tooling).
- Deliverables: `docs/fixes/solo-owner-duplex/final-implementation-report.md`, `docs/HARDWARE_ACCEPTANCE.md` (setup,
  enrollment, shadow day, 10 scenarios + trace events + Control Center checks, real-recording benchmark commands, VAD
  comparison, work-state parity, long session, defaults selection, rollback, result sheet) + helper
  `scripts/summarize_voice_trace.py` (scalars only).
- Remaining risks: nothing acoustic measured on real hardware (thresholds/latencies/echo); engine choice open; handover
  leak ≈ 1.2 s; quiet owner under loud speech may not open a candidate; profile unencrypted at rest; `owner_onset_ms`
  is an estimate; other pre-existing Windows `os.replace` sites; no producer lease; Solo Owner inherits the
  `continuous_brain` opt-in; replay burst never seen by the real provider VAD.

## Critic round 1 (2026-09-12) — score 80/100 → fixes dispatched

Report: `reviews/critic-review-1.md` (conformance 27/30, correctness 17/25, tests 16/20, truthfulness 7/10,
documentation 8/10, safety 4.5/5). 6 blocking defects + 26 non-blocking findings. Four fix agents ran in parallel,
split by file ownership; the orchestrator verified the tree after each.

- Core work-state / brain (B1, B2, B4 + NB3–NB6, NB14): attention notes now served from the char budget **before** the
  active list and consumed by `take_delivered()` (`domain/brain_context.py`, `core/brain_context.py`); a restarted
  producer claims after decoding and keeps the keys its own batch reports, plus a narrow reopen of items interrupted
  with `error_class == PRODUCER_RESTARTED` (`core/work_state.py`); a rejected 400 batch arms a resync and is journaled
  once (`work_ingress.py`); `resync()` keeps owed merge closures; the attention subscriber is now a `lossy=True`
  subscription (drop oldest, counted `core.event_bus.event_dropped`) instead of an evictable one (`v2_services.py`,
  `v2_app.py`); eviction memory 512 → 4096 with the sizing argument written down.
- Control Center / UI (B5 + NB7, NB18, NB23): page logic extracted to `jarvis/runtime/control_center_work.js`, inlined
  by the server at a marker and **executed** by node in tests (revision guard compared case-by-case against the
  server's `accept_snapshot`, elapsed from Core dates + skew, terminal vs running); `GET /api/work` builds nothing;
  a failed settings write unlinks the temp file and returns a coded 503 (no secret left on disk); a hand-edited
  `continuous_brain` + `gemini_live` pair is now `refused`, and a mode change no longer drops a stored `shadow`.
- Voice runtime / CLI (B6 + NB1, NB2, NB9, NB10, NB20, NB21, NB22, NB24): coded French CLI failures instead of
  tracebacks (no network, busy mic, no keyboard, missing audio lib); the owner replay is undroppable (live block
  evicted instead) and a lost replay is traced `owner_replay_dropped`; a capture refusing the owner gate fails closed;
  the probe verifies the model SHA-256 (cached on size+mtime, 48 ms then ~4 ms) so a corrupt model is no longer
  `ready`; `owner_profile_path` must stay under `runtime_root`; model downloads abort past the pinned size;
  `trace_summary` clamps free-text fields and prints on a cp1252 console; 4 diagnostic kinds documented.
- Benchmark / report (B3 + NB8, NB12, NB13, NB15, NB17, NB19, NB25): every published figure re-derived from the named
  JSON by `scripts/speaker_benchmark_figures.py` and guarded by `tests/unit/test_published_benchmark_figures.py`
  (README / final report / OPERATIONS must agree with the artifacts); corrected cost table (baseline 30.1 ms/hop,
  3.51 % core, 517.6 ms load, +107.4 MB), full P50 series instead of "1.6 s at every threshold", noise claim restated
  exactly, hop-level FRR (28.0 % strict / 20.8 % settled) published next to the 7.7 % gate miss; release gate now scans
  `scripts/` and catches dynamic imports; SHA-256 + size for all 8 models in the docs + third-party notice
  (sherpa-onnx Apache-2.0, 7 models Apache-2.0, WeSpeaker CC-BY-4.0 attribution); stale « Ce qui n'est pas vérifié »
  section updated; per-file test counts re-collected.
- Tree after fixes (orchestrator): full suite **1702 passed, 4 skipped** ×3 (68.2 / 70.6 / 67.9 s),
  `scripts/verify_release.py` passed. Known watch item: one isolated flake seen once in
  `tests/unit/test_state.py::test_initialize_recovers_stale_visualizer_runtime_files` during a concurrent run.

## Critic round 2 (2026-09-12) — score 87.5/100 → two blockers fixed

Report: `reviews/critic-review-2.md` (conformance 28/30, correctness 20/25, tests 18/20, truthfulness 8/10,
documentation 8.5/10, safety 5/5). Five of six round-1 blockers confirmed genuinely fixed (not test-satisfied),
23/26 non-blocking fixed; the `test_state.py` watch item was cleared as environmental (8× standalone green, two
concurrent full suites green). Two new blockers, both created by the round-1 fix pass, were dispatched to two agents:

- **R1 — producer-restart reopen ignored producer identity** (`jarvis/core/work_state.py`): Core now keeps two
  private maps (`_owners`, `_core_interrupted`) — never on `WorkItem`, so they cannot reach `to_payload`,
  `core.work.updated`, the snapshot or `from_payload`; `apply(observation, *, producer=…)` takes the producer only
  from `WorkObservationBatch.producer_id`; reopen requires the key to have been interrupted **by Core** and the
  speaker to be the source's current claimant (`error_class` is no longer an authority); `min()` on `updated_at`
  dropped, so a stale observation stays stale; `interrupt_source(..., owner=)` only interrupts the displaced
  producer's items; maps pruned on eviction. Probe (5 scenarios, same script before/after): two Control Centers
  alternating 7 rounds went from revision 54 / 26 false attention notes / half the items wrongly `interrupted` to
  revision 8 / 4 notes / all items stable; a forged `error_class=producer_restarted` no longer reopens; a 6 s-old
  observation is `stale`; the legitimate restart-reopen still works. Tests 44 → 49 (4 of 5 fail on the pre-fix module).
  `docs/ARCHITECTURE.md` rewritten accordingly, including an honest row for two concurrent Control Centers.
- **R2 — published evidence promised a reproducibility contract the guard did not keep**: `figures()` now raises on a
  missing key (no more silent `0.0`) and exposes the six missing figure classes (model verify, hop P50/P95, zero-FA
  miss/P95, noise/non-owner counts, CPU ratio, per-scenario and per-tag scores); the guard compares Markdown cells
  **in position** (20 tests): 2026-09-12 gate table 7×9, cost table, report engine table, the whole 2026-09-11 table
  (8 engines × 8 columns), short-reply **counts** instead of prose, decision paragraphs, OPERATIONS figures.
  Mutation harness (scratch): real falsifications caught **5/30 before → 30/30 after**, positive controls 4/4 both
  times. README/report now state exactly which figures are machine-checked and which are not; the misleading
  « P50 1.6 s at every threshold » sentence is replaced by the derived series. NB11 fixed (`{task_id}` route
  template) with a new `tests/unit/test_documented_routes.py` guard; report count `test_trace_summary.py` 6 → 8.
- Tree after fixes (orchestrator): full suite **1718 passed, 4 skipped** ×2 (67.9 / 67.4 s),
  `scripts/verify_release.py` passed; work-state targeted set 134 passed. The final report's suite-count line was
  refreshed to 1718 by the orchestrator.

## Critic round 3 (2026-09-12) — score 93.5/100 — BAR CLEARED, no blocking defects

Report: `reviews/critic-review-3.md` (conformance 29/30, correctness 23/25, tests 19/20, truthfulness 8.5/10,
documentation 9/10, safety 5/5).

- R1 **FIXED (high confidence)**: the auditor's own 28-check probe against the real store passes 28/28; two Control
  Centers over 7 alternating rounds → revisions `[6,8,8,8,8,8,8]` and 4 attention notes (was 54 / 26 / permanent
  flapping); forged `error_class` stays terminal for the owner and for a new claimant; a 6 s-old observation is
  `stale`; the private maps are absent from bus payloads, snapshot, ingest ack and the diagnostic sink, pruned on
  eviction; every Task 11 acceptance re-verified; the five new tests are real oracles (values reproduced independently).
- R2 **FIXED**: rebuilt mutation harness — positive controls 4/4, **28 structural falsifications built, 28 caught,
  0 missed** (all eleven round-2 misses plus 17 new); systematic single-number sweep: README 284/359, report benchmark
  table 100 %; remaining misses are threshold labels, fixture parameters and configuration constants the pages declare
  unasserted.
- Runs: full suite **1718 passed, 4 skipped** ×2 standalone (71.1 / 68.9 s), again inside the release gate (69.2 s,
  passed), and a concurrent pair both green (72.5 / 72.5 s) — the `test_state.py` watch item did not reproduce;
  timing-sensitive set 6 × 321 passed, no flake.
- Non-blocking items left by the auditor were dispatched as a final accuracy polish (README checked/unchecked sets
  incl. the overlap-events claim, the two-Control-Centers consequence in `ARCHITECTURE.md`, a visible `MAX_PRODUCERS`
  overflow, "AEC-cleaned" wording vs the three degraded branches, the stale « sonde bon marché » comment, the lone CR
  in `.gitignore`, the producer-sourced subagent badge).

## Final accuracy polish (2026-09-12) — non-blocking items from round 3

- README « machine-checked » set completed rather than re-declared: `overlap_events(_confirmed)` exposed in
  `speaker_benchmark_figures.py`, the overlap claim, the owner-cost paragraph, the noise thresholds and the
  « (4 → 1) » decision figure now asserted against the page (guard 20 → 22 tests; 7/7 hand-built falsifications
  caught). The one genuinely underivable statement (« ~2–3× » strict/settled ratio) moved to the declared-unchecked list.
- `docs/ARCHITECTURE.md` two-Control-Centers row now states the consequence (every item ends `interrupted /
  producer_restarted` and stays there; the work keeps running, only Core's view is dead), pinned by the two-CC test.
- `MAX_PRODUCERS` overflow is now visible: `core.work.producer_forgotten` (bounded, deduped, no producer id) +
  a test pinning that a later takeover on the forgotten source interrupts nothing.
- « AEC-cleaned » corrected in the docs (no code defect): `docs/ARCHITECTURE.md` now defines the three pass-through
  branches where the verifier and the Task 06 ring receive the **raw microphone**; `docs/OPERATIONS.md` says what is
  scored in each `dégradée` state; new parametrized duplex test (no canceller / failed canceller → observer bytes ==
  microphone bytes).
- Carried-over: stale « sonde bon marché » comment corrected (the probe verifies the model SHA-256, cached on
  size+mtime); the phantom CR patterns removed from `.gitignore` (all four blank lines) + new `.gitattributes`
  (`.gitignore text eol=lf`) so `core.autocrlf` cannot reintroduce them; the subagent badge now marks a non-Core count
  as « décompte local du Control Center, non autoritaire ».
- Final tree (orchestrator): full suite **1723 passed, 4 skipped** (68.8 s), `scripts/verify_release.py` passed;
  working tree 35 modified / 61 untracked, no commit.

## Handoff closed

Tasks 00–14 complete. Score 93.5/100 (round 3, no blocking defects). Remaining work needs the user: physical
workstation acceptance per `docs/HARDWARE_ACCEPTANCE.md` (owner enrollment, office scenarios, real-recording
benchmark, final defaults). Final report: `docs/fixes/solo-owner-duplex/final-implementation-report.md`.
