# Slice 08 — Speculative preparation, delegation and staged display resources

| | |
| --- | --- |
| Scope | The speculative lane. **No composition-root wiring** and **no real runner** (rollout slice), **no reveal policy** (Slices 09/10), **no alert policy** (Slice 09). |
| New modules | `jarvis/domain/presentation_speculative.py`, `jarvis/core/presentation_speculative.py`, `jarvis/runtime/presentation_staging.py` |
| Changed | `jarvis/runtime/display_mcp.py` (+15, one keyword-only parameter) |
| Docs | `docs/presentation-speculative-preparation.md` (new), `docs/ARCHITECTURE.md`, `docs/presentation-ambient-lane.md`, `docs/presentation-working-set.md` |
| Tests | `tests/unit/test_presentation_speculative.py` — **66 tests, all passing** |
| Scene gate | **222 passed / 21 failed before, 222 passed / 21 failed after** — unchanged |
| Mutations | **38 run, 0 survivors** (plus a deliberate positive control that survives) |

---

## 1. The freshness audit SLICE.md asks for

`SLICE.md` says *"Prefer existing speculative primitives if the freshness audit
confirms they fit."* The audit was done first, and the answer is **reuse the
vocabulary, refuse the execution path**. Two measured facts, both verifiable:

1. **A `speculative_analysis` scope already exists** in `BackBrainTaskService`
   (`jarvis/core/back_brain.py:101` `_submit_speculative`) with its own job id
   (`speculative_job_id`), its own `BackBrainSpeculativeProvenance` whose
   `authorizes_actions` is structurally pinned to `False`, a worker capability
   probe (`supports_speculative_analysis`), a durable unavailability record
   (`BackBrainAdvisoryReference`) and two test files. It is genuinely built.
   **But its execution profile launches the CLI with `--tools ""`**
   (`jarvis/runtime/claude_local.py:713`, `restricted_args`). Zero tools. That
   is exactly right for re-reading a transcript and exactly wrong for D07,
   which calls for research, document resolution, code inspection and web/news
   lookup. **Correction (rework):** widening that profile would *not* widen the
   addressed path — `back_brain_worker.py` selects `speculative_analysis` only
   for a speculative job, the addressed one staying on `job_result`. The real
   cost is to today's `speculative_analysis` consumers (`live_delegation.py`).
   And the decisive argument is one I did not make: **that path is durable**
   (`state.accept_speculative_job`, capacity 16), which D13 forbids.

2. **`OwnedJobExecution._slots` is an `asyncio.Semaphore(1)`**
   (`jarvis/core/owned_job_execution.py:24`) and `_execute` holds it for the
   entire worker call (`timeout_s` defaults to 900 s). A speculative job
   admitted through that path would **block the next addressed turn** — D08
   violated as written. **Correction (rework):** "no preemption possible"
   overstates it; `owned_job_execution` has cancellation machinery. What it
   lacks is **concurrency**.

So: own pool, own execution, own priorities. What is reused rather than
redeclared — `VoiceStateDisposition`, `RiskLevel` + `FORBIDDEN_TOOL_NAMES`,
`ResourceReference` / `PreparedResource` / `ObservationProvenance`,
`SceneDisplayTools`, `DiagnosticSink`, and the `on_trigger` seam Slice 06 left.

`BackBrainTaskService` is **not modified**. Its addressed-only rule at
`back_brain.py:86-87` is byte-identical.

---

## 2. The capability boundary, as data rather than prose

Two tables in `jarvis/domain/presentation_speculative.py`:

- **`SPECULATIVE_TOOL_RISK`** — every tool this lane can name, with its
  `RiskLevel` taken from `jarvis/domain/actions.py`, the vocabulary
  `V1_ACTION_POLICY` already uses. Not a second risk vocabulary for the same
  question.
- **`CAPABILITY_TOOLS`** — what each of the seven `SpeculativeCapability`
  values grants. The seven come word for word from D07 and SLICE.md.

`_check_capability_table()` runs at **module import**. It requires that every
capability has a table, that every granted tool is declared, that its risk is
in `GRANTABLE_RISKS` (`READ` or `EPHEMERAL` — `WRITE` excluded in exactly one
place), and that its name is not in `FORBIDDEN_TOOL_NAMES` **compared
lower-cased**, so `Bash` cannot slip past `bash`. Granting a write tool breaks
the import of the module and therefore of the package: the fault cannot hide in
a rarely-taken branch.

