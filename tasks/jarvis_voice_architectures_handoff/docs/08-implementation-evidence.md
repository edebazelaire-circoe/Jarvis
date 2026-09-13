# Task08 — source-aware presentation

The production continuous-brain path still instantiates `SpeechScheduler` in
`PersistentVoiceRuntime`. Legacy mode does not instantiate this scheduler;
continuous Gemini remains unavailable. Every scheduler instance now requires
explicit Core source authority and the reserved-output capability. Missing
authority or capability defers presentation; test doubles exercise the same
policy and do not bypass it through `canonical_history`.

## Contracts and ownership

`domain/speech_presentation.py` contains `SpeechSource`, `SpeechDependency`,
`SpeechTextSpan`, `SpeechChunk`, `SpeechCandidateStatus` and `BackendOutcome`.
Sources use actual Core turn IDs, originating correlation, durable intent epoch
and exact `(work_id, source_correlation_id)` dependencies. They never compare
against the general working-state revision. Current source and original source
are distinct. Details of durable source allocation, outcome identity, queries
and explicit later selection are in [Core outcomes](08-core-outcomes.md).

`SpeechRequest` adds optional `source`, `outcome_id` and exact `chunks`. Legacy
payloads decode with unknown source and cannot become eligible by implication.
The request/chain text bound is 65,536 characters; each provider chunk is at most
8,192. `semantic_text_spans` uses only explicit LF/CRLF paragraph boundaries,
keeps separators in their original spans and reconstructs the exact text.
Decimals, abbreviations and sentence periods do not split a paragraph. At most
16 nonempty contiguous chunks are accepted. An oversized paragraph or more than
16 parts makes presentation unavailable; it never truncates the stored result.

Core persists a completed result before considering its presentation. The real
ControlCenter adapter emits COMPLETED before constructing result speech. Tests
run that HTTP adapter through BrainService for an oversized single paragraph,
a valid long two-paragraph chain, and a 17-paragraph result. All retain exact
text across repository reopen, remain successful backend work and create no
assistant heard turn merely by being available.

The scheduler expands spans into child requests with deterministic identities
derived from parent request ID, chunk index and exact span. Each child retains
source, priority, expiry, work reference and outcome ID. A chain ID is not a
durable outcome ID. Explicit re-expression creates a new Core request/chain;
neither retry nor frontend restart reactivates an already attempted child ID.

## Selection and cancellation

Eligibility precedes priority/FIFO selection. Unknown source/state/capability
defers; expired text expires; revoked exact dependencies supersede; an old
intent supersedes transient wording and defers durable wording. Available
outcomes stay owned by Core. A current result survives ordinary non-intent
state revisions and invalidations for an older generation of a reused work ID.
Directed supersession applies only between eligible candidates with the same
exact source, including when delayed source reconciliation makes them eligible.

The current child is reserved before any Core registration or provider send
await. `ReservedSpeechOutput.speak_reserved` carries the exact local output ID
through facade, canonical command and low-level response metadata. The existing
Task06 `OutputAdmission` is attached to that ID, checked by the actual device
writer after its lock/lazy-start waits. New intent, exact dependency revocation,
supersession or expiry can invalidate only an output whose native write has not
begun. Cancellation is owned, deduplicated and directed at the exact response;
it never cancels the backend or the next useful response.

Once a native write starts, freshness does not rewrite or retract heard audio.
The existing bridge owns interruption and Task07 owns checked device drain.
Raw VAD/Solo Owner CANDIDATE holds selection of queued speech; it is not a new
intent and does not invalidate an already reserved answer. Rejection releases
that selection hold without deleting the answer. Confirmed interruption retires
the chain tails. The eight-second hold timeout is not proof of silence and
cannot force selection while user activity remains asserted.

The delivery loop replans after each child terminal and after interruption.
The production multichunk test feeds provider `response.done` while device stop
is still waiting for buffered PCM consumption: child two remains absent until
the first real wrapper drain completes. Generated text remains separate from
heard text; only the canonical ledger projects the Task07 evidence. No partial
word alignment is inferred. A provider terminal without a complete matching
manifest still proves no heard text. Controlled device buffers test ownership
and ordering, not physical acoustic quality.

