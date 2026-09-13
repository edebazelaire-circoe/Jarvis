# Task08 parent review tracking

Accepted, 2026-09-12. Final parent release:2294 passed,4 skipped in242.19s; all release guards green. Scheduler/domain presentation and Core persistence/source owners agreed the shared interface before integration. Task07 baseline:2205 passed,4 skipped.

## Shared interface accepted before implementation

- `SpeechSource`: actual Core conversation turn/correlation, intent identity and durable per-conversation arrival epoch, exact `(work_id, source_correlation_id)` dependencies. An uncertain turn receives an origin but becomes current only through existing ordered promotion. Canonical voice IDs remain distinct.
- Source query/event projection: schema version1, conversation, nullable current source, exact invalidated dependencies (bound256), `source_complete`. Overflow preserves uncertainty instead of forgetting invalidations and rearming old output. Snapshot/global brain revision is not speech eligibility.
- `SpeechRequest`: optional source and durable outcome reference; at most16 exact contiguous text spans. Core authors paragraph boundaries through a neutral helper; the existing scheduler owns child/chain presentation identity, selection and first-write admission.
- Outcomes: Core-owned source/work/text/status/date and channel kind, independently persisted. Deterministic identity uses conversation/origin correlation/actual work or null/status/exact text, independent of notification channel. Same result from speech then completion joins; a different terminal text remains a separate version. A turn-level aggregate without work identity is not assigned to an invented work. Same-ID origin/text remain immutable; kind may advance to the more authoritative channel.
- Explicit selection creates a new candidate under current source while preserving the stored outcome's original source. No heard-history write, job execution or old candidate revival.
- Scheduler freshness is strict for all callers; missing fake capabilities or `canonical_history` must not silently select old behavior. Production legacy does not instantiate this scheduler, and unsupported continuous Gemini is already refused. Adapt fixtures to actual declarations/source contracts and keep positive behavior covered.

| Area | Required evidence |
|---|---|
| Source truth | Core turn identity, voice turn identity and correlation remain distinct. Originating intent/dependencies are stamped at acceptance, not at result receipt. Current speech survives unrelated global state changes. |
| Restart identity | Persisted old outcomes cannot accidentally match a new intent because an in-memory counter restarted. Unknown/legacy provenance stays explicit; no fabricated current source. |
| Result retention | Persist completed ordinary outcomes before publication through the existing repository boundary. Retrieve an unspoken result after Core restart without an assistant heard turn or synthetic Job. Duplicates do not replace immutable origin or create duplicate outcomes. |
| Freshness | Reevaluate at ingress, selection, after awaited registration/provider send and immediately before first device write. Old result arriving after new input remains available but its old speech is deferred. |
| Speech opportunity | Raw VAD/timeout is not admitted intent or proof of silence. Priority cannot bypass source invalidity or the interruption owner. Useful current answers still proceed. |
| Chunks | A real production path emits exact bounded semantic chunks; preserve spans/source and avoid naive decimal/abbreviation splitting. Replan at each boundary. |
| Interruption | Existing device/epoch evidence remains authoritative. Cancel/defer unstarted tails; never relabel a started write as unheard, replay the full interrupted answer or derive words from milliseconds. |
| Bounds and replay | Queue, deferred state, dedup, source watermarks and chunk metadata bounded. Saturation/gaps/switching do not resurrect stale candidates or delete durable outcomes. |
| Inspection | Queue/result projection is bounded and correlated, with stable eligibility/reason codes. Normal diagnostics do not add raw transcript content or another logging system. |
| Composition | Existing scheduler, Core event path, output admission and native drain actually use new contracts. No independent backend executor, sidecar or Live implementation in this slice. |

Required scenarios from reviewed preparation:29.1s/35.9s stale filler, late old result, retained background result during another topic and later explicit selection, unrelated revision, uncertain input versus admitted correction, selection/first-write races, interrupted multichunk tail, reconnect/gap/saturation, frontend switch and Core restart retention. Use controlled clocks/transport/device where needed; no live acoustic quality claim.

See `08-scheduler-review-plan.md` and Decision23. Task11 retains ownership of independent backend execution; Task09 may reuse the accepted source contract only after this gate.

## Initial implementation findings

- Existing Core `_cancelled_work` and `_spoken_works` use work ID alone. New exact dependency identity must prevent an old invalidation from affecting another source that reused that work ID.
- Paragraph splitting must preserve both LF and Windows CRLF spans exactly, without treating decimal points or abbreviations as sentence boundaries.
- A new8192-character `SpeechRequest` bound can reject a completed backend answer before Core sees it: `ControlCenterBrainBackend._settle_success` constructs the request before emitting COMPLETED/returning its result. Outcome storage permits65536. Separate whole-result/chain bounds from per-provider chunk bounds, or retain success before deferring oversized presentation. Exercise this actual adapter path; no truncation, result loss or false backend failure due solely to presentation constraints.

