# Canonical Settings IA and option contract

Status: canonical input for Slices 02–07. Machine-readable source: `settings-ia-contract.json`.

## Product information architecture

Settings keeps five primary destinations: **Agent / CLI**, **Voix**, **Prompts**, **Clés API**, and **Raccourcis**. `Aiguillage` disappears as navigation and user-facing vocabulary. Its working policy remains an internal part of Agent / CLI.

Agent / CLI order is locked:

1. **Technique** — active CLI, model, permissions, delegation mode, advanced routing/self-development.
2. **Comportement** — verbosity then politeness/formality.
3. **Sous-agents / Modèles** — sourced catalog and profile candidate choices.

Voice top sub-tabs are locked by stable IDs: `architecture`, `conversation`, `turn_taking`, `models`, `audio`, `advanced`, `diagnostic`. Labels may be polished, IDs and mappings may not drift.

## Auto / Dupliqué

One source of truth remains `agent_routing.enabled`; no second routing engine or duplicate persistence field is introduced.

| UI value | Persisted value | Runtime contract |
|---|---:|---|
| `auto` / Auto | `agent_routing.enabled=true` | Existing profile policy handles each `Agent`/`Task` call. It may replace caller model with first allowed, usable candidate from the active/host CLI only. Exactly one candidate wins. |
| `duplicate` / Dupliqué | `agent_routing.enabled=false` | Compatibility/inheritance. Hook does not rewrite caller/CLI model. It does not duplicate task, spawn second agent, or fan out. |

Nuances preserved from live resolver:

- Auto + disabled profile or empty candidate list -> compatibility for that call.
- Auto + configured list -> first eligible candidate; optional General fallback follows existing policy.
- Cross-CLI execution is excluded from Auto: only the active/host CLI can execute the call. Cross-CLI work requires the explicit self-development workflow.
- Configured candidates all ineligible -> explicit deny, not model outside policy.
- Hook internal failure -> fail open, keep caller/CLI choice, emit `routing_hook_failed`.
- Toggling Dupliqué never deletes profile candidates. Toggling Auto later restores them.

## Agent / CLI inventory

| Current persistence/API | Destination | State |
|---|---|---|
| `agent_cli` | Technique / active CLI | live |
| `agent_cli_settings.<agent>.command` | Technique / advanced | live |
| `agent_cli_settings.<agent>.model` | Technique | live, catalog-backed |
| `agent_cli_settings.<agent>.permission_mode` | Technique / advanced | live; CLI-specific enum |
| `agent_routing.enabled` | Technique / delegation mode | live alias Auto/Dupliqué |
| `agent_routing.profiles.*.enabled` | Technique / routing advanced | live |
| `agent_routing.profiles.*.candidates` | Sous-agents / Modèles | live, ordered |
| `agent_routing.profiles.*.allow_general_fallback` | Technique / routing advanced | live |
| `self_development.enabled` | Technique / self-development advanced | live API, not current UI |
| `self_development.auto_deploy` | Technique / self-development advanced | live API, not current UI |
| `agent_behavior.response_verbosity` | Comportement | live; shared backend-turn consumer |
| `agent_behavior.politeness_formality` | Comportement | live; shared backend-turn consumer |

Verbosity values: `inherit`, `concise`, `balanced`, `detailed`. Politeness/formality values: `inherit`, `direct`, `courteous`, `formal`. Default `inherit` adds no instruction and exactly preserves current behavior. Slice 02 wires both fields once through the shared `backend.turn.addition` composition used by Claude and Codex across `/api/agent/ask`, `/api/agent/send`, and owned jobs. Saved turn addition plus generated behavior must fit the existing 8,192-character bound before either Settings or Prompts persists a change.

Parallelism, generic delegation timeout, cost/latency/quality bias, extra fallback, configurable security confirmations, proactivity, and separate explanation depth remain deferred for reasons recorded in manifest. Current ActionBroker confirmations remain mandatory policy, never personality.

## Voice mapping

Every live writable voice setting has exactly one destination. Full type/default/options/ranges/help live in manifest.

`voice_stack` and `voice_arch` are explicit compatibility metadata. Without a versioned `voice_architecture`, they choose the historical runtime and its stack. With a versioned architecture, models come from that block, the runtime derives its active stack (OpenAI today), and transport settings for that stack (audio, VAD, transcription) still apply. Inactive stack values remain stored. Compatibility `model` fields never override versioned architecture models.

