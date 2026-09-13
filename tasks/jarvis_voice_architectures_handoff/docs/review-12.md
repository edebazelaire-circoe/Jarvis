# Task12 review

2026-09-12. Targeted implementation, independent reviews and parent full release complete; **Task12 accepted**. Task13 owns the remaining durable lifecycle work.

## Verified review results

| Finding / controlled scenario | Resolution and permanent evidence |
|---|---|
| Local transcript correction arrives while Core returns an older `fresh` result | Flush before status and compare local input watermark before injection; query again after a correction. `test_local_correction_during_status_request_prevents_stale_result_append`. |
| Stale progress was still appended as quiet fact | Require explicit `fresh=True`; `test_stale_progress_is_not_injected_as_quiet_context`. |
| Rejected oversized append or unknown ACK was logged as presented | Distinct acknowledged/unconfirmed diagnostics, no hearing claim or retry. Two cases in `test_rejected_or_unconfirmed_append_never_logs_presented_or_retries`. |
| Seen-delegation eviction rearmed an old trigger | Capacity refusal without forgetting prior identities. `test_retention_saturation_does_not_rearm_old_delegation`. |
| Live close returned normally despite UNKNOWN, allowing false idle/offline/reopen | Typed close result reaches runtime; unresolved session retained and startup blocked. `tests/unit/test_live_runtime_safety.py`. |
| Cancelled connection abandoned shielded startup and its eventual transport | Facade-owned cleanup joins late startup, requests stop and waits for transport cleanup before propagating cancellation. `test_cancelled_connect_owns_late_start_and_unconfirmed_stop`. |
| Input/direction change assigned a fresh local output ID to a late interrupted tail | Synchronous incarnation-wide playback latch before device stop, also checked for queued events and asynchronous pre-play races. `tests/unit/test_live_runtime_safety.py`. |

The first four controller findings produced five failing tests before correction. The controller review file now also proves canonical flush can block submission without blocking provider/audio input, diagnostics failure cannot change business behavior, and actual RuntimeJournal ACK evidence contains no result text or heard claim. All tests live in `tests/unit/test_live_duplex_review.py`; the normal progress fixture now supplies the explicit freshness fact required by the protocol.

## Contract and authority checks

- Adapter sends `session.start` with client delegation and `store:false`, waits for `session.started`, owns one reader and correlates the three append ACK types. It does not invent Realtime commands, transcript finality, provider item IDs or audio completion.
- Explicit Duplex composition selects Live; the app factory/config gates and controlled end-to-end session run the actual facade/controller/adapter. Canonical observation batches exclude PCM. Generated transcript and local partial/unknown playback remain separate.
- First-session provisional input reaches the real Core/SQLite/BackBrainJobWorker/Claude wrapper path under controlled subprocess streams. No committed turn or action authority is fabricated. Concurrent duplicates and restart retain one durable job/result; correction invalidates freshness, and frontend replacement does not transfer the old delegation ID.
- Effective native-Claude argv disables tools, routing hooks, plugin/MCP/browser integration, interactive permissions and session resume/persistence for speculation. Negative payloads cannot choose these settings. Codex and unsupported shims remain unavailable. Configured admitted-work behavior is preserved.
- Original Job ownership survives frontend closure. Provider callback/result text cannot resolve an action or call the action router without the existing explicit application authority boundary.

## Validation and limits

Parent targeted gate before final repairs: **376 passed in12.42s**, warnings as errors. Final connect-cleanup/usage/smoke repair gate: **76 passed,3 skipped**. Earlier parent adapter gate105; restricted-worker gate169; controller gate245; lifecycle gate117. Exact commands and scope are in [implementation evidence](12-implementation-evidence.md) and [lifecycle/playback evidence](12d-lifecycle-playback-evidence.md). Do not add these overlapping counts together. Final parent release: **2765 passed,5 skipped in299.86s**, release verification passed.

The dedicated Live smoke is present in `tests/integration/test_live_openai.py`, guarded by `JARVIS_LIVE_GPT_LIVE=1` plus a credential, and was not executed. No actual model turn, paid session, acoustic test or invoice verification occurred. Server frames, native output and CLI results were controlled; real code paths and durable SQLite state were exercised. Privacy-safe `voice.live.usage` cumulative/final observations now have actual RuntimeJournal coverage. Local playback suppression intentionally cannot resume in the same Live incarnation after barge-in. Append ACK is not speech, and exact heard words remain unknown. Results above the conservative append bound remain retrievable rather than silently truncated.

The current close path preserves uncertainty and blocks false OFF; it does not implement durable session ownership, sideband reaping or crash-safe billing termination. These remain Task13. In-process startup cancellation now owns cleanup, but process crash and lost terminal delivery are not solved by that repair. Action execution from provisional Live input remains unavailable; analysis returns nonauthorizing facts/proposals only.

Historical research gaps are retained as dated preparation in [provider review](12-provider-contract-review.md) and [authority plan](live-delegation-authority-plan.md), with links to their Task12C resolution. Decision22 records the supported restricted path without changing the Task11 acceptance history.