`SpeculativeGrant.permits` is an **allowlist** — an unknown tool is refused for
being unknown, not for having been anticipated (Slice 04's schemes, Slice 06's
import guards). `SpeculativeToolbox` is the **only** route from a runner to a
tool: it asks the grant, then delegates, so a tool that is not granted is never
called — not called-then-undone.

**Granted to nobody, deliberately:** `scene_set_visibility`, `scene_archive`,
`scene_pin`. A preparation stages a hidden object; revealing it is a policy or
explicit-turn decision. **Correction (rework):** this claim was contradicted
three lines below by `scene_update_object`, which accepts `visibility`,
`geometry`, `layer` and an arbitrary `object_id` — an unrestricted superset of
the tool being withheld. It is now granted to nobody either.

---

## 3. Where P1–P4 lives, and why

**In the new lane only.** `jarvis/domain/work_state.py` has zero occurrences of
"priorit" (verified) and gains none — it is shared with Simple, so widening it
would be a D14 regression-boundary violation (G5).

`SpeculativePriority` is P0…P4. P0 (`ADDRESSED_TURN`) exists so preemption can
name it and is **never admitted**: a turn lives in the brain, and this lane only
keeps room for it. P1 is explicit preparation; P2–P4 are speculative and
sacrificial.

D08 is held by two mechanisms, both tested against a genuinely saturated pool:

- **the reserve** — pool 8, of which 2 are takeable only by an explicit rank, so
  speculative caps at 6 and saturation always leaves the reserve free;
  `free_explicit_slots` makes that readable rather than merely true;
- **preemption** — a full pool plus an arriving explicit rank sacrifices
  speculative work, lowest rank first (P4 before P2), newest first within a rank
  (a nearly-finished job has already cost what it will cost). An explicit job is
  never a victim.

Above both: the lane holds its own pool and never touches `BackBrainTaskService`,
which is the structural reason a saturated speculative pool cannot consume an
addressed request's capacity. A test asserts that by import closure.

**Trigger confidences are not a threshold.** `presentation-ambient-lane.md` §11
says the four values are posed, not calibrated. There is no `confidence > x`
anywhere in this lane; a trigger at 0.0 is admitted like any other, and a test
pins it. Rank comes from the trigger's *nature*, which is closed data.

---

## 4. How each binding constraint is discharged

| Constraint | Discharged by | Test |
| --- | --- | --- |
| G5 — no priority on canonical `WorkItem` | P0–P4 declared only in `jarvis/domain/presentation_speculative.py`; `work_state.py` untouched | `test_les_rangs_explicites_et_speculatifs_partitionnent_l_enumeration` + `work_state` suite unchanged (42 tests green) |
| Addressed admission not weakened | `back_brain.py` not modified; no import edge to it | `test_un_bassin_speculatif_sature_ne_consomme_aucune_place_du_back_brain`, `test_le_service_speculatif_n_atteint_ni_le_back_brain_ni_le_registre_d_outils` |
| Slice 06's 20-module closure preserved | coupling stays one-way (`on_trigger`); nothing of this slice enters the lane | `test_la_voie_ambiante_ne_depend_toujours_pas_de_la_preparation` + Slice 06's own equality guard re-run green |
| D03 — no write/side-effect authority | the two tables + load-time guard + allowlist toolbox | `test_un_travail_ambiant_ne_peut_atteindre_aucun_outil_d_ecriture` (write tools really wired, really called), `test_aucune_capacite_n_accorde_un_outil_de_risque_write`, the three `garde_de_table` tests |
| D08 — sacrificial, reserved capacity | reserve + preemption, own pool | `..._sature_laisse_toujours_la_reserve_libre`, `..._preparation_explicite_passe_sur_un_bassin_sature`, `..._bassin_entierement_plein_sacrifie_du_speculatif`, `..._preemption_ne_sacrifie_jamais_un_travail_explicite` |
| D12 — Scene authority, no executable HTML | staging goes through `SceneDisplayTools`; descriptors go through Slice 04's `ResourceReference` | `test_le_monteur_ne_construit_aucune_commande_de_scene_lui_meme` (AST), `test_une_reference_illegale_est_refusee_par_le_contrat_de_la_slice_04`, `test_un_descripteur_structure_sûr_est_accepte` |
| Slice 04 store is the output; typed dispositions only | every call counted under its own name; unknown said at `error` | `test_toutes_les_dispositions_du_magasin_sont_comptees_sous_leur_nom` |
| Re-preparation after a capacity refusal works | key released on completion | `test_une_cle_liberee_peut_etre_repreparee`, `test_une_cle_terminee_est_rendue_et_la_table_ne_grossit_pas` |
| `Disposition` vs `OutputDisposition` collision (G2) | no module imports both; staging imports only `Visibility` from `scene.py` | the AST test above enumerates scene symbols |
| Hidden until revealed | atomic hidden creation; no fallback to visible | `..._monte_masque_et_le_reste_jusqu_a_sa_revelation`, `..._cree_l_objet_masque_en_une_seule_commande`, `..._montage_en_echec_ne_range_rien_et_ne_montre_rien` |
| Cancel/evict on mode and session change | `retire` bumps generation **before** cancelling | `..._changement_de_seance_annule_tout`, `..._quitter_presentation_retire_la_voie`, `..._resultat_revenu_apres_un_retrait`, `..._seance_du_meme_nom` |

