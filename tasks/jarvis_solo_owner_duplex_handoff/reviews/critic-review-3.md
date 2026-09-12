# Critic review 3 — JARVIS Solo Owner Duplex + Core Work State handoff

Reviewer: independent adversarial auditor (read-only on the implementation).
Date: 2026-09-12. Tree audited: uncommitted working tree on `main` @ `e292784`,
after the two round-2 fix agents.
Round 1: `reviews/critic-review-1.md` (80/100). Round 2: `reviews/critic-review-2.md` (87.5/100).

Out of scope and excluded from scoring (unchanged): the parallel "brain
availability / delegation" effort (`brain_service` supersession / turn budget /
`announce_notice`, `claude_local.py`, `control_center_brain.py`,
`app._brain_availability_from_env`, `v2_app._brain_notice_loop`,
`tests/unit/test_brain_delegation.py`) and the user folders `docs/reviews/`,
`transcript/`.

---

## Score: 93.5 / 100 (R1: 80 → R2: 87.5 → **R3: 93.5**)

| Dimension | Weight | R1 | R2 | R3 | Comment |
|---|---|---|---|---|---|
| Conformance to the handoff docs | 30 | 27 | 28 | **29** | The over-strong producer-restart sentence R2 deducted for is rewritten and now matches the code exactly (I reproduced its numbers). NB11 fixed **with a guard** (`test_documented_routes.py`). Every Task 11 acceptance re-verified against the real store. Residual: two documented divergences (NB8, NB16) still stand, honestly labelled; "AEC-cleaned" in two doc lines overstates the degraded branch; `tasks/TODO.md:30` still unticked. |
| Correctness & robustness | 25 | 17 | 20 | **23** | R1 is genuinely repaired, not test-satisfied: 28/28 of my own probes pass, including the two-Control-Center thrash, the forged `error_class`, the stale observation, private-map leakage, eviction pruning, and every Task 11 acceptance. I hunted for defects the fix could have introduced and found none that bites. Held back from 25 by three accepted-but-real degradations (two-CC config ends all work permanently `interrupted`; `MAX_PRODUCERS` overflow silently forgets a claim, undocumented; the verifier is fed un-cancelled audio on three AEC-degraded branches). |
| Tests | 20 | 16 | 18 | **19** | Both R2 test gaps closed. Five new R1 tests, each of which I independently reproduced against the real store with my own code — they are real oracles, not tautologies. The benchmark guard went 11 → 20 tests and now catches **28/28** structural falsifications (all 11 R2 named misses + 17 of my own) and 284/359 single-number README mutations. 4 green full suites (2 standalone + gate + a concurrent pair) and 6 green targeted timing runs; no flake, and R2's watch item did not reproduce. |
| Truthfulness of the reports | 10 | 7 | 8 | **8.5** | All four R2 truthfulness deductions are corrected (the blanket "every figure is re-derived", the misleading flat-P50 sentence, the stale `test_trace_summary` count, the producer-restart over-claim). The new machine-checked / not-machine-checked split is materially accurate but still slightly over-strong: ~6 measurements in README prose are in neither set (detail below). |
| Documentation | 10 | 8 | 8.5 | **9** | Route template fixed and guarded; `work_state.py`'s docstring now states what the code actually enforces; a new, accurate row documents two concurrent Control Centers. Still open: `control_center.py:750` "sonde bon marché", the unticked TODO line, and the "AEC-cleaned" wording. |
| Safety / privacy | 5 | 4.5 | 5 | **5** | Re-verified independently and at runtime: the new private attribution maps never reach any payload **or the diagnostic sink**; 18 wire keys; zero vendor imports in `domain`/`ports`/`core`; nothing biometric reachable by Git (`git check-ignore` proven on 6 paths, `git add -A --dry-run` stages no model or profile); the ingress rejects `prompt` / `raw` / `transcript` / `embedding` / `trace` with 400 on a live server. |

