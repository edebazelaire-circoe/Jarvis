# QA-1 - Slice 17 Scene-Local Variants (standard tier: qa-verification + code-review)

Reviewed: detached worktree `C:/Projects/jarvis/bipq` at `9c954ed6` (HEAD checked before and after; clean `git status` after every mutation). Diff `bf3450cb..9c954ed6` (4 commits). No product code modified. One temporary file I created in bipq (`tests/unit/zz_adv_test.py`) was deleted; scratch scripts live in my scratchpad only.

## Verdict recommendation: REWORK (small, one BLOCKING)

One BLOCKING defect in the core `select` algorithm (set-size check makes a legitimate select refuse). Everything else is POLISH/ISSUE. The permutation itself is sound (see property test).

## Evidence run (all one file at a time, foreground)

- 7 new files: domain 37, service 24, playback 10, retention 4, routes 14, docs 8 passed; crash drill 4 passed, run 3 times (3x green).
- Touched/related files, all green: presentation_studio_{edit 85, edit_service 59, edit_overlay 8, edit_routes 18, edit_docs 6, history 23, history_service 37, history_routes 15, history_docs 8, history_crash 6, playback 257, playback_service 39, playback_routes 13, playback_docs 9, playback_rework 18, scene 120, scene_service 26, score 129, score_edit 6, score_service 34, store 32, service 25, routes 26, docs 21, crash 6, domain 142, recovery 23, variants_{domain 79, service 41, routes 17, playback 4, store 12, recovery 15, crash 15, docs 13}}, prefab_retention 41, conversation_events 142, control_center_timeline_js 72, documented_routes 3, v2_architecture 8, schema_migrations 8.
- Not run: browser/player tests (`player_browser*`, `player_js`, `stage`, `art_direction*`, `roles`, `durability`): outside the touched surface.

## Property test (mine, different seeds)

Script (scratchpad `prop.py`): 3-scene deck through the real `apply_ops`, seeds 5000..5149 x 400 steps. Random create (incl. from a variant), select (25% `drop_others`), delete (incl. selected), rename, live edit, undo, redo; undo/redo replay the recorded `plan.inverse`. Asserted: content multiset conserved by select/rename; `drop_others` leaves exactly one content, taken from the prior multiset; delete removes exactly one; exactly one entry has no `content`; refusals leave the document byte-identical; every undo is byte-exact vs the pre-op document; full unwind returns the initial deck byte-exact; other scenes never change. Result: PASS, no violation. `current_id` vs `RUNTIME_KEYS` naming: documented and consistent in the 09-canonical-names section 16 and the contract.

## Findings

### BLOCKING

B1. `select` can be refused for size although it is a pure permutation. `jarvis/domain/presentation_studio_scene_variants.py:select` (L~233) rebuilds `SceneVariantSet`, whose `__post_init__` (L~172) re-checks `MAX_SET_BYTES` (40 KiB). The cap counts only STORED contents; the live content is not counted. Select moves the live content into the stored side, so a bigger live content than the target's pushes the set over the cap.
Repro (domain, `size.py`): scene with 5 stored copies of 7 KB (set 36.5 KB); live content grown by editing to 14 KB; `select(other)` -> `EditRefusal presentation_studio_limit_reached: the scene variants of one scene take 43567 bytes, at most 40960: delete one`. The user did nothing that adds bytes; the only way out is to delete a variant (loses content). Reachable by the normal flow create copies -> edit the live scene (live edits are not counted at all). Contradicts the documented "select is a permutation... nothing lost" and the same size claim ("a set operation's undo record always fits").
Fix direction for PM: either count the live content in the budget at every write (create and live edits), or make select size-neutral (allow when result <= max(cap, previous size)) and re-derive the 64 KiB undo bound from per-content caps rather than from one set cap. The existing tests do not grow the live content after creating variants.

### POLISH

