# Presentation response policy — silence as a successful outcome (contract)

Handoff `tasks/jarvis-presentation-interaction-mode/`, **Slice 07**.

Slice 01 gave the matrix as data ([interaction-mode.md](interaction-mode.md)).
This page is what reads it at runtime: the situation classifier, the speech
gate, and where the enforcement boundary sits.

Modules: `jarvis/domain/presentation_response.py`,
`jarvis/runtime/presentation_speech_gate.py`, plus the three call sites in
`jarvis/runtime/speech_scheduler.py`.
Conformance suite: `tests/unit/test_presentation_response_policy.py`.

## The problem this page exists to close

Before this slice, the only "show, don't speak" rule in the repository was a
sentence in a prompt (`BRAIN_DISPLAY_PROMPT`, `jarvis/runtime/claude_local.py`):

> Les actions d'affichage sont silencieuses : ne décris pas à l'oral ce que tu
> places ni où.

A prompt sentence holds for exactly as long as the model keeps re-reading it.
It does not survive a reformulation, a different provider, or a competing
instruction — and decision **D09** requires something stronger than a habit: a
brain turn that completes with **zero** `SpeechRequest` must be a *normal,
observable success*, not an accident.

`BRAIN_NOT_ADDRESSED_ANSWER` (`[pas-pour-moi]`, `jarvis/domain/v2.py`) is the
closest existing precedent, and it is deliberately **not** the model followed
here. It is a magic string the model must reproduce exactly for nothing to be
said; a model that mis-spells it speaks it aloud. It stays in place untouched —
assistant mode does not move (**D14**) — but Presentation decides in the
runtime.

## Where the boundary sits, and why there

`SpeechScheduler` is already the single owner of what gets said and in what
order. Every brain utterance in continuous mode arrives there through
`brain.speech.requested`, every controller notice through
`enqueue_controller_speech`, every direct Duplex answer through
`request_conversation`, and the only surface-generated speech through the
reflex preamble. Putting the policy anywhere else would mean putting it in more
than one place.

Three call sites, all in `jarvis/runtime/speech_scheduler.py`:

| Site | What it gates | Why there |
| --- | --- | --- |
| `_enqueue`, after the duplicate/capacity checks | every `SpeechRequest` from Core | before the queue, so a refused speech never becomes a candidate — and *after* deduplication, so a retransmitted request is not counted twice |
| `request_conversation` | the direct spoken answer of **SIMPLE, FRONT_BRAIN and DUPLEX** | Presentation cannot be silent in one architecture and talkative in another for the same sentence. The identity consumed before the gate here too, for the same reason |
| `_decide_reflex` | the surface preamble | the only filler the surface can produce on its own |

The matrix decides **what gets said**; the gate asks it and applies the answer
without nuancing it, and otherwise holds only the per-turn situation, the
counts and the journal. Two rules are the gate's own, because they are not
matrix rows: no surface preamble in Presentation (a preamble is nobody's
speech — it is a turn of the surface, contentless by construction), and a
speech belonging to no classified turn falls to `UNADDRESSED_SAFETY_KINDS`.

**Outside PRESENTATION the gate is inert** — it records nothing, accumulates
nothing, admits everything, and writes no journal line at all. That absence is
itself a test (`test_le_mode_assistant_ne_laisse_aucune_trace_de_presentation`):
a gate that journals in assistant mode has already started deciding something.

## How a turn is classified

The classifier runs **once**, when the bridge submits an addressed turn
(`RealtimeConversationBridge` → `on_addressed_turn` →
`SpeechScheduler.note_addressed_turn`). The transcript is read and discarded;
only the situation and a short evidence marker are kept.

Reading order — and the order *is* the contract:

1. an **explicit speak request** (`dis-moi`, `raconte`, `lis-moi`, `à voix
   haute`, …), **not under a negation** → `EXPLICIT_SPEAK_REQUEST`;
2. a question word **opening** the phrase → `KNOWLEDGE_QUESTION`;
3. a **display verb** (`montre`, `affiche`, `ouvre`, `masque`, `épingle`,
   `archive`, `range`, …) → `VISUAL_COMMAND`;
