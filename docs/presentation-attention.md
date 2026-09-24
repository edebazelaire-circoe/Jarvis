# Presentation fact-check attention

Contract page for the Presentation attention path: what may become an alert,
what may never become one, how the alert reaches the screen, and how exactly one
discreet sound is produced for it.

Locked decision **D11**: *a meaningful contradiction/mismatch creates a small
audible cue and a floating warning/attention indicator. Jarvis does not
spontaneously explain aloud.*

Modules:

| Layer | Module |
| --- | --- |
| Vocabulary and the gate (pure) | `jarvis/domain/presentation_attention.py` |
| The service that judges, stores and journals | `jarvis/core/presentation_attention.py` |
| The lane that feeds it verdicts | `jarvis/core/presentation_speculative.py` |
| Classification and payload for the UI | `jarvis/runtime/background_events.py` |
| The floating warning and the sound arbiter | `jarvis/runtime/control_center_presentation_attention.js` |

## 1. What is reused, and what is new

Nothing here re-declares what earlier slices already own.

- `AttentionCategory` / `AttentionSeverity` / `AttentionItem` — declared by
  Slice 04 in `presentation_working_set.py`. Extended, never duplicated.
- `ClaimStatus` — Slice 04's verification state, reused as the verdict
  vocabulary. `UNCERTAIN` already means *checked without concluding*, which is
  precisely the value that stops a failed search becoming an alert.
- `BackgroundEventLedger`, `GET /api/background`, `POST /api/background/ack`,
  `#bgPills` and its popover — the background-event system. D12 says reuse it.
- **`bgCue()`** — the discreet sound. It already existed, it already plays only
  on a *rise* of the ledger sequence, and it already never plays on the first
  poll. No second sound was added: two sounds for one event is what D11 forbids.
- Slice 08's lane, its capability table and its normalisation path.

New: `AttentionEvidence`, `FactCheckAssessment`, `PresentationAttention`,
`decide_attention`, `PresentationAttentionService`, one trace kind, one status
field, and one page module.

## 2. The typed event

`tasks/jarvis-presentation-interaction-mode/docs/02-architecture.md` asks for a
`PresentationAttention` carrying category, severity, confidence, source
references, the related topic/claim and prepared-resource references. (That page
lives under the handoff folder, not `docs/` — the neighbouring contract pages
cite it at the wrong path, which is pre-existing drift reported by Slice 08 and
still open repo-wide.)

**It does not carry resource references, and that is deliberate.** A first
version did: declared, validated, bounded, carried all the way to the browser —
and read by nothing. Slice 04 had already removed the same field from
`AttentionItem` for the same reason. Dead wiring starts lying the moment someone
believes it is connected. It returns when a consumer exists, which is when
Slice 10 decides on a `reveal()`; until then each piece of evidence carries its
own `resource_id`, which is enough to find the resource behind a source.

```
PresentationAttention(attention_id, category, severity, confidence, raised_at,
                      claim_id, topic_id, evidence, resource_ids, reason)
  .to_item()          -> the Slice 04 AttentionItem (carries `reason`)
  .to_trace_payload() -> references and numbers only (no `reason`)
  .dedup_key          -> (category, claim_id, topic_id), the store's own key
  authorizes_actions  : ClassVar[bool] = False
  requests_speech     : ClassVar[bool] = False
```

The producer names neither the category nor the severity. The category comes
from `ALERTING_VERDICTS`, the severity from `severity_for(confidence)`. This is
Slice 07's rule applied again: a label a producer can write is a ceiling a
producer can lift.

## 3. Evidence and confidence rules

`decide_attention` is pure, never raises, and returns a typed `AttentionDecision`
that is either raised or refused with a named `AttentionRefusal`. The order is
part of the contract, because the first refusal is the one that gets journalled:

| # | Check | Refusal |
| --- | --- | --- |
| 1 | the input is a `FactCheckAssessment` | `attention_assessment_invalid` |
| 2 | the job's grant holds `FACT_VERIFICATION` | `attention_capability_missing` |
| 3 | `searched is True` | `attention_search_failed` |
| 4 | the verdict is in `ALERTING_VERDICTS` | `attention_not_alerting` |
| 5 | at least one piece of evidence, each with a locator | `attention_no_evidence` |
| 6 | the claim exists in the working set | `attention_claim_unknown` |
| 7 | at least one piece names a source the working set holds | `attention_provenance_unknown` |
| 8 | `confidence >= MIN_ATTENTION_CONFIDENCE` (0.6) | `attention_low_confidence` |
| 9 | the event is constructible | `attention_not_constructible` |

**A search failure or absence is never a contradiction**, and the rule has two
halves because a runner can be wrong in both directions:

