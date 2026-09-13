# Independent Task10 Luna adapter review

Scope: `tests/unit/test_luna_front_brain_review.py` and, by subsequent parent assignment, `tests/unit/test_front_brain_sidecar_review.py`, plus this report. The implementation lead changed production. No real API request, account credential, Core mutation or shared fixture edit occurred during review.

## F1 — remote plaintext URL accepted (resolved)

The adapter constructor accepted `http://evil.example/v1` and `http://127.0.0.1.evil.example/v1`. A subsequent request would attach the provider authorization header. This differed from the existing HTTPS/loopback-only configuration rule.

Permanent test: `test_plain_http_nonloopback_is_rejected_before_any_credential_can_be_sent`, two cases. Both initially failed because construction did not raise. Positive HTTPS and exact localhost/127.0.0.1/IPv6 loopback cases remain supported. The lead added constructor URL validation; both rejection cases now pass before any POST.

## F2 — outer JSON exponent overflow bypassed finite validation (resolved)

The outer parser rejected NaN via `parse_constant`, but JSON `1e999` became Python infinity through default `parse_float`. Merely setting `output:1e999` yielded INVALID_OUTPUT through the later shape check and did not establish finite parsing. A valid completed hint beside `metadata:{nested:1e999}` was incorrectly accepted as AVAILABLE.

Permanent test: `test_nonfinite_outer_number_cannot_hide_next_to_valid_hint`. It initially failed with AVAILABLE; the lead added finite float parsing. The nested case and direct `output:1e999` now produce INVALID_OUTPUT. The Task09 decoder was not altered by this review.

## Evidence

Command, run from repository root:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_luna_front_brain_review.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

- Initial boundary gate: 37 passed, 0.42 s.
- URL regressions added: 2 failed / 42 passed, 0.55 s.
- Nested exponent regression added: 3 failed / 42 passed, 0.50 s.
- Independent rerun after lead fixes: **45 passed, 0.39 s**.

Covered: exact Responses endpoint/model/effort/output cap/schema; nullable fields; selected context kept as user data; no tools/continuation; refusal/incomplete/failed/cancelled/error dominance; ambiguous message/tool output; duplicate keys and invalid confidence values; malformed outer JSON; streaming read bound; unknown-preserving usage; no reasoning/cached-token double counting; sanitized HTTP failures and no retry; deadline with a shared client configured without a timeout; cancellation propagation and correct owned/shared client cleanup; expiration at consumer time even when the result arrived earlier.

The oversized-body test uses an HTTPX AsyncByteStream producing 100 chunks of 16,384 bytes. Reading stops by the fifth chunk at the 65,536-byte bound and closes the response stream. It does not simply assert rejection after the entire body has been buffered.

Diagnostics assertions inspect the actual `voice.hint.analysis` sink records emitted by the adapter. Private input/context/key/error-body markers are absent; absent or invalid usage is unknown. Successful subset fields remain provider-reported, without adding reasoning to output tokens or cached tokens to input tokens.

## Limits and remaining slice acceptance

No unresolved adapter finding remains in this review scope. The adapter alone cannot establish production parallelism, per-turn reservation ownership, final-revision coalescing or frontend lifecycle wiring. Those are coordinator/composition gates owned by the lead and composition reviewer. This report does not claim an input-token tokenizer guarantee, measured provider latency, account model access or paid end-to-end validation.

Parent decision: reserve a fixed conservative allowance before each call, never refund on timeout or missing usage; enforce call count and `max_output_tokens` separately. Actual token usage remains observed evidence. Characters/4 is not a token-budget proof. Task18 owns monetary aggregation.

## Independent sidecar follow-up

`tests/unit/test_front_brain_sidecar_review.py` passed **13 tests in 0.66 s**, with the same command options as above. The initial source read found `VoiceContext(())` in the default constructor (tuple incorrectly supplied as revision). The lead fixed it before this review's first test run; the permanent default-construction test is positive, without claiming an independently recorded FAIL for that repair.

The controlled analyzer records active calls and can deliberately suppress cancellation until released. Tests establish one flight with only the latest pending revision, a maximum of two speculative requests with the third slot available for final input, and no budget refund after cancellation/timeout. A stale partial result returned despite cancellation is ignored; only the final request reaches `voice.hint.consumed`. The observation APIs return while analysis remains blocked; they do not await it.

Permission for item A does not permit B. Rejected items remain tombstones after new permission/final/late events. A conflicting transcript ID invalidates the previous speculation. Capacity exhaustion disables subsequent speculation without evicting rejection evidence. Close remains pending until a cancellation-resistant owned task finishes, refuses late observations, and leaves no live worker/flight.

Reservation is observable before entering the analyzer. Current constants reserve 135,168 conservative units per call (131,072 serialized request bytes plus the adapter's maximum 4,096 output-token cap), with 405,504 for three calls. These intentionally mixed conservative accounting units are not measured input tokens. A configuration below the fixed ceiling is rejected.

The payload bound tests use the real sidecar and real Luna adapter with HTTPX MockTransport. Two 8,192-character texts plus maximum source/dependency metadata exercise UTF-8, astral characters and JSON control-character escaping. Valid UTF-8/astral cases reach transport unchanged and within 131,072 bytes. The escaped case exceeds the serialized bound despite satisfying character limits: no POST occurs and the conservative reservation remains charged. This proves refusal instead of truncation or retrospective budget refund.

No transcript, context, key or hypothesis marker appears in the diagnostics inspected by these tests. The hint DELEGATE is only consumed as a value; the sidecar has no speech/Job authority. Actual app/device parallelism and selection semantics remain the composition review's responsibility.

## Source-contract follow-up

The accepted final-input contract now requires an independently projected, complete Core current source exactly equal to the item's admitted origin. An acceptance supplies origin; it cannot declare itself current. `update_source` may reconsider a held final when that projection catches up. A newer, different current source rejects the old final; observing finality still cancels the speculative flight before the Core source arrives.

Only the two positive final fixtures were updated to supply `update_source(source=origin, source_complete=True)` before their final observation. All existing finality, stale-result, cancellation, unique-flight and reservation assertions remain unchanged. The production reread covered the current adapter, sidecar, factory and explicit composition resolver; no production edit was made. Remote-HTTP/finite-JSON fixes and the streaming/payload bounds remain present.

Independent combined rerun:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_front_brain_sidecar_review.py tests/unit/test_luna_front_brain_review.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

**58 passed, 0.86 s.** No new finding identified in this bounded follow-up. Core admission ordering and real source-feed/device composition have separate owner/reviewer gates; these unit tests do not replace them.
