# Task06 parent review tracking

Accepted, 2026-09-12. One implementation owner plus independent review; production reachability, focused regressions and observable outcomes verified by parent.

| Area | Required check |
|---|---|
| WAIT | Normal typed decision, no speech request/provider response/device write for confirmations, decline, thinking pause, ambient input or missing work evidence. |
| Whole utterance | An initial “OK” followed by a real request must not become an acknowledgement-only classification. Uncertain semantics fail toward silence without suppressing the actual backend answer. |
| Preamble | At most one per admitted correlation, only for attested ongoing work after configured delay; no invented completion, progress or tool execution claim. Existing zero delay disables preambles. |
| Ordering | Work started may precede reflex request; completion/failure/cancellation and a later authoritative user turn invalidate old candidates. State and dedup retention bounded. |
| Supersession | Useful answer before deadline, while waiting for silence, and during provider startup wins over an unplayed preamble. Guard queued/received PCM as well as response creation. |
| Cross-thread start | Atomic admission token arbitrates invalidation versus native write start. No asyncio policy/log calls on the device worker; write attempt is not heard evidence. |
| Expiration and cancellation | Existing expiry remains effective during slow provider send and delayed first PCM. One owned cancellation per exact output; deferred cancellation must not block the sole provider reader. Repeated events cannot target a newer useful output or leak tasks. |
| Authority | Gate DELEGATE is advisory, not a new executor. Existing owner/action permissions and actual user admission remain authoritative. No VAD/sidecar work hidden in this slice. |
| History | Dropped output never enters heard context. Existing provider/local output identity and playout fences remain correct. |
| Observability | Gate action/reason/correlation and measured decision latency; WAIT is not failure. No new raw transcript logging or second logging subsystem. |
| Evidence | Controlled race through real facade/frontend/bridge; deterministic fixture acknowledgement-rate comparison. Synthetic transport/device proves policy, not live acoustic quality. |

Source notes: `replay-fixture-extraction-notes.md`. In particular, source duplicate logs do not establish duplicate playback, and the source's “OK, très bien” continues into a substantive question.

## Review findings requiring regression evidence

- Independent reviewer reproduced a duplicate request invalidating a valid preamble after provider acceptance but before write; the duplicate guard originally checked only the pending candidate, not the live unstarted candidate.
- Independent reviewer reproduced a duplicate request rearming the expiry of an already-expired candidate. Deduplication must retain the original correlation/deadline even when no generation was attempted.
- Parent reproduced a Task05 lifecycle follow-up: controlled transport close emits EOF, then waits before confirming close. With an active event consumer and concurrent Stop, `_read.finally` sets the finished event and the consumer ends with STARTING/ACTIVE/STOPPING. Later Stop reaches STOPPED but the consumer missed its terminal event. Fix terminal/stream-end ownership and cover both close-ACK delay and cancellation-control failure. This is handled in the current adapter integration, not a separate concurrent implementation slice.
- Guard rejection after waiting for the native output lock must not emit first-audio/speaking observations when no write succeeded.

All findings resolved with persistent regressions. Correlation deduplication includes live/expired/WAIT candidates; exact cancellation and expiry are owned and bounded; an atomic native-write token keeps generated/attempted/written/heard distinct. Parent independently reran its EOF-before-close-ACK reproduction successfully after the fix.

Implementation gate:285 passed (13.53s). Parent independent expanded gate:567 passed (22.07s), warnings as errors, covering new gate/cleanup/race tests plus adapter/pipeline, Core state/codec/ledger, owner/barge-in/replay, audio lifecycle/cursor, scheduler/migration, app/environment, canonical contracts and real production composition. Diff check clean. Real RuntimeJournal assertions verify info-level WAIT, correlation/latency, no raw fixture text and no error file. Synthetic counterfactual comparison:6→2 preambles, both long-work positives retained. No hardware or live provider quality claim; Task07 still owns device completion.
