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

`docs/02-architecture.md` asks for a `PresentationAttention` carrying category,
severity, confidence, source references, the related topic/claim and
prepared-resource references. `AttentionItem` has no resource references — they
were removed as dead in Slice 04's rework — so the event carries them and the
stored record does not. That is the difference between *what is kept* and *what
is signalled*.

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
acknowledged through the existing door. The working set lives in another
process and the Control Center has no path to it: this is an absence of an edge,
not a discipline.

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

Two rules are its own, both measured:

- below **760 px** a 44 px bottom margin lifts the whole stack above the centred
  voice hint, which already overlaps the toast rail at that width;
- below **700 px** the mode control leaves the left rail for `left:84px` and
  occupies the band 84 to 144 above the bottom — the same band the lifted card
  occupies. Measured overlap: **119x31 at 500x700**, with the card at rank 70
  against the control's 32, so the mode button became unclickable. The card
  therefore narrows and right-aligns
  (`width: max(156px, calc(100vw - 348px))`), the same horizontal escape the
  mode control itself took.

Below roughly 420 px this page's bottom is contended long before this slice:
the toasts already cover the voice hint, the pills and the dock. The card
inherits those conflicts rather than adding new ones.

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
| `presentation.speculative.assessment_refused` | `warning` | a verdict from a job whose grant does not open verification |
| `presentation.speculative.attention_unavailable` | `warning` | a verdict arrived with no judge wired |
| `presentation.speculative.attention_failed` | `error` | the judge raised; the lane stays open |

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
- **No production wiring.** `PresentationAttentionService` has no composition
  root, exactly like the audio session (05), the ambient lane (06) and the
  speculative runner (08). **Slice 11 must wire it**, and `HV-PRES-ALERT-01`
  is not reachable until it does.
- **No reveal policy.** `PresentationSpeculativeService.reveal()` exists; the
  warning does not call it. Opening a card shows the *sources*; revealing a
  staged scene object is Slice 10's decision.
- **No second sound.** `bgCue` is the one emitter and stays so.
