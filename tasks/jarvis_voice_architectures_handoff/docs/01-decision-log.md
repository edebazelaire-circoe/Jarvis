# Decision Log

## Decision 01 — Three named voice architectures
**Status:** locked

**Decision:** Settings exposes `Simple`, `Front Brain`, and `Duplex` as the top-level voice architecture choices.

**Rationale:** Architecture is more meaningful than a flat “voice model” selector because each mode has a different number and type of models/settings.

**Implications:** UI and config must be architecture-aware.

**Tests / enforcement:** Schema validation and UI tests must reject impossible combinations.

## Decision 02 — Common frontend abstraction
**Status:** locked

**Decision:** Realtime, Realtime+Front Brain, and GPT-Live must implement a common JARVIS-facing frontend contract.

**Rationale:** Prevent provider APIs from leaking through the whole runtime and make benchmarking/switching possible.

**Implications:** Introduce canonical events, lifecycle, capabilities, usage reporting, and speech controls.

**Tests / enforcement:** Contract test suite runs against every frontend adapter.

## Decision 03 — GPT-Live is a primary expected target, not a one-off branch
**Status:** locked

**Decision:** Implement GPT-Live 1 as a first-class Duplex frontend using client delegation while preserving Realtime modes.

**Rationale:** GPT-Live's conversation/delegation split closely matches JARVIS's desired architecture.

**Implications:** Backend remains JARVIS-controlled.

**Tests / enforcement:** End-to-end duplex scenario with mocked backend delegation.

## Decision 04 — JARVIS owns application/task state
**Status:** locked

**Decision:** Conversation/task state must live in JARVIS, not only in provider session state.

**Rationale:** Required for switching providers, reconstructing context, permissions, tracing, and recovery.

**Implications:** Session restart can rehydrate relevant state.

**Tests / enforcement:** Provider swap does not erase active task metadata or spoken-history ledger.

## Decision 05 — Actually spoken text is authoritative
**Status:** locked

**Decision:** The conversation core records what the voice layer actually emitted, including reflex speech and provider paraphrase.

**Rationale:** The user responds to heard speech, not intended speech.

**Implications:** Output transcript events feed the common state store.

**Tests / enforcement:** Simulated divergence updates state with actual speech, never intended speech.

## Decision 06 — Silence is a first-class action
**Status:** locked

**Decision:** The frontend/controller can choose `WAIT` and finish a turn without spoken acknowledgement.

**Rationale:** Systematic acknowledgements are irritating and increase latency/queue contention.

**Implications:** Reflex generation is gated, not automatic.

**Tests / enforcement:** “OK”, side conversation, background noise, and “attends je réfléchis” regression scenarios can produce no speech.

## Decision 07 — Reflex speech is narrow and ephemeral
**Status:** locked

**Decision:** Reflex speech may backchannel or preamble when genuinely useful but must not invent factual/task state.

**Rationale:** Current failures include voice improvisations that contradict backend reality.

**Implications:** Fact-bearing task answers come from verified conversation/backend state.

**Tests / enforcement:** No “I checked”, “done”, or fabricated result unless state confirms it.

## Decision 08 — Speech queue is freshness-aware, not strict FIFO
**Status:** locked

**Decision:** Unstarted/remaining speech can be cancelled, merged, reprioritized, or dropped when a newer user turn makes it stale.

**Rationale:** The trace contains 29–36 second queue delays for responses that were no longer useful.

**Implications:** Every speech item needs source turn, age/freshness, priority, and cancellation state.

**Tests / enforcement:** Stale queued response never plays after a superseding user correction.

## Decision 09 — Backend work must not block conversation
**Status:** locked

**Decision:** Long/tool-heavy work is delegated to back brain/sub-agents; conversation frontend remains responsive.

**Rationale:** An 85.7s lookup blocked later turns in the trace.

**Implications:** Explicit delegation policy and progress/result routing.

**Tests / enforcement:** Conversation accepts/handles new input while a mock backend task is still running.

## Decision 10 — Partial-transcript analysis is speculative
**Status:** locked

**Decision:** Use transcript deltas to prepare intent/response/delegation hypotheses while the user is speaking, but revise them as deltas arrive and never execute irreversible actions from partial speech alone.

**Rationale:** Long utterances create useful pre-computation time.

**Implications:** Separate provisional and committed turn state.

**Tests / enforcement:** A late correction invalidates a provisional intent before commit.

## Decision 11 — Front Brain sidecar runs in parallel
**Status:** locked

**Decision:** In Front Brain mode, the fast analysis model must not sit as a serial blocking hop between audio and voice output.

**Rationale:** Specialization should reduce latency, not add mandatory latency.

**Implications:** Hints can race/arrive late and must be optional.

**Tests / enforcement:** Voice frontend can respond without waiting for sidecar when the answer is direct.

## Decision 12 — Prompt transparency
**Status:** locked

