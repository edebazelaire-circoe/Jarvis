# Presentation addressed turn: immediate, fresh, and reusing what exists

Canonical contract for **Slice 10** of `jarvis-presentation-interaction-mode`.
Decisions **D04**, **D05**, **D06**, **D08**, **D09** and **D10** are locked and
this page is where they become code. Companion pages:
[presentation-audio-capture.md](presentation-audio-capture.md) (where the
trigger comes from), [presentation-working-set.md](presentation-working-set.md)
(what the turn reads),
[presentation-speculative-preparation.md](presentation-speculative-preparation.md)
(what it reuses or re-asks for),
[presentation-response-policy.md](presentation-response-policy.md) (what it is
allowed to say).

Implementation: `jarvis/domain/presentation_addressed_turn.py` (the window, the
precedence rule, the resolver, the projection — pure) and
`jarvis/core/presentation_addressed_turn.py` (the service).
Conformance: `tests/unit/test_presentation_addressed_turn.py`.

## 1. The chain

```text
ExplicitAddressTrigger            Slice 05, from the wake word or the manual key
   -> arm()                       synchronous: window bound, P0 slot freed, clock started
   -> AddressedWindow             pre-roll .. trigger .. max_wait; one window, one turn
   -> open()                      synchronous: one snapshot read, classify, resolve, project
        -> classify_addressed_situation   Slice 07, injected, never re-decided
        -> resolve_referent               the freshest utterance, always from the tail
        -> resolve_prepared_resource      anchored, or stale, or ambiguous
        -> build_addressed_turn_context   bounded projection, two named exits
   -> decide_action               show prepared | refresh | clarify | ask the brain
   -> deliver()                   asynchronous: reveal, warm, reserve, or nothing
   -> conclude()                  the session stays in ambient Presentation
```

Nothing on this path speaks by itself, opens a microphone, or calls a model.

## 2. Addressed-window binding

A trigger says *who* addressed Jarvis and *when*, on a monotonic clock frozen at
lane admission (Slice 05). The window says *which speech belongs to it*:

| Bound | Value | Why |
| --- | --- | --- |
| `opens_at_s` | `trigger.monotonic_s - DEFAULT_PREROLL_S` (1.5 s), never below 0 | the wake detector never fires on the first syllable; the phrase started before the stamp. This is the logical twin of Slice 05's PCM `CommandPreRoll` |
| `closes_at_s` | `trigger.monotonic_s + MAX_ADDRESSED_WINDOW_S` (12 s) | a command, plus a segment's transcription latency. Past it, what is heard belongs to the room, and treating room speech as addressed would hand an ordinary conversation the authority to act (**D03**) |

Three rules the window carries, each with its test:

- **one window serves one turn.** `open()` disarms. Otherwise a single key press
  would address two sentences, and nobody addressed the second one;
- **a second press replaces the window** rather than queueing behind it, and the
  replacement is counted (`rearmed`). A person who presses again is
  re-addressing, not stacking;
- **out of range fails safe.** `covers()` answers `False` and `expired()` answers
  `True` for anything that is not a finite number. Not addressing by mistake
  costs a repeated sentence; addressing by mistake costs an action nobody asked
  for.

