# Slice 09 — Fact-check attention, floating warning, discreet sound

Commit `801e5a8`. A verified contradiction produces **one unobtrusive floating
card and at most one discreet non-speech cue**. Never a spoken interruption. The
user may ignore it, or open it for its evidence.

Contract page: `docs/presentation-attention.md`, linked twice from
`docs/ARCHITECTURE.md`.

---

## 1. What I built

| File | What | Size |
| --- | --- | --- |
| `jarvis/domain/presentation_attention.py` | The vocabulary and **the gate**: `AttentionEvidence`, `FactCheckAssessment`, `PresentationAttention`, `AttentionDecision`, `AttentionRefusal`, `ALERTING_VERDICTS`, `decide_attention`, `severity_for`, `confidence_band`, `attention_output_policy`, `_check_alerting_table`. Pure — no clock, no store, no journal, never raises. | new, 601 |
| `jarvis/core/presentation_attention.py` | `PresentationAttentionService` — feeds the snapshot to the gate, counts every answer under its own code, stores what it accepts, journals. `AttentionCounters`, `ALLOWED_IMPORT_CLOSURE`. | new, 407 |
| `jarvis/core/presentation_speculative.py` | `SpeculativeOutcome.assessments`, the `AttentionRaiser` protocol, `attention=` on the constructor, `_raise_attention`, three counters. | +103 |
| `jarvis/runtime/background_events.py` | Classifies `presentation.attention.raised` as `attention`; carries a re-clipped typed payload on the event; `attention_digest()` for the status poll. | +149 |
| `jarvis/runtime/control_center.py` | The conditional `background.attention` field; the script marker pair and its `index` replacement. | +36 |
| `jarvis/runtime/control_center.html` | The marker; `bgCueAllowed(seq)` consulted before `bgCue`; the `gate`/`statusLost` seam in `refreshStatus`. | +24 |
| `jarvis/runtime/control_center_presentation_attention.js` | The floating card and the cross-tab sound arbiter. | new, 654 |
| `jarvis/domain/presentation_working_set.py` | One public alias, `check_confidence = _confidence`, so Slice 09 shares the rule instead of writing a second one. No behaviour change. | +8 |
| `docs/presentation-attention.md` | The contract page. | new, 269 |
| `docs/ARCHITECTURE.md` | Two links and the paragraph placing this path in the whole. | +19 |
| `tests/unit/test_presentation_attention.py` | 39 tests. | new, 952 |
| `tests/unit/test_presentation_attention_js.py` | 40 tests (node). | new, 383 |
| `tests/unit/test_presentation_attention_browser.py` + `_presentation_attention_browser.mjs` | 13 tests in real Chrome over HTTP. | new, 484 + 293 |

14 files, **+4370 / −12**.

---

## 2. What I reused, and what I deliberately did not rebuild

### The sound already existed — that is the whole design

`bgCue()` in `control_center.html` is two WebAudio sine notes, no asset file, and
it already plays **only on a rise of the ledger sequence, never on the first
poll**. Adding a second emitter would have produced two sounds for one event,
which D11 forbids in as many words. **This slice adds no sound emitter at all.**
It adds the one thing that was missing: `bgCueAllowed(seq)`, a gate the existing
call consults.

That gate is **open by default**. If the module fails to install, or the
arbitration throws, the page sounds. One sound too many is a minor defect;
silence where D11 asks for a signal is the defect this exists to prevent.

### The ledger, the pill, the popover

`BackgroundEventLedger`, `GET /api/background`, `POST /api/background/ack`,
`#bgPills` and `#bgPop` are untouched in behaviour. An attention event becomes an
ordinary `attention` entry, counted in the "points à vérifier" pill and
acknowledged through the existing door. The card does not replace the pill; it
shows what the pill counts, for the one case D11 says to show.

### Slice 04's vocabulary, extended not duplicated

`AttentionCategory`, `AttentionSeverity` and `AttentionItem` are used as they
are, per the LOG's instruction. `PresentationAttention.to_item()` produces the
Slice 04 record, so the store's coalescing key `(category, claim_id, topic_id)`
**is** the event's identity — semantic dedup comes free and is not
re-implemented. `ClaimStatus` is reused as the verdict vocabulary: `UNCERTAIN`
already meant *checked without concluding*, exactly the value that stops a failed
search becoming an alert.

The only addition to that module is one public alias next to the existing
`check_text` / `check_descriptor`.

### Slice 03's harness — model, not import

`_served_page` uses the same reflective marker discovery, so my module joined
Slice 03's own browser suite automatically (re-run: **6 passed**). I wrote a
separate harness because mine must serve the page **over HTTP**: two tabs share a
`localStorage` only if they share an origin, and `file://` gives none usable.
"Two tabs, one sound" is not demonstrable at any lower level. My harness also
answers `/api/status` itself, so the page does its real 1 Hz polling against real
responses — nothing page-side is simulated.

