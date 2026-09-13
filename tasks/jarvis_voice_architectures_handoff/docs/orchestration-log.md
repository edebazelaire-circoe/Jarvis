# Orchestration log

## Initial checkpoint — 2026-09-12

- Repository: `C:/Projects/jarvis/jarvis`, branch `main`, HEAD `2ced8dd`.
- Starting tracked tree clean; the supplied `tasks/jarvis_voice_architectures_handoff/` bundle is untracked and preserved.
- Read bundle specifications, source transcript, ordered tasks and report templates. Task 00 stays in progress until final gates.
- Skills resolved locally: `C:/Users/Clarice/.codex/skills/caveman/SKILL.md`, `C:/Users/Clarice/.codex/skills/coding-guideline/SKILL.md`, and `.system/openai-docs/SKILL.md`. The handoff's `~/ai/skills` path is stale. No installation needed.
- Implementation follows the user's authorization, with focused subagents and independent parent review before dependent slices. No commits requested.
- Use existing RuntimeJournal diagnostics; validate ownership during inventory. Do not introduce a parallel logging subsystem.
- This handoff's intended-versus-actually-spoken distinction supersedes earlier assumptions that intended backend prose alone describes heard output. Preserve existing behavior during the adapter refactor, then introduce explicitly selected architecture behavior.
- Official GPT-Live delegation/migration and Luna model pages opened; exact wire contracts require verification before provider implementation. No billable Live session starts before lifecycle safeguards.

## Slice 01 — accepted

Inventory production paths and baseline without behavioral edits. Parent reviews configuration migration risks and official API evidence concurrently.

Agent supplied `current-code-map.md` and resolved questions 4/6. Parent cross-checked app composition, old architecture gates, provider event bridge, scheduler persistence, neutral ports and catalog discovery. Focused baseline: 300 passed in 9.78s with warnings as errors. No production edits. See map for exact command.

Decisions 18/19 now document legacy execution preservation and generated-versus-played evidence. Task 02 may proceed; validation must cover real settings precedence and distinguish capability support from remote account availability.

## Provider contract research — reviewed

Official documentation notes saved in `verified-provider-contracts.md`; no billable calls. Live uses a different wire/session and transcript model. No authoritative transcript-final event or exact primary output alignment. Sideband permits known-session close attempts; lost terminal confirmation must remain explicitly unknown. Updated Tasks 12/13 to prevent unsupported Realtime assumptions or invented recovery endpoints. Luna structured Responses format verified. Live entitlement and acoustic behavior remain later validation work.

## Slice 02 — accepted

Added neutral architecture/config/capability types, runtime registry and versioned codec/query/migration; GPT-Live catalog role corrected. Legacy execution mode and model/source/stack settings survive projection. No new mode is wired into the running app yet.

Parent review removed billing-dependent Duplex eligibility and mandatory reasoning-effort support for analysis. Added explicit architecture profiles, optional analysis effort, safe primitive legacy settings and stack environment precedence tests. Agent gate: 174 passed (7.75s). Independent parent gate: 180 passed (4.23s), including new config, legacy migration, Settings endpoints/workbench and architectural import boundaries; warnings are errors. Tests inspect RuntimeJournal normal/rejected events without leaking credentials. Compatibility note and feature INDEX present. Slice 03 may proceed.

## Slice 03 — accepted

Fresh agent `voice_frontend_contract` implements neutral lifecycle/control/event types and a test-only fake. Parent reviewed existing output playout fences and history persistence to guide integration. Realtime documentation research saved in `verified-realtime-contracts.md`: retain input order independently of ASR final arrival; generation completion is not playback; quiet insertion and WAIT must not reuse response-triggering helpers. Task 05 notes updated. No additional provider calls or sessions.

Added typed commands/events, single-consumer frontend port, test-only deterministic fake and recursive/relative import guards. Parent review required generation INCOMPLETE, input predecessor/order evidence, strict integer counters, rejection of unknown Stop falsely claiming stopped, and cancellation with a full fixture queue preserving CancelledError. Agent gate: 102 passed (1.50s). Independent parent gate: 190 passed (3.56s), adding existing Realtime output, audio lifecycle, scheduler and voice-toggle regressions. Pure contracts introduce no production runtime/logging path. Task04 may proceed.

