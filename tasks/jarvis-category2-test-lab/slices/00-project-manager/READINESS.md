# Slice 00 — Readiness report

- Date: 2026-09-17
- Branch: `task/jarvis-category2-test-lab`, created from `origin/main@f7e33ad` (no `dev` branch exists in this repository)
- Planning snapshot: `main@c33207281a` (2026-09-12), now stale for several files
- Handoff origin: remote (Drive `to-do/jarvis-category2-test-lab`). The Drive connector cannot move folders, so the Human must move it to `current`.

## Declared state

**`READY`** (2026-09-17, after Human decisions)

First declared `HUMAN_DECISION_REQUIRED`. The Human then chose:
- D1: fix `main`. The conflict resolution was pushed as `b86f228` ("fix: resolve committed merge conflict markers in realtime_audio"), and the task branch was replayed onto it. `jarvis.runtime.realtime_audio` imports again, and the narrow voice set passes (52/52 on the fix commit).
- D2: Workspace Task Type gate waived; `task_type` stays `null` in every Slice metadata file.
- D3: filesystem TestRun store under `runtime/testlab/` accepted by default.

## Blind audit — live facts that change the plan

### B1. `origin/main` does not import (blocking)
`jarvis/runtime/realtime_audio.py` has unresolved merge-conflict markers at lines 1095–1114 (`<<<<<<< HEAD` / `>>>>>>> origin/task/jarvis-conversation-observability-timeline`), committed in `c914f7d` ("trash") and `d7e9ca4` ("sauvegarde avant refresh") on 2026-09-17. `ast.parse` fails, so the voice stack, the async conversation harness and every voice test fail at import. `task/jarvis-constellation-scene-runtime` holds the correct 5-line resolution, which keeps both `_is_stream_already_stopped` and `_tool_status`.

### B2. Baseline with B1 resolved (scratch worktree, not committed)
Foreground chunks (host ~1.6 GB free RAM):

| Chunk | Result |
|---|---|
| narrow voice/replay/conversation-events set | 92 passed |
| unit 1/5 | 654 passed, **5 failed** |
| unit 2/5 | 697 passed, 1 skipped |
| unit 3/5 | 722 passed, 2 skipped |
| unit 4/5 | 694 passed, **4 failed**, 1 skipped |
| unit 5/5 | 953 passed |
| integration 1/2 | 181 passed, 4 skipped |
| integration 2/2 + e2e | 107 passed |

These 9 failures already exist on `main` and have nothing to do with the Test Lab. They must never be counted as regressions from this task:
- `tests/unit/test_agent_routing_settings.py` (3): `agent_routing.group_by_harness` missing, `KeyError: 'harnesses'`
- `tests/unit/test_routing_settings_screen.py` (4): page source assertions (`data-routing-drop`, substring not found)
- `tests/unit/test_brain_card_state.py` (2): menu item source assertions

See `Issues/main-baseline-broken-2026-09-17.md`.

### B3. Reuse obligations (canonical implementations that already exist)
Implementers must extend or wrap these rather than duplicate them:

| Need | Existing implementation | Slices |
|---|---|---|
| Bounded, strictly validated action DSL | `tests/replay/voice_replay.py` (schema `jarvis.voice_replay` v1; user/brain/scheduler/provider/owner/device/control families), fixtures `tests/fixtures/voice_replay/*.json` | 04, 06 |
| Scenario suite, evidence run keyed by `run_id` | `jarvis/runtime/voice_architecture_benchmark.py`, `benchmarks/voice/common_suite_v1.json` | 01, 02, 07 |
| Threshold sweeps, isolated one-shot subprocess with JSON result + timeout | `jarvis/runtime/speaker_benchmark.py` (`_run_isolated`) | 05, 07 |
| Worker process tree ownership (Windows Job Object) | `jarvis/runtime/owned_process_tree.py::OwnedProcessTree`; restart/backoff in `scripts/supervisor_v2.py` | 05 |
| Session metrics with caps | `jarvis/runtime/voice_metrics.py::VoiceSessionMetricRecorder` | 03, 07 |
| Trace summarisation | `jarvis/runtime/trace_summary.py` | 03 |
| Session evidence input | Conversation Events (`docs/conversation-events.md`, `jarvis/domain/conversation_event*.py`, export `jarvis.conversation-events.export` v1, `trace_ref` join keys) + `RuntimeJournal` `trace.jsonl` | 03 |
| Virtual conversation stack | `tests/integration/async_conversation_harness.py` (`voice_stack`, `FakeRealtimeSession`, `FakeAudio`, `ScriptedBrainBackend`, `FakeClock`) | 06 |
| Device diagnostics | `jarvis/runtime/audio_devices.py::SoundDeviceAudioDiagnostics`, Control Center `GET /api/audio/devices`, `POST /api/audio/test` (lock → 409) | 08, 09 |
| Atomic writes | `replace_with_retry` pattern used by `ControlCenter._write_settings` | 02 |

