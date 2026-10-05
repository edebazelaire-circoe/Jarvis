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