Final Task03 fixture parameterization also covers both default/full queue cancellation: final agent gate 103 passed (1.38s). Docs clarify delta revisions append; Task04 owns explicit provisional replacement semantics.

## Slice 04 — accepted

The contract agent continues with the neutral conversation reducer, evidence ledger and snapshots. No provider/bridge migration in this slice. Parent checks ordering, stale-session rejection, playback truth, task retention and snapshot defensive boundaries before Task05 integration.

Final review required silent completed outputs to settle as unheard/evictable, confirmed-prefix/cursor regressions to be rejected, and closed frontends to reject new activity without discarding valid historical playback. Agent gate: 146 passed (1.66s), including 43 state tests and real RuntimeJournal privacy/error evidence. Independent parent gate: 243 passed (6.91s), adding existing brain migration/orchestration, speech scheduler and Core recovery tests. `docs/state-model.md` documents strict versioned snapshots, task retention, shared dispatch sequencing and mandatory Task05 history integration.

## Slice 05 — accepted

Reviewed `realtime-integration-plan.md`: actual OpenAI composition must pass through VoiceFrontend, one wire reader, existing playout fences and a bounded canonical observation dispatcher to Core. The existing contract needs narrow typed tool-call/result/reflex controls and lightweight received-audio evidence; no PCM crosses Core HTTP. Core owns the ledger and the sole migrated assistant-history projection. Legacy execution/model/settings and Gemini separation remain intact; new conversational policies and UI stay in later slices. Compatibility facade must have an explicit removal condition, with no raw-provider escape hatch.

Device evidence scope: Task05 preserves current acoustic behavior and reports conservative partial/unknown delivery where the existing device wrapper cannot prove drain. Its tests must show this limitation honestly. Task07 now owns establishing a real natural-completion boundary while retaining interruption responsiveness and native stream lock safety. This is required before switching/benchmark closeout; synthetic injected COMPLETE evidence cannot substitute for that production path.

Parent production composition and Core review accepted. First release found outdated startup doubles and a direct-call AST assertion; tests were repaired without relaxing original model/settings/owner/privacy checks. Final parent release:2113 passed,4 skipped (226.88s), all release checks green. Full evidence and reviewed boundaries in `review-05.md` and `05-implementation-evidence.md`. No commits or live provider/hardware calls.

## Slice 06 — accepted

The same implementation owner handles a neutral reflex gate plus existing scheduler/bridge integration. WAIT creates no speech; preamble requires confirmed ongoing work and remains supersedable until first audible output. Parent requires controlled races through the canonical facade/frontend, bounded decision state, existing permission gates and privacy-safe decision/latency traces. Task07 plan and source replay extraction are read-only preparation; later implementation has not begun.

Read-only Live preparation found a committed-source mismatch for metadata-only delegation and broad CLI permissions incompatible with speculative actions. Parent accepted Decision22 and revised Tasks11/12: explicit source-snapshot advisory-job provenance, enforced restricted analysis profile, upstream action admission and durable correlation. Local CLI help was inspected; no inference/provider session was launched. This clarification preserves existing authorized-work permissions and the locked no-irreversible-partials rule.

Parent accepted06 after 567 expanded tests passed (22.07s), including independent duplicate/deadline findings and a parent-reproduced Task05 EOF-before-close-ACK defect. All repaired with persistent tests. Synthetic preambles6→2, both long waits retained; real RuntimeJournal inspected in tests. Documentation reviewed, including correction of failure channel and future-slice ownership labels. No commits.

## Slice 07 — accepted

Two disjoint implementation responsibilities within this slice: native audio lifecycle/interruption, and canonical audio-part identity/completion manifest. They must agree the narrow interface before coding integration. Parent enforces checked device drain, urgent control/capture independence, explicit pending native ownership and all-parts proof before heard-text confirmation. Plans: `07-implementation-plan.md`, `device-playback-completion-plan.md`; no billable provider tests are authorized by these synthetic gates.

