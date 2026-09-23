# Interaction mode and output disposition (contract)

Handoff `tasks/jarvis-presentation-interaction-mode/`.

**Slice 01 — the domain contract**, everything up to "Deliberate limits of this
contract". Pure vocabulary: `jarvis/domain/interaction_mode.py`,
`jarvis/domain/output_disposition.py`, `jarvis/domain/presentation_policy.py`;
conformance suite `tests/unit/test_interaction_mode_contract.py`. No I/O, no
persistence, no API, no UI, no prompt, no audio.

**Slice 02 — the control plane**, the last section. Who persists the
preference, who owns the live effective value, the routes and the event, and
why a mode change never restarts Voice. Still no UI selector (Slice 03) and no
Presentation behaviour (Slices 06+).

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
until a mode has been chosen explicitly *and* readably, Jarvis behaves exactly
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
  stable code `interaction_mode_not_implemented`. A user who clicks `REUNION`
  reads why nothing happened instead of silently getting another mode.
- `behaving_interaction_mode(value)` — the **behaviour** reading. Total and
  silent: a `meeting` left on disk stays known to `stored_interaction_mode` —
  so an interface still shows REUNION checked — but produces assistant
  behaviour here. It never raises and never runs meeting behaviour, because
  there is none.

The two readings are named apart on purpose. They differ on exactly one input,
`meeting`, and that is the input where choosing wrong is expensive: feeding a
display from `behaving_interaction_mode` would erase REUNION from the interface,
which is precisely what decision 02 forbids. `stored_` is what the user chose,
`behaving_` is what actually runs.

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

## Presentation policy matrix

Encoded as data in `PRESENTATION_POLICY`, read by the runtime (Slice 07) through `policy_for()`
and `may_speak()`. A
policy in a prompt is not a policy — it holds until the model stops rereading
it. `disposition` is what the turn manifests by default; `voice_allowed` is a
**ceiling**, not a default.

| Situation | Disposition | Voice allowed | Needs explicit address | Authorizes action | Speech kinds | Attention cue | Decisions |
| --- | --- | :-: | :-: | :-: | --- | :-: | --- |
| `ambient_observation` | `silent` | no | no | no | — | no | D03, D11 |
| `visual_command` | `visual_only` | no | yes | yes | — | no | D09 |
| `knowledge_question` | `visual_and_voice` | yes | yes | yes | `question`, `result` | no | D10 |
| `explicit_speak_request` | `voice_only` | yes | yes | yes | all five | no | D05, D10 |
| `command_confirmation` | `visual_only` | no | yes | yes | — | no | D09 |
| `command_error` | `visual_only` | yes | yes | yes | `error` | yes | D09, D11 |
| `fact_check_attention` | `visual_only` | no | no | no | — | yes | D11 |

Reading the rows:

- **Ambient observation** — listening is not obeying. It stays silent, it
  authorizes nothing, and it cannot request speech (decisions 03, 11).
- **Visual command** — the screen answers, the voice keeps quiet (decision 09).
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
  and be spoken, as an `error` and nothing else: a silent failure is a defect,
  not discretion.
- **Fact-check attention** — a light and a short sound; Jarvis does not
  contradict a speaker aloud in front of their audience (decision 11).

`speech_kinds` reuses `SpeechKind` from `jarvis/domain/v2.py`, already the thing
that drives the speech scheduler's policy. A second vocabulary would have meant
two truths about whether Jarvis may say something.

### Invariants checked at construction

`PresentationOutputPolicy.__post_init__` refuses a contradictory row when it is
built, so a row added later cannot quietly contradict a locked decision:

- a speaking default requires `voice_allowed`;
- `speech_kinds` is non-empty exactly when `voice_allowed`;
- `voice_allowed` implies `requires_explicit_address` — this *is* "nothing
  speaks spontaneously in V1" (decision 11), as data;
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
[presentation-audio-capture.md](presentation-audio-capture.md).

## Control plane (Slice 02)

Slice 01 gave the vocabulary; this is what makes it live. Three owners, one
effective value, and deliberately no fourth copy anywhere.

| Owner | What it owns | Where |
| --- | --- | --- |
| Core | the **effective live mode** and its **revision** | `jarvis/core/interaction_mode.py` |
| Control Center | the **stored operator preference** | `jarvis/runtime/interaction_mode_settings.py` |
| Voice | a read-only **observation** of Core's value | `jarvis/runtime/interaction_mode_observer.py` |

