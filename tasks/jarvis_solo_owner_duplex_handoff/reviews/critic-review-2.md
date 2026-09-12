# Critic review 2 — JARVIS Solo Owner Duplex + Core Work State handoff

Reviewer: independent adversarial auditor (read-only on the implementation).
Date: 2026-09-12. Tree audited: uncommitted working tree on `main` @ `e292784`,
after the four round-1 fix agents.
Round 1: `reviews/critic-review-1.md`, score 80/100.

Out of scope and excluded from scoring (unchanged from round 1): the parallel
"brain availability / delegation" effort (`brain_service` supersession / turn
budget / `announce_notice`, `claude_local.py`, `control_center_brain.py`,
`app._brain_availability_from_env`, `v2_app._brain_notice_loop`,
`tests/unit/test_brain_delegation.py`) and the user folders `docs/reviews/`,
`transcript/`.

---

## Score: 87.5 / 100 (round 1: 80)

| Dimension | Weight | R1 | R2 | Comment |
|---|---|---|---|---|
| Conformance to the handoff docs | 30 | 27 | **28** | Task 12's purpose restored (B1), task 13's acceptance now actually executed (B5), task 11's guarantees repaired (B2/B4). The two documented divergences persist and stay honestly labelled. New deduction: `ARCHITECTURE.md:1036` now states a producer-restart guarantee stronger than the code delivers. |
| Correctness & robustness | 25 | 17 | **20** | Five of six blocking defects cleanly fixed, and I found no regression in the three changes I was asked to stress (input-queue eviction, lossy bus, SHA cache). Against that: the B2 fix introduces a **new** defect — the reopen exception ignores producer identity and is keyed on a wire-settable field, so two producers flap forever and any producer can reopen its own terminal item. |
| Tests | 20 | 16 | **18** | The grep-based UI tests are gone: node executes the very file the server inlines, and the revision guard is compared case-by-case against the server's own `accept_snapshot`. Both tautological tests were replaced by real oracles. 1643 → 1702 tests, 5 green full runs + gate, no flake reproduced. Gaps: no regression test for the two-producer flap or the forged `error_class`, and the new benchmark-figures guard misses 11 of 11 injected doc mutations. |
| Truthfulness of the reports | 10 | 7 | **8** | All four named B3 mismatches are genuinely corrected and every quoted figure I re-derived reconciles with a named JSON key. Docked for a **new** over-claim ("every figure on this page is re-derived by the script" — several are hand-copied), one residual misleading P50 sentence in the 2026-09-11 section, one stale test count, and the over-strong producer-restart sentence. |
| Documentation | 10 | 8 | **8.5** | The 4 undocumented diagnostic kinds are documented, so are the 3 new ones; the stale « Ce qui n'est pas vérifié » section is updated; all 8 model SHA-256 + sizes now match the catalogue exactly. Still open: the wrong route template in two files, the unticked TODO line, and two docstrings that assert more than the code enforces. |
| Safety / privacy | 5 | 4.5 | **5** | Both hygiene gaps closed (temp file with the API key unlinked + coded 503; `owner_profile_path` confined to `runtime_root`). Download size ceiling added on both paths. Vendor boundary and payload-privacy invariants re-verified clean on the new code. |

**Verdict:** the fix round did real work — five of six blockers are genuinely
repaired rather than test-satisfied, and round 1's two weakest spots (UI logic
asserted by grep, benchmark numbers that did not reconcile) are now among the
strongest. Two blocking defects remain, both created by the fix round: a reopen
exception keyed on a field any producer can set and blind to which producer is
speaking, so two Control Centers on one Core now thrash instead of deadlocking
and feed the brain false "interrupted" notices through the very channel B1 was
fixed to protect; and a reproducibility promise on the evidence page that the
guarding script does not actually keep.

---

## Round-1 defect table