Interface agreed. Parent reproduced double drain/stale cached proof and concurrent Stop publishing background before provider close; native drain coalescing/cache correction independently rerun successfully. Canonical peer review found post-freeze inventory/text contradictions; multipart truncation must follow the part actually playing. Findings and pending evidence tracked in `review-07.md`; no acceptance yet.

Read-only08 preparation accepted into Task08 and Decision23: the scheduler already has priority ordering, but needs source-aware late-arrival and first-write freshness. Ordinary unspoken backend summaries currently disappear on Core restart; a minimal separate Core outcome projection is required before deferring their speech. This does not move Task11's executor ownership or promote outcome data to heard history.

Parent accepted07 after final release2205 passed,4 skipped (252.11s), all release checks green. First release's five legacy fixture failures were corrected without relaxing safety/telemetry assertions. Additional slow native-start admission race repaired and tested. Root/peer findings, exact gates, device/manifest limitations and true-chain blocked-control QA are in `review-07.md`, `07-runtime-device-evidence.md`, `evidence07-canonical.md` and `review-07-canonical-findings.md`.

## Slice 08 — accepted

Two disjoint owners: existing speech scheduler/domain presentation contract and Core source/outcome persistence. Agree minimal source/chunk/retention interface before integration. Reuse current scheduler, actual intent-order bookkeeping, atomic output admission and checked device completion. Preserve results independently of speech; no fabricated heard turn, job or global-revision freshness rule. Parent requires late-arrival/first-write races, bounded inspectable queue, actual multichunk path and unspoken-outcome retrieval after Core restart. Task09 preparation remains read-only.

Accepted after parent release2294 passed,4 skipped (242.19s), all guards green. Actual multichunk composition and independent outcome restart tests passed. Parent/peer reproduced and repaired first-write, reconnect/Stop, work-generation and concurrent-provenance defects. First release21 failures were migrated fixtures plus a duplicate expiry emission exposed during repair; original interruption/history assertions were preserved. Evidence: `review-08.md`, `08-core-outcomes.md`, `08-implementation-evidence.md`. No commits or live acoustic claims.

## Slice 09 — in progress

Core/frontend contract owner implements a small advisory hint request/value/result, one asynchronous analysis port, deterministic synchronous consumer and controlled fake. Reuse final08 sources and canonical user records; provisional B has no invented Core origin, while committed A can remain selected context. Parent approved the proposed interface before coding. No Luna call, new worker/queue, job dispatch, frontend control or ledger mutation in this slice. Task10 owns actual parallel model composition and budgets.

## Slice 09 — accepted

The provider-neutral hint contract, strict JSON codec, one-request consumer and
bounded controlled fake are accepted. Independent QA reproduced an oversized
integer escaping as OverflowError; parent review found an untyped selected
context role. Both were repaired with permanent tests. Independent QA reports
59 passing tests; the parent dependent-layer gate reports 284 passed in 6.70s,
warnings as errors, and diff check is clean. Task06/08 keep policy/output
authority. No provider session or production Luna composition was claimed.

## Slice 10 — in progress

Task10 begins with separate reviews of the actual conversational composition
seam and the Luna Responses adapter. New Simple and Front Brain modes need a
direct conversational response path after local admission; legacy
`continuous_brain` cannot be relabelled because it submits substantive turns to
the strong backend and speaks results verbatim. The sidecar remains parallel,
bounded and optional, with one canonical event-reader fan-out.

## Slice 10 — accepted

Explicit Simple and Front Brain now use the same admitted direct Realtime
conversation path; Front Brain adds bounded Luna analysis in parallel without
speech or work authority. Confirmed role data stays outside instructions, exact
provider items and checked device drain preserve conversation truth, and saved
compatibility modes retain their prior meaning. Canonical Core order is durable
across HTTP reordering, snapshot eviction and restart. Independent Luna,
composition and Core reviews have no open findings. Parent gates: 428 direct
composition tests, 58 Luna/sidecar tests and final release **2595 passed,
4 skipped in 294.40s**, all release checks green. Evidence: `review-10.md` and
the linked Task10 implementation/reviewer reports. No live or hardware claim.

## Slice 11 — in progress

