# Task09 hint contract — review preparation

Read-only preparation, 2026-09-12. No implementation, task/status change or provider session. Task08 is not assumed accepted; its final source/freshness types must be inspected before Task09 coding. Decisions22/23 remain authoritative.

## Smallest useful boundary

A Front Brain hint is an optional interpretation of a particular application-selected input snapshot. It can advise the existing controller; it cannot submit work, invoke tools, resolve confirmations, commit transcripts, change heard history or call the frontend. An absent hint means ordinary conversation continues. A model-generated WAIT is not a global mute or a prerequisite for answering.

Reuse existing contracts rather than reproducing state:

| Existing contract | Reuse / limitation |
|---|---|
| `FrontBrainVoiceConfig` | Already selects reflex and analysis `VoiceModelRef`, speculative-delta enablement and reasoning effort. No second model-selection config. |
| `VoiceCorrelation` | Exact frontend incarnation and optional known turn/task/provider identities. Unknown stays `None`; correlation is not permission. |
| `VoiceConversationSnapshot` / `VoiceUserRecord` | Read-only canonical evidence, transcript revision and committed/source flag. Do not pass the whole snapshot or let hints replace it. |
| `VoiceContext` | Bounded selected history. Heard assistant words remain distinct from generated/intended text; character bounds do not imply token bounds. |
| `ReflexAction` / `ReflexDecision` | Existing WAIT/BACKCHANNEL/SPEAK/PREAMBLE/DELEGATE vocabulary. Reuse it for a **suggestion**, preserving Task06's actual gate. |
| `SpeechPriority` | Reusable bounded urgency suggestion if a consumer needs it; no authorization to interrupt or outrank stale-source rejection. |
| Task08 source/dependency/eligibility contract | Reuse after acceptance. Do not independently introduce a rival intent epoch, result store, candidate queue or output admission token. |

Sources: `jarvis/domain/voice_architecture.py`, `voice_frontend.py`, `voice_state.py`, `reflex_policy.py`, `v2.py`; [scheduler preparation](08-scheduler-review-plan.md), [reflex behavior](05-reflex-optimization.md).

## Proposed request and result

These are conceptual fields for review, not names of existing classes or a locked JSON schema.

**Request:** opaque application request ID; `VoiceCorrelation`; exact source transcript/group ID, revision and committed flag; bounded full current text; selected `VoiceContext`; references to relevant verified Core outcomes/work facts if needed; source snapshot revision as a watermark; application-owned analysis-admission scope; original request deadline. Reuse the accepted Task08 source reference for intent/dependency identity. Full current text per coalesced revision is simpler than asking another model to reconstruct arbitrary dropped deltas.

Task08 follow-through: a new provisional input may not yet have any Core `SpeechSource`. Keep that origin nullable and bind analysis to the actual canonical frontend/transcript revision. The previous committed intent A can be selected context for provisional B, but is not B's originating turn. Do not borrow A's turn/epoch or allocate a fictional committed B just to populate the hint request. An explicit input origin, when known, and a current-context dependency have different meanings.

**Hint value:** suggested `ReflexDecision`, optional short intent hypothesis, optional addressed-to-JARVIS confidence, optional overall confidence, optional likely-backend-needed boolean and optional urgency. Unknown is nullable, not `0`, `False` or a guessed classification. Omit conversation phase in v1 unless an identified controller consumer needs it: current speech activity, commit state and WAIT/other suggestions already carry the useful distinctions. Do not add generated speech text, tool name/arguments, executable plan or hidden reasoning to this contract.

**Application result envelope:** request/source identity, hint value or explicit unavailable outcome, and receipt/deadline evidence. Request IDs, source revisions, expiry and scope come from the request owner; the model cannot assign them or extend validity. A provider's JSON body need contain only the hint value. Reusing the original request binding avoids trusting echoed model IDs.

Use one small asynchronous analysis port with typed request/result. The port receives no Core, frontend, tool router or job dispatcher handle. A deterministic fake can return a supplied hint, wait on a controlled gate, fail or return unavailable. It must not invent user commits, generated audio or COMPLETE observations. No separate hint event bus, persisted conversation mirror or model-owned scheduler is needed.

## Eligibility and authority table

| Suggestion | Allowed controller interpretation |
|---|---|
| WAIT | Optional silence for this still-current candidate. Does not block a ready direct answer or erase a task result; expires with the request. |
| BACKCHANNEL / PREAMBLE | Candidate for Task06 policy. Owner/address admission, current work evidence, useful-answer availability, expiry and exact first-write admission still decide. A hint cannot attest that work started. |
| SPEAK | Consider already eligible content through Task08. No speech text or direct frontend call comes from the hint. |
| DELEGATE | Advisory need for work; no dispatch in Task09/10. Task11 later applies admitted-work or restricted speculative-analysis scope under Decision22. |
| High addressing confidence / urgency | Useful analysis evidence only. Neither establishes owner identity nor bypasses explicit-request/action confirmation or interruption policy. |

Task06's deterministic gate remains the final policy owner for reflexes. Contradictory hints cannot overwrite a committed user record, independently confirmed heard words or an already-invalidated output token. A useful result is preserved under Decision23 even if a hint suggests WAIT.