A trigger delivered late (older than Slice 05's `MAX_TRIGGER_AGE_S`) is **still
armed**, counted (`stale_triggers`) and said at `warning`. That is Slice 05's own
rule — losing a user's press is worse than serving an old one — and the two
layers must not contradict each other.

## 3. D04: the admission cannot wait for ambient, structurally

`arm()` and `open()` are **synchronous**. Not "fast": synchronous. A function
with no `await` cannot yield the event loop, so no ambient transcription, no
speculative preparation and no queued analysis can interleave between the
trigger's stamp and the context snapshot. The guarantee is therefore checkable
without a stopwatch, and an AST test refuses an `await` in either method — a
source-reading test, justified on the spot, because no behavioural test proves
the *absence* of an await.

It is also measured, against an ambient backlog **confirmed saturated** and
still saturated after the measurement:

- the ambient lane's segment queue at its bound with segments already dropped;
- its transcriber blocked and never returning;
- the speculative pool full of jobs whose declared cost is two minutes each,
  none finished.

Under that, admission is measured in the low milliseconds.

### What this does *not* prove

`free_explicit_slots` is honest about the **speculative lane's** table and is
not evidence that an addressed turn has execution capacity: the addressed turn
runs on `OwnedJobExecution._slots`, an `asyncio.Semaphore(1)` that the
speculative lane cannot see and that this slice does not touch. Slice 08 was
corrected on exactly this conflation and the correction is carried here rather
than repeated.

What the service does for **D08** is named and bounded: it calls
`note_addressed_turn()`, which frees one slot in that lane by sacrificing
speculative work, lowest rank first. When the pool has room it sacrifices
nothing — D08 asks that explicit interaction pass, not that useful work be
thrown away for the ceremony.

## 4. Context precedence (D06), and why it cannot invert

The explicit turn receives both halves of the snapshot. **They are not equal.**

1. **The referent of a deictic is always the most recent utterance in the
   tail.** The working set is never authoritative about *what was just said*; it
   is authoritative about what analysis has finished understanding, which can be
   thirty seconds behind the room.
2. **A prepared resource may answer a deictic only if it is anchored to that
   referent**: its provenance cites the same utterance, or its topic is one of
   the **referent's topics** — see §5.
3. **Everything else is stale** — prepared from speech older than what the user
   just pointed at. Refresh; do not show.

`ContextOrigin` records which of the two the referent came with — `tail` when
only the sentence is known, `working_set` when the enrichment has reached it.
It never changes *which* utterance is the referent; it says what is known about
it in addition.

### The structural argument, and its correction

Both halves compare on one scale — the utterance rank — and the rank is
**assigned by the store**. An earlier version of this page said the invariant
therefore held by a *data dependency*, generalising Slice 06's finding about the
**ambient lane's ordering** (where the enqueue genuinely needs a rank that does
not exist until the store assigns it) into a property of the **store**. That
generalisation was false, and it was measured: `apply()` copied
`provenance.sequence` verbatim with no check, so a record citing rank 54 against
a tail whose maximum was 4 was accepted, `observed_sequence` became 54, and rule
3 below was **dead** from then on. The invariant held only because two producers
happened to read the rank back (`ambient_lane._tail_sequence`,
`presentation_speculative._provenance`) — producer discipline honoured twice,
not a data dependency. A true statement about one component, promoted to a
property of the system without the system being asked.

It is a property of the store now. `PresentationWorkingSetStore.apply()`
**clamps** the freshness a record may claim to `assigned_sequence`, the highest
rank the store has ever handed out in this session:

- clamped, not refused, because the record *was* said — only its claim to
  freshness is wrong, and refusing would turn an approximate producer into lost
  analysis. Refusing was tried and measured: it breaks 118 existing tests across
  Slices 04, 08 and 09, all of which legitimately build provenance by hand;
- the clamping is **journalled** at `warning`
  (`presentation_provenance_rank_clamped`, with the cited and assigned ranks),
  because a silent correction is how the faulty producer stays hidden;
- and the read side closes the same door a second time: `cited_rank()` re-reads
  every rank bounded by `observed_sequence`, so a resolver never trusts the
  field either.

**The residual, stated.** Clamping pulls a forged rank down to the ceiling, not
to the truth. The most a forging producer can claim is therefore "as fresh as
the freshest thing the store knows" — bounded, never ahead of reality, and it
cannot resurrect a resource older than the referent. Slice 11 adds a third write
path; this is the bound it inherits.

## 5. The prepared-resource resolver

Deictic turns only. A **named** request ("montre-moi le bilan Q3") gets
`ResourceVerdict.NOT_REQUESTED`: matching a name to a resource here would need a
second lexical classifier, weaker than the brain's. Stating it beats guessing it.

That escape hatch used to read "the brain receives the whole projection anyway",
and **it did not**: `to_brain_context()` emitted topics, claims, entities,
sources, questions, attention and recent speech, and for resources only the
single resolution — `{verdict: "not_requested", resource_id: ""}`. So for
"montre-moi le bilan Q3" with a perfectly good hidden scene object staged for
`t-bilan`, nothing reused it **and the brain was not told it existed**. The
projection now carries a bounded `prepared_resources` section (id, kind, title,
topic, temperature), symmetric with the others, `discardable` ones excluded so
the model is never invited to ask for what the resolver refuses. References
only, never a payload — the locator and the descriptor do not cross.