Task11 starts from the existing durable `JobService`, not the shared
conversational ask route. The slice must add typed submit/status/cancel ingress,
immutable source provenance, durable state/result events and a registered worker
with its own CLI instance/process ownership. Speculative Codex remains
unavailable under Decision22 because a complete context-only capability profile
was not verified. Already admitted work retains configured permissions; frontend
stop or replacement must not own job lifetime or automatically seize speech.

### Task03R — global collection regression found

A parent whole-suite collection check after the focused gate found six `ModuleNotFoundError: conftest` failures (1950 tests otherwise collected). Task03's new `tests/__init__.py` changes the module namespace for legacy helper imports. Task03 is reopened until repaired. An isolated agent owns the six affected test imports and will run collection plus their tests. Task04 may continue independent state work, but cannot pass its gate or advance to Task05 until 03R is green. No production behavior or expected assertions should change in this repair.

03R resolved: six imports now target `tests.conftest`; no production/assertion changes. Whole-suite collection: 1992 tests, zero errors (1.82s). Affected modules: 42 passed (0.68s); parent independently reran the same six modules successfully. Evidence in `review-03R.md`. Task03 gate restored.

## Backend preparation — reviewed

`nonblocking-backend-integration-notes.md` identifies JobService as the durable authority but missing generic ingress/agent worker. Corrected Codex CLI description in code map. Decision20 and Task11 now specify reuse with an independently owned executor, existing permissions, targeted process cleanup and concurrency-safe acceptance; observational tracking alone is not implementation. No jobs launched.

## Slice 11 — accepted

Task11 now extends the existing Core JobService with atomic admitted-source
acceptance, typed status/progress/result/cancel state and one independently owned
CLI wrapper per executing job. Caller cancellation, transient/permanent SQLite
failures, delayed native cleanup and shutdown retries retain ownership and exact
results. Simple/Front Brain expose a no-argument, lineage-checked delegation tool;
only its controller may enqueue a source/job-bound acceptance ACK through the
existing scheduler, and terminal jobs stay silent. Speculative analysis remains
explicitly unavailable with immutable advisory provenance. Independent QA has no
open finding. Parent release: **2700 passed, 4 skipped in 320.97 s**; all release
checks green. Evidence: `review-11.md`, `11-core-back-brain-evidence.md` and
`11-runtime-implementation-evidence.md`. No inference, real agent CLI or hardware
acoustic claim.

## Slice 12 — in progress

Task12 starts only after Task11 acceptance. First gate is the current official
GPT-Live API contract: session transport, client delegation events, transcript
and usage evidence, quiet/spoken update semantics and close behavior. Provider
wire types remain inside a new adapter; speculative delegation cannot fabricate
a commit or inherit admitted-work permissions.

## Slice 12 — accepted

Task12 adds the production `openai/gpt-live-1` client-delegated frontend, one
provider reader, canonical provisional transcript/audio/usage evidence and a
bounded controller over durable restricted-Claude speculative jobs. Independent
review reproduced and repaired stale progress/result injection, false append
presentation, delegation rearming, false stopped state, late playback after
barge-in and an orphaned late startup after caller cancellation. Generated text
never becomes heard text without device evidence; the Live incarnation remains
muted after interruption because the provider exposes no safe resume boundary.

Parent targeted gates: 376 passed before final repairs, then 76 passed/3 skipped
for connect cleanup, usage diagnostics and the dedicated opt-in smoke. Final
release: **2765 passed,5 skipped in299.86s**, all release checks green. The GPT-
Live smoke exists behind `JARVIS_LIVE_GPT_LIVE=1` plus credentials and was not
executed; no paid provider, acoustic or billing claim. Evidence: `review-12.md`,
`12-implementation-evidence.md`, `12d-lifecycle-playback-evidence.md` and
`10-openai-api-notes.md`.

## Slice 13 — in progress

Task13 begins after Task12 acceptance. It owns the durable single-session lease,
heartbeat/epoch, truthful idle and stop states, process-crash recovery, orphan
reaper and usage/cost reconciliation. A new activation must remain fenced while
an earlier provider session is uncertain.

### Slice 13A — accepted foundation

