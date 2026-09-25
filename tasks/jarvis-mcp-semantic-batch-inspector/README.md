# Jarvis — MCP semantic batches and human inspector


## Purpose


This handoff turns the MCP audit into an implementation task. The target is not merely to make every UI action technically reachable from MCP. The target is to make one coherent user intent map to one coherent semantic operation, with clear domain meaning, minimal model-to-tool calls, and no hidden N-command fan-out when the user experiences the action as atomic.


The second deliverable is a human-facing MCP inspector in the Control Center. It must make the actual Jarvis MCP surface understandable without dumping a raw `tools/list` payload into a wall of JSON.


## Project identity


- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Source branch inspected: `main`
- Source commit inspected: `ddcdb71e17d7be76236c7dd6ab070af90e8f7d65`
- Freshness check date: 2026-09-24
- Intended Drive destination: `Jarvis/task/to-do/jarvis-mcp-semantic-batch-inspector/`


## Locked product intent


1. A user-level scene intention must be expressible as a single semantic operation where the action is conceptually indivisible.
2. Scene batching must become real Core/domain batching: selection resolution, validation and mutation occur against one snapshot, producing at most one scene revision/patch for the operation.
3. Constellation membership must have one canonical domain meaning shared by MCP, UI and future Bare Hands behavior.
4. Selection itself becomes a domain concept rather than an MCP-only convenience.
5. MCP calls should become semantically denser. Do not replace one generic tool with dozens of setting-specific tools simply to make the inspector look friendly.
6. The inspector must be driven by the same source of truth as the MCP servers, with parity tests preventing documentation/schema drift.
7. Add an **MCP** button to the existing right-side Control Center dock (`ERR / TRC / LAB / CNV / SET / AGT`). It opens a dedicated, clean inspector surface.
8. The inspector defaults to a compact/collapsed view and supports detailed expansion. Parameters show type, required/optional state, defaults and constraints. Results show a readable output schema.
9. The inspector groups capabilities into human categories, at minimum **General**, **Stars / Scène**, **Settings**, and **Bare Hands**. Optional/external MCPs may have a separate category when Jarvis can describe them reliably.
10. The inspector is an inspection/documentation surface in this task, not an arbitrary destructive tool runner.
11. Adding the inspector must not increase the model's MCP context cost by advertising redundant meta-tools. Protocol/catalog helpers such as `list_tools`/`get_tool` belong in the Control Center catalog layer unless there is a separate, justified model use case.
12. Final advertised Jarvis-native tool count must not grow mechanically. Semantic tools should replace redundant granular tools where possible; the scene surface must not exceed its current 13 advertised tools without an explicit, documented reason.


## Current evidence from the audit


- `jarvis/runtime/display_mcp.py` exposes 13 scene tools. `scene_update_many` resolves a selection once but sends one Core command per object, reports `atomicity: best_effort`, has a 15 s bulk deadline and rejects more than 32 selected objects.
- `jarvis/domain/scene.py` already proves the domain can do a true batch: `archive_many` produces one revision, but its eligibility is intentionally narrower than general scene manipulation.
- MCP `connected` means a graph walk over scene relations. UI `constellationOf(...)` additionally creates virtual signal-owner edges using `signalOwners(...)`, so the same word can currently denote different sets.
- The scene UI supports multi-selection and drags selected objects together visually, then commits geometry object-by-object. Bare Hands currently documents an intentional single-frame limitation.
- FastMCP input metadata is reasonably rich through `Annotated`/`Field`, but many mutating tools return `dict[str, Any]`, so result schemas are not a strong human contract.
- `jarvis-console` has a good generic settings design (`settings_describe/get/set`). Preserve that density instead of generating one tool for every setting.
- The Control Center's existing tool dock is the correct home for the requested `MCP` entry.


## How the Project Manager starts


Open `slices/TODO.md`, then execute **Slice 00 — Project Manager** yourself. Do not dispatch implementation before Slice 00 reaches `READY`.


Slice 00 must perform an independent blind audit first, then reconcile it with this handoff. This task deliberately contains architecture conclusions from an audit; the blind audit is required to catch repository drift and bad assumptions before code moves.


## QA and Human validation doctrine


Every implemented Slice gets `qa-verification`. Code changes also get `code-review`. User-visible or runtime behavior also gets `runtime-validation`. Any Slice touching MCP tools, tool descriptions, tool exposure, prompts, routing or agent runtime also gets `agent-trace-analysis` with real trace evidence. QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, file an Issue, or escalate.


A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation never substitutes for machine QA; run the strongest reasonable machine checks before requesting a Human check.


All coding Slices must require `/caveman` and `/coding-guideline`. Frontend Slices must additionally require `/impeccable` and a Claude Work Agent when the host supports that routing rule.


## Planning blocker carried into Slice 00


The current Workspace Task Type vocabulary is not exposed to this task creator. No Task Type is invented. Slice 00 must resolve valid existing Task Types before dispatch, or obtain an explicit host-supported waiver.

