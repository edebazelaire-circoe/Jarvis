# S01 independent critical QA — 2026-10-30

Reviewed implementation `85f0d820` from a different agent. No product code, canonical documentation or Slice contract changed in QA. Recommendation: evidence supports proceeding to UI integration; PM owns disposition. No blocking finding identified.

## Scope and canonical reuse

Read Slice contract, documentation.md, IMPLEMENTATION.md, complete implementation diff, new unit/protocol tests and surrounding `SceneSelection`, scene object authority, batch planner, `SceneService` transaction/publication order and Core/Control Center transport fixtures. Applied qa-verification, code-review, runtime-validation and coding-guideline.

The new command fits existing selection ownership: strict explicit IDs, exact target identity, 1–512 unique typed geometry targets, all-or-none expected rectangles, canonical resolver eligibility, existing `_plan_object_write` authority/provenance, one `_plan_states` patch and existing service lock/persistence. `runtime` is denied before member resolution, including no-op geometry. `brain`/`user` explicitly moving pinned objects follows existing contract. Optional `pin=true` participates in the same patch; omission preserves current pins. No duplicate transaction, history, object renderer or route added.

Comparisons run before per-member writes and before duplicate detection. One stale member prevents all members, including earlier valid targets and proposed pins. All changed rectangles and batch ordering follow selection IDs, not arbitrary target list order. Failure leaves snapshot/patch/revision unchanged. Service publication remains after durable commit; existing refusal/persistence diagnostics are retained. Geometry-only undo preserves newer non-geometry data and pin state. Public payload field whitelist rejects execution/payload injection through targets; normal IDs/geometry/count diagnostics introduce no private model or prompt surface.

## Executed evidence

Interpreter `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe`; cwd `C:/Projects/jarvis/mov1`. All pytest commands used `--assert=plain --tb=short -q`.

- `qa/test_adversarial.py tests/integration/test_scene_layout_transport.py`: **7 passed in 4.07 s**. Independent cases: a later stale member prevents earlier valid move+pin; forbidden extra target payload rejected; real SQLite/Core HTTP commit survives controlled sandbox Core stop/start, then compared undo succeeds, retains pins and refuses replay without revision change. Existing protocol tests verify one revision, 400/403/413, large-patch relay omission and normal patch readback.
- Six sequential foreground mutations: **6 killed**, each by an assertion in the intended scenario. Details, failing output and restored SHA-256 hashes: `mutation-results.json`; reproducible runner `mutations.py`.
- After exact byte restoration, `tests/unit/test_scene_layout_selection.py qa/test_adversarial.py`: **32 passed in 3.47 s**. Includes serialized concurrent comparisons, persistence failure/diagnostic, max512, JS patch parity and independent restart case.
- `git diff --exit-code -- jarvis/domain/scene.py jarvis/domain/scene_batch.py jarvis/core/scene_service.py`: clean after mutations. No surviving temporary code changes.

## Mutation matrix

| Mutation | Observed detection |
| --- | --- |
| Remove stale-geometry rejection | No-op stale compare test refuses successful/duplicate outcome |
| Remove exact selection/target identity check | Mismatched wire selection unexpectedly accepted, test fails |
| Bypass operation-level runtime authority | Runtime no-op test detects changed refusal authority |
| Pin despite omitted pin request | No-op command unexpectedly creates a patch/revision |
| Allow unplaced target | Explicit unplaced member no longer refuses, test fails |
| Publish in-memory state before persistence | Failed commit test detects memory/disk divergence |

Runner initially stopped before fourth mutation because its text anchor matched two functions; exact source restoration still ran. Narrowed QA anchor to the layout-specific loop and resumed remaining three. Six actual mutations total; no product defect implied by this harness error.

Each case uses a fresh Python subprocess and changes the source byte length, invalidating timestamp/size-based `.pyc` caches even if timestamps share a second. All six outputs fail at the intended behavioral assertion, proving mutant code was imported; restored baseline then passes. The runner explicitly enforces length-changing mutants for reproducibility.

## Findings

None established in this Slice. No model/provider/runtime behavior changes and no new user-facing wait state; agent-trace-analysis/real model calls are not applicable to this domain/protocol addition.

## Flagged integration requirements

- Existing 65,536-byte request budget can reject 512 compared rectangles although 512 unconditional short-ID targets may fit. Domain max does not promise wire capacity. This is documented accurately. S05 must preflight both operation and reverse compare encoding (including relay canonical floats), surface refusal, and never chunk or record an unsendable undo.
- Representation/visibility changes are intentionally not part of Core's geometry comparison. S05 owns invalidating relevant transient undo entries. Undo must omit pin when restoring geometry so newer pins remain unchanged.
- New refusal `geometry_changed` must become an actionable UI message in S05; S01 deliberately leaves the browser mapper unchanged. No blanket generic refusal is acceptable at convergence.

These are downstream contract obligations, not S01 defects or scope expansion.

## Missing / residual risk

No full repository suite (reserved S06), browser organization/undo flow (S05), real user data or user's live runtime used. Runtime evidence is a real isolated SQLite/Core HTTP stack and Control Center TestServer, not a production deployment. No broad performance campaign; max512 conformance case passed. PM independently ran additional focused checks separately; their results are not represented as this reviewer's own executions.
