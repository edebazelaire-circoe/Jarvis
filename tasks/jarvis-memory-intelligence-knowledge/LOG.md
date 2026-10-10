# Execution Log - jarvis-memory-intelligence-knowledge

Agent 0 (orchestrator). Last update 2026-10-07 (session paused on the Human's request, to resume later).
Binding documents: `docs/06-resolved-architecture.md` (sections 1-5 + amendments A1-A3 in section 6), `slices/00-project-manager/READINESS.md` (state READY, audit, baseline, inherited reds).

## Where things are (read this first)

- Task branch `task/jarvis-memory-intelligence-knowledge` in `C:/Projects/jarvis/sub-agents/jarvis-agent-01`, based on `origin/main` 5ee4345. Tip `cf5b306b` + the commit that adds this log. Working tree clean. Not pushed, not merged into main (needs the Human).
- **`origin/main` has moved: 3 commits ahead (9721b3ca) since the task base.** Before close-out: `git fetch`, `git rev-list --left-right --count origin/main...HEAD`, then merge `origin/main` INTO the task branch (never the reverse), re-run the wide sweep.
- Drive: handoff folder `1V5doC6rNlTqIbFmjKdgwQPxS1baWHpOM` is still in `to-do` (queue IDs: to-do `1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm`, current `1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`, done `16yBLZRVOEbfDAN_CRh5722bkN46IUmo7`). The Drive connector cannot move folders: **the Human must move it to `current`** (check H1). Do not move it to `done` before explicit acceptance.
- Mirror caveats: `task.json` belongs to another handoff (`jarvis-subagent-routing-continuous-self-dev`), ignored. Original SLICE.md files were generic templates; each now has a pointer to the binding contract in `docs/06-resolved-architecture.md` section 3.

## Slice status

| Slice | State | Branch / commits (merged into task branch unless stated) |
| --- | --- | --- |
| 00 PM readiness | DONE | S0 `00a2464`, `8abbb5e`, amendments A1 `3d2e48d`, A2 `709e6670`, A3 `cf5b306b` |
| 01 contracts | DONE (QA reworked) | `dac25703`, `fe8e54b2` |
| 02 canonical store | DONE (critical QA reworked) | feat/mik-s02 `ac6c1fb9`, `436d5b45`; merge `9bd0d6e` |
| 03 hybrid retriever | DONE (critical QA approved + polish) | feat/mik-s03 `e17f42e1`, `4c10b411`; merges `694735b`, `65f05ca` |
| 04 consolidation | DONE (critical QA approved + polish) | feat/mik-s04 `052ecdbd`, `7f483f4b`, `8d2451ef`; merge `7ce4b24` |
| 05 V2 Brain integration | **IN REWORK, not merged** | feat/mik-s05 (worktree `C:/Projects/jarvis/b05`): `9384062c` (QA verdict REWORK), `b2c7bb2f` (merge of task tip), `5f0efa5a` WIP rework, UNVERIFIED (agent stopped mid-edit, tests not run) |
| 05b memory tools MCP | TODO | needs 05 (+ 09 knowledge tools) |
| 06 Tencent adapter | DONE (critical QA reworked) | feat/mik-s06 `62bb3b38`, `a9e4f1e0`, `89d34e61`; merge `55301ce` |
| 07 Wiki | DONE (QA reworked) | feat/mik-s07 `3bfbbc1d`, `a4884796`; merge `68956ca` |
| 08 CodeGraph | DONE (QA approved + polish) | feat/mik-s08 `a1ca1634`, `449d07bb`; merge `5bf46fb` |
| 09 skills + loadouts | DONE but DORMANT until wired (critical QA reworked) | feat/mik-s09 `870b1f23`, `ef6b549d`, `9d5e431d`; merge `7c3078b` |
| 10a settings model | DONE (critical QA reworked) | feat/mik-s10a `e8930104`, `9428c593`; merge `6b27385` |
| 10b settings endpoints | TODO | needs 05, 06, 07, 08, 09, 10a; must show `downgraded` in status; add `memory.tencent.service_id` / `allow_private` (see P7 below) |
| 11 settings UI | TODO | needs 10b |
| 12 Memory Center UX | TODO | needs 02, 03, 04, 06-09, 10b; extends the existing "Sessions & Boards" view (`control_center_workspace.js`) |
| 13 critic-agent validation | TODO (QA only) | needs 11, 12, 05b |
| 14 e2e / rollout / docs | TODO | last: fix SECURITY.md/ARCHITECTURE.md/OPERATIONS.md V1-memory claims, rebuild/backup drills, sidecar outage drill |
| Integration step | TODO | see "Integration step" below |

Waves left (max 3 concurrent agents, host RAM is the limit): finish 05 -> {integration, 05b, 10b} -> {11, 12} -> 13 -> 14.

## Slice 05 rework list (what the stopped agent was doing)

QA of `9384062c` (real Core turns + real Brain traces, about 1.6 USD) found plumbing solid but recall content poor. The WIP commit `5f0efa5a` edits `memory_context.py`, `memory_service.py`, `memory_wiring.py`, `brain_context.py`, `memory_routes.py`, `memory_brief.py`, `memory_composition.py`, `domain/memory_settings.py`, `runtime/memory_settings.py` (379 insertions / 90 deletions, untested). To resume: new implementer on `feat/mik-s05`, run the tests first (`test_memory_context.py`, `test_memory_brain_injection.py`, `test_memory_routes.py`, `test_memory_settings.py`, `test_v2_architecture.py`), then finish:

- **B1 blocking:** injected recall text is the 18-token FTS5 snippet (`markdown_memory.py:~397`): duplicated `# Title`, `...` cuts, dates lost. After recall `store.get()` the kept items and use the canonical body (strip title line/front matter), clip to 400 chars UTF-8-safe, ellipsis only when clipped. Regression: Orion note ("...Lyra (code ORION-47) et la livraison est prevue le 14 mars...") must arrive intact; tests need notes longer than 18 tokens.
- **B2 blocking:** no relevance floor (lexical OR ranks stopwords; "12x12" injected 3 unrelated notes incl. the hostile one). In `build_query` drop FR+EN stopwords and tokens < 3 chars, borrow the previous turn only when < 2 content tokens remain, skip recall if no content token; dedupe recall vs profile; require a lexical match or semantic similarity above floor.
- **P1** keep the profile on degradation (recall_timeout, index_syncing): separate profile and recall tasks. **P2** Brain manifest uses the Slice 09 `brain` loadout, `brain_policy()` derived from that single source. **P3** malformed/traversal note id -> 400 `invalid_request` (not 503), no error-level `errors.jsonl` row, no Python class names in 5xx messages. **P4** `BrainMemoryContext.bounded` clips `error`; remove the dead 3 000-char cap; recall-explain backstop timeout. **P5** shorter item provenance labels. **P6** warm the lexical leg at wiring start. **P7** wire Slice 06 into Core (`register_retriever`, `register_write_listener(sink.notify_written)`, start/aclose; settings `memory.tencent.service_id`, `memory.tencent.allow_private` default false; zero network when disabled). **P8** tests for the 3 surviving mutations (`bounded(max_items=10)`, superseded filter in `_profile_sync`, `NotifyingStore.revise` notifies index + listeners) and an `app.py` `_run_core_v2` wiring test.
- Then re-run critical-tier QA in its own worktree (QA brains need `--strict-mcp-config`; isolated Core on other ports; never the Human's live JARVIS 17653/17654).

## Integration step (separate commit after 05 merges)

Slice 09 wiring (`register_knowledge`, `set_loadout_resolver`, `write_loadout_snapshot` at startup and on every skills/wiki/loadouts change, role markers `[reviewer]`/`[research]` taught in `PROFILE_RULE` with prompt-catalog tests); Slice 04 consolidator injection into the maintenance worker + candidate routes (list/get/decision) in `memory_routes.py` (see `docs/memory.md` "Wiring"); real sub-agent traces `code`/`reviewer`/`research` (Slice 13).

## Decisions taken (all recorded in the architecture doc, section 6)

Zero schema migrations (canonical = Markdown, derived = disposable files; a v9 needs a PM amendment); task type gate waived; memory root unified at `<data_root>/memory` with copy-only adoption of `./data/memory` (H2); consolidation default `manual`, `auto` only settles current-run candidates and refuses without dedup (`auto_needs_dedup`); cosine floor 0.18; loadouts owned by Slice 09; Tencent wire shapes pinned to upstream MemoryCore v3 @0468a2a but never run against a real sidecar.

## Baseline and inherited reds (at 5ee4345; see READINESS.md for the table)

10 failures, not this task's: `test_app.py` (1), `test_barehands_interaction_js.py` (2), `test_brain_delegation.py` (1), `test_interaction_mode_hud_browser.py` (1), `test_scene_group_drag_js.py` (1), integration testlab audio/hardware/live runners (4). `test_app.py` and `test_brain_delegation.py` re-confirmed identical on the baseline checkout. **No wide sweep has been run on the merged task branch yet**: do it at close-out (foreground chunks, `JARVIS_DATA_ROOT` scratch, baseline worktree `C:/Projects/jarvis/bwt2` at 5ee4345 is still there).

## Evidence and numbers worth keeping

Lexical p95 20 ms at 5 000 notes; hybrid p95 43-58 ms; first search after a write 1.5 ms (numpy, 2 000 chunks); pure-Python 20 000-chunk scan 451 ms (over the 250 ms leg budget, numpy needed for large vaults); cold index sync 10-25 s for 2 000 notes (turns are degraded `index_syncing` meanwhile); real extractor 5 calls 0.034 USD, 4/4 valid proposals; memory block adds about 8 ms to a Core turn; real Brain traces for Slice 05 in the session scratchpad (lost with the session, summarised above).

## Human checks still pending (architecture doc section 5)

H1 move the Drive folder to `current`; H2 confirm memory-root unification and the tracked `data/memory/Jarvis-V1.md`; H3 consolidation defaults; H4 embedding disclosure (remote embeddings opt-in, private excluded) and cosine-floor calibration with a real model; H5 real voice session, felt latency with recall on/off; H6 optional real Tencent sidecar run (`JARVIS_TENCENT_LIVE=1`, never run so far); H7 Memory Center walk-through by a non-author; H8 loadout sanity on a real sub-agent run; H9 backup/restore on a second data root; H10 Wiki import allowlist sign-off.

## Environment notes for resuming

- Python: `C:/Projects/jarvis/sub-agents/jarvis-agent-01/.venv/Scripts/python.exe`; in other worktrees set `PYTHONPATH=<worktree>` (the venv editable install points at agent-01).
- Worktrees: `b05` kept (Slice 05 WIP). Removed after merge: b02, b03, b04, b06, b08, b09, b10a, bmq4 (branches `feat/mik-s02..s10a` remain). `b07` could not be deleted (permission denied: remove with `git worktree remove --force C:/Projects/jarvis/b07` later). Shared reuse worktrees `bqa`, `bqb`, `bwt`, `bwt2` belong to other sessions too: use uniquely named QA worktrees (`bmq1`...).
- Sub-agents: foreground pytest only, one file at a time (RAM), no `git stash`, tell implementers about the inherited reds. Interrupted or stopped agents can be resumed from their transcripts by SendMessage only within the same Claude session; after a restart, start fresh agents from this log and the branches.
- The Drive MCP drops connections: retry the identical call, sequentially.
- This machine's `data/state/jarvis.sqlite3` stays untouched; this task adds no migration.

## 2026-10-09 - Fast close-out (user asked for speed, light testing)
main merged into the task branch (fed66732 then the IPS fast-forward is NOT in this branch yet: merge main again before landing). Merged: 05 (rework B1/B2/P1-P8, `15ab081f`), 10b (`ee17f1b5`), integration (09 wiring + 04 consolidator + candidate routes), 11 (`a979cd2b`), 12 (`6827380a`), 05b (`7bb383fd`, `5f38e5ed`; conflicts with 10b/12 resolved in memory_routes/memory_relay/control_center), 14 docs only (`8ab486a4`). Slice 13 (critic-agent validation) SKIPPED. No QA tiers re-run, no mutation testing, no wide sweep.
Targeted sweep (one file at a time): 42 files green, 0 failures, then stopped by the host (low memory) at test_mcp_plugin_store_sqlite.py; the rest not run. Not verified: test_brain_capability_parity has 1 red (`jarvis-display` `ui_intent_publish` missing from brain prompt), not compared to baseline. UIs 11/12 never seen in a real browser. 05b never run with a real Brain. Backup/sidecar drills written, not rehearsed. Human checks H1-H10 still pending.
