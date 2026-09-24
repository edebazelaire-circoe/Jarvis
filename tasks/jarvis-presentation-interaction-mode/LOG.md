# Execution Log

Reserved for implementation agents. Record durable execution notes, decisions caused by repository drift, validation evidence references, and cross-slice handoffs here. Do not use this file for ephemeral scratch notes.

---

## 2026-09-23 — Slice 00, Project Manager readiness gate (agent 0)

**Outcome: `READY`, conditional on Human decisions W1 and D15.** Full record in
`slices/00-project-manager/READINESS.md`.

- Branch `task/jarvis-presentation-interaction-mode` created from `main` @ `ddcdb71`, which is
  exactly `task.json.source_snapshot.sha`. **Zero snapshot drift.**
- Handoff mirrored from Drive into `tasks/jarvis-presentation-interaction-mode/`: 48 files,
  every byte size matching its Drive source, all 25 JSON files parsed. Committed as S0.
- Blind repository audit performed by a sub-agent forbidden from opening `tasks/`, dispatched
  before any handoff conclusion was read. It confirmed every Level-0 claim in
  `docs/05-documentation-levels.md` independently.
- Regression baseline: 248 unit test files, **7022 collected, 6994 passed, 26 failed, 2 skipped**.
  The 26 are pre-existing at the branch point and listed by name in `READINESS.md` §4. Every
  implementer receives that list as "not yours, do not fix".
- **21 of the 26 are in Scene**, the reuse surface for Slices 08 and 09. Those two Slices get a
  narrower named green subset as their gate, and the Scene failure set is re-measured
  immediately before their dispatch.

### Gaps found by the audit, now binding constraints

| id | Gap | Slices |
| --- | --- | --- |
| G1 | Two voice-architecture axes coexist (`voice_arch` legacy/continuous_brain **and** typed `voice_architecture`); `_apply_voice` is a three-way exclusive branch that deletes `voice_architecture` | 01, 02 |
| G2 | `Disposition` is already taken by `jarvis/domain/scene.py` — use `OutputDisposition` | 01 |
| G3 | `PERSISTABLE_OPTION_IDS` is a 47-entry allow-list; a control absent from it fails to save *silently* | 02, 03 |
| G4 | `configuration_id` restart semantics undecided — escalated as **D15** | 02 |
| G5 | The work lane has no priority field at all; P0-P4 must live in the new speculative path, never on canonical `WorkItem` | 08, 10 |
| G6 | No generic UI seam and no framework; `openLifecycleSeam` is Bare Hands-specific; the z-index registry comment is test-asserted | 03 |
| G7 | `AddressingDecision` is closed, wire-encoded and persisted — do not widen it | 06 |

### Human decisions, both answered 2026-09-23

- **W1 — waived.** Workspace Task Type vocabulary does not exist in this environment; the Human
  granted the same waiver as for the four previous tasks. `task_type: null` stands everywhere.
- **D15 — decided: keep it out.** Interaction mode does not enter
  `VoiceComposition.configuration_id`. Core owns the effective live mode plus a revision counter;
  Voice consumes it through an explicit live event and never restarts on a mode change. Slice 02
  must carry a test asserting a mode change produces **no** `voice.switch.requested`.

Slice 00 is `READY`. Implementation dispatch is open.

### Lifecycle state

Drive folder is still in `to-do`. It must be moved to `current` by the Human before the first
implementation Slice is dispatched; the Drive connector available here can create, read and
update but cannot move folders.

---

## 2026-09-23 — Slice 01, interaction-mode and output-disposition contracts

Implemented at `584b51f` (six files, +1007, zero deletions, zero modifications to existing
modules). Pure domain vocabulary: `InteractionMode{assistant, presentation, meeting}` labelled
SIMPLE / PRESENTATION / REUNION, `OutputDisposition{silent, visual_only, voice_only,
visual_and_voice}` in its own module, and the Presentation policy matrix as data.

### QA

Both mandated passes ran independently and converged: `qa-verification` and `code-review`.
**No blocking findings from either.** Test evidence re-run by QA rather than taken on trust:
`test_interaction_mode_contract.py` 79 passed; with `test_v2_architecture.py` 87 passed;
voice-architecture contract set 134 passed; admission/policy set 67 passed. The Scene files
re-run returned exactly the declared baseline (5 failed / 82 passed for the three files
touched), so no regression. The diff adds only new files, so the regression surface is
structurally nil.

What QA verified rather than believed: all five canonical-reuse claims against their cited
sources; that `dataclasses.replace` — the realistic mutation path — is genuinely refused by the
policy invariants; and that `resolve_interaction_mode` survives 39 hostile inputs (bytes, nan,
Cyrillic homoglyphs, Turkish casing, embedded nulls, `object()`) without raising.

### The decisions are data, not prose

The point of this Slice, and it landed: D03 ("ambient never authorizes an action") and D11
("nothing speaks spontaneously") are two lines in `PresentationOutputPolicy.__post_init__` —
`voice_allowed ⇒ requires_explicit_address` and `authorizes_action ⇒ requires_explicit_address`.
A future row that contradicts either cannot be constructed. QA evaluated both implications over
all rows independently: zero violations.

### Rework (10 items) — delivered at `b75b8e9`, **Slice 01 APPROVED**

The one that mattered: `CONFIRMATION_OR_ERROR` was a single row serving two outcomes with
different policies, so `may_speak(..., ERROR)` returned true for a *success*, and the doc's
"a success is seen, not announced" was enforced only by caller convention — the very thing this
module exists to abolish. Split into `COMMAND_CONFIRMATION` and `COMMAND_ERROR`; the matrix is
seven rows.

Also fixed: the G2 AST guard missed relative imports, aliased module imports and the re-export
path; `decisions` accepted `("Dcheese",)` and now validates against `LOCKED_DECISIONS` = D01-D14;
`resolve_`/`effective_interaction_mode` became `stored_`/`behaving_interaction_mode` so Slice 03
cannot silently drop REUNION from the display; the REUNION refusal message is French (the code
stays ASCII); ~60-80 lines of serialization scaffolding guessing at Slice 02/03 boundaries were
deleted.

### Verification by agent 0, not taken on report

- `test_interaction_mode_contract.py` + `test_v2_architecture.py` + `test_voice_architecture_config.py`
  → **168 passed**, re-run directly.
- The matrix was evaluated independently: 7 rows, **zero invariant violations**, and the R1 claim
  holds in the data — a `COMMAND_CONFIRMATION` can neither speak (`may_speak` false for every
  `SpeechKind`) nor beep (`may_raise_attention_cue` false), while `COMMAND_ERROR` may speak
  `SpeechKind.ERROR`.
- **The G2 guard was probed end to end.** A file containing `from .scene import Disposition` plus
  `from .output_disposition import OutputDisposition` was dropped into `jarvis/domain/`; the
  rebuilt guard flagged it (`assert not ['jarvis/domain/_g2_probe.py']`). That exact spelling
  walked past the original guard. Probe removed.

Incidental find reported by the implementer, worth keeping: `tests/unit/test_third_party_bootstrap.py`
carries a UTF-8 BOM that `ast.parse` rejects, so any repo-walking AST test must read with
`utf-8-sig`. `test_v2_architecture.py` never hit this because it only walks `domain`/`ports`/`core`.

### Carried forward — do not re-derive these

- **Slice 07.** `VISUAL_COMMAND` carries `voice_allowed=False` as a hard ceiling, not a default,
  which is correct for V1. The consequence is that Slice 07's situation classifier must route
  "montre-moi le bilan **et dis-moi le total**" to `EXPLICIT_SPEAK_REQUEST` or
  `KNOWLEDGE_QUESTION`; under `VISUAL_COMMAND` no amount of asking unlocks speech. The failure
  path is already sound — a failed command becomes `COMMAND_ERROR`, which permits
  `SpeechKind.ERROR`, so errors stay audible.
- **Slice 02.** The label collision survives one level up: `VoiceArchitectureId.SIMPLE.name`
  equals `"SIMPLE"` equals `InteractionMode.ASSISTANT.label`. Nothing in the repo transports an
  architecture by `.name` today (QA grepped), but the settings-key design must not create the
  first such path, and the mode must never be read from a key that a voice-architecture value
  could also land in.

---

## 2026-09-23 — Slice 02, live interaction-mode control plane

Implemented at `52ab8cf`, reworked at `abc73c9`. Core owns the live mode plus an epoch and a
revision; the Control Center owns the persisted preference; Voice observes read-only over the
existing `/v1/events` stream. Three mandated QA passes ran: `qa-verification`, `code-review`,
`runtime-validation`.

### One blocking defect, found by QA and predicted by Slice 00

The observer's guard was `revision <= self._revision`. Core's revision is process-local and resets
to 0 on restart, while the observer is owned by `PersistentVoiceRuntime` and survives stream gaps —
`SpeechScheduler._consume_core_events` reconnects forever rather than rebuilding. So after a Core
restart the observer discarded every new revision as stale: **the user chose SIMPLE, Core applied
it, and Voice kept serving PRESENTATION.** Silent, with no recovery path (`adopt()` passed through
the same guard) and no test.

`READINESS.md` §3 G4 wrote this down as D15's residual risk before a line was implemented: *"the
mode changes live, but any path gated on a configuration change will not observe it, and Voice
keeps a stale view."* The slice implemented the D15 half and left the predicted half open. This is
the first time in this task that writing a risk down paid for itself.

**Fix:** Core stamps a per-process `epoch`; the observer holds `(epoch, revision)`; a different
epoch resets the revision floor; an **absent** epoch (older Core) is also accepted, so version skew
fails safe toward freshness rather than staleness. `adopt()` — which had zero production callers —
is now wired to a snapshot refetch on each successful `/v1/events` subscription.

### Proven in the running system, not only in tests

`runtime-validation` built a real Core + Control Center from `abc73c9` in an isolated runtime root
and exercised 6 Core lives, 7 Control Center lives, 16 mode requests, 213 trace lines. The
decisive evidence:

```
{"kind":"interaction.mode.observed",
 "message":"Nouvelle vie de Core observée : la révision du mode repart de zéro",
 "data":{"mode":"presentation","revision":1,"previous_revision":5,
         "code":"interaction_mode_core_restarted"}}
```

Revision 1 arriving while the observer held 5 — exactly what the old guard threw away — and the
user-driven change immediately after it adopted live. The resync seam earned itself too: the bus
event for revision 1 was published at `16:47:38.21` while the stream was still reconnecting at
`16:47:39.5`, so `adopt()` is what caught the observer up. `CoreInteractionModeTransport` also
survived a real token rotation (Core rewrites `core.token` on every start; the stream took a 401
and succeeded on the re-read).

Other runtime results: the replay fires **exactly once** when a late Core appears (96 polls, one
`reconciled`); log hygiene is **0 lines/min** over 179 s of idle polling with a non-default mode and
an unreachable Core, where the previous round could emit a warning per second; `configuration_id`
is byte-identical across assistant / presentation / meeting / absent (`4611e8d8…`), and no
`voice.switch.*` line or switch file ever appeared across 16 mode requests.

### Honestly not proven

A real Voice process was never started — it needs a Realtime credential and it opens the
microphone, which the user's own live Voice process is holding. QA exercised the production
`InteractionModeObserver` against the live Core over a real `/v1/events` socket, wired the way
`SpeechScheduler` wires it, which is a faithful stand-in but is **not** the Voice process. So
"nothing asks for a teardown" is proven; "no session is torn down" is not. That is the right
sentence to carry into Slice 11's end-to-end validation rather than a claim to bank now.

### For the Human

- The JARVIS stack running on this machine **predates this slice** (started 23/09 15:20, the code
  landed 18:03/18:32) and returns `"interaction_mode": null`. It must be restarted before any of
  this is reachable. Its Voice process is `continuous_brain`, so the observer path will be live
  once it is.
- `GET /api/status` now costs ~2.02 s when Core is down, because the slice adds a second Core
  round-trip to the page's only 1 Hz heartbeat. The two reads are gathered, so it is one wait and
  not two, and a failure cannot take the status down — but the page degrades to ~0.5 Hz while Core
  is unreachable. Flagged as a judgement call for a human eye, deliberately not changed.

### Issue raised, not fixed

`Issues/001-settings-read-swallows-a-corrupt-file.md`. `ControlCenter._settings()` swallows a
`JSONDecodeError` and returns an empty dict, so a corrupt settings file reads as a first launch
with no journal line — every setting gone at once. A UTF-8 BOM is enough to trigger it. This is
the exact confusion Slice 02 was built to prevent one level down, sitting underneath a reader that
loses the whole file without a word. Pre-existing and shared by every Control Center setting, so
fixing it inside a Presentation slice would be scope creep with a wide blast radius.

### Journal-truth pass — `0de10f8`, **Slice 02 APPROVED**

Two runtime findings closed. An idempotent rewrite no longer logs `interaction.mode.applied`, so
`.applied` is countable as "the mode actually moved" — and the implementer took the better route
than the one asked for: the verdict comes from **Core's** `disposition` in the POST answer, not
from comparing two local preferences. That distinction is load-bearing, because the stored
preference and the live value can legitimately diverge; after a direct protocol call, writing
PRESENTATION through the route changes the preference while moving nothing, and a local comparison
would have mislabelled it. A Core answering without a disposition falls back to the local
comparison rather than going silent.

The unreadable-setting line now names the stored value (bounded at 64 chars), so `fromage` and
`gruyere` are two incidents in the trace rather than one indistinguishable default.

Final state: **271 passed** across the interaction-mode, control-centre, speech-scheduler and
documented-routes suites, re-run by agent 0. Baseline failures untouched.

---

## 2026-09-23 — Slice 03, the left-side interaction-mode selector

`a3e5583` + rework `347c3c1` + validation pass `48bea17`. A vanilla-JS control bound to the 1 Hz
`/api/status` poll, zero local state, SIMPLE/PRESENTATION selectable, REUNION reserved.
Three QA passes: `qa-verification`, `code-review`, `runtime-validation` **in a real browser**.

### Four blocking defects, all found by QA, none by tests

1. **A hung write permanently disarmed the control.** One shared `deadlineTimer`: the deadline
   released `choosing` while the first fetch was still in flight, so a retry installed its own
   timer in the same variable, and the late first request's `finally` cancelled the *retry's*
   deadline. Driven to `PRESENTATION · 3626 S` with every option disabled. Fixed with a per-call
   ticket in the call's own closure.
2. **The bottom-left corner was not free.** The module asserted in a comment that it was the one
   left-edge slot that could be promised to overlap nothing. Three JS-injected elements were
   already there: `.jh-badge` (`bottom:18`, on a host at z-index 2147483000), `.jh-note`
   (`bottom:46`, which landed *inside* the button), `.sc-status` (18→52). The repo already had a
   dodge convention for that rail keyed off `JarvisBarehandsContracts.DOM.badgeSelector`; the
   control now joins it and is governed by `test_barehands_contracts_js.py`.
3. **A 503 and the REUNION reservation rendered in danger red.** `refusalOf` computed
   `tone:'warn'` and nothing read it; `noteOf` hard-coded `'bad'`, and no `[data-im-note=bad]`
   rule existed at all, so it fell through to a DANGER-coloured base. The slice's own argument —
   the 503 is where being wrong costs most — was honoured in words and contradicted in colour.
   A test actively pinned the wrong value.
4. **The Bare Hands palette overlap was real at ≤700px — at every height, not only short ones.**
   Declared in advance as an unresolved residual, then measured: 64×46 at 700×600, 64×60 at
   700×750, still 64×24 at 700×900, with the button winning on z-index so **the palette's bottom
   tool became unclickable**. The rail lift made it worse. Fixed horizontally — below 700px the
   control leaves the rail and sits right of the Bare Hands column, which makes clearance
   independent of the tool count. The `max-height:640` shrink rule was deleted: it mitigated
   nothing and was dead weight kept for a vanished problem.

### The pattern worth carrying to Slice 09

**Three separate tests in this Slice asserted on source text and missed the bug they existed to
catch**: the z-index registry claim (which greps CSS, not prose — see the correction in
`READINESS.md` §3 G6), the `api()` test (a substring match over a 19-line window containing ten
unrelated functions), and the reduced-motion rule (whose block *names* `.im-mark::after` while
losing the cascade to a higher-specificity selector, so the stylesheet reads correct and the
browser does the opposite).

In a repo where JS is tested from Python by shelling out to Node, `inspect.getsource` plus a
substring match is the path of least resistance, and it produces tests that are precisely wrong
in the cases that matter. **Slice 09 must assert on behaviour or computed style, never on source
text.**

### What runtime validation was worth

The Chrome extension was not connected, so QA drove **headless Chrome over the DevTools Protocol**
instead of reporting nothing: real layout, real `getBoundingClientRect`, 51 screenshots,
`Fetch.requestPaused` to freeze a write mid-flight. That froze-write test is the one that proves
the central constraint — with the POST held open, `--im-ink` was still cyan, no halo, options
disabled, `aria-checked` still on the old mode. Nothing paints amber before the server answers.

It also left a durable asset: `tests/unit/test_interaction_mode_hud_browser.py` +
`_interaction_mode_browser.mjs`, which compose the page through the same marker chain
`ControlCenter.index` uses and **fail rather than skip** if the page does not compose. Slice 09
should use it.

### Final state

**246 passed** across the node suite, the new browser suite, the contracts suite, the control
plane and Control Center quality, re-run by agent 0. 26 baseline failures untouched.

### Human check outstanding

`HV-PRES-MODE-01`, narrowed from 14 steps to **three** by machine evidence — everything a machine
could catch has been cleared, as the handoff's QA doctrine requires.

---

## 2026-09-23 — Slice 04, Presentation working set and transcript tail

`4078acc` + rework `34dcf0b`. Bounded session-scoped state: the working set (topics, entities,
claims with provenance, sources, prepared resources with `hot`/`warm`/`discardable`, open
questions, attention items) and the recent transcript tail, deliberately separate per D06, with
one atomic `PresentationContextSnapshot` over both. In memory only, retired when the effective
mode stops being PRESENTATION. Two QA passes; no runtime pass, since the slice has no producer,
no consumer and no user-visible surface by design.

### Four blocking defects, and what they had in common

1. **A refused `apply()` wrote to store state.** `_bounded_working_set` retired resource ids while
   it was still *deciding*, so a `CAPACITY` refusal permanently banned an id that was never
   stored — and Slice 08's speculative lane is exactly the caller that re-prepares after a
   capacity refusal. The disposition also lied, reporting a resource as *retired* when it had
   never been in the set. Found independently by both QA agents.
2. **`enrichment_lag_s` did not measure enrichment lag.** It measured time since the last commit
   of anything, so ten un-enriched utterances over 27 s reported `0.0` — identical to fully caught
   up. This is the field a Slice 08/10 consumer would gate a deictic on, which makes it the exact
   staleness D06 exists to prevent.
3. **The char ceiling sat below the module's own maximum** (a genuinely maximal set measured
   119 504 against an 80 000 ceiling) and escaped as a bare `ValueError`, breaking the store's
   contract that every call returns a typed disposition — on the one path the header declared
   unreachable.
4. **The markup filter applied to all speech-derived text**, so `PresentationClaim(statement="la
   marge < 10 %")` raised, with a code naming a *resource*. Slice 06 would have received
   exceptions instead of dispositions on ordinary analysis output.

**All four lived in the gap between an invariant being stated in a header and being exercised at
its edge** — "la borne ne peut jamais refuser un ensemble légal", "a refused call writes nothing".
None was in the implementer's mutation set.

### The method note worth keeping

