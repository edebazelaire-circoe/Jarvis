# 05 - Documentation levels and prerequisite gaps

The PM must re-evaluate these levels against current HEAD before dispatch. The levels below are planning estimates based on the inspected code/docs.

| Concept | Current estimate | Required by this task | Gap / action |
| --- | --- | --- | --- |
| Capture ownership and API | L3 | L3 | Preserve; update UI references only if routes/behavior change |
| Artifact registry | L3 | L3 | Preserve |
| Interaction mode | L3 | L3 | Preserve; update UI screenshots/entry docs if needed |
| Bare Hands lifecycle | L3 | L3 | Preserve |
| Bare Hands tool presentation | L2/L3 implementation-specific | L3 for new wheel contract | Establish wheel contract before migration |
| Mouse/Bare Hands arbitration | L0/L1 for this exact policy | L3 | New contract + pure tests + runtime validation |
| Control Center shell/layout | **L3 (S01)**: `docs/control-center-shell.md` (zones, tokens, a11y rules), `control_center_shell.js` (`JarvisShell`), conformance `tests/unit/test_control_center_shell_layers.py` | L3 for new shell | Done in S01; later slices update the doc, the sheet and the mirror in the same commit |
| Z-index/layer registry | **L3 (S01)**: single table in `docs/control-center-shell.md`, compared to every real sheet (page, Cosmos, modules); same ranks in both themes | L3 | Done in S01; reserved ranks 37/38/40/60 for S02/S05/S06 |
| Background notifications UI | L1/L2 | L3 | Separate category model from rendering; document semantics |
| Hidden-object visibility | L2/L3 in scene interaction | L3 | Preserve canonical owner; add eye control contract |
| Presentation rail | L2/L3 implementation | L3 | Document new right-rail behavior and retained actions |
| General active workspace rail | L0 | L2 minimum, preferably L3 | Define view model, source adapters, refresh semantics |
| Rich preview sourcing | L0/L1 | L2 | Define truthful fallback/caching/size bounds |
| `changed/unreviewed` status | unknown / likely absent in presentation rail | L2 before UI | Define owner if implemented; otherwise defer indicator |
| Bottom-left mode+Board context composition | L1 UI concept | L2 | Document composition without merging state owners |

## Level interpretation used here

- **L0:** idea only, no durable contract.
- **L1:** implementation/comments imply behavior but it is not a stable reusable contract.
- **L2:** explicit durable behavior/ownership/edge-case documentation exists.
- **L3:** behavior is documented, implemented behind clear boundaries, and protected by conformance tests/runtime evidence.

## Blocking rule

If Slice 00 finds that a concept relied upon by a later slice is below the required level, the PM creates or expands the prerequisite contract/test slice before implementation. Do not compensate for missing contracts with assumptions inside UI code.