**Verdict:** both blocking defects are genuinely fixed — R1 by moving the reopen
authority into Core-private state that provably cannot leak, R2 by making
`figures()` total and comparing tables in position. I could not construct a
falsification either guard misses, and I found no new defect the fixes
introduced. **This work is finished (≥ 90). No blocking defects remain.**

---

## R1 — verdict: **FIXED** (high confidence)

*Defect was: the producer-restart reopen ignored producer identity and trusted a
wire-settable `error_class`, so two Control Centers thrashed forever, the brain
was fed unbounded false "interrupted" notices, and any producer could reopen its
own terminal item — including with a stale observation.*

The fix (`jarvis/core/work_state.py`) keeps two maps on the **store**, never on
`WorkItem`: `_owners` (`:172`) and `_core_interrupted` (`:173`). Reopen authority
is `_may_reopen` (`:317-327`): the key must be one **Core itself** interrupted
while claiming the source, **and** the speaker must be the source's current
claimant. `_core_interrupted` is written only inside `interrupt_source`
(`:313-314`), under `error_class == PRODUCER_RESTARTED` and a confirmed `UPDATED`
outcome — a producer's own `error_class` never enters it. `interrupt_source`
takes `owner=` (`:301`) so a displaced instance carries away only its own items.
`_reopened_after_producer_restart` (`:90-111`) keeps `current.updated_at`, so the
reopening observation is ordered like any other.

I re-ran an independent probe (28 checks, my own code, against the real
`WorkStateStore`): **28/28 pass**.

| Probe | Result |
|---|---|
| Two Control Centers, 7 alternating rounds, 2 items each | revisions `[6, 8, 8, 8, 8, 8, 8]`, **4** attention notes (one per item), `outcome_totals {'created': 4, 'updated': 4, 'terminal': 24}`, state stable at rest. R2 measured revision 54 / **26** notes / permanent flapping on the same scenario. |
| Producer forges `status=interrupted, error_class=producer_restarted`, then reports the item running | outcome `terminal`, item stays `interrupted`, activity `''` |
| …and a *new* claimant then tries to reopen that forged terminal item | outcome `terminal` — the forged marker is inert for everyone |
| Observation 6 s **older** than the Core interruption, from the current claimant | outcome `stale`, item stays `interrupted`, activity `''`. Dropping `min()` on `updated_at` has exactly this consequence and no other I could demonstrate: the DUPLICATE branch (`:251-255`) takes `max(reopened.updated_at, observation.observed_at)`, which keeps `updated_at ≥ started_at` and keeps the revision strictly increasing. |
| Legitimate restart-reopen (observation newer than the interruption) | `updated`, `running`, `error_class=None`, `ended_at=None` |
| Reopen by an otherwise-identical observation | `updated` (the DUPLICATE branch fires; the item does not stay interrupted) |
| Private maps in bus payloads / snapshot / ingest ack / **diagnostic data** | producer ids appear in none of the four; item keys are the 20 public ones only |
| Eviction prunes both maps (`_make_room`, `:362-363`) | after forced evictions, 0 orphan entries in `_owners` and `_core_interrupted`; both ⊆ `_items`, so both are bounded by `max_items` |
| Evicted Core-interrupted key | outcome `evicted`, does not resurrect, not reopenable |
| **Task 11 acceptances** — Claude clean stop / `process_stopped` | `completed` stays, `process_stopped` stays terminal and is **not** reopenable by the claimant (the exception really is narrow) |
| Task 11 — idempotency | `created`, then `duplicate ×4`, revision +1 total |
| Task 11 — revision monotonicity | 30 mixed batches, strictly non-decreasing, no item newer than its snapshot |
| Task 11 — bounded retention | 300 items → 64 kept, `_evicted` 236 ≤ 4096, `_owners` 64 |
| Task 11 — Core restart | empty store, fresh `store_id`, revision 0; first contact interrupts nothing |
| Task 11 — Control Center restart of genuinely abandoned items | abandoned item stays `interrupted` / `producer_restarted` through 5 later batches; the live item survives and keeps updating |
| Task 11 — other sources and Core-internal observers | `interrupt_source(owner=)` spares both (`_owners` is unset when `producer is None`) |
| Adversarial: 3-instance chain, ownership re-attribution, later takeover of a reopened item, reopen chain, mid-batch claim ordering | all coherent; a reopen re-attributes `_owners` to the reopening producer and revokes the Core mark (`:271-274`) |