This implementer mutation-tested their own suite before review: six mutations, all caught, and QA
re-ran all six independently and confirmed it. That is real and it should continue. But mutation
testing proves the tests catch changes to paths they **already drive**, and says nothing about
paths they do not — which is why it caught none of the four blockers. The rule given back, and
adopted: **a header sentence of the form "X can never happen" is the test case.**

The root cause was sharper than the individual bugs, and the implementer named it in the rework:
`retired_resource_ids` is now exposed read-only *because without it a test cannot tell "nothing was
written" from "the snapshot did not move"*. The invariant was unobservable, so it could not be
tested, so it drifted.

QA also mutated `_notify`/`_publish` ordering — the guarantee this slice argued for most carefully
— and 301 tests still passed. Being right is not the same as being protected; there is now a test
that reads the bus from inside the listener and fails if the order moves.

### The cross-slice edit, judged and kept

Slice 04 added a narrow synchronous `add_listener` to Slice 02's `InteractionModeService` rather
than subscribing to `CoreEventBus`, on the argument that *a `/v1/events` subscriber would do for
learning the change; it does not do for ceasing to retain what was said in the room*. Both
reviewers endorsed it. `_notify` sits after the state assignment (so a listener reads the new
value), outside the lock (so it cannot deadlock a non-reentrant `asyncio.Lock`), and before the
publish (so the session is gone before any subscriber learns the mode moved); with no `await`
between, notification order can never diverge from state order.

### Final state

**450 passed** across the presentation, interaction-mode, brain-context, work-state, event-bus and
app suites, re-run by agent 0. 118 tests in the new suite, up from 90. Ten of ten rework mutations
caught. 26 baseline failures untouched.

### Carried forward

- **Slice 06** writes the tail and the observations. `bounded_text` (type + length) and
  `safe_reference_text` (locators, titles, descriptor strings) are now different rules — use the
  right one, and expect a typed disposition rather than an exception.
- **Slice 08** consumes snapshots and prepared resources. A capacity refusal no longer bans an id;
  re-preparation after refusal works. `enrichment_lag_s` and `enrichment_lag_entries` now agree.
- **Slice 09** must extend this module's `AttentionCategory`/`AttentionSeverity` rather than
  declaring its own, since `docs/02-architecture.md` gives it the typed `PresentationAttention`
  event.

---

## 2026-09-23 — Slice 05, shared audio capture and the explicit-address lane

`34de032` + rework `0461fca`. The hardest slice in the handoff. PRESENTATION gets one microphone
owner and a priority trigger lane; **SIMPLE is untouched** — the option SLICE.md offers and D14
requires. Two QA passes; no runtime pass, because nothing in a running JARVIS reaches this code
yet (see below).

### Two blocking defects

1. **The counted invariant counted 3 of 6 openers.** `input_ownership.py` claimed every code path
   opening a PortAudio input registers itself. Three did not, including `SoundDeviceRecorder`,
   which runs in production. So with a recorder stream live, `PresentationAudioSession.start()`
   read an **empty** registry, passed its pre-open refusal, opened the hub, and the post-open
   `owners != 1` check read **1** — activation succeeding with two competing streams, and
   journalling success. The mechanism built to make "exactly one" measurable returned the wrong
   number in the only direction that matters.
2. **`stop()` then `start()` produced a deaf Presentation that reported itself healthy.** Both
   QA agents found this independently. Measured: `started=True`, `owners=1`, **device opens=2**,
   zero hub subscriptions, the manual key raising `StopAsyncIteration` — while the journal emitted
   `presentation.audio.started` with `sources: ['manual_key','wake_word']`. This slice's own
   principle is that silence must never mean both fine and dead; this was worse, a positive line
   that meant dead. The suite already knew: the test named "…stops_and_restarts…" built a *second*
   session in its body and carried a comment explaining that a closed lane does not reopen. The
   knowledge never reached the docstring, the doc, or a guard.

Fixed by registering all three sites plus `weakref.finalize` so a GC'd stream cannot leave a
permanent phantom; and by making the session terminal — `stop()` is final, a second `start()`
raises `presentation_session_stopped`. The right distinction, found in rework: the *hub* is
replayable, the *session* is not, because it owns sources that cannot reopen.

### The exception to the no-source-text rule, written down

B1 is about the **absence** of a call, which no behavioural test can prove. So
`test_every_site_that_opens_a_physical_input_registers_its_owner` enumerates every
`RawInputStream(` / `sd.rec(` site against a declared table — a source-text assertion, and the
correct tool here. Its docstring says why the rule does not apply and asks not to be deleted on
that ground.

**Probed independently by agent 0**: an unregistered `sd.RawInputStream(` dropped into
`jarvis/runtime/` made it fail by name; probe removed. This is the same technique Slice 01 used on
its G2 import guard, now propagated by the implementer without being asked.

### Mutation testing, three rounds in

30 mutations run, 30 caught. **Three survivors across the task so far, each a real defect in the
tests rather than the code**:
- **M10** — the resampler continuity test used 480-sample blocks; at 24→16 kHz the step is 1.5
  samples and 240 is a multiple of it, so the carried sample was **never consulted**. The test
  proved nothing about the one thing the module exists for.
- **M12** — `_lost_announced` was dead code; `check_liveness()` already returned early unless the
  state was `OPEN`. Deleted, and the mutation rewritten to remove the state transition, which is
  what actually carries the guarantee.
- **M19** — a `finally` test that proved the wrong thing: `lane.close()` was made to raise, but the
  lane isolates its own sources, so nothing propagated and the `finally` was never exercised.
  Re-aimed at `wake.close()`, which has no internal isolation.

QA independently re-ran six of the first sixteen and confirmed them, and independently verified the
resampler fix byte-for-byte against one-shot at block sizes 7/101/137/480/512/1200, maxdiff 0.

### Where the slice was right and the reason was wrong

The deliberate divergence from `CaptureProcessor.observer`'s permanent-detach-on-first-exception
was **correct** — a hub subscriber is a lane, not an optional observer. But the rationale written
into the code and the canonical doc said it protected the wake detector, and the wake detector is a
*queued* subscriber that can never reach `_deliver_inline` where the counter lives. Conclusion
kept, reason corrected in both places. A right decision defended by a false fact is still a
liability, because the fact is what the next reader inherits.

### Final state

**409 passed** across the presentation-audio, wake, realtime-lifecycle, duplex, owner-voice,
speaker-verifier, architecture, audio-capture and audio-devices suites, re-run by agent 0. The new
suite is 94 tests, up from 70. 26 baseline failures untouched.

### `HV-PRES-AUDIO-01` is not reachable from this slice — moved to Slice 11

The composition root passes nothing, deliberately: wiring it now would open the room microphone in
production, do nothing with the audio (no ambient consumer until Slice 06), and compete for a
device the Human's live Voice process holds. The implementer stated this plainly rather than
claiming the check was reachable. **Slice 11 must wire it and must carry `HV-PRES-AUDIO-01`.**

### Carried forward

- **Slice 06** calls `AudioCaptureHub.subscribe()`. Its docstring now carries the anti-aliasing
  limitation: linear interpolation, no filter — fine for a band-limited wake engine, **wrong for
  transcription**. `06-ambient-ingestion-lane/SLICE.md` does not reference the contract page, so
  the implementer must be pointed at `docs/presentation-audio-capture.md` explicitly.
- A slow **inline** sink starves its siblings on the capture thread (measured: 10 blocks in
  0.506 s). Queued subscribers are isolated; inline ones are not. Slice 06's ambient consumer must
  be queued.

---

## 2026-09-24 — Slice 06, continuous ambient ingestion

`4e85429` + rework `43c51dc`. Hub PCM → segmenter → the neutral transcription port → Slice 04's
store → cheap analysis. Two QA passes; no runtime pass, for the same reason as Slice 05 — nothing
in a running JARVIS reaches this code by design.

### Four blocking defects

1. **A dangling revision marker wrote stale speech into the tail with a fresh timestamp.** A
   force-cut segment armed `_pending_revision`, cleared only by the *next successful* observation.
   Seven failure paths left it set indefinitely, so a transcript arriving an hour later was joined
   onto twelve-second-old text under the old utterance id with a current `spoken_at` — the exact
   corruption D06 exists to prevent, in the one field a deictic resolves against, and silent. The
   implementer found a further defect while fixing it: the promise was armed **before** the store
   call, so a *refused* text could promise a continuation.
2. **The transcription worker was the only one of three with no exception guard.** It died
   permanently and silently — `stats()` still reported `started=True, degraded=False`, and the
   task's exception was not retrieved until `stop()`, which swallowed it. "A conforming store
   never raises" over a `Protocol` the doc says Slice 11 may back with a cross-process relay.
3. **It took the hub's threshold, dropped the hub's window, and claimed both.** `capture_hub.py`
   pairs `MAX_CONSECUTIVE_SINK_FAILURES = 3` with `SINK_FAILURE_WINDOW_S = 2.0`, and its comment
   names the failure precisely: *« sinon trois accrocs espacés d'une minute finiraient par
   détacher l'abonné »*. Slice 05's finding recurring, with the correct pattern sitting in the
   module cited as the source. **Copying a constant is easy; copying the mechanism around it is
   what gets dropped.**
4. **Both import guards were denylists, and QA walked through both** — `from jarvis.core.tools
   import ToolRegistry` into the lane and `import subprocess` into the domain module, 75/75 still
   passing. These guard G7/D03, the task's most important constraint.

### The fix for B4 came from QA's own method

QA verified G7 by taking the **transitive import closure**: importing `ambient_lane` into a clean
interpreter loads a small declared set — no brain service, no back-brain, no tool registry, not
even `jarvis.domain.v2`. There is no path to a mutation tool because there is no edge to reach one
on. That property is now the guard: the lane must load exactly 20 declared modules, the domain
exactly 5 plus a stdlib allowlist. The by-name test is kept **alongside** it deliberately, because
when it fails its *name* says what broke.

**Probed by agent 0**: `from jarvis.core.tools import ToolRegistry` — the import that walked
through the denylist — now fails `test_la_lane_ambiante_ne_charge_que_des_modules_declares`, and
the message enumerates the six modules it drags in. Tree restored.

