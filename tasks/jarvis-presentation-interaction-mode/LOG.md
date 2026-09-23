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

---

## 2026-09-23 — Slice 02, live interaction-mode control plane

Implemented at `52ab8cf`, reworked at `abc73c9`. Core owns the live mode plus an epoch and a
revision; the Control Center owns the persisted preference; Voice observes read-only over the
existing `/v1/events` stream. Three mandated QA passes ran: `qa-verification`, `code-review`,
`runtime-validation`.

### One blocking defect, found by QA and predicted by Slice 00

The observer's guard was `revision <= self._revision`. Core's revision is process-local and resets
to 0 on restart, while the observer is owned by `PersistentVoiceRuntime` and survives stream gaps —
`SpeechScheduler._consume_core_events` reconnects forever rather than rebuilding. So after a Core
restart the observer discarded every new revision as stale: **the user chose SIMPLE, Core applied
it, and Voice kept serving PRESENTATION.** Silent, with no recovery path (`adopt()` passed through
the same guard) and no test.

`READINESS.md` §3 G4 wrote this down as D15's residual risk before a line was implemented: *"the
mode changes live, but any path gated on a configuration change will not observe it, and Voice
keeps a stale view."* The slice implemented the D15 half and left the predicted half open. This is
the first time in this task that writing a risk down paid for itself.

**Fix:** Core stamps a per-process `epoch`; the observer holds `(epoch, revision)`; a different
epoch resets the revision floor; an **absent** epoch (older Core) is also accepted, so version skew
fails safe toward freshness rather than staleness. `adopt()` — which had zero production callers —
is now wired to a snapshot refetch on each successful `/v1/events` subscription.

### Proven in the running system, not only in tests

`runtime-validation` built a real Core + Control Center from `abc73c9` in an isolated runtime root
and exercised 6 Core lives, 7 Control Center lives, 16 mode requests, 213 trace lines. The
decisive evidence:

```
{"kind":"interaction.mode.observed",
 "message":"Nouvelle vie de Core observée : la révision du mode repart de zéro",
 "data":{"mode":"presentation","revision":1,"previous_revision":5,
         "code":"interaction_mode_core_restarted"}}
```

Revision 1 arriving while the observer held 5 — exactly what the old guard threw away — and the
user-driven change immediately after it adopted live. The resync seam earned itself too: the bus
event for revision 1 was published at `16:47:38.21` while the stream was still reconnecting at
`16:47:39.5`, so `adopt()` is what caught the observer up. `CoreInteractionModeTransport` also
survived a real token rotation (Core rewrites `core.token` on every start; the stream took a 401
and succeeded on the re-read).

Other runtime results: the replay fires **exactly once** when a late Core appears (96 polls, one
`reconciled`); log hygiene is **0 lines/min** over 179 s of idle polling with a non-default mode and
an unreachable Core, where the previous round could emit a warning per second; `configuration_id`
is byte-identical across assistant / presentation / meeting / absent (`4611e8d8…`), and no
`voice.switch.*` line or switch file ever appeared across 16 mode requests.

### Honestly not proven

A real Voice process was never started — it needs a Realtime credential and it opens the
microphone, which the user's own live Voice process is holding. QA exercised the production
`InteractionModeObserver` against the live Core over a real `/v1/events` socket, wired the way
`SpeechScheduler` wires it, which is a faithful stand-in but is **not** the Voice process. So
"nothing asks for a teardown" is proven; "no session is torn down" is not. That is the right
sentence to carry into Slice 11's end-to-end validation rather than a claim to bank now.

### For the Human

- The JARVIS stack running on this machine **predates this slice** (started 23/09 15:20, the code
  landed 18:03/18:32) and returns `"interaction_mode": null`. It must be restarted before any of
  this is reachable. Its Voice process is `continuous_brain`, so the observer path will be live
  once it is.
- `GET /api/status` now costs ~2.02 s when Core is down, because the slice adds a second Core
  round-trip to the page's only 1 Hz heartbeat. The two reads are gathered, so it is one wait and
  not two, and a failure cannot take the status down — but the page degrades to ~0.5 Hz while Core
  is unreachable. Flagged as a judgement call for a human eye, deliberately not changed.

### Issue raised, not fixed

`Issues/001-settings-read-swallows-a-corrupt-file.md`. `ControlCenter._settings()` swallows a
`JSONDecodeError` and returns an empty dict, so a corrupt settings file reads as a first launch
with no journal line — every setting gone at once. A UTF-8 BOM is enough to trigger it. This is
the exact confusion Slice 02 was built to prevent one level down, sitting underneath a reader that
loses the whole file without a word. Pre-existing and shared by every Control Center setting, so
fixing it inside a Presentation slice would be scope creep with a wide blast radius.

### Journal-truth pass — `0de10f8`, **Slice 02 APPROVED**

Two runtime findings closed. An idempotent rewrite no longer logs `interaction.mode.applied`, so
`.applied` is countable as "the mode actually moved" — and the implementer took the better route
than the one asked for: the verdict comes from **Core's** `disposition` in the POST answer, not
from comparing two local preferences. That distinction is load-bearing, because the stored
preference and the live value can legitimately diverge; after a direct protocol call, writing
PRESENTATION through the route changes the preference while moving nothing, and a local comparison
would have mislabelled it. A Core answering without a disposition falls back to the local
comparison rather than going silent.

The unreadable-setting line now names the stored value (bounded at 64 chars), so `fromage` and
`gruyere` are two incidents in the trace rather than one indistinguishable default.

Final state: **271 passed** across the interaction-mode, control-centre, speech-scheduler and
documented-routes suites, re-run by agent 0. Baseline failures untouched.