The five new repo tests (`test_work_state_store.py`, 44 → 49) are **not**
tautological: each one's expected value I reproduced independently with my own
harness before reading the assertion — the revision series `[6, 8, 8, …]`, the
note count 4, the `terminal` and `stale` outcomes, and the payload-absence check
all match.

## R2 — verdict: **FIXED** (the substantive defect; a small honesty residue remains, non-blocking)

*Defect was: the pages promised "every figure on this page is re-derived by
`scripts/speaker_benchmark_figures.py`" while `figures()` exposed no key for six
figure classes, `_number((row.get(k) or 0) * 100, 1)` turned a missing metric
into `0.0`, and a mutation harness caught 0 of 11 real falsifications.*

`scripts/speaker_benchmark_figures.py` now routes every read through `_dig`
(`:110-118`), which raises `KeyError` on an absent path — `_pct` and every
resource/gate/sweep/zero-FA/scenario figure go through it. The six missing
classes are exposed: `model_verify_ms` and `hop_ms` p50/p95 (`RESOURCE_FIGURES`),
the zero-FA columns (`ZERO_FA_FIGURES`), `noise_hops`/`noise_hops_accepted`
(`SWEEP_COUNTS`, `AT_ENGINE_COUNTS`), `cpu_ratio_vs_baseline`, and per-scenario
plus per-tag scores (`_scenario_figures`). The guard grew 11 → **20** tests and
compares Markdown **cells in position** (`table()` / `cells()`,
`test_published_benchmark_figures.py:78-106`).

I re-built the mutation harness from scratch (doc copies edited, the JSON
artifacts never touched, page paths monkeypatched).

**Positive controls:** 4/4 caught (each page emptied → 13 / 7 / 2 test failures;
a deleted gate-table row → 1 failure). Unmutated copies: 0 failures.

**Structural falsifications: 28 built, 28 caught, 0 missed** — including all
eleven R2 named misses:

| # | Falsification | Caught by |
|---|---|---|
| R2#1 | swap the two engine columns of the README cost table | `…cost_table_of_the_readme_is_anchored_per_row_and_per_engine_column` |
| R2#2 | falsify the whole `wespeaker` row of the 2026-09-11 table | `…2026_09_11_table_matches_its_own_settled_json_row_by_row` |
| R2#3 | falsify the report's entire baseline gate row | `…cost_cells_of_the_final_report_are_anchored_per_row` |
| R2#4 | rewrite the short-reply prose to "only one … none" | `…short_reply_counts_are_the_published_ones_not_just_the_word` |
| R2#5 | `noise_forwarded_ms` in the report | `…noise_figure_of_the_final_report_names_both_campaigns` |
| R2#6 | `owner_start_lost_ms_p95` (2.79 s) | `…decision_paragraph_of_the_readme_quotes_the_gate_sweep` |
| R2#7 | `model_verify_ms` (OPERATIONS) | `…operations_cost_paragraph_comes_from_the_settled_json` |
| R2#8 | `hop_ms.p50` (OPERATIONS) | same |
| R2#9 | the 865.5 ms contention figure | same |
| R2#10 | README EER column | `…gate_table_of_the_readme_matches_the_strict_gate_sweep_cell_by_cell` |
| R2#11 | gate-table leaked-ms / P95 cells | same |

