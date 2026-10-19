# Interaction mode and output disposition (contract)

Handoff `tasks/jarvis-presentation-interaction-mode-2026-09/`.

**Slice 01 — the domain contract**, everything up to "Deliberate limits of this
contract". Pure vocabulary: `jarvis/domain/interaction_mode.py`,
`jarvis/domain/output_disposition.py`, `jarvis/domain/presentation_policy.py`;
conformance suite `tests/unit/test_interaction_mode_contract.py`. No I/O, no
persistence, no API, no UI, no prompt, no audio.

**Slice 02 — the control plane**, the last section. Who owns the live effective
value, where the mode comes from (since Slice 01b of
`jarvis-board-ui-wheel-dossier-refactor`: **the active Board's type, and nothing
else**), the routes and the event, and why a mode change never restarts Voice.

The **interaction mode** says how Jarvis behaves. It is not how Jarvis is
wired, and it is not who is allowed to speak to him. Those are two other axes
that already exist and that this one must never be confused with (decision 01).

| Axis | Type | Meaning | Where |
| --- | --- | --- | --- |
| Interaction mode | `InteractionMode` | product behaviour policy | `jarvis/domain/interaction_mode.py` |
| Voice architecture (typed) | `VoiceArchitectureId{SIMPLE, FRONT_BRAIN, DUPLEX}` | which composition is selected, key `voice_architecture` | `jarvis/domain/voice_architecture.py` |
| Voice architecture (runtime authority) | `VoiceArchitecture{LEGACY, CONTINUOUS_BRAIN}` | which code path actually runs, key `voice_arch` | `jarvis/v2_config.py` |
| Conversation authorization | `ConversationMode{OPEN_ROOM, SOLO_OWNER}` | who may constitute a turn | `jarvis/domain/speaker.py` |

A presentation stays a presentation whatever architecture carries it. Product
capability is not branched by voice architecture unless a provider genuinely
cannot do it.

## The three modes

| Internal value | User label | Status | Default disposition |
| --- | --- | --- | --- |
| `assistant` | `SIMPLE` | ready | `visual_and_voice` |
| `presentation` | `PRESENTATION` | ready | `visual_only` |
| `meeting` | `REUNION` | **planned** | `silent` |

`assistant` is the default, and it is the regression boundary (decision 14):
unless the active Board's type designates another mode, Jarvis behaves exactly
as before.

`InteractionModeStatus{READY, PLANNED}` reuses the vocabulary of
`VoiceAdapterStatus` — the same distinction between "documented" and "actually
exists" — minus `legacy_only`, which has no meaning here. The descriptor's
`implemented` flag is derived from it, never stored twice.

### Reading a stored value

Two parsers, deliberately separate, so that no value of another axis can ever
become a mode:

- `parse_interaction_mode(value)` — internal value → mode, or `None`. Strict.
  Trimmed and case-folded. `simple`, `continuous_brain`, `solo_owner` return
  `None`: **no value of another axis can become an interaction mode.**
- `parse_interaction_mode_label(value)` — user label → mode, or `None`.
  **Case-exact.** Decision 02 locks uppercase labels while every other axis in
  the repository carries lowercase values, so case-exactness is what keeps the
  architecture value `simple` out of the `SIMPLE` label door.
- `stored_interaction_mode(value)` — never raises. Missing, empty, mistyped,
  unknown: the default. A corrupt setting must not stop Jarvis from starting,
  and must certainly not start him in a mode nobody asked for.

The value door normalizes case, so the label `PRESENTATION` also passes through
it — without consequence, since it designates the same mode there. The two
labels that *would* change meaning on the way, `SIMPLE` and `REUNION`, are not
values and are refused. The separation that matters is the one that holds:
nothing from another axis gets in through either door.

There is **no `InteractionMode.SIMPLE`**. The label `SIMPLE` exists only through
`label`, because `VoiceArchitectureId.SIMPLE` already exists with an unrelated
meaning. `InteractionMode.SIMPLE` raises `AttributeError`, and a test pins that.

### Reserved mode

`REUNION` is known, listed and displayable; it has no behaviour and none is
invented.

- `is_activatable(mode)` / `activatable_interaction_modes()` — `meeting` is
  excluded.
- `ensure_activatable(mode)` — the **explicit request** path. Refuses with the
  stable code `interaction_mode_not_implemented` (no screen asks for a mode any
  more; the Board card says « Réunion · prévu » from the type).
- `behaving_interaction_mode(value)` — the **behaviour** reading. Total and
  silent: a Réunion Board designates `meeting` — so an interface still shows
  REUNION as the Board type's mode — but that produces assistant behaviour
  here. It never raises and never runs meeting behaviour, because there is none.

The two readings are named apart on purpose. They differ on exactly one input,
`meeting`, and that is the input where choosing wrong is expensive: feeding a
display from `behaving_interaction_mode` would erase REUNION from the interface,
which is precisely what decision 02 forbids. `stored_` is what a value
designates, `behaving_` is what actually runs.

## Output disposition

`OutputDisposition{silent, visual_only, voice_only, visual_and_voice}` in its
own module. It is **not** the scene's `Disposition{active, archived}`
(`jarvis/domain/scene.py`), which is about presence in the scene; the two names
never appear unqualified in the same module. A test enforces that over
`jarvis/` and `tests/`, matching the imported *name* whatever module it comes
from, and covering the absolute and relative spellings, `import … as …`, and
re-export — the guard is checked against synthetic sources of each spelling so
it cannot quietly stop guarding.