Conformance suites: `tests/unit/test_interaction_mode_control_plane.py` and
`tests/unit/test_interaction_mode_protocol.py`.

### Persistence owner — the Control Center

The preference lives under its own root key in
`runtime/control-center-settings.json`:

```json
"interaction_mode": { "schema_version": 1, "mode": "presentation" }
```

- **Its own key and its own apply path.** It is never written through
  `ControlCenter._apply_voice`, whose first branch is a three-way mutually
  exclusive arm that *deletes* `voice_architecture`; an axis routed through it
  would inherit that exclusion and a `brain_compatibility` toggle would silently
  erase the mode. It is likewise absent from
  `voice_settings_schema.PERSISTABLE_OPTION_IDS`, the 47-entry allow-list, which
  is exactly why it has a route of its own instead.
- **Never a key a voice-architecture value could land in.**
  `VoiceArchitectureId.SIMPLE.name` is the string `"SIMPLE"`, which is also
  `InteractionMode.ASSISTANT.label`. The stored value is an internal mode value
  read through `parse_interaction_mode` — the door that refuses `simple` — and
  never through the label door.
- `load()` is the **display** reading (`stored_interaction_mode`): a stored
  `meeting` survives, so the interface keeps showing REUNION checked.
  `behaving()` is the **behaviour** reading; it is what gets sent to Core.
- Missing, mistyped, empty, unknown, or written under a foreign
  `schema_version`: the default, `assistant`, and Jarvis starts. `inspect()` and
  `describe()` separate "default because new" from "default because unreadable",
  and `stored_value` keeps the raw value visible instead of losing it silently.
  A foreign block is **not** archived — there is a single word at stake, against
  a whole archival mechanism to maintain — but it is stated, on screen and once
  per process in the journal (`interaction.mode.foreign_version`).

Writing is strict, with stable codes carried in `X-Jarvis-Error-Code`:
`interaction_mode_bad_payload`, `interaction_mode_missing`,
`interaction_mode_unknown`, `interaction_mode_unknown_field`,
`interaction_mode_schema_version_unsupported`, and
`interaction_mode_not_implemented` for REUNION (409, not 400: the request is
well formed and the mode exists — it is the behaviour that does not).

### Live-truth owner — Core

`InteractionModeService` holds one `InteractionModeState{mode, revision, source,
changed_at}`. Nothing is persisted there: an effective mode is a fact of this
process's life, and the preference that outlives it belongs to the Control
Center.

- `request(value, source)` is the **explicit** path. An unreadable value is an
  error (`interaction_mode_unknown`), never a silent fallback; REUNION is
  refused by Slice 01's `ensure_activatable`.
- `request()` is the **only** entry point, and it is strict. A tolerant twin
  lived here briefly and had no caller: the Control Center reads and normalises
  the setting at home, so Core never sees the raw value from disk. Tolerance
  therefore belongs to the owner of the persistence, and it is the Control
  Center that says a setting was unreadable (`interaction.mode.defaulted`, code
  `interaction_mode_unreadable`) — otherwise "started in SIMPLE" and "its
  setting was corrupt" leave the same trace, and the second is a failure. Two
  places for the same indulgence, one of them unreachable, was a promise
  nothing kept.
- The **disposition** (`applied` / `unchanged`) travels back with the answer to
  a `POST`, and it is what the Control Center journals against. Comparing two
  stored preferences instead would count a change Core never made: the
  preference and the live value can legitimately differ, for instance after a
  direct protocol call.
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

  The contract is deliberately narrow: typed mode in, synchronous, no veto. A
  listener that raises is journalled (`interaction.mode.listener_failed`) and
  swallowed — a piece of state refusing to let go must not block a user leaving
  PRESENTATION. The exception text is clipped at
  `MAX_TRACE_EXCEPTION_CHARS` (200), like every other value this module copies
  into the journal from elsewhere.

  Its one caller today is the **Presentation session working set**
  (`jarvis/core/presentation_working_set.py`), wired in `JarvisCoreApplication`:
  leaving PRESENTATION must drop what was said in the room immediately, and a
  `/v1/events` subscriber — right for *learning* a mode change — would leave it
  alive for a round trip, or longer if the bus dropped the event. What that
  store holds, and for how long, is its own contract:
  [presentation-working-set.md](presentation-working-set.md).