The order of refusals **is** the contract, because the first one is what gets
journalled and what explains the session:

| # | Check | Verdict / code |
| --- | --- | --- |
| 1 | no referent — the tail is empty | `absent` / `addressed_no_recent_speech` |
| 2 | nothing left once **retired** and **cold** resources are removed | `absent` / `addressed_no_live_resource` |
| 3 | enrichment has not reached the referent | `stale` / `addressed_enrichment_behind_referent` |
| 4a | provenance cites the referent utterance | `reusable` / `addressed_resource_anchored_to_referent` |
| 4b | otherwise, the resource's topic is one of the **referent's topics** | `reusable` / `addressed_resource_anchored_to_referent_topic` |
| 4c | neither | `stale` / `addressed_no_resource_for_referent` |
| 5 | the top two rank **identically** | `ambiguous` / `addressed_resource_ambiguous` |

### The referent's topics, and the defect that named them

Rule 4b once read *any live topic*, which looks prudent and is not:

```text
u-001 "regardons le bilan Q3"      -> topic t-bilan, resource r-bilan prepared
u-002 "parlons de la tresorerie"   -> topic t-treso committed
"montre-moi ca"                    -> r-bilan: the previous subject's screen
```

Enrichment is **current** in that trace — `observed_sequence` equals the
referent's rank, the lag is zero — so none of the freshness gates could catch
it, and neither could anything else. It is "showing the wrong item" reached from
the one direction the gates do not watch. Nor is it a corner case: analysis
produces a *topic* for a new utterance long before a *resource* exists for it,
so every deictic command issued in that window showed the previous subject.

`referent_topic_ids()` is the narrower, named rule. A topic belongs to the
referent when **a record that names it cites an utterance of rank at least the
referent's**. A topic, an entity, a claim or an open question all qualify; a
**resource** does not — it would vouch for itself.

**The cost, accepted and pinned by a test.** `_coalesce` never rewrites a
topic's provenance (Slice 04's rule, and it is right: a fact must keep citing the
utterance that produced it). A *re-mentioned* topic therefore keeps its first
mention's rank and does not join this set: "toujours sur le bilan" followed by
"montre-moi ça" **refreshes** instead of reusing, until analysis also produces an
entity, a claim or a question of fresh rank on that topic — which it commonly
does. A lost reuse, never a wrong screen; the side this slice takes everywhere
else. Doing better would need the working set to keep, per topic, the last
utterance that mentioned it: a field that does not exist and would belong to
Slice 04.

**Retired never resurrects.** The store already holds that on the write side
(`apply()` refuses a late preparation naming a discarded resource); this is the
read side.

**In-process, the store cannot produce that state** — it retires and replaces the
snapshot in the *same* commit — so the read-side filter is defence in depth
against a state only a **split read** creates: a cross-process relay, which
Slice 06 §7 says may back the sink and which Slice 11 adds a third write path to,
makes `snapshot` and `retired_resource_ids` two round trips that can straddle a
retirement. That is the state the conformance test constructs, with a control arm
showing the same data is `reusable` without the filter.

If the retired list cannot be read at all, the answer is `stale` — not
an empty set, which would assert "nothing was retired", the one thing we are not
in a position to say. A `str` counts as unreadable: iterated, it would yield a
set of **letters**, a wrong answer wearing the shape of a right one.

**Cold means `discardable`** — the resource's topic has left the working set, or
it has slept longer than `MAX_RESOURCE_IDLE_S`. Slice 04 computes the effective
temperature rather than accumulating it, so this reading is stable.

**Ranking** is `(provenance.sequence, temperature.rank, last_used_at)` and
deliberately **does not end with the id**. The store's own `sort_key` does, to
make eviction deterministic; here it would turn a genuine "which one?" into an
alphabetical coin toss. Two preparations for one sentence is an ordinary
situation, and the honest answer is to ask.

### What happens next

| Verdict | Action | Effect |
| --- | --- | --- |
| `reusable`, `scene_object` | `show_prepared` | `PresentationSpeculativeService.reveal()` — it owns the stager and warms the resource through `use_resource` |
| `reusable`, any other kind | `show_prepared` | `store.use_resource()` — the temperature rises to `hot` and `last_used_at` moves, so the reuse is **observable** |
| `ambiguous` | `clarify` | one `SpeechKind.QUESTION` |
| `stale` / `absent` | `refresh` | `reserve_explicit()` at **P1**, which takes a reserve slot and preempts speculative work if the pool is full |
| `not_requested`, or any non-visual situation | `ask_brain` | the projection goes to the brain |