### QA argued in the implementer's favour, and was right

The report claimed D06 holds by line order. It holds by a **data dependency**: the enqueue needs a
sequence rank that does not exist until the store has assigned it, and is gated on the store
having accepted. The ordering cannot be inverted because the second step consumes a value only the
first can produce.

QA proved this the right way round — it mutated the code into a genuine D06 inversion and found
**the test named as the D06 proof still passed**, because the analysis worker is a separate task so
`apply()` lands after `observe()` regardless of enqueue order. The inversion was caught, by three
*other* tests. A test can be right about the system and wrong about itself. The doc now leads with
the data-dependency argument.

### The mutation pattern this slice named

Two survivors across two rounds, both the same shape. **M6**: a refused tail append still fed the
analysis queue — the test refused nothing mid-flight. **M26**: removing the `tail_refused` abandon
changed nothing, because the test refused *every* observation, so no promise was ever armed and
the abandon was a no-op; the bug is only visible when the refusal lands **mid-cut**.

The implementer named it themselves: *a test that exercises a guard's code without ever reaching
the state the guard exists for*. That is the third distinct failure-of-tests pattern this task has
catalogued, after source-text assertions (Slice 03) and unexercised header invariants (Slice 04).

### Other corrections

The report claimed the lane was "the first thing in the repo to depend on" the transcription port.
It was not — every reference was prose, and a local look-alike returning `Any` meant the port still
had zero importers. Now genuinely imported, and load-bearing for the first time since it was
written. Also corrected: `prune()` was the one store call site not accounting its disposition (the
test *fixture* was part of the gap), deafness is now a state rather than a silence, and the doc no
longer calls the analysis queue's bound of 8 a burst absorber — it says plainly that it absorbs
nothing today and why it exists anyway.

### Final state

**630 passed** across the ambient, working-set, presentation-audio, audio-capture, v2-domain,
admission, architecture, control-plane, realtime-lifecycle and duplex suites, re-run by agent 0.
The new suite is 100 tests, up from 75. 25 stable baseline failures untouched.

### Carried forward

- **Slice 08** inherits the analysis heuristics with their caveats now documented (doc §11): the
  four confidences are hard-coded and uncalibrated and are the only ranking signal it will get;
  `_references` yields a whole sentence for any of 19 nouns.
- **Slice 11** inherits O1, now written into doc §7: `PresentationObservationSink` is
  **synchronous**, so backing it with a cross-process relay is blocking IO on the Voice event loop
  — the loop that also carries the explicit-address lane. The "one-line substitution" framing is
  false for the relay branch, and that would be a D04 violation discovered late.
- **Slice 11** must wire both the audio session and the lane, and `HV-PRES-AUDIO-01` needs an
  ambient half.

---

## 2026-09-24 — Slice 07, the Presentation response and speech policy

`708eaef` + rework `0c122d4`. Silence becomes a first-class successful outcome, enforced by a
runtime gate in `SpeechScheduler` rather than by prompt prose. Two QA passes.

### The blocker that vindicates the readiness record

**Presentation was mute on all three typed voice architectures.** `realtime_audio.py:4494` opens
`if self.direct_conversation:` and returns at `:4521`, before `:4549` where the gate is told a turn
happened — and `voice_v2.py:651` sets `direct_conversation = conversation_architecture is not
None`, which is `SIMPLE`, `FRONT_BRAIN` **and** `DUPLEX`. Only the legacy `continuous_brain` path
behaved as designed. QA reproduced it on live objects with the repo's own `direct_harness`:
`"quel est le total ?"`, `"dis-moi le total"` and `"montre-moi le bilan"` each produced **0**
responses in PRESENTATION and 1 in ASSISTANT.

This is **G1 from the Slice 00 blind audit**, seven slices later. The audit's finding was that two
voice-architecture axes coexist and the older one is still the runtime authority; this slice was
exercised against one of them. A gap written down on day one caught a defect that 91 tests and 47
mutations missed.

It is also the Slice 06 test pattern for the **third** time:
`test_la_voie_directe_de_duplex_obeit_a_la_meme_politique` primed the gate by hand with a state
production cannot reach, and its name asserted the opposite of live behaviour. The replacement
drives `bridge._handle_transcript` on the real harness and adds a test resolving all three typed
configs, so "the direct path is tested" is now a claim about three.

### The deviation: adopted in substance, rejected in form

The implementer found a real hole — `may_speak(VISUAL_COMMAND, QUESTION)` was `False`, so a
clarifying question on an ambiguous visual command was silenced, giving a turn with neither screen
nor sentence — and flagged their own fix as a judgement call on a locked artifact rather than
shipping it quietly. Both reviewers converged on a sharper answer, and it was adopted:

- Slice 01's `COMMAND_ERROR` precedent is **outcome-driven**; the re-situation was **label-driven**,
  keying off a field the speech producer chooses. Nothing leaked today only because the brain
  cannot choose a kind — but the ceiling the matrix calls absolute would be unlocked by writing a
  different word in a field, the moment a tool let it.
- `SpeechKind.QUESTION` had **no producer anywhere in the repo**. The clarification arrives as
  `RESULT`, which `VISUAL_COMMAND` refuses, so the hole was still open on the only reachable path —
  verified live. Worse, `BRIEF_PRESENTATION_MODE` promised the model that whatever it had not
  understood could always be asked, while the runtime dropped exactly that sentence.
- **The matrix is not what the Human locked.** D01-D14 is. D09 says visual commands should
  *normally* execute silently; D11 is about fact-check alerts. "Nothing speaks without an explicit
  address" is **Slice 01's own generalisation**, stricter than the decision it cites.

So the exception entered the matrix **as data**: `safety_speech_kinds`, validated in `__post_init__`
against `requires_explicit_address` exactly as `speech_kinds` is. Verified by agent 0:
`may_speak(VISUAL_COMMAND, QUESTION)` is now `True`, `may_speak(VISUAL_COMMAND, RESULT)` is `False`,
and both unaddressed rows carry no safety kinds — **D11 holds**. `may_speak` is the whole truth
again; `SAFETY_SITUATIONS` and `judged_situation` are deleted, and the previously undocumented
`situation=None, kind=ERROR` rule is now named data in the doc's table.

The producer question was answered the principled way: `public_answer_kind()` labels an answer
`QUESTION` only when it is **one interrogative sentence and nothing else**, computed by Core from
content — not a field the agent fills. *A statement cannot declare itself a question without
ceasing to be one.* An answer that then asks a follow-up stays `RESULT` and stays withheld. Zero
tests moved across the brain, orchestrator, contracts, outcome and protocol suites: what the user
hears is identical, only Core's bookkeeping becomes correct.

And the boundary is now guarded.
`test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole` enumerates every
production `SpeechRequest(` site by AST and requires each `kind=` to be a literal or a declared
Core decider. **Probed by agent 0** at the real site — fails by name, tree restored. Note the first
probe attempt *passed*, because the literal it targeted no longer existed: **a probe that passes
must be checked too.**

### Final state

**569 passed** across the response-policy, speech-scheduler, presentation-speech, reflex,
control-plane, ambient, contract and composition suites, re-run by agent 0. 41 mutations, zero
survivors. 25 stable baseline failures untouched.

### Two operational findings worth keeping

1. **The scratchpad is shared between agents.** A QA agent had left harnesses named `mutate.py` and
   `mutate5.py`; the implementer ran what they took for their own, and it **restored two product
   files to HEAD mid-rework**, after which mutations reported "caught" while the suite was failing
   for an unrelated reason. Caught by `git diff --stat` showing two expected files missing, then
   every mutation round and test batch re-run from scratch under unique names. **Agents must
   namespace scratchpad files, and verify the tree before trusting a mutation result.**
2. **A second flake, investigated rather than dismissed:**
   `test_back_brain_worker.py::test_cancel_during_spawn_retains_owner_then_closes_exact_process[claude]`
   failed once in a 90 s batch, passes alone and on re-run, and is green on both the pre-rework and
   the reworked tree. The assertion is a 2 s deadline on a spawn/cancel race under load. Same family
   as `[owned_read]`. Both belong on the baseline list as flakes, not as inherited failures.

### `HV-PRES-SPEECH-01` must be run once per voice architecture

B1 is exactly what a single-architecture human check would have missed — and the path it would most
likely have exercised is the one that worked.

---

## 2026-09-24 - Slice 08, speculative preparation and hidden staging

New lane: ambient triggers -> bounded, deduplicated, sacrificial preparation ->
Slice 04 resources + hidden Scene objects. Three new modules, one +15-line
change to `display_mcp.py`, 66 new tests. No QA pass yet.

### The freshness audit changed the shape of the slice

`back_brain` **already has** a `speculative_analysis` scope, fully built. It is
unusable here for a reason worth writing down: its execution profile launches
the CLI with **`--tools ""`** (`claude_local.py:713`) - zero tools, which is
right for re-reading a transcript and wrong for D07's research. And
`OwnedJobExecution._slots` is an `asyncio.Semaphore(1)` held for the whole
worker call (900 s default), so a speculative job admitted there would **block
the next addressed turn** - D08 violated as written, with no preemption
possible. Hence a separate pool. `BackBrainTaskService` is untouched.

Also corrected for the record: the "flat capacity of 32" at `back_brain.py:40`
bounds in-flight *submission continuations*, not jobs. Durable job capacity is
**16** (`sqlite_state.py:689`). The real bottleneck is the semaphore.

### Two defects the slice's own tests caught before review

1. **The journal carried speech.** `SpeculativeJobKey.value` is built from the
   trigger text, and Slice 06 warns `_references` yields a *whole sentence*.
   Every `admitted`/`coalesced`/`preempted` line printed what was said in the
   room. Fixed with a digest; `value` now carries a docstring forbidding it in
   a trace.
2. **`stop()` returned while work was still running.** `drain()` awaited the
   pool, but a preempted job has already given its slot back - so it awaited
   nothing.