### Deliberately not done

- No second notification system (D12).
- No second poll — the card rides `refreshStatus` through the `gate`/`statusLost`
  convention four modules already use.
- No new rung on the bottom-left rail — Slice 03 wrote that a third rung belongs
  to no single occupant; measured, and agreed.
- No `reveal()` call — the mechanism exists (Slice 08); *when* is Slice 10's.
- No user preferences (out of scope).
- No production wiring — see §10.

---

## 3. The evidence and confidence rules

`decide_attention` is pure and returns an `AttentionDecision` that is either
raised or refused with a named `AttentionRefusal` — never both, never neither
(`__post_init__` holds it). The **order** is part of the contract, because the
first refusal is the one journalled and read:

| # | Check | Refusal code |
| --- | --- | --- |
| 1 | the input is a `FactCheckAssessment` | `attention_assessment_invalid` |
| 2 | the job's grant holds `FACT_VERIFICATION` | `attention_capability_missing` |
| 3 | `searched is True` | `attention_search_failed` |
| 4 | the verdict is in `ALERTING_VERDICTS` | `attention_not_alerting` |
| 5 | ≥1 piece of evidence, each with a locator | `attention_no_evidence` |
| 6 | the claim exists in the working set | `attention_claim_unknown` |
| 7 | ≥1 piece names a source the working set holds | `attention_provenance_unknown` |
| 8 | `confidence >= 0.6` | `attention_low_confidence` |
| 9 | the event is constructible | `attention_not_constructible` |

**Search failure or absence is not a contradiction** — held twice, because a
runner can be wrong in both directions:

- `searched=False` is refused at step 3, **before the verdict is read**. A runner
  returning `CONTRADICTED` on a failed search is refused, not promoted. That
  hostile case is the test, not the polite one.
- `UNCERTAIN` / `SUPPORTED` / `ASSERTED` are absent from `ALERTING_VERDICTS`, and
  `_check_alerting_table()` enumerates the values the table must **not** hold, so
  it meets the state it forbids on every call. That is the fix for the pattern
  this handoff catalogued three times.

**Provenance is verified, not declared.** Steps 6 and 7 resolve the claim and at
least one source against the live working set. A runner that invents a source
passes every other check and fails this one.

**The producer names neither category nor severity** — computed from
`ALERTING_VERDICTS` and `severity_for()`. Slice 07's rule: a label a producer can
write is a ceiling a producer can lift.

**The thresholds are caution, not measurement.**
`docs/presentation-ambient-lane.md` §11 records the four trigger confidences as
hard-coded and uncalibrated. `MIN_ATTENTION_CONFIDENCE = 0.6` and
`HIGH_CONFIDENCE = 0.8` inherit that, so the surface shows a **band in words**
and never a number. A browser test reads the whole rendered text and refuses any
numeric confidence form.

In V1 the image of `ALERTING_VERDICTS` is exactly `{CONTRADICTION}`. `MISMATCH`,
`MISSING_SOURCE` and `STALE_RESOURCE` stay declared by Slice 04 and are
**unreachable from this door**. Stated rather than left to be assumed.

---

## 4. Which layer dedupes which case

| Case | Held by | Where |
| --- | --- | --- |
| the same contradiction twice | the Slice 04 store, coalescing on `(category, claim_id, topic_id)` | reused |
| **polling** | the existing rise rule `seq > BG.seq` | pre-existing |
| **reload** | `BG.armed` (refuses the first poll of a fresh page), **plus** the shared high-water mark which survives the page | pre-existing + new |
| **multiple tabs / windows** | a 3 s leader lease plus a shared high-water mark in `localStorage` | **new — the only hole that needed code** |

The semantic one comes first and matters most: a coalesced item posts **no trace
line**, so the sequence does not rise, so nothing sounds. Proved by counting
emitted lines, not by reasoning.

`claimCue(seq)` *consumes* the sequence: calling it twice for the same `seq`
returns `false` the second time.

**What the arbitration does not guarantee.** `localStorage` has no atomic
compare-and-swap. The lease makes the window tiny — a non-leader gives up without
writing — and the mark catches the ordinary case of two tabs noticing a few
hundred milliseconds apart. Two tabs reading the mark in the *same* event-loop
turn before either writes could both sound. A very strong reduction, not a proof.

---

## 5. Placement, measured before anything was placed

`scratchpad/s09_measure.mjs` composed the served page and drove headless Chrome at
1440×900 (panel open and closed), 1024×768, 820×900, 700×600, 500×700 and
360×640, with the Bare Hands palette at **five** tools, three toasts, the live
banner shown and the pills populated. At 1440×900:

```
topbar   x  18..1422  y  18..54    z=31
banner   x 360..1080  y  68..131   z=35
dock     x1370..1422  y 269..631   z=32
pills    x1382..1410  y 643..779   z=40
toasts   x1082..1422  y 692..882   z=70
hint     x 641..799   y 846..878   z=31
modeBtn  x  18..195   y 818..878   z=32
palette  x  18..82    y 168..611   z=30   (grows with tool count)
panel    x 794..1354  y  18..882   z=33   (open)
```

**No corner is free at every size.** Bottom-left is the contended rail with two
rungs. Top-right is taken by the panel when open and the banner when live.
Bottom-right is the toast rail. Below 700 px the toasts already overlap the voice
hint, the pills, the dock and the mode control — all pre-existing.

So the card **joins the toast rail** instead of inventing a fifth anchor: an
ordinary child of `#toasts` with `order:1`, keeping it the lowest card whatever
`toast()` appends after it. It inherits the rail's width, its open-panel dodge
and its reduced-motion rule with **no shared rule touched**. It declares no
`z-index` of its own — a child of a ranked rail, the reasoning Slice 03
documented for its host.

Two rules are its own, both measured:

- **≤760 px**: a 44 px bottom margin lifts the stack above the centred voice hint.
- **≤700 px**: my own geometry test then **failed, and it was a real defect.** The
  mode control leaves the left rail for `left:84px` and occupies the band 84→144
  above the bottom — the band the lifted card occupies. **Measured overlap 119×31
  at 500×700**, card at rank 70 against the control's 32, so the mode button
  became unclickable. That is exactly the defect Slice 03 was reworked for, in
  the other direction. Fixed horizontally, the escape the mode control itself
  took: `justify-self:end; width: max(156px, calc(100vw - 348px))`.

Residual, stated: below roughly 420 px this page's bottom is a pile-up that
predates this slice. The card inherits those conflicts; it does not create them.

---

## 6. How each constraint is discharged, and the test that proves it

| Constraint | Discharged by | Proving test |
| --- | --- | --- |
| **D11 — never spontaneous TTS** | the Slice 07 row read not restated; no speech field on the type; an equality import allowlist | `test_aucune_nature_de_parole_n_est_admise_pour_un_point_d_attention` (every `SpeechKind`), `test_un_point_d_attention_ne_peut_pas_se_declarer_autorise_ni_parlant` (`dataclasses.replace` refused), `test_la_charge_utile_ne_porte_aucun_champ_de_parole`, `test_le_juge_d_attention_ne_charge_que_des_modules_declares` |
| **Search failure/absence ≠ contradiction** | step 3 before the verdict; closed table; a guard that meets its forbidden state | `test_une_recherche_ratee_ne_devient_jamais_une_contradiction`, `test_une_recherche_sans_conclusion_ne_devient_pas_une_alerte` ×3, `test_la_table_d_alerte_ne_peut_pas_accueillir_un_verdict_non_concluant` + `test_la_table_saine_passe_la_garde` |
| **Evidence / provenance / confidence gating** | steps 5–8, resolved against the live snapshot | `test_sans_piece_il_n_y_a_pas_d_alerte`, `test_une_piece_qui_ne_designe_aucune_source_connue_est_refusee`, `test_une_affirmation_absente_de_l_ensemble_de_travail_est_refusee`, `test_sous_le_seuil_de_confiance_rien_n_est_signale`, `test_un_evenement_d_attention_ne_peut_pas_exister_sans_preuve` |
| **Dismissal must not mutate facts** | local UI state, **no network call at all**; no edge from the Control Center to the store | `test_ecarter_l_avertissement_n_emet_aucune_requete` (real HTTP log between two markers), `test_acquitter_ne_touche_ni_la_charge_utile_ni_l_ensemble_de_travail` (snapshot identity unchanged) |
| **One sound, deduped across polling/reload/tabs** | §4 | `test_une_contradiction_donne_une_carte_et_au_plus_un_signal`, `test_le_sondage_ne_rejoue_ni_carte_ni_signal_apres_un_rechargement`, `test_deux_onglets_ne_sonnent_qu_une_fois` (real oscillator count), + 8 node tests on `claimCue` |
| **Capability gating** | `_raise_attention` reads `FACT_VERIFICATION` from the job's own grant | `test_seul_un_travail_qui_pouvait_verifier_peut_alerter` — driven through the **real** `submit_trigger` path, `checkable_claim` vs `new_topic` |
| **No source-text assertions** | none in this slice | every JS claim is computed style, geometry, rendered `textContent`, a real network log or a WebAudio call count |
| **"X can never happen" is a test case** | every header invariant has one | table-poison, both/neither decision, store-refusal, secret-phrase trace hygiene, event-without-evidence |
| **Make invariants observable** | `AttentionCounters` (one counter per refusal code, none bucketed), `raised_ids`, `stats()` | `test_chaque_refus_est_compte_sous_son_propre_code` (all 8 codes), `test_un_point_refuse_par_le_magasin_ne_pose_aucune_ligne` asserts `raised_ids == ()` — without it a test cannot tell "nothing was signalled" from "the snapshot did not move" |
| **G6 — a throwing module takes down the others** | install refuses under a searchable code and catches its own refusal; `gate` never raises | `refreshStatus` wraps the gate as it wraps the other four; 11 hostile-payload node cases; the browser suite asserts `installed` |