---

## 5. The narrow Display MCP change

`SceneDisplayTools.create_object` gains one keyword-only `visibility` parameter
(+15 lines). `SceneObjectFields` already carried the field; only the call path
was missing.

Why it is necessary rather than convenient: create-then-hide is two commands,
and between them the object is **visible on a screen someone is watching**. A
staged preparation that flashes is exactly what "normally invisible" promises
not to do.

Why the blast radius is nil: the parameter is **not** passed by the FastMCP tool
`scene_create_object` (`display_mcp.py:2474`), so the brain-facing catalogue is
byte-identical. **Correction (rework):** the test that claimed to guard this
inspected the internal method, not the published surface, and a second attempt
that read the published *schema* also failed to catch a mutation of the tool's
body. The guard is now behavioural — see B6. `test_display_mcp.py` + `test_scene_contracts.py` +
`test_scene_projector.py` = **427 passed**. A test asserts the omission case
still sends no `visibility` at all.

---

## 6. Mutations

Harness: `scratchpad/s08_mutate_slice08.py` (namespaced `s08_*`, per the Slice 07
incident). It verifies via `git status` that all five expected files are present
before and after **every** mutation, and refuses to report anything if one is
missing.

**Round 1 was void and I threw it away.** The harness passed `--timeout=120`,
which is not installed in this venv, so pytest exited non-zero on *every* run and
all 36 mutations reported "caught". The `BASELINE after restore: RED` line is
what exposed it. This is the Slice 07 lesson in a new shape — *a probe that
passes must also be checked* — so the harness now (a) refuses to start on a red
baseline and (b) carries **`M00-CONTROL`, a purely cosmetic mutation that must
survive**. A run where the control is reported caught is a lying harness.

**Round 2: 36 mutations, 10 survivors.** Every one was a real test gap:

| Survivor | What it revealed | Fix |
| --- | --- | --- |
| M01 | risk table could contradict `V1_ACTION_POLICY` | test pins agreement on shared names |
| M03 | `GRANTABLE_RISKS` could include `WRITE` — **the load-time guard was never reached in the state it exists for** | poisoned-table test |
| M05 | case-sensitive forbidden check let `Bash` past `bash` — same root cause | poisoned-table test |
| M12 | preemption could sacrifice an **explicit** job | explicit-only pool test |
| M16 | `_by_key` leaked; invisible because the pool looked fine | `tracked_keys` exposed in `stats()` |
| M17 | provenance could use the service clock instead of `spoken_at` — the test spoke at the frozen clock, so the two were identical | speak 90 s earlier |
| M24 | a failed staging was blamed on the reference, not the stager | assert `findings_invalid == 0` |
| M25 | the `display_mcp` change was never exercised (only fakes) | drive the real class over a capturing transport |
| M28 | **`mode is None` was dead code** — `behaving_interaction_mode` never returns `None` | branch removed, docstring corrected |
| M30 | generation check was masked by the session-id check | retire and re-bind under the *same* session name |

M03/M05 are the same defect and it is **the third catalogued pattern again**: a
guard whose code ran on every import but never met the state it guards. That is
now three slices in a row.

**Round 3: 38 mutations (36 + `tracked_keys` + the corrected mode check), 0
survivors** other than `M00-CONTROL`, which survives by design. Baseline green
before and after; tree verified intact each time.