| # | Title | Verdict | Evidence |
|---|---|---|---|
| **B1** | Brain attention notes destroyed when the char budget is full | **Fixed** | `jarvis/domain/brain_context.py:328` serves notes *before* the active list; `jarvis/core/brain_context.py:319` calls `take_delivered(context.attention)`, and `take_delivered` (`:127-142`) pops only notes whose pending revision is `<=` the delivered one, so a note replaced meanwhile survives. My probe with 12 maximal active items: 8 notes in → **8 delivered + 4 active listed**, `active_total=12` still reported (never starves to zero). Tests `test_brain_work_context.py::test_attention_notes_survive_a_full_budget_and_only_delivered_ones_are_consumed` and `::test_a_note_that_did_not_fit_is_not_erased` are real oracles. |
| **B2** | A restarted producer permanently kills work it is still running | **Fixed for the stated case, but regressed** | `core/work_state.py:214` claims the producer *after* decoding, with `keep=` the batch's own ids (`:296`); `_reopened_after_producer_restart` (`:83-110`) reopens an `interrupted`/`producer_restarted` item. The original symptom is gone (`test_work_state_store.py:338`). **But** the exception ignores producer identity and trusts a wire-settable `error_class` — see blocking defect **R1** below. |
| **B3** | Published benchmark numbers do not reconcile with the published data | **Fixed for all four named mismatches; a new over-claim replaces them** | All four corrected against the artifacts, re-read twice independently: `2026-09-12-synthetic-settled.json` baseline gives `model_load_ms` 517.6 / `rss_steady_delta_mb` 107.4 / `cpu_pct_one_core` 3.51 / `scoring_hop_ms.p50` 30.142 — exactly what `docs/results/speaker-benchmark/README.md:61-64` now prints, with the JSON key named in each row. The full P50 series (1600, 1600, 1600, 1650, 1700, 2100, 2450 vs 1600, 1600, 1600, 1600, 1700, 1700, 1750) is published per engine (`README.md:70-75`) and matches `2026-09-12-synthetic.json` `gate_sweep[].gate_confirm_ms_p50`. `short_confirmations` is now stated per engine (`README.md:95-96`). FRR 28.0 % (`at_engine_threshold.frr` 0.2802) / 20.8 % settled (0.2075) and gate miss 7.7 % (`gate_at_engine_threshold.owner_gate_miss_rate` 0.0769) are all published. Every other number on the four pages also reconciles, including the 8-row 2026-09-11 table and the scenario scores. **But** the page now promises more than the tooling delivers — see blocking defect **R2** below. |
| **B4** | A rejected batch is dropped without arming a resync | **Fixed** | `jarvis/runtime/work_ingress.py:427` sets `self._lost = True` in the `WorkIngressRejected` handler. The test that used to encode the bug now asserts the consequence: `test_work_ingress.py::test_a_rejected_batch_is_dropped_and_arms_a_full_resend` checks `resyncs == [1]` after the next ack. |
| **B5** | UI work-state logic "tested" by grepping the HTML | **Fixed** | Logic extracted to `jarvis/runtime/control_center_work.js`; the server inlines that exact file at a unique marker (`control_center.py:70-71,425-427`, marker at `control_center.html:382`, no duplicate definitions in the page). `tests/conftest.py:24` runs it under `node -e`; `test_work_view.py:564` compares `acceptWork` against the server's `accept_snapshot` **case by case**, and `:549` proves the served page contains the file byte-for-byte. The page really calls the extracted functions (`control_center.html:486,521,601,640,1879`). |
| **B6** | `jarvis owner-voice` crashes with a raw traceback | **Fixed** | `owner_voice.py:501-507` routes unknown exceptions through `_cli_failure` (`:522-561`), which maps `URLError` → `speaker_model_download_failed`, `EOFError` → `enrollment_aborted`, `ImportError` → `enrollment_audio_unavailable`, and `PortAudioError`/`OSError` → `enrollment_device_unavailable` (per command). `_portaudio_error()` (`:515`) resolves the class from `sys.modules` without importing sounddevice. Conservative: anything unmapped still re-raises. |

### Non-blocking findings from round 1