**Decision:** Settings exposes every JARVIS-controlled initial prompt and model-specific prompt layer relevant to the selected architecture, plus the resolved effective prompt.

**Rationale:** Prompt behavior is part of runtime configuration and must be inspectable/debuggable.

**Implications:** Prompt registry with provenance, editing, validation, reset, and resolved preview.

**Tests / enforcement:** UI and config tests cover each architecture's prompt layers.

## Decision 13 — Capability-driven model lists
**Status:** locked

**Decision:** Model selectors derive from provider/model capabilities rather than hard-coded architecture-specific lists.

**Rationale:** Realtime, Gemini, future duplex providers, and future models should plug in without restructuring Settings.

**Implications:** Capability registry includes audio in/out, full duplex, transcript deltas, tools/delegation, interruption, prompt controls, and usage reporting.

**Tests / enforcement:** Unsupported combinations are filtered and schema-rejected.

## Decision 14 — Live billing visibility and kill switch
**Status:** locked

**Decision:** Any active GPT-Live session has a prominent active marker, elapsed timer, immediate Stop control, and watchdog/cleanup protection.

**Rationale:** Live is billed by active time and must never silently remain active in background.

**Implications:** Session lifecycle is explicit and observable.

**Tests / enforcement:** Crash/exit/mode-switch/orphan tests close or mark-and-reap Live sessions.

## Decision 15 — Live idle timeout is configurable
**Status:** locked on principle; value unresolved

**Decision:** Auto-close after inactivity is required, but the exact timeout is a setting/benchmark parameter rather than a hidden constant.

**Rationale:** Cost vs conversational continuity needs real-world tuning.

**Tests / enforcement:** Configurable timeout and disable/override semantics are tested.

## Decision 16 — Benchmarking is first-class
**Status:** locked

**Decision:** Every voice session records architecture/model/prompt identifiers and comparable quality, latency, interruption, delegation, and cost metrics.

**Rationale:** The final architecture winner should be selected empirically.

**Implications:** Replay/scenario harness and session report.

**Tests / enforcement:** The same scenario suite runs in all three modes.

## Decision 17 — Exact Gemini compatibility is discovered, not assumed
**Status:** locked

**Decision:** Existing Gemini support should be included where its actual capabilities permit, but exact model names and feature support must be taken from the current JARVIS code/provider integration.

**Rationale:** Avoid stale external assumptions and incorrect UI options.

**Implications:** Inventory task precedes final capability registry population.

**Tests / enforcement:** Provider registry reflects discovered adapter capabilities.

## Decision 18 — Preserve existing execution mode during migration
**Status:** implementation constraint, 2026-09-12

**Decision:** The new three-way architecture configuration must preserve the existing `legacy` / `continuous_brain` execution choice during automatic migration. These values currently select tool authority, audio capture, prompts and default models; mapping a label to Simple must not silently change those semantics. Explicit selection of the new architecture is a separate transition, completed through the switch coordinator.

**Tests / enforcement:** Cover saved-settings and environment precedence, both execution modes, explicit model preservation, Gemini restrictions and missing/unknown model handling. Keep the current safe default pending Task 20 evidence.

## Decision 19 — Generated transcript is not playback confirmation
**Status:** clarification of Decision 05, 2026-09-12

**Decision:** Keep intended text, provider-generated transcript and local playback evidence distinguishable. Existing Realtime can finish generating text before playback completes. A zero-played output is unspoken; an interrupted output with no word alignment remains explicitly partial/unknown rather than asserting that all generated words were heard. Provider timing and playback support define the precision available.

**Tests / enforcement:** Before-first-audio interruption, transcript-before-playback, partial playback with unknown alignment, provider paraphrase, late transcript after cancellation, and snapshot projection. Do not infer completed user turns or heard speech from silence alone in providers lacking authoritative completion events.

## Decision 20 — Reuse durable jobs with an independent backend executor
**Status:** implementation direction from inventory, 2026-09-12

**Decision:** Task 11 extends existing Core JobService and its local protocol with the missing general backend worker/ingress. The executor must not share the conversational CLI ask lock. Reuse configured CLI wrappers, routing and permissions with explicit job/session/process ownership; keep durable task authority in Core.

**Rationale:** The current subagent tracker is observational, and an extra coroutine around the shared agent route cannot guarantee conversation responsiveness. Self-development is an existing but narrower workflow with deployment side effects and is unsuitable as a generic research substitute.

**Tests / enforcement:** Independent long worker while conversation proceeds; duplicate submission starts once; targeted bounded cleanup; results survive frontend replacement without forcing speech. See `nonblocking-backend-integration-notes.md` for exact gaps and cancellation constraints.

## Decision 21 — Device completion is a separate audio boundary
**Status:** implementation clarification of Decision 19, 2026-09-12

**Decision:** Task05 preserves acoustic behavior and reports partial/unknown delivery wherever the existing audio wrapper lacks device completion evidence. Task07 must establish and use a real natural-completion boundary before switching and benchmark closeout. Provider completion, an empty Python queue, elapsed latency or a zero-latency fake cannot alone confirm full delivery.