## Interim review evidence

Parent focused Core gate:47 passed in2.98s, with warnings as errors (`test_core_brain_outcomes.py`, `test_brain_outcome_protocol.py`, `test_voice_outcome_retention.py`). The independent integration tests use real Core HTTP and reopened SQLite, observe persistence at the publication boundary, and verify late-result origin plus explicit idempotent selection without Jobs/heard turns. This is not slice acceptance.

The reused-work finding was confirmed: late A control/terminal events could mutate a new B activation. The Core owner now compares durable source epochs, preserves the old public outcome before rejecting a stale mutation, and tests that a newer intention can still explicitly cancel an older active work. Historical cross-source result descriptions remain ambiguous; retain their data and defer their presentation instead of manufacturing a dependency. Task11 carries the follow-up for immutable Job/source links.

Pending scheduler review: a context query must not rearm candidates during a known stream gap before effective resubscription, and a query from an older gap cannot resolve a newer gap. Stop must own pending queries, timers and cancellation operations. Temporary raw VAD/owner candidates must remain distinct from admitted intent changes. Independent QA is reproducing these boundaries while the lead finishes the production chunk path.

## Reproduced findings and interim resolution

- Independent QA reproduced EOF rearming before effective reconnect, then Stop waiting for query cleanup while the still-active consumer/delivery accepted a new output. The lead fences admission and cancels execution before cleanup awaits, clears stream connectivity before closing, and uses the existing server subscription acknowledgement plus query generation. Seven persistent review tests pass, including raw VAD/Solo Owner rejection before and after a real device write.
- Parent reproduced concurrent outcome deduplication failing when the same text's work ownership changed between two first observations: `brain outcome identity conflict`. The Core service now rejoins the persisted winner only for the exact same content and Core origin, allowing solely unknown/known observation of the same dependency. The repository's conflict validation remains strict. No extra queue/worker/lock service. Parent-owned `test_brain_outcome_review_races.py` now passes.
- Long answers now separate65,536-character result/chain capacity from8,192-character provider chunks. Actual Control Center HTTP backend tests cover a long admissible two-paragraph result, an oversized single paragraph, and17 paragraphs. Success/result retention survives all three; presentation defers only when it cannot fit. LF and CRLF spans reconstruct exactly.
- The independent production composition test exercises `app._run_voice_v2` → Core HTTP/SQLite → scheduler → canonical frontend → bridge → native wrapper. Two paragraphs use distinct outputs and two checked drains; chunk2 waits while device1 remains buffered. Exact text, source and outcome survive through the canonical heard ledger. No COMPLETE was injected.

Parent interim gates:30 passed in1.93s (domain, scheduling policy, independent Stop/gap review and three first-write barriers);31 passed in2.64s (Core outcomes, parent concurrent-provenance reproduction and actual multichunk composition). Scope owners' broader focused gates are recorded in their handoffs. Same-source selected supersession and final release verification remain before acceptance.

## First release regression pass

Full `verify_release.py`, warnings as errors:21 failed,2272 passed,4 skipped in401.84s. Failures were13 cases in the historical async-conversation harness,7 scheduler cases in `test_v2_barge_in.py`, and1 selected-supersession case in `test_brain_delegation.py`. The first harnais lacked reserved-output methods and bypassed the guarded writer. Its migration now uses the real guarded writer around a controlled native stream, retaining original order/interruption/history assertions. It also exposed a real duplicate SPEECH_EXPIRED emission at Stop; the redundant trace was removed while preserving the uniqueness assertion. Owner gate76 passed in8.68s, including all16 harness scenarios. The two remaining test files have disjoint repair owners; final acceptance awaits their review and a complete release rerun.

## Final acceptance

The two remaining fixture migrations were reviewed:26 barge-in tests passed, preserving current-result positives and explicitly retaining stale results as deferred;25 delegation tests passed, including separate RESERVED/WRITE_STARTED cases and a uniquely correlated supersession assertion. No production compatibility bypass was added. Same-source selected supersession, delayed source reconciliation, query bounds and reserved output ID reuse also passed their focused gates.

Parent reran the complete release script with warnings as errors: **2294 passed,4 skipped in242.19s; Release verification passed.** The skips remain two opt-in provider tests, POSIX-only signals and unavailable symlinks. Diff whitespace check clean. No physical acoustic or live-provider quality claim, no commit. Task08 accepted; Task09 may begin using its final contracts.
