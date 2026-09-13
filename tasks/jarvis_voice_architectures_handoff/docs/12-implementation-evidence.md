# Task12 implementation evidence

Date:2026-09-12. Implementation, controlled review and parent release complete; **Task12 accepted**. Task13 has started on the remaining durable lifecycle boundary.

## Ownership and production path

| Responsibility | Files |
|---|---|
| Official contract and documented discrepancies | [provider review](12-provider-contract-review.md), [API notes](10-openai-api-notes.md) |
| Canonical Live transport, sole provider reader, audio/deltas/delegations/usage/ACK/stop | `jarvis/adapters/openai_live_frontend.py` |
| Duplex factory, versioned rules, canonical fan-out and device facade | `jarvis/app.py`, `jarvis/runtime/voice_composition.py`, `jarvis/runtime/voice_capabilities.py`, `jarvis/domain/live_prompt.py`, `jarvis/runtime/live_frontend_session.py` |
| Bounded trigger/poll/result controller | `jarvis/runtime/live_delegation.py`, existing `voice_observations.py` |
| Strict speculative provenance/results, atomic acceptance, freshness and recovery | `jarvis/domain/back_brain.py`, `jarvis/core/back_brain.py`, `jarvis/core/voice_ledger.py`, `jarvis/core/owned_job_execution.py`, `jarvis/core/v2_services.py`, `jarvis/adapters/sqlite_state.py`, `jarvis/ports/v2.py` |
| Fresh independent restricted CLI owner | `jarvis/runtime/back_brain_worker.py`, `jarvis/runtime/claude_local.py`, existing process-tree ownership |
| Local interruption latch, native epochs, uncertain close propagation | `jarvis/runtime/realtime_audio.py`, `jarvis/runtime/voice_v2.py`, Live facade |

Explicit Duplex chooses `openai/gpt-live-1`, client delegation and shared24kHz PCM. Simple/Front Brain and legacy/continuous compatibility remain separate. No Luna substitution, managed Responses backend, Realtime commit/response trigger or model-generated execution configuration enters this path.

The facade has one canonical event consumer. It forwards observations to the existing Core dispatcher and playable envelopes to the existing bridge. PCM is converted to cumulative received-duration evidence before Core ingress; snapshots never carry PCM. The controller starts separate bounded asynchronous work so flush/submit/status/append ACK cannot block provider reading or microphone send. It allows four pending delegations, retains128 seen identities without eviction/rearming, and never cancels a Core Job merely because a frontend closes.

## Restricted first-session analysis

`speculative_analysis` does not require or invent a USER commit, SpeechSource, provider item or authoritative turn. Core captures a persisted snapshot with1–8 exact same-session dependencies; `dependencies_complete=False` rejects an omitted provisional record. Stable conversation/session/delegation identity, strict repository validation and atomic admission prevent duplicate execution. Dependencies preserve text/revision/commit state and known optional provider identity. Freshness checks current session and exact dependency state; an unrelated new group is distinct from a correction to an existing dependency.

`BackBrainJobWorker` permits this scope only for configured native Claude with a fresh wrapper/session/process. On Windows, direct `.exe`/`.com` launch preserves the deliberately empty `--tools` argument; shell shims and Codex remain unavailable. The configured command/model/cwd/runtime root remain application-selected. Effective flags include:

```text
--restricted --tools "" --strict-mcp-config --safe-mode --no-chrome
--disable-slash-commands --permission-prompts none --no-session-persistence
--permission-mode dontAsk
```

No routing-hook settings, MCP/plugin configuration, resume or conversational Brain prompt enters this profile. The installed Claude CLI help was inspected for these restrictions. Controlled wrapper/argv tests exercise malicious input as data, result-only output and owned cancellation; they do not claim adversarial live-model execution or an independent OS network sandbox. Normal `admitted_work` settings and permissions remain unchanged.

The result is bounded typed Job data, persisted independently from speech/history. Startup, finalizing and cleanup observations use existing Job diagnostics/progress. Cancellation retains exact process-tree ownership; cleanup uncertainty never becomes fabricated completion. Existing Task11 recovery interrupts incomplete work without automatically rerunning a speculative CLI.

## Injection and delivery truth

Flush precedes both initial Core source capture and every status query. A local input-observation watermark detects corrections during HTTP or a progress ACK; the controller consults Core again instead of injecting a stale result. Quiet progress requires `fresh=True`; fresh terminal text uses commentary with the original provider delegation ID. Replacement closes polling; the Job/result remains Core-owned and retrievable.

Append admission is at most500 UTF-8 bytes, deliberately conservative against the documented500-token content limit. Oversized results remain retained; there is no silent truncation. An accepted Job is logged `accepted`; an acknowledged append is `append_acknowledged`; rejected/uncertain injection is `append_unconfirmed`. There is no blind retry after lost ACK and no diagnostic claiming the user heard it. A correction arriving after an append has already been sent cannot retract context the provider consumed.

Generated transcript is retained as generated. Primary Live lacks authoritative finality, part inventory and word alignment, so playback evidence carries partial/unknown duration without confirmed words. Authorized barge-in latches suppression for the entire incarnation; new local output IDs, transcripts or append ACKs do not resume playback. Confirmed provider close is separate from pending native device cleanup. An unknown typed close retains the session, exposes ERROR and blocks idle/offline/reopening. Full semantics and controlled device tests: [12D lifecycle evidence](12d-lifecycle-playback-evidence.md).

## Reproducible gates

