# Slice 01 - Implementation report

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Commits | `584b51f` (implementation), plus the rework commit that carries this file |
| Scope | Pure domain vocabulary. No persistence, no API, no UI, no audio, no prompt wiring. |
| Canonical doc | `docs/interaction-mode.md` (new, Level 2+), linked from `docs/ARCHITECTURE.md` |

## 1. What was built

### `jarvis/domain/interaction_mode.py`

`InteractionMode{ASSISTANT="assistant", PRESENTATION="presentation",
MEETING="meeting"}`, with a `label` property returning the locked D02 labels
`SIMPLE` / `PRESENTATION` / `REUNION`.

- `InteractionModeStatus{READY, PLANNED}` — maturity, in the vocabulary of
  `VoiceAdapterStatus`.
- `InteractionModeDescriptor` — `mode`, `status`, `default_disposition`,
  `summary`; `label` and `implemented` are derived, never stored twice.
- `INTERACTION_MODES` — the single door to descriptors (`MappingProxyType`).
- `DEFAULT_INTERACTION_MODE = ASSISTANT`.
- `parse_interaction_mode` (value → mode | `None`, case-folded),
  `parse_interaction_mode_label` (label → mode | `None`, **case-exact**).
- `stored_interaction_mode` — display reading, never raises, `meeting` survives.
- `behaving_interaction_mode` — behaviour reading, never raises, `meeting`
  becomes assistant.
- `is_activatable`, `activatable_interaction_modes`, `ensure_activatable`
  (loud refusal, code `interaction_mode_not_implemented`, French message),
  `default_disposition`.
- `InteractionModeError(code, message)` — English stable code, French message,
  because `control_center.py` pipes `str(exc)` into the user-visible payload.

### `jarvis/domain/output_disposition.py`

`OutputDisposition{silent, visual_only, voice_only, visual_and_voice}` with
`shows` / `speaks`, and `parse_output_disposition`. Its own module, per the
Slice 00 G2 constraint.

### `jarvis/domain/presentation_policy.py`

`PresentationSituation` (7 values), `PresentationOutputPolicy` (frozen,
self-validating), `PRESENTATION_POLICY` (`MappingProxyType`), `policy_for()`,
`may_speak()`, `LOCKED_DECISIONS` (`D01`–`D14`), `PresentationPolicyError`.

### `tests/unit/test_interaction_mode_contract.py`

100 tests, full-sentence names, French/English as the surrounding suite does.

## 2. Reuse

**Reused**

- `SpeechKind{ACK, PROGRESS, QUESTION, RESULT, ERROR}` (`jarvis/domain/v2.py`)
  as the type of `speech_kinds`. It already drives the speech scheduler's
  policy; a second vocabulary would have created two truths about whether
  Jarvis may say a given thing.
- The `VoiceAdapterStatus{legacy_only, planned, ready}` descriptor convention
  of `jarvis/domain/voice_architecture.py`, which already separates
  "documented" from "actually exists" — exactly what REUNION needs. Minus
  `legacy_only`, which has no meaning here.
- The `XxxError(code, message)` convention of `VoiceConfigError`.
- `MappingProxyType` registries and frozen slotted dataclasses with a
  validating `__post_init__`, as the neutral layer does throughout.
- `importlib.util.resolve_name` import-scanning logic from
  `tests/unit/test_v2_architecture.py` for the G2 guard.

**Deliberately not reused**

- `ReflexAction{WAIT, BACKCHANNEL, SPEAK, PREAMBLE, DELEGATE}` — a surface-side
  reflex about one utterance in flight, not a per-situation manifestation
  policy. Different question, different lifetime.
- `SpeechPriority` — scheduling order within the speech lane. G5 reserves the
  P0–P4 work-lane model for Slice 08, and nothing here schedules.
- `BRAIN_NOT_ADDRESSED_ANSWER` — a magic string carrying a brain's textual
  verdict on one turn; orthogonal to a typed disposition.