### Routes and events

| Route | Owner | Meaning |
| --- | --- | --- |
| `GET /v1/interaction-mode` | Core | effective mode, revision, advertised modes |
| `POST /v1/interaction-mode` | Core | request a mode; 409 + `interaction_mode_not_implemented` for REUNION, 400 + `interaction_mode_unknown` otherwise |
| `GET /api/interaction-mode` | Control Center | stored preference + `effective` block read from Core |
| `POST /api/interaction-mode` | Control Center | persist the preference, then apply it live |
| `GET /api/status` | Control Center | `interaction_mode`: effective value, revision, `stored`/`stored_label`, `modes` |
| `GET /api/settings` | Control Center | `interaction_mode`: the stored preference only |

The event is `interaction.mode.changed` on `CoreEventBus`, therefore relayed as
is by `/v1/events`, payload `{mode, label, revision, source, changed_at, modes}`.

Both the effective value and the stored preference appear in `/api/status`, and
they are named apart. They differ on exactly one input — a stored `meeting`,
displayable and never effective — and publishing only one of them would either
erase REUNION from the interface (decision 02) or make it look as though it
behaves (decision 14).

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
  and `SpeechScheduler` calls it on every successful subscription — so a resume
  after a stream gap is a real path, not a capability waiting for a caller;
- the observer applies `behaving_interaction_mode`, so a reserved mode can never
  become running behaviour even if something upstream published one.

Three independent assertions pin this: the `configuration_id` is byte-identical
across mode changes, no `voice.switch.requested` line is journalled, and no
switch request file appears.

**Known limit.** Voice's only `/v1/events` subscription lives in
`SpeechScheduler`, which is created only in continuous mode. In legacy mode
nothing in the Voice process subscribes, so neither the event nor the
subscription-time snapshot has an occasion to fire and the observer stays at the
default. That is the seam Slices 06+ will use; no second subscription was opened
for a consumer that does not exist yet.

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
  it. The bias is deliberately towards freshness — between serving the mode the
  user just chose and serving the one from before a restart, the second is the
  failure;
- **same epoch:** the monotonic guard. Older is discarded silently (a doubled
  message, or a resync snapshot arriving after the event it describes). Equal
  revision with a *different* mode is a Core inconsistency: discarded **and
  said**, because settling it by coin flip would let two processes diverge
  unnoticed.

Without this, a Core restart made Voice serve the wrong mode permanently and
silently: Core re-emitted revisions 1, 2, 3; the observer discarded them all as
"older"; the user picked SIMPLE, Core applied it, Voice kept PRESENTATION. This
is the residual risk `READINESS.md` §3 G4 wrote down as D15's other half.

### Restart reconciliation

- **Control Center starts:** `ControlCenter.start()` does two things, and
  **neither waits on the network**. It names, locally and at once, a stored
  preference that is not the one that will apply (unreadable, or reserved), and
  it arms the replay towards Core as a background task. Awaiting the replay
  would have delayed startup by seconds against a Core that accepts TCP and
  then hangs, which is exactly what a setting may not do.
- **Core starts later or restarts:** its revision is 0, the precise signal that
  it has never been told the preference. The status poll — the page's only
  regular heartbeat — **arms** the replay; it never performs it inline, because
  a 1 Hz read path must not contain a write. One replay task lives at a time,
  and it takes `INTERACTION_MODE_REPLAY_BACKOFF_S` before another poll can arm
  the next, so a Core that refuses forever costs one attempt per window instead
  of one per second. The warning is throttled by the same `ReportThrottle` the
  scene uses, and says how many lines it swallowed.
- **Voice restarts:** its observer starts at `assistant`/revision 0 and catches
  up on the **snapshot taken at each successful subscription**
  (`SpeechScheduler._subscription_ready`), then on events. `CoreEventBus` has no
  backlog and can evict a slow subscriber, so without that snapshot a Voice
  process started after the last mode change would sit at the default until the
  next one — which may never come, since a user who is presenting does not
  toggle modes to please the software. It never restarts *because of* a mode
  change.
- **Core and Voice both restart, in that order:** the case the epoch exists
  for. Voice holds a revision from the previous life of Core; the new life's
  epoch differs, so the first thing it says is believed, and the resync snapshot
  makes that happen at subscription time rather than at the next change.
