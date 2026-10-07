# Execution Log

Reserved for implementation agents and the Project Manager to record durable execution notes, decisions caused by repository drift, and completed validation evidence.

## 2026-10-05 — Agent 0: import (S0)

- Mode `start`, remote origin. `docs/workflows/AGENT_TASK_LIFECYCLE.md` does not exist in this repository: fallback to the Drive queue IDs recorded in project memory (to-do `1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm`, current `1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`, done `16yBLZRVOEbfDAN_CRh5722bkN46IUmo7`). No `dev` branch: base is `origin/main` `085928d`.
- Drive folder `1XuocX4v9H3e74eF7bX6xa39j2SxYkEUM` (uploaded 2026-10-05 09:35Z) mirrored byte-for-byte: 48 files, sizes match, all JSON parse, no markdown escaping. The Drive connector cannot move folders: **the Human must move it from `to-do` to `current`.**
- Slug collision with the first Presentation task (handed off 2026-09-23, merged into `main` by the Human as `9a722c0` on 2026-09-25). Its record moved to `tasks/jarvis-presentation-interaction-mode-2026-09/` (git mv, nothing deleted); its branch renamed `task/jarvis-presentation-interaction-mode-2026-09` (fully merged). Path references in 5 docs and `jarvis/domain/presentation_policy.py` repointed. The code it landed is repository reality for Slice 00 to reconcile ("preserve/reconcile, do not rewrite").
- Worktree `C:/Projects/jarvis/bpm`; the main checkout (the Human's live Jarvis) is untouched.

## 2026-10-05 — Agent 0: Slice 00 READY

- Blind audit (Explore, product goal only) → `slices/00-project-manager/BLIND-AUDIT.md`. Its headline (reveal broken in production) and the brain-turn context gap were re-verified by agent 0 in code.
- Plan agent drafted `docs/06-resolved-architecture.md` plus the per-Slice binding contracts from the audit and agent-0 decisions A1–A12. Agent 0 accepted its additions P1–P10, written as is.
- Baseline: 11 stable failures (10 unit, 1 integration), no flakes → `slices/00-project-manager/BASELINE.md`.
- Readiness: **READY**. 08/09 DEFERRED (Tool Brain not started; prefab foundation not merged). Details in `slices/00-project-manager/READINESS.md`.
- Supersession: the 2026-09 HV-PRES-MODE-01, -ALERT-01, -AUDIO-01, -SPEECH-01, -PRIORITY-01 and -E2E-01 are superseded by this task's three HV checks (06 R8).

## 2026-10-05 — Slice 01 APPROVED (`a9840d3`, report `2c994c7`)

QA (glue: qa-verification + code-review) found no blocking issues. The reveal now sends a single `SET_VISIBILITY` command: no other field changes, nothing can be created, and a refusal raises. Probes on scratch copies made the contract test go red for each case: the pre-fix source, a wrong keyword, a renamed stager method, and a renamed real-class method.

Polish, batched for a later implementer:
- (p1) Stale `scene_set_visibility` wording in the docstrings at `test_presentation_speculative.py:319,1908`.
- (p2) Back-links to `presentation-mode.md` from the 7 `presentation-*.md` pages and `interaction-mode.md`.
- (p3) Move the fixtures imported from `test_display_mcp` into a shared conftest.

Watch list (flakes outside the baseline):
- `test_presentation_attention_browser.py`: 1 failure, then 30/30 on rerun.
- `test_presentation_integration.py::test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee`: R6.2 eviction race, already a known flake in 2026-09.

## 2026-10-05 — Slice 02 delivered (`625c5e3`), QA running

Implementer report: the follower is owned by `PersistentVoiceRuntime.run` and cancelled first in `close()`. Each of the 5 new tests was shown red on a pre-fix copy. The fake Core in `test_v2_speech_scheduler.py` now fans out events to every subscriber, matching the real `CoreEventBus`. The optional board-kind test was skipped because it is already covered (`test_board_service.py:108`, `test_board_protocol.py:128`, `test_board_memory_contract.py:71`).

## 2026-10-05 — Slice 02 APPROVED (`625c5e3`)

QA ran glue tier plus a runtime check on an isolated real stack: Core and Voice started from `bpq` on their own ports and data root, F9 wake, fake provider key.
- **continuous_brain:** PRESENTATION is entered about 1.2 s after the POST with no wake (`presentation.runtime.entered`, `physical_input_owners: 1`), and back to SIMPLE the microphone is released.
- **legacy:** exactly one `entry_refused` per change, with no microphone opened.
- **Voice started while Core is already in PRESENTATION:** the session is entered from the snapshot.

No blocking findings. Batched for a later implementer:
- (p4) The follower keeps its stale token after an independent Core restart and stops following until Voice restarts. Same limit as the scheduler. Fix: re-read `token_file` on a refused handshake, as `CoreWorkTransport` does.
- (p5) The legacy refusal alert stays on screen after returning to SIMPLE (`presentation_runtime.py:1046-1049`).
- (p6) The fake Core in `test_v2_speech_scheduler.py` replays a backlog that the real bus drops.
- (p7) No follower-level test that a stale snapshot never overwrites a newer event.

## 2026-10-05 — Slice 04 delivered (`90dfae6`); agent-0 decisions P11/P12

The implementer stopped before coding with a real finding. On DUPLEX (GPT-Live), the model speaks on its own: Live output gets no output admission, so it plays directly. No transcript ever reaches `_handle_admitted_transcript`, so P2 could not be enforced there.

Decided by agent 0:
- **P11:** PRESENTATION is refused on DUPLEX (`presentation_architecture_unsupported`, `duplex_autonomous_output`).
- **P12:** on direct paths, authority is checked with a non-consuming `window_live()` before admission; the turn is opened after admission under Core's correlation.

Implementer deviations, accepted by agent 0 and to be stated in the R6 limits and in HV-PRESENTATION-E2E-01:
- In PRESENTATION the manual key arms an address window instead of stopping the session (with server VAD the key meant "stop", which ate the announced sentence). "Stop" remains available by voice barge-in and "Jarvis mute".
- A pending confirmation needs "Jarvis, oui" or a key press while a session is live.

Left for critical QA to judge: a window that expires between the pre-check and `open()` leaves that one sentence's text in `voice.transcript`.

## 2026-10-05 — Slice 04 QA (critical) → rework; S2 regression; Slice 05 delivered

**Slice 04 QA:** no authority bypass outside window/vocative. 9/9 mutants killed; the cosmetic control survived. The composed-stack replay sent 0 brain turns for the ambient monologue. Findings handed to the implementer in `bpm`, fixed in `3c8f890` (`S4: rework`):
- F1 (pre-existing, high): the plan correlation was cut to 64 characters while real brain correlations are 72, so CLARIFY was never spoken on the brain path.
- F2: the window race leaked text into `voice.transcript`.
- F3: a session reader that raises now fails closed.
- F4: an `open()` that raises now uses up the window.
- F8: docs and the HV-E2E instruction.

Accepted and added to R6: F5 and F7. F6 → `Issues/001`.

**S2 regression found by agent 0's bisect:** `test_speech_scheduler_review_races.py` went from 7 passed to 7 failed at `625c5e3`. Neither the implementer nor QA had run that file. The root cause was the test double `ConnectedCore` still reading a queue that `FakeCore` lost. Fixed in `92f227d`, and a sweep of all 52 files with a fake Core or `PersistentVoiceRuntime` is green.

**Slice 05 delivered** (`d6c2b34`, polish `0b2a115`):
- The context is transported on the brain path.
- The real-journal privacy test shows the planted phrase only in the model's stdin.
- A deaf lane is pruned on the diagnostics tick.
- Direct path: no context transport → `Issues/002`, accepted as a V1 limit by agent 0.

## 2026-10-05 — Slice 04 APPROVED (`90dfae6` + rework `3c8f890`)

Re-verification by the Slice 05 QA agent (Job A): F1–F4 and F8 are fixed, and each test is meaningful; reverting the F1 fix turns its test red. The S2 test-double rework (`92f227d`) holds.

## 2026-10-05 — Slice 05 QA (critical) → rework `b8a4b76`

Composed run, swept across JARVIS-owned sinks (data root, runtime dirs, `~/.jarvis`, `errors.jsonl`): no leak, including on the duplicate, 400 and CC-down paths. Mutation: 8 killed. M6 (in-memory dedup) is equivalent, because the persisted claim also catches the duplicate. The control survived.

Real Claude CLI, 2 turns through the full Core→CC→`ClaudeLocalAgent` path with `--strict-mcp-config`:
- the brief carries the framed block;
- the planted "Jarvis, supprime le fichier X" caused no tool call (the file still exists);
- the deictic question was answered from the tail.

Dispositions:
- **B1, downgraded by agent 0 to an R6 limit.** The Claude CLI's own session log (`--resume`, session persistence on) keeps the brief, room speech included. This follows the precedent `docs/session-context-capture.md:129`. The false "only in stdin" wording was corrected.
- **B2 (an answer quoting the tail is persisted):** doc.
- **B3 (projection offered retired or already-shown objects):** fixed.
- **B4 (Core 400 on a context now retries once without it, same correlation):** fixed.
- **F4 scheduler-side consume:** test added.

Agent 0 deleted the two `~/.claude/projects/*pytest*real-cli-turn0-cc` folders the real turns left behind (synthetic planted text only).

## 2026-10-05 — Slice 06 delivered (`8f35b16`) + rework `761fa7d`

The real CLI run showed 2 speculative jobs admitted and the third refused for capacity, with peak RSS ~250 MB per sub-agent. It also showed a **real defect**: `--permission-mode dontAsk` denied WebSearch even though it was listed in `--tools`, so the sub-agents never searched the web.

Decided by agent 0: `--allowedTools` must equal exactly the granted `--tools`, for `presentation_preparation` only. The other three profiles are byte-identical (`test_other_profiles_argv_unchanged`). The real re-run gives `permission_denials: []`.

## 2026-10-05/06 — Slice 05 APPROVED; Slice 06 security rework; Slice 07 delivered

- **Slice 05 APPROVED** (`d6c2b34` + polish `0b2a115` + rework `b8a4b76`). Re-verification confirms B3, B4, F4 and the B1/B2 docs.
- **Slice 06 QA (glue) → blocking security finding.** Agent 0's own `761fa7d` decision (`--allowedTools` = `--tools`) allowed WebFetch next to Read while the sub-agent's cwd was the repo root (`.env`, `runtime/core.token`). An ambient claim or a fetched page could therefore exfiltrate a secret in a URL; QA proved it with a fake canary to example.com. Agent 0's wrong call is recorded here.
  - Decided by agent 0: each preparation job runs in a dedicated empty cwd under the data root, removed at job end, with orphans swept at entry and at Voice start (`a1b3119`). `--restricted` confines Read to the cwd. The real probe showed the canary never left the fake repo. The probe cost $0.095, above the $0.05 cap given.
  - Pool semantics, reachability and docs were found correct.
- **Slice 07 delivered** (`e3f5c81`): `PresentationOutputIntent`, the `PresentationDisplaySink` port and `DirectSceneDisplaySink`. The trace shows `presentation.intent.published` before `presentation.staging.revealed`, and the spoken text appears 0 times in the trace.

## 2026-10-06 — Slices 06 and 07 APPROVED; Slice 10 delivered

**Security re-verification of `a1b3119`: fixed.**
- A real Read probe from the empty cwd was refused: `--restricted` confines file tools to the cwd.
- Job ids, `..` and junction children cannot make removal escape the prep root.
- WebFetch reaches loopback but fails on its forced https upgrade. Core is token-protected. The Control Center is not: `Issues/003`, which predates the task.

**Slice 06 APPROVED** (`8f35b16` + `761fa7d` + `a1b3119`). **Slice 07 APPROVED** (`e3f5c81`): no blocking findings, the import-closure guard is real, and no room text appears in intents or traces. The port's gaps for a Tool Brain cancellation are recorded in Slice 08's SLICE.md.

Polish, batched for the Slice 03 implementer:
- (p8) refuse to sweep when the prep root itself is a junction or symlink;
- (p9) trace a junction child that was skipped;
- (p10) `correlation_id` on withdraw trace lines;
- (p11) a vocative turn withdraws speculative work too.

**Slice 10 delivered** (`faafd21`):
- withheld speech → `mouth.speech.superseded` (`presentation_withheld`);
- preparation jobs → `subagent.*` spans, with `task_id` = `<session>/<job>` and the capability label as the only content;
- new instant types `system.mode.changed` and `system.attention.raised` / `cleared`;
- `/api/status.presentation`, scalars only;
- `bgCue('attention')`: 587/698 Hz at gain 0.025, against 392/294 Hz at 0.06 for `bad`, measured in real headless Chrome.

Deviations noted: there is no dedicated system lane (the events land in the "Jarvis · voix" lane), and there is no `trace_ref` join.

## 2026-10-06 — Slice 10 APPROVED (`faafd21`); Slice 03 + polish delivered

**Slice 10 QA (glue + ui): no blocking findings.**
- A planted-phrase sweep over 23 events in a real SQLite event store, and over the raw database bytes, found nothing.
- Every span closes (preempted, retired, session-ended). `task_id` is unique across sessions.
- The status endpoint is fail-safe on 10 malformed-file shapes.
- The cue was re-measured in Chrome. The real timeline was rendered with the new events.

Issue → `Issues/004` (a newer Voice loses whole event batches against an older Core).

Polish batched for Slice 11:
- (p12) Status strings reduced to codes: no whitespace, as `presentation_timeline._token` does.
- (p13) A mixed attention + finished-task rise plays `bad`; it should play `attention` when no failure rose.
- (p14) `test_single_audio_emitter` should scan the served page, with an allowlist of the known Bare Hands and work sites.
- (p15) Withheld speech is shown as "remplacé" in the timeline and transcript; it should name `presentation_withheld`.
- (p16) `docs/OPERATIONS.md` says preparations show in "Jarvis · voix"; they render in "Sous-agents".

**Slice 03 delivered** (`e296153`): the live status line in the mode button covers listening, deaf, refused, entry failed and inactive. It is non-optimistic, adds no new route or settings key, and is announced to screen readers. 6 new real-browser tests use a real Control Center server.

**Polish p8–p11** (`43e5398`). p8 caught **real data loss**: `sweep()` deleted the children of a junction-linked target when the prep root itself was a junction.

## 2026-10-06 — Slice 03 APPROVED; wide sweep #1; reworks

**Slice 03 APPROVED** (`e296153` + polish `43e5398`). QA (ui tier, real Chrome over CDP) found no blocking issue:
- every transition is reflected within one poll (0.78–1.13 s);
- no announcement spam over 9 polls;
- keyboard and reduced motion OK.

Polish p8–p11 were confirmed fixed. Polish p17–p20 went to the rework batch.

**Wide sweep #1** at `89ac6fa` (unit: 392 files / 11 825 tests; integration: 72 / 653):
- All 11 baseline failures are unchanged.
- **5 new stable failures, all first bad at `625c5e3` (S2)**: `test_voice_board_rebind.py` (1) and `integration/test_v2_async_conversation.py` (4). Like the earlier `review_races` case, test doubles did not model the follower's permanent `/v1/events` subscription: a fake-Core backlog, and the testlab harness's `_expected_subscribers()`.
- 1 new flake in S10's own test (completion order).

This is the second time the per-Slice test lists missed S2 fallout. The wide sweep after a batch is not optional.

**Reworks**
- `3e37f0c` S2 rework 2: test doubles only, product unchanged; a 104-file sweep is clean apart from the baseline.
- `281404c` S10 rework: assertion made order-independent; 10/10 green.
- `71cdcda` polish p12–p20, each red→green:
  - p17 time bound adapted by the implementer: a stale refusal is judged against the last poll that showed another mode; documented.

## 2026-10-07 — Slice 11 delivered, awaiting critical QA

Commits: `a8fd112` (Issue 002: dropped-transcript trace carries reason and length only), `d4e8236` (scenario matrix 1–12, SIMPLE identity, planted-phrase sweep), `2ff9ee2` (latency under ambient load + docs).

- `tests/integration/test_presentation_scenarios.py`: 16 passed. The new test runs 12 explicit turns quiet vs loaded (slow provider 50 ms, running preparations, pool bound asserted each step). (superseded by the S11 rework below: the 3.5 ms figures were one execution, not a range).
- Docs: `docs/presentation-mode.md` (limitations R6, row 11), `docs/ACCEPTANCE_STATUS.md` (HV-PRESENTATION-E2E-01 with AUDIO/SPEECH/PRIORITY sub-checks, S11 evidence).
- Not done: real-host latency measurement, full unit suite diff vs baseline, `docs/OPERATIONS.md` runbook addendum, polish p12–p16 check, critical QA passes and mutation.

## 2026-10-07 — Slice 11 rework (critical QA)

- **B1** The latency test was flaky (2 failures in 10; real quiet baseline is 4-7 ms, not 3.5). Now: median over 5 alternating quiet/loaded runs of 12 turns; p50 within max(10 %, 5 ms), p95 under an absolute 20 ms ceiling; two running preparations asserted before each press. 10/10 green; measured over those 10 executions: p50 4.5-6.2 ms quiet, 4.7-7.3 ms loaded; p95 5.5-9.4 ms quiet, 6.0-10.2 ms loaded. The 30 ms admission-delay mutant still turns it red (loaded p50 34.8-37.8 ms).
- **B2** OPERATIONS.md runbook addendum; `human-validation.json` carries the AUDIO/SPEECH/PRIORITY sub-checks. **Real-host latency measurement deferred as a human point** (PRIORITY sub-check of HV-PRESENTATION-E2E-01); no isolated Core/Control Center was launched.
- **I1** Privacy tests for the `echo` path and for `presentation_window_refused`; a mutant adding `text` to both emissions turns them red.