P1. "Lightweight" is not a delta: each variant stores the WHOLE scene content (pin, props, data, controls, anchors). Measured through the real service (`Env`/`World`, fixture scene ~1.5 KB, 7 extra variants per scene): 12-scene deck: file 19,248 B -> 208,633 B (x10.8, 81% of the 256 KiB `MAX_DOCUMENT_BYTES`). 64-scene deck (100,732 B base): the 11th scene refuses with `limit_reached`; only 10 scenes can hold 8 variants. A 12-scene deck with ~3 KB scenes cannot hold 8 variants everywhere. The per-scene 40 KiB set cap is never the binding limit (12 x 40 KiB >> 256 KiB); the document cap is. It is typed and the file stays valid (tested), and the docs state sizes, but "no duplication unnecessarily" (SLICE step 3) is only met at the deck level (rest of the deck is not duplicated), not at scene-content level. Cheap mitigation: `describe.limits` could also report document bytes left; or store controls/anchors as a reference when equal to the live one.
P2. The 64 KiB undo bound is real but thin and not tested at its worst case. All set operations (create/delete/restore/drop_others) carry at most one set <= 40,960 B, so they fit (measured 39,974 B for drop_others, 39,882 B for delete). `scene.remove` carries live + set: max live content measured 23,277 B (payload 16 KiB + 32 controls + 16 anchors, which are outside the payload cap) + 40,960 B ~ 64.2 KB before wrapper -> the margin is under 1 KiB and a worst-case test does not exist; measured realistic worst 59.6 KB. If it overflows it degrades to `available:false/too_large` (the existing Slice 08 "Trou"), not corruption. Add a worst-case test (title/section at max, 32 controls, 16 anchors) or lower `MAX_SET_BYTES`. ops_size uses `ensure_ascii=False` like canonical_json, so no 3-6x escape inflation (checked).
P3. Test gap, mutation M4 survived (see below): nothing tests that a refusal INSIDE `create_branch(transform=)` spends no variant number. The code is right today (transform runs before `new_id`/number allocation, `jarvis/core/presentation_studio_variants.py` L~300); the claim is untested. A transform refusal is reachable via B1 or a race between the pre-checks and the lock.
P4. Module sizes: `jarvis/domain/presentation_studio_edit.py` 814 -> 1030 lines; `jarvis/core/presentation_studio_playback.py` 973 -> 1060 lines (preview state could be its own small module). New modules are small (307/233).
P5. `describe.limits.bytes_used` counts only the stored contents (the live one is excluded), so it under-reports what B1 needs; revisit with B1.

### ISSUE (non-blocking, for the PM)

I1. Score-regression refusal (`C.SCORE_INCOMPATIBLE`) only applies when `step is None` (a fresh edit) and the request contains a `scene_variant.select` (`jarvis/core/presentation_studio_edit.py` ~L229). Reasoned, not run: an undo/redo of a select replays `select` and skips the check; because score saves are not in the Slice 08 ring, sequence select(B) -> save_score (valid against B) -> undo select can leave the score with unresolved references. History already reports `score_problems` on undo/redo (Slice 08 behaviour), and the docs state "undo/redo never blocked", so this is by design, not a Slice 17 regression. `drop_others` and multi-op batches ARE checked (final plan scenes); delete/rename/create/restore_set do not change live content so need no check. No wrong refusal found (comparison is against pre-existing problems only).
I2. `scene_variant.restore_set` is exposed to both actors as a normal op and, with `existing=None`, accepts any valid set (provenance fields such as `created_by` / `source` can be forged by a caller). No integrity issue (contents are validated), only provenance trust.
I3. `show_preview` on stage failure: `_stage.show` raising leaves no `_preview` recorded but the stage may already show the preview payload until the next sync; edge only, a stage fault is surfaced as an error.

## Checked and OK

