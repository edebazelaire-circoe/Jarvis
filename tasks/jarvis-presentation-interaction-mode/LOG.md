# Execution Log

Reserved for implementation agents. Record durable execution notes, decisions caused by repository drift, validation evidence references, and cross-slice handoffs here. Do not use this file for ephemeral scratch notes.

---

## 2026-09-23 — Slice 00, Project Manager readiness gate (agent 0)

**Outcome: `READY`, conditional on Human decisions W1 and D15.** Full record in
`slices/00-project-manager/READINESS.md`.

- Branch `task/jarvis-presentation-interaction-mode` created from `main` @ `ddcdb71`, which is
  exactly `task.json.source_snapshot.sha`. **Zero snapshot drift.**
- Handoff mirrored from Drive into `tasks/jarvis-presentation-interaction-mode/`: 48 files,
  every byte size matching its Drive source, all 25 JSON files parsed. Committed as S0.
- Blind repository audit performed by a sub-agent forbidden from opening `tasks/`, dispatched
  before any handoff conclusion was read. It confirmed every Level-0 claim in
  `docs/05-documentation-levels.md` independently.
- Regression baseline: 248 unit test files, **7022 collected, 6994 passed, 26 failed, 2 skipped**.
  The 26 are pre-existing at the branch point and listed by name in `READINESS.md` §4. Every
  implementer receives that list as "not yours, do not fix".
- **21 of the 26 are in Scene**, the reuse surface for Slices 08 and 09. Those two Slices get a
  narrower named green subset as their gate, and the Scene failure set is re-measured
  immediately before their dispatch.

### Gaps found by the audit, now binding constraints

| id | Gap | Slices |
| --- | --- | --- |
| G1 | Two voice-architecture axes coexist (`voice_arch` legacy/continuous_brain **and** typed `voice_architecture`); `_apply_voice` is a three-way exclusive branch that deletes `voice_architecture` | 01, 02 |
| G2 | `Disposition` is already taken by `jarvis/domain/scene.py` — use `OutputDisposition` | 01 |
| G3 | `PERSISTABLE_OPTION_IDS` is a 47-entry allow-list; a control absent from it fails to save *silently* | 02, 03 |
| G4 | `configuration_id` restart semantics undecided — escalated as **D15** | 02 |
| G5 | The work lane has no priority field at all; P0-P4 must live in the new speculative path, never on canonical `WorkItem` | 08, 10 |
| G6 | No generic UI seam and no framework; `openLifecycleSeam` is Bare Hands-specific; the z-index registry comment is test-asserted | 03 |
| G7 | `AddressingDecision` is closed, wire-encoded and persisted — do not widen it | 06 |

### Human decisions, both answered 2026-09-23

- **W1 — waived.** Workspace Task Type vocabulary does not exist in this environment; the Human
  granted the same waiver as for the four previous tasks. `task_type: null` stands everywhere.
- **D15 — decided: keep it out.** Interaction mode does not enter
  `VoiceComposition.configuration_id`. Core owns the effective live mode plus a revision counter;
  Voice consumes it through an explicit live event and never restarts on a mode change. Slice 02
  must carry a test asserting a mode change produces **no** `voice.switch.requested`.

Slice 00 is `READY`. Implementation dispatch is open.

### Lifecycle state

Drive folder is still in `to-do`. It must be moved to `current` by the Human before the first
implementation Slice is dispatched; the Drive connector available here can create, read and
update but cannot move folders.

---

## 2026-09-23 — Slice 01, interaction-mode and output-disposition contracts

Implemented at `584b51f` (six files, +1007, zero deletions, zero modifications to existing
modules). Pure domain vocabulary: `InteractionMode{assistant, presentation, meeting}` labelled
SIMPLE / PRESENTATION / REUNION, `OutputDisposition{silent, visual_only, voice_only,
visual_and_voice}` in its own module, and the Presentation policy matrix as data.

### QA

Both mandated passes ran independently and converged: `qa-verification` and `code-review`.
**No blocking findings from either.** Test evidence re-run by QA rather than taken on trust:
`test_interaction_mode_contract.py` 79 passed; with `test_v2_architecture.py` 87 passed;
voice-architecture contract set 134 passed; admission/policy set 67 passed. The Scene files
re-run returned exactly the declared baseline (5 failed / 82 passed for the three files
touched), so no regression. The diff adds only new files, so the regression surface is
structurally nil.