- `searched=False` is refused at step 3, *before the verdict is read*. A runner
  returning `CONTRADICTED` on a failed search is therefore refused, not promoted.
- `ClaimStatus.UNCERTAIN` and `SUPPORTED` are not in `ALERTING_VERDICTS`, and
  `_check_alerting_table()` enumerates the values the table must **not** hold,
  at import. It meets the state it forbids on every call, which is the fix for
  the pattern this handoff catalogued three times.

**Provenance is verified, not declared.** Steps 6 and 7 resolve the claim and
at least one source against the live working set. A runner that invents a source
passes every other check and fails this one.

**One decider, not two.** The speculative lane is the only place that knows the
job's token, so it reads it — and then *passes the value*, instead of deriving
its own refusal. A first version decided the capability on both sides and then
handed the judge a hard-coded `True`, which made step 2 and
`attention_capability_missing` unreachable outside tests. The lane now counts the
refusal by reading the decisions it gets back.

Step 5 no longer tests each piece for a locator: `AttentionEvidence` already
refuses an empty one through `safe_reference_text(required=True)`, so that half
of the condition could never be true and only gave a reader a guard to
misplace their trust in.

**The thresholds are caution, not measurement.**
`docs/presentation-ambient-lane.md` section 11 records that the four trigger
confidences are hard-coded and uncalibrated. `MIN_ATTENTION_CONFIDENCE = 0.6`
and `HIGH_CONFIDENCE = 0.8` inherit that uncertainty, so the surface shows a
**band** (`confiance elevee` / `confiance moyenne`) and never a number. Showing
`0,72` would lend an arbitrary figure the authority of a measurement.

In V1 the image of `ALERTING_VERDICTS` is exactly `{CONTRADICTION}`. `MISMATCH`,
`MISSING_SOURCE` and `STALE_RESOURCE` remain declared by Slice 04 and are
**unreachable from this door**, for want of a verdict that names them. Saying so
is better than letting a reader believe otherwise.

## 3b. "It never raises" is a promise, so it is a test

`decide_attention` and every public method of `PresentationAttentionService`
return typed values and never raise — the same discipline as Slice 04's store,
for the same reason: an exception is caught and lost, a value is counted.

That promise was stated three times and true only once. The id collections were
turned into sets **outside** the guard, so `set(None)` raised a bare `TypeError`;
`list(assessments)`, `store.apply(...)` and the injected clock were unguarded.
None of it was a live crash path — the only production caller wraps everything —
which is exactly why it mattered: a promise nobody exercises is a promise the
next caller will believe.

Each is now guarded and each has a test that reaches it: a non-iterable snapshot,
a non-iterable batch, a store that raises rather than refuses, a clock that
raises, and an identifier the event cannot be built from
(`attention_not_constructible`, which nothing in the repository reached before).

A `str` passed as an id collection is refused too. It is iterable, so `set()`
would have accepted it and produced a set of **letters** — turning a caller's
mistake into a perfectly plausible and perfectly wrong `attention_claim_unknown`.

## 4. Nothing here can ask to speak

D11 holds at three levels, deliberately:

1. **the matrix** — `may_speak(FACT_CHECK_ATTENTION, k)` is `False` for every
   `SpeechKind`, because the row carries `requires_explicit_address=False` and
   no `safety_speech_kinds`. The module reads that row through
   `attention_output_policy()` instead of restating the rule;
2. **the type** — `PresentationAttention` has no speech field, and its two
   `ClassVar` flags cannot be turned by `dataclasses.replace`;
3. **the import closure** — `ALLOWED_IMPORT_CLOSURE` is an equality allowlist.
   The honest sentence is not "no edge to anything that speaks": the speech
   *vocabulary* is in the closure, through `presentation_policy`, and that is
   wanted — it is what makes D11 readable from here. What the guard holds is
   that no speech **producer** enters, and no `jarvis.core.*` beyond this module.

## 5. Room speech never reaches the trace

`reason` is speech-derived: Slice 04 validates it with `bounded_text`, not
`safe_reference_text`, precisely because *la marge < 10 %* is an ordinary French
sentence. It is kept in the working set, in memory, for Slice 10's addressed
turn — which is literally `HV-PRES-ALERT-01`'s script, *"then optionally ask
Jarvis what it found."*

It does **not** enter `to_trace_payload()`. `trace.jsonl` is durable and shared
by three processes, and Slices 04, 06 and 08 all set the same rule: identifiers,
numbers, codes, never speech. Everything that does cross is validated by
`safe_reference_text` — the locator and title rule.