- **The write order is deliberate:** persist, then apply. If Core is
  *unreachable*, the user's choice survives, a replay is armed, and the response
  is a 503 saying the mode is *saved but not yet applied*. If Core **refuses**
  (a version-skewed Core answering 400), the 503 says so instead and nothing is
  retried: promising a retry that will never succeed is worse than saying no.

### Diagnostics

All on `runtime/trace.jsonl`, dotted kinds like their neighbours. They carry
mode values, stable codes, revisions, counters and type names — never a
transcript, never free user text; a rejected value is truncated to 64
characters so a form field cannot fill the journal.
`test_aucune_trace_de_mode_ne_porte_de_contenu_utilisateur` drives every one of
these emitters and then checks each line's fields against one allow-list.

| Kind | Level | When |
| --- | --- | --- |
| `interaction.mode.requested` | info | a change is asked for |
| `interaction.mode.applied` | info | the mode actually moved; `changed: true` |
| `interaction.mode.unchanged` | info | idempotent write — the route was called and nothing moved; `changed: false`. Counting real mode changes means filtering `.applied`, so a no-op must not land there |
| `interaction.mode.refused` | warning | unknown value, or REUNION |
| `interaction.mode.not_applied` | error | saved, but Core did not take it |
| `interaction.mode.reconciled` / `.reconcile_failed` | info / warning | startup or Core-restart replay; the failure is throttled |
| `interaction.mode.defaulted` | warning | the stored preference is not the one that will apply (unreadable, or reserved) — said by the Control Center, the only process that sees the raw value. Both branches carry `stored_value`, bounded to `MAX_JOURNALLED_VALUE_CHARS`, so two different bad values are two different incidents in the trace |
| `interaction.mode.foreign_version` | warning | preference written by a newer Jarvis; once per process |
| `interaction.mode.observed` / `.ignored` | info / warning | Voice's observation (including a new Core life), and a discarded event: malformed, unknown mode, reserved mode, or an equal revision carrying a different mode |
| `interaction.mode.resync_failed` | warning | the snapshot taken at subscription did not come back; the next event will catch up |
| `interaction.mode.view_invalid` | error | Core answered off-contract; the stored preference is shown instead, once per exception type |
| `interaction.mode.publish_failed` | error | the bus refused the change; the state is still held |
| `interaction.mode.listener_failed` | error | a synchronous `add_listener` subscriber raised; the mode change still went through, and the message names the real cause, clipped to `MAX_TRACE_EXCEPTION_CHARS` |

### What this slice deliberately does not do

No UI selector (Slice 03 renders canonical status, not optimistic selection) and
no Presentation behaviour whatsoever (Slices 06+). Meeting is advertised
everywhere and activable nowhere; not a line of meeting behaviour was invented.

## The Control Center selector (Slice 03)

`jarvis/runtime/control_center_interaction_mode.js` — a compact, always-visible
mode button at the **bottom left** of the Control Center, with a three-choice
selector. It renders canonical status and nothing else. No Presentation
behaviour, no audio, no meeting behaviour.

### One source of truth, and it is `/api/status`

The module holds **no mode state**. Its only input is the `interaction_mode`
block of `GET /api/status`, handed to it by `refreshStatus` once a second
through `JarvisInteractionModeControl.gate(block)`, plus `statusLost()` when
that poll itself fails. That is the same pair (`gate` / `statusLost`) that
`JarvisScene` and `JarvisBarehandsCommandChannel` already use; the page learns
no second vocabulary and opens no second poll.

**Why the 1 Hz poll and not a pushed seam.** There is no framework, no store and
no generic seam in this page. The only pushed channel is `openLifecycleSeam`,
which is Bare Hands-specific (`control_center_barehands.js`). Generalising it
would have meant editing another feature's module to invent a mechanism nothing
else would use, to gain at most one second of latency on a setting changed twice
a day. The cost is written down instead: up to one second between a change made
elsewhere and its appearance — except right after a click, where the module
re-reads the status itself rather than waiting for the next beat.

### Four presentations for three modes

| Presentation | When | Chip checked |
| --- | --- | --- |
| `assistant` | SIMPLE is in force | SIMPLE |
| `presentation` | PRESENTATION is in force — amber and a breathing halo, because Jarvis is *not* behaving as usual | PRESENTATION |
| `unconfirmed` | `core_reachable: false` — the displayed value is the named local fallback (`source: "settings"`, `revision: null`), desaturated **and dashed** | **none** |
| `unknown` | the status poll itself failed | **none** |
| `other` | the server advertises a mode this page does not know, and it is in force | **none** |

