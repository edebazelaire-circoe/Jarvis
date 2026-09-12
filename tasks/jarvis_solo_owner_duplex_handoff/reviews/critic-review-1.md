# Critic review 1 — JARVIS Solo Owner Duplex + Core Work State handoff

Reviewer: independent adversarial auditor (read-only on the implementation).
Date: 2026-09-12. Tree audited: uncommitted working tree on `main` @ `e292784`.
Out of scope and excluded from scoring: the parallel "brain availability /
delegation" effort (`brain_service` stale-reply supersession / turn budget /
`announce_notice`, `claude_local.py`, `control_center_brain.py`,
`app._brain_availability_from_env`, `v2_app._brain_notice_loop`,
`tests/unit/test_brain_delegation.py`) and the user folders `docs/reviews/`,
`transcript/`.

---

## Score: 80 / 100

| Dimension | Weight | Score | Comment |
|---|---|---|---|
| Conformance to the handoff docs | 30 | **27** | D01–D17 and spec §1–§4 honoured; every task's acceptance criteria met except task 14's hardware ones, which are correctly and loudly labelled PENDING USER. Two documented divergences (production default changed on synthetic evidence; `solo_owner` requires `continuous_brain`). |
| Correctness & robustness | 25 | **17** | The audio path is genuinely well engineered and survived my own fuzzing. Against that: one silent brain-context data-loss bug, an irreversible work-state trap, and several unguarded error paths — including the two commands the user must run next. |
| Tests | 20 | **16** | Large, honest, mostly non-tautological (real oracles for EER/percentiles, real engine smoke tests), no flakes in 3 full runs + 6 repeats of the timing-sensitive set. Weak spot: every "UI logic" test is a source-string grep; no JavaScript is ever executed. Coverage gaps map exactly onto the defects below. |
| Truthfulness of the reports | 10 | **7** | All 70 `file::test` references, all per-file test counts and the `1643 passed / 4 skipped` headline reproduce exactly. But several benchmark numbers in the final report and in the *published* results README do not match any published result file, and one is engine-transposed. |
| Documentation | 10 | **8** | Unusually accurate and complete (≈120 constants/event names/endpoints verified, all correct). Minor: 4 undocumented diagnostic kinds, one wrong route template, one stale "not verified" section, incomplete SHA table, and one docstring that asserts a guarantee the code does not enforce. |
| Safety / privacy | 5 | **4.5** | No biometric or model artifact reachable by Git; the voiceprint never leaves `owner_voice_profile.py`; diagnostics are scalars only; licences recorded with pinned SHA-256. Two hygiene gaps: a world-readable settings temp file containing the OpenAI API key can be left behind, and `owner_profile_path` is unconstrained when hand-edited. |

**Verdict:** a strong, honest, well-tested implementation of the voice track and
a solid work-state track, held back from ≥ 90 by one silent brain-context
data-loss bug, an irreversible work-state trap, raw tracebacks on the two
commands the user has to run next, UI logic asserted by grep rather than
executed, and benchmark numbers in the published evidence that do not reconcile
with the published data.

---

## Blocking defects (must fix to reach ≥ 90)