Plus 17 of my own, all caught: engine-name swap in the gate table; row
permutation in **both** tables; cost-table row-label swap; reversed
confirmation-latency series; deleted "provisional pending real owner data";
altered CPU ratio; altered scenario score and tag mean; altered
"0 of 354 for all eight"; altered embedding dim; altered zero-FA cell; altered
manifest scenario count; falsified `replays_clamped`; altered strict-run load
sentence; altered 2026-09-11 P95 series; altered `at_engine` FRR paragraph.

**Systematic single-number sweep** (every numeric token perturbed one at a time):

| Region | Mutations | Caught | Missed |
|---|---|---|---|
| `docs/results/speaker-benchmark/README.md` L31-189 | 359 | 284 | 75 |
| final report §"Benchmark results" L283-360 | 164 | 63 | 101 |
| `docs/OPERATIONS.md` guarded paragraphs L1140-1352 | 73 | 15 | 58 |

The two big "missed" columns are mostly **out of the claimed scope and correctly
so**: the report's misses are concentrated in the *Defaults decision* table and
the "Reading the two rejection figures" bullets, which the report's own
"What the guard covers" sentence deliberately does not claim; the OPERATIONS
window I swept over-captures CLI docs, model SHA-256 and enrolment prose that are
not benchmark figures at all. The report's **benchmark-results table (L298-299)
is 100 % caught**, and every miss in the paragraph that follows it is a threshold
label, a fixture parameter or a configuration constant — exactly what the README
declares unasserted.

**Is what the pages now declare "not machine-checked" accurate?** Materially yes,
with a small residue — see non-blocking finding 1.

---

## Blocking defects remaining

**None.** Both R2 blockers are genuinely repaired, I could not falsify either
guard, and nothing I probed in the rest of the handoff rises to blocking.

---

## Non-blocking findings