Final repair update: cancellation of `LiveFrontendSession.connect()` now retains a facade-owned cleanup task, joins the adapter's shielded startup, stops the resulting incarnation and waits for transport cleanup before propagating cancellation. Repeated caller cancellation does not detach that owner. An unconfirmed provider close still stays UNKNOWN. `test_cancelled_connect_owns_late_start_and_unconfirmed_stop` covers the late-start race with a controlled connector/transport; this does not establish crash recovery.

`voice.live.usage` now emits privacy-safe `session_id`, `seconds`, provider `source` and `usage_type` (`cumulative` or `final`). It neither sums cumulative observations nor infers billing completion. `test_usage_diagnostic_is_cumulative_or_final_and_privacy_safe` inspects actual RuntimeJournal JSONL.

After these repairs, parent targeted gate: **76 passed,3 skipped**. The skips include the guarded provider tests; no provider request was made. Earlier full-release **2763 passed** is a **pre-final-fix baseline only**. Final parent release on the repaired tree: **2765 passed,5 skipped in299.86s**; release verification passed.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_live_runtime_safety.py tests/unit/test_live_duplex_review.py tests/unit/test_live_delegation.py tests/integration/test_live_duplex_session.py tests/unit/test_openai_live_frontend.py tests/unit/test_openai_live_frontend_review.py tests/integration/test_live_openai.py tests/unit/test_app.py tests/unit/test_voice_composition.py tests/integration/test_voice_production_composition.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Commands run from repository root; no billable provider/CLI inference in these tests. Parent12B adapter/reviewer/frontend-contract/codec gate reported105 passed. The parent targeted Task12 gate before the final repairs supersedes the narrower gates below: **376 passed in12.42s**.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_live_duplex_review.py tests/unit/test_live_runtime_safety.py tests/unit/test_live_delegation.py tests/integration/test_live_duplex_session.py tests/unit/test_openai_live_frontend.py tests/unit/test_openai_live_frontend_review.py tests/unit/test_app.py tests/unit/test_voice_composition.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_event_codec.py tests/unit/test_voice_conversation_state.py tests/unit/test_back_brain_speculative.py tests/unit/test_back_brain_speculative_adversarial.py tests/unit/test_back_brain_protocol.py tests/unit/test_v2_architecture.py tests/unit/test_v2_voice_toggle.py tests/unit/test_v2_continuous_live.py tests/unit/test_v2_barge_in.py tests/unit/test_owner_barge_in.py tests/unit/test_realtime_audio_lifecycle.py tests/integration/test_voice_production_composition.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Restricted executor/regression gate: **169 passed in15.19s**.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_back_brain_speculative.py tests/unit/test_back_brain_worker.py tests/unit/test_back_brain_tasks.py tests/unit/test_back_brain_protocol.py tests/unit/test_voice_ledger_protocol.py tests/unit/test_v2_architecture.py tests/unit/test_voice_to_claude.py tests/unit/test_claude_debug_console.py tests/unit/test_owned_process_tree.py -q -W error --tb=short
```

After the optional-source recovery correction: **95 passed in9.42s**.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_back_brain_speculative.py tests/unit/test_back_brain_tasks.py tests/unit/test_back_brain_protocol.py tests/unit/test_back_brain_worker.py -q -W error --tb=short
```

Independent controller/composition review: **245 passed in10.50s**.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_live_duplex_review.py tests/unit/test_live_delegation.py tests/integration/test_live_duplex_session.py tests/unit/test_openai_live_frontend.py tests/unit/test_openai_live_frontend_review.py tests/unit/test_app.py tests/unit/test_voice_composition.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_event_codec.py tests/unit/test_voice_conversation_state.py tests/unit/test_back_brain_speculative.py tests/unit/test_back_brain_protocol.py tests/unit/test_v2_architecture.py -q -W error --tb=short
```

Separate lifecycle/device gate:117 passed in3.97s; exact command in [its evidence](12d-lifecycle-playback-evidence.md). Scoped/global diff checks passed at review handoff.

Actual RuntimeJournal JSONL was inspected through `read_jsonl_tail` and file reads. Restricted-job traces show owned→started→finalizing→closed→result with speculative identity and no invented source correlation. Controller review traces show accepted→append_acknowledged with session/job identity, no raw answer or heard claim. Tests also inject unavailable journals without losing the business result.

## Remaining limits and Task13 boundary

The dedicated GPT-Live smoke is **present, not executed**, in `tests/integration/test_live_openai.py`, guarded by both `JARVIS_LIVE_GPT_LIVE=1` and `OPENAI_API_KEY`. It targets the actual Live adapter's start/stop/terminal-usage contract, with bounded cleanup and no device playback; the existing Realtime guard remains separate. No project entitlement check, live Claude inference, physical microphone/speaker validation or billing assertion was performed. Transport/server frames and native device/CLI behavior are controlled. Existing Windows process-tree tests exercise a controlled parent/child process, not the provider model.

Unknown close remains unknown and may require recovery not supplied by this slice. Durable session lease, crash/process-exit cleanup, idle/watchdog policy, sideband reaper, reconnection and final-usage reconciliation belong to Task13. Current usage/expiry observations are not crash-safe session ownership or billing finalization. Same-incarnation speech remains suppressed after authorized interruption; a fresh confirmed lifecycle is required to hear later speech. Long-session bounds can reject new observations/work explicitly. No speculative proposal can invoke an action, confirmation or existing CoreToolRouter admission by itself.
