# 04 - Testing and Quality

## QA doctrine

- Every implemented Slice: `qa-verification`.
- Any code change: `code-review`.
- Any user-visible/runtime behavior: `runtime-validation`.
- Agent prompts/tools/routing/score execution/cue matching: `agent-trace-analysis` with real trace evidence.
- Regressions introduced by the active Slice are blocking.
- Human validation comes only after machine validation is exhausted.

## Required deterministic test families

### Artifact / persistence

- schema round-trip;
- unknown/invalid field rejection;
- autosave atomicity and restart recovery;
- bounded undo/redo behavior;
- variant graph identity/provenance;
- scene-local variant selection;
- branch delete confirmation boundary.

### Edit engine

- control patch with no scene rebuild;
- structural patch affects only target scene;
- source edit hot reload affects only target scene when possible;
- failed hot reload rolls back or leaves prior valid scene intact;
- preview-only DOM changes never survive without commit;
- editor and voice path produce equivalent mutations.

### Score / cue safety

- only armed cue IDs are matchable;
- ambient transcript never becomes an arbitrary tool/action request;
- ambiguous cue does not auto-fire when confidence/predicate rules are not met;
- locked sequence timing is deterministic under replay;
- explicit address preempts sidekick automation;
- detour/resume restores a coherent score position;
- `Jarvis speech: none` prevents filler TTS.

### Playback

- user presenter role;
- Jarvis presenter role;
- rehearsal role;
- pause/back/forward/jump;
- auxiliary prefab/resource display then resume;
- scene remount under edit preserves/repairs score state.

### Variants

- create branch from current state;
- numeric display ID never changes/reuses unexpectedly;
- rename does not change identity;
- compare same logical scene across variants;
- semantic mix creates a new variant and preserves sources;
- promotion to template strips/parameterizes project-specific content.

### Fullscreen

Automated UI/runtime checks should prove state transitions, chrome policy, target display selection and restore behavior where the host exposes testable APIs. Physical borderless fullscreen still requires a workstation Human check.

## Regression boundaries

- `SIMPLE` behavior unchanged.
- `PRESENTATION` still works without a Presentation Artifact.
- ambient privacy/logging guarantees unchanged;
- Board/Session/Context state semantics unchanged;
- scene objects not owned by the presentation remain unaffected by presentation edits/reloads;
- no unbounded transcript, variant history or undo growth.

## Performance expectations

Exact numbers should be calibrated in Slice 01 against the host, but the user-visible budget is qualitative and strict:

- declared control edits feel immediate;
- structural edits do not rebuild the full deck;
- source edits refresh only the affected scene when technically possible;
- cue actions are fast enough to feel synchronized with live speech;
- Variant Explorer remains interactive with realistic project branch counts.

Turn these into measured repository-specific budgets during implementation rather than inventing unsupported millisecond thresholds now.