## Gaps, bounds and lifecycle

`LocalCoreClient.events(on_connected=...)` announces the existing authenticated
server `connected` acknowledgement. Source query runs only after that actual
subscription barrier. EOF marks source incomplete before closing the old
iterator; no query can rearm speech during the reconnect delay. Each query is
tagged by a local reconciliation generation, so a late older success cannot
clear a newer gap. This is not a claim of globally atomic network freshness at
the physical write instant.

Bounds per scheduler incarnation: 64 pending, 64 deferred, 256 diagnostic
candidates, 4,096 seen speech identities/chain metadata, 4,096 exact dependency
tombstones and at most eight owned reconciliation queries. Terminal diagnostic
records may be evicted; dedup identities are never evicted into replay. Capacity
refusals are explicit and never remove a Core outcome. Core snapshots cap
invalidations at 256 and set `source_complete=false` on overflow. Low-level
output identities also retain 4,096 tombstones independently of the 32 detailed
provider mappings, preventing reserved-ID reuse after mapping eviction.

Stop closes admission synchronously and cancels consumer/delivery tasks before
waiting for query cleanup. Late source/speech events cannot reserve output.
All query, cancellation and timer owners are retained through cleanup. A
stopped scheduler requires a new frontend incarnation; its queues are not an
automatic replay source.

## Observability and validation

`presentation_snapshot()` exposes bounded source, status, reason, age, priority,
work/outcome and exact chunk-span metadata. `voice.speech.presentation_decided`
records the same decision identities and age without raw transcript, result
text, PCM or credentials. Existing queued/started/completed/expired/superseded
channels remain, with neutral messages and correlation fields. Expected
deferral is an ordinary decision, not a provider error. Start/cancel/query
failures record stable reasons and exception type. Existing RuntimeJournal is
the only logging system; no temporary probes or hidden logging memory.

Permanent evidence:

- `test_speech_presentation.py`: strict schema, LF/CRLF exact reconstruction,
  decimals, long chains, chunk/result/count bounds.
- `test_speech_presentation_scheduler.py`: synthetic 29.1/35.9-second stale
  wording, unknown-source refusal, ordinary revision positive, late reused
  work, multichunk/tails, same-source start race and bounded queues/queries.
- `test_speech_presentation_race.py`: actual facade/frontend/Core ledger and
  guarded writer; new intent during Core registration, response creation and
  device-lock wait produces zero writes/no heard text, successor untouched.
- Independent `test_speech_scheduler_review_races.py`: EOF/reconnect ACK,
  cancellation-resistant query and late Stop events, raw VAD/Solo Owner reject
  before/after a real guarded write.
- Independent `test_speech_multichunk_composition.py`: real app factory,
  authenticated Core HTTP/SQLite, provider facade/adapter, bridge, wrapper and
  controlled native buffer. Exact two-part source/outcome lineage, sequential
  checked drains and Core confirmed history; no injected COMPLETE evidence.
- `test_core_brain_outcomes.py`, `test_brain_outcome_review_races.py` and existing migration
  tests: durable outcomes, exact source generation, long real-adapter result,
  failure/restart and explicit later selection.

Stable presentation gate, 2026-09-12:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_v2_speech_scheduler.py tests/unit/test_speech_presentation_scheduler.py tests/integration/test_speech_multichunk_composition.py tests/integration/test_speech_presentation_race.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

**48 passed in 3.94 s**, after the last source-query supersession fix. Earlier
domain/presentation gate: **20 passed in 0.78 s**. The additional same-source,
query-capacity, reservation-ID and Stop race gate: **21 passed in 1.98 s**.
Independent composition/Stop/raw-VAD/retention gate: **10 passed in 1.83 s**.
The broader in-progress gate had 326 passing tests and one supersession race
exposed by context reconciliation; that logic is fixed and covered by the final 48.
Final parent release gate: **2294 passed, 4 skipped in 242.19 s**; all release
architecture and privacy guards passed. Task08 is accepted. The first full
run exposed historical fixture incompatibilities and duplicate expiry
telemetry; their repairs and preserved behavioral assertions are recorded in
`review-08.md`. No live provider session or physical device benchmark was run.
