# Slice08 scheduler review plan

Read-only preparation, 2026-09-12, while Task07 is in progress. No code, slice status or TASK.md changed; no tests or provider sessions run. Re-read Task07's final interfaces before implementation because playback ownership is changing concurrently.

## Outcome and current behavior

Separate the lifetime of a backend result from permission to voice its current wording. A result can remain available after its original speech candidate becomes irrelevant. Freshness here can be deterministic dependency/intent policy; it does not require a new semantic model, text-similarity service or Task10 sidecar.

The current `SpeechScheduler` is already priority ordered, with FIFO only for equal priorities. It has transient TTL, directed supersession, explicit Core work invalidation, one delivery owner, and no replay on mute. Extend these seams rather than replacing them with a second queue.

| Existing path | Current behavior / remaining gap |
|---|---|
| `_enqueue`, `_pop_next` | Deduplicate speech IDs, honor expiry, compare supersession keys/work and choose `ordering_key`. No explicit source intent revision or semantic chunk chain. Pending list and ordinary speech-ID retention are unbounded. |
| `brain.turn.accepted` | Drops already queued ACK/PROGRESS. A late old candidate arriving afterwards can enter the queue again because its source epoch is not checked. |
| `brain.intent.revised` | Drops queued speech for superseded/cancelled work, including results. No retained invalidation watermark prevents later arrival for that old source. |
| Core `_take_stale_replies` | Identifies work whose nontransient speech had already been emitted when the new intent arrived. It does not identify an old turn's result that has not yet arrived. |
| `_deliver_pending` | Correctly waits for silence before selecting. A further await inside `session.speak` leaves a selection-to-first-write race. The current façade awaits Core speech registration before sending generation. |
| `_note_revision`, stream reconnect | Drops transient speech on a gap, but leaves durable-result candidates eligible despite potentially missing intent invalidation. |
| `stop` | Expires local queue without canceling Core work. This is the required separation to preserve. |

Sources: `jarvis/runtime/speech_scheduler.py`, `realtime_frontend_session.py`, `output_admission.py`; `jarvis/core/brain_service.py`; [Task08](../tasks/08-freshness-aware-speech-scheduler/TASK.md), [architecture](02-architecture-spec.md), [reflex policy](05-reflex-optimization.md).

## Available provenance and missing metadata

| Evidence | Usable meaning |
|---|---|
| `SpeechRequest.id`, conversation/correlation/work IDs, provenance | Existing speech identity and origin links. `work_id` is not necessarily a durable `Job.id`. |
| Request kind/priority/created_at/expires_at/supersedes_key | Existing display policy; priority is not a relevance override. Expiry does not imply task/result deletion. |
| `BrainTurnAcceptance.turn_id`, correlation and revision | Accepted Core record plus origin correlation. An uncertain accepted turn may repeat the existing revision without changing intent. |
| `BrainIntentRevision` | Core-owned retained/superseded/cancelled work partition, previous/current revision. Retained work remains active; this does not compel immediate announcement in an unrelated conversation. |
| `BrainWorkingState.revision` | Changes for intent, facts, questions and work updates. Not every increment invalidates speech. |
| Canonical user record revision, turn order, speech/task records | Committed/provisional distinction, source dependencies and independent heard evidence. Canonical snapshot revision and brain revision are different counters. |
| Façade `_source_turns` | Runtime mapping from source correlation to canonical voice turn. Do not equate Core persisted turn IDs, voice turn IDs and correlation IDs by string reuse. |
| `Job.result`, `VoiceTaskRecord.result` | Respectively durable job data and a bounded canonical reference/projection; neither starts speech automatically. |

Minimal proposed candidate envelope: speech/candidate ID, optional chunk-chain ID/index, exact source reference (turn/correlation plus work/job where known), originating intent epoch/dependency revision, relevance policy, request priority/expiry/supersession key, local selection state and stable reason code. Source fields must be stamped by Core/controller, not inferred from a wall-clock timestamp or the latest turn at candidate receipt. Missing metadata is explicit legacy/unknown provenance, not fabricated current intent.

Keep `available`, `eligible`, `selected`, `started`, `deferred`, `superseded`, `expired` presentation states distinct from backend job status and canonical playback evidence. New admission may create a fresh speech candidate for an existing result; it does not create a new result or revive the old speech ID.

## Bounded implementation sequence