### B1 — Brain attention notes are destroyed when the context char budget is full
**Severity: high (silent data loss, defeats task 12's stated purpose)**
`jarvis/core/brain_context.py:296` together with `jarvis/domain/brain_context.py:310-325`

`build_brain_work_context` spends the 6000-char budget on **active items first**
(`listed_active = take(...)` at `domain/brain_context.py:324`), then on attention
notes (`:325`). `BrainContextBuilder.work_context` then calls
`self._attention.take_pending()` **unconditionally** (`core/brain_context.py:296`),
and `take_pending` clears the whole dict (`core/brain_context.py:115-120`).

Why it matters: attention notes are the *only* channel by which the brain learns
that a task failed, was interrupted, or is blocked waiting for the user (D17,
task 12 acceptance "Unexpected normalized failure can be noticed by the
cognitive/event policy"). Exactly when the workstation is busy — several active
sub-agents with long labels/summaries — the budget is exhausted by the active
list, every note is dropped from the context **and** erased from the policy. The
user asks "où en sont mes tâches ?" and the brain never hears that three of them
failed.

Evidence: with a worst-case snapshot only ~6 active entries fit in 6000 chars
(compact JSON 5972–5989), leaving `attention: ()` while
`WorkAttentionPolicy.pending` held 3 notes; after the turn `pending` is 0.
No test exercises this: `tests/unit/test_brain_work_context.py:238` (the bounds
test) never passes `attention=`.

Fix: reserve the attention budget *before* the active list (notes are at most
8 × ~200 chars ≈ 1.6 kB), **and** make consumption match delivery — replace
`self._attention.take_pending()` with a `take_delivered(context.attention)` that
pops only the notes actually included and leaves the rest pending for the next
turn. Add a test with 12 large active items + 3 failures asserting the notes
survive.

### B2 — A restarted producer permanently kills work it is still running
**Severity: high (irreversible state, no self-heal)**
`jarvis/core/work_state.py:219-238` (`_claim_producer`) → `:202-217`
(`interrupt_source`) → `jarvis/domain/work_state.py:725-727` (terminal is final)

When `producer_id` changes for a source, every active item of that source is set
to `INTERRUPTED`, which is terminal and irreversible: any later observation with
a different status returns `TERMINAL` and is refused. The new producer's first
resync of a **still-running** `external_id` is therefore rejected forever.

Why it matters: two Control Center processes pointed at one Core (different UI
ports, one Core — a supported configuration: `producer_id = uuid4()` per process,
`work_ingress.py:293`) make the `producer_id` flap on every batch. Each batch
terminates the other's work; from then on no Claude sub-task is ever shown
running again until Core restarts, and the brain's work context is permanently
wrong. Core emits `core.work.producer_restarted` but has no recovery path and no
way to distinguish this from a real interruption.

Evidence: after a producer swap, a `RUNNING` resync of the same `external_id`
returns outcome `terminal`, revision unchanged, item stuck `interrupted`.

Fix: perform the claim **after** decoding the batch, and interrupt only the items
whose key is *absent* from the arriving batch; or allow an observation from the
new producer to reopen an item whose `error_class == PRODUCER_RESTARTED` (a
narrow, documented exception to terminal-is-final). Add a regression test:
producer A running → producer B resyncs the same running id → item stays running.

### B3 — Benchmark numbers in the published evidence do not reconcile with the published data
**Severity: high for truthfulness (the results README *is* the evidence artifact)**
`docs/results/speaker-benchmark/README.md:42-44`,
`docs/fixes/solo-owner-duplex/final-implementation-report.md:253,256-259`,
`docs/OPERATIONS.md:1246`

Four independent mismatches, all verified against the JSON:

1. **Model-load / RSS figures are unsourced and engine-transposed.** README:43
   says "baseline … load **1.06 s**, RSS +109 MB; ERes2Net-VoxCeleb … **0.87 s**,
   +133 MB" and attributes them to the *settled* run. Actual
   `resources.model_load_ms`: 2026-09-12 settled **517.6 / 339.8**, strict
   **588.2 / 359.0**; 2026-09-11 settled **865.5 / 398.0**, strict 569.9 / 337.7.
   No file, alone or with `model_verify_ms`, yields 1.06 s. "0.87 s" matches
   0.8655 s — which is the **baseline** in the 2026-09-11 settled run, not
   ERes2Net. `rss_steady_delta_mb` is 107.4/107.9, not 109.
2. **"Confirmation P50 is 1.6 s for both engines at every threshold"**
   (report:256-257) is false and self-contradicted 10 lines later
   ("P50 unchanged (1.65 s)", report:266). `gate_sweep[].gate_confirm_ms_p50` for
   the baseline: 1600, 1600, 1600, **1650, 1700, 2100, 2450** ms at 0.45→0.75.
3. **"31 ms/scoring hop, 3.6 % core (settled)"** (report:253, README:42) mixes
   runs: settled is `scoring_hop_ms.p50` 30.1 / `cpu_pct_one_core` 3.51; 3.56 is
   the strict run; 31 is neither p50 nor mean.
4. **"Three short replies … at every threshold up to 0.65"** (report:258,
   README:59) holds only for the baseline; ERes2Net `short_confirmations` is
   3,3,3,**2**,2,1,0 — already 2 at the new 0.6 default.

Why it matters: these are the numbers the hardware protocol will be compared
against, and item 1 sits in the file the report calls the reproducible evidence.
An unreproducible number there breaks the "numbers live in `docs/results/`"
contract that the whole benchmark design rests on.

Fix: regenerate every quoted figure from the named JSON
(`resources.model_load_ms`, `scoring_hop_ms.p50`, `cpu_pct_one_core`,
`gate_sweep[].gate_confirm_ms_p50`, `short_confirmations`), name the run each
figure comes from, and replace the "1.6 s at every threshold" sentence with
"1.6 s up to 0.55, 1.65 s at the 0.6 default, degrading to 2.45 s by 0.75 for
the baseline".

### B4 — A rejected batch is dropped without arming a resync
**Severity: medium (silent, permanent divergence between reality and Core)**
`jarvis/runtime/work_ingress.py:410-412` (vs the correct handling at `:343-346`)

The overflow path sets `self._lost = True` so the next ack triggers a full
resend (`:430-435`). The `WorkIngressRejected` (HTTP 400) path discards up to 64
observations and never sets `_lost`. Core then shows a finished task as running
— forever, unless the 30 s idle probe happens to fire while `_pending` is empty,
which a busy stream prevents.

Evidence: `_lost` is assigned only at `:314`, `:346`, `:434`. The existing test
`tests/unit/test_work_ingress.py:512-520` asserts the drop and nothing else — it
encodes the bug rather than catching it.

Fix: `self._lost = True` next to `self.rejected_total += len(batch)` at `:411`,
and change the test to assert a full resend follows the next ack.

### B5 — UI work-state logic is "tested" by grepping the HTML source
**Severity: medium (task 13's core guarantees are unverified)**
`tests/unit/test_work_view.py:505-528`

`test_the_panel_guards_revisions_like_the_server`,
`test_elapsed_time_comes_from_authoritative_dates_only` and
`test_the_panel_never_writes_work_state` assert that literal substrings such as
`"return next.revision>=held.revision;"` appear in
`jarvis/runtime/control_center.html`. No JavaScript is executed anywhere in the
suite (no node, no jsdom); the implementers' own log admits the pure functions
were only checked "in a scratch node run". So task 13's acceptance criteria
("stale revisions ignored", "elapsed derived from authoritative timestamps",
"UI never writes work state") rest on string matching that survives any logic
error preserving the substring, and breaks on any reformat.

Fix: extract `acceptWork`/`taskElapsed` into a small `.mjs` the page imports, and
drive them from Python via `node --input-type=module` (node is already assumed by
the existing `node --check` step), or add a minimal jsdom/`js2py`-free harness
that evaluates the two pure functions with a table of revision/store_id cases.

### B6 — `jarvis owner-voice` crashes with a raw traceback on its two most likely failures
**Severity: medium (it is the very next command the user must run)**
`jarvis/runtime/owner_voice.py:482` (the dispatch `except`), `:326-334`
(`record_microphone`), `:469` (`input()`)

The CLI catches only `(EnrollmentError, OwnerProfileError, SpeakerModelError)`.
Escaping uncaught:

- **no network** during `download-model` → `urllib.error.URLError`
  (`download-model RAW EXCEPTION: <urlopen error getaddrinfo failed>`);
- **microphone busy** during `enroll --mic` → `sounddevice.PortAudioError -9985` —
  which is *exactly* the documented hazard: `owner_voice.py:180-186` and the
  Control Center hint both say "stop Voice first, the microphone must be free",
  so the user who forgets gets a stack trace instead of a coded message;
- no TTY → `EOFError` from the confirmation prompt;
- a missing `sounddevice`/`numpy` import.

Why it matters: `tasks/TODO.md` lists enrollment as the one **USER ACTION** that
unblocks everything else, and `docs/HARDWARE_ACCEPTANCE.md` §1 makes it step one.
Every other path in this module is meticulous about stable codes, so this reads
as an omission, not a choice. It also contradicts task 03's testing requirement
("profile create/load/reset/**error paths**").

Fix: wrap the command dispatch with `except (URLError, OSError, EOFError)` plus a
lazily imported `sounddevice.PortAudioError`, mapping to
`speaker_model_download_failed`, `enrollment_device_unavailable`,
`enrollment_aborted`; add tests asserting the coded exit for a simulated network
failure and a raising input stream.

---

## Non-blocking findings

1. **The owner replay can be silently discarded by the input queue and is never
   re-sent.** `jarvis/runtime/realtime_audio.py:398-404`: `_put_input` drops the
   **oldest** item when the 64-slot queue is full. The replay is a single item of
   up to `owner_buffer_ms` (2.5 s) pushed by `_deliver_capture`
   (`realtime_audio.py:310-315`), while `CaptureProcessor._replay_owner_prefix`
   has already advanced `_sent_until` (`duplex.py:733`) so the prefix will never
   be offered again — and `voice.owner.replay` will report a successful replay
   that never reached the provider. Low probability (needs the provider send path
   to stall > 3.2 s) but the consequence is losing a whole sentence start, which
   is precisely what task 06 exists to prevent. Fix: on overflow drop the
   *newest* live block instead of the oldest, or mark replay blobs undroppable.
2. **Silent degradation if the capture refuses the owner gate mid-flight.**
   `realtime_audio.py:2281-2294` (`_set_owner_gate`) swallows any exception and
   sets `_owner_gated = False` with no trace; `_input_gated()` then returns False
   and Solo Owner quietly becomes "owner cuts, everyone is forwarded" — contrary
   to spec §3 "do not silently pretend owner filtering exists". Unreachable today
   (activation refuses a capture without a ring, `voice_v2.py` `_authorization_refusal`),
   but it is the one remaining silent-fallback path. Fix: call `_lose_owner(
   "solo_owner_capture_unsupported")` when `accepted` is False while the
   authority is `OWNER`.
3. **`resync()` throws away pending merge closures.** `work_ingress.py:188-192`
   clears `_sent` then calls `sync()`, whose retired-key loop (`:155-162`) pops
   from the now-empty `_sent` and skips every key, so no `cancelled/merged`
   observation is emitted and a merged duplicate stays active in Core forever.
   Fix: snapshot retired keys before clearing `_sent`.
4. **The attention subscriber can be evicted for the process lifetime.**
   `jarvis/core/v2_services.py:95-105` unsubscribes a saturated subscriber;
   `WorkAttentionPolicy` subscribes once (`core/v2_app.py:105-106`) and nothing
   re-subscribes. One burst (a 64-item resync plus job progress) filling the 512
   queue silently ends work attention for good. Fix: detect the eviction
   diagnostic and re-subscribe with a forced resync.
5. **Terminal work can resurrect after 512 evictions.** `core/work_state.py:63`
   caps `_evicted` at 512; once a key ages out, the forwarder's periodic full
   resync re-creates the finished task as fresh, skewing `finished_total` and the
   brain brief. Bounded, but document or raise the cap above tracker capacity.
6. **A persistent 400 floods the journal with blocking disk writes from the event
   loop.** `work_ingress.py:463-472` has no dedup (unlike `_report_unavailable`
   at `:452-455`) and `RuntimeJournal.emit` writes synchronously; a version-skewed
   Core produces ~2 blocking writes/s inside the loop.
7. **`GET /api/work` has a construction side effect.** `control_center.py:1541`
   touches `self.agent`, which on first access builds a `ClaudeLocalAgent`,
   subscribes a new observer and rebinds `work_ingress.on_resync`. No Core state
   is mutated (the contract holds), but a read route should not do this.
8. **The release-gate exemption is slightly wider than advertised.**
   `scripts/verify_release.py` now allow-lists two modules that still ship inside
   the `jarvis` package; the new AST guard catches static imports only, not
   `importlib.import_module`, and `scripts/` is not scanned at all (it does import
   them). The cleaner invariant would be to move the benchmark tooling out of the
   `jarvis` package entirely. (The repair is otherwise sound: I confirmed the old
   rule really did fail, and that `subprocess.run(` appears in exactly those two
   files.)
9. **A hand-set `owner_profile_path` can place the voiceprint outside the ignored
   area.** `jarvis/v2_config.py:400-410` accepts any absolute path, `~`, or
   `../..` (probed: `"../../evil.json"` → `runtime\..\..\evil.json`,
   `"C:\Windows\System32\x.json"` → taken verbatim). The HTTP surface correctly
   refuses the key (`control_center.py:87-95`, `read_only` at `:856`) — the risk
   was recognised — but a user editing `control-center-settings.json` by hand can
   land a biometric profile inside the repo under a name the `.gitignore`
   pattern `owner-voice-profile*.json` does not match. Fix: require the resolved
   path to stay under `runtime_root` (or refuse a path inside the project tree
   that is not git-ignored), with a coded error.
10. **Four diagnostic kinds are emitted but absent from every docs table:**
   `voice.capture_report_failed` (`voice_v2.py:460`),
   `voice.authorization_report_failed` (`:631`), `voice.duplex_reset_failed`
   (`:710`), `core.work.attention_invalid_event` (`core/brain_context.py:45`).
11. **Wrong route template in docs.** `ARCHITECTURE.md:1105` and
    `OPERATIONS.md:591` write `/api/agent/tasks/{external_id}/trace`; the route
    registered at `control_center.py:256` is `{task_id}` (it does also resolve a
    Core `external_id`, so only the template is wrong).
12. **Stale "Ce qui n'est pas vérifié" section.** `OPERATIONS.md:826-841` still
    lists three unverified points and predates Solo Owner; it should point at
    `docs/HARDWARE_ACCEPTANCE.md` as a fourth.
13. **SHA-256 pinning documented for 1 of 8 catalogued models.**
    `docs/SPEAKER_BENCHMARK.md:279-293` claims pinning but the table has no hash
    column; seven of the eight hashes live only in
    `jarvis/adapters/sherpa_model_catalog.py:116-171`. There is also no
    consolidated `NOTICE`/`THIRD_PARTY` entry for sherpa-onnx or the weights.
14. **Two more tautological tests.** `test_work_ingress.py:512-520` (see B4) and
    `test_brain_work_context.py:238` whose `listed_active <= 12` is trivially
    satisfied by data where only ~6 entries fit — it never demonstrates that 12
    *can* fit, nor that attention notes survive (see B1).
15. **Production default changed on synthetic evidence.** Task 09's handoff note
    said "do not set the production default here unless enough real workstation
    data exists"; task 14 moved `owner_threshold` 0.5 → 0.6
    (`jarvis/adapters/sherpa_speaker_embedder.py:52`) on TTS fixtures whose own
    header says they are "NOT evidence for production thresholds". It is a
    documented deviation, the direction is the safe one, and it is labelled
    provisional everywhere — but it remains a decision taken ahead of its
    evidence, and the hop-level FRR at that threshold (28 %, strict run) is not
    surfaced in the report's own defaults table.
16. **`solo_owner` is gated on `continuous_brain`.** Spec §2 asks not to conflate
    conversation authorization with voice architecture; the implementation
    refuses `solo_owner` under `legacy` (`solo_owner_requires_continuous_brain`).
    The settings stay separate and the reason (duplex capture exists only in
    `continuous_brain`) is sound and documented — noted only so the divergence
    from §2 is on the record.
17. **Bookkeeping.** `tasks/TODO.md:30` still shows `- [ ] 00 — Orchestrate the
    implementation` unticked although the orchestration record, the progress log
    and the final report are all written; and the report's task table says
    `test_control_center_quality.py (67)` where the file collects 68 (the task-14
    "+1" is recorded separately). Cosmetic, but the TODO is the status board.
18. **`_write_settings` leaves a world-readable temp file containing the OpenAI
    API key when the retries are exhausted.** `jarvis/runtime/control_center.py:525-538`
    lets the `PermissionError` from `replace_with_retry` escape, so the route
    still returns HTTP 500 (one second later) *and*, unlike
    `owner_voice_profile.save_profile:134-143`, never unlinks the temp file.
    Measured: `control-center-settings.json.tmp` left behind containing
    `"openai_api_key": "sk-…"` at mode `0o666`. It lives under the git-ignored
    `runtime/`, so nothing can be committed — but a plaintext secret should not
    survive a failed save. Fix: `try/except OSError` → `tmp.unlink(missing_ok=True)`
    and return a coded 503; `test_control_center_quality.py:304-324` covers only
    the recoverable path.
19. **The benchmark's per-engine subprocess has no timeout.**
    `jarvis/runtime/speaker_benchmark.py:1085` calls `subprocess.run(...)` with
    fixed argv and no shell (good) but no `timeout=`, while every other
    subprocess in the feature passes one (`speaker_benchmark_fixtures.py:152`).
    A child hung loading ONNX stalls the whole campaign silently
    (`capture_output=True`). Fix: add a derived `timeout=` and map
    `TimeoutExpired` onto the existing `engine_subprocess_failed` status.
20. **The verifier probe checks the model's size, not its content, so a corrupt
    model reports `ready`.** `jarvis/runtime/owner_voice.py:114` compares
    `st_size` to `engine.MODEL_SIZE`; a 28 281 164-byte file of zeros yields
    `/api/settings → status: ready, verifier: ready` and the green "Solo Owner
    appliqué" banner, while Voice will refuse at load time when
    `SherpaSpeakerEmbedder.load` runs the real SHA check. That undercuts task
    08's acceptance ("the operator can tell whether Solo Owner is truly
    enforced"). Fix: cache a `file_sha256` keyed on `(size, st_mtime_ns)` in the
    model dir (~50 ms once) or label the state `unverified` rather than `ready`.
21. **`trace_summary` echoes four free-text fields verbatim, contradicting its own
    docstring.** `jarvis/runtime/trace_summary.py:1-8` promises nothing but
    scalars; numerics are whitelisted and transcripts/embeddings are indeed
    dropped (I verified this independently), but `data.reason` (`:138`),
    `data.code` (`:142`), `data.phase`/`code` (`:144`) and `store` (`:152`) are
    printed as-is. A `reason` containing a sentence is reproduced in full.
    No live emitter does that today — it is a hardening gap, not a leak — but the
    guarantee should be enforced: `str(value)[:64]` restricted to
    `[a-z0-9_./-]`, as `control_center._voice_capture_report` already does.
22. **`scripts/summarize_voice_trace.py` dies with `UnicodeEncodeError` on a
    cp1252 stdout** (`trace_summary.py:254` prints `→`, `·`, `—`). Fine in
    PowerShell 7, fatal in git-bash/`cmd.exe` — and it is the tool the operator
    runs right after a recording session. Fix:
    `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` in `main()`.
23. **Two smaller Control Center inconsistencies.** `_voice_arch_is_continuous`
    (`control_center.py:614-620`) ignores `_voice_arch_problem`, so a hand-edited
    `continuous_brain` + `gemini_live` pair shows a green "Solo Owner appliqué"
    for a runtime that will not boot; and `authFieldChanged` in
    `control_center.html` blanks `speaker_verification` on *any* mode change, so
    open_room+shadow → solo_owner → open_room silently drops a stored shadow
    setting.
24. **Model download has no size ceiling** (`sherpa_speaker_embedder.py:122-125`,
    `sherpa_model_catalog.py:221-224`): the stream is read to EOF and only then
    hashed, although the pinned `size` is available. Abort past `MODEL_SIZE`.
25. **One more misnamed test.** `test_speaker_benchmark.py:651-660`
    (`test_the_handover_rule_only_lowers_a_window_score_never_raises_it`) asserts
    only that hops exist and re-reads its own config; it never compares `score`
    against `window_score`. It should assert
    `all(h.score <= h.window_score for h in hops …)`.
26. **Known, documented behavioural limits worth keeping visible:** owner state
    is published on *change* only, so an owner already confirmed and speaking
    will not cut JARVIS if JARVIS starts talking (mitigated by
    `_hold_for_candidate`); handover leak ≈ 1.2 s; a lone "oui" under ≈ 600 ms of
    voiced speech is dropped; `owner_onset_ms` after a non-owner verdict is an
    estimate.

---

## Verified-good list (checked and confirmed — do not redo)

**Audio / Solo Owner**

- **Exactly-once replay and stream order.** I fuzzed `CaptureProcessor` with 60
  random seeds × 400 blocks of randomly interleaved
  `open_owner_flow`/`close_owner_flow`/`set_owner_gate` commands, with every
  frame carrying a unique marker: **0 duplicated frames, 0 out-of-order frames, 0
  partial frames** across all seeds.
- **No non-owner audio reaches the provider.** Owner gate on, flow never opened,
  500 blocks: the entire 240 000-byte output is digital silence.
- **Sentence start is preserved and the margin is applied.** Onset at 500 ms,
  confirmation 1.5 s later: replay starts at 350 ms (= onset − 150 ms
  `OWNER_REPLAY_MARGIN_MS`) and runs to the live edge, `already_sent_ms = 0`.
- **Ring wrap is clamped and reported.** With `owner_buffer_ms = 500` and an
  onset 3 s old: `clamped_ms = 2500`, replay limited to what the ring still held,
  `code = owner_replay_clamped`.
- **No global non-owner latch (D06).** `OwnerStateMachine` has no latch;
  `owner_confirmed` and `rejected` alternate freely inside one candidate
  (`speaker_shadow.py:189-212`).
- **Owner state only inside an acoustic candidate.** `region is None ⇒ IDLE`
  regardless of verdict (`speaker_shadow.py:189-190`) — echo, clicks and desk
  impacts can never become the owner.
- **The verifier never runs in the PortAudio callback.** `observe()` only masks,
  assembles and enqueues (`speaker_shadow.py:796-834`); all verifier calls happen
  on `jarvis-speaker-verifier` (`:875-905`). Queue overflow drops the oldest hop,
  counts `dropped_ms` and resets the engine.
- **AEC before verification** (`duplex.py:638` `_cancel_echo` → `:676` `_observe`),
  and residual echo is masked to digital silence while JARVIS is audible
  (`speaker_shadow.py:812-815`).
- **No listener leak.** `_detach_owner_source` is in the `finally` of `_consume`
  (`realtime_audio.py:1845-1846`); the publisher removes a failing listener and
  reports it (`speaker_shadow.py:283-302`).
- **Provider `speech_started` is advisory only in Solo Owner**
  (`realtime_audio.py:2643-2649`, `_note_provider_speech:2432-2475`); it never
  cuts, before, after or never.
- **Fail-closed on verifier loss.** `_lose_owner` keeps the gate with the owner
  and closes the flow (`realtime_audio.py:2030-2053`), then deactivates the
  session — no silent open-room fallback.
- **Non-owner transcripts never reach the brain, the trace or the activity
  timer.** `_handle_transcript` drops before `voice.transcript` and before
  addressing (`realtime_audio.py:2799-2808`) and routes to `ambient_activity`,
  which deliberately does not reset the timeout (`voice_v2.py:719-728`).
- **The authorization matrix has no silent-degradation hole.** I enumerated all
  2 modes × 3 verification modes × 4 availabilities × 2 architectures through
  `ConversationAuthorization` + `assess_authorization`: `open_room+enforce` and
  `solo_owner+off|shadow` are refused at construction; every `solo_owner` case
  without a `ready` verifier (or without `continuous_brain`) returns **refused**
  with a stable code, never a quiet open-room fallback; `open_room+shadow`
  without a verifier returns `degraded` with routing unchanged — exactly what
  spec §3 asks for.
- **No vendor type above the adapter boundary.** `grep` over `jarvis/domain`,
  `jarvis/ports`, `jarvis/core` finds no `sherpa`/`numpy` import;
  `test_v2_architecture.py` still enforces it.

**Work state**

- Bounded store (64 items, oldest-terminal eviction, `capacity` refusal),
  `core.work.updated` payload shape, 30 s idle resync + full resend on a new
  `store_id`, revision monotonicity, duplicate idempotency with no revision bump,
  late-terminal wins, `running → pending` refused — all confirmed in code and by
  probe.
- Unknown provider keys genuinely cannot reach the domain: `prompt`, `raw`,
  trace blobs, nested dicts and envelope-level extras are all rejected at the
  batch boundary (`domain/work_state.py:293-296`, applied at `:481`/`:493`).
- External provider id is never equated to the brain `work_id`
  (`WorkLink.merge`, `domain/work_state.py:347-364`).
- `/api/work` is GET-only; no Control Center route can write Core work state.
- The forwarder never blocks the Claude stream reader (`offer()` is sync,
  bounded, I/O-free, `work_ingress.py:324-346`); a tracker listener exception is
  isolated and journaled once (`agent_tasks.py:54-73`).
- `tests/integration/test_work_state_protocol.py` really uses HTTP: real Core,
  real `LocalProtocolServer` on a loopback port, real aiohttp, real Core restart
  with a new token, and a genuine `"secret" not in str(snapshot)` leak check.

**Benchmark harness**

- **The "gate replay" does not fabricate favourable numbers.**
  `jarvis/audio/speaker_benchmark.py:810-912` builds a real `CaptureProcessor`
  with a real owner ring, a real `SpeakerVerificationWorker`, a real
  `ShadowOwnerTelemetry` with `enforce=True`, and replays the bridge's role; the
  `forwarded` spans come from the capture's own per-frame sent flag (`tap.live`)
  plus the real `OwnerReplay` reports — not from labels. The one concession is
  `max_pending_ms = 1 << 20` so no hop is dropped offline, which is disclosed.
- **EER math is correct.** Hand-built cases through
  `speaker_benchmark.equal_error_rate`: perfectly separable → 0.0; identical
  distributions → 0.5; genuine {0.4, 0.6} vs impostor {0.3, 0.5} → 0.5 at
  threshold 0.5, which is the hand-computed answer.
- **Model download is safe.** `sherpa_speaker_embedder.download_model:110-141`
  streams to a `.part`, verifies SHA-256 **before** `replace_with_retry`, cleans
  the partial in a `finally`, and raises a coded `speaker_model_mismatch` /
  `speaker_model_install_failed`. `replace_with_retry` (`adapters/file_replace.py:29-45`)
  retries `PermissionError` only, 8 attempts, 20 → 250 ms, never falls back to an
  in-place write — exactly as the report claims.
- **`owner_profile_path` is deliberately not writable over HTTP**
  (`control_center.py:87-95`, `read_only` at `:856`) — the "arbitrary path from a
  browser" risk was seen and closed.
- **Settings validation is hostile-input clean.** 18 adversarial payloads (NaN /
  inf threshold, `10**400` buffer, negative evidence, dict and list modes, every
  incoherent mode × verification pair) all return HTTP 400 with a stable code in
  `X-Jarvis-Error-Code` and leave `control-center-settings.json` byte-identical;
  `owner_profile_path` is silently dropped from POSTs; the request works on a
  fresh dict so no pre-validation mutation can reach disk.
- **The result schema is frozen by a real test.**
  `tests/unit/test_speaker_benchmark.py:663-725` pins the literal
  `jarvis.speaker_benchmark.result` string, version 2, the whole top-level key
  tuple, `METRIC_KEYS`, `GATE_METRIC_KEYS` and every sweep row.
  `::test_missing_and_failing_engines_are_reported_not_faked` is exactly the
  anti-fabrication test this harness needed.
- **`node --check` really ran** (the suite reports 215 passed / 0 skipped for the
  Control Center + owner-voice set, and the test skips only when node is absent).
- **Nothing biometric reaches `/api/settings` or `.voice_capture`.** Injecting a
  192-float embedding into a real profile and a `SECRET_EMBED` array into
  `.voice_capture` produced a GET payload with no numeric lists and none of the
  embedding digits; `_voice_capture_report` (`control_center.py:576-601`)
  whitelists key by key with type checks and 64-char truncation.

**Reports and tests**

- **All 70 `file::test` references in the final implementation report exist.**
  (Script-checked every `` `x.py::test_y` `` and `` `::test_y` `` in the report.)
- **Per-file test counts match**: 51 / 22 / 39 / 51 / 92 / 79 / 56 / 107 / 3 / 6
  for conversation_authorization, owner_barge_in, owner_replay, owner_input_gate,
  work_state_contracts, owner_voice, speaker_verifier, voice_duplex,
  solo_owner_acceptance, trace_summary. `test_control_center_quality.py` is 68,
  not the 67 in the table (the task-14 "+1" is stated separately — harmless).
- **`1643 passed, 4 skipped` reproduces exactly**, three times.
- **`scripts/verify_release.py` passes**, and the claim that it did *not* pass
  before is true: `subprocess.run(` appears in exactly
  `jarvis/runtime/speaker_benchmark.py` and `speaker_benchmark_fixtures.py`.
- **No flakes**: the timing-sensitive set ran 6× green; `test_solo_owner_acceptance.py`
  5× green standalone. The `test_v2_speech_scheduler.py` flake fix (autouse
  fixture re-anchoring the module-level `ORIGIN`) is a genuine root-cause fix.
- **Docs accuracy**: ≈120 constants, bounds, stable codes, event kinds, endpoints,
  CLI flags and file paths cross-checked against code — all correct, including
  every `voice.*`/`core.*` name in `HARDWARE_ACCEPTANCE.md`.
- **No pre-existing test was deleted or weakened.** `git diff --numstat -- tests/`
  is purely additive on the committed files (`test_voice_duplex.py` +381/−0,
  `test_app.py` +86/−0, `test_v2_speech_scheduler.py` +16/−0); the only removed
  lines generalise a hard-coded bus-subscriber count of 3 into a measured
  baseline (`async_conversation_harness.py`) and widen one payload key set
  (`test_agent_tasks.py`) — both strengthen rather than relax the assertion.
- **`trace_summary` is genuinely whitelist-based.** I fed it a trace containing a
  transcript, a `text` field, a fake embedding array and a base64 `pcm` blob: none
  of them appear anywhere in the summary (only counts and scalar percentiles).

**Safety / privacy**

- Nothing biometric is reachable by Git: `git ls-files` contains no `.onnx`, no
  profile; `/runtime/` was already ignored and `.gitignore` adds
  `speaker-verification/`, `owner-voice-profile*.json`, `*.onnx`.
- The embedding never leaves `jarvis/adapters/owner_voice_profile.py`: excluded
  from `repr` (`field(repr=False)`, `:54`) and absent from `metadata()`
  (`:72-86`), which is the only public view.
- Diagnostics carry scalars only (rounded score, durations, engine, profile id,
  status, exception *type* name) — `speaker_shadow.py:673-709`.
- Licences recorded: sherpa-onnx Apache-2.0, baseline model Apache-2.0 with SHA-256
  `aa3cfc16…` pinned in code and matching the docs; the benchmark result JSON
  carries `model_license` + `model_license_source` per engine.
- No private recording or profile left behind; benchmark fixtures are generated
  from Windows TTS at run time.

---

## Evidence appendix

Commands run from `C:\Projects\jarvis\jarvis` with `.venv\Scripts\python.exe`.

| # | Command | Result |
|---|---|---|
| 1 | `-m pytest tests -q -p no:cacheprovider` (run 1) | **1643 passed, 4 skipped**, 65.89 s |
| 2 | same (run 2) | **1643 passed, 4 skipped**, 65.33 s |
| 3 | same (run 3) | **1643 passed, 4 skipped**, 78.28 s |
| 4 | `scripts/verify_release.py` | suite 1643 passed / 4 skipped (65.44 s) then **"Release verification passed."** (exit 0) |
| 5 | 6 × `pytest tests/unit/{test_solo_owner_acceptance,test_speaker_verifier,test_voice_duplex,test_owner_replay,test_owner_barge_in,test_owner_input_gate,test_v2_speech_scheduler,test_work_ingress}.py tests/integration` | 419 passed, 2 skipped every time — 17.0 / 16.4 / 19.0 / 17.0 / 17.2 / 26.4 s. **No flake.** |
| 6 | 5 × `pytest tests/unit/test_solo_owner_acceptance.py` | 3 passed, 0.75–0.81 s each. No flake. |
| 7 | `--collect-only` per new test file | counts listed in "Verified-good" above |
| 8 | scratch `gate_probe.py` — 60 seeds × 400 blocks of fuzzed owner-gate commands against the real `CaptureProcessor`, unique per-frame markers | **0 seeds with duplicated / out-of-order / partial frames** |
| 9 | scratch probe: owner gate on, flow never opened, 500 blocks | output is entirely zero bytes (240 000 B) |
| 10 | scratch probe: onset 500 ms, 2 s verification delay, 24 kHz | `OwnerReplay(owner_onset_ms=500, requested_from_ms=350, from_ms=350, until_ms=2000, replay_ms=1650, margin_ms=150, already_sent_ms=0, clamped_ms=0, buffer_ms=2500)` |
| 11 | scratch probe: `owner_buffer_ms=500`, onset 3 s old | `clamped_ms=2500`, `replay_ms=500`, warning code path reached |
| 12 | script cross-checking every `` `file.py::test` `` in the final report | 70 references, **0 missing** |
| 13 | `git ls-files \| grep -iE "onnx\|profile\|speaker-verification\|\.wav$"` | only the pre-existing `tests/fixtures/bonjour-jarvis.wav` |
| 14 | `git check-ignore -v` on the default model/profile paths | ignored by `/runtime/` and `owner-voice-profile*.json` |
| 15 | old (`HEAD`) release rule replayed over the current tree | `subprocess.run(` → True, only in `speaker_benchmark.py` and `speaker_benchmark_fixtures.py` — the "it did not pass before" claim is true |
| 16 | JSON read of the four `docs/results/speaker-benchmark/*.json` | `model_load_ms` 517.6/339.8 (09-12 settled), 588.2/359.0 (strict), 865.5/398.0 (09-11 settled); `gate_confirm_ms_p50` 1600…2450; `short_confirmations` baseline 3,3,3,3,3,2,2 vs ERes2Net 3,3,3,2,2,1,0 — see B3 |
| 17 | `grep` for vendor imports in `jarvis/domain`, `jarvis/ports`, `jarvis/core` | none (one comment mention only) |
| 18 | `-m pytest tests/unit/test_control_center_quality.py tests/unit/test_owner_voice.py` | 147 passed, 7.1 s |
| 19 | `-m pytest tests/unit/test_speaker_benchmark.py` | 68 passed, 22.0 s (real-engine e2e included) |
| 20 | `git diff --numstat -- tests/` | additive only; no test function deleted |
| 21 | scratch probe feeding `trace_summary.summarize` a transcript, a `text` field, an embedding array and a base64 `pcm` blob | none of them appear in the summary |
| 22 | enumeration of `ConversationAuthorization` × `assess_authorization` (2 × 3 × 4 × 2) | matrix as documented; no silent degradation for `solo_owner` |
| 23 | hand-built oracles through `speaker_benchmark.equal_error_rate` | separable → 0.0; identical → 0.5; {0.4,0.6} vs {0.3,0.5} → 0.5 @ 0.5 — all match hand computation |
| 24 | `-m jarvis owner-voice --help` | 5 subcommands as documented |
| 25 | 18 hostile `POST /api/settings` payloads | all 400 + stable code, settings file unchanged |
| 26 | corrupted-model probe (28 281 164 zero bytes at the model path) | `/api/settings` reports `ready` — see non-blocking finding 20 |
| 27 | `_write_settings` with `os.replace` failing 8× | `PermissionError` propagates (HTTP 500) and leaves `control-center-settings.json.tmp` (mode 0o666) containing the API key — see finding 18 |

Scratch files were written only under the session scratchpad
(`…\scratchpad\critic-me\`, `…\critic\`, `…\critic-docs\`, `…\critic-cc\`); no
implementation file, test, doc, `tasks/TODO.md` entry or Git object was modified,
and no commit, stash or revert was performed.