`other` exists so that a mode added by a newer server is not painted as though
it were SIMPLE. It carries the ordinary text colour and no halo: it is running,
but this page cannot claim to know what it does.

The last two are states one *undergoes*, and they check nothing: checking a chip
would present a local value as authoritative. `REUNION` belongs to the same
family from the other end — advertised, explained, and never checked, because it
is never in force.

`stored_label` is what the user chose, `label` is what is running. When they
diverge (a stored `REUNION`, or a 503 that persisted the preference without
applying it) the button says so on its second line — `CHOISI : REUNION` — and
the selector's banner names both. Neither value is arbitrated away.

### Meeting is driven by data, not by its name

The chooser is built from the status `modes` catalogue; `implemented: false`
makes an option reserved. Declaring `meeting` implemented makes it selectable
with no code change, and declaring `assistant` unimplemented makes it reserved —
both are pinned by tests. A reserved option is `aria-disabled`, **not**
`disabled`: it stays reachable so it can say why it cannot be chosen.

Clicking a reserved mode performs **no request**. The server would answer 409
with the same meaning, and spending a round trip on a refusal known in advance
turns a deliberate product decision into what looks like a transport failure. The
409 branch still exists on the write path, because this page's catalogue is a
one-second-old photograph and an older Core can refuse a mode it advertises.

### Writing, and the absence of optimism

`POST /api/interaction-mode`, then a re-read of the canonical status. The
selected chip never moves because of a click; it moves because the status says
so. A failure therefore leaves the previous canonical mode selected with nothing
to roll back. Each outcome is distinct, keyed on the stable code carried in
`X-Jarvis-Error-Code`:

| Outcome | What the user is told |
| --- | --- |
| 200 | the next canonical status paints the new mode |
| 409 `interaction_mode_not_implemented` | a reservation, not a failure |
| 503 | *saved, but not yet applied* — the preference **is** on disk, and the divergence appears at once. The server's own sentence is shown verbatim, not re-prefixed |
| 400 (`_bad_payload`, `_missing`, `_unknown`, `_unknown_field`, `_schema_version_unsupported`) | the named refusal |
| anything else | the server's own message, verbatim |

Reaching that code required one addition to the page: `api()` now sets
`e.code` from the `X-Jarvis-Error-Code` header (falling back to a JSON `code`).
Before, a caller could only compare French sentences, which breaks at the first
rewording.

Each outcome also carries a **tone**, and the banner renders it: a 409 and a
503 are amber, only a real failure is red. Painting a reservation or a deferred
save in the danger colour would contradict the sentence beside it, and colour is
what a reader takes in first.

Two bounded waits, per RULE ZERO: a live counter on the button while a write is
in flight, and `WRITE_DEADLINE_MS` (12 s) after which the control releases,
says how long it waited, and lets canonical status describe what actually
happened. A late response can no longer paint anything. Each call owns **its
own** deadline ticket: one shared ticket let a late first request cancel a
retry's deadline, leaving the control disarmed for the life of the page.

The 12 s refusal is the one that does **not** reopen the chooser. Twelve seconds
after the click the user has moved on, and taking the focus back would snatch
whatever they are doing; it goes through the page's `toast()` instead, which
four other modules already use. Every other refusal reopens the chooser on its
reason, where the click just happened.

A refusal is cleared when the chooser closes. It used to outlive everything,
because `gate()` only drops it when the effective mode moves — deliberate for a
503, where the mode does not move and the sentence stays true, but wrong after a
locally refused REUNION, where the mode never moves at all and a Core that went
unreachable afterwards stayed hidden behind a stale sentence.

### Placement — a shared rail

Bottom left: `left: 18px`, with the vertical offset composed from two custom
properties, `--im-rail` (which rung of the bottom-left stack) and `--im-lift`
(clearing the voice hint).

**That corner is not empty, and the first version of this module wrongly said it
was.** Three elements already live on the same rail, all of them positioned by
stylesheets injected from JavaScript and therefore invisible to an audit that
reads only `control_center.html`:

| Element | Where | Position |
| --- | --- | --- |
| `#jarvisHands .jh-badge` | `control_center_barehands.js` | `left:18px; bottom:18px`, on a host at `z-index: 2147483000` — it paints over everything |
| `#jarvisHands .jh-note` | `control_center_barehands.js` | `left:18px; bottom:46px`, the suppressed-gesture word |
| `.sc-status` | `control_center_scene_page.js` | `left:18px; bottom:18px`, moving to `52px` when the hands badge is present |

The repository already had a dodge convention for this rail —
`body:has(#jarvisHands .jh-badge) .sc-status { bottom: 52px }`, with the badge
selector written out because a stylesheet cannot read
`JarvisBarehandsContracts.DOM.badgeSelector`, and a test refusing divergence.
This module **joins that convention** rather than inventing a second offset, and
added itself to the test that governs it
(`tests/unit/test_barehands_contracts_js.py`).

Two rungs, never a third: `railOne` (52 px) above a single occupant, `railTwo`
(86 px) above two. Beyond that the rail itself is overloaded, and rationing it
is not any single occupant's decision.

**The second rung is engaged permanently as soon as Bare Hands mounts, and that
is deliberate.** `shell.mount()` creates the suppressed-gesture word once and
only toggles its `display`; `:has()` cannot see `display: none`, so
`body:has(#jarvisHands .jh-note)` is true from the moment Bare Hands mounts.
The control therefore goes 22 → 86 in one step at mount and never moves again,
and the first rung is unreachable in the Bare Hands case — it serves the scene
alone, which has no transient word. **Do not make this reactive.** A suppressed
gesture appears exactly while the user is mid-gesture, and a control that jumped
34 px at that instant would be far worse than one that is permanently 34 px
over-conservative. The 34 px buys never moving under someone's hand.

The voice hint is centred at the bottom **at every width** and the page never
moves it, so the control lifts above it below 820 px. Measured, its longest text
(`F9 · VOICE HORS LIGNE`) is 200 px and the button's right edge is at 195 px, so
they would in fact only meet below ~708 px. The threshold stays at 820 px on
purpose: being early costs nothing, and a tight number breaks at the first
longer label.

**Below 700 px the left rail is abandoned entirely.** At that width the Bare
Hands column becomes centre-relative (`top: calc(50% + …)`) and its palette's
height depends on how many tools are installed, so no `body:has()` can compute
the clearance — and the rail lift made it *worse*, pushing the button deeper
into the palette. Measured in a real browser with a three-tool palette, the
button overlapped it by 64×46 at 700×600, 64×60 at 700×750 and still 64×24 at
700×900: at every height, not only short ones. Since the button is `z-index: 32`
and the palette `30`, the palette's bottom tool became covered and unclickable —
a Bare Hands regression caused by this control.

The fix is horizontal, not vertical: below 700 px the control moves
**right of the Bare Hands column**, whose width is fixed (`10 + 64 + 10 = 84 px`), which
makes the clearance independent of the tool count. The lift rises to 62 px there
because toasts grow upward from the bottom and bit by 12 px under 520 px wide.
The other candidates were measured and all contested: bottom-right by toasts at
every size, top-left by the GPT-Live banner. Free at 700×600, 700×750, 700×900,
500×700, 420×700 and 360×640.

The selector opens **upward**, and carries `max-height` plus `overflow-y: auto`
— it is anchored to the bottom of the screen, so without them its top would
clip off-screen with no way back, exactly as `.bgpop` guards against.

Stacking ranks (32 for the button, 36 for the selector) are the same as the Bare
Hands control's, for the same reasons, and are recorded in the registry comment
at the top of `control_center.html`.

Geometry and motion are asserted by `tests/unit/test_interaction_mode_hud_browser.py`,
which composes the served page, loads it in headless Chrome and reads
**computed** rects and styles. Three defects in this slice survived tests that
read the stylesheet as text — the rule was present, named the right selector,
and the cascade did the opposite.

### Limits

Accessibility: each option carries its own visually hidden description
(`aria-describedby`), because the visible `.im-hint` banner was the target of no
`aria-describedby` at all — a screen reader announced the label and the
reservation, never what the mode actually does.

The module depends on no other page module at **runtime** — not Bare Hands, not
the scene. Its stylesheet does name their selectors, because they share the
bottom-left rail and that is the repository's dodge convention; none of them has
to exist for this control to install and paint. It refuses to install, under a
searchable name, if its host element is missing;
that refusal is caught so it cannot take the rest of the single concatenated
`<script>` down with it. It writes no Presentation behaviour and invents no
meeting behaviour.
