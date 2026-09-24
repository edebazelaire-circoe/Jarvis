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
| `request_conversation` | Duplex's direct spoken answer | Presentation cannot be silent in one architecture and talkative in another for the same sentence |
| `_decide_reflex` | the surface preamble | the only filler the surface can produce on its own |

The gate itself (`PresentationSpeechGate`) holds no policy: it holds the
per-turn situation, the counts, and the journal. The policy is the Slice 01
matrix, read through `jarvis/domain/presentation_response.py`.

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
   haute`, …) → `EXPLICIT_SPEAK_REQUEST`;
2. a **question** — a `?` anywhere, or a question word opening the phrase →
   `KNOWLEDGE_QUESTION`;
3. a **display verb** (`montre`, `affiche`, `ouvre`, `masque`, `épingle`,
   `archive`, `range`, …) → `VISUAL_COMMAND`;
4. otherwise → `KNOWLEDGE_QUESTION`, evidence `no_visual_command_evidence`.

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

`admit_presentation_speech(situation=…, kind=…)` reads the Slice 01 matrix.
Two speech kinds are judged on their own row rather than the turn's
(`SAFETY_SITUATIONS`):

| Kind | Judged as | Why it cannot be withheld |
| --- | --- | --- |
| `ERROR` | `COMMAND_ERROR` | a silent failure is a defect, not discretion |
| `QUESTION` | `KNOWLEDGE_QUESTION` | this is hearing repair and required clarification — a turn where Jarvis could not ask *which* bilan would die silently, and the user would not even know to ask again |

This is the path Slice 01 already blessed for errors: a failed command becomes
`COMMAND_ERROR`, it is not a mute `VISUAL_COMMAND`. The clarification half is
the same argument: a turn that needs a question back is not a *completed*
visual command.

**A situation that does not arise from an explicit address is never promoted.**
`judged_situation` reads `requires_explicit_address` from the matrix rather
than naming rows, so `AMBIENT_OBSERVATION` and `FACT_CHECK_ATTENTION` — and any
row added later with the same property — stay exactly where they are, for all
five kinds. That is **D03** and **D11**, and it is a test over the whole matrix.

A speech request that belongs to **no known addressed turn** (a spontaneous
relay at the end of a background sub-agent, a notification) is treated as
unaddressed: the matrix says `voice_allowed ⇒ requires_explicit_address`, so it
does not speak — except `ERROR`, for the reason in the table above.

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

`WAIT` and `SPEAK` are untouched. Hearing repair and required clarification do
not travel on this channel at all: they arrive as `SpeechKind.QUESTION`, which
`SAFETY_SITUATIONS` protects.

## Silence is observable

An invariant nobody can observe drifts (the lesson Slice 04 paid for). So a
Presentation turn's outcome is readable and written:

- `SpeechScheduler.presentation_turn_outcome(correlation_id)` returns a payload
  — situation, evidence, admitted count, withheld kinds, `silent`, and
  `silent_reason`;
- `silent_by_policy` (the gate refused at least one speech) and
  `silent_no_speech` (the brain asked for nothing) are **different** values, so
  "it worked quietly" never reads the same as "something died";
- journal lines, all metadata-only:

| Kind | Level | When |
| --- | --- | --- |
| `voice.presentation.turn_classified` | info | a turn is classified |
| `voice.speech.presentation_withheld` | info | a speech is refused |
| `voice.presentation.classification_failed` | warning | the classifier raised; the turn fell back to speech |
| `voice.presentation.turn_silent` | info | a turn ended without a word |

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
- **Meeting mode has no policy here.** `behaving_interaction_mode` maps it to
  assistant, as everywhere else in this handoff.