1. **Establish the result-retention seam first.** JobService persists `Job.result` before `job.completed`; reuse that source. A separate gap exists for conversational backend summaries: Core `_settle` only adds them to in-memory `known_public_facts`. `rehydrate` explicitly documents loss after a Core restart when the result was never heard. Do not claim crash durability from this state, WorkStateStore or a scheduler cache. If Slice08's durable availability includes these ordinary results, add the smallest typed Core-owned outcome persistence/projection before discarding their only speech representation, reusing the SQLite repository boundary. Keep result records separate from heard turns; do not fabricate a Job or assistant history to store them. Task11 still owns the independent worker/ingress, not this presentation queue.
2. **Add source-aware eligibility at ingress and dequeue.** Track admitted intent change independently of global state revision. Retain bounded supersession/cancellation watermarks for exact source/work generations so delayed arrivals cannot resurrect stale speech. A source-less/legacy result may be retained as available but cannot be asserted current merely because it arrived recently. An explicit current selection can make it eligible later.
3. **Choose among eligible candidates only.** Reuse priority, with current-intent relevance before FIFO ties. ACK/PROGRESS expire or disappear when their source is invalidated; late old results/questions/errors become deferred when no longer relevant. Explicit Core supersession invalidates the old wording. A retained background job result can become eligible at an authorized current selection or designated notification opportunity; do not interrupt unrelated speech solely because a task completed. Priority never overrides source invalidity or the existing interruption owner.
4. **Use minimum real chunks.** Prefer explicit Core-authored semantic chunks, preserving exact text and provenance. Existing unsplit requests can remain one atomic chunk. Any deterministic sentence/paragraph splitting must retain exact spans, not paraphrase, and must avoid turning decimal numbers/abbreviations into broken chunks. Bound chain length/text and surface overflow. Do not hard-code a large “split by every period” rewrite or add an LLM splitter. Test at least one multi-chunk production path so chunk support is actually used.
5. **Fence selection through first device write.** Recheck eligibility after awaits and reserve an output-specific admission token before provider send. Reuse/generalize Task06's `OutputAdmission` where appropriate; current use is reflex-specific. Source invalidation before `begin_write` denies the stale candidate and cancels its exact generation safely. Once write starts, do not claim it was unheard; Task07 interruption/drain/epoch rules own the active output. Never cancel a newer response as a fallback.
6. **Replan at each chunk boundary and interruption.** Preserve heard prefix, mark interrupted/unknown evidence through the canonical ledger, cancel/defer unstarted sibling tails and select against the newest admitted context. Never replay the whole old answer or calculate a word offset from milliseconds. A follow-up request can select retained result data into a new candidate.
7. **Bound and expose state.** Cap pending/deferred candidates, retained source watermarks, chain metadata and dedup entries; define saturation without evicting IDs in a way that resurrects stale output. Keep durable result storage independent of these bounds. Expose a content-bounded snapshot with source, age, eligibility/status and reason. On event gaps, defer candidates whose relevance is unknown and obtain current Core state; never replay the missing speech stream. Persisted facts are not sufficient to reconstruct exact lost invalidation—remain deferred if current state cannot reconcile it.

## Policy edges to settle in the review

- A raw VAD start can hold new output but is not committed intent, owner admission or permission to cancel work. Use the existing addressing/owner gate and Task07 interruption evidence. An uncertain accepted Core turn must not automatically advance the authoritative intent epoch.
- The current eight-second user-speech hold can time out into selection. Re-evaluate actual eligibility after that wait; timeout is not proof the user stopped speaking. Bound application waits without promising a speech opportunity while activity evidence remains unresolved.
- Old tests/comments say results/questions are durable and therefore spoken unless Core names their work. Preserve the truth/retention rule, but update the implication that truth must immediately play. This is the intentional behavioral change of the new handoff's Decision08, not a reason to delete Core data.
- TTL protects time-sensitive wording; it is not a semantic relevance classifier. Keep explicit backend deadlines. Do not assign blanket short expiry to results or solve the 29–36s examples by sleeping or lowering every timeout.
- Frontend replacement clears executable presentation state. Available Core outcomes survive independently and need a fresh selection; dedup must not be reset into automatic replay. Live advisory work later needs the distinct provenance described in [Live authority preparation](live-delegation-authority-plan.md); Slice08 must not invent committed turns for it.

## Focused evidence required

Reuse `tests/unit/test_v2_speech_scheduler.py` FakeClock, RecordingJournal, FakeCore, held output and controlled finish helpers; they already cover priority, TTL, supersession, revision gaps, reconnect and stop. Preserve their single-output and uncertainty assertions. Extend Core tests in `test_v2_brain_orchestrator.py` / `tests/integration/test_v2_brain_protocol.py`, canonical state tests, and the actual factory path in `tests/integration/test_voice_production_composition.py`.

| Scenario | Required assertion |
|---|---|
| Filler waits 29.1s or 35.9s, then newer admitted input | No later stale speech; inspect source/reason, not just final queue length. |
| Old ACK/result arrives after the new turn, including reordered revision/speech events | Old filler rejected; result available but deferred; no resurrection after duplicate/reconnect. |
| Result for retained background work arrives during another topic | Fact stays queryable; no forced interruption; explicit later request yields a new relevant candidate. |
| Current result plus unrelated state revision/work update | Useful answer remains eligible; no global-revision-equality false rejection. |
| Uncertain/ambient activity versus admitted correction | Temporary hold differs from source invalidation; no unauthorized turn commit or job cancellation. |
| Pause after selection before provider send / first write | New intent invalidates exact reserved output; successor untouched; known zero-write stays unspoken. |
| Three-chunk answer interrupted in chunk one | Heard evidence retained; tails canceled/deferred; no full replay; useful new answer can proceed. |
| Core event gap, queue saturation, duplicate terminal event | Explicit bounded uncertainty; no lost durable result or hidden duplicate speech. |
| Mute/restart frontend with completed result | Stored result retained, queue not replayed. If crash durability is claimed, recreate Core/repository and query the unspoken outcome too. |
| Provider generation complete while device buffers | No next chunk over live playback; real Task07 drain/epoch evidence, not injected COMPLETE, releases output. |

No full Task19 replay or acoustic benchmark is needed for this bounded review. Use exact source delays only as deterministic test scenarios; [fixture extraction notes](replay-fixture-extraction-notes.md) distinguish reconstruction from captured timing. Final gate should show production queue/provenance integration, actual result retention, race safety through first write and Task06/07 regressions, without claiming that passing policy fakes proves acoustic quality.