| # | Verdict | Evidence |
|---|---|---|
| NB1 replay droppable by the input queue | **Fixed** | `realtime_audio.py:416-442`: a queued replay is never evicted; the arriving live block is dropped instead. Two stuck replays are counted (`dropped_replays`) and traced `owner_replay_dropped` (`:2433-2446`, `OWNER_REPLAY_DROPPED_SIGNAL` at `:39`). I walked all four branches: the `_queued_replay` deque stays length-synchronised with the queue, and `_deliver_capture` runs on the loop via `call_soon_threadsafe` (`:292`), so there is no cross-thread hazard. |
| NB2 silent degradation if the capture refuses the owner gate | **Fixed** | `realtime_audio.py:2340-2354` calls `_lose_owner("solo_owner_capture_unsupported")` when the gate is refused while the authority is `OWNER`. |
| NB3 `resync()` throws away pending merge closures | **Fixed** | `work_ingress.py:198-202` snapshots the retired keys, restores their `_sent` entries after the clear, and passes them to `sync(retired=...)`. |
| NB4 attention subscriber evictable for the process lifetime | **Fixed** | `v2_app.py:108` subscribes with `lossy=True`; `CoreEventBus._drop_oldest` (`v2_services.py:127-150`) drops the oldest event, counts it, and reports `core.event_bus.event_dropped` once per message type. Checked for a new defect: `previous_status` travels in the event payload, not in policy memory, so dropping an intermediate event cannot corrupt a later note. |
| NB5 terminal work resurrects after 512 evictions | **Fixed** | `MAX_EVICTED_KEYS = 4096` with the sizing argument written out (`core/work_state.py:65-74`). |
| NB6 persistent 400 floods the journal | **Fixed** | `_report_rejected` (`work_ingress.py:470-481`) dedups per series; `test_a_core_that_refuses_every_batch_is_journaled_once`. |
| NB7 `GET /api/work` construction side effect | **Fixed** | `control_center.py:1594` reads `self._agents.get(self._agent_id)` instead of `self.agent`, with the reason in a comment. |
| NB8 release-gate exemption wider than advertised | **Addressed, divergence documented** | `scripts/verify_release.py` now scans `scripts/` too, parses imports with AST (relative imports resolved by `_package_of`), and additionally fails on any textual mention of the tooling modules — so `importlib.import_module("jarvis.runtime.speaker_benchmark")` is caught. Round 1's preferred fix (move the tooling out of the package) was not taken; string-concatenated dynamic imports would still evade. Fails closed on false positives. |
| NB9 `owner_profile_path` unconstrained | **Fixed** | `v2_config.py:345-363` `_under_runtime_root` resolves and refuses anything outside `runtime_root` with `owner_profile_path_outside_runtime`. |
| NB10 four undocumented diagnostic kinds | **Fixed** | All four now in `docs/ARCHITECTURE.md`, and so are the three kinds the fixes introduced (`core.event_bus.event_dropped`, `core.event_bus.subscriber_evicted`, `owner_replay_dropped`). |
| NB11 wrong route template in docs | **Not fixed** | `docs/ARCHITECTURE.md:1164` and `docs/OPERATIONS.md:591` still write `/api/agent/tasks/{external_id}/trace`; `control_center.py:261` registers `{task_id}`. No justification recorded. |
| NB12 stale « Ce qui n'est pas vérifié » | **Fixed** | `docs/OPERATIONS.md:826-851` now lists four points, the fourth pointing at `docs/HARDWARE_ACCEPTANCE.md`. |
| NB13 SHA-256 documented for 1 of 8 models | **Fixed** | `docs/SPEAKER_BENCHMARK.md:285-294` lists all 8 models with SHA-256 and byte size; parsed programmatically against `MODELS` in `jarvis/adapters/sherpa_model_catalog.py`: **8/8 exact on both hash and size**, embedding dims too, no doc-only or catalogue-only entry. `verify` compares both (`:203`). |
| NB14 two tautological tests | **Fixed** | `test_work_ingress.py::test_a_rejected_batch_is_dropped_and_arms_a_full_resend` now asserts the resend; `test_brain_work_context.py::test_twelve_modest_active_entries_all_fit_in_the_budget` proves the 12-item bound is reachable, so the budget test is no longer trivially satisfied. |
| NB15 production default on synthetic evidence | **Noted, now surfaced** | The owner-side cost is published next to the gate figure and guarded (`test_published_benchmark_figures.py::test_the_owner_side_cost_of_the_new_default_is_published`, which also pins the literal "provisional pending real owner data"). |
| NB16 `solo_owner` gated on `continuous_brain` | Unchanged, on the record | Documented divergence, sound reason. |
| NB17 bookkeeping | **Partly fixed** | The report's count table is re-collected and correct for 7 of 8 files (see the truthfulness finding below); `tasks/TODO.md:30` still shows `- [ ] 00 — Orchestrate the implementation`. |
| NB18 world-readable temp file with the OpenAI key | **Fixed** | `control_center.py:554-570`: the temp file is unlinked on failure and the route returns a coded 503 (`settings_write_failed`). |
| NB19 benchmark subprocess without timeout | **Fixed** | `speaker_benchmark.py:1115-1121` passes `timeout=` and maps `TimeoutExpired` onto the existing failed-engine result. |
| NB20 probe checks size, not content | **Fixed** | `owner_voice.py:118` compares `engine.cached_file_sha256(model)` to `MODEL_SHA256`; the cache is keyed on `(path, size, st_mtime_ns)` with a bounded table and an honest docstring (`sherpa_speaker_embedder.py:104-121`). `verify_model` still re-reads the file every time, so the security gate is unaffected. |
| NB21 `trace_summary` echoes free text | **Fixed** | `label()` (`trace_summary.py:66-75`) restricts to `[a-z0-9_./-]`, 64 chars; applied to `reason`, `code`, `phase` and `store_id` (`:154-170`). |
| NB22 `UnicodeEncodeError` on cp1252 | **Fixed** | `trace_summary.py:268-271` reconfigures stdout to UTF-8 with `errors="replace"`. |
| NB23 two Control Center inconsistencies | **Fixed** | `_voice_arch_is_continuous` now consults `_voice_arch_problem` (`control_center.py:646-663`); `authDraftAfterChange` (`control_center_work.js:79-87`) only forces the default when the stored value would be refused, so a stored `shadow` survives a mode round trip. |
| NB24 model download without a size ceiling | **Fixed** | Both paths abort past the pinned size (`sherpa_speaker_embedder.py:153-159`, `sherpa_model_catalog.py:225-230`). |
| NB25 misnamed handover test | **Fixed** | `test_speaker_benchmark.py:678-680` now asserts `all(h.score <= h.window_score)` **and** `any(h.score < h.window_score)` so the inequality is not vacuous. |
| NB26 known behavioural limits | Unchanged, still documented | — |

