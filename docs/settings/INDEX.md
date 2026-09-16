# Agent / CLI settings backend

## Components

| Component | Responsibility | Key entry points |
| --- | --- | --- |
| `jarvis/runtime/agent_behavior.py` | Tolerant read, strict atomic validation, API metadata, bounded response instruction | `load`, `apply`, `describe`, `prompt_instruction` |
| `jarvis/runtime/agent_routing.py` | Canonical Auto/Dupliqué projection over existing routing persistence | `delegation_mode`, `apply_delegation_mode`, `delegation_enabled` |
| `jarvis/runtime/prompt_overrides.py` | Keep saved prompt edits separate from runtime-only behavior merge into shared backend turn composition | `stored_prompt_override_document`, `prompt_override_document` |
| `jarvis/runtime/prompt_runtime.py` | One bounded Agent-turn composition for ask, direct send and owned jobs | `compose_agent_turn` |
| `jarvis/runtime/control_center.py` | `/api/settings` projection/save, alias conflict rejection, active-agent refresh | `_settings_payload`, `save_settings`, `_apply_cli`, `agent_ask` |
| `jarvis/runtime/agent_settings.py` + `back_brain_worker.py` | Carry and consume behavior choice for owned background agent executions | `resolve_agent_execution`, `execute_with_progress` |

Rollout and compatibility checks are documented in
[`migration-rollout.md`](migration-rollout.md). The canonical Voice projection
is documented in [`../voice-settings-schema.md`](../voice-settings-schema.md).

`delegation_mode` is never persisted. `auto` maps to
`agent_routing.enabled=true`; `duplicate` maps to `false`. Existing profile
candidates remain the source of truth and keep their order across mode changes.
Both modes select at most one model for the one sub-agent call requested by the
caller.

Auto is enforceable only inside the active Claude CLI, whose `Agent`/`Task`
hook is the verified sub-agent boundary. Codex exposes no equivalent hook in
the current runtime: when Codex is active, its catalog candidates are
non-selectable in Auto. No cross-CLI fallback or fan-out is attempted.

## Control Center surface

The single `Agent / CLI` tab renders three sections in order: Technique,
Comportement, then Sous-agents / Modèles. Delegation and behavior controls are
generated from `cli.delegation_mode_metadata` and `cli.behavior.fields`; the
page contains no duplicate option vocabulary. Its canonical draft is
`cli={agent,settings,delegation_mode,behavior}` plus
`routing={profiles}`—the legacy `routing.enabled` alias is never sent beside
the canonical mode.

Profile activation, ordered candidates and General fallback remain available
under `Configuration avancée des sous-agents`. The compatibility candidates
endpoint stays internal, including saved unavailable candidates. The main
inventory mounts `JarvisCatalog` with `surface=subagents` and `role=subagent`;
it loads independently from settings save and exposes no request/add action.
Technique, Comportement and the catalog shell render before CLI/model probes
finish. CLI and model hydration replaces and rebinds only the Technique
container, preserving the mounted catalog controller and its search, filters
and comparison selection. Failures stay local and expose retry controls. The
candidates endpoint is called only when the advanced disclosure opens, with
its own local retryable error.
Its controller is destroyed before tab re-render, switch or modal close, so
requests and delegated handlers cannot outlive their surface. Programmatic
selection of the old `routing` tab ID maps to `cli` without persisting anything.

Behavior is persisted only under `agent_behavior.response_verbosity` and
`agent_behavior.politeness_formality`. Invalid stored values read as `inherit`
without a write migration. `inherit` returns no generated instruction and
therefore keeps the previous context-free request path byte-for-byte. Any
explicit choice is appended once through `backend.turn.addition`, shared by
Claude and Codex. Saved prompt overrides remain untouched; stale overrides are
not reactivated by this runtime merge. The Prompts workbench reads only saved
edits, so generated behavior cannot masquerade as or duplicate a user override.
The saved turn addition plus generated behavior share the existing 8,192
character override bound. Both Settings save and Prompts edit validate the
combined layer before their atomic writer runs.

## Observability / Test Contract

- Successful save: existing `settings.update`, level `info`, top-level request
  keys only. No setting values or secrets.
- Agent/CLI validation rejection on `/api/settings`:
  `settings.agent.rejected`, level `warning`, stable `code` only. This includes
  `agent_settings_behavior_prompt_too_large`; file and active-agent memory
  remain unchanged. Event scope also includes existing CLI, routing and
  self-development validators; each keeps its owning stable code registry.
  Slice 02 documentation lists only codes introduced here, not an incomplete
  replacement list for those existing validators.
- Prompt edit rejected by the same combined bound: existing
  `prompt.override.rejected`, level `warning`, same stable bound code. Prompt
  writer is not called.
- Auto routing decision: existing `agent.routing.decided`, correlated by
  `tool_use_id`; exactly one winner or one explicit deny.
- Hook failure: existing `agent.routing.failed` / `routing_hook_failed`; caller
  model survives and no retry or fan-out occurs.
- Dupliqué normal flow: no routing decision event because hook is inactive.
- Composed `/api/agent/ask` and `/api/agent/send`: existing `agent.prompt`,
  level `info`, when agent supports prompt evidence. Payload contains program,
  layer revisions, static/render fingerprints, channel and application only;
  never prompt text. The composed transport stays in memory: `agent.input` and
  Agent snapshots retain only the canonical user request, never saved
  `backend.turn.addition` text or generated behavior instructions.
- Owned jobs: evidence is passed to `ask(prompt_evidence=...)` when supported.
  Real Claude/Codex wrappers emit existing `agent.prompt`; `_JobJournal`
  projects it to `job.agent.prompt` correlated by `job_id`. Legacy agents
  without parameter still receive identical composed prompt, without failure.
- Temporary probes: none.

Regression coverage:

- `tests/unit/test_agent_behavior.py`
- `tests/unit/test_settings_endpoints.py`
- `tests/unit/test_agent_routing.py`
- `tests/unit/test_routing_hook.py`
- `tests/unit/test_prompt_registry.py`
- `tests/unit/test_agent_cli_settings_ui.py`
- `tests/unit/test_control_center_catalog_ui.py`

Official `observability.cli` queries remain required when that module is
available. This repository currently lacks it; report that absence and do not
substitute raw JSONL inspection for release evidence.
