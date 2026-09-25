# Jarvis V1 acceptance status

> Realtime + async brain revalidation, **2026-09-12**: 1,891 tests passed,
> 4 expected skips with warnings treated as errors; release verifier passed.
> The real Realtime speech smoke also passed separately. Four behavioral
> regressions and test fixture leaks were corrected. See the
> [current report](../tasks/jarvis-realtime-brain-orchestration/FINAL-REPORT.md).
> This does not close workstation acoustic or brain calendar/reminder gates.

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
| 09 Barehands (upstream AGPL board) | IMPLEMENTED / MANUAL GATE | **One word: the third-party board on port 8794, not the native subsystem.** Hardened patch + token client + CDN removal + integrity tests pass. Physical authenticated server smoke, offline browser load and hand gestures require workstation/camera. |
| 10 Visualizer/launcher | IMPLEMENTED / MANUAL GATE | Launcher, health degradation, state mapping and process boundaries implemented. Full multi-process launch requires bootstrapped third-party snapshots and physical workstation. |
| 11 E2E/release | PASS automated; MANUAL GATES remain | Simulated E2E/security suite passes. Real-provider/hardware latency and gesture smoke are NOT CLAIMED. |

### Bare Hands V1 (native subsystem)

Delivered by the handoff `tasks/jarvis-bare-hands-v1/`, thirteen Slices (00-12).
**Two words: this is native Jarvis code inside the Control Center page — no
separate process, no port, no token. It is not row 09 above.**

| Slice | Status | Evidence / remaining gate |
| --- | --- | --- |
| 00 Readiness | PASS | Findings F1-F7 and human decisions D1-D5 recorded in `slices/00-project-manager/READINESS.md`. |
| 01-12 implementation | PASS automated; **MANUAL CAMERA GATE NOT RUN** | Every Slice implemented; 01-09 and 12 reworked after QA. Contract, engines, target resolution, interaction, tools/settings, calibration, tutorial, diagnostic recording/replay and the brain command channel all have node-executed or server-side tests. |
| Real-camera behaviour | **WAIVED, NOT PASSED** | See below. |

**The camera gate was waived for this run, which is not the same as passing
it.** There is no webcam and no browser in this environment, so *no* statement
in this repository about how Bare Hands feels, tracks, wakes or fails in front
of a real hand has been verified by observation. The procedure a human must run
is in `docs/OPERATIONS.md`, « Procédure de test manuel (caméra réelle) »,
batched A1-A7 so it fits a small number of camera sessions. **A2.2 — a flat
hand, fingers together, thumb adducted, may falsely wake — is the single
most-referenced open item of the whole task and is listed first.**

What *is* established without a camera: the refusals, the schemas, the
migrations, the origin guards, the whitelists, the clean-room boundary, the
determinism of replay, and that every module-load failure is contained. What is
*not*: any number that describes a real hand.

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

### C. Gestures (upstream Barehands board)

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
| Live OpenAI Realtime smoke test on the continuous path | **PASS — 2026-09-12** | `test_real_openai_realtime_brain_speech`: 1 passed in 3.28 s against the real service. No microphone or speaker opened. [Evidence](../tasks/jarvis-realtime-brain-orchestration/live-smoke-2026-09-12.txt). This validates session/speech creation, correlated output/audio and sending cancellation, not acoustic behavior or a server cancellation acknowledgement. |
| `response.metadata` correlation round-trip | **PASS — 2026-09-12, one live session** | The live smoke test observed the expected output id and `speech_id` on normalized output start and first audio. This closes the previously unrun provider-binding check for the tested adapter/service combination; retain the opt-in regression test for future provider changes. |
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
---

# Presentation interaction mode — acceptance status

Date: 2026-09-24. Scope: the handoff `tasks/jarvis-presentation-interaction-mode/`
(Slices 00-11). Everything above is unchanged by it.

Legend is the same as above. **UNVERIFIED** means the gate exists, was not
executed, and is not assumed to pass.

## Automated acceptance executed

Run from the repository root on the Windows workstation, 2026-09-24, with the
project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_presentation_integration.py `
    tests/unit/test_presentation_response_policy.py tests/unit/test_presentation_speculative.py `
    tests/unit/test_presentation_audio_capture.py tests/unit/test_presentation_working_set.py `
    tests/unit/test_presentation_attention.py tests/unit/test_presentation_addressed_turn.py `
    tests/unit/test_ambient_ingestion_lane.py tests/unit/test_interaction_mode_contract.py `
    tests/unit/test_interaction_mode_control_plane.py tests/unit/test_v2_speech_scheduler.py `
    tests/unit/test_v2_continuous_live.py tests/unit/test_v2_voice_toggle.py