---

## 7. Two defects my own tests caught during development

1. **The journal carried speech.** `SpeculativeJobKey.value` is built from the
   trigger's text, and Slice 06 warns that `_references` yields a *whole
   sentence* for any of nineteen nouns. Every `admitted` / `coalesced` /
   `preempted` line was therefore printing what was said in the room, breaking
   the rule the working set and the ambient lane both hold. Fixed with
   `SpeculativeJobKey.digest` (12 hex chars); `value` now carries a docstring
   saying it must never be journalled.
2. **`drain()`/`stop()` awaited the pool, not the tasks.** A preempted job has
   already given its slot back, so awaiting the pool awaited nothing — `stop()`
   would return while work was still running. Fixed with a `_tasks` set.

---

## 8. Exact commands and counts

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| the 8 Scene files, **before** any change | **21 failed, 222 passed** |
| the 8 Scene files, **after** | **21 failed, 222 passed** (gate held) |
| `test_presentation_speculative.py` | **66 passed** |
| `test_display_mcp.py test_scene_contracts.py test_scene_projector.py` | **427 passed** |
| `test_presentation_working_set.py test_ambient_ingestion_lane.py test_presentation_response_policy.py` | **337 passed** |
| `test_back_brain_tasks.py test_back_brain_speculative.py test_back_brain_speculative_adversarial.py test_work_state_store.py` | **100 passed** |
| `test_v2_architecture.py test_brain_delegation.py test_interaction_mode_contract.py` | **143 passed, 1 failed** (the declared `test_brain_delegation.py` baseline failure) |
| `test_agent_routing.py test_agent_routing_settings.py test_routing_hook.py test_agent_tasks.py test_conversation_event_subagents.py` | **152 passed** |
| `test_documented_routes.py test_control_center_quality.py` | **76 passed** |
| `test_back_brain_worker.py` (known flake) | **31 passed** |
| `test_presentation_speculative.py test_v2_architecture.py test_ambient_ingestion_lane.py test_presentation_working_set.py` | **292 passed** |

Blast radius: **1 522 tests run across the affected surfaces, one failure, and
that failure is on the declared baseline list.** Neither known flake reproduced.

---

## 9. Where SLICE.md and the live repository disagree — stated, not resolved

0. **Correction to §9.1 below:** only `docs/presentation-ambient-lane.md`
   carried the dead `docs/02-architecture.md` citation.
   `docs/presentation-working-set.md` did **not**; that claim was wrong. The one
   real instance is fixed.

1. **The doc paths in my brief do not exist.** `docs/02-architecture.md` and
   `docs/01-decision-log.md` are not in `docs/`; they live at
   `tasks/jarvis-presentation-interaction-mode/docs/`. I read them there.
   Note this is a **pre-existing** stale reference, not only in my brief:
   `docs/presentation-ambient-lane.md` §2 and `docs/presentation-working-set.md`
   both cite `docs/02-architecture.md` as if it were a repository page. I did
   not rewrite those citations — that is a task-wide call, not a Slice 08 one.

2. **"`BackBrainTaskService` has a flat capacity of 32" is true but names the
   wrong bound.** `back_brain.py:40-41` bounds *concurrent in-flight submission
   continuations*, keyed by `(conversation, scope, correlation, session,
   delegation)`. The durable job capacity is **16**
   (`sqlite_state.py:689`, `accept_speculative_job(capacity=16)`), and the real
   bottleneck is neither: it is `OwnedJobExecution._slots = Semaphore(1)`.

3. **"`back_brain` has no notion of sacrificial work" is correct, but the brief
   reads as if there were no speculative support at all.** There is a complete
   one — see §1. It is unusable here for a different reason (`--tools ""`), and
   that distinction matters for whoever revisits this.

4. G5's line numbers check out (`WorkItem` at 485, `WorkSnapshot` at 587,
   `MAX_WORK_ITEMS = 64` at line 56). The Scene baseline matched exactly.

---

## 10. What I could not satisfy

- **No real sub-agent, by instruction and by design.**
  `SpeculativePreparationRunner` is a port with no production implementation.
  Wiring one — building `--tools` from `SpeculativeGrant.allowed_tools` against
  a restricted CLI profile — is rollout work, and it is where the `--tools ""`
  finding of §1 will have to be answered. **Slice 11 must carry it**, alongside
  the audio session (Slice 05) and the ambient lane (Slice 06) that are waiting
  there for the same reason.