Core now owns a durable, globally unique Live lease with strict state, owner
epoch/revision fencing, provider-start marker, terminal evidence and a durable
last-operation receipt for exact retries after a lost acknowledgement. SQLite
reads fail closed when indexed columns disagree with the canonical record;
client clocks and malformed JSON cannot influence expiry or release the slot.
Cleanup and late provider-ID binding remain available while shutdown blocks new
admission. Provider-confirmed closure requires matching `session.closed`
identity and finite final `usage.seconds`; absent proof remains unresolved.

Independent reviewer gate: **136 passed**. Parent compatibility gate:
**179 passed in 21.66 s**, warnings as errors; diff check clean. No P1/P2 remains
in 13A. The full-history scan on current/reserve is recorded as a future storage
optimization. Provider attachment, watchdog execution, idle policy and runtime
wiring remain in 13B/13C.

### Slice 13B — accepted recovery boundary

Added the documented known-ID sideband attach-and-close adapter and a Core-owned
watchdog. The adapter installs its reader before the sole `session.close`,
persists a strict matching `session.closed` receipt before transport cleanup,
and treats every ambiguous transport/provider outcome as unresolved. The reaper
claims only expired/uncertain ownership, renews its lease, applies bounded
backoff, and retains a terminal receipt across pre/post-commit SQLite failures
without issuing a second close. Shutdown uses one bounded budget and preserves
existing Core cleanup guarantees.

Independent final gate: **194 passed in 13.26 s**. Parent focused gate:
**168 passed in 11.70 s**, warnings as errors; diff check clean. No P1/P2 remains
in 13B. No provider was contacted. Production credential/composition wiring,
primary ownership and semantic idle remain explicitly pending in 13C.

### Slice 13C — accepted primary and semantic-idle integration

The production Live facade now follows the durable reserve/mark/bind/ACTIVE
order, renews and fences its primary lease, persists strict cumulative/final
usage evidence and requests provider close urgently even when Core persistence
is slow. Shutdown, fatal error, idle and the future switch hook use distinct
reasons. Core composes the sideband closer without opening a connection.

Semantic idle requires recent classified microphone evidence, no active local
speech, a known output device, checked native buffer drainage and no bounded
immediate continuation. A late drain is reconciled only for the same audio
epochs and PCM generation. Independent review also repaired failed-start
heartbeat leakage, stale-primary receipt loss, UNKNOWN hot polling and a
cross-provider Realtime double-drain.

Reviewer gate: **171 passed**. Parent focused gate: **232 passed**. Final parent
release: **2937 passed, 5 skipped in 327.32 s**, all release checks green. No
provider or hardware was contacted. Evidence: `review-13.md`,
`13a-lifecycle-lease-evidence.md`, `13b-sideband-reaper-evidence.md` and
`13c-primary-runtime-evidence.md`.

## Slice 14 — in progress

Task14 begins after Task13 acceptance. It owns the architecture-first Settings
projection and persistence for Simple, Front Brain and Duplex, including
capability-derived role choices, preserved legacy compatibility and explicit
unavailable reasons. Prompt editing, Live active controls and hot switching
remain Tasks15–17.

### Slice 14 — accepted

Settings now selects Simple, Front Brain or Duplex first and renders exact role
fields from the capability registry. Explicit selections are validated and
stored atomically; an unchanged compatibility projection writes no canonical
namespace and continues to inherit its legacy/environment sources. Unsupported
or unavailable selections remain inspectable with a reason, and malformed
optional provider-cache data cannot take down the Settings endpoint.

Independent review caught and closed inconsistent option metadata, same-mode
default substitution, corrupt-cache failure paths and a missing rejection trace.
Parent focused gate: **346 passed**; final Task14 probes: **59 passed**. Final
release: **2996 passed, 5 skipped in 332.31 s**, all release checks green. No
provider or hardware was contacted. Evidence: `review-14.md` and
`14-implementation-evidence.md`.

## Slice 15 — in progress

Task15 begins after Task14 acceptance. It owns the registry of actual
JARVIS-controlled prompt layers, structured inspection, versioned scoped
overrides, reset/conflict behavior and truthful next-session versus acknowledged
application status. Provider-internal instructions and Task16/17 controls remain
outside this slice.

### Slice 15A — accepted foundation

