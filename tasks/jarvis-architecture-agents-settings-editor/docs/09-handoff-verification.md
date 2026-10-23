# 09 - Handoff Creation Verification

This document records the requested second-pass comparison performed during task creation.

## Pass 1 - completeness audit

The draft was compared against:

- the full current conversation about Architecture & Agents;
- the two user-approved UI references;
- live `main` evidence for roles/routing/model catalog/Tool Brain;
- the existing `jarvis-settings-ui-reorganization` task, especially its obsolete Slice 04.

The audit explicitly checked for common omissions:

- no Brain tab;
- right-click/context brain popup;
- draggable brain nodes;
- audio input/output endpoints;
- Tool Brain visibility;
- real semantic links rather than decorative links;
- locked vs editable vs disabled connection states;
- runtime effect of connection edits;
- future brain extensibility without showing fictional brains today;
- per-brain delegation intensity separated from global role/model choice;
- five delegation levels including never and exploratory/spread;
- all seven current canonical sub-agent roles;
- model/harness ordering and fallback;
- existing role instructions, Work Methods, skills/tools/loadout and robust revision/error states;
- removal of personality controls from this page;
- removal of old `Auto` / `Duplique` as the target product concept;
- Advanced relocation of CLI/permission/re-probe/diagnostics;
- server-authoritative model and topology state;
- reference-image features treated as illustrative when not requested.

## Corrections applied after Pass 1

The handoff was tightened to make these points explicit rather than implicit:

1. Node dragging persists layout only and never rewires the runtime.
2. Connection editing is port/compatibility validated and must roll back/refresh on runtime failure.
3. The brain popup summarizes connections but the graph remains the canonical connection editor.
4. Role policy migration from task profiles must preserve existing ordered candidates and provenance.
5. The existing Settings task Slice 04 is explicitly superseded to avoid conflicting implementation.
6. Frontend/backend branches avoid shared hot-file wiring until Slice 07 to preserve safe parallelism.
7. Mockup-only controls such as presets/test-flow/analytics are not requirements unless the live runtime justifies them.
8. Accessibility includes a non-right-click path for keyboard/touch users.
9. Reference-image global policy toggles are now explicitly classified as runtime-backed candidates, preventing accidental invention of unsupported settings while preserving them for audit.

## Pass 2 - final verification

A second comparison found every locked user requirement represented in at least one of:

- `README.md` locked decisions;
- `docs/01-decision-log.md`;
- `docs/06-functional-spec.md`;
- an implementation Slice acceptance criterion;
- final Slice 08 runtime/E2E scenarios.

No known user requirement from this discussion remains intentionally omitted. Remaining uncertainties are explicitly marked provisional and delegated to Slice 00/live runtime evidence rather than guessed.