### The mutation round that lied, and how it was caught

The first round reported **36/36 caught** and was **entirely void**: the harness
passed `--timeout=120`, which is not installed, so pytest exited non-zero on
every run. Only the trailing `BASELINE after restore: RED` line exposed it.

This is Slice 07's *"a probe that passes must also be checked"* in a new shape.
The harness now refuses to start on a red baseline **and** carries a deliberate
cosmetic mutation (`M00-CONTROL`) that **must survive**; a run reporting it
caught is a lying harness. Recommend every later slice adopt the control.

Round 2: 36 mutations, **10 survivors, all real test gaps**. Round 3: 38
mutations, **zero survivors** (control excepted).

### The third pattern, for the third slice running

Three survivors (M01/M03/M05) were one defect: `_check_capability_table()` ran
on every import but **never met a table it should refuse**, so widening
`GRANTABLE_RISKS` to include `WRITE` broke nothing. That is *a test exercising a
guard's code without reaching the state the guard exists for* - Slices 06, 07,
now 08. M17 was the same shape on provenance: the test spoke at the frozen
clock, so `spoken_at` and `now()` were identical and confusing them was free.
M28 found a **dead branch**: `behaving_interaction_mode` never returns `None`,
so a documented guard described a mechanism the code could not reach.

### Carried forward

- **Slice 11** must wire the runner. `SpeculativePreparationRunner` is a port
  with no production implementation, and building `--tools` from
  `SpeculativeGrant.allowed_tools` is where the `--tools ""` finding has to be
  answered. It joins the audio session (05) and the ambient lane (06) already
  waiting there.
- **Slices 09/10** get `reveal()` built and tested; *when* to reveal is theirs.
- **A judgement call flagged for review:** `scene_create_object` is classified
  `RiskLevel.EPHEMERAL`, following `BOARD_PRESENT`'s precedent. It is the only
  place this slice extends the canonical risk vocabulary to a new name.
- **Doc drift, pre-existing, not resolved here:** `docs/presentation-ambient-lane.md`
  and `docs/presentation-working-set.md` both cite `docs/02-architecture.md`,
  which does not exist in `docs/` - it lives under the handoff folder.

### State

Scene gate **222 passed / 21 failed before and after**, unchanged. 1 522 tests
run across the affected surfaces; one failure, the declared
`test_brain_delegation.py` baseline. Neither known flake reproduced.

### Reprise — six defauts bloquants, douze points

**B1 etait ma propre correction, et elle etait pire que le defaut qu'elle
remplacait.** `while self._tasks: await gather(...)` ne suspend pas quand tous
les enfants sont deja termines, donc les rappels `done` en attente ne tournent
jamais : 710 550 tours en deux secondes, et un `stop()` dont on ne revenait pas.
Aucun test ne l'atteignait — les trente-huit appels existants entraient pendant
qu'une tache tournait encore, la ou l'ordre des rappels sauvait la mise, et il
n'existait aucun test dedie de `stop`/`drain`.

**B2/B3 sont le meme defaut vu de deux cotes : le seul effet durable de la voie
etait le seul que la table de capacites ne gardait pas.** Un travail ambiant
`new_topic`, sans un seul outil de scene dans son jeton, creait un objet de
scene — et cet objet descend jusqu'a `INSERT INTO scene_objects`, survit au
redemarrage, n'etait jamais repris, et un
`scene_set_visibility(scope="all_hidden")` du cerveau les revelait tous d'un
coup. La page contractuelle disait « No persistence. That is D13 » : c'etait
faux. `scene_create_object` est desormais `WRITE` et non `EPHEMERAL` — le
precedent de `BOARD_PRESENT` ne transporte pas, ce tableau-la ne range rien — la
capacite qui l'accorde est hors de portee de l'ambiant, un jeton ambiant qui la
porterait **ne peut pas se construire**, et `retire()` reprend les objets montes.

**B4 : l'outil retenu avait un sur-ensemble accorde trois lignes plus bas.**
`scene_update_object` accepte `visibility`, `geometry`, `layer` et un
`object_id` quelconque. Retire.

**B6 est la lecon la plus utile de la reprise.** La garde d'origine testait le
chemin interne sous une docstring qui pretendait viser la surface MCP. Ma
deuxieme version lisait le **schema** publie — et la mutation de QA est passee
aussi, parce qu'un schema ne voit pas un corps de fonction. La troisieme traverse
le serveur construit jusqu'a la commande serialisee. **Un probe qui passe doit
etre verifie** vaut aussi pour les probes de reparation, pas seulement pour ceux
de l'implementation initiale.

### Le troisieme motif, encore, et cette fois cause par ma propre correction

M12 a survecu a deux rondes. La seconde fois parce que ma correction du point 3
(ne rien sacrifier quand le bassin a de la place) faisait sortir
`note_addressed_turn` **avant** d'atteindre le filtre de victimes que le test
existe pour garder. Corriger un defaut peut rendre inatteignable l'etat qu'un
autre test visait : il faut re-verifier que les gardes voisines sont encore
atteintes apres chaque correction, pas seulement que la suite est verte.

### Note operationnelle — arreter une ronde de mutations

Tuer une ronde en vol a laisse un fichier mute sur le disque **et** deux
processus en attente active a 5 783 s et 1 119 s de CPU, sur une machine souvent
sous 2 Go libres. Deux consequences, toutes deux traitees :

- la verification d'arbre du harnais lit desormais des **marqueurs de contenu**
  plutot que `git status` : une partie du travail est commitee, donc « modifie »
  n'est plus le bon test ;
- avant de tuer quoi que ce soit, lister les `python.exe` **par ligne de
  commande**. Sur cette machine, tout sauf deux appartenait a la pile JARVIS
  vivante de l'utilisateur (core, voice, control-center, serveurs MCP). Tuer
  « tous les python » aurait coupe son assistant.

### Corrections a mon propre rapport

- « elargir ce profil elargirait le chemin adresse » etait **faux** :
  `back_brain_worker.py` ne choisit `speculative_analysis` que pour un travail
  speculatif. Et l'argument decisif contre ce chemin est celui que je n'avais
  pas fait : **il est durable**, ce que D13 interdit.
- « sans preemption possible » exagerait : ce qui manque la-bas est la
  **concurrence** (`Semaphore(1)`), pas l'annulation.
- `docs/presentation-working-set.md` ne portait pas la citation morte que je lui
  attribuais ; seul `presentation-ambient-lane.md:65` l'avait, et c'est corrige.

### Etat

**88 tests** (contre 66), **51 mutations, zero survivant** hors controle
positif. Porte Scene **222 / 21 avant et apres**, remesuree. 1 579 tests sur les
surfaces touchees, un echec, celui de `test_brain_delegation.py` deja au
referentiel. Aucun des deux flakes connus ne s'est reproduit.

### Reste ouvert

- **La garde de fermeture d'import du service reste une liste d'interdiction.**
  La forme de la Slice 06 est la bonne et le domaine l'emploie deja ; pour le
  service, la fermeture atteint des paquets tiers dont l'ensemble exact varie
  d'un environnement a l'autre. Signale plutot que declare fait.
- **Slice 11** herite en plus de la reprise des objets montes apres un arret
  **non propre** : `retire()` ne couvre que le chemin ordonne.

---

## 2026-09-24 — Slice 08, speculative preparation

`6cb43d3` + rework `064e505`. Ambient triggers launch bounded, lower-priority, deduplicated
research; results normalise into Slice 04's working set and stage as hidden Scene objects. Two QA
passes. Scene gate held at **222 passed / 21 failed** before and after, measured three times by
three agents.

### Six blocking defects, and the one thread that connected them

The slice's headline claim was a capability table that gates what speculative work may do. Four of
the six blockers were the same fact from different angles: **the one effect in this lane that
reaches durable state was the one the table did not gate.**

1. **`stop()` never returned.** Awaiting a `gather` whose children are already done does not
   suspend, so the `discard` done-callbacks never ran and `_tasks` never emptied. QA measured
   **710,550 spins in 2 s**; the process had to be killed. It was the implementer's own fix for a
   defect they had self-caught, and it was worse than the bug it replaced.
2. **Staging bypassed the table entirely.** A P4 **ambient** job granted `RESEARCH_SEARCH` only —
   four read tools, no scene access — created a Scene object. Proven by QA driving the real classes.
3. **Staged objects were durable, not ephemeral.** `scene_create_object` → `_repository.commit` →
   **`INSERT INTO scene_objects`** in `data/state/scene.sqlite3`. They survived process restart;
   one existing brain call `scene_set_visibility(scope="all_hidden")` revealed **every** hidden
   object including every speculative staging the user never asked for; and nothing ever removed
   them, so they accumulated against `MAX_SCENE_OBJECTS = 512`. The contract page said "No
   persistence. That is D13."
4. **`scene_update_object` was `scene_set_visibility` under another name** — it accepts
   `visibility`, an arbitrary `object_id`, plus `geometry`, `layer` and `order`. QA captured the
   wire payload: `{"op":"set_visibility","actor":"brain",...}`. A job could reveal itself and
   re-place any object the user was looking at — a D12 breach three lines below the table that
   granted it.
5. **Ordinary long triggers were silently dropped as illegal.** `job_key_text` truncated *after*
   stripping, so a 64-char cut could land on a space; the key's own validator then refused it and
   the refusal was swallowed as `speculative_trigger_unkeyable`. Slice 06's `_references` yields
   whole sentences, so these were the common case.
6. **The guard on the brain-facing MCP surface tested the wrong function** — proven by a mutation
   that survived.

### The classification error that unravelled it

`scene_create_object` was labelled `EPHEMERAL`, citing `BOARD_PRESENT`. The precedent does not
transfer: `BOARD_PRESENT` posts to a loopback board that **stores nothing**. An `INSERT` is not
ephemeral. It is now `WRITE`, the capability that grants it sits outside `AMBIENT_CAPABILITIES`, an
ambient grant carrying it **cannot be constructed**, `retire()` reclaims staged objects via
`scene_archive`, and `MAX_STAGED_OBJECTS` bounds them.