What QA verified rather than believed: all five canonical-reuse claims against their cited
sources; that `dataclasses.replace` — the realistic mutation path — is genuinely refused by the
policy invariants; and that `resolve_interaction_mode` survives 39 hostile inputs (bytes, nan,
Cyrillic homoglyphs, Turkish casing, embedded nulls, `object()`) without raising.

### The decisions are data, not prose

The point of this Slice, and it landed: D03 ("ambient never authorizes an action") and D11
("nothing speaks spontaneously") are two lines in `PresentationOutputPolicy.__post_init__` —
`voice_allowed ⇒ requires_explicit_address` and `authorizes_action ⇒ requires_explicit_address`.
A future row that contradicts either cannot be constructed. QA evaluated both implications over
all rows independently: zero violations.

### Rework (10 items) — delivered at `b75b8e9`, **Slice 01 APPROVED**

The one that mattered: `CONFIRMATION_OR_ERROR` was a single row serving two outcomes with
different policies, so `may_speak(..., ERROR)` returned true for a *success*, and the doc's
"a success is seen, not announced" was enforced only by caller convention — the very thing this
module exists to abolish. Split into `COMMAND_CONFIRMATION` and `COMMAND_ERROR`; the matrix is
seven rows.

Also fixed: the G2 AST guard missed relative imports, aliased module imports and the re-export
path; `decisions` accepted `("Dcheese",)` and now validates against `LOCKED_DECISIONS` = D01-D14;
`resolve_`/`effective_interaction_mode` became `stored_`/`behaving_interaction_mode` so Slice 03
cannot silently drop REUNION from the display; the REUNION refusal message is French (the code
stays ASCII); ~60-80 lines of serialization scaffolding guessing at Slice 02/03 boundaries were
deleted.

### Verification by agent 0, not taken on report

- `test_interaction_mode_contract.py` + `test_v2_architecture.py` + `test_voice_architecture_config.py`
  → **168 passed**, re-run directly.
- The matrix was evaluated independently: 7 rows, **zero invariant violations**, and the R1 claim
  holds in the data — a `COMMAND_CONFIRMATION` can neither speak (`may_speak` false for every
  `SpeechKind`) nor beep (`may_raise_attention_cue` false), while `COMMAND_ERROR` may speak
  `SpeechKind.ERROR`.
- **The G2 guard was probed end to end.** A file containing `from .scene import Disposition` plus
  `from .output_disposition import OutputDisposition` was dropped into `jarvis/domain/`; the
  rebuilt guard flagged it (`assert not ['jarvis/domain/_g2_probe.py']`). That exact spelling
  walked past the original guard. Probe removed.

Incidental find reported by the implementer, worth keeping: `tests/unit/test_third_party_bootstrap.py`
carries a UTF-8 BOM that `ast.parse` rejects, so any repo-walking AST test must read with
`utf-8-sig`. `test_v2_architecture.py` never hit this because it only walks `domain`/`ports`/`core`.

### Carried forward — do not re-derive these

- **Slice 07.** `VISUAL_COMMAND` carries `voice_allowed=False` as a hard ceiling, not a default,
  which is correct for V1. The consequence is that Slice 07's situation classifier must route
  "montre-moi le bilan **et dis-moi le total**" to `EXPLICIT_SPEAK_REQUEST` or
  `KNOWLEDGE_QUESTION`; under `VISUAL_COMMAND` no amount of asking unlocks speech. The failure
  path is already sound — a failed command becomes `COMMAND_ERROR`, which permits
  `SpeechKind.ERROR`, so errors stay audible.
- **Slice 02.** The label collision survives one level up: `VoiceArchitectureId.SIMPLE.name`
  equals `"SIMPLE"` equals `InteractionMode.ASSISTANT.label`. Nothing in the repo transports an
  architecture by `.name` today (QA grepped), but the settings-key design must not create the
  first such path, and the mode must never be read from a key that a voice-architecture value
  could also land in.
