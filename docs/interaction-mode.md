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
- `reconcile(value, source)` is the **stored-value** path. Total and silent in
  its outcome — anything unreadable yields `assistant` — but not silent in the
  journal: the fallback is named, because "started in SIMPLE" and "its setting
  was corrupt" must not look identical.
- One `asyncio.Lock` serialises every change, so concurrent requests produce one
  revision per real change. **Idempotent**: re-requesting the current mode bumps
  nothing and publishes nothing. The revision starts at 0 (nobody has asked
  anything yet) and only ever increases.
- Publication happens outside the lock, and a bus failure never loses the state
  (`interaction.mode.publish_failed`): a subscriber that missed the event finds
  the whole state in the snapshot, which is what the snapshot is for.

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
  for a resume after a stream gap;
- the observer applies `behaving_interaction_mode`, so a reserved mode can never
  become running behaviour even if something upstream published one.

Three independent assertions pin this: the `configuration_id` is byte-identical
across mode changes, no `voice.switch.requested` line is journalled, and no
switch request file appears.

**Known limit.** Voice's only `/v1/events` subscription lives in
`SpeechScheduler`, which is created only in continuous mode. In legacy mode
nothing in the Voice process subscribes, so the observer there stays at the
default until something calls `adopt()` with a snapshot. That is the seam Slices
06+ will use; no second subscription was opened for a consumer that does not
exist yet.

### Restart reconciliation

- **Control Center starts:** `ControlCenter.start()` replays the stored
  preference towards Core. It never raises and never blocks the startup — Core
  legitimately starts later. A failure is journalled
  (`interaction.mode.reconcile_failed`) and `/api/status` keeps showing the
  local fallback, explicitly named `source: "settings"`,
  `core_reachable: false`, with an `error.code`.
- **Core starts later or restarts:** its revision is 0, which is the precise
  signal that it has never been told the preference. The status poll — the only
  regular heartbeat the page has — replays it once. The condition extinguishes
  itself as soon as Core has taken the mode, and only comes back on the next
  Core restart.
- **Voice restarts:** its observer starts at `assistant`/revision 0 and catches
  up on the next event, or on a snapshot. It never restarts *because of* a mode
  change.
- **The write order is deliberate:** persist, then apply. If Core is
  unreachable, the user's choice survives and will be replayed, and the response
  is a 503 saying the mode is *saved but not yet applied* rather than letting
  anyone believe a presentation is armed.

### Diagnostics

All on `runtime/trace.jsonl`, dotted kinds like their neighbours. They carry
mode values, stable codes, revisions and sources — never a transcript, never
free user text; a rejected value is truncated to 64 characters so a form field
cannot fill the journal.

| Kind | Level | When |
| --- | --- | --- |
| `interaction.mode.requested` | info | a change is asked for |
| `interaction.mode.applied` | info | Core took it (Control Center and Core both name it) |
| `interaction.mode.unchanged` | info | idempotent write; a called route and a route never reached must not share a trace |
| `interaction.mode.refused` | warning | unknown value, or REUNION |
| `interaction.mode.not_applied` | error | saved, but Core did not take it |
| `interaction.mode.reconciled` / `.reconcile_failed` | info / warning | startup or Core-restart replay |
| `interaction.mode.foreign_version` | warning | preference written by a newer Jarvis; once per process |
| `interaction.mode.observed` / `.ignored` | info / warning | Voice's observation, and a malformed event |
| `interaction.mode.publish_failed` | error | the bus refused the change; the state is still held |

### What this slice deliberately does not do

No UI selector (Slice 03 renders canonical status, not optimistic selection) and
no Presentation behaviour whatsoever (Slices 06+). Meeting is advertised
everywhere and activable nowhere; not a line of meeting behaviour was invented.