`shows` / `speaks` expose the two channels. `silent` is a legitimate outcome, not a missing one: decision 09 requires
that a successful brain turn be able to request no speech at all.

### Voice channel and Chat

The Chat's voice lock (handoff jarvis-unified-chat-and-board-drop,
[chat.md](chat.md) › *Voice channel*) is a third axis, not this one.
`VoiceChannelService` (Core, in memory) says whether the voice runtime is
`absent`, `background`, `connecting`, `active`, `error`, `switching` or
`unknown`, and therefore whether a typed turn may be admitted. It is **not**
`InteractionMode` (it never reads nor sets the mode, and disabling voice never
changes it) and **not** `OutputDisposition` (a text turn's silence is a
per-correlation disposition, `text_channel`, decided in Core's speech
emission, not a mode-driven presentation outcome).

## Presentation policy matrix

Encoded as data in `PRESENTATION_POLICY`, read by the runtime (Slice 07) through `policy_for()`
and `may_speak()`. A
policy in a prompt is not a policy — it holds until the model stops rereading
it. `disposition` is what the turn manifests by default; `voice_allowed` is a
**ceiling**, not a default.

| Situation | Disposition | Voice allowed | Needs explicit address | Authorizes action | Speech kinds | Safety kinds | Attention cue | Decisions |
| --- | --- | :-: | :-: | :-: | --- | --- | :-: | --- |
| `ambient_observation` | `silent` | no | no | no | — | — | no | D03, D11 |
| `visual_command` | `visual_only` | no | yes | yes | — | `error`, `question` | no | D09 |
| `knowledge_question` | `visual_and_voice` | yes | yes | yes | `question`, `result` | `error` | no | D10 |
| `explicit_speak_request` | `voice_only` | yes | yes | yes | all five | — | no | D05, D10 |
| `command_confirmation` | `visual_only` | no | yes | yes | — | `error`, `question` | no | D09 |
| `command_error` | `visual_only` | yes | yes | yes | `error` | `question` | yes | D09, D11 |
| `fact_check_attention` | `visual_only` | no | no | no | — | — | yes | D11 |

`may_speak()` reads both columns and is the **whole** truth: nothing layered on
top of it decides anything. A speech that belongs to no known addressed turn
has no row at all, and is governed by `UNADDRESSED_SAFETY_KINDS` — `error`
only, because without an addressed turn there is nothing to clarify.

Reading the rows:

- **Ambient observation** — listening is not obeying. It stays silent, it
  authorizes nothing, and it cannot request speech (decisions 03, 11).
- **Visual command** — the screen answers, the voice keeps quiet (decision 09).
  `voice_allowed` is false and stays a ceiling; the two **safety kinds** are
  the named exceptions to it, and nothing else passes. A failure is heard
  because a silent failure is a defect, not discretion. A clarification is
  heard because a command Jarvis could not resolve, and could not ask about,
  ends with no screen *and* no sentence — and the user does not even learn
  that they must ask again. Decision 09 says visual commands should
  *normally* execute silently; these are the two cases that are not normal.
  Same shape as `command_error`: it is the outcome, not a label, that takes
  the turn out of "a completed visual command".
- **Knowledge question** — a real question deserves a real spoken answer, with
  the detail and the caveats, leaning on what is already prepared on screen
  (decision 10).
- **Explicit request to speak** — words were asked for, words are given; the
  presenter's screen is not seized on the way.
- **Command confirmation** — success is seen, not announced: no voice ceiling
  at all, no cue. Its own row rather than a shared one, because while the two
  outcomes shared a line "a success is not announced" held only as long as the
  runtime remembered not to ask for speech — the kind of convention this module
  exists to abolish.
- **Command error** — seen too, and it may additionally raise the discreet cue
  and be spoken as an `error`: a silent failure is a defect, not discretion.
- **Fact-check attention** — a light and a short sound; Jarvis does not
  contradict a speaker aloud in front of their audience (decision 11).

`speech_kinds` reuses `SpeechKind` from `jarvis/domain/v2.py`, already the thing
that drives the speech scheduler's policy. A second vocabulary would have meant
two truths about whether Jarvis may say something.

**The kind is set by Core, never named by the agent.** That is what keeps
`safety_speech_kinds` from becoming a way around the ceiling: `SpeechKind.ERROR`
comes from a turn that failed, and `SpeechKind.QUESTION` from
`public_answer_kind()` (`jarvis/adapters/control_center_brain.py`), which reads
the answer's own shape — one interrogative sentence and nothing else. The agent
writes French; it does not fill in a category, and a statement cannot declare
itself a question without ceasing to be a statement. Every production
construction site is enumerated against a declared table by
`test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole`,
so the day a tool lets the agent name its own kind, that test fails first.

### Invariants checked at construction

`PresentationOutputPolicy.__post_init__` refuses a contradictory row when it is
built, so a row added later cannot quietly contradict a locked decision:

- a speaking default requires `voice_allowed`;
- `speech_kinds` is non-empty exactly when `voice_allowed`;
- `voice_allowed` implies `requires_explicit_address` — this *is* "nothing
  speaks spontaneously in V1" (decision 11), as data;