---

## Blocking defects remaining

### R1 — The producer-restart reopen ignores producer identity and trusts a wire-settable field
**Severity: high (new defect, introduced by the B2 fix; wrong data delivered to the brain continuously)**
`jarvis/core/work_state.py:83-110` (`_reopened_after_producer_restart`), used at `:231`;
claim at `jarvis/core/work_state.py:88` and `docs/ARCHITECTURE.md:1036`

The reopen condition is exactly "the held item is `interrupted` with
`error_class == "producer_restarted"`, and the observation is non-terminal". It
does **not** check which producer is speaking, and `error_class` is an ordinary
public field a producer may set on the wire (`OBSERVATION_WIRE_KEYS` contains
`error_class`; `_payload_optional_id` accepts the token; `ERROR_WORK_STATUSES`
permits it for `interrupted`). Three consequences, all reproduced:

1. **Two Control Centers on one Core now thrash instead of deadlocking.** Each
   batch interrupts every active item the *other* instance owns (`_claim_producer`
   → `interrupt_source(keep=own batch)`), and the other instance's next batch
   reopens them. Probe: two producers, two items each, 14 alternating batches →
   revision 54, `outcomes {'created': 4, 'updated': 50}`, and at every instant
   half the items read `interrupted / producer_restarted` while they are running.
2. **The brain is fed false failures through the D17 channel.** `INTERRUPTED` is
   in `ATTENTION_WORK_STATUSES`, so each flap raises a `WorkAttention`. The same
   probe produced **26 attention notes in 14 batches**, 4 still pending at the
   end. Before the fix this flood was bounded (items went terminal once and
   stayed there); it is now unbounded. This is precisely the channel B1 was
   repaired to protect, and every note in it is wrong.
3. **Any producer can reopen its own terminal item, and with stale data.** A
   producer that sends `status=interrupted, error_class=producer_restarted` can
   reopen the item on its next batch (probe: outcome `updated`, status back to
   `running`) — "terminal is final" is no longer enforced against producers, only
   against Core-internal statuses. Because the reopened base is rebuilt with
   `updated_at=min(current.updated_at, observation.observed_at)` (`:109`), an
   observation **older** than the interruption also reopens it (probe: interrupt
   at t=11, reopen with an observation at t=5, activity `old` accepted).