A failed or refused reveal, a store refusal, or a missing stager all fall back to
**refresh**, never to a claimed success: a resource declared served beside an
empty screen is the "it worked" that means "nothing happened". The refusal is
*named* (`addressed_reveal_unavailable`) rather than arriving as an
`AttributeError` dressed as one.

The refresh's job topic is the **utterance id**, never the turn's text. The key
is journalled by digest, but the topic also feeds coalescing and there is no
reason to put speech in it.

## 6. Speech: Slice 07's policy, integrated, not re-decided

`classify_addressed_situation` and `admit_presentation_speech` are **injected
fields**, defaulting to the domain functions. Two reasons, both load-bearing:
the matrix stays the whole truth, and a guard no test can make fail is not a
guard but a wish (Slice 07's own words about its classifier).

- the turn's `OutputDisposition` is `policy_for(situation).disposition`, read,
  never recomputed. A visual command completes with **zero** speech;
- a genuine question is `visual_and_voice` and may speak `RESULT`;
- the clarification is audible **because `SpeechKind.QUESTION` is in
  `VISUAL_COMMAND`'s `safety_speech_kinds`** — Slice 07's exception, exercised
  here for the first time. A conformance test reads that row directly, so the
  day it moves, it fails here rather than in a user's silence three months on;
- if the policy ever refused the clarification, the service **refreshes** rather
  than going quiet. A turn with neither a screen nor a sentence is precisely the
  defect that exception was added to close.

The kind is still Core's, never the agent's: this service names `QUESTION` as a
literal at one site. An earlier version of this page claimed the Slice 07 AST
guard "already enumerates" it — **it did not**. That guard walks
`SpeechRequest(...)` *construction* sites, and this slice constructs none.

**Closed in Slice 11.** The request is built in `SpeechScheduler`, and that site
is now in `SPEECH_KIND_SITES`. It carries the literal `SpeechKind.QUESTION`
rather than the verdict's field, and **refuses** any other kind the resolver
might one day return: the guard rejects a bare name at that position, and it is
right to — a copied field is a field a future producer can fill differently,
while `VISUAL_COMMAND` admits `QUESTION` only as a *safety* kind.

## 7. The projection, and its two named exits

`AddressedTurnContext` has **two** serializers, named differently on purpose:

- `to_brain_context()` carries the recent tail **as spoken**, topic and entity
  labels, claims, open questions and each attention item's `reason`. It is
  speech, by design — that is D06's whole point, and the only way to answer
  *"qu'est-ce que tu as trouvé ?"* (`HV-PRES-ALERT-01`'s own script). It goes to
  the model, in memory, in-process;
- `to_trace_payload()` carries counts, ids, codes and booleans. It goes to the
  journal.

Slice 09 left a precondition: `reason` is the one field that can carry room
speech, and it already propagates through `AttentionItem.to_payload()` →
`PresentationWorkingSet.to_payload()` → `PresentationContextSnapshot
.to_payload()`. While nothing called those serializers the constraint held *by
absence*. This slice is the one that wanted `reason`: it reads it **off the
object**, and an AST test forbids any `to_payload` call in either Slice-10
module, so the constraint now holds by construction. The counters' own
serializer is called `to_trace_payload` for the same reason — a homonym would
have forced the guard to carry an exception, and a guard with an exception is a
guard that gets widened.

A behavioural test plants a phrase in the tail, in a claim and in an attention
`reason`, drives the whole lane, and finds it in **zero** journal lines and in
the brain context, where it belongs.

Failure lines carry `error_class` and a stable code, never the exception's text.
This is the same deliberate departure Slice 08 documented, for the same reason:
the refresh path hands material to another lane, and a caller echoing its input
into an error message would deposit speech in a durable file.

### Bounds

| What | Bound |
| --- | ---: |
| tail entries projected | 8 (of the tail's 16) |
| topics / claims | 6 / 6 |
| entities / sources / questions / attention | 8 / 4 / 4 / 3 |
| prepared resources named to the brain | 6 (of the store's 16) |
| compact JSON budget | `MAX_ADDRESSED_CONTEXT_CHARS` = 6 000 |

6 000 is the **prompt budget** this projection owes, the counterpart of
`MAX_BRAIN_WORK_CONTEXT_CHARS` for work — not `MAX_WORKING_SET_CHARS` (120 000),
which only proves the store is finite. `presentation-working-set.md` said this
budget would live here; it does.

Over budget, whole sections fall in a declared order — questions, entities,
sources, attention, claims, resources, topics — and only then is the tail trimmed **from
the oldest**, never emptied while one entry remains. The tail goes last because a
projection without recent speech is exactly the stale context this slice exists
to prevent. Whatever fell is **named** in `clipped`: an absent section and an
empty one must not read alike, or a working set that is merely too big reads as
a working set that is empty.

## 8. Latency telemetry, and what it actually measures

Three measures, on `LatencyTracker` reused as-is — with one addition to it,
`mark(..., at=)`, so a measure can start from an instant already stamped
elsewhere. Without it this slice would have kept a second stopwatch, which is two
mechanisms for one question.

| Measure | From | To |
| --- | --- | --- |
| `explicit_trigger_to_addressed_admission` | the stamp the explicit-address lane froze at admission | `open()` has finished building the projection |
| `explicit_trigger_to_visible_reaction` | the same stamp | the caller declares a visible reaction |
| `explicit_trigger_to_audible_reaction` | the same stamp | the caller declares an audible reaction |

Read honestly:

- the **admission** measure is in-process work with no IO. It is the quantity
  D04 obliges us to bound and the only one of the three this slice controls end
  to end;
- **visible** does not mean "a pixel changed". It ends when the call that asked
  for the change returns; the rest of the distance belongs to the scene and the
  browser;
- **audible** ends where the caller says it does. **Slice 11 chose "the speech
  entered the scheduler's queue"**, and the reason is written down: that is the
  last instant PRESENTATION controls. Past it lie the provider and the sound
  card, which the existing voice-output latency measures already cover; closing
  the bound later would count the same wait twice and give two numbers for one
  question. So this measure answers *"how long before JARVIS decided to speak
  and the sentence was ready"*, not *"how long before it was heard"*.

Both bounds of every measure come from **one** monotonic clock in **one**
process, which is the constraint `LatencyTracker` already imposes on itself, and
the service guards **both directions** of a mismatch:

- **behind** the trigger's stamp: no measure at all. `latency_clock_mismatch` is
  counted, a `warning` says so, and the latency reads `None`. A `None` says *we
  do not know*; a zero would say *we know it was instant*;
- **ahead by more than `MAX_TRIGGER_CLOCK_SKEW_S`** (the window, 12 s): the turn
  is **refused at `arm()`** with `addressed_trigger_clock_skew` at `error`, and
  the message names the fix. This direction used to fail *wrong* rather than
  blank — a clock 0.5 s ahead produced a plausible `502.0 ms` with no signal, and
  beyond the window every addressed turn died with `addressed_window_expired`,
  which blames the user for speaking too late. Past the window a trigger cannot
  address the sentence being spoken anyway, so there is no case where continuing
  helps and exactly one where saying so does.

**The residual, stated rather than papered over.** *Under* the ceiling a forward
skew is genuinely indistinguishable from elapsed time: a press can legitimately
wait in the lane, so 0.5 s of skew and 0.5 s of queueing produce the same number
and nothing can separate them. The `addressed_trigger_stale` warning therefore
names **both** possible causes rather than asserting the one that reads better.

These three names live in this module, **not** in `LATENCY_MEASURES` — that
tuple is the exhaustive inventory of the realtime-brain handoff's six measures,
consumed by the testlab and pinned at six by a test.

## 9. After the turn: still Presentation, still ambient

`conclude()` reads where the session stands and says it. What it deliberately
does **not** do: end the session, retire anything, change the mode, stop any
lane. An addressed turn is an episode inside an ambient session, not an
excursion into assistant mode.

The balance comes back as a **value** (`AddressedTurnSettlement`: mode, session
id, generation, `still_presentation`) and not only as a journal line, so a test
can assert the session survived without reading a log — Slice 04's unobservable-
invariant lesson. If the mode did leave Presentation mid-turn, the line is a
`warning` with its own code rather than a cheerful `settled`.

`behaving_interaction_mode` is the reading used, as everywhere in this handoff,
so a reserved `meeting` does not behave like Presentation, and an unreadable
value falls back to assistant — the safe direction.

## 10. Failure behaviour

| Situation | Counter / code | What happens |
| --- | --- | --- |
| Trigger is not an `ExplicitAddressTrigger` | `addressed_trigger_invalid` | rejected, nothing armed |
| Trigger claims `authorizes_actions` | `addressed_trigger_authorizing` | rejected (D03); unreachable with the real type, reachable through a transport that rebuilds it |
| Mode is not Presentation | `addressed_mode_not_presentation` | ignored; the window is closed if one was open |
| No session bound | `addressed_working_set_inactive` | ignored |
| Window expired, or speech outside it | `windows_expired` / `addressed_window_expired`, `addressed_speech_outside_window` | stale, window closed |
| Second `open()` without a new press | `addressed_no_window` | ignored |
| Snapshot unreadable | `store_failures` / `addressed_snapshot_unreadable` | rejected, said at `error` |
| Retired list unreadable or untyped | `store_failures` / `addressed_retired_unreadable`, `addressed_retired_untyped` | resolution is `stale`; nothing is reused |
| Store raises on `use_resource` | `store_failures` / `addressed_store_failed` | refresh |
| Speculative lane raises on `note_addressed_turn` | `speculative_failures` / `addressed_preemption_failed` | the turn continues |
| Reveal raises or is refused | `reveal_failures` | refresh |
| No stager wired | `reveal_failures` / `addressed_reveal_unavailable` | refresh, never a claimed success |
| `reserve_explicit` raises or refuses | `refresh_failures` / `addressed_refresh_failed`, `addressed_refresh_refused` | said, counted |
| Classifier raises or returns an untyped value | `classification_failures` | falls back to `knowledge_question` — **speech**, never silence |
| Speech admission raises or refuses | `clarification_withheld` | refresh, never silence |
| Clock raises or is untyped | `addressed_clock_unreadable` | rejected |
| Clock behind the trigger | `latency_clock_mismatch` | no latency at all rather than an invented one |
| Journal raises | `diagnostic_failures` | swallowed — a broken journal never decides a turn — but **counted**, so `stats()` cannot describe a healthy lane beside an empty trace |
| An unknown store disposition | `store_failures` / `addressed_store_disposition_unknown` | said at `error`, counted under its own name, bucketed into nothing (Slice 06's lesson) |

All seven of Slice 04's dispositions are **pre-declared** in the counter table:
a counter that only appears once encountered cannot distinguish "never happened"
from "never counted".

The expected path is journalled at `info` too
(`presentation.addressed.{armed,opened,reused,refresh_requested,clarified,brain_turn,settled}`),
so an empty trace cannot mean both "fine" and "dead".

## 11. What this contract deliberately does not do

- **Wired in Slice 11.** `PresentationWakeRouter` consumes
  `ExplicitAddressLane.triggers()` and calls `arm()`; `SpeechScheduler.note_addressed_turn`
  calls `open()`, hands `plan.situation` to the speech gate instead of letting it
  re-classify, awaits `deliver()`, closes the two reaction measures and always
  calls `conclude()`. The service's `clock` **is** the lane's, set at composition
  rather than assumed. What is *not* wired: `ASK_BRAIN` reaches the brain without
  `to_brain_context()`, because `submit_brain_turn` carries no context parameter
  and the turn is classified after submission by Slice 07's design — the other
  three actions are complete;
- **no named-resource matching.** A named request goes to the brain with the
  projection, and `not_requested` says so;
- **no second speech policy.** The matrix decides; this service reads it;
- **no `SpeechRequest`.** The clarification's *kind* is decided here; the
  request is built in Slice 11, whose site now appears in `SPEECH_KIND_SITES`;
- **no priority on canonical work.** That is G5, and it stays that way;
- **no execution capacity claim.** The addressed turn's concurrency lives on
  `OwnedJobExecution`, untouched here;
- **no persistence.** Nothing on this path writes to disk. The one durable
  footprint it can cause is a scene object revealed through Slice 08's stager,
  which Slice 08 already reclaims.