Verified by agent 0: an ambient job can now reach exactly six tools — `Glob, Grep, Read, WebFetch,
WebSearch, memory_search` — and **zero** `WRITE` tools. `scene_update_object` is gone from the table
entirely.

The implementer flagged the `EPHEMERAL` call for review themselves. It was the right instinct: that
single label was the thread that, pulled, unravelled four of the six blockers.

### Three lessons this slice produced

- **"A probe that passes must be checked" applies to repair probes too.** The implementer's
  *second* MCP guard read the published FastMCP schema — and passed under the same mutation,
  because a schema cannot see a function body. The third drives the built server through
  `call_tool` to the serialized command, and fails by name. Agent 0 then hit the same lesson in a
  third form: two probe attempts passed because the `-k` filter never *selected* the guard (the
  test is named `…ne_cree_jamais_un_objet_masque`, containing neither "mcp" nor "visibilite").
  A passing probe means nothing until you confirm it reached the guard.
- **Fixing one defect can make another test's target state unreachable.** Mutation M12 survived
  twice — the second time because the fix for another item made `note_addressed_turn` return
  *before* reaching the victim filter the test exists to guard. Green is not enough; neighbouring
  guards need re-checking after each fix.
- **Mutation testing is silent about paths no test enters.** The implementer ran 38 mutations with
  zero survivors and a control that must survive — genuinely rigorous — and QA still found six
  test-shape defects by reading. Five of the six blockers sat on paths no test reached.

### The freshness audit, corrected

Both facts checked out — `speculative_analysis` launches the CLI with `--tools ""`
(`claude_local.py:713`), and `OwnedJobExecution._slots = asyncio.Semaphore(1)` is held for the
whole worker call. Building a separate pool was correct. But two supporting claims were wrong:
widening that profile would **not** have touched the addressed path (which uses `job_result`), and
preemption *was* possible there — what was not possible cheaply is concurrency. **The strongest
argument was the one not made**: that path is durable, and D13 forbids persistence. Now stated.

### Final state

Scene gate **222/21** unchanged. **459 passed** across the speculative, working-set, ambient,
back-brain, work-state, architecture and display-MCP suites, re-run by agent 0. 88 tests in the new
suite, up from 66. 51 mutations, zero survivors besides the deliberate control.

### Carried forward

- **Slice 11** inherits: wiring this lane (nothing reaches it today); the `--tools ""` question for
  the real runner; and **reclaiming staged Scene objects after an unclean shutdown** — `retire()`
  covers only the orderly path, and these rows are durable.
- **Slice 11** should also convert the service's import-closure test from a denylist to an equality
  allowlist over the `jarvis.*` subset, leaving third-party packages unasserted. The domain one is
  already an allowlist. QA verified the current closure is clean (32 modules, none forbidden), so
  this is about keeping it that way — Slice 06 established the pattern.
- A regression in `drain()` **hangs rather than fails**, and no in-loop deadline can fire during a
  busy spin. `pytest-timeout` is not installed. The test says so in its docstring.

### Process note

Agent 0 dispatched this rework while `qa-verification` was still mutating the same checkout. QA
noticed the tree diverge and correctly scoped its verdict to the commit rather than folding another
agent's edits into it. Nothing was lost. The `one-implementer-per-worktree` memory has been
corrected: **a QA agent that mutation-tests is a writer, not a reader**, and must not overlap an
implementer. Separately, a killed mutation run left two orphaned busy-spin processes; before
killing anything the implementer listed every `python.exe` by command line and found all but two
belonged to the Human's live JARVIS stack.

---

## 2026-09-24 — Slice 09, fact-check attention

`801e5a8` + report `ca5cb59` + rework `726146f`. A verified contradiction produces one floating
card and at most one discreet cue, never speech. Two QA passes, **one in a real browser**.

### Reuse was the strongest in the handoff

No second sound emitter, no second poll, no second ledger. `bgCue` remains the sole emitter and the
slice contributed only the gate that was missing. The card is an ordinary child of the existing
`#toasts` rail; `#bgPills`, `GET /api/background` and `POST /api/background/ack` are untouched in
behaviour. Slice 04's `AttentionCategory`/`AttentionSeverity`/`AttentionItem` are used as-is — and
because `to_item()` produces the Slice 04 record, the store's coalescing key **is** the event
identity, so semantic dedup came free. That reuse was possible because Slice 04 recorded, five
slices earlier, that Slice 09 must extend its vocabulary rather than declare its own.

### Four blocking defects — two of which only a browser could find

1. **A refused tab stole the cue lease, and a real contradiction went silent.** `claimCue` wrote
   the lease *before* consulting the high-water mark and never released it on refusal, so a tab
   that emitted nothing became the 3-second leader and muted every other tab. QA reproduced it in
   real Chrome with **no forced timing** — one tab merely missing a few 1 Hz polls, which is what
   Chrome does to a hidden tab. The card then rendered with **zero cues, permanently**. That is the
   outcome the module header names as the defect it exists to prevent.
2. **The card made the acknowledgement pill unclickable on a short viewport.** `.pa-card` is
   bottom-anchored in the toast rail; `.bgpills` follows the viewport *centre*. Confirmed by
   `document.elementFromPoint` returning `div.pa-card` where the button should be — and that pill
   is the documented acknowledgement door for the very warning the card shows. Unlike a toast, the
   card never expires.
3. **"Never raises" was asserted three times, false twice, untested in all three**, and the one
   refusal code defending the genuinely fallible path was reached by nothing.
4. **The burst-limiter test proved nothing about bursts** — it overrode the production bound and
   submitted two *identical* assessments, so deleting the clip entirely would have changed nothing
   observable. `MAX_ATTENTION_PER_BATCH` could have been set to 1000 with the suite still green.

### Where the blind spots were, exactly

Both browser blockers came from measurement sets with holes, not from carelessness:
- The implementer measured **seven viewport sizes before choosing placement** — the right order of
  operations, and rare. The set had no **short-and-wide** shape, which is the only geometry that
  brings the centre-anchored pills into the bottom-anchored rail.
- The test covering the lease reached the exact failing state and **asked the wrong question**: it
  re-queried only the tab that was refused, never whether the other could still sound. QA applied
  the correct fix and all 40 JS tests still passed — blind in both directions. Sixth occurrence of
  that pattern in this task.

### Two fixes better than what was asked for

- For the lease, agent 0 proposed releasing it on refusal. The implementer **reordered** instead,
  so a tab with nothing to announce touches neither the lease nor the mark: *"there is nothing to
  release because nothing is taken."* Verified — the mark now refuses at `:31`, the lease is
  written at `:32`. Removing the possibility beats handling it.
- For the viewport collision, they **deleted the threshold rather than moving it**: *"a threshold
  wrong at 820×900 will be wrong somewhere else."* The bug was not the number; it was that a magic
  width decided anything.

### A wrong answer that reads as a right one

Closing B3 turned up something sharper than the finding. A `str` passed where an id collection was
expected is iterable, so `set()` would have silently produced a set of **letters** — turning a
caller's bug into a plausible-looking `attention_claim_unknown` refusal. Now refused explicitly. A
wrong answer wearing the shape of a legitimate one is worse than a crash.

### The `reason` divergence — upheld, overruling Slice 04

Slice 04 specified the attention `reason` as 160 chars for this slice's warning. The implementer
composed the card from typed references instead and kept `reason` for Slice 10, arguing room speech
must never enter the durable trace — and **asked for an explicit ruling rather than resolving it
quietly**. Upheld.

QA proved it end to end: a phrase planted in both the claim and the `reason`, driven through the
real service, real ledger, real digest and the real served page, appears in **zero** journal lines
(including the message field), zero ledger payloads, zero status payloads, and is absent from the
DOM both closed and open — while remaining in the working set, exactly where it was said to stay.

**The cost, recorded:** the card says *that* something was contradicted and where the evidence is,
never *which sentence*. That is why `HV-PRES-ALERT-01` splits across two slices — its own script
ends "then optionally ask Jarvis what it found", which is Slice 10.

### A fifth way a mutation harness can lie

This task has now catalogued five: pytest exiting before collection (three agents); CRLF making
multi-line patterns match nothing, so a mutation that never applied read as caught; and here, a
round killed by the memory reaper left a mutation applied on disk while the tree check passed,
because it verified **one** content marker per file and that marker was intact. Caught only because
a pattern search returned 0 against a file that visibly contained the mutation.

The common shape every time: **the harness reported a state it had not checked.** The rule now
adopted — print `git diff --stat` for every mutation before rendering its verdict — would have
caught all five.

Also worth keeping: **three of four rework survivors were the implementer's own tests, not their
code**, each reported rather than quietly fixed. One reused three claim ids so the store coalesced
and the ring never filled; one pressed Escape and checked nothing else; one used a fixture whose
trace label *was* the table's sentence, making two sources indistinguishable.

### Final state

**424 passed** across the attention, JS, browser, ledger, working-set, speculative, quality,
documented-routes and hud-browser suites, re-run by agent 0. 123 tests in the slice, up from 92.
21 rework mutations, zero survivors besides the control. Baseline re-measured at exactly 25,
name for name.

### For the Human, at `HV-PRES-ALERT-01`

- **Not runnable until Slice 11.** Nothing constructs `PresentationAttentionService` or
  `PresentationSpeculativeService` outside tests; the card and cue can fire only on a trace kind
  nothing in the product emits. Confirmed independently three times.
- **The cue is one they already know, deliberately.** No second emitter was added, because two
  emitters means two sounds for one event. A contradiction plays the existing *failure* variant —
  two quiet descending sine notes. **Ask whether a contradiction should be audibly distinguishable
  from "an agent crashed"**; today it is not, and it is a one-line change. Left untouched on
  purpose, pending that answer.