**Rationale:** The current playback cursor subtracts device latency and never credits natural buffer drain. Installed sounddevice supports checked output-only stop as a drain proof, but its native call has no safely cancellable timeout. Application control must stay responsive while uncertain native work remains owned; it cannot promise immediate physical stop under a blocked driver.

**Tests / enforcement:** Controlled device-buffer tests through the canonical runtime, interruption/session epochs, native lock exclusion, drain failure/timeout and truthful lifecycle. See `device-playback-completion-plan.md`; manually injecting COMPLETE into a ledger test is insufficient for the production audio gate.

## Decision 22 — Live advisory work has explicit provenance and restricted execution

**Status:** Accepted implementation clarification, 2026-09-12.

**Decision:** A metadata-only Live delegation can request analysis of application-admitted, bounded, revision-tagged context. It does not commit a user turn or authorize an action. Task11 must give advisory jobs an explicit Core-owned job reference/source-snapshot projection while preserving the committed-source invariant of existing VoiceTaskRecord. No synthetic commit, borrowed turn identity or invented provider task text.

**Rationale:** Live lacks authoritative transcript finality, and the existing canonical task record requires a committed source turn. The existing CLI wrappers can carry broad tools/permissions; an analysis-only prompt does not constrain external effects. CoreToolRouter also assumes upstream explicit request admission.

**Tests / enforcement:** Reuse JobService and independently owned CLI wrappers with separate speculative-analysis and admitted-work scopes. Speculative execution requires an enforced restricted profile; unsupported restriction returns unavailable rather than launching a permissive child. Preserve configured backend/model and normal authorized-work permissions. Capture source dependencies after canonical observation ingress; deduplicate durable delegation-to-job acceptance and retain results across frontend changes. Actions remain subject to actual application admission and existing execute/confirm distinctions. See `live-delegation-authority-plan.md` for verified gaps and acceptance cases.

**Implementation update, Task12C (accepted and release-verified):** The Task11 unavailable-only advisory route now has an executable restricted Claude profile. `BackBrainSpeculativeProvenance` captures a Core snapshot and at most8 complete provisional dependencies without a committed source; stable conversation/session/delegation identity deduplicates the existing JobService path. Configured native Claude retains its model/command under explicit restricted/no-tools/no-hooks/no-MCP/no-browser/no-resume flags. Codex and unsupported launch profiles remain durable unavailable. Results and freshness are queryable, remain nonauthorizing, and survive frontend replacement/restart. This is a controlled implementation/test result, not live-model or billing evidence. See [Task12 implementation evidence](12-implementation-evidence.md).

## Decision 23 — Outcome retention is independent of speech freshness

**Status:** Accepted implementation clarification for Task08, 2026-09-12.

**Decision:** A completed ordinary backend outcome must remain queryable through Core even when its immediate speech becomes stale and after Core restart. Reuse the repository boundary for a minimal outcome projection; `BrainWorkingState` alone is not durable. Existing Job results remain owned by JobService. Neither store is heard history or a new execution authority.

**Rationale:** Inventory found that unspoken conversational summaries currently disappear during Core rehydration. Deferring presentation must not become data loss or force a fabricated assistant turn. Speech eligibility depends on explicit originating intent/dependencies, not every global state revision or the mere truth of a result.

**Tests / enforcement:** Restart Core with an unspoken completed outcome and retrieve it; a newer unrelated intent defers the old speech, while a current answer survives unrelated state updates. Reuse the existing scheduler, exact output admission and device completion boundaries. See `08-scheduler-review-plan.md` for ordering, chunk and bounded-state cases. Task11 still owns independent backend execution.

## Decision 24 — Keep the safe compatibility default pending live evidence

**Status:** provisional closeout decision, 2026-09-13

**Decision:** Do not promote Simple, Front Brain or Duplex to a new default
from the offline benchmark. Preserve the current operational `legacy` default
and all three explicit choices until an authorized provider/audio campaign can
measure real latency, acoustic behavior, conversational quality, availability,
usage and cost.

**Rationale:** The frozen Task20 suite proves composition readiness,
representative controlled conversations, shared policy invariants and safe
migration. It deliberately produces no live timing, token, duration, price or
audio-quality evidence, so it cannot rank the architectures. Existing calendar
and reminder authority blockers also still protect the current default.

**Implications:** Explicit users may select and switch among all three modes.
Compatibility sessions retain `legacy` or `continuous_brain` as their
operational architecture in metrics and switch provenance. Realtime Mini is
frozen for the Simple/Front Brain comparison; the current full-Realtime Front
Brain UI preset remains unchanged and is not a selected default.

**Tests / enforcement:** The Task20 CLI requires exact production-seam node
evidence, verifies compatibility migration separately, and excludes
compatibility samples from architecture comparison. The release suite must keep
default/migration, Live lifecycle, switch and replay gates green.