1. **The README's "What is machine-checked" sentence is still slightly
   over-strong.** `docs/results/speaker-benchmark/README.md:77-79` says "every
   measurement quoted in the paragraphs and observations around them is
   re-derived … and compared". Six statements are in neither that set nor the
   four declared exceptions:
   - `README.md:182` "All **9** overlap events were confirmed by the baseline at
     0.5 and at 0.65" — the only one with **no** corresponding key in `figures()`
     at all; mutating `9 → 0` passes.
   - `README.md:185-187` "≤ **0.35** … ≤ **0.10** … ≤ **0.05** — **11** hops
     each". The test asserts those values *against the JSON* as literals
     (`::test_the_noise_observation_is_true_of_all_eight_engines:439-445`) but
     never compares them to the page, so a page-side typo escapes.
   - `README.md:46`, `:52` restate `28.0 %`; `:51` restates `3 of his 39 turns`
     and `miss 7.7 %`; `:119` restates `(4 → 1)`. All four are asserted **once**
     elsewhere on the page, so these are unguarded duplicates rather than
     unsourced numbers.
   - `README.md:136` "~2–3×" is an approximation the README's own "What is not"
     does not list (the report's wording does cover it).
   Fix: either add the four missing assertions (a `confirmed overlap events`
   figure, and page-side comparisons of the noise thresholds and hop count), or
   extend "What is not" with a fifth class — "figures restated a second time in
   prose, and the overlap-confirmation count".
2. **Two Control Centers on one Core leave every item permanently
   `interrupted`.** `docs/ARCHITECTURE.md:1040` is accurate as far as it goes
   ("neither can reopen the other's") but stops short of the consequence I
   measured: in that configuration all four items end `interrupted /
   producer_restarted` and stay so, and every *new* item costs one more false
   attention note. The configuration is explicitly unsupported and the flapping
   is now bounded, which was the point; one more clause would make the row
   complete.
3. **`MAX_PRODUCERS` overflow silently disarms the guarantee.**
   `jarvis/core/work_state.py:83`, `:335-336`. Past 32 sources, the oldest
   producer claim is evicted; a takeover on that source then reads `known is
   None` and interrupts **nothing** (probe: `interrupted=0`, the previous
   instance's item stays `running` forever). It fails in the safe direction and
   64 items / 32 sources is generous for a single workstation, but unlike
   `MAX_EVICTED_KEYS` (`:73-81`) the constant carries no note about what is lost
   at the bound.
4. **`producer_id` is unauthenticated, so "current claimant" is whoever last
   claimed.** A producer that reuses the claimant's id can reopen a
   Core-interrupted item (probe: `updated`, back to `running`). This is not an
   escalation — anything that can reach the ingress can forge observations
   outright — and it is the only authority model available without producer
   authentication. Worth one sentence next to `_may_reopen`'s docstring.
5. **The verifier is fed un-cancelled microphone audio on three branches.**
   `jarvis/audio/duplex.py:777-792`: when `echo_cancellation` is off
   (`jarvis/app.py:530-534`), when LiveKit is absent
   (`jarvis/adapters/webrtc_echo.py:84-90`), or after the canceller raised once
   (`duplex.py:789`), `_cancel_echo` is a pass-through and the frame handed to
   `SpeakerVerificationWorker` still carries echo — a double-talk frame reaches
   the verifier's evidence intact. The handoff spec only requires "if configured
   AEC is unavailable, expose a visible degraded state"
   (`docs/.../02-architecture-spec.md:100`), and that is met loudly
   (`aec_not_installed` / `aec_unavailable` / `aec_failed` banners at
   `control_center.py:115-127`, documented at `OPERATIONS.md:981-983`, journalled
   `voice.duplex`). But `docs/ARCHITECTURE.md:341` and `docs/OPERATIONS.md:1007`
   both call the verified audio "AEC-cleaned" without qualification. Decide
   explicitly whether `speaker_verification = enforce` should be *refused* when
   no canceller exists, and soften the two doc lines meanwhile.
6. **`control_center.py:750` still calls the verifier probe "une sonde bon
   marché"** — carried over from R2 finding 2, unchanged. After the NB20 fix the
   first call hashes ~27 MiB synchronously on the aiohttp loop. The adjacent
   claim "le modèle n'est jamais chargé ici" remains true.
7. **`tasks/TODO.md:30` still shows `- [ ] 00 — Orchestrate the
   implementation`** — carried over from NB17 through two rounds.
8. **The nav subagent badge is producer-sourced without a degraded marker.**
   `control_center.html:315` feeds `updateSubagentBadge` / `watchSubagents` from
   the Control Center's own `AgentTaskTracker` (`control_center.py:480`); only
   `control_center.html:1266` switches to Core's `activeAgents()`, and only while
   the Agents tab is open with Core reachable. The main work list is correctly
   Core-first and its degraded fallback is labelled verbatim
   (`control_center.html:744-750`); the badge is the one uncaptioned exception.
9. **`.gitignore` line 28 is a lone `CR`, which Git reads as a pattern.**
   `git check-ignore -v foo/` reports `.gitignore:28:<CR>` as the matching rule.
   It ignores no real content today (`docs/`, `jarvis/`, `transcript/` all
   resolve correctly), but it makes `git check-ignore` output untrustworthy for
   any directory query.
10. **Benchmark tooling still ships inside the `jarvis` package** (NB8) and
    **`solo_owner` is still gated on `continuous_brain`** (NB16). Both remain
    documented divergences with sound reasons; carried forward unchanged.
11. **Known behavioural limits carried forward unchanged** (owner state published
    on change only; handover leak ≈ 1.2 s; a lone "oui" under ≈ 600 ms voiced
    speech dropped; `owner_onset_ms` after a non-owner verdict is an estimate;
    nothing acoustic measured on real hardware). All still labelled PENDING USER
    in `docs/HARDWARE_ACCEPTANCE.md` and in the "not verified" section of
    `docs/OPERATIONS.md`.

---

## Verified-good list (re-checked this round)

- **R1's private attribution is genuinely private.** `_owners` and
  `_core_interrupted` live on the store, not on `WorkItem`; runtime check over
  bus payloads, the snapshot, the ingest ack **and the diagnostic sink** shows no
  producer id anywhere, and no item key starting `producer`/`owner`. Both maps
  are subsets of `_items` and are pruned on eviction, so both are bounded by
  `max_items`.
- **Terminal-is-final is intact for everything but the one narrow exception.**
  `process_stopped`, `completed`, `failed` and `cancelled` are all unreopenable,
  including by the current claimant; a late terminal observation on an
  interrupted item is refused (`terminal`).
- **The ingress / store handshake still satisfies task 11 end to end.**
  `work_ingress.py:305` mints a per-process `producer_id`; `:447-453` triggers a
  full resend on a new `store_id` or after `_lost`; `resync` (`:189-202`) keeps
  pending closures; `ingest` claims **after** applying the batch
  (`work_state.py:219-224`), so a restarted Control Center never kills work its
  own first batch reports.
- **Benchmark guard is non-circular.** It parses the raw JSON through
  `figures()` and asserts against hand-written Markdown; nothing regenerates the
  prose. `figures()` raises on a missing key
  (`::test_a_missing_metric_is_an_error_not_a_zero` builds a JSON copy with
  `cpu_pct_one_core` removed and expects `KeyError`).
- **NB11 fixed *and* guarded.** `docs/ARCHITECTURE.md:1168` and
  `docs/OPERATIONS.md:591` now write `{task_id}`, matching
  `control_center.py:261`; `tests/unit/test_documented_routes.py` builds a real
  `ControlCenter`, enumerates `router.resources()` and compares every `/api/…`
  the two pages quote against it.
- **Invariants, independently re-verified.** No raw audio, transcript or
  embedding on any public surface (payload keys enumerated at runtime for
  `WorkObservation`, `WorkItem`, `WorkSnapshot`, `BrainWorkEntry`,
  `WorkAttention`, `BrainWorkContext`, `GET /v1/work/snapshot`, `GET /api/work`);
  zero non-stdlib, non-`jarvis` imports anywhere in `jarvis/domain`,
  `jarvis/ports`, `jarvis/core` (AST walk, top-level **and** function-local);
  `tools_for(continuous_brain=True)` returns `[]`
  (`realtime_tools.py:30-51`, wired at `app.py:481`), with a second barrier at
  call time (`realtime_audio.py:1339-1371`); Core authoritative for work state
  (brain reads `work_state.snapshot()`, UI reads `GET /v1/work/snapshot`, and
  `control_center_work.js:37-45` writes Core's fields *after* the tracker
  spread); a live server rejects `prompt`, `raw`, `transcript`, `embedding`,
  `trace` on both the envelope and each observation with 400.
- **Nothing biometric reachable by Git.** `git ls-files` finds no
  `.npy/.npz/.onnx/voiceprint/owner-voice*`; `git check-ignore -v` confirms six
  representative profile and model paths are ignored (`.gitignore:6`, `:25`,
  `:26`), including inside a redirected `JARVIS_RUNTIME_DIR`; `git add -A
  --dry-run` stages no model and no profile; no pasted float vector in `docs/` or
  `tasks/`.
- **R2's watch item is clear.** Two full suites run concurrently, both
  1718 passed / 4 skipped (72.46 s / 72.49 s);
  `test_state.py::test_initialize_recovers_stale_visualizer_runtime_files` did
  not fail.
- **No flake in the timing-sensitive set.** 6 × 321 passed
  (`test_voice_duplex` + `test_owner_barge_in` + `test_owner_replay` +
  `test_owner_input_gate` + `test_speaker_verifier` + `test_state` +
  `test_v2_async_conversation`), 10.22–11.50 s.
- **`test_solo_owner_acceptance.py` is a real end-to-end acceptance**, not a
  smoke test: it drives the real `CaptureProcessor`, a real
  `SpeakerVerificationWorker` over a scripted verifier, and the real conversation
  bridge, over synthesised audio; no fixture audio is versioned.

---

## Evidence appendix

Commands run from `C:\Projects\jarvis\jarvis` with `.venv\Scripts\python.exe`.

| # | Command | Result |
|---|---|---|
| E1 | `-m pytest tests -q -p no:cacheprovider` (run 1) | **1718 passed, 4 skipped**, 71.05 s |
| E2 | same (run 2) | **1718 passed, 4 skipped**, 68.92 s |
| E3 | `scripts\verify_release.py` | suite **1718 passed / 4 skipped** (69.23 s), then **"Release verification passed."** (exit 0) |
| E4 | two full suites launched **concurrently** (distinct `--basetemp`) | both **1718 passed, 4 skipped** (72.46 s / 72.49 s) — R2's watch item did not reproduce |
| E5 | 6 × the timing-sensitive set (7 files) | **321 passed** every time, 10.22–11.50 s. No flake. |
| E6 | scratch `r1_probe.py` — 28 independent checks against the real `WorkStateStore` | **28/28 pass.** Two-CC: revisions `[6,8,8,8,8,8,8]`, 4 notes, `{'created':4,'updated':4,'terminal':24}`. Forged `error_class` → `terminal` (also for a new claimant). Stale observation → `stale`. Legitimate reopen → `updated`/`running`. Eviction: 0 orphans in `_owners`/`_core_interrupted`. Retention: 64 items / 236 evicted keys / 64 owners. Idempotency `created` then `duplicate ×4`. Revision monotone over 30 batches. Core restart empty + fresh id + 0 interrupted. Abandoned item stays interrupted through 5 batches. Core-internal and other sources spared. |
| E7 | scratch `r2_mutate.py` — positive controls | 4/4 caught (13 / 7 / 2 / 1 failing tests); unmutated copies 0 failing |
| E8 | scratch `r2_mutate.py` — structural falsifications | **28 built, 28 caught, 0 missed** (R2's 11 + 17 new). Round 2 measured 0/11 on the same eleven. |
| E9 | scratch `sweep3.py` — systematic single-number sweep | README L31-189: **359 mutations, 284 caught, 75 missed**; report §Benchmark results L283-360: 164 / 63 / 101; OPERATIONS L1140-1352: 73 / 15 / 58. Report benchmark table (L298-299) 100 % caught. Misses classified in the R2 section and non-blocking finding 1. |
| E10 | `--collect-only -q` per file | work_state_store **49** (R2: 44), work_ingress 37, published_benchmark_figures **20** (R2: 11), documented_routes **2** (new), work_view 37, brain_work_context 34, solo_owner_acceptance 3, trace_summary 8 (report says 8 — corrected) |
| E11 | runtime enumeration of payload keys for the 6 work/brain types + the 2 HTTP routes | no key can carry PCM, arrays, transcript or embeddings; `WorkItem.to_payload` = 20 public keys |
| E12 | AST walk of every `.py` in `jarvis/{domain,ports,core}` for imports (top-level + function-local) | zero non-stdlib, non-`jarvis` imports; no `importlib` / `__import__` |
| E13 | live `LocalProtocolServer` on 127.0.0.1, hostile ingress payloads | clean batch → 200; `prompt` / `raw` / `transcript` on an observation → 400 `observations[0] has unknown fields: [...]`; `raw` / `prompt` on the envelope → 400 `batch has unknown fields: [...]` |
| E14 | `git ls-files` + `git check-ignore -v` + `git add -A --dry-run` on profile/model paths | no biometric artefact tracked or stageable; 6 representative paths ignored via `.gitignore:6/25/26` |
| E15 | `git status --short` before and after the audit | identical (35 modified, 60 untracked) — nothing in the repo was touched |

Scratch files were written only under the session scratchpad
(`…\409409a7-…\scratchpad\`); no implementation file, test, doc, script,
`tasks/TODO.md` entry or earlier review was modified, and no commit, stash or
revert was performed. The only file created in the repository is this review.
