# Slice 06 - Local runtime security, capabilities and bounds

## Goal
Prevent agent-authored Remotion code and imported templates from acquiring arbitrary Jarvis filesystem, shell, network or plugin authority.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Isolate process/user/working directory as supported; only allow approved source+asset roots and dependencies.
- Define network and asset fetch policy, local-only ports, CSP/iframe boundary and process timeout/memory control.
- Validate archives/source imports; prohibit implicit npm arbitrary install.
- Report violations as typed errors and preserve source for diagnosis.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
04-remotion-one-time-provisioning, 05-remotion-project-source-contract

## Implementation Steps
1. Isolate process/user/working directory as supported; only allow approved source+asset roots and dependencies.
2. Define network and asset fetch policy, local-only ports, CSP/iframe boundary and process timeout/memory control.
3. Validate archives/source imports; prohibit implicit npm arbitrary install.
4. Report violations as typed errors and preserve source for diagnosis.

## Files Likely Touched
- `docs/SECURITY.md` (verify actual final-branch path before editing)
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Adversarial source/dependency/file path/URL tests; real process stop/kill, resource limits and privilege review.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- No untrusted template can read secrets or act as Jarvis; isolated crash does not take Core down.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/SECURITY.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- The existing prefab sandbox (`docs/SECURITY.md` section 16, prefab frame `<iframe>`) is the precedent for the browser side; extend it, do not invent a second CSP model. Server-side (Node build/dev process) isolation is genuinely new.
- Hostile-source test corpus: reuse the style of `tests/unit/test_presentation_studio_authoring_*` hostile-input nets and `test_presentation_studio_release_faults.py` rather than starting from zero.