```

The release verifier's **static** gates were run separately from its pytest step,
because the single process is killed by this machine's memory reaper.

> **Six of its seven static gates pass; the seventh fails, and it is not this
> feature's.** `jarvis/runtime/barehands_replay.py:144` uses `subprocess.run(`
> and is not in the verifier's two-file tooling allow-list, so
> `scripts/verify_release.py` exits non-zero. Proven on HEAD's own blobs to
> predate this branch. **`scripts/verify_release.py` is therefore not green on
> this tree**, and the 2026-09-12 "release verifier passed" line above describes
> an older one. Full detail and three options:
> `tasks/jarvis-presentation-interaction-mode/Issues/003-…`.

Counts and the per-chunk commands are in
`tasks/jarvis-presentation-interaction-mode/slices/11-integration-rollout/REPORT.md`.

## Status

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Interaction-mode vocabulary, output disposition, the seven-row policy matrix | PASS | Slices 01/07. The matrix is data and its two implications are checked over every row at construction. |
| Live mode control plane, no Voice restart on a mode change | PASS automated **and** in a running system | Slice 02 ran a real Core + Control Center over 6 Core lives and 16 mode requests; `configuration_id` is byte-identical across all three modes and no `voice.switch.*` line ever appeared. |
| Control Center mode selector | PASS automated **and** in a real browser | Slice 03, headless Chrome over the DevTools Protocol: real layout, a frozen mid-flight write, 51 screenshots. |
| Session working set and transcript tail, retired on a mode change | PASS | Slice 04. |
| Single microphone owner in PRESENTATION, counted | PASS automated | Slices 05/11. The ownership registry counts all six openers; entering suspends the SIMPLE wake stack before opening the hub, and a second owner makes activation refuse rather than open a second stream. **No real microphone was opened at any point.** |
| Continuous ambient ingestion | PASS automated | Slice 06, against the real hub, the real segmenter and the real store, with a fake device and a fake transcription provider. **No real transcription provider was called.** |
| Silence as a successful outcome | PASS automated, **on the four continuous architectures only** | Slice 07 + the Slice 11 matrix. On `voice_arch=legacy` no `SpeechScheduler` is built, so no addressed turn can open at all — PRESENTATION now **refuses to take the microphone** there (`presentation_architecture_unsupported`) instead of listening to a room it could never answer. The matrix is parametrised over all five readings and asserts that refusal on the one row that needs it. |
| Speculative preparation, bounded and sacrificial | PASS automated | Slice 08. |
| Fact-check attention: one card, one cue, never speech | PASS automated **and** in a real browser | Slice 09. |
| Priority addressed turns, D04 | PASS automated, structurally **and** by measurement | Slice 10: `arm()`/`open()` are await-free by AST guard, measured at 3.6 ms against a saturated backlog; Slice 11 re-measures it against its own deterministic slow-ambient fixture. |
| **Composition: the five subsystems reach a running JARVIS** | PASS automated | Slice 11. Before it, three independent audits confirmed **zero** production construction sites. |
| **The real speculative runner** | PASS automated, **no real sub-agent run** | The `presentation_preparation` CLI profile is asserted on the `argv` actually built, with `asyncio.create_subprocess_exec` intercepted. No `claude` process was ever launched by a test. |
| **Fact-check provenance end to end** | PASS automated | Before Slice 11 nothing constructed a `PresentationSource`, so `decide_attention` would have refused **every** verdict as `attention_provenance_unknown`. The runner now records the source it cites before citing it. |
| Privacy: no raw audio, bounded working set, trace boundaries | PASS automated, **after a defect found in review** | A planted phrase is driven through the ambient lane, a claim and an attention `reason`, then searched in the whole trace: zero hits. **The first version of that test used a scripted sub-agent with no journal, so it could not fail**; the real `ClaudeLocalAgent` copied its whole prompt — the room's speech — into `agent.input`, i.e. into an append-only file with no rotation. Both restricted profiles now withhold that echo, and the test drives the real agent. PRESENTATION writes to two durable places, both stated in `docs/OPERATIONS.md`. |
| Diagnostics: queue lag, backlog, speculative jobs, trigger latency | PASS automated | `presentation.runtime.diagnostics`, emitted every 30 s while a session lives, asserted against a session with a real backlog. |
| Ambient transcription on a non-OpenAI voice stack | **NAMED BLOCKER** | No transcription is available; PRESENTATION answers explicit address and reports `ambient_deaf` rather than degrading in silence. |
| Speculative preparation with an agent CLI other than Claude | **NAMED BLOCKER** | `--tools` and the restricted profile are Claude CLI arguments; `back_brain_worker` already refuses the speculative scope for the same reason. |
| Working-set projection reaching the brain turn | **NOT WIRED** | `submit_brain_turn` carries no context parameter, and the addressed turn is classified *after* submission by Slice 07's design. `SHOW_PREPARED`, `CLARIFY` and `REFRESH` are wired; `ASK_BRAIN` reaches the brain without the projection. See the Slice 11 report, remaining limitations. |
| Workstation acceptance of PRESENTATION | **UNVERIFIED** | No microphone, no speakers, no wake word, no real sub-agent, no real transcription, no real scene. The checklist below is the gate. |

## Blocking workstation checklist for PRESENTATION

**Not executed.** Everything a machine could clear has been cleared; what
remains needs the physical station. Run on the target Windows workstation, with
`python -m jarvis core`, `python -m jarvis control-center` and
`python -m jarvis voice` all **restarted from this commit** — a stack started
before it does not carry any of this.

`HV-PRES-E2E-01` is the whole walkthrough; the four earlier checks are the
narrowed remainders of Slices 05-10.

1. **Start in SIMPLE and change nothing.** One wake, one question, one answer.
   This is the D14 baseline: anything that behaves differently from last week
   is a regression, and it is the first thing to judge.
2. **Switch to PRESENTATION in the Control Center.** Expect: the selector turns
   over without Voice restarting, and `runtime/trace.jsonl` shows
   `presentation.runtime.entered` with `physical_input_owners: 1`. If it shows
   `entry_failed`, stop and record the code: no further result is meaningful.
3. **Say nothing to JARVIS and talk to the room for two minutes.** Expect:
   nothing is said, nothing appears on screen, and the periodic
   `presentation.runtime.diagnostics` lines show `segments_pending` returning to
   zero between utterances. Ambient preparation is visible only in the trace.
4. **Address him with a visual command** — press the key (or say "Jarvis") and
   ask *"montre-moi le bilan"*. Expect: the screen changes and **nothing is
   spoken**. Silence here is the feature, not a failure.
5. **Address him with a knowledge question.** Expect: he answers out loud.
6. **Ask for something that was prepared ahead** — mention a document while
   talking to the room, wait, then ask for it. Expect: it appears without a new
   round of work. `presentation.addressed.reused` in the trace is the proof;
   without that line, it was re-prepared.
7. **Contradict a fact you stated earlier.** Expect: a small card in the toast
   rail and **one** discreet cue. Nothing is spoken. *(`HV-PRES-ALERT-01`.)*
   **Open question for the Human, deliberately left open since Slice 09:** the
   cue is the existing *failure* variant — a contradiction currently sounds like
   an agent crashing. Decide whether it should be distinguishable; it is a
   one-line change.
8. **Interrupt ambient work with an explicit address.** While a preparation is
   obviously running, press the key. Expect: the turn is served immediately.
   *(`HV-PRES-PRIORITY-01`.)*
9. **Switch back to SIMPLE.** Expect: the microphone returns to the SIMPLE path,
   the session memory is gone, and behaviour is exactly step 1's.
10. **Repeat steps 2-9 on every voice architecture you run.** Slice 07 shipped a
    mute Presentation on three architectures because it was exercised against
    one. *(`HV-PRES-SPEECH-01` asks for exactly this.)*
11. **Wake word and manual key, separately.** *(`HV-PRES-AUDIO-01`.)* With a
    Porcupine key configured, both must reach JARVIS, and
    `physical_input_owners` must stay at 1 throughout.
12. **Kill the Voice process while a preparation is staged**, then start it
    again and enter PRESENTATION. Expect: `presentation.runtime.reclaimed`, and
    no leftover hidden objects in the scene.

Record the OS, the PortAudio device and the voice stack, and record failures as
failures: a limitation written down is worth more than a claimed pass.