- a non-empty `safety_speech_kinds` implies `requires_explicit_address` too: a
  safety exception is still speech, so it is held to the same bar;
- `safety_speech_kinds` and `speech_kinds` are disjoint, and `safety_speech_kinds`
  carries no duplicate — otherwise a row would say both "this kind passes the
  ceiling" and "this kind goes around it", which is two truths about one kind;
- `authorizes_action` implies `requires_explicit_address` — this *is* "ambient
  speech never authorizes an action" (decision 03), as data;
- every row names the decisions it implements, and each reference must be one
  of the locked `D01`–`D14` of the handoff decision log (`LOCKED_DECISIONS`) —
  otherwise the field proved nothing, since any string starting with `D` used
  to pass.

Codes: `presentation_policy_spontaneous_speech`,
`presentation_policy_ambient_authority`, `presentation_policy_unjustified`,
`presentation_policy_invalid`.

`dataclasses.replace` re-runs `__post_init__`, so the realistic way of
relaxing a row — copying it with one flag changed — is refused too. This is a
construction-time guarantee, not immutability in the strong sense: a forced
`object.__setattr__`, or a subclass overriding `__post_init__`, defeats it as
it defeats any Python dataclass. Both registries are `MappingProxyType`, so the
tables themselves are read-only at runtime.

## Deliberate limits of this contract

Assistant mode has no matrix — it keeps the behaviour it always had
(decision 14). Meeting mode has no matrix, no situation and no channel of its
own. Nothing here logs: the domain layer is pure, and the visible-feedback
obligations of an error or a refusal are discharged at the runtime boundary that
consumes this vocabulary, from Slice 02 onwards.

Microphone ownership is likewise not a matter of policy but of devices, and it
lives in its own contract: PRESENTATION holds exactly one physical input stream
and fans it out, Simple keeps the two-stream arrangement it has always had, and
wake word and manual key normalise to one typed `ExplicitAddressTrigger` —
[presentation-audio-capture.md](presentation-audio-capture.md). The wake word is a
configurable provider (`wake_word` settings block: `porcupine` or `openwakeword`,
disabled by default, read at Voice startup); in PRESENTATION the chosen engine
reads the hub's PCM and opens no stream of its own, in SIMPLE the openWakeWord
detector opens its own stream *instead of* Porcupine's — see
[OPERATIONS.md](OPERATIONS.md), « Mot d'éveil (bloc `wake_word`) ».

What *reads* this matrix at runtime is likewise a separate contract: which
situation an addressed turn constitutes, which speech kinds that situation
admits, why a preamble never fires in Presentation, and how a turn that
completed without a word is told apart from a turn that died —
[presentation-response-policy.md](presentation-response-policy.md).

## Control plane (Slice 02, derived since Slice 01b)

Slice 01 gave the vocabulary; this is what makes it live. One owner of the
effective value, one source of the mode, and deliberately no copy anywhere.

| Owner | What it owns | Where |
| --- | --- | --- |
| Core | the **effective live mode** and its **revision** | `jarvis/core/interaction_mode.py` |
| Core, per Board | nothing stored: the active **Board type** designates the mode (schema v9) | `jarvis/core/board_service.py`, `board_kind` of `work_boards.data` |
| Control Center | nothing: a **read-only relay** of Core's value and of the Board type's mode in `/api/status` (no mode control on screen; the Board card shows the type) | `jarvis/runtime/control_center.py`, `jarvis/runtime/interaction_mode_view.py` |
| Voice | a read-only **observation** of Core's value | `jarvis/runtime/interaction_mode_observer.py` |

Conformance suites: `tests/unit/test_interaction_mode_control_plane.py` and
`tests/unit/test_interaction_mode_protocol.py`.

### Persistence owner — none: the mode is derived from the Board type