- Contract coverage: create/rename/select/delete; copy from current (or from another local variant); preview in memory; promote into the current state (`drop_others`) and to a full presentation variant; provenance (`source`, `created_by`, `created_at`, promote rationale with scene and variant ids, parent/sources); invisible in the top-level graph (test + my promote run: numbers 2,3 exactly one new node per call).
- Edit integration: all five ops are `OpName`, tier `structure`, both actors, single write path `_write_variant -> _persist_variant`, revision CAS (my 20-way concurrent select on one basis: 1 applied-and-changed, rest stale/no-op, revision 3 -> 4, exactly one `content is None` entry). `edit_committed` carries op names only: event and journal rows contain no label/rationale/psx id (test + review of traces).
- Labels (my adversarial run): NUL, newline, tab, U+202E (RLO), leading space, empty, 41 chars all refused `invalid`; Arabic, CJK, combining accent, emoji accepted; duplicates refused case-insensitively incl. casefold (`STRASSE` vs `straße`) -> `already_exists`. RTL letters fine, bidi controls rejected (isprintable).
- Delete selected -> `scene_variant_protected` (409). Promote twice -> two branches. Promote with unknown id -> `unknown_scene_variant`, no number spent (next promote got 4).
- Preview: writes nothing (tree digest tests), stage only for a paused run of that variant, exits on cancel/timeout/any playback command (even refused)/foreign commit/stop; every exit repaints canonical. `timeout_s` bounds 1..120 enforced. My race (preview timeout 1 s vs concurrent committed edit at 0, 0.5, 0.95, 0.99, 1.0, 1.01, 1.05 s): in all 7 cases `_preview is None`, stage shows the committed value, no error row.
- Pins: `held_pins()` and `variant_pins` include stored variants; `pins_of` covers `scene.add` with a set and `restore_set`; real 01a retention test green; mutation M5 caught (3 files fail).
- Branch copy/archive/restore: tests green; branch carries the set, source file hash unchanged by promote.
- Schema: variant v3 (identity step, key absent when unused, v2 JARVIS refuses v3); fixture `variant.v3.json` added; merge rule with Slice 06 documented and coherent (second merger renumbers to 4, `held_pins` is the one function to extend).
- Routes / relay / client parity: 4 Core routes, 4 relay routes with `actor` forced to `user` in the relay, 4 client methods, error envelope reused; documented_routes and docs-parity tests green.
- Crash safety: one atomic variant write, crash drill 3 x green.
- DOT_TYPES fix `d15e7f72` (`jarvis/runtime/control_center_timeline.js` ~L257): correct and minimal. The merge had left two array tails (`...'variant_changed']);` and `...'playback_changed']);`) = SyntaxError; the fix merges them into one list containing `edit_committed`, `variant_changed`, `playback_changed`, 2-line change, `control_center_timeline_js` 72/72 green.

## Mutations (5, foreground; each restored by `git checkout -- .`, clean status verified)

| # | Mutation | Result |
| --- | --- | --- |
| M1 | select stores the TARGET's content in the old slot (loses live content) | KILLED (domain: 1 failed) |
| M2 | `drop_others` keeps the set (`final = picked`) | KILLED (domain 1, service 1 failed) |
| M3 | preview shown on stage while the run is playing (pause guard off) | KILLED (playback 1 failed) |
| M4 | `create_branch` applies the transform AFTER the number is allocated | SURVIVED (service 24 passed) - P3 |
| M5 | `held_pins()` ignores stored variants | KILLED (retention 2, service 1, domain 1 failed) |
"preview writes" mutation not done (no single cheap injection point; the tree-hash tests were reviewed instead).

## Answers to the implementer's 3 open questions

1. Hard refusal `score_incompatible` on select: acceptable for this Slice (preview stays available, the message names the first dangling reference and the fix). Consider an explicit "fix score" path or a force flag in Slice 18/19; note I1 (undo bypass is by design).
2. No durable trash for deleted local variants: acceptable. The ring is memory-only and the docs say so plainly; promote-to-variant is the durable alternative. Keep the "after a restart a deleted local variant is gone" sentence in the UI copy of Slice 18.
3. Slice 06 takes v3, Slice 17 renumbers to v4 at merge: agreed. The renumber is mechanical (UPGRADES key, constant, fixture `variant.v3.json`, tests pinning `CURRENT_VERSIONS`); PM should add it to the merge checklist, plus Slice 06's `variant_pins` must call `held_pins()`.

## Not verified

- Browser/UI (none in scope). Brain/voice tool exposure of the new ops (Slice 21).
- Undo-after-score-save bypass (I1) reasoned from code only.
- Live-Core manual drill (real stage window); only the fake-stage `Rig` tests ran.
- Worst-case `scene.remove` undo size to the byte (P2) - estimated, not constructed.

## Flagged

- None pre-existing worth a separate issue; the `ops_size`/`canonical_json` pair both use `ensure_ascii=False` (consistent).
