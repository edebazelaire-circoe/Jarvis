# 04 — Testing and Quality

## QA doctrine

- Every implemented Slice gets `qa-verification`.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent-facing operations/routing add `agent-trace-analysis` using real traces.
- Regressions introduced by the current Slice block approval.
- Human validation occurs only after machine validation is exhausted.

## Required automated coverage

### Contract/schema

- valid and invalid prefab definitions
- version/provenance rules
- base/system mutation gate
- structured input validation
- unknown/missing field behavior
- event contract validation

### Runtime lifecycle

- mount exactly once
- update without leaking duplicate handlers
- unmount cleanup
- repeated create/destroy cycles
- behavior failure containment
- style isolation/scoping
- child/composed prefab lifecycle if supported

### Scene integration

- instance owner/provenance retained across scene updates
- show/hide/focus/destroy semantics
- scene rerender does not accidentally destroy live instance state unless contract says so
- one object cannot mutate a sibling through uncontrolled DOM access

### Agent operations

- catalog search/list/inspect are read-only
- instantiate/fork/create/save operations have distinct contracts
- direct base modification refuses requests without explicit base-edit intent/gate
- malformed generated prefab is rejected before publication
- trace shows who/what created or modified a prefab definition

### Visual/runtime

- each migrated window family has representative browser coverage
- resize/layout and focus behavior
- keyboard accessibility for interactive prefabs
- checklist/data-driven proof with empty/single/many items
- variable changes such as color do not require source mutation

## Human validation

Human checks are reserved for product judgments that automated tests cannot settle, especially whether the recovered window families feel correct and whether library management makes base/variant/custom provenance understandable.
