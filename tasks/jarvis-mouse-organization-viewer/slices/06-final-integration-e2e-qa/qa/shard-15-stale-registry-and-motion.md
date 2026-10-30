# Shard 15: remove four proven-stale registry entries

Frozen root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc` completed shard 15:
**1277 passed, 1 failed, 7 skipped**, zero unknown failures, no session
problems. Gate duration: 1571.6 seconds; pytest duration: 1568.32 seconds.
Original `qa/evidence/shard-15.log` lines 230–233 show all four parameters of
`test_control_center_shell_browser.py::test_one_geometry_and_one_rank_set_for_both_themes`
passing: `[size0]`, `[size1]`, `[size2]`, `[size3]`. The JSON consequently
lists exactly those four as `stale_known_failures` and correctly stays red.

## Exact metadata correction

Removed only those four `kind: failing` entries from
`tests/known_failures.json`. The diff is exactly four deleted lines, zero
added lines. Every other entry, its order and all outer metadata are
preserved; the `test_reduced_motion` entry remains byte-for-byte unchanged.
No new ignore or known-failure entry was added.

Validation directly imported and called production
`scripts.release_test_gate.load_known` before and after the edit. It accepted
the schema, required fields, types, dates and unique IDs: **28 → 24 entries**.
Assertions also compared the complete parsed document with the original
minus exactly these four entries, and compared every remaining loaded entry
for equality. See [retained validation output](shard-15-registry-validation.log).
`git diff --check` passed. No pytest, Node, browser, model or product runtime
was executed. Actual complete browser passes from the canonical shard are
the evidence for removal; they were not repeated.

## Reduced-motion failure: limited source check

The one known actual failure is `test_reduced_motion` line 767. Both
`moving_wheel` and `moving_pop` report only these Boards controls:

```text
#boardsBack transition color, border-color
#boardsClose transition color, border-color
#boardsNewSession transition border-color, color
button.bd-kindpick transition background (three entries)
#boardsKindRetry transition border-color, color
#boardsCreateTitle transition border-color
#boardsCreate transition border-color, color
```

The test module and `control_center_boards.js` are unchanged between baseline
`c0858a80` and frozen root. Their source remains consistent with this existing
known failure: `.bd-act` declares color/border transitions (line 955),
`.bd-kindpick` a background transition (972), and `.bd-bigfield` a border
transition (1010). The Boards reduced-motion override (1055–1060) disables
other named transitions but does not list these classes. This read-only
inspection did not execute or newly diagnose the baseline case.

The shared `_status_centre_browser.mjs` **has changed**, adding atomic layout
fixture handling and input support, including native-dialog Escape handling.
It was not represented as byte-identical. The measured failure values above
are entirely Boards selectors, with no new viewer/grip selector in them.

The `MOVING` audit explicitly excludes `#sceneLayer` descendants and examines
shell controls/Boards/popovers/toasts; this scenario does not open the new
object viewer. Therefore it is not a standalone reduced-motion proof for
resize grips or an open viewer. Separately inspected source shows the new
grip geometry rules do not introduce an animation/transition, and the object
viewer has its own scoped reduced-motion override (`.jvov *`, line 90). No
broader runtime claim is inferred from the known Boards failure.

Original raw shard evidence stays red/stale and unchanged. Root remains
immutable during the complete gate; integrate this metadata correction only
after the gate, as assigned by PM.
