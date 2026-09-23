# Interaction mode and output disposition (contract)

Handoff `tasks/jarvis-presentation-interaction-mode/`, Slice 01 (domain
contract). Pure vocabulary: `jarvis/domain/interaction_mode.py`,
`jarvis/domain/output_disposition.py`, `jarvis/domain/presentation_policy.py`;
conformance suite `tests/unit/test_interaction_mode_contract.py`. No I/O, no
persistence, no API, no UI, no prompt, no audio — Slices 02+ consume this.

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
