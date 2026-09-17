# Settings redesign migration and rollout

This guide covers migration from the former routing and dense Voice settings
surfaces to the canonical `Agent / CLI` and categorized `Voix` surfaces.

## Compatibility contract

Loading settings is a read-only projection. A `GET /api/settings` does not
rewrite the settings file.

- `agent_routing.enabled=true` projects to `cli.delegation_mode=auto`.
- A missing or false `agent_routing.enabled` projects to
  `cli.delegation_mode=duplicate`.
- A canonical save writes the existing `agent_routing.enabled` field; it does
  not persist a second `delegation_mode` field.
- Auto considers at most one candidate on the active caller CLI/host. Only the
  existing auto-development path may cross CLI boundaries.
- Dupliqué preserves the caller-selected CLI/model and starts at most one
  requested sub-agent. It does not fan out.
- Saved candidates are retained when discovery reports them unavailable,
  stale or unknown. Discovery does not silently repair or delete preferences.
- Voice `stack` remains the compatibility selection. Explicit
  `voice_architecture` values take precedence through the derived
  `voice.effective_stack`; inactive OpenAI and Gemini stack settings remain
  persisted.
- Unknown top-level and nested settings keys survive partial Agent/CLI and
  Voice saves. Projection-only metadata, categories and diagnostics are never
  persisted.

The seven Voice categories are ordered by the backend contract:
Architecture, Conversation, Tours & interruptions, Modèles, Audio, Avancé and
Diagnostic. Diagnostic is read-only. The browser sends an explicit
architecture only after that control becomes dirty, so saving an unrelated
category cannot manufacture a migration choice.

## Rollout procedure

1. Stop concurrent settings edits and back up the current
   `control-center-settings.json` file from the configured data root.
2. Start Jarvis and confirm `/api/status`, `/api/settings` and `/api/catalog`
   return successfully. A Voice runtime may legitimately be offline while its
   settings remain editable.
3. In Agent / CLI, confirm Technique, Comportement and Sous-agents / Modèles
   render in that order. Check the projected Auto/Dupliqué value and saved
   unavailable candidates before saving.
4. Change one Agent/CLI preference, save, reload the Control Center, then
   confirm the value and candidate ordering.
5. Visit all seven Voice categories. Change one value in a saveable category,
   save, reload, and confirm both active and inactive stack values remain.
6. Run the automated gate from the repository root:

   ```powershell
   .\.venv\Scripts\python.exe scripts\verify_release.py
   ```

7. Complete the Slice 07 human walkthrough. Do not declare rollout complete
   from automated tests alone.

## Availability interpretation

Catalog state is evidence-backed and is not an entitlement or install action.

- `usable`: a current source and runtime/CLI evidence establish use.
- `configured_unverified`: a saved choice exists, but credentials or provider
  availability were not verified.
- `available_not_configured`: a fresh provider source lists the model while
  the required CLI/runtime is absent.
- `unavailable`: current authoritative evidence rules the choice out.
- `unknown`: the probe is absent or invalid.

There is no request/add action because this repository has no durable request
sink. A missing action must not be represented as a successful request.

## Troubleshooting

### A saved model is missing from the selectable list

Inspect its catalog evidence and freshness. The saved candidate must remain in
settings even when it is shown as unavailable, stale or unknown. Restore CLI or
credential availability, refresh the catalog, then re-evaluate; do not delete
the saved value merely to remove a warning.

### Auto selected an unexpected CLI

Confirm the active caller CLI/host and its ordered profile candidates. Normal
Auto routing is limited to that host. Cross-CLI selection belongs only to the
separate auto-development path.

### Voice shows a different effective stack than the stored stack

Check `voice_architecture`. An explicit architecture derives the effective
composition and may intentionally differ from the legacy compatibility
`stack`. Diagnostic reports are accepted only when correlated to the current
composition; after changing architecture, restart Voice if the UI requests it.

### A settings save is rejected

The write is atomic: validation failure leaves the file and active memory
unchanged. Use the stable rejection code from `settings.agent.rejected` or
`voice.settings.rejected`; do not log setting values, credentials or prompt
text.

### Rollback

Stop Jarvis, restore the exact backed-up settings file, and restart. Since
reads do not write migrations and compatibility storage remains unchanged,
rollback does not require a reverse data transformer.

## Observability contract

- `settings.update` records only top-level request keys.
- `settings.agent.rejected` and `voice.settings.rejected` expose stable codes
  without values or secrets.
- `agent.routing.decided` is correlated by `tool_use_id` and records one winner
  or one explicit deny; `agent.routing.failed` is fail-open without retry or
  fan-out.
- `agent.prompt` and `job.agent.prompt` contain prompt identity/fingerprints,
  channel and application, never prompt text.
- Catalog failures use the existing provider diagnostics. Projection and UI
  migration add no new event or correlation channel.

The official `observability.cli` errors, summary and correlation queries are
required when that module is installed. This repository currently does not
ship it; record that limitation rather than parsing raw JSONL as a substitute.
