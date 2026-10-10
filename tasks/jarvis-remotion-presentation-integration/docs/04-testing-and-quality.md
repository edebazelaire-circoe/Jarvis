# 04 - Testing and QA doctrine

## Mandatory QA per Slice

`qa-verification` always. Add `code-review` for code, `runtime-validation` for visible/runtime code, and `agent-trace-analysis` for tools/prompts/agent dispatch. QA returns evidence and findings; PM decides approve, rework, extra Slice, Issues or Human escalation. A regression introduced by the Slice BLOCKS; never defer it as an unrelated Issue. Before Human tests, exhaust runnable machine tests.

## Baseline and reproducibility

At audit snapshot: branch SHA `16e3dc585a29a767af26440e5a4364c8d57d9065`; `main` comparison 129 commits ahead/85 behind; old LOG claims 16,739 passed, 10 failed, 0 errors, 40 skipped, all 10 failures baseline. The review did **not** run this suite locally (no cloned runtime, git network unavailable). This is not a passing test certification. PM must rerun at the completed branch head, compare against main baseline and record logs, environment, command, touched files and root causes of any red results.

## High-priority tests

1. Install-once: fresh installation, existing compatible install, partial install repair, restart, uninstall/disable without corrupting projects, Windows paths, npm process death, no duplicate module folders, no unmanaged global packages.
2. Engine policy: Remotion always chosen in ordinary agent flow; error is surfaced and no Slidecar code runs as fallback; only explicit UI human experimental switch enables Slidecar.
3. Preview: initial render, control prop update without MP4 render, HMR success and rollback on invalid edit, preserve scene/score/variant and stale CAS reject, handle concurrent subagents.
4. Score: soft cues, locked sequences, user presenter, Jarvis voice/presentation silence, no ambient arbitrary tool authority, detour/recovery, no duplicate effects.
5. Assets/exports: live Board ref in edit, ref moved/expired/deleted, freeze packages all required assets, MP4/still/PDF accurately attributed to parent source and variant, no absolute private file path leak, reverse lookup by Board.
6. Prefab shop: taxonomy consistent, engine support native/adapter/unsupported, detail parameters, license/upstream provenance, pinned versions, new-version notification, upgrade only into variant, opt-in publish, rollback/delete branch doesn't destroy source.
7. Security: reject hostile TSX, attempts at filesystem traversal, network exfiltration, executable dependency installation, untrusted URLs/archived templates; isolate processes/ports; resource limits.
8. Regression: ordinary Scene/Prefab, project Boards, captures, remote MCP plugins, existing Slidecar/HTML, browser fullscreen gesture and two-display restore.

## Performance acceptance targets (measure before locking numeric budgets)

- Props/controls patch should be visibly faster than source edit; no full MP4 render per tweak.
- Repeated edits should not leak Node processes, Chrome profiles or disk; verify before/after counts.
- Preview mount and HMR latencies measured on representative laptop, complex scene and real Windows client; PM captures pass/fail thresholds from observed baseline or user acceptance, never invents timing promises.

## Human validation

Check first install and error text; visible Player vs optional Studio; 2 monitor fullscreen plus Esc/return; voice-controlled edit of real presentation; reliable locked AV sequence; Prefab shop comprehensibility; Board file reuse and successful frozen export opening without source disk. No Human test is a substitute for code and integration QA.