Why it matters: `core/work_state.py:88` states the marker is "un statut que Core
seul pose" and `docs/ARCHITECTURE.md:1036` states the reopen happens on "a later
batch **from the same producer** … so two Control Centers sharing one Core cannot
kill each other's running work". Neither holds. The narrow, documented exception
to terminal-is-final is in practice a general one, and the configuration the fix
was written for is the one it destabilises.

Evidence: scratch probe (four scenarios) at
`…\scratchpad\b2_probe.py`; output reproduced in the appendix (E8).

Fix: make the marker Core-private and producer-scoped. Concretely — record the
owning `producer_id` on the held `WorkItem` as an internal (non-wire) field set
by `apply` from the batch being ingested; have `_claim_producer` interrupt only
items whose recorded producer is the displaced one; and let
`_reopened_after_producer_restart` reopen only when the observing producer is the
current claimant **and** the interruption was posted by Core itself (a Core-side
`set[key]` of keys it interrupted, cleared on reopen), never on the value of
`observation.error_class`. Drop the `min(...)` on `updated_at` in favour of the
observation's own time so a stale observation stays `STALE`. Add regression
tests: (a) two producers alternating full resyncs → every item stays `running`,
zero attention notes after the first claim; (b) a producer that itself reports
`interrupted/producer_restarted` cannot reopen; (c) an observation older than the
interruption is refused.

### R2 — The evidence page promises a reproducibility contract the guard does not keep
**Severity: medium (truthfulness; this is the file the report calls the reproducible evidence)**
`docs/results/speaker-benchmark/README.md:77-80`, `docs/fixes/solo-owner-duplex/final-implementation-report.md:307-311`;
also `docs/results/speaker-benchmark/README.md:157`

The fix round closed B3 by re-deriving the disputed numbers and adding
`scripts/speaker_benchmark_figures.py` + `tests/unit/test_published_benchmark_figures.py`.
The guard is genuine and non-circular (it parses the raw JSON and asserts the
formatted string appears in the hand-written Markdown — nothing regenerates the
prose). The problem is the sentence the pages now carry:

> "Every figure on this page is re-derived from the named JSON by
> `scripts/speaker_benchmark_figures.py`"

This is false. `figures()` exposes no key for `model_verify_ms` (33.1,
`OPERATIONS.md:1284`), `hop_ms.p50` (0.25, `OPERATIONS.md:1282`), the zero-FA
columns' miss % and P95 (`README.md:127-134`), `noise_hops_accepted`, the 2.4×
CPU ratio, or any scenario-level score (0.65 / 0.56 / 0.75 / 0.62,
`README.md:147-167`). Those numbers are all *correct* — I checked them — but they
are hand-copied, which is exactly the condition B3 existed to end.

The guard is also shallow enough that the promise could not be kept even for what
it does cover. A mutation harness (doc copies edited, JSON untouched) caught 4 of
4 positive controls but **missed 11 of 11** real falsifications, including:
swapping the two engines' entire columns in the README cost table (presence-
anywhere ignores position); falsifying the whole `wespeaker` row of the
2026-09-11 table; falsifying the report's entire baseline gate row; and rewriting
the short-reply prose to "only one … none". That last one matters most:
`::test_the_short_reply_and_clamping_claims_name_both_engines` only asserts that
the literal strings `short_confirmations` and `ERes2Net-VoxCeleb` occur and that
the two artifact series differ — it never compares the published counts, so the
guard for round-1 mismatch #4 does not in fact guard it. Separately,
`_number((row.get(key) or 0) * 100, 1)` in `scripts/speaker_benchmark_figures.py`
turns a missing metric into `0.0` instead of failing.

Finally, one residue of the original mismatch #2 survives in the older section:
`README.md:157` says "Confirmation latency P50 = 1.6 s for every engine … P95
grows with the threshold". True only at the table's @0.5 column; the contrast
with P95 implies P50 is threshold-independent, which the same artifact
contradicts (`2026-09-11-synthetic-settled.json` `sweep[].confirm_ms_p50`: 1700
at 0.75/0.80 and 2200 at 0.90 for the baseline, 1950 at 0.80 for campplus-zh-cn,
2000 at 0.85 for eres2netv2).

