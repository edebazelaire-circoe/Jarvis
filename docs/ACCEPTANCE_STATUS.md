# Jarvis V1 acceptance status

Date: 2026-08-31

> Solo Owner (owner-aware voice gating) and the Core work state, delivered by the
> handoff `tasks/jarvis_solo_owner_duplex_handoff/`, have their own workstation
> protocol: [`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md), **not
> executed** (it needs the owner's voice and real background speech). What was
> automated is reported in
> [`docs/fixes/solo-owner-duplex/final-implementation-report.md`](fixes/solo-owner-duplex/final-implementation-report.md).

Legend:

- **PASS**: executed in this build environment.
- **IMPLEMENTED / MANUAL GATE**: implementation and automated contract tests are present, but acceptance needs hardware/network/browser unavailable in the build sandbox.
- **NOT CLAIMED**: deliberately not fabricated or inferred.

## Task-by-task status

| Handoff task | Status | Evidence / remaining gate |
| --- | --- | --- |
| 00 Orchestrator | PASS | Original handoff retained under `docs/handoff`; implementation order and final status documented. |
| 01 Pin upstreams | PASS for code/integrity design | Exact commits + licenses in `third_party/LOCK.json`; bootstrap is reproducible/fail-closed. Actual binary bootstrap cannot run in this sandbox because outbound downloads are unavailable. |
| 02 Core contracts | PASS | Typed ports/domain, fake text/E2E tests, provider-import release rule, invalid config tests. |
| 03 State bus | PASS | Deterministic transition tests; visualizer-compatible files generated without UI; runtime state kept out of source control. |
| 04 Voice/STT | PASS automated; MANUAL audio/provider gate | In-memory AudioClip, mocked real adapter contract, provider failure recovery, no raw audio persistence. Real mic/OpenAI STT is manual. |
| 05 Agent backend | PASS | Normal responses, exactly three tool schemas, unknown/general tools denied, provider-neutral core gate. |
| 06 TTS/interruption | PASS automated; MANUAL speaker gate | Cooperative cancellation and runtime-level PTT barge-in tests pass; real speakers/TTS latency manual. |
| 07 ActionBroker | PASS | Board no-confirm, memory write confirm, denial/timeout no write, forged policy cannot bypass broker. |
| 08 Memory | PASS | Seed search, confirmed Markdown persist, restart persistence, index deletion/rebuild, traversal/symlink tests. |
| 09 Barehands | IMPLEMENTED / MANUAL GATE | Hardened patch + token client + CDN removal + integrity tests pass. Physical authenticated server smoke, offline browser load and hand gestures require workstation/camera. |
| 10 Visualizer/launcher | IMPLEMENTED / MANUAL GATE | Launcher, health degradation, state mapping and process boundaries implemented. Full multi-process launch requires bootstrapped third-party snapshots and physical workstation. |
| 11 E2E/release | PASS automated; MANUAL GATES remain | Simulated E2E/security suite passes. Real-provider/hardware latency and gesture smoke are NOT CLAIMED. |

## Automated acceptance executed

Run from repository root:

```bash
python -W error::ResourceWarning -m pytest -q
python scripts/verify_release.py
python -m compileall -q jarvis scripts tests
sh -n setup.sh
```

PowerShell is not available in this Linux sandbox, so `setup.ps1` is not claimed as executed. It is included for the Windows workstation acceptance pass.

Current automated pytest result at report generation: **107 passed, 1 skipped**. The skip is the explicitly opt-in live OpenAI smoke test.

## Blocking manual workstation checklist

These gates are the only reason this report calls the artifact a release candidate rather than a fully accepted physical V1.

### A. Bootstrap and integrity

1. On a networked workstation run `python scripts/bootstrap_third_party.py`.
2. Run `python scripts/bootstrap_third_party.py --verify`.
3. Expected: success and an `INSTALL-STATE.json` with no integrity mismatch.
4. Disconnect network temporarily, start Barehands, reload `http://127.0.0.1:8794/stage.html`.
5. Expected: hand-tracking/3D runtime assets load locally; browser network panel shows no CDN/model fetch.

### B. Barehands authentication

1. Start full launcher with `OPENAI_API_KEY` set.
2. Ask Jarvis to present a summary on the board.
3. Expected: authenticated board command materializes.
4. Separately POST a valid-looking command to `http://127.0.0.1:8794/cmd` without `X-Jarvis-Token`.
5. Expected: HTTP 401; no board mutation.
6. Send a request with a non-loopback `Origin` and any incorrect token.
7. Expected: no mutation (authentication and/or origin rejection).

### C. Gestures

In Chrome with camera permission:

- hand cursor follows the hand;
- pinch/grab/move works;
- existing open/close/present interactions still work;
- clap/clear behavior (where provided by upstream) still works;
- board remains usable after Jarvis-presented content appears.

Record browser/OS versions because this is an upstream hand-tracking compatibility gate.

### D. Real voice loop

1. Run `python -m jarvis health`; microphone must be `ok`.
2. Hold F9, ask a project question, release.
3. Expected state sequence: listening -> transcribing -> thinking -> speaking -> idle.
4. Press F9 while Jarvis is speaking.
5. Expected: playback stops promptly and the new capture begins; next reply is synchronized.
6. Temporarily make provider unavailable.
7. Expected: visible error state, short spoken error if TTS remains reachable, no crash, returns idle.

### E. Memory confirmation and restart

1. Ask Jarvis to remember a distinctive fact.
2. Before confirmation, verify Markdown has not changed.
3. Say an ambiguous phrase such as `ok` -> still no write.
4. Say exact `oui` -> write occurs.
5. Restart Jarvis and ask/search for the fact -> it is retrieved.
6. Repeat with exact `non` -> no write.

### F. Real latency measurements

Capture at least 10 normal turns after one warm-up and record p50/p95 for:

- transcription completion;
- agent response completion (or first-token metric if streaming is added later);
- TTS first audio / completion;
- end-to-end release-to-first-audio and release-to-idle.

The current V1 adapter is non-streaming, so `agent_first_token_ms` cannot honestly be measured as a first-token value. Record agent response completion instead and treat streaming/first-token as a V2 optimization unless the adapter is changed.

## Skills deviation from handoff

The handoff asked the implementation agent to load `/caveman` and `/coding-guideline` for coding tasks. Those skills were not installed/available in this ChatGPT environment, so they could not be invoked. Their observable engineering intent was enforced manually through modularity, typed contracts, fail-closed security, tests on behavior changes, and repeated audit/rework. This is a tooling-environment deviation, not a runtime dependency of Jarvis.

---

# Realtime + async brain acceptance status (v0.2 voice path)

Date: 2026-09-09. Scope: the handoff under `docs/handoff-realtime-brain/`
(Tasks 00-12). The V1 status above is unchanged by it.

Legend is the same as above, plus:

- **UNVERIFIED**: the gate exists, was not executed, and is not assumed to pass.

## Automated acceptance executed

Run from the repository root on the Windows workstation, 2026-09-09:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_release.py
```

Result: **706 passed, 4 skipped, 0 failed**, and `Release verification passed.`
The four skips are the two opt-in live OpenAI tests, one POSIX-only signal test
and one test needing symlinks.

## Status

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Typed brain/speech contracts, Core-owned orchestrator, protocol ingress | PASS | Unit + integration suites; provider-neutral architecture gate widened before any backend was injected. |
| Continuous LIVE lifecycle and `JARVIS_VOICE_ARCH` switch | PASS automated | `legacy` stays the default, computed from `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS`; both directions pinned by tests. |
| Empty surface tool catalogue in continuous mode | PASS | Unit test on the catalogue plus an integration scenario proving no Core tool executes from the surface. |
| Barge-in ordering and truncation honesty | PASS automated, up to the local stop | Tests prove local stop -> `cancel_output` -> `truncate`, and that a truncated sentence is persisted as partly heard. They do **not** prove that sound stops in the speakers, nor how fast. |
| Six latency measures | PASS automated | Emitted into `runtime/trace.jsonl`, identifier-only, joinable by `correlation_id` / `speech_id` / `work_id`. |
| Live OpenAI Realtime smoke test on the continuous path | **UNVERIFIED** | `tests/integration/test_live_openai.py` covers it but is opt-in and was not run. Not a failure; simply not executed. It carries the `response.metadata` round-trip check described in step 1 of the checklist below. |
| `response.metadata` round-trip on `response.created` | **UNVERIFIED** | Named single point of failure. `speak()` correlates a brain speech with its provider response only through `response.metadata` (`jarvis/adapters/openai_realtime.py:455-467`, `_bind_response()` line 235). If the real service does not echo it back, the speech loses its `speech_id` and is persisted twice - once as `surface.reflex` by the conversation bridge, once as `brain.speech` by the scheduler - and barge-in loses its truncation target. Open question 9 in `docs/handoff-realtime-brain/docs/07-open-questions.md`. |
| Workstation acoustic acceptance | **UNVERIFIED** | No microphone, speaker, headphone, echo or VAD-retrigger measurement was made at any point in this handoff. |
| Brain access to calendar and reminders | **UNVERIFIED** | The blocking gate. In continuous mode the surface holds no tools, and the brain's own calendar/reminder access has never been confirmed. Drive is reachable only if the operator registered `python -m jarvis drive-mcp` in the CLI agent. |

## Blocking workstation checklist for `continuous_brain`

Not executed. Run on the target Windows workstation with
`JARVIS_VOICE_ARCH=continuous_brain`, after `python -m jarvis core`:

1. **Check this first, before anything else is judged.** Have the brain speak
   once, then open `runtime/trace.jsonl` and find the `voice.output_started`
   event of that speech (it is emitted from the `realtime.output_started`
   envelope). Its `speech_id` **must be non-null**. If it is null, the real
   service did not echo `response.metadata` back on `response.created`, and the
   whole correlation chain is broken: the sentence is persisted twice, once as
   `surface.reflex` by the conversation bridge and once as `brain.speech` by the
   scheduler, and barge-in can no longer truncate the right output. Stop the
   checklist there and record it - nothing measured afterwards is trustworthy.
   See open question 9 in
   `docs/handoff-realtime-brain/docs/07-open-questions.md`.
2. Headphones: normal conversation over several turns without a second wake.
3. Normal speakers: same, and record whether Jarvis' own voice retriggers the
   VAD while the microphone stays open. If it does, keep `legacy` and say so.
4. Keyboard noise and background speech: neither must count as useful activity
   nor open a turn.
5. Interrupt Jarvis mid-sentence. Measure how long the sound keeps playing.
   Compare with the `stop_latency_ms` recorded in `voice.barge_in`.
6. Long brain job while the user keeps talking: the session must stay ACTIVE,
   progress must be spoken, and the surface must never claim a result.
7. `Jarvis Mute` during a job: the job survives in Core, nothing is spoken, and
   no auto-wake occurs when the result arrives.
8. Wake again after the job completed: the surface must stay silent about the
   missed result; the brain receives it on the next turn.
9. Ask for a calendar event and a reminder. This is the gate of Decision 34: it
   fails today unless the brain has that access.

Record the OS/PortAudio/device versions, because echo behaviour is a hardware
gate, not a software one.