**No mode is persisted anywhere** (Slice 01a of
`jarvis-board-ui-wheel-dossier-refactor`, schema v9; [boards.md](boards.md#board-type)).
A Board has one fixed type, chosen at creation (`board_kind`: `assistant`,
`presentation`, `meeting`); the mode it designates is `board_kind_mode(kind)`,
and the behaviour that runs is `behaving_interaction_mode` of it (a Réunion
Board behaves as assistant, the trace says `meeting_planned`). `BoardService`
requests that mode through the strict `request()` at Core start
(`source="board_restore"`) and on every Board switch (`source="board_switch"`).
The v9 migration turned every stored per-Board mode into the Board's type once
(rules in [boards.md](boards.md#persistence)).

**Writers (Slice 01b).** There are exactly two, both in Core's process:

| Writer | Source | Lifetime |
| --- | --- | --- |
| `BoardService` | `board_restore` (Core start), `board_switch` (every switch) | the mode of the active Board's type |
| Presentation Studio run | `presentation_studio_run`, in process (`presentation_studio_playback.py` › `start` / `_restore_mode`) | **transient**: entered at run start, restored to the mode held before the run — the Board type's — at its end ([presentation-studio.md](presentation-studio.md#playback-roles-and-speech-authority-level-3-slice-01c-decision-a)) |

Every former outside writer **refuses with the same stable code and sentence**
(`INTERACTION_MODE_DERIVED` / `INTERACTION_MODE_DERIVED_MESSAGE`,
`jarvis/domain/interaction_mode.py`): « Le mode d'interaction suit le type du
Board actif : il ne se règle plus à part. Pour présenter, ouvrez ou créez un
Board Présentation ; pour revenir au mode simple, ouvrez un Board Assistant.
Rien n'a été changé. »

| Former writer | Answer now |
| --- | --- |
| `POST /v1/interaction-mode` (Core), any source, `presentation_studio_run` included | 409 `{"error": {"code": "interaction_mode_derived", …}}`, trace `interaction.mode.refused` (warning); `LocalCoreClient` has no write method |
| `POST /api/interaction-mode` (Control Center) | 409, `X-Jarvis-Error-Code: interaction_mode_derived`, the sentence as body, journal `interaction.mode.refused` (warning); nothing written, nothing asked of Core |
| `settings_set("interaction_mode", …)` (`jarvis-console` MCP) | `interaction_mode_derived`, the sentence plus the Board tools to use; journal `settings.tool_refused` |
| the bottom-left HUD chooser | removed with its module by Slice 02 of the wheel/dossier refactor (see *The Control Center: no mode control* below); until then it sent nothing and explained in place |

The routes stay so that a page, tool or client of an older version reads a
named refusal instead of a 404 or 405.

**The legacy global key.** An older `runtime/control-center-settings.json` may
still carry `"interaction_mode": {"schema_version": 1, "mode": …}`. It is **left
in the file** (no destructive cleanup of a user file) and is **neither read nor
written** by anything: not the status, not `/api/settings`, not a replay. The
module that owned it (`interaction_mode_settings.py`) and the Control Center's
replay (`startup`, `core_restart`, `save_retry`, `interaction.mode.replay_retired`)
are deleted. A Core without Boards (older than the board-session handoff) keeps
its default, assistant: nothing replays a mode to it any more.

**A switch to the Board already active re-applies its type's mode**
(`switch_noop`, `board_service.py`, `source="board_switch"`; idempotent when it
is already in force). With the outside writers gone, the live mode can differ
from the Board type only during a Studio run or after a failed Studio restore
(`mode_restore_failed`): the no-op switch (sent by the protocol or the brain's
`board_switch`; the page's Boards control sends none) is one more way back, at
the accepted cost of stopping a Studio run that held a transient mode on that
Board. The `switch_noop` trace carries the resulting `mode` and `mode_source`.

### Live-truth owner — Core

`InteractionModeService` holds one `InteractionModeState{mode, revision, source,
changed_at}`. Nothing is persisted there: an effective mode is a fact of this
process's life, derived from the active Board's type (`BoardService`, above).

- `request(value, source)` is the **explicit, in-process** path, called by
  `BoardService` and the Studio only. An unreadable value is an error
  (`interaction_mode_unknown`), never a silent fallback; REUNION is refused by
  Slice 01's `ensure_activatable`. It returns the state and a **disposition**
  (`applied` / `unchanged`), which `BoardService` traces.
- `request()` is the **only** entry point, and it is strict; no tolerant twin.
- `refuse_external_request(value, source)` is what `POST /v1/interaction-mode`
  calls: it traces `interaction.mode.refused` (`interaction_mode_derived`, the
  received value and source bounded to 64 characters) and returns the error the
  route serialises. It changes nothing.
- One `asyncio.Lock` serialises every change, so concurrent requests produce one
  revision per real change. **Idempotent**: re-requesting the current mode bumps
  nothing and publishes nothing. The revision starts at 0 (nobody has asked
  anything yet) and only ever increases *within one epoch*. Honest note: the
  lock's critical section currently contains no `await` that yields, so today
  the guarantee is really held by the single-threaded loop; the lock is there
  for the day it does, and a comment in the code says so.
- The change event carries the **state**, not the catalogue. `supported_modes()`
  is constant, the observer ignores it, and the snapshot already publishes it —
  putting it in every event would hand subscribers a second door to "what
  exists".
- Publication happens outside the lock, and a bus failure never loses the state
  (`interaction.mode.publish_failed`): a subscriber that missed the event finds
  the whole state in the snapshot, which is what the snapshot is for.
- **`add_listener(callable)` (added by Slice 04)** is the seam for Core state
  that must react *at the instant the mode changes*, not one event-loop hop
  later. It is called after the new state is assigned, outside the lock, and
  **before** `_publish`, with no `await` in between — so a listener always reads
  the new value, cannot deadlock, and cannot run after a subscriber has learned
  the mode moved. That ordering is the guarantee, and
  `test_la_seance_est_retiree_avant_que_le_changement_ne_soit_publie` fails if
  it is inverted.
  `add_listener(callable, with_state=True)` hands the listener the change's
  `InteractionModeState` (mode, revision, source) instead of the mode alone;
  `remove_listener(callable)` unsubscribes. A request that changes nothing
  (`disposition: unchanged`) reaches no listener and publishes nothing (the
  former `with_unchanged` flag left with the per-Board mode writes, Slice 01a).

  The contract is deliberately narrow: typed mode in, synchronous, no veto. A
  listener that raises is journalled (`interaction.mode.listener_failed`) and
  swallowed — a piece of state refusing to let go must not block a user leaving
  PRESENTATION. The exception text is clipped at
  `MAX_TRACE_EXCEPTION_CHARS` (200), like every other value this module copies
  into the journal from elsewhere.

  Its one caller in Core is the `PresentationWorkingSetStore` that
  `JarvisCoreApplication` builds — which, after Slice 11, has **no producer**:
  the session that is actually fed lives in the Voice process, because Slice
  10's addressed turn reads the store inside a frame an AST guard keeps
  await-free, and a cross-process store would make that read blocking. The Core
  instance is retained rather than removed; the asymmetry is stated in
  `docs/ARCHITECTURE.md` and in the Slice 11 report instead of being tidied
  away by a rollback of Slice 04.

  Voice has the same seam, for the same reason. `InteractionModeObserver`
  carries `add_listener` (Slice 11), and its subscriber is the PRESENTATION
  composition (`jarvis/runtime/presentation_runtime.py`): leaving PRESENTATION
  must hand the microphone back **at** the change, not a round trip later. What
  the store holds, and for how long, is its own contract:
  [presentation-working-set.md](presentation-working-set.md).

### Routes and events

| Route | Owner | Meaning |
| --- | --- | --- |
| `GET /v1/interaction-mode` | Core | effective mode, revision, epoch, source, advertised modes |
| `POST /v1/interaction-mode` | Core | **always** 409 `interaction_mode_derived` (Slice 01b), whatever the body or source |
| `GET /api/interaction-mode` | Control Center | the same block as `interaction_mode` in `/api/status` (read-only) |
| `POST /api/interaction-mode` | Control Center | **always** 409 `interaction_mode_derived` (Slice 01b); nothing written |
| `GET /api/status` | Control Center | `interaction_mode`: `mode`, `label`, `revision`, `epoch`, `source` (`core` or `local`), `core_reachable`, `error`, `board_mode` / `board_mode_label`, `modes` |

`/api/settings` carries no `interaction_mode` block: the mode is not a setting.

The event is `interaction.mode.changed` on `CoreEventBus`, therefore relayed as
is by `/v1/events`, payload `{mode, label, revision, epoch, source, changed_at}`.

Both the effective value and the Board type's mode appear in `/api/status`, and
they are named apart (`mode` vs `board_mode`). They differ on a Réunion Board —
`meeting`, designated and never effective — and during a Studio run;
publishing only one of them would either lose REUNION from the status (decision
02) or make it look as though it behaves (decision 14). No page reads
`board_mode` since the mode HUD left (Slice 02): it stays a diagnostic field of
the status, read by tests and operators. `board_mode`
is `null` when the active Board cannot be read (`interaction.mode.board_unknown`,
throttled) or the Control Center knows no Core. When Core is unreachable, the
block is the named local fallback (`source: "local"`, `core_reachable: false`,
`revision: null`): the behaviour of `board_mode` when it is known, else assistant.

### No restart (decision D15)

Interaction mode does **not** enter `VoiceComposition.configuration_id`
(`jarvis/runtime/voice_composition.py`). That SHA-256 is what
`VoiceSwitchCoordinator` compares to decide whether to restart the Voice
process, and a restart triggered by switching to Presentation would cut the
audio at the worst possible moment. So:

- nothing on the mode path recomputes a composition or writes on `VoiceSwitchBus`;
- the mode travels as a live event, and Voice's `InteractionModeObserver` holds
  the last value it saw, guarded by the revision: an event older than or equal
  to the one held is ignored, so two crossing messages cannot walk backwards.
  `adopt()` takes a `GET /v1/interaction-mode` snapshot through the same guard,
  and the mode follower (below) calls it on every successful subscription — so
  a resume after a stream gap is a real path, not a capability waiting for a
  caller;
- the observer applies `behaving_interaction_mode`, so a reserved mode can never
  become running behaviour even if something upstream published one.

Three independent assertions pin this: the `configuration_id` is byte-identical
across mode changes, no `voice.switch.requested` line is journalled, and no
switch request file appears.

### The mode follower: one feed for the life of the process

`runtime/interaction_mode_observer.py` › `follow_core_mode(observer, core,
journal, *, backoff, token_file)` is Voice's process-lifetime mode feed. It is started by
`PersistentVoiceRuntime.run` and cancelled first thing in `close()`, so it runs
while Voice is idle (BACKGROUND) as well as during a session, and on **every**
voice architecture, legacy included.

- It subscribes to `core.events(on_connected=…)` and routes only
  `interaction.mode.changed` to `observer.observe`.
- On each successful (re)subscription it reads `GET /v1/interaction-mode` and
  `adopt()`s it: `CoreEventBus` replays nothing, so a change made during a gap
  is caught up at reconnect.
- It never raises. A failed subscription, a stream that errors or one that
  closes cleanly is an outage: it re-subscribes after `backoff` seconds
  (default 2), doubled up to `FOLLOWER_MAX_BACKOFF_S` (30), reset on reconnect.
  **One** warning line per outage (`interaction.mode.follower.outage`) and one
  info line when it ends (`interaction.mode.follower.resumed`), nothing in
  between. Only cancellation stops it.
- A refused handshake (401: Core restarted on its own and wrote a new session
  token) makes it re-read `token_file` (`PersistentVoiceRuntime(core_token_file=)`,
  `settings.token_file` in `app.py`) and set it on the shared client, the way
  `CoreWorkTransport` does. One info line `interaction.mode.follower.token_reread`
  when the token changed, never the token. Before, it kept the stale token and
  stopped following until Voice restarted.
- `SpeechScheduler`'s own feed (`handle_core_event`, `_resync_interaction_mode`)
  stays. During a session both deliver the same revision; the observer's
  epoch/revision guard turns the second into a no-op, so listeners are called
  once.

Consequence: switching to a Présentation Board while Jarvis is idle reaches
`PresentationCoordinator.observe_mode` at once, and the PRESENTATION session
(and its single microphone owner) opens without a wake. Switching back to an
Assistant Board closes it and hands the microphone back to the wake stack (the
resting detector, Porcupine or openWakeWord, reopens its own stream).

**PRESENTATION requires a continuous voice architecture whose answers pass
through JARVIS: `continuous_brain`, SIMPLE or FRONT_BRAIN.** The addressed turn
lives in `SpeechScheduler`, which `PersistentVoiceRuntime` builds only for a
session that spans several turns (`continuous`). On `voice_arch=legacy`
(one turn per press) no addressed turn can ever open; on DUPLEX (GPT-Live) the
model answers the room on its own, outside the turn-authority rule (P11). Both
are refused by `presentation_architecture_refusal`
(`jarvis/runtime/presentation_runtime.py`, wired as `app.py` › `precondition=`;
`_refused_by_precondition`) **before** touching the microphone, with reason
`legacy_one_turn_per_press` or `duplex_autonomous_output`. Because the follower runs on legacy too, that refusal happens
at the mode change: one `signals.alert` with the sentence that says what to
change, one `presentation.runtime.entry_refused` error line with code
`presentation_architecture_unsupported`, and the SIMPLE wake stack untouched.
Core still holds PRESENTATION as the effective mode — Voice reports it cannot
serve it; it does not overrule Core. When the mode then leaves PRESENTATION the
alert is cleared (`presentation.runtime.alert_cleared`); a coordinator that
posted nothing clears nothing, since the alert channel is shared.

Pinned by `tests/unit/test_interaction_mode_follower.py` (legacy) and
`tests/unit/test_presentation_turn_authority.py` (Duplex).

### Epoch: why a revision alone is not enough

A revision is **local to one life of Core**. It starts at 0 and resets on every
Core restart, while the Voice-side observer lives in the Voice process and
survives stream gaps — `SpeechScheduler._consume_core_events` reconnects
forever rather than rebuilding anything.

So `InteractionModeState` carries an `epoch`, drawn once when the service is
constructed, and it travels in both `GET /v1/interaction-mode` and
`interaction.mode.changed`. The observer holds `(epoch, revision)`:

- **different epoch, or none at all** (an older Core that does not send one):
  the state is taken **unconditionally** and the revision floor restarts from
  it. The bias is deliberately towards freshness — between serving the mode of
  the Board just opened and serving the one from before a restart, the second
  is the failure;
- **same epoch:** the monotonic guard. Older is discarded silently (a doubled
  message, or a resync snapshot arriving after the event it describes). Equal
  revision with a *different* mode is a Core inconsistency: discarded **and
  said**, because settling it by coin flip would let two processes diverge
  unnoticed.

Without this, a Core restart made Voice serve the wrong mode permanently and
silently: Core re-emitted revisions 1, 2, 3; the observer discarded them all as
"older"; the user opened an Assistant Board, Core applied SIMPLE, Voice kept PRESENTATION. This
is the residual risk `READINESS.md` §3 G4 wrote down as D15's other half.

### Restart reconciliation

- **Control Center starts or Core restarts:** nothing is replayed (Slice 01b).
  Core applies the active Board type's mode itself at start
  (`source="board_restore"`), so the Control Center only reads.
- **Voice restarts:** its observer starts at `assistant`/revision 0 and catches
  up on the **snapshot taken at each successful subscription**
  (`follow_core_mode`, from process start; also
  `SpeechScheduler._subscription_ready` during a session), then on events. `CoreEventBus` has no
  backlog and can evict a slow subscriber, so without that snapshot a Voice
  process started after the last mode change would sit at the default until the
  next one — which may never come, since a user who is presenting does not
  toggle modes to please the software. It never restarts *because of* a mode
  change.
- **Core and Voice both restart, in that order:** the case the epoch exists
  for. Voice holds a revision from the previous life of Core; the new life's
  epoch differs, so the first thing it says is believed, and the resync snapshot
  makes that happen at subscription time rather than at the next change.
- **Core restarts during a Studio run:** the run is memory and is gone; Core
  re-applies the Board type's mode at start, never the run's transient one.

### Diagnostics

All on `runtime/trace.jsonl`, dotted kinds like their neighbours. They carry
mode values, stable codes, revisions, counters and type names — never a
transcript, never free user text; a rejected value is truncated to 64
characters so a form field cannot fill the journal.
`test_aucune_trace_de_mode_ne_porte_de_contenu_utilisateur` drives every one of
these emitters and then checks each line's fields against one allow-list.

| Kind | Level | When |
| --- | --- | --- |
| `interaction.mode.applied` | info | Core: the mode actually moved (`source` says who: `board_restore`, `board_switch`, `presentation_studio_run`) |
| `interaction.mode.unchanged` | info | Core: an idempotent request — nothing moved. Counting real mode changes means filtering `.applied` |
| `interaction.mode.refused` | warning | Core: unknown value, REUNION, or any protocol request (`interaction_mode_derived`); Control Center: a refused choice (`interaction_mode_derived`, `requested` bounded to 64 characters) |
| `interaction.mode.board_unknown` | warning | Control Center: the active Board could not be read, or has no valid type (`invalid_board_snapshot`); throttled |
| `interaction.mode.observed` / `.ignored` | info / warning | Voice's observation (including a new Core life), and a discarded event: malformed, unknown mode, reserved mode, or an equal revision carrying a different mode |
| `interaction.mode.resync_failed` | warning | the snapshot taken at subscription did not come back; the next event will catch up |
| `interaction.mode.follower.outage` / `.resumed` | warning / info | Voice's process-lifetime mode follower lost its `/v1/events` subscription (once per outage, with `exception_type` when one was raised), then got it back |
| `interaction.mode.view_invalid` | error | Core answered off-contract; the named local fallback is shown instead, once per exception type |
| `interaction.mode.publish_failed` | error | the bus refused the change; the state is still held |
| `interaction.mode.listener_failed` | error | a synchronous `add_listener` subscriber raised; the mode change still went through, and the message names the real cause, clipped to `MAX_TRACE_EXCEPTION_CHARS` |

### What this slice deliberately does not do

No mode writer outside Core, and no Presentation behaviour whatsoever (Slices
06+). Meeting is advertised everywhere and activable nowhere; not a line of
meeting behaviour was invented.

## The Control Center: no mode control; Voice's presence on the Board card

**Removed by Slice 02 of `tasks/jarvis-board-ui-wheel-dossier-refactor/`
(D03).** The bottom-left mode button and its detail
(`control_center_interaction_mode.js`, `#interactionModeHud`, the SIMPLE /
PRESENTATION / REUNION chooser) are gone from the page, module and host
included: the mode follows the active Board's type (above), so a chooser could
only explain that it chooses nothing. What it carried that mattered — Voice's
**presence report** of a PRESENTATION session — moved, unchanged, to the
bottom-left **Board card** (`jarvis/runtime/control_center_boards.js`,
[boards.md](boards.md) › *Control Center Boards control*,
[control-center-shell.md](control-center-shell.md) › *Board card*), which took
the control's place and envelope on the bottom-left rail. The card shows the
Board's **type** (Assistant, Présentation, Réunion « prévu ») — the mode is not
shown separately anymore; the `interaction_mode` block of `/api/status`
(`mode`, `board_mode`, `board_mode_label`, `modes`) is unchanged; the card
reads only `mode` (and `core_reachable`) for the Voice presence line, the other
fields are diagnostics.

### One source of truth, and it is `/api/status`

The card holds **no mode state**. `refreshStatus` hands it, once a second,
the `boards`, `interaction_mode` and `presentation` blocks of the **same**
`/api/status` beat (`JarvisBoardsControl.gate(s.boards, s.interaction_mode,
s.presentation)`), and `statusLost()` when that poll fails. Up to one second
between a change made elsewhere and its appearance — the cost of the 1 Hz poll,
written down rather than paid with a second channel.

### The live Presentation session (presentation-interaction-mode, Slice 03)

The effective mode says what Core decided; Voice's report says what Voice did
with it. They diverge in exactly the cases that matter — a PRESENTATION refused
by the voice architecture, an entry that could not open the shared microphone, a
session that runs but is deaf to the room — and without this line the page
would show a Présentation Board while nobody was listening.

The `presentation` block is Voice's scalar report (`VisualSignalBus.presentation`
→ `.voice_presentation`, published by Slice 10, P7) and is `null` whenever Voice
is offline. Nothing else feeds it: no route, no setting, no second poll
(`test_boards_hud_js.py::test_no_new_settings_surface_for_the_voice_presence`).

`presenceOf(report, mode)` derives one state from the real keys:

| State | Derived from | Line on the card | Mark | `title` |
| --- | --- | --- | --- | --- |
| *(none)* | `presentation: null` (Voice offline) | hidden, `data-bd-presence="none"` | — | — |
| `listening` | `active: true`, `ambient_deaf` not `true` | *Écoute la salle* | filled dot, slow pulse (stops under reduced motion) | `blocker_code`, else the sentence |
| `deaf` | `active: true`, `ambient_deaf: true` | *Sourd à la salle* | ring | `blocker_code` (e.g. `presentation_transcription_unavailable`) |
| `refused` | `active: false`, `event: "refused"`, mode in force is PRESENTATION | *Refusé par la voix* (card stroke red) | red square | `last_failure_code` (`presentation_architecture_unsupported`, legacy or Duplex) |
| `entry_failed` | `active: false`, `event: "entry_failed"`, mode in force is PRESENTATION | *Entrée échouée* (card stroke red) | red square | `last_failure_code` |
| `inactive` | anything else | *Séance inactive* in PRESENTATION; **hidden** in SIMPLE (the ordinary state) | dashed ring | the sentence |

**`refused` and `entry_failed` only count while PRESENTATION is in force.** The
coordinator does not republish its report when the mode leaves PRESENTATION
after a refusal (there is no session to close), so the file still says
`event: "refused"` in SIMPLE. Believing it would paint a refusal that is no
longer true.

**A refusal written before the switch is ignored (`freshReport`).** The same
file also holds the previous session's refusal when PRESENTATION comes back,
until Voice reacts to the new switch. The card records the page's wall-clock
time of the **last beat that showed another mode confirmed by Core**
(`core_reachable: true`); a `refused` / `entry_failed` report whose `ts` is
older than that time minus `STALE_REPORT_MARGIN_S` (2 s) is treated as no
report at all (*Séance inactive*). The bound is deliberately **not** the first
beat showing PRESENTATION: Voice writes its refusal once, milliseconds after
Core's event, usually before the page's next 1 Hz poll, and that true refusal
would then be hidden for good since it is never republished. With no such beat
(page opened while PRESENTATION was already in force) or no `ts`, nothing dates
the report and it is believed. `ts` is Voice's clock and the bound the page's:
both run on the same machine, since the Control Center is served locally.

The state is shape **and** word, never colour alone. The full sentence joins the
card button's accessible name *before* its action (« … sourde à la salle …
Ouvrir la liste des Boards »), the card's polite live region
(`#boardsPresenceAnnounce`) announces it once when it changes, and the console
keeps `[boards] boards.voice_presence_shown {state, code}` (`warn` for a
refusal or a failed entry). The card's tooltip is short (`Board actif : <title>
(<type>) · Refusé par la voix (<code>)`); the presence line keeps the bare code
in its own `title`. During a Studio run shown in Variantes the card stays live
and drawn above it (`data-keep-live="run"`, rank 9150), so a refusal stays
visible; the way out of a run is the Studio's own stop — there is no mode
toggle on the card.

**Not optimistic, like the mode.** A click on the card opens the Board panel
and changes neither the mode nor the line; the line changes only when a status
beat brings another report
(`test_boards_hud_js.py::test_status_never_optimistic_after_click`).

Checked in a real browser against a **real** Control Center
(`tests/unit/test_boards_card_browser.py`: the server is `ControlCenter._app` on
loopback, Core is the real `InteractionModeService`, the harness writes
`.voice_heartbeat` / `.voice_presentation` as Voice would, and a **test-only**
route `POST /__test/board-mode` stands for the mode change `BoardService` makes
on a Board switch). "Within one poll" is counted in `/api/status` responses the
page actually received (≤ 2: the one possibly in flight at the change, plus the
next), not in milliseconds. Accessible names are read from Chrome's computed
accessibility tree, with real key events.

### Placement

The card sits where the mode button sat, on the bottom-left rail it shares with
the Bare Hands badge, the suppressed-gesture word and the scene notes, with the
same two rungs (52 / 86 px), the same lift above the status centre under 820 px
and the same move right of the Bare Hands column at 700 px and below. The
reasoning, measured for the mode button (no third rung; the second rung engaged
permanently once Bare Hands mounts so nothing jumps under a hand; the
horizontal exit below 700 px because the palette's height depends on its tool
count), is kept as the `GEO` comment of `control_center_boards.js` and in
[control-center-shell.md](control-center-shell.md) › *Board card*; the dodge
convention is still governed by `tests/unit/test_barehands_contracts_js.py`.

## The brain's handle: the Board tools, never a setting

« Passe en mode présentation / simple / réunion » is answered with the Board
tools of `jarvis-workspace` ([mcp/tool-contract.md](mcp/tool-contract.md)):
`board_list` gives each Board's `board_kind`; with exactly one Board of the
wanted type the brain switches to it (`board_switch`), with several it asks
which, with none it proposes to create one (`board_create` with `board_kind`)
and creates it if the user accepts. The rule is in
`jarvis/runtime/claude_local.py` › `BRAIN_WORKSPACE_PROMPT`, with the tools it
names; `BRAIN_SETTINGS_PROMPT` only says the mode is not a setting and points
there (never `settings_set`).

The `jarvis-console` MCP server (`jarvis/runtime/settings_mcp.py`) lists **no**
`interaction_mode` item and no `interaction` category. `settings_set` called
with `interaction_mode` anyway is refused before any request with the stable
code `interaction_mode_derived` and the shared sentence, followed by the tools
to use; the refusal is journalled (`settings.tool_refused`) and nothing is written.

## A sibling that reuses the pattern: Bare Hands calibration mode

The Bare Hands adaptive-calibration task (Slice 06) needed the brain to behave
differently while a calibration session is open on the page, and reused this
mode's **pattern** without becoming an interaction mode: a per-turn context
flag, a turn-brief addendum, a runtime gate, a closed capability table. Two
differences, both deliberate:

- **Owner.** The session is declared by the page to the **Control Center**
  (`POST /api/barehands/calibration-session`, heartbeat, expiry), so the Control
  Center attaches `context.calibration` itself in `agent_ask`; Core is not in
  the path and `observe_interaction_mode` is untouched. Outside a session the
  context is byte-for-byte what it was.
- **Orthogonal.** It is not a value of `InteractionMode`: a calibration can run
  in SIMPLE or PRESENTATION, and both addenda then apply.

The brief text is `BRIEF_CALIBRATION_MODE` (`control_center.py`, registered as
`backend.turn.calibration_mode`); the gate is the Control Center refusing
`calibration_*` tools outside a session and verifying the user's words before an
accept. Canonical contract: `docs/barehands-contracts.md` §17, decisions 50–55.

