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