## Freshness, bounds and failure

- Match frontend incarnation, request identity, transcript group/revision, committed phase and relevant source dependencies. A newer input revision invalidates an older hint immediately; later commit supersedes the provisional hint even if its text happens to match. Do not fabricate a commit when a provider lacks finality.
- Treat canonical snapshot revision as a captured watermark, not a universal equality check. New output audio, usage or unrelated backend progress can change global state without changing the hint's source. Conversely, matching global revision alone cannot establish speaker/admission validity. Reuse Task08's dependency and intent-generation checks once available.
- Expiry belongs to the request owner and is measured with its local monotonic clock. Preserve each dispatched request's original deadline across retries; receiving a late answer must not restart TTL. A newer pending snapshot gets its own request binding without renewing an older hint. Keep UTC timestamps only for diagnostics if useful; do not serialize process-local time as a durable authority. Expired or superseded hints are discarded, never queued for later speech.
- Proposed initial bounds: current transcript at most 8,192 characters; at most 8 selected history messages and 16,384 total request text characters; intent hypothesis at most 512 characters; bounded reason code; IDs at most 256 printable characters; finite confidence numbers in [0,1], explicitly rejecting booleans/NaN/infinity. These are application proposals; Task09 should reuse stricter existing limits where possible and test aggregate size. Token/call budgets and timing defaults belong to Task10 implementation, not provider-neutral fields guessed in Task09.
- Keep at most one in-flight analysis and one replaceable latest pending snapshot per active frontend, with bounded invalidation/dedup retention. Newer revisions replace unsent snapshots. Cancellation of an in-flight request is an optimization; stale rejection is required even when cancellation fails or the old result arrives afterwards. No unbounded “one call per delta” task list.
- Distinguish valid WAIT from unavailable/refusal/timeout/invalid-output/transport-error/superseded. Unavailable outcomes do not masquerade as model WAIT and do not raise a critical-path exception. Accept only a strict known schema/version; unknown fields, unsupported enum values, missing required fields or excessive data yield invalid-output. Any provider refusal/incomplete response must be detected before treating content as a hint.
- A duplicate hint does not create another preamble or reset a deadline. A session switch, analysis configuration change or revoked analysis admission invalidates pending hints; restarting the sidecar cannot resurrect them. Cache saturation must fail to ordinary conversation, without silently forgetting a still-relevant rejection watermark.

## Exact slice dependencies and unresolved integration seams

**Task09:** immutable provider-neutral request/value/outcome contract, strict validation/codec as needed, one small port, fake and deterministic consumption tests. It depends on already implemented02/04/06; this orchestration also waits for08 acceptance so source freshness can be reused. No Luna client, request worker, prompt settings UI or task execution.

**Await Task08:** final typed source identity/dependency/intent-epoch semantics; candidate selection/defer interface; exact point where hint freshness is rechecked before output admission; durable outcome reference/projection. At inspection time `SpeechRequest` lacks these new fields. Do not implement their proposed names from `08-scheduler-review-plan.md` as if already present. Task09 may rely on transcript revision now, but must attach to08's accepted source contract before claiming integrated freshness.

**Task10:** actual configured analysis-model client, structured-output mapping, bounded projection builder, latest-pending coalescing/debounce, request/token budgets, cancellation ownership, runtime composition and diagnostics. Preserve the configured model/provider and validate capabilities; do not silently replace a configured model. Recheck official model/request schema when implementing. Task09 should not encode Luna-specific reasoning or Responses objects.

The current compatibility façade forwards canonical user input to Core only after admission and suppresses provisional user observations. Task10 therefore needs an explicit bounded fan-out from the existing canonical reader, not a second consumer of `VoiceFrontend.events()` or raw provider socket. Analysis before the final **addressing decision** may be useful, but it still needs application permission to analyze that input: preserve the pre-upload owner boundary and do not feed known rejected/unauthorized data to a new model. Keep provisional addressing uncertainty separate from completed turn admission. If provisional records enter Core, give rejected/superseded/failed groups a bounded lifecycle without empty synthetic commits.

Decision22 does not turn a hint into a CoreJob: only Task11's actual admitted submission creates durable work identity. Until that path exists, DELEGATE remains advisory. Task14/15 own Settings/prompt registry presentation; Task18 owns cross-mode metrics. Task09 must not quietly implement those slices.

## Review evidence

Contract tests: nullable unknowns; finite bounded confidence; strict enum/version/shape; aggregate bounds; non-authorizing source/result types. Controller/fake tests: newer revision defeats slower older hint; commit invalidates provisional result; unrelated snapshot update preserves current hint; session/config switch rejects old result; duplicate does not renew TTL; refusal/timeout/malformed payload allows direct response to proceed; ready answer is not blocked by WAIT; PREAMBLE cannot invent work evidence; DELEGATE cannot call an executor; conflicting intent cannot mutate committed/played state.

Task10 adds controlled long-utterance tests proving bounded actual calls and one latest pending revision, with final input receiving timely budgeted analysis rather than starving behind speculative requests. Observe request/source IDs, decision/outcome, latency, expiry/drop reason and counts without raw transcript or hidden reasoning in normal diagnostics. A fake timeout test proves fallback behavior, not live latency or model quality.
