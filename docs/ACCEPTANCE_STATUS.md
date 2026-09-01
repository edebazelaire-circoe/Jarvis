# Jarvis V1 acceptance status

Date: 2026-08-31

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