### Rule Zero

The card *is* the visible feedback, not a long operation, so no live counter is
due. The obligations that do apply are met: the expected path logs at `info`
(`not_raised` is the ordinary "no alert" outcome, so an empty journal never means
both "fine" and "dead"), every refusal is named and counted rather than bucketed,
a broken journal is counted rather than silent, and the card says plainly what to
do next — "Jarvis ne le dira pas de lui-même : demandez-lui ce qu'il a trouvé."

---

## 7. Mutations — 55 run, zero survivors besides the deliberate control

The harness (`scratchpad/s09_mutate.py`, namespaced because the scratchpad is
shared — it currently holds four other agents' `mutate*.py`) refuses to start on
a red baseline, verifies the tree by **content markers** rather than `git status`,
and carries `M00-CONTROL`, a cosmetic comment change that **must survive**.

**Round 1 — 50 mutations: 44 caught, 5 real survivors, 5 silent SKIPs.**

Five survivors, every one a genuine test gap, all now closed:

| Mutation | Why it survived | Fix |
| --- | --- | --- |
| **M14** `or`→`and` in the evidence guard | every test reached the type through `decide_attention`, which refuses empty evidence one step earlier. **The type's own invariant was guarded only by the gate's.** | `test_un_evenement_d_attention_ne_peut_pas_exister_sans_preuve` constructs the type directly |
| **M20** drop `counters.refuse(...)` | no test read the refusal counters — the observability this module claims was itself unobserved | `test_chaque_refus_est_compte_sous_son_propre_code` exercises all 8 codes |
| **M24** unbound the evidence list | my hostile payload only ever contained **one** valid piece, so the bound was never crossed. *A test exercising a guard's code without reaching the state the guard exists for* — the pattern this handoff catalogued three times, and I walked into it | a hostile entry with 40 pieces, plus an assertion that the last payload actually **hit** the bound |
| **M31** narrow `except Exception` to `ZeroDivisionError` | `_run` catches everything anyway and counts the same `failed`, so the test was **true about the system and false about itself** (Slice 06's finding) | assert which journal line fired: `attention_failed` present, `normalise_failed` absent |
| **M33** neutralise the leader lease | the two-tab test used the **same** sequence number, which the high-water mark blocks regardless — the lease was only tested where it was redundant | a test where the sequence *rises* between the two tabs, so only the lease can hold |

Five SKIPs were **not passes and not failures — they were silent non-events**:
every file in this repo is CRLF, and my multi-line patterns were written with
`\n`, so they matched nothing and the mutation never ran. This is "a probe that
passes proves nothing" in a new shape, and it is exactly the trap this task warned
about. The harness now translates each pattern into the file's real line ending
and prints `<-- A CORRIGER` on any skip. All five then ran: **all caught.**

One mutation, **M08, was an equivalent mutant** — it inserted a no-op `if …:
pass` rather than actually swapping the two checks, so it could not be caught by
anything. Replaced with a real order inversion; then caught.

**Closing M14 revealed a real product defect.** `PresentationAttention.__post_init__`
called `to_item()` *before* validating the evidence tuple, and `to_item()` reads
`source_ids`, which walks the pieces. A malformed piece therefore raised a bare
`AttributeError` — an **untyped** refusal, which `decide_attention`'s
`except (PresentationWorkingSetError, TypeError, ValueError)` would not have held,
breaking its "never raises" promise. Unreachable through the gate, reachable by
any direct caller. Fixed by validating the pieces first.

**Round 2 — the 5 survivors, the 5 corrected skips, M08, and M50–M54: all caught.**
M50–M53 had never run in round 1: my `-k`-style filter was `M4`, which selects
M40–M49 and silently excludes M50+. Caught only by counting the RESUME entries
against the mutation list — the same class of error as the SKIPs.

`M54` was added after a regression surfaced (§9) and is caught.

**Final tally: 55 mutations, 54 caught, 1 survivor — `M00-CONTROL`, as required.**
In every batch containing it the harness reported `controle cosmetique survivant:
True`. Batches run without it report `False`; that is a reporting artifact of the
filter, not a lying harness, and the control was verified in the batches that
included it.

### One honest note on the harness

Round 1 ran as a background process and was **killed by the system for low
memory** just as it reached its own closing baseline check, which therefore
printed `BASELINE apres restauration: RED`. I did not trust any result until that
was resolved: I re-ran the suite in the foreground immediately (**49 passed**) and
re-verified the tree markers (**all present**, diffstat unchanged). The RED was
the kill, not a failure. Every later batch ran in the foreground and closed
`GREEN` with `arbre apres: OK`. Backgrounding it was my mistake — the task says
foreground, and the reason is exactly this machine's memory.

### Guard probe

`test_le_juge_d_attention_ne_charge_que_des_modules_declares` was probed end to
end:

1. confirmed the `-k` filter **selects** it — `1/38 tests collected (37 deselected)`;
2. planted `from jarvis.core.speech_scheduler import SpeechScheduler`. **The probe
   failed for the wrong reason** — that module does not exist, so the failure was
   a `ModuleNotFoundError` at collection, not the guard firing. This is the Slice
   08 lesson landing on me: a probe's *outcome* must be checked, not just its
   sign;
3. used the real path, `jarvis.runtime.speech_scheduler`. The guard then failed
   **by name**, enumerating the intruders including `jarvis.runtime.speech_scheduler`;
4. probe removed, 38 passed, `grep -c "PROBE S09"` → 0.

---

## 8. Test commands and counts

All foreground, narrow lists, `-q -p no:cacheprovider`.

```
.venv/Scripts/python.exe -m pytest \
  tests/unit/test_background_events.py tests/unit/test_control_center_mvp.py \
  tests/unit/test_control_center_quality.py tests/unit/test_documented_routes.py \
  tests/unit/test_presentation_working_set.py tests/unit/test_presentation_speculative.py \
  tests/unit/test_presentation_response_policy.py tests/unit/test_scene_renderer_logic.py \
  tests/unit/test_presentation_attention.py tests/unit/test_presentation_attention_js.py \
  -q -p no:cacheprovider
→ 578 passed in 45.77s

.venv/Scripts/python.exe -m pytest \
  tests/unit/test_interaction_mode_hud_js.py tests/unit/test_interaction_mode_hud_browser.py \
  tests/unit/test_barehands_contracts_js.py tests/unit/test_presentation_attention_browser.py \
  -q -p no:cacheprovider
→ 87 passed in 101.26s

.venv/Scripts/python.exe -m pytest \
  tests/unit/test_presentation_attention.py tests/unit/test_presentation_attention_js.py \
  tests/unit/test_presentation_attention_browser.py -q -p no:cacheprovider
→ 92 passed   (39 + 40 + 13 — the new suite; the 91 measured before the
                 status-contract test of §9 was added)
```

Every file on the mandated re-run list is covered: `test_background_events`,
`test_control_center_mvp`, `test_control_center_quality`,
`test_interaction_mode_hud_js`, `test_interaction_mode_hud_browser`,
`test_presentation_working_set`, `test_presentation_speculative`,
`test_presentation_response_policy`, `test_scene_renderer_logic`,
`test_documented_routes`. **666 distinct tests, zero failures.**

### Blast radius

Declared baseline re-measured file by file:

```
test_scene_artifacts(6) test_scene_batch_tools(3) test_scene_capture(1)
test_scene_interaction_logic(1) test_scene_query_tools(2)          → 13 failed / 156 passed
test_scene_service(2) test_scene_settings(2) test_scene_transport_client(4)
test_barehands_interaction_js(2) test_barehands_tutorial_retired_js(1)
test_brain_delegation(1)                                            → 12 failed / 151 passed
```

**25 failures, exactly the declared baseline, name for name.** Neither known flake
reproduced (`test_back_brain_tasks[owned_read]`,
`test_back_brain_worker::test_cancel_during_spawn…[claude]`).

---

## 9. One regression I introduced, found and fixed

The first version put `"attention": [...]` unconditionally in the status
`background` block. `test_brain_delegation.py::test_background_events_are_counted_read_and_acknowledged`
pins that block by **strict equality**, so it failed — a 26th failure against a
declared 25.

I found it by re-measuring the baseline file by file rather than trusting the
count, and I fixed it the better way rather than the lazy one: **the key is now
omitted when empty.** That block goes out every second and the ordinary second has
no attention at all, so the payload is byte-identical for every existing
consumer, and an older server reads exactly like a server with nothing to signal —
which the page already treats the same way. Editing the existing test would have
worked and taught nothing.

Pinned by `test_le_statut_ne_porte_le_bloc_d_attention_que_s_il_y_a_quelque_chose_a_montrer`
and by mutation **M54**.

---

## 10. Where SLICE.md and the live repository disagreed

State them, do not silently resolve them:

1. **`docs/02-architecture.md` and `docs/01-decision-log.md` do not exist in
   `docs/`.** They live under `tasks/jarvis-presentation-interaction-mode/docs/`.
   Slice 08 already reported this as pre-existing doc drift and it is still open:
   `docs/presentation-ambient-lane.md` and `docs/presentation-working-set.md` both
   cite `docs/02-architecture.md`. My own contract page cites it the same way, to
   stay consistent with its neighbours rather than diverge unilaterally — but the
   drift is real and belongs to whoever closes it repo-wide.

2. **SLICE.md lists categories "contradiction, uncertainty, useful_context,
   source_found, data_issue"; Slice 04 shipped `contradiction, mismatch,
   missing_source, stale_resource`.** The LOG binds Slice 09 to *extend* Slice
   04's enum rather than declare its own, so I used the shipped four and did not
   rename or widen them. `uncertainty` in particular must **not** become a
   category here: `ClaimStatus.UNCERTAIN` is precisely the value that must never
   alert. Not silently resolved — the two vocabularies genuinely differ, and I
   followed the LOG.

3. **Slice 04's report says `MAX_ATTENTION_REASON_CHARS = 160` is "one line for
   Slice 09's floating warning".** I did not use it that way. `reason` is
   speech-derived, and Slices 04, 06 and 08 all set the rule that room speech
   never enters the durable trace — which is the only bus between Core and the
   Control Center. So the card is composed in the browser from typed references
   (category, band, source titles and links) and `reason` stays in the working set
   for Slice 10's addressed turn, which is literally `HV-PRES-ALERT-01`'s own
   script ("then optionally ask Jarvis what it found"). **This is a deliberate
   divergence from a prior slice's stated expectation**, argued in
   `docs/presentation-attention.md` §5, and the reviewer should agree or overrule
   it explicitly.

4. **SLICE.md step 6 says "ensure one leader/tab emits sound".** The leader
   mechanism is only one of three layers, and it is the only one that was
   missing. Saying which layer holds which case (§4) matters more than the
   mechanism itself, and `bgCue`'s existing rules were honoured rather than
   rebuilt.

5. **SLICE.md's "Automated Validation" names "status/poll and attention contract
   tests"; there is no runtime to poll.** No composition root wires any of this,
   exactly as for Slices 05, 06 and 08. The browser suite is the closest true
   equivalent: it runs the real page against a real HTTP `/api/status`.

---

## 11. What I could not satisfy

- **`HV-PRES-ALERT-01` is not reachable from this slice, and I do not mark it
  done.** `PresentationAttentionService` has no composition root, and neither does
  the speculative runner that would feed it (Slice 08 left that to Slice 11), nor
  the ambient lane (06), nor the audio session (05). Nothing in a running JARVIS
  reaches this code today. **Slice 11 must wire the judge** —
  `PresentationSpeculativeService(attention=…)` — before a human can create a
  controlled fact and watch the cue.

- **The cross-tab guarantee is strong, not absolute.** `localStorage` has no
  atomic compare-and-swap; §4 states the residual precisely rather than implying
  a proof. `BroadcastChannel` would not fix it either — it is also not atomic.

- **Below ~420 px the Control Center's bottom is a pile-up that predates this
  slice** (measured: toasts over the voice hint, the pills and the dock). The card
  inherits those conflicts. Fixing them is a page-wide job, not a Presentation
  slice's.

- **`MISMATCH`, `MISSING_SOURCE` and `STALE_RESOURCE` are unreachable** from this
  door in V1, for want of a verdict that names them. Declared and said, not
  quietly left to look available.

- **The confidence thresholds are uncalibrated.** They are inherited caution, and
  the surface is built so that no number is ever shown. Calibration needs real
  sessions and is nobody's slice yet.

- **`background_events` / `background_ack` routes hand-roll their refusal
  payload** (`{"ok": False, "error": …}`) instead of going through
  `send_error_response`. Pre-existing, untouched by me, and shared by much of this
  server; flagged rather than fixed inside a Presentation slice. My own additions
  raise nothing out of those routes.

---

# Reprise — commit `630df7b`

Four blocking defects and fourteen items. Every blocker was closed **test first**:
the test that reaches the state was written, confirmed failing against the
shipped code, and only then was the code changed.

The `reason` ruling is recorded in `docs/presentation-attention.md` §5 as upheld.

## B1 — a refused tab stole the cue lease, and a real contradiction went silent

Exact defect: the lease was written **before** the high-water mark was consulted,
and never released when the mark refused. A tab with nothing to announce became
the three-second leader and silenced every other tab for any genuinely new event.

Fixed by **reordering rather than releasing**. The suggested
`removeItem`-on-refusal works; consulting the mark first is stronger, because
there is nothing to release — a tab with nothing to announce now touches neither
the lease nor the mark. The lease serialises the tabs that *do* have something to
say; it is not a veto taken on the way out.

Item 10 came with it: the age is now bounded on both sides, so a backwards clock
correction (`at` in the future, negative delta) is no longer read as "held".

Tests, both failing before the fix:
`test_un_onglet_refuse_par_la_borne_ne_garde_pas_le_bail` follows QA's exact
trace — A cues 100, B wakes after expiry and is refused by the mark, then a
genuinely new event arrives — and asserts the three things that matter: B does
not cue, B is **not** the leader afterwards, and **A can still cue**.
`test_un_bail_pris_a_rebours_d_horloge_ne_fait_taire_personne` covers the clock.

And the blind test is fixed: `test_la_borne_haute_tient_meme_quand_le_bail_a_change_de_main`
now also asks whether **A** can still sound. That was the half it never queried —
the sixth occurrence in this task of a guard exercised without reaching the state
it guards, and the reason the defect survived my own round.

## B2 — the card made the acknowledgement pill unclickable

Reproduced before fixing, with `elementFromPoint` rather than overlap alone:
at 1440×520 and 360×640 the card received the click, at 700×600 its chevron did.

Fixed with a **52 px right margin** clearing the pill column (28 px wide at 30 px
from the edge, 22 px below 940 px). The pills follow the viewport *centre* while
the toast rail is anchored to the *bottom*, which is why only a short viewport
brings them together.

**The measurement set now carries a short-and-wide viewport permanently**:
`(1440,520)`, `(1280,560)`, `(700,600)`, `(360,640)`, `(1440,900)`, `(820,900)`.
Six sizes was not the problem — the hole in the set was, and it sat exactly where
this defect lives.

## Item 1 — the card covered the voice hint, taken with B2

820×900 (inside the original set, but just above the 760 px threshold) and
1440×900 with the panel open, where the rail shifts left onto the centred hint.

Fixed by **deleting the threshold**, not moving it: the 44 px lift is now
unconditional. A threshold that is wrong in one measured case will be wrong in
another. Below 700 px the escape also changed from horizontal to **vertical** —
a 136 px bottom margin puts the card above the mode-control band, which clears
the pills, the dock and the hint at the same time and is independent of width.
Narrowing worked at 500 px and failed at 360, where the card fell back onto the
mode control.

Four new browser tests, all failing first:
`test_la_carte_ne_vole_jamais_le_clic_de_la_pastille` (6 sizes),
`test_la_carte_ne_recouvre_jamais_l_indication_vocale` (4 cases incl. panel open),
`test_la_carte_ne_deborde_jamais_de_la_fenetre` (688/694/700/706 — both sides of
the cliff).

## B3 — "never raises" was asserted three times and true once

All four unguarded paths are now guarded, and **each has a test that reaches it**:

| Path | Guard | Test |
| --- | --- | --- |
| `set(known_claim_ids)` outside the `try` | `_id_set()` → `INVALID` | `test_la_porte_ne_leve_pas_sur_un_instantane_inutilisable` (4 hostile inputs) |
| `list(assessments)` | `except TypeError` → `batches_invalid` | `test_le_service_ne_leve_pas_sur_un_lot_qui_n_est_pas_iterable` |
| `self._store.apply(...)` | `except Exception` → `store_failed`, **nothing signalled** | `test_le_service_ne_leve_pas_quand_le_magasin_lui_meme_casse` |
| `_now()` | returns `None` → typed refusal | `test_le_service_ne_leve_pas_quand_l_horloge_casse` |
| `NOT_CONSTRUCTIBLE` unreached | — | `test_la_porte_nomme_un_evenement_qu_elle_ne_peut_pas_construire` |

A `str` is refused as an id collection. It is iterable, so `set()` would have
accepted it and produced a set of **letters**, turning a caller's mistake into a
perfectly plausible and perfectly wrong `attention_claim_unknown`.

**On the shape.** You are right that this is M14 again, and that I closed one
instance without sweeping the class. I have now swept it: every totality promise
in both modules is exercised at its edge, and the contract page states the
promise and the tests that hold it (§3b).

One correction to the brief: `NOT_CONSTRUCTIBLE` *was* reachable — an illegal
`attention_id` reaches it — but **no test reached it**, which is the same thing
in practice. It is reached now, twice.

## B4 — the burst-limiter test proved nothing about bursts

Rewritten: default bound, **three distinct `claim_id`s**, asserting exactly two
`ATTENTION_RAISED_KIND` lines — the property the docstring names, the number of
sounds. `MAX_ATTENTION_PER_BATCH` is now referenced by a test, and mutating it to
1000 is caught (R12). The store fixture carries three distinct claims so a burst
can be a burst.

## The other items

| # | Done |
| --- | --- |
| 2 | **One decider.** The lane reads the token and *passes the value*; the domain refuses; the lane counts `CAPABILITY_MISSING` from the decisions it gets back. Step 2 and that code are now reachable in production. Judge failure gets `attention_failures`, separate from the generic `failed`. |
| 3 | `armed` deleted. `statusLost()` now returns plainly and its comment says it is **deliberately inert**, and why — the behaviour comes from `refreshStatus` not calling `gate` on a failed fetch, not from a flag. |
| 4 | The unreachable half of the evidence guard removed; `AttentionEvidence` already refuses an empty locator. |
| 5 | The headline comes from the client-side `CATEGORY` table. `entry.label` is no longer read, so a future producer on that kind cannot put speech on the card. |
| 6 | Stated, not implemented: dismissal is per-tab (no `storage` listener), and the contract page says so next to the note that the **cue** is deliberately cross-tab. |
| 7 | Deleted: the whole `resource_ids` vertical, six view fields (`seq`, `category`, `band`, `claimId`, `topicId`, `ts`), the `severity` transport, `FactCheckAssessment.source_ids`. `severity_for` stays — it feeds store coalescing. |
| 8 | Tests added for `[:64]` and the `[-16:]` ring; `_ids()` and `MAX_ATTENTION_RESOURCE_REFS` deleted with the vertical. |
| 9 | The vacuous assertion went with the rewritten lane test. |
| 10 | Done with B1. |
| 11 | The probe is documented in the guard's own docstring, including that the first attempt failed for the wrong reason. |
| 12 | Escape closes then dismisses, on the card, stopping propagation only after acting. The 688–700 px overflow is covered by a test on both sides of the cliff. **`target="_blank"` kept**, as a stated judgement: navigating the Control Center away from a live session is worse than a new tab, and those are a link's only two options. |
| 13 | One `safeStorage()` probe, hoisted. |
| 14 | Citation corrected to the handoff path, with a note that the neighbouring pages still carry the wrong one (pre-existing, Slice 08, open repo-wide). |

## Mutations — 21 in the rework round, zero survivors besides the control

`git diff --stat` is printed before **every** verdict, as asked, so a patch that
never applied cannot read as "caught".

Four survivors were found and closed, and three of them were my tests, not my code:

- **R19** — the ring bound. My test reused three `claim_id`s, so the store
  coalesced and only three ids ever entered: the bound was never reached. Fixed
  with twenty distinct claims **and** an advancing clock, because the store's own
  bound of 8 otherwise refuses rather than evicts. Now asserts `== 16`, not `<= 16`.
- **R21** — moving `stopPropagation()` above the key check makes the card swallow
  *every* keystroke. My Escape test only pressed Escape. New test installs a
  document-level witness and presses `a` and `F9` as well.
- **R17** — the headline. My fixture's trace `label` was exactly the table's
  sentence, so the two sources were indistinguishable. New test makes them differ
  and asserts the trace message never appears on the card.
- **R11** — an equivalent mutant: the `isinstance(raised_at, datetime)` check I
  added was already covered by the `try` below it. Dead defensive code, deleted;
  the mutation now targets the real guard (the typed `except`).

### The harness defect this round exposed

A round killed by the system's memory reaper **left R20 applied on disk**, and my
tree check passed because it verified only *one content marker per file* and that
marker was intact. I then took a "backup" of the already-mutated file and probed
against it. Caught by noticing that a pattern search returned 0 while the file
visibly contained the mutation.

`tree_ok()` now verifies that the original text of **every mutation site** is
present exactly once. A partially restored file can no longer hide behind a
healthy neighbour. This is the same family as the CRLF skips from the first
round: the harness reporting a state it had not actually checked.

Both background rounds were killed for memory; the browser mutations were then
verified by **targeted foreground probes** (one short Chrome session each,
mutation applied, `-k` run, restored, tree re-verified) rather than a full batch.
R01–R05 completed inside the killed run before it died and are recorded with their
diffstats; R17, R20 and R21 were probed individually. I did not restart the
background batch.

## Counts

```
test_presentation_attention.py           51 tests
test_presentation_attention_js.py        42 tests
test_presentation_attention_browser.py   30 tests   (123 total, was 92)

530 passed  — attention, node, ledger, speculative, control-centre MVP + quality,
              documented routes, working set, response policy
 30 passed  — browser suite, 208 s
```

**Baseline re-measured file by file: 25 failures, exactly the declared set, name
for name.** 13 in `test_scene_artifacts/batch_tools/capture/interaction_logic/query_tools`,
12 in `test_scene_service/settings/transport_client`, `test_barehands_interaction_js`,
`test_barehands_tutorial_retired_js`, `test_brain_delegation`. Neither known flake
reproduced.

## Left alone, as instructed

The cue plays the existing `bgCue` **failure** variant, so a verified
contradiction sounds like a crashed agent. Untouched and handed to you for the
Human's call.
