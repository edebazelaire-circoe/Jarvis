# Slice 10 - Priority addressed turns: immediate, fresh, and reusing what exists

| | |
| --- | --- |
| Commit | `S10: le tour adresse arrive tout de suite, contre la parole la plus fraiche` |
| Files | 2 new modules, 1 new suite, 1 new contract page, +13 lines in `docs/ARCHITECTURE.md`, +16/-2 in `jarvis/core/latency.py` |
| Tests | **113 new**, 0 moved, 0 deleted |
| Mutations | 33 per round, 3 rounds; round 1 had **3 survivors**, all real test gaps; rounds 2 and 3 **zero survivors** besides the deliberate control |
| Wiring | **None**, by design - same discipline as Slices 05, 06, 08 and 09 |

## 1. What was built

`jarvis/domain/presentation_addressed_turn.py` (777 lines, pure - no IO, no
`jarvis.core`, no `jarvis.runtime`, no wall clock):

- `AddressedWindow` - binds the speech that follows a trigger, pre-roll included;
- `ContextOrigin`, `ResolvedReferent`, `resolve_referent` - the D06 precedence;
- `ResourceVerdict`, `ResourceResolution`, `resolve_prepared_resource` - the
  staleness and ambiguity rules;
- `AddressedTurnAction`, `decide_action` - the crossing of situation x verdict;
- `deictic_marker` - a small French lexicon with its limits written down;
- `AddressedTurnContext`, `build_addressed_turn_context` - the bounded
  projection, with **two named exits** (see section 5).

`jarvis/core/presentation_addressed_turn.py` (1 189 lines):

- `PresentationAddressedTurnService` - `arm()`, `open()` (both **synchronous**),
  `deliver()`, `note_visible_reaction()`, `note_audible_reaction()`,
  `conclude()`, `stats()`;
- `AddressedTurnPlan` / `AddressedTurnResult` / `AddressedTurnOutcome` /
  `AddressedTurnSettlement` / `AddressedTurnCounters`;
- three latency measures, on the existing `LatencyTracker`.

`jarvis/core/latency.py` gains one optional parameter, `mark(..., at=)`, so a
measure can start from an instant already stamped and frozen elsewhere. Default
behaviour is byte-identical and a test pins that. Without it this slice would
have carried a second stopwatch - two mechanisms for one question.

`docs/presentation-addressed-turn.md` is the contract page SLICE.md asks for
(window binding, context precedence, cache reuse, latency telemetry), linked
from `docs/ARCHITECTURE.md` next to its five sister pages.

## 2. The context-precedence rule, and how stale cache is prevented from winning

Three lines, in order:

1. **the referent of a deictic is always the most recent utterance in the
   tail.** The working set is never authoritative about *what was just said*;
2. **a prepared resource may answer only if it is anchored to that referent** -
   its provenance cites the same utterance, or enrichment has caught up
   (`observed_sequence >= referent.sequence`) and it hangs off a live topic;
3. **everything else is stale.** Refresh or ask which one; never show.

### Why it cannot invert

The rule does **not** rest on the order of two lines. Both halves compare on one
scale - the utterance rank - and that rank is **assigned by the store**. A
working-set record can only cite a rank that already exists, because its
provenance is copied from a tail entry the store accepted first; the ambient
lane reads it back with `_tail_sequence` and refuses to invent one. There is no
execution in which a cache announces a rank the tail does not hold. It is a
**data dependency**, not a convention - the shape Slice 04 established and
Slice 06 was made to write correctly into its own page, applied to the read side.

`test_la_precedence_se_compare_sur_un_rang_que_seul_le_magasin_attribue` drives
the store the way production drives it (speak, read back the assigned rank,
store) over eight utterances, asserts the inequality at every step, and asserts
that both the lagging and the caught-up state were actually reached - so the
test cannot pass by never entering either.

### The test that reaches the exact failing state

`test_un_cache_perime_perd_contre_une_parole_plus_fraiche` builds the **worst
case for the rule**: the cached resource is `HOT`, live, anchored to a topic
still in the working set - everything that would make showing it tempting -
while enrichment is three utterances behind. Only the rank says it was prepared
from older speech. Result: `STALE` / `addressed_enrichment_behind_referent`,
action `REFRESH`, `use_resource` never called.

Mutation **M03** removes that gate; it is caught by two tests.

## 3. The prepared-resource resolver: staleness and ambiguity

Refusal order is the contract, because the first refusal is what gets journalled:

| # | Check | Verdict / code |
| --- | --- | --- |
| 1 | no referent (empty tail) | `absent` / `addressed_no_recent_speech` |
| 2 | nothing left once **retired** and **cold** are removed | `absent` / `addressed_no_live_resource` |
| 3 | enrichment has not reached the referent | `stale` / `addressed_enrichment_behind_referent` |
| 4a | provenance cites the referent utterance | `reusable` / `..._anchored_to_referent` |
| 4b | otherwise the resource hangs off a live topic | `reusable` / `..._anchored_to_live_topic` |
| 4c | neither | `stale` / `addressed_no_resource_for_referent` |
| 5 | the top two rank identically | `ambiguous` / `addressed_resource_ambiguous` |

- **Retired never resurrects.** The store holds this on the write side; this is
  the read side, because a snapshot can still show a resource whose id was just
  retired. `test_une_ressource_reellement_retiree_par_le_magasin_n_est_pas_montree`
  reaches the state **through the store itself** (topic ages out, the cascade
  makes the resource `discardable`, eviction records it in
  `retired_resource_ids`), not through a test parameter.
- **Unreadable retirements are not an empty set.** `_retired_resource_ids()`
  returns `None`, and the resolution becomes `stale`. An empty tuple would
  assert "nothing was retired", the one thing we are not in a position to say.
  A `str` counts as unreadable: iterated it would yield a set of **letters** - a
  wrong answer wearing the shape of a right one, which Slice 09 paid for once.
  Both branches carry a **control arm**: the same data through a healthy store
  must be `REUSABLE`, otherwise the refusal proves nothing.
- **Cold** is Slice 04's computed `discardable` (topic gone, or idle past
  `MAX_RESOURCE_IDLE_S`), read, not recomputed.
- **Ranking** is `(provenance.sequence, temperature.rank, last_used_at)` and
  deliberately does **not** end with the id. The store's `sort_key` does, to make
  eviction deterministic; here it would turn a genuine "which one?" into an
  alphabetical coin toss. `test_l_egalite_n_est_pas_brisee_par_l_identifiant`
  pins it; mutation **M07** adds the id back and is caught by 5 tests.
- **Ambiguity is audible.** A tie produces one `SpeechKind.QUESTION`, which
  passes only because Slice 07 put `QUESTION` in `VISUAL_COMMAND`'s
  `safety_speech_kinds`. A test reads that matrix row directly, so the day it
  moves this fails here rather than in a user's silence.
- **A named request is not resolved here.** `ResourceVerdict.NOT_REQUESTED`.
  Matching a name to a resource would need a second lexical classifier, weaker
  than the brain's, which receives the whole projection anyway.

Every fallback is to **refresh**, never to a claimed success: a failed reveal, a
refused reveal, a store refusal and a missing stager all end in
`reserve_explicit` at P1. A resource declared served beside an empty screen is
the "it worked" that means "nothing happened".

## 4. Latency telemetry, and what it actually measures

| Measure | From | To |
| --- | --- | --- |
| `explicit_trigger_to_addressed_admission` | the stamp the explicit-address lane froze at admission | `open()` has finished building the projection |
| `explicit_trigger_to_visible_reaction` | the same stamp | the caller declares a visible reaction |
| `explicit_trigger_to_audible_reaction` | the same stamp | the caller declares an audible reaction |

Read honestly, and this is in the module header and the contract page too:

- **admission** is in-process work with no IO. It is the quantity D04 obliges us
  to bound, and the only one of the three this slice controls end to end;
- **visible** does not mean "a pixel changed": it ends when the call that asked
  for the change returns. The rest belongs to the scene and the browser;
- **audible** ends where the caller says it does. Slice 11 chooses between "the
  speech entered the scheduler's queue" and "the first frame played"; the number
  means something different under each, and this slice does not choose for it.

Both bounds of each measure come from **one** monotonic clock in **one**
process. When the service's clock is behind the trigger's stamp it refuses to
measure at all: counts `latency_clock_mismatch`, says so, reports `None`. A
`None` says *we do not know*; a zero would say *we know it was instant*.

The three names live in the slice's own module, **not** in `LATENCY_MEASURES` -
that tuple is the realtime-brain handoff's exhaustive six, consumed by the
testlab and pinned at six by `test_v2_latency_telemetry.py`. A test asserts the
two sets are disjoint.

## 5. How each binding constraint is discharged

