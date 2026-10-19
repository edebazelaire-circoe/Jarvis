# Slice 09 — Task/constellation graph UI for roles & relations

## Goal

Make roles, ownership and relation semantics immediately legible in the live/historical task graph without clutter or speculative planning.

## Dependencies

00-project-manager-readiness, 08-scene-projection-role-relations

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Per-role star/node identity.
- Mission Owner secondary badge.
- Task/mission origin summary.
- Distinct link grammar for Delegation, Communication, Adversary, QA, Handoff.
- Communication message affordance at/on relation and accessible board/detail panel.
- Relation details and explicit messages.
- Dense graph, zoom/pan/responsive/accessibility behavior.
- Finished actual history; no ephemeral finished nodes.

## Scope — out

- Showing future plan nodes.
- Using color as the only semantic cue.
- Revealing hidden reasoning.
- A full redesign of unrelated Control Center surfaces.

## Implementation steps

1. Run `/impeccable` design audit of current constellation/Agents graph and shell constraints.
2. Define a compact role visual grammar from Role Registry tokens.
3. Define relation visual grammar: Adversary visibly competitive (paired/double/curved treatment), QA review direction, Handoff direction, Communication message affordance, Delegation hierarchy.
4. Implement relation hit targets/focus/keyboard details and communication board surface.
5. Keep UI derived from Core/Scene semantic fields; no label parsing.
6. Test actual-vs-planned invariant and ephemeral absence.
7. Run viewport/zoom/browser matrix and Human Validation screenshots/session.

## Files likely touched

- `jarvis/runtime/control_center_scene_page.js` and related scene renderer modules
- Control Center styles/shell registry if new layer/panel required
- relation board/detail module
- browser tests
- `docs/control-center-shell.md` / `docs/OPERATIONS.md`

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

caveman; coding-guideline; impeccable

## Independent QA

Required: code-review; qa-verification; runtime-validation.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Frontend routing

This is frontend work. Prefer Claude where the workspace supports agent routing and run `/impeccable` before implementation/review. Preserve the Control Center shell/stacking/accessibility contracts.

## Human Validation

- `HV-ORG-09-01` — At a glance identify at least Developer, Web Research, Document Research and QA roles in one populated task graph without opening details.
- `HV-ORG-09-02` — Distinguish Delegation, Communication, Adversary, QA and Handoff links visually; confirm Adversary and QA cannot be confused.
- `HV-ORG-09-03` — Click/focus the Communication relation message affordance and verify the correct readable relation board opens and keyboard navigation works.
- `HV-ORG-09-04` — Observe a mission evolve and confirm only actual agents/relations appear; no speculative future plan nodes are shown.
- `HV-ORG-09-05` — At 200% zoom and a dense graph, confirm role labels, relation affordances and shell controls remain usable without major overlap.

See `human-validation.json`.

## Acceptance criteria

- [ ] A user can identify roles and major relation types at a glance.
- [ ] Adversary and QA are visually and semantically distinct.
- [ ] Communication link opens the correct explicit message board.
- [ ] No color-only semantics.
- [ ] No speculative future graph.
- [ ] Dense graph remains usable at supported sizes/zoom.
- [ ] Human visual checks pass.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- Start from the existing ephemeral/scene rendering (`control_center_scene_page.js`, `control_center_scene_layout.js`, `JarvisSceneView` and its `showEphemeral` setting) and keep it consistent with the Slice 08 path.
- `3351ef59` changed `control_center_scene_page.js` after the handoff baseline; the unmerged branch `task/jarvis-board-orbital-ui-workspace-rail` (worktree `bor`) also touches the Control Center UI: check both in the freshness step.