4. a **question mark** → `KNOWLEDGE_QUESTION`;
5. otherwise → `KNOWLEDGE_QUESTION`, evidence `no_visual_command_evidence`.

### The question mark comes after the display verb

Real-time ASR punctuates interrogative intonation, and « tu peux afficher le
bilan ? » is ordinary French for a display command. While a `?` anywhere beat
the display verb, the most natural way to ask for a display was read as a
question and Jarvis answered it aloud — re-creating, on the most frequent
phrasing, exactly the filler decision 09 removes. Measured: « Tu peux montrer
le bilan ? », « Montre-moi le bilan ? », « Affiche le bilan, d'accord ? » all
spoke.

A question word **at the head** still wins, and that half matters just as much:
« pourquoi tu as affiché le Q3 ? » is a real question about a display, and
muting it would trade a chatter defect for a silent-failure defect. Step 4
therefore only fires when there is neither a head question word nor a display
verb — « c'est bien ça ? ».

### Negation

A speak marker under a negation is skipped (three tokens of lookback,
`NEGATORS`). « montre le bilan, ne commente pas » used to ask for speech
*because* the user refused it: `commente` was read without its « ne ». A missed
marker makes Jarvis speak, which is the safe side; a marker read backwards does
the one thing the user asked it not to.

### « montre-moi le bilan **et dis-moi le total** »

This sentence is why step 1 comes first. `VISUAL_COMMAND` carries
`voice_allowed=False` as a **hard ceiling, not a default**: under that row, no
amount of asking unlocks speech. So a sentence that asks for both the screen
and the voice must be classified on the side where the voice exists, or its
spoken half would be dropped with no recourse. `dis moi` is found, the turn is
an `EXPLICIT_SPEAK_REQUEST`, and both halves happen.

Strip the speak request and the ceiling shows itself: « montre-moi le bilan »
is a `VISUAL_COMMAND`, and `ACK`, `PROGRESS` and `RESULT` are all refused.

### Silence requires positive evidence

Step 4 is a deliberate bias. Muting an addressed turn we failed to parse would
produce a silent failure — the exact defect this slice exists to abolish, and
one this repository has already paid for (`voice.speech.error_withheld` was
written after a real incident on 16/09/2026). So `VISUAL_COMMAND` needs a
display verb to be *found*; absent evidence, Jarvis answers.

For the same reason, question words are matched **only at the head of the
phrase**: `ou` is an ordinary conjunction, and matching it anywhere would turn
« affiche le graphique ou le tableau » into a question.

A classifier that raises falls back to `KNOWLEDGE_QUESTION` with evidence
`classification_failed` and a `warning` line — again, the fallback is speech.

## What a situation is allowed to say

`admit_presentation_speech(situation=…, kind=…)` calls `may_speak()` once, and
`may_speak()` is the **whole** truth: the ceiling and its exceptions are both
row data. Nothing sits on top of it deciding anything — an exception layered
above the matrix would be the prose this slice abolishes, rewritten in Python.

Two kinds are admitted despite the ceiling, named row by row in
`safety_speech_kinds`:

| Kind | Why it cannot be withheld | Its producer |
| --- | --- | --- |
| `ERROR` | a silent failure is a defect, not discretion | a turn that failed (`_settle_failure`, `brain_service`) |
| `QUESTION` | required clarification — a turn where Jarvis could not ask *which* bilan ends with no screen *and* no sentence, and the user does not learn they must ask again | `public_answer_kind()`, from the answer's own shape |

`__post_init__` holds them to the same bar as `voice_allowed`: a safety kind
still requires an explicit address, and it may not also appear in
`speech_kinds`. So `AMBIENT_OBSERVATION` and `FACT_CHECK_ATTENTION` — and any
row added later that does not require an explicit address — cannot carry one at
all. That is **D03** and **D11**, as data rather than as discipline.

### The kind is Core's, never the agent's

This is what keeps a safety kind from becoming a way around the ceiling. The
agent cannot name a `SpeechKind`; Core sets it. `ERROR` comes from a turn that
failed. `QUESTION` comes from `public_answer_kind()`
(`jarvis/adapters/control_center_brain.py`), which labels the public answer a
question only when it is **one interrogative sentence and nothing else** — so
« Voilà le bilan. Tu veux aussi le Q4 ? » stays a `RESULT` and stays withheld.
The agent writes French; a statement cannot declare itself a question without
ceasing to be a statement.