- **The check splits.** Discretion is validatable at Slice 11; "provides enough evidence to act"
  needs Slice 10's addressed turn.

### Carried forward

- **Slice 10** inherits a precondition: `reason` is the one field that can carry room speech, and
  it already propagates through `AttentionItem.to_payload()` → `PresentationWorkingSet.to_payload()`
  → `PresentationContextSnapshot.to_payload()`. Nothing production calls them today, so the
  constraint holds **by absence, not by construction**. `reason` may be read in-process for the
  addressed turn, **never through a snapshot serializer**.
- **Issue candidate**: `jarvis/domain/ambient_observation.py:316` hand-rolls the confidence range
  check despite already importing from `presentation_working_set`, where `check_confidence` lives.
  Adjacent, cheap, not this slice's to fix.

---

## 2026-09-24 — Slice 10, the priority addressed turn

Two new modules, one new suite (113 tests), one new contract page, plus one
optional parameter on `LatencyTracker.mark`. No wiring, by design, like 05, 06,
08 and 09. No QA pass yet.

### D04 is structural here, not a stopwatch reading

`arm()` and `open()` are **synchronous**. A frame with no `await` cannot yield
the loop, so no ambient transcription, no speculative preparation and no queued
analysis can interleave between the trigger's frozen stamp and the context
snapshot. An AST test refuses an `await` in either method — a source-reading
test on the **absence** of a thing, the exception Slice 05 established.

Measured as well, against a backlog **confirmed saturated before and still
saturated after**: the ambient lane's segment queue at its bound with segments
already dropped, its transcriber blocked and never returning, and the
speculative pool full of jobs whose declared cost is two minutes each, none
finished. Admission lands in the low milliseconds.

And the limit is stated rather than glossed: `free_explicit_slots` is honest
about the speculative lane's table and is **not** evidence that the addressed
turn has capacity — that lives on `OwnedJobExecution._slots`, untouched here.
Slice 08's conflation is carried forward as a correction, in the module header,
the contract page and the report.

### D06 as a data dependency, on the read side

The referent of a deictic is always the tail's most recent utterance; a prepared
resource answers only if it is anchored to it; everything else is stale, and
stale means refresh, never show. The precedence cannot invert because both
halves compare on one scale — the rank the **store** assigns — and a record can
only cite a rank that already exists. Slice 04 established that shape and
Slice 06 was made to write it correctly; this is the same argument applied to
reading.

The test that proves it reaches the worst case for the rule: the cached resource
is `HOT`, live, anchored to a topic still present — everything that would make
showing it tempting — while enrichment is three utterances behind.

### The Slice 09 precondition, closed by construction

`reason` is the one field that can carry room speech, and it propagated through
three `to_payload()` serializers that nothing called. This slice is the one that
wanted it. It reads `reason` **off the object**, the projection has two exits
named differently (`to_brain_context()` carries speech to the model;
`to_trace_payload()` carries counts to the journal), and an AST test forbids any
`to_payload` call in either Slice-10 module. The counters' own serializer was
renamed `to_trace_payload` so the guard needs no exception — a guard with an
exception is a guard that gets widened.

### A sixth way a mutation harness can lie

The harness printed `git diff --stat` for every mutation, as the LOG now
requires — and the first round's diff said **nothing about the new files**,
because they were untracked. A diff that cannot see the files being mutated is
exactly the shape of the previous five: a state reported without being checked.
`git add -N` on new files before trusting the diff. Any slice that adds files
must do this.

### The seventh occurrence of the recurring pattern, found by mutation

Three round-1 survivors, all three test defects, all three the same shape — *a
test that exercises a guard's code without ever reaching the state the guard
exists for*:

- the "freshest anchored resource wins" test had **one** candidate in the pool,
  because direct anchoring filtered the other out, so the ranking code was never
  consulted and inverting the sort survived;
- the projection test asserted the tail was bounded to eight and never *which*
  eight — the eight **oldest** utterances is precisely the stale context D06
  forbids, and it counts the same;