## Close-out (Slice 08, 2026-09-25)

Machine QA is green. The task now waits on the two Human checks below, the Drive move and the merge decision.

| Slice | Commits | Gates |
| --- | --- | --- |
| 00 Project Manager | ff525d0, e20897b, 20c5aba | readiness READY (H1 waiver, H2 realignment per slice) |
| 01 Canonical contracts (docs) | 9f913ca, f4726af | qa |
| 02 SceneSelection + constellation | 67502a0 (baseline), f5f391b, fb83a3a | qa, code-review |
| 03 Atomic scene batches | f67cf62 (baseline), 2760604, 675254f, cdf246a, e0dd185, 53c5d5d, 57a33b9 | qa, code-review, runtime |
| 04 MCP catalog + typed schemas | cd7178f, f0b1a3f, 16418cd, 2b2eb05, f405160 | qa, code-review, trace |
| 05 Semantic jarvis-display | 8f4b61e (baseline), df28431, f2d706e, 257e833, 93fbe54, ff15487, 878277f | qa, code-review, runtime, trace (real brain) |
| 06 Control Center MCP API | 9205d3e, 7011125, f711088, 4c0d0e3, b499b31 | qa, code-review, runtime, trace |
| 07 MCP inspector UI | 16e155e, 24d8645, 3def741, cf19dd7, eff1ecc, a31b014, 1db66e8, a9a5b16 | qa, code-review, runtime |
| 08 Integration + release QA | aa4c7dd (docs), the evidence and close-out commits | full sweep, static, runtime, trace (real brain), parity |

**Results.**

- **Tests:** unit 7 313 / 4 / 6 and integration 571 / 4 / 22. The only failures left are the 8 out-of-domain ones in `Issues/01`.
- **Display surface:** 13 tools, 31 864 B, below the 33 090 B baseline. No meta-tool and no alias.
- **Live brain:** every set operation was one MCP call, one Core command and one revision.
- **Inspector:** matches the live CLI's `tools/list`.

Evidence: `slices/08-integration-release-qa/qa/`. Pre-existing issues outside this task: `Issues/01`–`03`.

### Human checks still pending

**Setup, for both checks.**

1. Start Jarvis from this branch as usual, with the scene on.
2. Open the Control Center at http://127.0.0.1:17654/.
3. Let the brain start, so that CLAUDE shows RUNNING.

**HV-MCP-INSPECTOR-01: can a person read the inspector?**

1. Click **MCP** in the right-hand dock, between SET and AGT. The view opens on **Général**. Check that the server strip is readable at a glance: each server shows its state, its tool count and its cost in bytes. Check that the badge legend explains Lecture / Écriture / Destructif / Lot atomique / Idempotent.
2. **Général**: today it holds only the overview. It says there is no cross-domain tool, which is expected.
3. **Étoiles / Scène**: scan the 13 compact rows. Then expand **Masquer, réafficher, étiqueter un ensemble** (`scene_update_many`) and check the following:
   - The parameter table shows type, required or optional, default and constraints.
   - The `select` structure is readable: `constellation`, `near`, `exclude`.
   - The "Résultat" tree readably describes `SceneBatchResult`: `matched_count`, `hidden_count`, the id lists.
   - "Schéma brut" is closed at the bottom.
4. **Réglages**: expand `settings_set`. **Bare Hands**: expand `barehands_activate`, and check that `barehands_tutorial` shows **Déprécié**.
5. Type `radius` in the search box. Check that 5 scene tools match on `select.near.radius`, and that the tabs show `n/total`.
6. Press **Échap**. The view closes and focus returns to the MCP button. Also try Échap after clicking an empty area of the view.

Pass condition: the view is coherent and easy to scan, and the details expose the contract without clutter.

**HV-MCP-E2E-01: do the group actions match what the inspector says?**

1. Build a small scene by voice or by hand: 4 or more notes linked into one constellation, with one of them hidden.
2. Say « Masque toute la constellation de *X* ». The whole group must disappear at once, with no object-by-object flicker. The reply must count the members, for example « dont un qui l'était déjà ».
3. Say « Réaffiche-la ». The group comes back at once.
4. Say « Déplace toute la constellation vers la gauche » (or « jusqu'au bord gauche »). The group moves as one rigid shape. A member stopped at the edge stays still and on screen, with its link attached. Say « ramène-la au centre »: it orbits again.
5. Open **MCP → Étoiles / Scène** and expand `scene_update_many` and `scene_move`. Check that the inspector describes what you just saw:
   - one call, whole set, all-or-nothing (« Lot atomique »);
   - `select.constellation`;
   - the relative `dx` / `dy`;
   - `hidden_count` in the result.
6. Optional: open **TRC** or the Agents panel. The turn shows a single `scene_update_many` or `scene_move` call.

Pass condition: what the user sees and the inspector contract agree.
