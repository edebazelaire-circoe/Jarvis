# Testing and Quality

## Mandatory QA doctrine

- Every implemented Slice gets `qa-verification`.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime changes add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence/findings. The Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Machine checks must be exhausted before requesting a Human check.

## Automated test expectations

### Registry and navigation

- Exactly six top-level categories.
- Unknown category registration fails loudly.
- Duplicate section IDs fail loudly.
- Legacy aliases resolve to the expected new category/section.
- New modules do not mutate the top-level category list.

### Persistence/regression

- Settings save payloads are byte/field compatible where behavior is unchanged.
- Unknown/inactive legacy fields survive unrelated saves.
- Credentials never return secret values.
- Memory env/file/default precedence is unchanged.
- LocalStorage appearance settings retain their existing keys and immediate renderer behavior.
- Wake-word restart semantics remain unchanged.

### UI lifecycle

- Switching categories destroys stateful controllers that require cleanup.
- Pending requests do not render into detached surfaces.
- Dirty drafts are preserved or explicitly guarded according to the owning module's current contract.
- Escape/outside-click behavior matches the new shell contract.
- No focus trap regressions and no focus loss after local re-render.

### Accessibility

- Keyboard-only traversal of category navigation and controls.
- Visible focus for all interactive elements.
- Labels and descriptions associated with fields.
- Status/error regions keep appropriate live-region semantics.
- Reduced-motion setting respected.
- Contrast and disabled/read-only states remain distinguishable without relying on color alone.

### Responsive/visual

Machine screenshot comparison is preferred where the host supports it. Validate common desktop sizes and at least 100% and 125% browser zoom before Human review.

## Existing regression suites likely relevant

- `tests/unit/test_control_center_mvp.py`
- `tests/unit/test_control_center_quality.py`
- `tests/unit/test_control_center_voice_architecture.py`
- `tests/unit/test_wake_word_settings_ui.py`
- `tests/unit/test_agent_cli_settings_ui.py`
- `tests/unit/test_routing_settings_screen.py`
- `tests/unit/test_control_center_memory_settings_js.py`
- `tests/unit/test_scene_settings_ui.py`
- appearance/scene/Bare Hands UI tests discovered by Slice 00
- sub-agent Settings tests discovered from the current organic-agent-orchestration implementation

The Project Manager must update the exact command list after the blind audit rather than trusting this list as exhaustive.
