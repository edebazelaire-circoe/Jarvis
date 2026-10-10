# Slice 22 - trace analysis (agent-trace-analysis) over the committed traces

Scope: Slice 22 changes no agent, prompt, tool or routing. It reads the traces that exist and asks whether they support the release claims. **No model was
run in this Slice** (cost; the traces below are not re-run), so nothing here is a new trace: it is a review of evidence already committed, and of what the
real-Core journey of this Slice shows that those traces cannot.

## Trace sources

| Source | Where | What it covers |
| --- | --- | --- |
| Slice 15, authoring (real Claude `sonnet`, real planner prompt, fingerprint `1c3275b6255d913d...`) | `slices/15-remotion-one-shot-authoring/evidence/authoring-real-traces.run-a.*`, `run-b.*` | 5 scenarios: rich brief (6 scenes), vague exploratory (5 x 3), one-shot report, custom layout, hostile text |
| Slice 21, verbs and ownership (real Claude, `jarvis-remotion`, isolated Core) | `slices/21-voice-tools-and-toolbrain/evidence/trace-analysis.md`, `remotion-real-traces.*` | 20 turns over two passes: install, ambient/unattested refusals, Studio, export, Slidecar refusal, props vs source routing, delegation |
| Gate | `scripts/verify_release.py::presentation_studio_findings` | the planner fingerprint of the code equals the one every authoring trace and the scripted rig carry (checked on this head) |

## Execution path (from the committed traces)

- Authoring: 4 tool calls per scenario (ToolSearch x2, `presentation_inspect draft_guide`, `presentation_draft_assemble`), 1 gate round to `delivered` in 4 of 5
  scenarios, 2 in the hostile-text one (the first draft was refused by the gate, the second delivered; the hostile instruction in the text was not obeyed). Cost
  $0.07 to $0.19 per scenario. The engine is Remotion in every case; nothing named an engine.
- Verbs: a gesture is one call (`remotion_setup`, `remotion_export`), preceded by at most the id chain (inspect variant, inspect scene); a refused gesture
  makes zero Core calls; "passe en Slidecar" makes no call and points at the card; a structural change registers `scene.source_request` in the turn before
  delegating (after the first pass found the reverse order and fixed it).

## Findings

| # | Severity | Finding | Evidence |
| --- | --- | --- | --- |
| T1 | **MAJOR (coverage, now closed by a test)** | No committed trace goes from an agent-authored deck to an **export**. Every authoring trace ends at `delivered`; every verb trace scripts the Remotion capability routes (the harness Core has no capability store). The two halves were each green, and the product was broken between them: an authored deck could not be exported (the render did not hand the composition its `data` input). Found by the real-Core journey of this Slice, not by any trace. | `test_remotion_release_flows.py` (assemble -> play -> edit -> export), defect 1 of the release report |
| T2 | MINOR | Same blind spot for the **Studio** on an authored deck (the work copy lacked `data`): fixed, unit-tested, not re-run in a real Studio with an authored scene. | defect 2 of the release report |
| T3 | OPTIMIZATION | The authoring traces start with `ToolSearch select:Agent` (one call and some seconds) even when the model then answers "je n'ai pas pu confier le travail à un sous-agent": the planner prompt invites delegation that the harness tool set cannot honour. Not a defect of the product (the real brain has the Agent tool), a property of the harness. | `authoring-real-traces.run-a.md` calls 1 and the final answer |
| T4 | OPTIMIZATION | `install-unattested`: correct and safe (zero Core calls, asks the user to repeat), the wording could say why in one sentence. | Slice 21 trace analysis |
| T5 | FLAGGED | The cold first `presentation_inspect` of a run takes about 18 s (MCP server import), unchanged since the Studio task. | `presentation-studio-release.md` real-model gate, item 4 |
| T6 | FLAGGED | The attestation proves "a user turn is in progress", not that the sentence asked for the gesture; a sub-agent launched by the brain on its own could call the source-edit route with a forged request. Residual risk 5 of the release report; a trace cannot show it. | Slice 21 LOG, `docs/remotion-runtime.md` section 13 |

## Missing trace evidence (said, not inferred)

- No real-model run on this head; the traces are older heads whose planner fingerprint equals the current one, and whose tool sets are the current
  ones (`jarvis-remotion` 6 tools, `jarvis-presentation` 12; the catalogue tests pass on this head).
- Not traced: the delegated sub-agent's own HTTP edit, the import verbs against the network, `remotion_upgrades` with a real model, real voice, a real Control
  Center page answering the turn attestation (a stand-in answered).
- LogBroker / journal: the real-Core journey and faults assert the normal-path and refusal events (`core.presentation_studio.*`, `engine_refused`,
  `reload_built`, `remotion.compile.done`) and the absence of any `slidecar_*` event on the refusal paths; no source text is asserted in a log by
  these tests (that is `test_presentation_studio_release_faults.py`, unchanged and green).

## Suggested follow-ups (none blocks the release)

1. One real-model trace that ends in an export of the deck it just authored (the missing link of T1), when the Human accepts the cost.
2. A real Studio opened on an authored scene in the Studio harness (T2).
3. Give the authoring harness the Agent tool or remove `select:Agent` from the scenario prompt (T3).
