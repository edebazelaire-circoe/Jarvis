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
   lookup. Widening that profile would widen the **addressed** path that shares
   it — the thing I was told not to touch.

2. **`OwnedJobExecution._slots` is an `asyncio.Semaphore(1)`**
   (`jarvis/core/owned_job_execution.py:24`) and `_execute` holds it for the
   entire worker call (`timeout_s` defaults to 900 s). A speculative job
   admitted through that path would **block the next addressed turn** — D08
   violated as written, with no preemption possible, because nothing in that
   semaphore gives a slot back.

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
explicit-turn decision. Without that split, "normally invisible" would depend on
the job's good behaviour rather than on the system.

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
byte-identical. `test_display_mcp.py` + `test_scene_contracts.py` +
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
- **The `EPHEMERAL` classification of `scene_create_object` is a judgement.**
  It follows `BOARD_PRESENT`'s precedent in `V1_ACTION_POLICY` — a thing that
  appears for the session and does not survive. A reviewer who disagrees should
  say so now: it is one line in a table, and it is the only place where this
  slice extends the canonical risk vocabulary to a new name.
- **`reveal()` has no policy caller.** The mechanism is built and tested; *when*
  to reveal belongs to Slices 09/10.