| Constraint | How | Test |
| --- | --- | --- |
| **D06 - tail before cache, by data dependency** | precedence compares store-assigned ranks; a record cannot cite a rank the tail does not hold | `test_la_precedence_se_compare_sur_un_rang_que_seul_le_magasin_attribue` |
| **D06 - stale cache must never win** | rule 3 of the resolver | `test_un_cache_perime_perd_contre_une_parole_plus_fraiche` (HOT + live topic + lag 3) |
| **Slice 09 precondition - `reason` in-process only** | read off the object; `to_brain_context()` carries it, `to_trace_payload()` does not; **no `to_payload` call anywhere in either module** | `test_aucun_serialiseur_d_instantane_n_est_appele_par_la_slice` (AST, absence of a call, justified in its docstring) plus `test_aucune_parole_n_entre_dans_une_ligne_de_journal` (planted phrase, whole lane driven, zero journal lines) |
| **D04 - P0 never waits for ambient** | `arm()` and `open()` are **synchronous**; a frame with no `await` cannot yield the loop | `test_l_admission_d_un_tour_adresse_ne_peut_pas_ceder_la_boucle` (AST) plus `test_le_declencheur_est_admis_immediatement_malgre_un_arriere_a_l_echelle_de_la_minute` |
| **D08 - and its honest limit** | the service calls `note_addressed_turn()` and claims nothing more; the header and the page both say `free_explicit_slots` is not evidence of addressed-turn capacity, which lives on `OwnedJobExecution._slots` | `test_un_bassin_reellement_plein_sacrifie_un_travail_speculatif` (pool genuinely full, including the reserve, so the victim filter is actually reached) |
| **D09/D10 - integrate, do not re-decide** | `classify_addressed_situation` and `admit_presentation_speech` are injected defaults; disposition is `policy_for(situation).disposition` | `test_la_disposition_du_tour_est_exactement_celle_de_la_matrice`, `test_une_commande_visuelle_se_termine_sans_un_mot`, `test_une_vraie_question_peut_parler`, `test_la_clarification_est_audible_parce_que_la_matrice_le_dit` |
| **Clarification refused means refresh, not silence** | the guard is reachable because `admit` is an injectable field (Slice 07's own pattern) | `test_une_politique_qui_refuse_la_clarification_fait_rafraichir_pas_taire`, `test_une_admission_de_parole_en_panne_ne_montre_pas_le_mauvais_ecran` |
| **Reuse, do not resurrect; seven dispositions counted** | all seven pre-declared; an unknown one is said at `error`, bucketed into nothing | `test_les_sept_dispositions_du_magasin_sont_pre_declarees`, `test_chaque_disposition_du_magasin_est_comptee_sous_son_propre_nom`, `test_une_disposition_de_magasin_inconnue_est_dite_et_pas_rangee_par_defaut` |
| **Prepared material genuinely reused** | reveal called once, `reserve_explicit` never, temperature rises to `hot`, `last_used_at` moves | `test_le_materiel_prepare_est_reutilise_et_rien_n_est_re_prepare`, `test_une_ressource_non_scenique_est_rechauffee_par_le_magasin` |
| **Runtime stays in Presentation** | `conclude()` reads and reports; it ends nothing, retires nothing, changes no mode. The balance is a **value**, not only a log line | `test_apres_le_tour_la_seance_reste_en_presentation_ambiante`, `test_conclure_ne_retire_rien_du_magasin`, `test_quitter_la_presentation_est_dit_et_pas_pretendu` |
| **"X never raises" is a test case** | store raises (snapshot, retired, use_resource), speculative raises (note, reveal, reserve), classifier raises and returns untyped, admission raises, journal raises, clock raises and returns untyped - each exercised where it hurts | 13 tests in section 9 of the suite |
| **No tests asserting on source text** | two exceptions only, both about the **absence** of a thing, both carrying their justification and a "do not delete on that ground" note | the two AST tests above |
| **Namespaced scratchpad** | every scratch file is `s10_*` in the session scratchpad | - |

## 6. Mutations and survivors

Harness: `<scratchpad>/s10_mutate.py`. It refuses a red baseline, carries
`M00-CONTROL` (a cosmetic docstring edit that **must survive**), prints
`git diff --stat` for **every** mutation before rendering a verdict, verifies
the mutation is on disk by content marker before running pytest, and verifies
the restore afterwards.

**One finding about the harness itself, worth carrying forward.** The first
`git diff --stat` printed *nothing* about the new files, because they were
untracked - a sixth way a harness can look honest and say nothing. `git add -N`
on the new files fixes it, and the diff then shows all four. Any later slice
adding new files must do this before trusting its own diff.

| Round | Mutations | Caught | Survivors (excl. control) |
| --- | ---: | ---: | --- |
| 1 | 33 | 29 | **3** |
| 2 | 33 | 32 | 0 |
| 3 (after the test edits of section 7) | 33 | 32 | 0 |

Round-1 survivors, all three **test** defects and all three the same shape the
LOG has now catalogued seven times - *a test that exercises a guard's code
without reaching the state the guard exists for*:

- **M08** (`sorted(reverse=True)` becomes ascending). The "freshest anchored
  wins" test had only **one** candidate in the pool, because direct anchoring
  filtered the other out - the ranking code was never consulted. Rewritten so
  both candidates arrive through topic anchoring; now 5 tests catch it.
- **M17** (`entries[-8:]` becomes `entries[:8]`). The projection test asserted
  the tail was bounded to eight and never *which* eight. Eight oldest utterances
  is exactly the stale context D06 forbids, and it counts the same. Now asserts
  the ids and the sequences.
- **M32** (a missing stager falls through into the reveal branch). The test read
  a `warning` line the mutation left intact. Under the mutation the path goes
  through an `AttributeError` dressed up as the same refusal. Now asserts the
  absence of `addressed_reveal_failed` and `reveal_failures == 1` - the refusal
  must be *named*, not a crash wearing its clothes.

## 7. Probes of my own guards

Both source-reading guards were probed, and both were confirmed to **apply** and
to **select**:

- an `await asyncio.sleep(0)` plus `async def open` dropped into the service:
  `test_l_admission_d_un_tour_adresse_ne_peut_pas_ceder_la_boucle` failed by
  name (`open est devenue asynchrone : D04 tombe`);
- a `to_payload()` call inserted into the domain projection:
  `test_aucun_serialiseur_d_instantane_n_est_appele_par_la_slice` failed by name
  and printed the offending line.

`git diff --stat` was printed with each probe applied, and the tree was verified
restored afterwards (content markers plus the diff).

## 8. Exact pytest commands and counts

```
.venv/Scripts/python.exe -m pytest tests/unit/test_presentation_addressed_turn.py -q -p no:cacheprovider
  -> 113 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_presentation_working_set.py tests/unit/test_presentation_audio_capture.py tests/unit/test_presentation_response_policy.py -q -p no:cacheprovider
  -> 331 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_presentation_speculative.py tests/unit/test_presentation_attention.py tests/unit/test_ambient_ingestion_lane.py -q -p no:cacheprovider
  -> 239 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_v2_speech_scheduler.py tests/unit/test_voice_turn_admission.py tests/unit/test_brain_work_context.py tests/unit/test_v2_architecture.py -q -p no:cacheprovider
  -> 134 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_v2_latency_telemetry.py -q -p no:cacheprovider
  -> 21 passed            (latency.py changed; LATENCY_MEASURES still pinned at 6)

.venv/Scripts/python.exe -m pytest tests/unit/test_testlab_bundle.py tests/unit/test_speech_presentation.py tests/unit/test_speech_presentation_scheduler.py tests/unit/test_interaction_mode_contract.py -q -p no:cacheprovider
  -> 195 passed           (testlab consumes LATENCY_MEASURES)

.venv/Scripts/python.exe -m pytest tests/unit/test_documented_routes.py tests/unit/test_presentation_addressed_turn.py -q -p no:cacheprovider
  -> 116 passed
```

**Blast radius: 1 036 tests re-run across the affected surfaces, 0 failures, 0
moved, 0 deleted.** The 25 stable baseline failures are in Scene, Bare Hands and
`test_brain_delegation.py`, none of which this slice imports or touches; neither
known flake was run or reproduced.

## 9. What Slice 11 must wire for me

Nothing production constructs `PresentationAddressedTurnService`. In dependency
order:

1. **Build the service** in the Voice composition root, next to the audio
   session and the ambient lane, with: the Slice 04 store, the Slice 08
   speculative service, `mode=InteractionModeObserver.mode` (the *behaving*
   reading), the runtime journal as `diagnostics`, and **`clock=time.monotonic`
   - the same clock the `ExplicitAddressLane` uses to stamp its triggers.** If
   those two differ the service refuses to measure and says so; it will not
   invent a number, but the telemetry will be blank.
2. **Consume `ExplicitAddressLane.triggers()` instead of `detections()`** and
   call `service.arm(trigger, correlation_id=...)`. Slice 05 built both as two
   views of one queue precisely for this; the switch is Slice 10's seam and
   Slice 11's wiring.
3. **Call `service.open(text, correlation_id=...)`** where the bridge submits an
   addressed turn, and pass `spoken_at_s` when the surface knows when the
   utterance started - without it the window is checked against *now*, which is
   correct but coarser.
4. **Hand `plan.situation` to `SpeechScheduler.note_addressed_turn`** rather than
   letting the gate re-classify. The gate's `classify` is already a field; the
   pure function is deterministic so re-classifying is not *wrong*, but one call
   and one truth is better than two calls that agree by luck.
5. **`await service.deliver(plan)`**, then feed the result: `SHOW_PREPARED` is
   already done (the stager revealed it); `CLARIFY` needs one `SpeechRequest`
   with `kind=SpeechKind.QUESTION`; `REFRESH` and `ASK_BRAIN` need the brain turn
   with `plan.context.to_brain_context()` in its context. **Never**
   `to_trace_payload()` for the model, and **never** `to_brain_context()` into a
   journal.
6. **Close the two reaction measures**: `note_visible_reaction()` when the scene
   command returns, `note_audible_reaction()` at whichever point Slice 11 decides
   the audible bound is - and write that decision down, because the number means
   something different under each.
7. **Call `conclude(correlation_id)`** at the end of the turn. It is what makes
   "the session stayed in Presentation" a recorded, readable fact instead of an
   assumption.
8. **`HV-PRES-PRIORITY-01` is not reachable until all of the above.** It is also
   the second half of `HV-PRES-ALERT-01` ("then optionally ask Jarvis what it
   found") - that half needs the addressed turn to be live and to project
   `reason`, which it now does.

## 10. Where SLICE.md and the live repository disagreed - stated, not resolved quietly

1. **"Files Likely Touched" names `voice_v2.py`, the realtime/voice admission
   bridge and the Scene/display integration.** None of them is touched. Wiring
   any of them would open the room microphone in production and put a live
   consumer behind a lane nothing feeds - the exact reason Slices 05, 06, 08 and
   09 each left their composition-root wiring to Slice 11. I followed the same
   discipline and listed the wiring above instead. **This is a deliberate
   divergence from the literal file list.**
2. **Implementation step 3, "Implement P0 admission and reserved
   capacity/preemption".** The reserve and the preemption already exist, built
   and QA-measured in Slice 08. Re-implementing them would be a second table for
   one question. The service **integrates** them (`note_addressed_turn`,
   `reserve_explicit`) and adds only what was missing: the synchronous admission
   path and the window binding.
3. **Implementation step 6, "Wire display and response disposition".** The
   response disposition is wired - it is read from the matrix and carried on the
   plan. The *display* is wired only as far as Slice 08's `HiddenSceneStager`
   seam; the real Scene is exercised through that seam's double, not through
   `SceneDisplayTools`. "Scene display tests" in Automated Validation is
   therefore satisfied indirectly, and I say so rather than claiming the Scene
   was driven.
4. **`docs/02-architecture.md` still does not exist under `docs/`.** It lives in
   the handoff folder, and `presentation-ambient-lane.md` and
   `presentation-working-set.md` still cite it at the wrong path - the
   pre-existing drift Slice 08 reported and nobody has closed. My new page does
   not reintroduce it: it cites only pages that exist where it says they do.
5. **`AttentionItem.reason` versus Slice 04's original intent.** Slice 04 sized
   `reason` at 160 chars "for Slice 09's floating warning"; Slice 09 overruled
   that and kept it for me. I am the first and only reader. It reaches the model
   and nothing else.

## 11. What I could not satisfy

- **Nothing was exercised in a running JARVIS.** No composition root, no
  microphone, no model - by design, as above. The ambient backlog in the latency
  test is real machinery (real `AmbientIngestionLane`, real `AudioCaptureHub`
  with an injected stream factory, real `PresentationSpeculativeService`) driven
  by fakes at its edges; the minute-scale cost is **declared** and the jobs are
  confirmed still in flight, not actually waited out.
- **The addressed turn's execution capacity is still
  `OwnedJobExecution._slots = Semaphore(1)`,** and this slice does not change it.
  A speculative job cannot occupy it today (it runs in its own pool), but nor
  does anything here *prove* an addressed turn will not queue behind an earlier
  addressed turn. That remains Slice 11's to look at, and I have not claimed
  otherwise anywhere in the code, the page or this report.
- **The deictic lexicon is lexical and French**, like Slice 07's classifier, and
  its residuals lean the safe way: a missed deictic is handled as a named
  request; an invented one costs at worst a clarifying question. Neither shows a
  wrong screen. `ce` / `cet` / `cette` and `la` are deliberately absent -
  `normalized_tokens` decomposes "la" and "ca", so admitting `la` would make
  "montre-moi la courbe" a deictic. Mutation **M18** adds it back and is caught.
- **`ResourceVerdict.NOT_REQUESTED` is a stated gap, not a solved problem.** A
  named visual command ("montre-moi le bilan Q3") does not reuse prepared
  material through this resolver; it goes to the brain with the projection. A
  lexical name-matcher here would be weaker than the brain and would be the
  second classifier this handoff has spent three slices removing.