- the missing-stager test read a `warning` line the mutation left intact, so a
  fall-through into the reveal branch (an `AttributeError` wearing the same
  refusal's clothes) passed.

Also caught by hand before any mutation, and worth recording because it is the
same pattern found by reading: the `authorizes_actions` guard on the trigger was
tested with an object that was not an `ExplicitAddressTrigger`, so the type
check one line above refused it and the guard was never reached. It now uses a
subclass that *is* one and claims to authorize — the shape a transport
rebuilding the object would have.

Rounds 2 and 3: 33 mutations, zero survivors besides the deliberate control.

### Both source-reading guards probed, applied **and** selected

An `await` dropped into `open()` failed the D04 guard by name; a `to_payload()`
call dropped into the projection failed the serializer guard by name and printed
the offending line. `git diff --stat` printed with each probe applied, tree
verified restored after.

### Two small decisions worth carrying

- **`LatencyTracker.mark(..., at=)`** rather than a second stopwatch. The
  addressed turn's start is an instant already stamped and frozen by Slice 05;
  without the parameter this slice would have kept its own clock, which is two
  mechanisms for one question. Default behaviour unchanged, pinned by a test.
  The three new measure names live in the slice's own module and deliberately
  **not** in `LATENCY_MEASURES`, which the testlab consumes and a test pins at
  six.
- **The latency telemetry says what it measures.** Admission is in-process work
  with no IO. "Visible" ends when the call that asked for the change returns,
  not when a pixel moves. "Audible" ends where Slice 11 decides, and the number
  means something different under each choice — so Slice 11 must write the
  choice down. When the service's clock is behind the trigger's stamp it reports
  `None` and counts the mismatch: `None` says *we do not know*, a zero would say
  *we know it was instant*.

### State

**113 tests** in the new suite. **1 036 tests** re-run across the presentation,
ambient, speculative, attention, speech-scheduler, admission, brain-context,
architecture, latency-telemetry, testlab-bundle, interaction-mode and
documented-routes suites — zero failures, zero moved, zero deleted. The 25
stable baseline failures are in Scene, Bare Hands and `test_brain_delegation.py`,
none of which this slice imports.

### Carried forward

- **Slice 11** inherits the wiring list in the slice REPORT §9, including the
  one trap: the service's `clock` must be the **same** clock the
  `ExplicitAddressLane` stamps with, or the telemetry goes blank rather than
  wrong (it refuses to invent).
- **Slice 11** should hand `plan.situation` to
  `SpeechScheduler.note_addressed_turn` instead of letting the gate re-classify.
  One call, one truth.
- **A stated gap, not a defect:** a *named* visual command ("montre-moi le bilan
  Q3") is not matched to a prepared resource here — `NOT_REQUESTED` says so, and
  it goes to the brain with the projection. A lexical name-matcher would be the
  second classifier this handoff has spent three slices removing.
- **`HV-PRES-PRIORITY-01` is not reachable until Slice 11**, and it is also the
  second half of `HV-PRES-ALERT-01` — "then optionally ask Jarvis what it found"
  needs the addressed turn live and projecting `reason`, which it now does.

### Reprise — quatre défauts bloquants, douze points

**B1 montrait l'écran du sujet précédent, dans le cas ordinaire.** La règle
d'ancrage par sujet retenait *n'importe quel sujet vivant* :

```text
u-001 « regardons le bilan Q3 »      -> sujet t-bilan, ressource r-bilan préparée
u-002 « parlons de la trésorerie »   -> sujet t-treso committé
« montre-moi ça »                    -> r-bilan, révélé
```

L'enrichissement est **à jour** dans cette trace — retard nul, `observed_sequence`
au rang du référent — donc aucune garde de fraîcheur ne pouvait l'attraper. Et
ce n'est pas un coin : l'analyse produit un sujet pour une énonciation neuve bien
avant qu'une *ressource* existe pour elle, donc toute commande déictique lancée
dans cette fenêtre montrait le sujet d'avant. « Montrer le mauvais item »,
atteint par la seule direction que mes gardes ne surveillaient pas.

La règle est maintenant **au référent** : un sujet lui appartient quand un
enregistrement qui le nomme cite une énonciation de rang au moins égal au sien.
Une ressource n'y contribue pas — elle se porterait caution à elle-même. Le coût
est assumé et épinglé par un test : un sujet seulement **re-mentionné** garde le
rang de sa première mention (la Slice 04 ne réécrit jamais une provenance) et
fait donc rafraîchir. Une réutilisation perdue, jamais un mauvais écran.

**B2 — j'ai généralisé une phrase de ce LOG que j'avais écrite moi-même.** À la
Slice 06 j'ai noté, avec raison, que D06 tient par une dépendance de données :
l'enfilement a besoin d'un rang que seul le magasin peut attribuer. C'est vrai
**de l'ordonnancement de la lane ambiante**. Mon en-tête, la page contractuelle
et le rapport en ont fait une propriété du **magasin**, que le magasin ne tenait
pas : `apply()` recopiait `provenance.sequence` sans contrôle. Un enregistrement
citant le rang 54 contre un fil s'arrêtant à 4 était accepté, `observed_sequence`
passait à 54, et ma garde D06 était **morte** ensuite. L'invariant ne survivait
que parce que deux producteurs relisent le rang — de la discipline, pas une
dépendance.

Une phrase vraie d'un composant, promue en propriété du système sans qu'on
demande au système.

C'est une propriété du magasin maintenant : `apply()` borne à
`assigned_sequence` et **journalise** le rabotage ; `cited_rank` referme du côté
lecture. **Refuser** a été implémenté et mesuré d'abord : 118 tests cassés dans
les Slices 04, 08 et 09, qui construisent légitimement des provenances à la
main. D'où le rabotage — l'enregistrement a bien été dit, seule sa prétention de
fraîcheur est fausse. Résiduel écrit : on ramène au plafond, pas à la vérité.

**B3 — la preuve de tête ne citait aucun symbole de la Slice.** Elle conduisait
le magasin par le helper de test, lequel relisait le rang depuis le fil, puis
affirmait une propriété de ce helper. Elle ne pouvait échouer pour **aucune**
implémentation. Réécrite pour conduire le service et pour inclure le rang gonflé.

**B4 — l'échappatoire écrite dans trois documents était fausse.** « Le cerveau
reçoit de toute façon la projection » : la projection ne portait aucune ressource
préparée. Donc une demande nommée ne réutilisait rien **et** le cerveau ignorait
que le matériel existait. Section `prepared_resources` bornée, `discardable`
exclues, références seulement.

### Le motif, pour la huitième fois, et trois fois d'un coup

B1, B2 et B3 sont la même forme : **l'état discriminant n'était jamais
construit**. Les tests du chemin 4b gardaient tous un seul sujet d'un bout à
l'autre ; l'invariant de rang n'était jamais attaqué avec un rang forgé ; le
test de précédence ne touchait pas la Slice. Chacun est désormais réparé en
construisant l'état **d'abord**, puis en mutant.

Deux autres points de la reprise sont le même motif : le test « retirée par le
magasin » n'atteignait le filtre de lecture ni par le magasin ni par un
paramètre — la ressource avait déjà quitté l'instantané —, et
`counters.context_failures` ne pouvait être bougé par rien dans 2 522 lignes de
suite. Le premier est remplacé par un test de **lecture scindée**, qui est l'état
qu'un relais inter-processus produit vraiment ; le second par un magasin qui rend
une séance liée sans rendre un instantané typé.

### La septième façon dont un harnais ment, adoptée de QA

Après le premier commit, ces sources sont en **CRLF** et le magasin de la
Slice 04 est en **LF**. Un harnais qui lit en `read_text` et écrit en
`write_text` produit un diff de fichier entier qui noie le vrai changement ; un
harnais qui colle une ancre multi-ligne en LF ne trouve **rien**. Les deux ont
été rencontrés. `s10_mutate2.py` lit et écrit en **octets**, colle chaque ancre
avec la fin de ligne **du fichier visé**, et rend `ANCRE (n) — NON APPLIQUÉE`
plutôt qu'un faux survivant. La même garde a sauvé les scripts de correctif :
elle s'est arrêtée **avant** d'écrire, donc sans laisser un fichier à moitié
corrigé.

La sixième, trouvée à la première passe, reste : `git diff --stat` ne voit pas un
fichier non suivi, donc `git add -N` avant de croire son propre diff.

### La télémétrie échouait *faux*, pas *blanc*

Ma garde d'horloge était à sens unique. En arrière : pas de mesure, et c'est dit.
En **avant** : +0,5 s rendait `502.0 ms` sans le moindre signal, et au-delà de la
fenêtre **tous** les tours mouraient en `addressed_window_expired` — la
fonctionnalité éteinte sous un code qui accuse l'utilisateur d'avoir parlé trop
tard. Les deux directions sont gardées, le refus est nommé pour ce qu'il est, et
le résiduel est écrit : sous le plafond, une dérive et une attente en file sont
**indiscernables**, donc l'avertissement de retard nomme les deux causes au lieu
d'affirmer celle qui se lit mieux.

### État après reprise

**138 tests** dans la suite (contre 113). **47 mutations, 46 attrapées, zéro
survivant** hors contrôle cosmétique — quatorze mutations neuves visent la
reprise elle-même. **1 160 tests** rejoués sur les surfaces touchées, zéro échec ;
la suite de l'ensemble de travail et celles des voies spéculative, attention et
ambiante comptent plus qu'avant, puisque la reprise modifie le magasin de la
Slice 04. Les deux gardes de lecture de source ont été re-sondées après
réécriture : elles échouent par leur nom, et l'arbre a été vérifié restauré.

### Reporté à la Slice 11, en plus

- **Ajouter le site `SpeechRequest` de cette voie à la garde AST de la Slice 07.**
  La page affirmait que la garde « l'énumère déjà » : c'est faux, elle parcourt
  les sites de **construction** et cette Slice n'en construit aucun. La nature
  est décidée ici, la requête est bâtie là-bas.
- Le plafond de rang que la reprise installe est celui dont le troisième chemin
  d'écriture hérite.


---

## 2026-09-24 — Slice 10, priority addressed turns

`163c409` + rework `640589a`. An explicit command is immediate while ambient work is behind,
resolves deictic references against the freshest speech, and reuses prepared material. Two QA
passes.

### D04 proven structurally rather than by stopwatch

`arm()` and `open()` are synchronous with zero awaits, so the admission frame **cannot** yield the
event loop, and an AST guard refuses one being added — QA planted `async def open` plus an `await`
and it failed by name. A latency number says "it was fast on this run"; an await-free frame says
"it cannot be slow for this reason". QA then measured **3.6 ms** anyway, with its own harness,
against a backlog confirmed saturated before *and after* — and its own `perf_counter` agreed with
the service's number, so the measure is not self-flattering.

### Four blocking defects, three of them one shape

1. **A deictic command revealed the previous subject's screen — in the ordinary race, not a corner.**
   Rule 4b matched *any* live topic rather than the referent's. QA reproduced it end to end with no
   forging: "regardons le bilan Q3" → "parlons de la trésorerie" → "montre-moi ça" shows the **Q3
   curve**. The enricher commits a topic for the new utterance long before a *resource* exists for
   it, so every deictic command in that window shows the previous subject — with enrichment fully
   **current**, so the staleness gate cannot fire. Showing the wrong item, arriving from the one
   direction this slice's gates did not watch.
2. **"A data dependency, not a convention" was false.** `apply()` computed
   `max(existing, provenance.sequence)` with no validation against the tail. QA applied a record
   citing rank 54 against a tail whose maximum was 4: accepted, `observed_sequence` became 54, and
   the D06 gate was **dead thereafter**.
3. **The test carrying that headline claim referenced no Slice 10 symbol**, driving the store
   through the test's own helper and asserting a property of the helper.
4. **A named visual command neither reused the resource nor told the brain it existed** —
   `working_set.resources` was never projected, while three documents said the brain "receives the
   whole projection anyway".

**One, two and three are the same shape: the discriminating state was never constructed.** Eighth
occurrence in this task.

### Agent 0's own record was wrong, and this is the correction

At Slice 06 I wrote approvingly that D06 holds by a **data dependency** — the enqueue needs a rank
that does not exist until the store assigns it. That is true **of the ambient lane's ordering**, and
it was the right finding there. Slice 10's header, contract page §4 and report generalised it into
a **store-level invariant the store does not hold**, and I did not catch it until QA applied a
forged rank.

A true statement about one component, promoted to a property of the system, without the system
being asked — and I helped it along by recording the narrow version in language broad enough to be
reused. The restatement now names the writers that maintain it.

### The rework's best decision was to try the strict fix and measure it

The obvious repair for (2) is to **refuse** an out-of-range rank. The implementer implemented that
first and measured the blast radius: **118 broken tests** across Slices 04, 08 and 09, which
legitimately construct provenance by hand. So `apply()` now **clamps** to a new observable
`assigned_sequence` and **journals the clamp at `warning`**, with `cited_rank()` re-bounding on
read — and the residual is stated rather than hidden: *clamping pulls a forged rank to the ceiling,
not to the truth.*

A subtlety worth keeping: `assigned_sequence` is deliberately **not** `tail.latest_sequence`,
because the tail evicts — clamping to the tail's current maximum would be wrong once entries age
out.

For (1), `referent_topic_ids()` now requires a record naming the topic to cite an utterance of at
least the referent's rank. A topic, entity, claim or question qualifies; **a resource does not**,
since it would vouch for itself. The accepted cost is stated and pinned by its own test: a merely
*re-mentioned* topic keeps its first mention's rank, because Slice 04 never rewrites provenance, so
it refreshes instead of reusing. **A lost reuse, never a wrong screen** — the right direction to
fail in.

### Telemetry failed wrong, not blank

The clock guard was one-sided. QA measured both directions with independent fixed clocks: behind →
`None` plus a named mismatch ✔; **ahead +0.5 s → a plausible `502.0 ms` with zero signal**; ahead
+5 s → a *misleading* `addressed_trigger_stale` reading as "served late"; **ahead +300 s → every
addressed turn refused**. So a forward skew killed the feature, not just the measure. Now refused at
`arm()` under its own `addressed_trigger_clock_skew`, with the residual stated: below the ceiling,
skew and queueing are indistinguishable, so the stale warning names both causes.

### A seventh way a mutation harness lies

These sources are **CRLF** while Slice 04's store is LF. A harness reading with `read_text` and
writing with `write_text` produces a 777-line whole-file diff that **hides the real change in
noise**; one matching a multi-line anchor read with `read_bytes` silently matches **nothing**. QA
hit both; its anchor guard caught the second by reporting `ANCRE (0) – NON APPLIQUEE` rather than a
false survivor. The implementer's harness now reads and writes bytes and joins anchors with *that
file's* EOL — and the same guard aborted **before writing** on a later patch, so no half-patched
file was produced.

That makes seven catalogued, all the same shape: **the harness reported a state it had not
checked.** Including `git diff --stat`, the check added to catch that shape, which is silent on
untracked new files (the sixth, found by this same implementer).

### Final state

**643 passed** across the addressed-turn, working-set, speculative, attention, ambient,
response-policy, architecture and latency suites, re-run by agent 0. 138 tests in the slice, up
from 113. 47 mutations, zero survivors besides the control. Both AST guards re-probed after the
rewrite and confirmed failing by name.

### Carried forward to Slice 11

- This slice constructs **no** `SpeechRequest`, so when Slice 11 builds the clarification request
  its site must be added to Slice 07's `SPEECH_KIND_SITES` table — otherwise the AST guard that
  keeps the model from naming its own speech kind will not cover it.
- The wiring trap: the service's `clock` must be the same clock `ExplicitAddressLane` stamps with.
  A backward skew now reports blank; a forward skew is refused by name.
- `OwnedJobExecution._slots` remains `Semaphore(1)`. Nothing in this slice claims an addressed turn
  cannot queue behind an earlier one, and nothing should.