Why it matters: B3's finding was not "four numbers are wrong", it was that the
results README *is* the evidence artifact and an unreproducible number there
breaks the contract the benchmark design rests on. Restating that contract in
stronger terms than the tooling can honour re-creates the same defect one level
up — and the hardware protocol will be compared against these pages.

Fix: either (a) extend `figures()` to expose the six missing figure classes and
assert them, or (b) replace the blanket sentence with an explicit statement of
which figures are machine-checked and which are transcribed. Independently:
compare the published `short_confirmations` counts rather than the word; anchor
the cost-table assertions per row/engine instead of per page; make `_number`
raise on a missing key; and restate `README.md:157` as "P50 is 1.6 s at 0.5 and
rises with the threshold (…series…), P95 rises faster".

---

## Non-blocking findings

1. **Stale test count in the final report.**
   `docs/fixes/solo-owner-duplex/final-implementation-report.md:183` says
   `tests/unit/test_trace_summary.py` (6); the file now collects **8** (the NB21
   and NB22 fixes added two). The other seven counts in the table all reproduce
   exactly (51 / 22 / 43 / 51 / 72 / 92 / 3). The TODO claims per-file counts were
   re-collected; this one was not.
2. **Two docstrings assert more than the code enforces** — the same class of
   defect round 1 raised as finding 21. `jarvis/core/work_state.py:88` ("un statut
   que Core seul pose", false — see R1). `jarvis/runtime/control_center.py:750`
   still calls the verifier probe "une sonde bon marché"; after the NB20 fix the
   first call hashes ~27 MiB synchronously on the aiohttp event loop (the cache
   makes later calls free, and it re-hashes whenever size or mtime changes). The
   statement "le modèle n'est jamais chargé ici" is still true; "bon marché" is
   no longer.
3. **The B3 guard's coverage** — detail folded into blocking defect R2 above;
   `::test_the_2026_09_11_table_matches_its_own_settled_json` covers 4 of 8
   engines and 3 of 8 columns.
4. **A live block dropped to protect a replay is not counted.**
   `realtime_audio.py:426-427` returns without incrementing any counter when the
   newest live block is discarded. `dropped_replays` covers the rarer case; the
   common one is invisible except as a `captured_bytes` / `sent_bytes` gap.
5. **NB11 left unaddressed without justification** — see the table above.
6. **`tasks/TODO.md:30`** still shows task 00 unticked although the orchestration
   record, the progress log, the final report and now two critic rounds exist.
7. **Benchmark tooling still ships inside the `jarvis` package.** The release-gate
   repair is sound and now covers `scripts/` and dynamic imports, but the
   invariant is enforced by an allow-list plus a text scan rather than by the
   tooling living outside the package. A dynamically built module name would
   evade both.
8. **Known limits carried forward unchanged** (owner state published on change
   only; handover leak ≈ 1.2 s; a lone "oui" under ≈ 600 ms voiced speech is
   dropped; `owner_onset_ms` after a non-owner verdict is an estimate; nothing
   acoustic measured on real hardware). All four remain correctly labelled
   PENDING USER in `docs/HARDWARE_ACCEPTANCE.md` and in the "not verified"
   section of `docs/OPERATIONS.md`.

---

## The known watch item: `test_state.py::test_initialize_recovers_stale_visualizer_runtime_files`

**Not a race in the code under test.** Findings:

- The test touches nothing outside `tmp_path`. `FileStatePublisher`
  (`jarvis/adapters/file_state_bus.py:26-75`) writes only under
  `self.root = runtime_dir.resolve()`; no `runtime/` path, no module-level state,
  no clock. Two concurrent runs therefore share no application state.
- `jarvis/adapters/file_state_bus.py` is **untouched by this handoff**
  (`git status --short` on it is empty), so whatever the cause, it is pre-existing
  and outside the handoff's blast radius.
- Reproduction attempts, all green: the file standalone **8 ×** (26 passed each,
  0.14–0.78 s) and **two full suites running concurrently** (1702 passed / 4
  skipped in both, 72.96 s and 72.97 s). I could not reproduce the failure.
- Two plausible environmental mechanisms, both consistent with "seen once under a
  concurrent run": (a) pytest's numbered `pytest-<N>` temp-root garbage collection
  — a second pytest process prunes older numbered directories and can delete a
  directory the first process is still using, which would make the three
  `read_text`/`exists` assertions fail; (b) `_atomic_text` (`:62-75`) is the one
  remaining `os.replace` site in the tree that does **not** use the repo's own
  `replace_with_retry` helper (`jarvis/adapters/file_replace.py`), which exists
  precisely because Windows transiently refuses the replace under antivirus or
  indexer contention — contention two concurrent suites make likelier.

Recommendation (outside this handoff): give concurrent suite runs distinct
`--basetemp` directories, and, if the failure recurs, route
`file_state_bus._atomic_text` through `replace_with_retry` like the five other
call sites already do.

---

## Verified-good list (re-checked this round; round-1 entries not repeated unless retested)

- **B1 budget behaviour under stress.** 12 maximal active items (label 118 ch,
  activity 118 ch, summary 238 ch) + 0 / 3 / 8 notes → 0 / 3 / 8 notes delivered
  and 7 / 6 / 4 active listed, payload 5 791 / 5 937 / 5 913 chars, always under
  the 6 000 budget, `active_total` always truthful. The reordering does not
  starve the active list to zero, and `take_delivered`'s revision guard keeps a
  note that was superseded between build and consume.
- **B5 end to end.** The marker appears exactly once in the page, the page
  defines none of the nine exported functions itself, the server's `index()`
  substitutes the file verbatim, and a test asserts the served text contains it.
  `page_logic` runs real `node` and skips only when node is absent.
- **Event-bus lossy path.** Drop-oldest is bounded, counted (`dropped_total`),
  reported once per message type in a 32-entry table, and cannot corrupt a later
  attention note because `previous_status` travels in the payload.
- **Input-queue eviction.** All four branches of `_put_input` keep the
  `_queued_replay` deque length-synchronised with the queue, including the
  `stop_input` sentinel; the producer runs on the loop, not the PortAudio thread.
- **SHA cache.** Bounded, keyed on `(path, size, st_mtime_ns)`, limitation stated
  in the docstring, and `verify_model` (the actual gate) still re-reads the file.
- **Release gate.** Passes; the AST check resolves relative imports; `scripts/` is
  scanned; the text scan catches dynamic module naming; the dangerous-primitive
  rule is still total outside the two allow-listed files.
- **Invariants re-checked on the new code.** No `numpy`/`sherpa`/`sounddevice`
  import anywhere in `jarvis/domain`, `jarvis/ports`, `jarvis/core`. The Core
  wire contract still admits only 18 public keys — `prompt`, `raw`, `entries` and
  trace blobs cannot cross (`OBSERVATION_WIRE_KEYS` enumerated at runtime). No
  tool surface declared in `realtime_audio.py`. `control_center_work.js`,
  `core/work_state.py`, `core/brain_context.py` and `work_ingress.py` contain no
  transcript/text/embedding field.
- **All 69 `file.py::test_name` references in the final report resolve** to a test
  of that name **in that file** (script-checked, 0 problems — round 1 checked 70
  references against the older report).
- **Model licences and hashes.** All 8 catalogued models carry SHA-256 + size in
  both the docs and the code, matching exactly; `verify` compares both before a
  model is used.
- **B3 artifacts re-derived independently.** `2026-09-12-synthetic-settled.json`
  baseline: `model_load_ms` 517.6, `rss_steady_delta_mb` 107.4,
  `cpu_pct_one_core` 3.51, `scoring_hop_ms.p50` 30.142; candidate 339.8 / 133.5 /
  8.30 / 76.859. `2026-09-12-synthetic.json` `gate_confirm_ms_p50` baseline
  [1600, 1600, 1600, 1650, 1700, 2100, 2450], candidate
  [1600, 1600, 1600, 1600, 1700, 1700, 1750]; `short_confirmations` baseline
  [3, 3, 3, 3, 3, 2, 2], candidate [3, 3, 3, 2, 2, 1, 0]. Every one of these
  appears, correctly attributed, in `README.md`.

---

## Evidence appendix

Commands run from `C:\Projects\jarvis\jarvis` with `.venv\Scripts\python.exe`.

| # | Command | Result |
|---|---|---|
| E1 | `-m pytest tests -q -p no:cacheprovider` (run 1) | **1702 passed, 4 skipped**, 70.22 s |
| E2 | same (run 2) | **1702 passed, 4 skipped**, 72.17 s |
| E3 | same (run 3) | **1702 passed, 4 skipped**, 66.88 s |
| E4 | `scripts\verify_release.py` | suite 1702 passed / 4 skipped (68.30 s) then **"Release verification passed."** (exit 0) |
| E5 | two full suites launched **concurrently** | both **1702 passed, 4 skipped** (72.96 s / 72.97 s) — the reported flake did not reproduce |
| E6 | 8 × `-m pytest tests/unit/test_state.py -q -p no:cacheprovider` | 26 passed every time, 0.14–0.78 s. No flake. |
| E7 | `--collect-only -q` per file | conversation_authorization 51, owner_barge_in 22, owner_replay 43, owner_input_gate 51, control_center_quality 72, work_state_contracts 92, solo_owner_acceptance 3, **trace_summary 8** (report says 6), owner_voice 92, speaker_verifier 56, voice_duplex 107, work_view 37, brain_work_context 34, work_state_store 44, work_ingress 37, published_benchmark_figures 11 |
| E8 | scratch `b2_probe.py` — 4 scenarios against the real `WorkStateStore` | S1 two producers × 7 alternating rounds → revision 54, `{'created': 4, 'updated': 50}`, **26 attention notes**, half the items `interrupted/producer_restarted` at rest. S2 producer forges `error_class=producer_restarted` then reopens → outcome `updated`, status `running`. S3 the forged token decodes cleanly from the wire. S4 an observation 6 s **older** than the interruption reopens the item and writes its activity. |
| E9 | scratch `b1_probe.py` — 12 maximal active items × {0, 3, 8} notes | 0→0 notes/7 active/5 791 ch; 3→3/6/5 937 ch; 8→8/4/5 913 ch; `active_total` 12 in all three |
| E10 | scratch `refs.py` — every `` `file.py::test_x` `` in the final report, file-scoped | **69 references, 0 problems** |
| E11 | scratch `b3.py` — raw read of all four `docs/results/speaker-benchmark/*.json` | figures listed in the verified-good section; they match the README rows and the report cells |
| E12 | `-m pytest tests/unit/test_published_benchmark_figures.py -q -p no:cacheprovider` | **11 passed**, 0.09 s. Read in full — derives from JSON, asserts against doc text, non-circular |
| E17 | mutation harness: doc copies edited, JSON untouched, page paths monkeypatched | 4/4 positive controls **caught**; **11/11 real falsifications missed** (engine-column swap, whole `wespeaker` row, whole baseline gate row, short-reply prose inversion, `noise_forwarded_ms`, `owner_start_lost_ms_p95`, `model_verify_ms`, `hop_ms.p50`, 865.5 ms contention figure, README EER column, gate-table leaked-ms/P95 cells) — see R2 |
| E18 | `docs/SPEAKER_BENCHMARK.md:285-294` parsed against `MODELS` in `sherpa_model_catalog.py` | **8/8 exact** on SHA-256, byte size and embedding dim; no doc-only or catalogue-only entry |
| E19 | `figures()` key coverage vs every number quoted in the four pages | 6 figure classes published with no corresponding key (`model_verify_ms`, `hop_ms.p50`, zero-FA miss %/P95, `noise_hops_accepted`, the 2.4× ratio, all scenario scores) — see R2 |
| E13 | runtime enumeration of `OBSERVATION_WIRE_KEYS` | 18 keys, none of them `prompt` / `raw` / `entries` / trace |
| E14 | `grep` for `numpy` / `sherpa` / `sounddevice` imports in `jarvis/{domain,ports,core}` | none |
| E15 | `grep -c` marker / duplicate function definitions in `control_center.html` | marker once, 0 duplicate definitions of the 9 exported functions |
| E16 | `git status --short jarvis/adapters/file_state_bus.py` | empty — the flaky test's subject is untouched by this handoff |

Scratch files were written only under the session scratchpad
(`…\409409a7-…\scratchpad\`); no implementation file, test, doc, script,
`tasks/TODO.md` entry, round-1 report or Git object was modified, and no commit,
stash or revert was performed. The only file created in the repository is this
review.