- `AddressingDecision` — **untouched**, per G7. It is closed, wire-encoded and
  persisted. `requires_explicit_address` is a boolean field on a policy row, not
  a new enum value, and no admission rule was relaxed.
- The scene's `Disposition{ACTIVE, ARCHIVED}` — not extended, not shadowed,
  not imported.

## 3. How the axis-collision proof works (G1, G2)

Three axes are compared against, by importing all three:
`VoiceArchitectureId` (typed, `voice_architecture`), `VoiceArchitecture` from
`jarvis/v2_config.py` (the older runtime authority, `voice_arch`) and
`ConversationMode`.

1. **Value disjointness** and **member-name disjointness** against all three.
2. **Behavioural disjointness**, which is the stronger claim: each of the seven
   foreign values (`simple`, `front_brain`, `duplex`, `legacy`,
   `continuous_brain`, `open_room`, `solo_owner`) is fed to both parsers and
   must yield `None`, and to `stored_interaction_mode`, which must yield the
   default. No value of another axis can become a product mode.
3. **The named trap**: `VoiceArchitectureId.SIMPLE.name == "SIMPLE" ==
   InteractionMode.ASSISTANT.label` is asserted *true* — the collision is real
   one level up — and then `not hasattr(InteractionMode, "SIMPLE")` plus
   `pytest.raises(AttributeError)` pin that it cannot be written in code.

This proof found a real bug during implementation: the first
`parse_interaction_mode_label` uppercased its input, so `"simple"` — the voice
architecture *value* — resolved to `InteractionMode.ASSISTANT` through the label
door. The parser is now case-exact, which is sound because D02 locks uppercase
labels while every other axis in the repository carries lowercase values.

For **G2**, beyond `OutputDisposition` living in its own module: an AST guard
walks `jarvis/` and `tests/` and fails any file that imports the *name*
`Disposition` unqualified while also having the output vocabulary in scope. It
matches the name whatever module it came from, resolves relative imports with
`resolve_name`, catches `import … as …` and the re-export through
`interaction_mode`, and reads with `utf-8-sig` because one repository file
carries a BOM. Eight synthetic sources (five that must trip it, three that must
not) prove the guard still guards.

## 4. The policy matrix as encoded

| Situation | disposition | voice_allowed | requires_explicit_address | authorizes_action | speech_kinds | may_raise_attention_cue | decisions |
|---|---|:-:|:-:|:-:|---|:-:|---|
| `ambient_observation` | `silent` | no | no | no | — | no | D03, D11 |
| `visual_command` | `visual_only` | no | yes | yes | — | no | D09 |
| `knowledge_question` | `visual_and_voice` | yes | yes | yes | QUESTION, RESULT | no | D10 |
| `explicit_speak_request` | `voice_only` | yes | yes | yes | all five | no | D05, D10 |
| `command_confirmation` | `visual_only` | no | yes | yes | — | no | D09 |
| `command_error` | `visual_only` | yes | yes | yes | ERROR | yes | D09, D11 |
| `fact_check_attention` | `visual_only` | no | no | no | — | yes | D11 |

`disposition` is the default manifestation; `voice_allowed` is a **ceiling**,
not a default. Four invariants are enforced in `__post_init__`, so a
contradictory row cannot be constructed:

- a speaking default requires `voice_allowed`;
- `speech_kinds` is non-empty exactly when `voice_allowed`;
- `voice_allowed` implies `requires_explicit_address` — this *is* D11 "nothing
  speaks spontaneously in V1", as data;
- `authorizes_action` implies `requires_explicit_address` — this *is* D03
  "ambient speech never authorizes an action", as data.

Plus: every row cites at least one decision, and every citation must be in
`LOCKED_DECISIONS` (`D01`–`D14`). `dataclasses.replace` re-runs the validation,
so copying a row with one flag relaxed is refused as well.