The typed registry now describes 24 JARVIS-controlled layers and 14 actual
composition programs with stable provenance, applicability, channel operations,
editability and deterministic static/render fingerprints. Versioned overrides
are bounded, atomically persisted, conflict-aware and preserve unrelated or
inactive values. Dynamic data, tool schemas and runtime invariants remain
read-only; persistence reports `saved_only` and never implies provider delivery.

Independent prompt/override review has no open P1/P2. Parent prompt gate:
**51 passed**; broadened compatibility gate: **333 passed**; compilation and
diff checks clean. Evidence: `15a-prompt-registry-evidence.md`. Actual send-site
wiring and Settings inspection/editing remain in 15B/15C, so Task15 stays open.

### Slice 15 — accepted

Task15 now resolves 24 JARVIS-controlled layers through 14 typed programs and
uses those resolutions at Realtime, Gemini, Luna, GPT-Live and Claude/Codex
send boundaries. Settings exposes only programs relevant to the saved voice
architecture and backend, with ordered provenance, channel-specific effective
previews and atomic edit/reset. Dynamic data, tools, schemas and runtime
invariants remain read-only; provider-internal prompts are explicitly
unavailable. Saved, sent, acknowledged and resumed-session states are not
conflated, and normal telemetry stores IDs/revisions/fingerprints without text.

The first release run found five regressions in Luna dynamic-size handling and
legacy agent doubles; both causes were repaired and their direct 29-test gate
passed. Final release: **3054 passed, 5 skipped in 348.03 s**, all checks green.
No provider, billable session or hardware was contacted. Evidence:
`review-15.md`, `15a-prompt-registry-evidence.md`,
`15-implementation-evidence.md`, and updated `06-settings-and-prompts.md`.

## Slice 16 — accepted

The Control Center now keeps every unresolved GPT-Live lifecycle state in a
global high-contrast banner with authoritative elapsed time, semantic-idle
context and a Stop button outside Settings. Stop requests are atomic,
session-bound and idempotently consumed by Voice; their receipts never stand in
for Core's strict terminal evidence. Unknown closure, stale reads and Core
unavailability remain visibly uncertain, while a successful empty Core read is
the only condition that hides the banner.

Provider usage is labelled directly. Monetary estimates require complete,
matching, timezone-stamped pricing metadata and always expose their basis and
source; no price is embedded. Focused gate: **180 passed**. Broad Live/Control
Center gate: **500 passed, 2442 deselected**. Final release: **3062 passed,
5 skipped in 329.16 s**, all checks green. No provider, billable session or
hardware was contacted. Evidence: `review-16.md`,
`16-implementation-evidence.md`, and updated
`07-live-session-cost-safety.md`.

## Slice 17 — accepted

Architecture and model changes now follow an explicit cross-process state
machine. Voice snapshots Core conversation/work truth, stops the old frontend
with reason `switch`, and blocks on local or durable Live uncertainty. Once
terminal, it leaves a metadata-only handoff and exits cleanly; the supervisor
restarts Voice without spending crash budget. The new process retains the Core
conversation and re-fetches bounded actually-heard/user history plus active task
summaries. Core-owned work continues unchanged.

Settings reports pending/blocked/failed/applied phases. Replacement activation
traces source/target architecture and model plus prompt revision/fingerprint
evidence without text. The synthetic Simple -> Front Brain -> Duplex -> Simple
sequence and same-mode model restart pass. Focused gate: **170 passed**; broad
gate: **1123 passed, 1830 deselected**. The first release run caught an
incomplete Gemini compatibility target; its 63-test repair gate and final
release passed: **3075 passed, 5 skipped in 320.42 s**. No provider, billable
session or hardware was contacted. Evidence: `review-17.md`,
`17-implementation-evidence.md`, and the updated `02-architecture-spec.md`.

## Slice 18 — accepted

Task18 now records one versioned machine report and readable summary per
frontend session. The schema has identical latency and counter keys for Simple,
Front Brain and Duplex, retains raw samples, and keeps provider PCM receipt,
playback attempt, first successful native write and checked full drain as four
different boundaries. Existing six historical latency measures remain intact.

