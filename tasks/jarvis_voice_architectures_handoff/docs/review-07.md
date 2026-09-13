# Task07 parent review tracking

Accepted, 2026-09-12. Audio/device owner and canonical adapter/Core owner agreed their typed part/manifest/proof interface before integration. Parent reviewed implementation, independent reproductions, composition tests, diagnostics and documentation.

| Area | Required evidence |
|---|---|
| Weak candidates | Seven synthetic bus-like candidate signals preserve volume/output, capture and rejection diagnostics; real owner confirmation remains immediate without an added confirmation window. |
| Full inventory | Successful response terminal manifest enumerates all audio items and content indices; absent manifest, missing part, unknown type, conflicting identities or known lost PCM cannot establish complete coverage. |
| Actual drain | Production player invokes checked device stop after awaited writes, including byte credit. Python queue empty, write return, estimated latency and provider done are insufficient alone. |
| Identity | Device instance, frontend session, local output, provider response, playback/output epochs and all part byte extents match. Old completion cannot confirm a newer or interrupted output. |
| Late text | A matching final generated transcript may join retained full device proof later. No proportional word alignment, intended-text substitution or zero-audio heard entry. |
| Native ownership | Opening, writing, draining, aborting and closing stay owned despite caller cancellation. Serialized native calls retain pointers until terminal cleanup; application timeout remains explicit uncertainty. |
| Responsiveness | Urgent input and owner events bypass a blocked drain even when the Python audio queue has zero entries. Stop is bounded; pending device ownership blocks replacement opening and false idle/off. |
| Failure recovery | Write/start/stop/abort/close failures and repeated Stop preserve honest state, do not overlap native operations and do not lose cleanup ownership. |
| Integration | Real app factory, frontend/facade, Core HTTP/SQLite and production audio wrapper with a controlled consuming device verify full delivery and blocked/late cases. |
| Regression | Existing reflex atomic admission, cancellation, owner replay, canonical history, legacy/continuous modes and release architecture/privacy guards remain valid. |

## Initial draft findings

- Opening the output stream and then failing output start must clean up both created streams.
- Parent reproduced a failed output start followed by one failed close losing the partially opened output pointer: subsequent audio.close returned True/device_closed while the controlled output remained open. Retain streams from creation through successful close, including failed startup cleanup, and test a successful retry.
- Failure of abort/stop must not silently skip the close attempt or lose retained pointers and retry state.
- The same retained-pointer invariant applies to `stop_input`, which previously detached input before its close succeeded.
- Publishing partially opened stream pointers requires stop/write to join the opening owner. Parent reproduced abort overlapping a deliberately blocked native output.start after early pointer publication; close already waited for opening, but stop did not.
- Concurrent completion requests require one owned operation per identity/epoch; returning a cached COMPLETE after interruption is invalid.
- Delivery eligibility must account for the gain actually applied to each block, including a ramp returning to full volume.
- Existing comments claiming an upper bound of one audio block for native stop, exact interrupted cursor, or weak-candidate ducking must reflect actual guarantees.
- Lead's Task06 compatibility audit found lazy native start between admission.begin_write and stream.write. A slow start can outlive a preamble deadline before any PCM is written. Move the final admission/epoch check after start and immediately before write, with a retained-start expiry regression.
- Multipart truncation must carry the content index actually being played and a cursor relative to that part. The provider's latest received part can be ahead of the device; item identity alone cannot disambiguate multiple parts in one item.
- Removing an interrupted-output tombstone at provider response completion must not allow late PCM to resurrect that output.
- Concurrent runtime Stop calls must share cleanup ownership: a second call cannot publish BACKGROUND or resume wake input while the first still awaits provider close acknowledgement.
- Independent canonical review reproduced a frozen manifest accepting a later extra closed part or a delta after that part's final transcript. Revalidate coverage and contradictory terminal mutations when joining device evidence.
- Independent canonical review reproduced differing transcript text in the terminal provider manifest being discarded. Preserve/cross-check terminal generated text before confirming words; audio coverage alone cannot establish text identity.

Parent reproduced the duplicate-drain/cache defect with a controlled device and 480 bytes: two concurrent requests caused two native stops, and a request after interruption returned COMPLETE. Independent rerun after the fix observed one shared drain, equal proofs for both callers and STALE after interruption. Persistent regressions and the remaining integration gate are still pending.

Provider manifest facts and their limits are recorded in `realtime-audio-part-manifest-notes.md`; controlled fixtures prove application policy and device ownership, not historical acoustic classification or live provider quality.

## Independent validation

Canonical owner:178 passed (10.37s); device/runtime owner:237 passed (7.08s). Independent QA added two real runtime/frontend/Core HTTP/SQLite control-plane tests: blocked native drain with zero Python audio queue, progressing microphone/urgent events, bounded Stop, retained device ownership and refused reopening; concurrent Stop joins one provider close acknowledgement. Both passed, with no manually injected COMPLETE.

Parent independently reran the native reproductions successfully: shared drain/stale cache, concurrent runtime Stop, failed partial-open cleanup retry and Stop during opening without native overlap.

First parent release:2197 passed,5 failed,4 skipped (237.76s). Failures: one old Solo Owner rollback assertion still expected weak-candidate ducking; one controlled output stream lacked the newly checked shutdown keyword; three telemetry scenarios injected named output PCM without output_started. The fixtures required correction while preserving native exclusion, exact first-audio correlation and all six latency measurements. The separate slow native-start preamble-admission finding also needed a focused regression. Acceptance remained pending at that stage.

All findings resolved. Final repair gates:64 device/ownership/composition tests passed (3.50s),20 telemetry tests passed (4.27s), preserving all six metrics and their correlation/dedup requirements. Slow lazy start now precedes the final admission/epoch check, with expiry/Stop/close races producing zero written bytes.

Final independent parent release: **2205 passed,4 skipped in252.11s; Release verification passed.** Skips are two opt-in provider tests, POSIX-only signals and unavailable symlinks. No release guard was relaxed. Code/test diff check clean. The controlled63-candidate replay has zero gain changes/cancellations; true owner confirmation and replay regressions remain green. No physical acoustic measurement, Live session or commit was performed. Task18 still owns precise cross-architecture metric decomposition; native completion here establishes the device API boundary, not human perception.