The consequence is a deliberate design choice, and the place where this slice
diverges from a hint left by Slice 04 (*"`MAX_ATTENTION_REASON_CHARS = 160`, one
line for Slice 09's floating warning"*): **the warning is composed in the
browser from typed data**, not from a copied sentence. It names the nature of
the doubt, how confident the check was as a band, and *where the evidence is* —
source titles and links, which come from the fetched source and not from the
room. What Jarvis understood is asked for; D11 says he does not volunteer it.

## 6. The three deduplications, and which layer holds which

They sit at three different levels, and knowing which holds what is what stops a
fourth being added out of caution.

| Case | Held by | Where |
| --- | --- | --- |
| **the same contradiction twice** | the Slice 04 store, coalescing on `(category, claim_id, topic_id)` | `jarvis/core/presentation_working_set.py` |
| **a burst of distinct contradictions** | `MAX_ATTENTION_PER_BATCH = 2` — a burst of verdicts must not become a burst of sounds | `jarvis/core/presentation_attention.py` |
| **polling** (the same tab re-reads the status every second) | the existing rise rule, `seq > BG.seq` | `control_center.html`, pre-existing |
| **reload** (F5, or a reopened tab) | `BG.armed`, which refuses the first poll where everything is new by construction; plus the shared high-water mark, which survives the page | pre-existing, plus this slice |
| **several tabs or windows** | a leader lease plus a shared high-water mark in `localStorage` | `control_center_presentation_attention.js`, new |

The semantic one comes first and matters most: a coalesced attention item posts
**no trace line**, so the ledger sequence does not rise, so nothing sounds.

`claimCue(seq)` is the gate, and it *consumes* the sequence number: calling it
twice for the same `seq` returns `false` the second time.

**What the arbitration does not guarantee.** `localStorage` offers no atomic
compare-and-swap. The lease makes the race window tiny — a tab that is not the
leader gives up without writing — and the high-water mark catches the ordinary
case where two tabs notice the rise a few hundred milliseconds apart. Two tabs
reading the mark in the *same* event-loop turn before either writes could both
sound. That is a very strong reduction, not a proof.

With no usable `localStorage` — private window, blocked storage — the gate
**opens**. One sound too many is a minor defect; silence where D11 asks for a
signal is the defect this exists to prevent.

## 7. Dismissal never touches the facts

Dismissing a card is local UI state, persisted in `localStorage` (bounded at 32
identifiers). It issues **no network call at all** — not even the existing
acknowledgement route, which acknowledges a whole category and would sweep away
unrelated attention events.

The event stays counted in the "points a verifier" pill, where it is
acknowledged through the existing door — so that pill must stay clickable, which
is a geometric obligation, not a decorative one (section 8).

**Dismissal is per tab.** The dismissed list is read once at install and there is
no `storage` listener, so dismissing in one window leaves the card standing in
another until it reloads. That is consistent with "UI state only" and it is the
cheap behaviour, but it is worth saying plainly because the **cue** is
deliberately cross-tab: the sound is arbitrated between windows, the card is not.

Escape dismisses too, in two steps — it closes an open detail first, then
dismisses. The handler sits on the card, not on the document, and stops
propagation only once it has acted, so it never competes with the page's own
global Escape handler for the pill popover.

Evidence links open in a new tab (`target="_blank"`, `rel="noreferrer noopener"`).
Opening a tab mid-presentation is disruptive; navigating the Control Center
itself away from a live session is worse, and those are the only two options a
link has. Stated as a judgement rather than left as an accident.

## 8. Where the warning is placed, and why

The bottom-left rail is contended — `.jh-badge`, `.jh-note`, `.sc-status` and
Slice 03's mode control — and Slice 03 wrote that a third rung there belongs to
no single occupant. All four anchors were measured in a real browser at seven
sizes and **no corner is free at every size**.

So the card joins the only floating surface this page already has: `#toasts`.
It enters as an ordinary child with `order:1`, which keeps it the lowest card —
closest to the corner, always visible — whatever toast is appended after it. It
inherits the rail's width, its open-panel dodge
(`#app:has(.panel.open)~.toasts`) and its reduced-motion rule without a single
shared rule being touched.

Three rules are its own, all measured, and two of them are corrections:

- **a 44 px bottom margin, unconditional**, lifting the stack above the centred
  voice hint. A first version applied it only below 760 px and left a 48x32
  overlap at 820x900 — a size that *was* measured, but sat just above the
  threshold — and 162x32 at 1440x900 with the panel open, where the rail shifts
  left onto the centred hint. The card blocks no click there
  (`.voicehint` is `pointer-events:none`) but it persistently hides the page's
  voice affordance. A threshold that is wrong in one case will be wrong in
  another, so there is no threshold;
- **a 52 px right margin**, clearing the background pill column. The pills follow
  the viewport **centre** (`top:calc(50% + 193px)`) while this rail is anchored
  to the **bottom**, so on a short viewport they descend into it. Measured with
  `elementFromPoint`: at 1440x520 and 360x640 the card received the click meant
  for the pill, at 700x600 its chevron did. That pill is the acknowledgement
  door for the very warning the card shows, and unlike a toast, which clears
  after five seconds, the card persists until dismissed;
- below **700 px** the mode control leaves the left rail for `left:84px` and
  occupies the band 84 to 144 above the bottom — the band the lifted card
  occupied. Measured overlap: **119x31 at 500x700**, card at rank 70 against the
  control's 32, so the mode button became unclickable. The escape here is
  **vertical**: a 136 px bottom margin puts the card above that band. Narrowing
  worked at 500 px and failed at 360, where the card fell back onto the control;
  going above is independent of width and clears the pills, the dock and the
  voice hint at the same time. The price is 136 px of empty space below the
  stack on a small screen, and it is the right price.

**The measurement set now includes a short-and-wide viewport permanently.** The
original set — 1440x900, 1024x768, 820x900, 700x600, 500x700, 360x640 — had no
short-and-wide shape, which is the only one that brings the pills down into the
toast band. Six sizes was not the problem; the hole in the set was.

Rank: the card is a child of a ranked rail, so it declares no `z-index` of its
own — the same reasoning Slice 03 documented for its host.

## 9. Journal

`presentation.attention.*`, sharing the shape of `presentation.working_set.*`
and `presentation.speculative.*`.

| Event | Level | When |
| --- | --- | --- |
| `presentation.attention.raised` | `warning` | an alert is raised **and stored**. The only line the ledger classifies. |
| `presentation.attention.not_raised` | `info` | the gate refused; carries the refusal code and the verdict. A verdict that does not deserve an alert is the ordinary case, not an anomaly. |
| `presentation.attention.coalesced` | `info` | the same contradiction, already signalled |
| `presentation.attention.store_refused` | `warning` | the working set refused it, so nothing is signalled |
| `presentation.attention.batch_clipped` | `warning` | more verdicts in one batch than `MAX_ATTENTION_PER_BATCH` |
| `presentation.attention.observation_refused` | `error` | the record could not even be observed |
| `presentation.attention.store_failed` | `error` | the store **raised** instead of refusing; nothing is signalled |
| `presentation.attention.batch_invalid` | `error` | the batch was not iterable |
| `presentation.speculative.assessment_refused` | `warning` | a verdict from a job whose grant does not open verification |
| `presentation.speculative.attention_unavailable` | `warning` | a verdict arrived with no judge wired |
| `presentation.speculative.attention_failed` | `error` | the judge raised; the lane stays open, counted under `attention_failures` and not the generic `failed` |

**Nothing is signalled that is not stored.** The trace line is posted only after
`store.apply` returns `applied`, so a warning the user hears is always a warning
Slice 10 could explain if asked.

## 9b. What the page is given

`GET /api/status` carries the typed payload of the **unread** attention events
inside its existing `background` block, newest first, bounded to three. The page
therefore opens no second heartbeat: it already polls this route once a second,
and G6 records that this page has no generic push seam to reuse.

The key is **absent when there is nothing to show**, not present and empty. That
block goes out every second and the ordinary second has no attention at all, so
the payload stays byte-identical for every existing consumer — an equality that
`test_brain_delegation.py` already pinned. A older server then reads exactly
like a server with nothing to signal, which the page treats the same way.

Everything crossing is re-clipped on arrival by `_attention_payload`: the trace
is a file three processes write and a human can edit, so nothing out of it is
taken on trust. A malformed line yields a poor event, still counted in the pill,
never an exception that would empty the badge for the whole session.

## 10. Not in scope

- **No user preferences.** Out of scope per `SLICE.md`.
- **Wired in Slice 11**, as `PresentationSpeculativeService(attention=...)`
  inside `jarvis/runtime/presentation_runtime.py`. `HV-PRES-ALERT-01` is
  reachable from there and is still a human check.

  One thing had to be built for this page to be true end to end. §5 refuses a
  verdict whose evidence names a source the working set does not hold —
  *"a runner that invents a source does not pass"* — and **nothing in the
  repository constructed a `PresentationSource`**. The set of known sources was
  therefore always empty, so every verdict would have been refused as
  `attention_provenance_unknown`, and no test saw it because nothing joined the
  chain. The Slice 11 runner records the source it found **before** citing its
  identifier, so the provenance stays verified rather than declared, and the
  model never chooses an identifier at all.
- **No reveal policy.** `PresentationSpeculativeService.reveal()` exists; the
  warning does not call it. Opening a card shows the *sources*; revealing a
  staged scene object is Slice 10's decision.
- **No second sound.** `bgCue` is the one emitter and stays so.