Reports join Voice and Core diagnostics through session/correlation provenance.
They include configuration and prompt fingerprints, Core-owned Live active
seconds, separate surface/analysis/backend usage, and only produce monetary
estimates from strict versioned pricing provenance matching the identity Core
actually observed. Partial writes freeze and retry the same report before a new
session can replace it.

Independent review finished with no open P0/P1/P2 after three adversarial
passes. Focused remediation: **95 passed**; expanded audio/admission/metrics and
Back Brain gate: **157 passed**; reviewer gate: **142 passed**. The final clean
release passed **3093 tests, 5 skipped in 331.34 s**. No provider, billable
session or hardware was contacted. Evidence: `review-18.md`,
`18-implementation-evidence.md`, and updated `08-benchmark-plan.md`.

## Slice 19 — in progress

The replay work is split into a strict bounded fixture/clock/driver layer and a
separate integration layer that invokes the production scheduler, bridge,
ledger and Core stack. Fixtures retain source line references and label each
fact as reported, derived or constructed; they do not copy historical prose,
raw audio, prompts or pricing. The driver only advances time and dispatches a
closed action vocabulary, leaving all policy decisions to production code.

### Slice 19 — accepted

Nine strict fixtures now replay every required September 11 failure class
through production policy seams and fake provider/audio/Core adapters. The
35.9-second acknowledgement is superseded before device release; later turns
remain admissible during 85.7-second work; heard/generated/intended divergence,
seven rejected noise candidates, interruptions, provider-cancel rejection,
missing terminal recovery and manual close all assert state, side effects and
real session-report metrics.

The independent review found no P0/P1 and identified two P2 gaps: the stall
counter was checked only as a raw event, and the requested command/provenance
guide and regression summary were missing. Both were repaired. Combined focused
gate: **144 passed**; independent replay gate: **53 passed**; final release:
**3146 passed, 5 skipped in 316.41 s**. No provider, billable session, network or
audio hardware was used. Evidence: `review-19.md`,
`19-implementation-evidence.md`, `19-replay-regression-summary.md`, and updated
`04-testing-and-quality.md`.

## Slice 20 — in progress

Task20 starts after Task19 acceptance. It owns a repeatable common-scenario
benchmark runner/report, deterministic cross-architecture evidence, migration
verification, provisional-default decision and final program report. Live
provider and hardware evidence will remain explicitly unavailable unless it is
separately authorized.

### Slice 20 — accepted

The frozen 14-scenario suite now binds exact ordered actions, parameters,
invariants and pytest selectors. Its CLI runs 16 allowlisted selectors expanding
to 26 production-seam cases before writing atomic reports. Architecture-neutral
policy evidence remains separate from per-mode evidence: Simple and Front Brain
each prove one common direct-question scenario, Duplex retains a separate
representative delegated E2E, and every unavailable scenario/metric stays
explicit. Compatibility migration is verified outside the comparison.

Independent review rejected two successive auto-oracles: constructed expected
states, then globally allowlisted tests reassigned across scenarios and modes.
Both were eliminated with execution-backed evidence and immutable per-role
mappings. Migration review also repaired compatibility sessions labelled as
`simple` and an uncaught invalid explicit configuration.

Real benchmark CLI: **26 passed**. Runner adversarial gate: **24 passed**.
Expanded Task20 gates: **144** and **174 passed**. Independent code gate:
**99 passed**. Final release: **3176 passed, 5 skipped in 333.76 s**, all release
checks green. No provider, billable session, external network or audio hardware
was used. Evidence: `review-20.md`, `20-implementation-evidence.md`,
`20-benchmark-results.md`, and the artifacts under `artifacts/task20-offline/`.

The evidence cannot rank live latency, quality or cost. Decision24 therefore
preserves the safe operational `legacy` default while keeping Simple, Front
Brain and Duplex explicitly switchable.

## Program completion — Task00 accepted

All Tasks 01–20 are complete. TODO state, decision log, benchmark plan/results,
open questions, per-slice reviews and the final implementation report now match
the verified implementation. The final release passed **3176 tests with 5
expected skips**. Remaining work is limited to the explicitly documented live
provider/device experiment and product decisions that require its evidence.