### B4. Corrections to the handoff's assumptions
1. **Harness is test-only.** It lives under `tests.` and needs a pytest `monkeypatch` object (it patches `realtime_audio.SoundDeviceRealtimeAudio`, `SpeechScheduler.RECONNECT_DELAY_S`, `protocol_server.web.AppRunner`). Slice 06 must move the reusable core into `jarvis/testlab/` behind a patch shim that doesn't depend on pytest. `tests/integration/async_conversation_harness.py` stays as a thin re-export, so its current tests are preserved unchanged.
2. **No settings layering exists.** Run-local overrides (Slices 05, 07) must use a per-run `JARVIS_RUNTIME_DIR` / `JARVIS_DATA_ROOT` directory with its own settings copy, plus `resolve_voice_composition(settings, environ=...)`. The permanent `runtime/control-center-settings.json` is never written.
3. **Storage.** `data/state/jarvis.sqlite3` is tracked in git, locked by the running Jarvis, and uses forward-only migrations shared with other active branches. Slice 02 must keep TestRun storage out of it. Default is a filesystem store under gitignored `runtime/testlab/`, with atomic writes and one directory per run.
4. **Process primitives.** `scripts/verify_release.py` forbids `subprocess.run(`, `os.system(` and `shell=True` under `jarvis/`. Workers must use `asyncio.create_subprocess_exec` / `Popen` + `OwnedProcessTree`.
5. **Control Center is aiohttp** with one `add_routes([...])` list and a single `control_center.html`, with JS files spliced in at markers (`*_SCRIPT_FILE` / `*_SCRIPT_MARKER`). JS logic is tested through node (`tests/conftest.py::page_logic`).
6. **Category 2 tooling mismatch.** Skills mention `pytest --include-category-2`, `category2` markers and `tests/category2_gate.py`, none of which exist in Jarvis. Locked decision 1 (native subsystem, not a pytest family) governs. Opt-in live tests keep the existing `skipif` + env-var convention (`JARVIS_LIVE_OPENAI=1`); no pytest markers are registered.
7. **Docs.** There is no CONTEXT.md, ADR directory or glossary. Canonical Level 3 docs follow the `docs/conversation-events.md` pattern. The Test Lab gets `docs/testlab.md` (contract doc) linked from `docs/ARCHITECTURE.md`.
8. **Incident transcript.** The 2026-09-12 transcript that Slice 12 relies on isn't in the handoff. Slice 12 must locate it (voice transcripts under `Documents\JARVIS`) or rely on live `runtime/trace.jsonl` sessions.
9. **Live device contention.** The workstation Jarvis continuously owns the laptop mic and speakers (continuous_brain). The resource gates in Slices 08/09 must detect and refuse contention with the running voice process, never steal the device.

## Conflict zones with parallel work

| Parallel work | Files | Affected Slices | Mitigation |
|---|---|---|---|
| `task/jarvis-constellation-scene-runtime` (117 commits ahead, uncommitted edits in `../sub-agents/jarvis-agent-01`) | `control_center.py` (+191), `control_center.html` (+171), `protocol/server.py`, `app.py`, `v2_app.py`, `realtime_audio.py` | 10, 11, 05 | Test Lab HTTP handlers in a separate `jarvis/testlab/http.py` (or `control_center_testlab.py`), registered with a single `add_routes` line. UI in `control_center_testlab.js` behind one marker + one dock button. CLI as `python -m jarvis.testlab` rather than a new `app.py` subcommand. Run a freshness diff against this branch before 05/10/11. |
| `fix/wave-amplitude-orchestration-color` worktree (**uncommitted** `speech_scheduler.py` +53, `voice_v2.py` +124) | speech scheduler / voice turn path | 06, 08, 12 | The Test Lab reads and drives these modules but must not modify them. Any needed seam goes through a Slice amendment after a freshness check. |
| Drive `current/jarvis-voice-turn-arbitration` (no local branch found) | voice turn arbitration | 06, 12 | Seed diagnostics assert current behaviour and never encode stale hypotheses. |

## Plan amendments

- **Order unchanged:** 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12. Slices run sequentially, because the host has too little RAM for parallel worktree test runs. 04 only depends on 01 and may be pulled before 03 if 03 blocks.
- **Slice 06 scope made explicit:** move the harness into production with a patch shim that doesn't depend on pytest (B4.1).
- **Slice 10:** the native Python API + CLI (`python -m jarvis.testlab`) come before the HTTP routes, and the HTTP routes live in a separate module (conflict mitigation).

## Verification commands

All run in the foreground and in chunks. Background runs and single-process full runs get killed on this host.

- **Narrow (voice regression guard, every Slice):**
  `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/integration/test_v2_async_conversation.py tests/integration/test_voice_replay_regressions.py tests/integration/test_voice_replay_safety_regressions.py tests/unit/test_v2_speech_scheduler.py tests/integration/test_conversation_event_rollout_gate.py tests/integration/test_control_center_conversation_events.py tests/unit/test_documented_routes.py`
- **Slice-local:** flat `tests/unit/test_testlab_*.py` and `tests/integration/test_testlab_*.py` (repo convention; decided in Slice 01).
- **Full baseline:** `tests/unit` split into 5 file chunks, `tests/integration` into 2, plus `tests/e2e`. Expected: the 9 known failures in B2 and nothing else.
- **Release static checks:** `scripts/verify_release.py` AST/lock checks with its pytest step stubbed (already covered by the chunked run).
- **Category 2 live/hardware:** only through Test Lab profiles behind explicit gates, never in the commands above.

## Decisions requested from the Human

- **D1 — Broken `main` (B1).** Recommended: commit the 5-line conflict resolution as a standalone `fix:` commit and push it to `main`, then rebase this task branch onto it. The alternative, a commit on this task branch only, leaves `main` unimportable for every other session and for a Jarvis restart.
- **D2 — Workspace Task Types.** No vocabulary exists in the repo or skills library. Recommended: waive this gate as for the settings and observability tasks, and leave `task_type: null`.
- **D3 (informational, no answer needed unless you disagree):** TestRun storage in the filesystem under `runtime/testlab/` rather than the shared SQLite database (B4.3).