| Sub-tab | Settings |
|---|---|
| Architecture | `voice_architecture.config.architecture`, read-only Duplex `client_delegation` invariant |
| Conversation | `speculative_deltas`, `idle_timeout_s`, OpenAI transcription language, Gemini input/output transcription, `ack_delay_ms`, `conversation_mode`, `speaker_verification`, `active_timeout_s` |
| Tours & interruptions | Per-stack `turn_mode`; all VAD controls; OpenAI echo cancellation; `owner_buffer_ms`; `shortcuts.wake_toggle` |
| Modèles | Architecture conversation/reflex/analysis models; `reasoning_effort`; per-stack model, voice/timbre, OpenAI transcription model; shared catalog |
| Audio | OpenAI noise reduction; input/output devices |
| Avancé | `owner_threshold`, `owner_evidence_ms`, `owner_short_evidence_ms`, `owner_short_margin` |
| Diagnostic | read-only owner profile and verifier/worker state, echo status, voice switch state, catalog provenance, adapter/availability state |

Compatibility settings remain reachable only under explicit compatibility disclosure: `voice_arch`, `voice_stack`, `voice_stack_settings`. Selecting a versioned architecture writes `voice_architecture`; unrelated saves must not auto-upgrade old settings or erase inactive stack values.

## Metadata contract

Every renderable option must provide `id`, `label`, `type`, `default`, `help`, `destination`, `advanced`, and `runtime_status`. Enums also provide stable `options`; numbers provide bounds; dependent fields declare dependency; catalog fields declare live source. `unknown` beats fabricated metadata.

`runtime_status` governs exposure:

- `live*`: render according to availability and advanced state.
- `required-consumer-missing`: do not render or persist until consumer and tests land (none remain in the Agent behavior contract after Slice 02).
- `live-readonly` / `live-invariant`: show status, never editable.

## Migration contract

Read migration is a projection and never writes. Missing/false `agent_routing.enabled` projects to Dupliqué; true projects to Auto. Slice 05 consolidates old `routing` navigation into Agent / CLI; no backend deep-link redirect is claimed. `/api/routing/candidates` may remain an internal compatibility endpoint through Slice 07 but must not restore `Aiguillage` vocabulary.

Existing mirrors remain supported: `claude_cli`, `claude_permission_mode`, `realtime_voice`, `voice_turn_mode`, `manual_wake_key`. Unknown fields, inactive voice stacks, profile candidates, prompts, credentials, and shortcuts survive unrelated saves.

## Observability / Test Contract

Slice 01 changes no runtime behavior, so it emits no runtime event and introduces no probe. Repository currently exposes `RuntimeJournal`, not LogBroker CLI.

Slice 02 verifies, and later Slices must preserve:

- successful save -> existing `settings.update`, info, keys only; no values/secrets;
- invalid Agent/CLI/behavior save -> `settings.agent.rejected`, warning, stable code, atomic recovery; combined prompt overflow uses `agent_settings_behavior_prompt_too_large`;
- prompt edit exceeding the same combined bound -> existing `prompt.override.rejected`, warning, same stable code, no writer call;
- composed direct Agent turn -> existing `agent.prompt`, info, bounded prompt identity only when evidence API is supported;
- composed owned job -> existing agent evidence projected as `job.agent.prompt`, info, correlated by `job_id`; legacy agent signatures remain compatible;
- Auto delegation -> existing `agent.routing.decided`, correlated by `tool_use_id`, with profile/requested/chosen/reason/applied;
- routing hook failure -> existing `agent.routing.failed`, error, `routing_hook_failed`, caller choice preserved;
- no normal Dupliqué call needs a decision event because hook intentionally stays inactive.

Contract tests cover manifest metadata, unique destinations, exact live field inventories, routing projection, single-winner/no-fan-out semantics, old navigation migration, and anti-placebo behavior controls. Official `observability.cli` queries are required when module becomes available; absence must be reported rather than replaced with raw JSONL parsing.

## Audited live sources

- `jarvis/runtime/control_center.py` and `.html`
- `jarvis/runtime/agent_settings.py`, `agent_routing.py`, `routing_hook.py`, `cli_catalog.py`
- `jarvis/domain/routing.py`
- `jarvis/runtime/voice_stack.py`, `voice_capabilities.py`, `voice_architecture_config.py`
- `jarvis/domain/voice_architecture.py`
- `jarvis/runtime/shortcuts.py`, `self_dev.py`, `prompt_overrides.py`