Judgment calls, for the record: `knowledge_question` is `visual_and_voice`
while `explicit_speak_request` is `voice_only`, because a real question may
lean on a prepared visual whereas "say it out loud" should not seize the
presenter's screen. `visual_command` keeps `voice_allowed=False` as a hard
ceiling; the coordinator has carried the consequence to Slice 07, which must
classify a mixed "show me X and tell me the total" as `explicit_speak_request`
or `knowledge_question`.

## 5. Rework pass (second commit)

Ten findings from the two QA agents, all inside this Slice's own files.

| | Change |
| --- | --- |
| R1 | Split `confirmation_or_error` into `command_confirmation` (silent ceiling, no cue) and `command_error` (may speak as ERROR, may cue). "A success is not announced" is now data, not a caller convention. Seven rows. |
| R2 | Rewrote the G2 guard: name-based matching, `resolve_name` for relative imports, `import … as …`, re-export, `tests/` included, `utf-8-sig`, plus eight synthetic-spelling tests. |
| R3 | `decisions` validated against `LOCKED_DECISIONS` (`D01`–`D14`); `("Dfromage",)` used to pass. |
| R4 | `resolve_interaction_mode` → `stored_interaction_mode`, `effective_interaction_mode` → `behaving_interaction_mode`, so a Slice 03 HUD author cannot silently drop REUNION. A test asserts the two readings diverge on `meeting` and nothing else. |
| R5 | REUNION refusal message rewritten in French; the stable code stays English ASCII. Tested. |
| R6 | Deleted `_BY_CHANNELS`, `output_disposition()`, both `to_dict()`, and `interaction_mode_descriptor()` — zero callers, and Slices 02/03 own those boundaries. `may_speak`, `is_activatable`, `default_disposition` kept. |
| R7 | `presentation_policy()` → `policy_for()`, so it no longer shadows its module. |
| R8 | `is None` instead of truthiness in `stored_interaction_mode`; "an display" typo; corrected the doc claim about labels and values "never meeting" (`PRESENTATION` does pass the value door, harmlessly) and softened "the data cannot break" to what `__post_init__` and `dataclasses.replace` actually guarantee. |
| R9 | Removed the tautological `isinstance(..., bool)`; made the three matrix-wide loops non-vacuous by asserting they covered every situation *and* that the interesting case exists; added tests for the untested `interaction_mode_descriptor_invalid` branch; renamed the over-promising `test_no_meeting_behaviour_is_invented_anywhere_in_the_contract`. |
| R10 | This file. |

## 6. Validation

All foreground, narrow file lists (host runs under 2 GB free RAM).

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Run | Result |
| --- | --- |
| `test_interaction_mode_contract.py` (after rework) | **100 passed** |
| `test_v2_architecture.py` `test_voice_architecture_config.py` | **68 passed** |
| `test_scene_contracts.py` `test_reflex_gate.py` `test_v2_domain.py` | **378 passed** |
| `test_owner_voice.py` `test_surface_reflex_policy.py` `test_documented_routes.py` `test_work_state_store.py` `test_third_party_bootstrap.py` | **178 passed** |

Before the rework: 79 tests in the contract suite, all passing, and the same
guard suites green. None of the 26 pre-existing baseline failures was touched,
fixed, or added to.

## 7. Nothing refused, two notes

- The handoff decision log holds **D01–D14**; the dispatch brief referenced
  D01–D15. D15 (restart semantics) lives in `READINESS.md` §6 and binds Slice
  02, not this one. The rows cite only D03, D05, D09, D10, D11, and
  `LOCKED_DECISIONS` stops at D14 deliberately — extending it means adding the
  decision to the log first.
- The coding guideline's documentation chain names `docs/CONTEXT.md` and
  `docs/documentation-level-registry.yaml`, **neither of which exists in this
  repository**. The actual convention was followed instead: a dedicated
  `docs/<concept>.md` contract (as `scene-model.md` and `conversation-events.md`
  do), linked from `docs/ARCHITECTURE.md`. No feature `INDEX.md` exists for
  interaction mode yet; `docs/interaction-mode.md` serves that role until the
  surface grows enough to need a folder.
