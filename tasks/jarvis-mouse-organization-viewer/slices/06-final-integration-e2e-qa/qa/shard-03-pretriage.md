# Shard 03: source baseline proof and Settings browser pretriage

Observed root revision: `97d56f1144cb721e7c5303f43ff71d291ed1d9bc`.
Completed canonical shard report: **1,155 passed, 3 failed, 3 skipped**, 1,161
collected, exit 1, green false, no session problems; all three failures unknown
to the dated known-failure list. Root log/JSON remain authoritative. No product
or root HEAD edits were made during this work.

## Bare Hands HUD served-page assertion: exact baseline reproduced

Node:
`tests/unit/test_barehands_hud_js.py::test_the_page_serves_the_pointer_before_the_hud_that_subscribes_to_it`.

Current traceback is line 987: raw HTML lacks the exact historic comment
`@shell-layer 32: .dock, #chatTab, #barehandsHud`.
The actual raw mirror at baseline and root is
`@shell-layer 32: .dock, #railDock, #barehandsHud, #boardsHud`; the current
comment does not put chatTab in that literal sequence. This failure occurs
after the test's pointer/HUD script-order, marker replacement, host and canonical
registry-row checks. It is the exact mirror-string assertion, not an observed
runtime stacking failure.

Under explicit bounded PM authorization, **only this source assertion** was run
in detached `C:/Projects/jarvis/movb` at exact
`c0858a8000e2ca23b57231edb8f46c643080ad07`, using the main checkout interpreter,
`--assert=plain --tb=short -p no:cacheprovider -q` and
`PYTHONDONTWRITEBYTECODE=1`.

Result: **1 failed, 35.16 s**, exit 1; same line 987 and exact assertion/message.
No browser, server or model was launched. Evidence:
[stdout](baseline-shard-03-hud.log), [JUnit](baseline-shard-03-hud.xml).
Recommendation to PM: classify this exact observed failure as proven
pre-existing source-assertion drift, unrelated to this task. No ignore or
product correction is proposed and the original shard remains red.

## Settings browser failures: still unclassified, no browser run

Nodes from `tests/unit/test_architecture_agents_settings_browser.py`:

1. `test_two_tabs_destinations_and_legacy_ids`, line 98: compound predicate
   `rt.category == advanced_diagnostics && rt.footer && rt.cmd && rt.perm`.
   The gate output does not preserve which member is false or the actual `rt`.
2. `test_architecture_canvas_and_core_window_work_together_then_subagents_tab`,
   line 150 via `assert_waits`: waits failed for hub `voice_audio` (~5 s),
   Personnalisation `conversation` (~10 s), and modal conversation tab (~5 s).
   These are upstream shared `open_settings()` navigation steps, so the output
   does not establish a failure of the later architecture/core-window action.

Source comparison against `c0858a80` finds byte-identical Settings test, served
fixture/helper, `_wake_word_settings_browser.mjs`, settings registry,
personalization, architecture settings, settings UI and brain-config panel.
The raw host HTML differs only by the four new scene/viewer module markers.
The relevant settings section and render functions are unchanged. This strongly
bounds the changed surface but does not prove a pre-existing browser failure;
the new scripts/pointer handlers could still affect timing or interaction.

### Concrete source discriminators

- Registry still defines `voice_audio`; Personalization detail rows still come
  from its registered sections and exclude only `agent_behavior`. `conversation`
  is still registered. Thus the missing selectors are not proven retired names.
- `cliTechnicalHtml()` deliberately omits command/permission fields until
  `SET.clis` exists (or when no CLI spec is detected). `/api/cli/agents` uses
  asynchronous `cli_catalog.detect_all`. The test's TOUR waits 400 ms after
  selecting Runtime & CLI, then samples those booleans, without an explicit
  field-hydration condition. This is a possible discriminator, not an observed
  timing explanation or permission to weaken the assertion.
- The browser harness starts actions after a fixed 1,100 ms navigation settle;
  its first OPEN condition only checks that `#openSettings` exists in the DOM.
  It does not explicitly await full script/handler initialization. A lost early
  hub click or different page state is therefore another unresolved path.
- The served fixture uses a real isolated Control Center/runtime and ephemeral
  port. No fixture runtime from these failures is reused as the user's runtime.

## Queued exact baseline browser check (not executed, needs PM allocation)

After the full gate, and only when explicitly authorized for Chrome:

```powershell
Set-Location C:/Projects/jarvis/movb
git rev-parse HEAD
$env:PYTHONDONTWRITEBYTECODE='1'
$env:JARVIS_BROWSER_SHOTS='C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/settings-baseline-captures'
& C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -p no:cacheprovider -q tests/unit/test_architecture_agents_settings_browser.py::test_two_tabs_destinations_and_legacy_ids tests/unit/test_architecture_agents_settings_browser.py::test_architecture_canvas_and_core_window_work_together_then_subagents_tab --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/settings-baseline.xml
```

Preserve actual failure values/first failed navigation action if further
diagnosis is required. Both browser unknowns remain pending; this source
pretriage does not accept them as unrelated, modify tests, add known failures or
authorize any product change. Dense-graph baseline Chrome is also still queued.