- **No composition-root wiring**, so no runtime validation is possible: nothing
  in a running JARVIS reaches this code. Same honest position as Slices 05 and 06.
- **The `EPHEMERAL` classification of `scene_create_object` was wrong.**
  Corrected to `WRITE` in the rework: the precedent did not transfer, and a
  scene object reaches a durable `INSERT`. See B3.
- **`reveal()` has no policy caller.** The mechanism is built and tested; *when*
  to reveal belongs to Slices 09/10.

---

# Rework — six blocking defects and twelve items

Second commit. **88 tests** (was 66), **51 mutations, zero survivors** besides the
deliberate control. Scene gate **222 / 21 before and after**, measured again.

## The six blockers

**B1 — `stop()` never returned.** `while self._tasks: await asyncio.gather(...)`
does not suspend when every child is already done, so the pending
`_tasks.discard` callbacks never ran. `drain()` now removes finished tasks
itself. My fix for a self-caught defect was worse than the bug it replaced, and
no test reached it because all 38 call sites entered while a task was still
running. There are now two dedicated tests. **Probed**: restoring the spin makes
`stop_rend_la_main` hang (exit 124), green after restore.

*Stated limitation*: a regression here **hangs** rather than failing, and the
in-test `wait_for` cannot help — the defect is a busy loop that starves the
event loop, so no in-loop deadline can fire. `pytest-timeout` is not installed
in this venv. The test says so in its docstring rather than implying otherwise.

**B2 — staging bypassed the capability table.** `_store_finding` honoured
`stage_hidden` with no grant check, so a `new_topic` ambient job whose grant held
only `RESEARCH_SEARCH` created a Scene object. The one effect that reaches
durable state was the one the table did not gate. Now gated on
`grant.may_stage`, counted as `stage_refused`. **Probed.**

**B3 — staged objects persisted forever.** Verified the chain myself:
`scene_create_object` → `SceneService._apply_serialized` → `repository.commit` →
`INSERT INTO scene_objects`, surviving restart. Three changes:

- `scene_create_object` is now **`RiskLevel.WRITE`**, not `EPHEMERAL`. The
  `BOARD_PRESENT` precedent does not transfer — that board stores nothing.
  (Noted: my report cited the wrong lines for it and said "one name" where I had
  added two.)
- the capability granting it sits outside `AMBIENT_CAPABILITIES`, and an ambient
  grant carrying it **cannot be constructed** — the refusal is in
  `SpeculativeGrant.__post_init__`;
- `retire()` reclaims staged objects via `scene_archive`; `MAX_STAGED_OBJECTS`
  (8) bounds them; `stats()` publishes `staged_objects`.

**B4 — `scene_update_object` was `scene_set_visibility` plus geometry and
layer.** Removed from `DISPLAY_PREPARATION` and from the risk table entirely. A
test asserts six scene supersets are granted to nobody.

**B5 — long triggers were refused as illegal requests.** `trimmed[:64]` can end
on a space; the key was then refused and the trigger answered
`REJECTED / speculative_trigger_unkeyable`. One `.strip()`. A test sweeps every
cut position from 1 to 140 words.

**B6 — the MCP guard tested the wrong function, twice.** The first inspected the
internal path under a docstring claiming the published surface. My second read
the FastMCP **schema** — and I probed it with QA's exact mutation (the MCP tool
passes `visibility='hidden'`) and **it passed too**: a schema cannot see a
function body. The guard is now behavioural — it drives the built server through
`call_tool` and asserts the serialized command carries no `visibility`. Probed
with QA's mutation: **fails by name**. A declarative companion test is kept and
marked explicitly as necessary but not sufficient.

## The twelve

1. **Coalescing false merges** documented in the contract page and pinned by a
   test: 64 chars against `MAX_TRIGGER_TEXT_CHARS = 320` merges "…in France" and
   "…in Germany". Bounded and failing safe, but not "by topic".
2. **Trace hygiene closed.** Every `f"…{exc}"` removed (five sites). Lines carry
   `error_class` and a stable code. This is a deliberate departure from "in the
   failure's own words", and the contract page and the `_trace` docstring both
   say why: a runner is handed room speech. The test now drives the **failure**
   paths with a runner that echoes its input into its exception.