That producer is also a repair, not a Presentation trick: `SpeechKind.QUESTION`
has had full semantics in Core since the beginning —
`BrainOrchestrator._revise_question` turns it into an open point of the working
state instead of an acquired public fact, and it is deliberately not retained
as a durable outcome — and **no producer ever emitted it**, while the system
prompt has always told the agent to settle an ambiguous request « en une
question courte ». The lane was dead. The change applies in both modes, because
nothing about it was ever specific to Presentation; what the user hears is
unchanged (same sentence, same priority), only Core's bookkeeping becomes what
the kind always meant.

Every production `SpeechRequest` construction site is enumerated against a
declared table by
`test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole`,
which fails the day a tool lets the agent choose.

A speech request that belongs to **no known addressed turn** (a spontaneous
relay at the end of a background sub-agent, a notification) has no row at all.
`UNADDRESSED_SAFETY_KINDS` governs it: `ERROR` only — without an addressed turn
there is nothing to clarify. The rule is named in the domain rather than living
in an `if` at the bottom of the runtime, so it can be read and documented.

## Ambient cannot request speech, twice over

1. **Structurally.** `BrainTurnInput.__post_init__` refuses
   `AddressingDecision.AMBIENT` outright, so no ambient utterance can ever
   become a turn, so no ambient speech request can ever be born. Slice 06's
   transitive import closure says the same thing one layer down: the ambient
   lane loads a declared set of modules that contains no path to the brain.
2. **By policy.** Even handed an `AMBIENT_OBSERVATION` directly, the gate
   refuses every `SpeechKind`, including the two safety kinds.

This slice opens no new edge between the ambient lane and the speech path;
`tests/unit/test_ambient_ingestion_lane.py` is re-run as the guard.

## Filler is suppressed, hearing is not

In Presentation the surface preamble never fires. It is filler by construction:
`REFLEX_INSTRUCTION` (`jarvis/adapters/openai_realtime.py`) forbids it to give a
result, announce progress, or ask a question. That is precisely the speech that
adds no value, which **D10** exists to remove.

The suppression is a post-filter in the runtime
(`SpeechScheduler._decide_reflex`), not a change to `decide_reflex`: the domain
policy is shared with assistant mode and must not move (**D14**). Only
`ReflexAction.PREAMBLE` is converted, to `WAIT` with reason
`presentation_no_filler`, and the decision is journalled on the existing
`voice.reflex.decided` channel — the preamble's absence is a recorded decision,
not a hole.

`WAIT` and `SPEAK` are untouched.

**What does not travel on this channel, and what has no channel at all.**
Required clarification arrives as `SpeechKind.QUESTION` from the brain, which
`safety_speech_kinds` admits on every addressed row — it never goes near the
reflex. *Hearing repair* is different and the earlier version of this page was
wrong about it: it lives in `CONTINUOUS_BRAIN_OPERATING_RULES`
(`jarvis/adapters/openai_realtime.py`), and in continuous mode the surface
cannot speak unbidden at all, because `CONTINUOUS_TURN_FLAGS` sets
`create_response: False`. So hearing repair has **no production path today**,
in either interaction mode; this slice neither opens nor closes one.
`ReflexAction.BACKCHANNEL` and `DELEGATE` are likewise unreachable: only the
advisory Front Brain hint names them, and its consumption result is discarded
by its single caller.

## Silence is observable

An invariant nobody can observe drifts (the lesson Slice 04 paid for). So a
Presentation turn's outcome is readable and written:

- `PresentationSpeechGate.outcome(correlation_id)` — situation, evidence,
  admitted count, withheld kinds, `silent` and `silent_reason`, with
  `to_payload()` for the journal. (A pass-through wrapper on `SpeechScheduler`
  was deleted: no production caller, and a second name for one read.);
- `silent_by_policy` (the gate refused at least one speech) and
  `silent_no_speech` (the brain asked for nothing) are **different** values, so
  "it worked quietly" never reads the same as "something died";
- journal lines, all metadata-only:

| Kind | Level | When |
| --- | --- | --- |
| `voice.presentation.turn_classified` | info | a turn is classified |
| `voice.presentation.speech_withheld` | info | a speech is refused |
| `voice.presentation.classification_failed` | warning | the classifier raised; the turn fell back to speech |
| `voice.presentation.turn_silent` | info | a turn ended without a word |

All four sit under `voice.presentation.`, deliberately not under
`voice.speech.`: `voice.speech.presentation_decided` already exists there and
means the *delivery* of a speech, and the testlab consumes it. Two senses of
"presentation" on one prefix would eventually have been read for each other.

**No transcript, ever.** `voice.transcript_dropped` writes `text[:300]`
elsewhere; that is a known pre-existing defect (`Issues/002`), not a pattern to
copy, and a test asserts that no line from this slice carries the spoken words.

### When a turn is settled

`voice.presentation.turn_silent` is written when it is certain nothing more will
come for that turn: on the arrival of the **next** addressed turn, and on
`SpeechScheduler.stop()`. It is deliberately **not** written on
`brain.work.completed`, because `ControlCenterBrainBackend._settle_success`
publishes `COMPLETED` *before* the turn's speech — settling there would date the
balance from before the only thing it counts. The read is immediate; only the
journal line waits one turn.

## The prompt follows the runtime

The runtime contract does not depend on a prompt being read — the conformance
suite proves the withholding with no instruction anywhere in the loop. But a
model that writes sentences the runtime then drops is a model fighting the
runtime, so the instruction is aligned:

- Core hands the effective mode to the brain backend
  (`InteractionModeService.add_listener` →
  `ControlCenterBrainBackend.observe_interaction_mode`, read with
  `behaving_interaction_mode`, so `REUNION` never reaches a model as a
  behaviour);
- the backend joins it to the **turn** context (`_turn_context`), not to the
  session, because the mode changes hot and never restarts anything (**D15**);
- **at the default mode the key is absent**, so an assistant turn's context is
  byte-for-byte what it was before this slice (**D14**);
- the Control Center renders `BRIEF_PRESENTATION_MODE` from it
  (`build_agent_brief`). `BRAIN_DISPLAY_PROMPT` is untouched: it is applied in
  assistant mode too, and its « quelques mots suffisent » is correct there.

## Known limits, stated rather than discovered later

- **A spontaneous relay inherits the last addressed turn's situation.**
  `BrainOrchestrator._relay_notice` reuses the *current* source's
  `correlation_id`, so a background sub-agent finishing right after a genuine
  question is judged under that question and may speak. A relay arriving after
  a `VISUAL_COMMAND` is silent, and one arriving with no current source is
  judged unaddressed. Narrowing this needs a provenance field the transport
  does not carry today.
- **The classifier is lexical and French.** It has no model behind it and its
  three word lists are the whole of it. `supprime` / `efface` are deliberately
  absent from the display verbs: they name a file as readily as a scene object,
  and muting the confirmation of a file deletion would be the opposite of D09.
- **The classifier is still lexical, and the residuals go towards speech.** A
  question word at the head beats a display verb, so « quel graphique tu peux
  afficher ? » speaks; a quoted string is not protected, so « ouvre la note
  intitulée "dis moi tout" » speaks and « crée une note qui dit "montre moi le
  bilan" » is silenced. Negation is handled only within three tokens before a
  speak marker. A marker written with another inflection (`commenter` for
  `commente`) is simply missed, which makes Jarvis speak.
- **Two views of the mode, one turn apart.** The prompt half reads Core's
  `InteractionModeService`; the gate reads the Voice process's
  `InteractionModeObserver`. Around a mode change they can disagree for one
  turn — the model may receive the Presentation paragraph while the gate is
  still inert, or the reverse. Neither direction loses speech: the worst case
  is one sentence written for nothing, or one spoken that would later be
  withheld.
- **`silent_no_speech` is not observable within its own turn.** Every refusal
  writes a line immediately, so `silent_by_policy` is; a turn where the brain
  simply asked for nothing leaves only `turn_classified` until the next turn
  settles it. `outcome()` is immediate but is a Python read, not a journal
  line.
- **Meeting mode has no policy here.** `behaving_interaction_mode` maps it to
  assistant, as everywhere else in this handoff.