3. **`note_addressed_turn()` no longer sacrifices on a pool with room.**
4. **A failing journal is counted** — `diagnostic_failures` on both the service
   and the stager, following `OwnedJobExecution`. The stager's lines now carry a
   real message instead of the kind repeated.
5. **Refusals carry `key.digest`**, on every branch that has a key.
6. **`submit_trigger` cannot raise**: `create_task` guarded, and the orphaned
   coroutine closed so it cannot surface as a warning in an unrelated test.
7. **`retire()` increments the generation before cancelling**, as it always
   claimed. A test reads the generation from inside the `CancelledError` handler.
8. **Freshness audit corrected** in the module header, the contract page and §1
   of this report: the shared-profile claim was **false** — `back_brain_worker.py`
   selects `speculative_analysis` only for a speculative job, the addressed path
   staying on `job_result`; "no preemption possible" overstated, since what is
   missing there is **concurrency**; and the durability argument — the strongest,
   and the one I had not made — now leads.
9. **Import-closure test** left as a denylist deliberately; see "still not
   satisfied".
10. **Deleted**: `SpeculativeToolbox` + `tools=` + `SpeculativeRequest.toolbox` +
    `tools_refused` + its trace (~70 lines), `SceneStagingTools`,
    `max_speculative_jobs()`, `_account_use`. `SceneStagingError.code` is now
    read (logged on a staging failure). The durable seam is
    `grant.allowed_tools`, and that is what the tests assert against.
11. **The enum is wider than its data**, now stated in the module and the
    contract page: seven names, **four** distinct tool sets, four of seven
    reachable from a trigger. That is why B2 and B4 were latent rather than live.
12. **The one real dead citation fixed** (`presentation-ambient-lane.md:65`).
    My §9.1 was wrong that `presentation-working-set.md` carried it too.

## Mutations

51 total. The rework's first round left **2 survivors**, both real gaps — an
orphaned coroutine no test observed, and a stager journal message no test read.
Both are now covered and re-run **caught**.

M12 survived a second time for the third-pattern reason yet again: my own fix
for item 3 (don't preempt when the pool has room) meant the existing test
returned before reaching the victim filter it exists to guard. Fixed by filling
the pool with explicit jobs only.

M45 (removing the B1 fix) is excluded from the automated round because it hangs
the runner by construction; it was probed by hand instead (exit 124).

**An operational note worth carrying.** Killing a mutation run mid-flight left a
mutated file on disk and two orphaned busy-spin processes at 5 783 s and 1 119 s
of CPU, on a host often under 2 GB free. Two consequences, both now handled: the
harness's tree check verifies **content markers** rather than `git status`,
because part of the work is committed and "modified" is no longer the right
test; and before killing anything I listed every `python.exe` by command line —
all but two belonged to the user's live JARVIS stack (core, voice, control
centre, MCP servers). Only the two scratchpad-path processes were killed.

## Counts, re-measured

| Files | Result |
| --- | --- |
| the 8 Scene files, before and after the rework | **21 failed, 222 passed** both times |
| `test_presentation_speculative.py` | **88 passed** |
| `test_display_mcp.py` + `test_scene_contracts.py` + `test_scene_projector.py` | **427 passed** |
| working set + response policy + back-brain ×3 + work-state | **337 passed** |
| architecture + delegation + interaction mode + routing ×4 + documented routes | **298 passed, 1 failed** (the declared `test_brain_delegation.py` baseline) |
| back-brain worker + ambient lane + this suite | **219 passed** |

Neither known flake reproduced.

## Still not satisfied

- **The import-closure test is still a denylist**, and I am flagging it rather
  than claiming it done. Slice 06's allowlist form is the right one; the
  **domain** closure here already uses it. For the core service the closure is
  32 modules and reaches third-party packages whose exact set is not stable
  across environments, so an equality assertion would be brittle in a way the
  domain one is not. A reviewer who wants equality there should say so and I
  will pin the `jarvis.*` subset by equality and leave the rest unasserted.
- **No runner and no composition-root wiring**, so still no runtime validation.
  Slice 11 carries it — and now also carries reclaiming staged objects after an
  **unclean** shutdown, since `retire()` only covers the orderly path.
- **`reveal()` has no policy caller** (Slices 09/10).
- **The `WRITE` classification of `scene_create_object` is still a judgement**,
  though a better-founded one than `EPHEMERAL` was: it is now backed by the
  storage path rather than by a precedent that did not transfer.
