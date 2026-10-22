# Agent / CLI settings backend

> **Settings navigation (canonical):** the six top-level categories, the section
> registration contract and the remaining legacy tab alias (`memory`, Slice 09) live in
> [`navigation-registry.md`](navigation-registry.md)
> (`jarvis/runtime/control_center_settings_registry.js`,
> `window.JarvisSettingsRegistry`). New Settings features register a section
> there; they never add a top-level tab. It supersedes the `navigation` part of
> `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json`.

## Components

| Component | Responsibility | Key entry points |
| --- | --- | --- |
| `jarvis/runtime/agent_behavior.py` | Tolerant read, strict atomic validation, API metadata, bounded response instruction | `load`, `apply`, `describe`, `prompt_instruction` |
| `jarvis/runtime/agent_routing.py` | Canonical Auto/Dupliqué projection over existing routing persistence | `delegation_mode`, `apply_delegation_mode`, `delegation_enabled` |
| `jarvis/runtime/prompt_overrides.py` | Keep saved prompt edits separate from runtime-only behavior merge into shared backend turn composition | `stored_prompt_override_document`, `prompt_override_document` |
| `jarvis/runtime/prompt_runtime.py` | One bounded Agent-turn composition for ask, direct send and owned jobs | `compose_agent_turn` |
| `jarvis/runtime/memory_settings.py` | Memory settings (`memory` key): tolerant read, strict whole-request write, server-described schema with one settings destination per field (`surface`), `has_secret` only; see [`memory.md`](memory.md) | `read_memory_settings`, `validate_memory_settings_write`, `describe_memory_settings`, `read_loadout_policy` (`memory.loadouts`, Slice 09), `SURFACE_SECTIONS` |
| `jarvis/runtime/control_center_memory_settings.js` + `control_center.html` (`MEMORY_SECTIONS`, `MEMORY_DIAGNOSTIC`) | Mémoire & connaissances: Rappel, Recherche sémantique, Consolidation, Sources de connaissances (Tencent sidecar, read-only per-agent loadouts), Centre mémoire; the Memory part of Advanced › Diagnostics; fields placed by their server `surface`, own save button, unchanged memory patch, draft shared by the memory sections for one opening; see [`memory.md`](memory.md) | `JarvisMemorySettings.create(host, {section\|mode, store})`, `createStore`, `memorySectionSpec`, `installMemorySettingsSections` |
| `jarvis/runtime/control_center_subagents_settings.js` | Sub-agent settings, two views: `roles` (section `agents_models` › `subagents`: role catalogue, role sheet, read-only Work Methods, order of the appended brief, running instances; writes role instructions through `POST /api/prompts/subagent_role.<id>`) and `work_methods` (section `advanced_diagnostics` › `work_methods`: observed approaches and explicit promotion); see [`../subagent-roles.md`](../subagent-roles.md) § 8 | `JarvisSubagentSettings.create(host, {view})`, `show` |
| `jarvis/runtime/control_center_settings_registry.js` | Canonical Settings navigation: six frozen categories, section registration with deterministic refusals, the explicit legacy alias table (`LEGACY_TAB_ALIASES`; the legacy-tab adapter is removed since Slice 09) and the shell navigation model; see [`navigation-registry.md`](navigation-registry.md) | `JarvisSettingsRegistry.page.register`, `resolve`, `shellNavigation`, `shellTarget`, `DEFAULT_CATEGORY` |
| `jarvis/runtime/control_center.html` (Settings shell) | Full-screen six-category Settings shell: category rail, category entries, focus/keyboard/Escape, section mount and cleanup, footer save policy; see [`settings-shell.md`](settings-shell.md) | `registerSettingsSection`, `selectTab`, `openSettingsTab`, `settingsTabs`, `mountRegisteredSection` |
| `jarvis/runtime/voice_settings_schema.py` (`surface`) + `control_center.html` (`VOICE_SECTIONS`, section `diagnostics`) + `control_center_wake_word.js` | Voix & audio : cinq sections orientées tâche, Architecture & compatibilité et Diagnostics sous Avancé, une destination par option décrite par le serveur; see [`voice-audio.md`](voice-audio.md) | `voiceSectionSpec`, `registerSettingsDiagnostic`, `voiceOptions(section)` |
| `jarvis/runtime/control_center.html` (`AGENT_SECTIONS`, `SUBAGENT_SECTIONS`) | Agents & modèles: four task sections (Agent principal, Comportement, Modèles des sous-agents, Rôles des sous-agents), Runtime & CLI and Work Methods apprises under Advanced; one destination per Agent/CLI setting, unchanged save payload; see [`agents-models.md`](agents-models.md) | `agentSectionSpec`, `subagentSectionSpec`, `installAgentSettingsSections` |
| `control_center_work.js` (`THEME_SCENE_SECTION`), `control_center_scene_page.js` (`JarvisSceneViewSettings`), `control_center.html` (`SHORTCUTS_SECTION`), `control_center_barehands.js` (`installSettingsSections`) | Interface & interactions: Thème & scène visuelle (theme + scene view prefs, browser `localStorage`, immediate), Raccourcis (canonical and only editor of every registered shortcut, `wake_toggle` included), Bare Hands ordinary preferences; Advanced › Bare Hands · essais (`barehands_lab`) and the Bare Hands part of Diagnostics; see [`interface-interactions.md`](interface-interactions.md) | `registerSettingsSection`, `startCapture`, `JarvisBarehands.showSettings`, `openSettingsLink` |
| `jarvis/runtime/control_center_connections_settings.js` + `control_center.html` (`CONNECTIONS_SECTION`) | Connexions: section Fournisseurs (`providers`; the old `keys` ID is retired since Slice 09), one card per provider served by the credential store (identity, configured state, active key, add/replace/delete, environment fallback by variable name, server `hint` as usage note); unchanged credential routes and payloads, never a value; see [`connections.md`](connections.md) | `JarvisConnectionsSettings.create(host, {request, state, isCurrent, onState})`, `html`, `CONNECTIONS_SECTION` |
| `control_center_settings_registry.js` (`CATEGORY_GROUPS`) + `control_center.html` (`PROMPTS_SECTION`) + `control_center_scene_settings.js` (`scene_gate`) | Avancé & diagnostic : cinq groupes déclarés, avis d'outils d'opérateur, section Prompts (atelier, routes et charges inchangées) et section Scène constellation (porte de test + redémarrage du brain) ; voir § « Avancé & diagnostic » ci-dessous | `R.groups`, `CATEGORY_GROUPS`, `PROMPTS_SECTION`, `promptWorkbenchHtml`, `JarvisSceneSettings` |
| `jarvis/runtime/control_center_settings_ui.js` | Pure Settings visual primitives (intro, section, field, badge, notice, advanced disclosure, action row); see [`settings-shell.md`](settings-shell.md) § 5 | `JarvisSettingsUI.section`, `field`, `notice` |
| `jarvis/runtime/control_center.py` | `/api/settings` projection/save, alias conflict rejection, active-agent refresh | `_settings_payload`, `save_settings`, `_apply_cli`, `agent_ask` |
| `jarvis/runtime/agent_settings.py` + `back_brain_worker.py` | Carry and consume behavior choice for owned background agent executions | `resolve_agent_execution`, `execute_with_progress` |

## Avancé & diagnostic (Slice 08)

Outils d'opérateur, pas réglages du quotidien : l'avis de la catégorie le dit (`notice` du registre). La catégorie
déclare cinq groupes (`CATEGORY_GROUPS.advanced_diagnostics`, figés dans
[`navigation-registry.md`](navigation-registry.md) § 1) ; chaque section y porte un `group` explicite, refusé s'il
manque ou n'est pas déclaré (`settings_section_group`). La liste des entrées les montre sous l'intitulé de leur
groupe (monospace : le style technique est réservé à cette catégorie, avec les éditeurs de prompt).

| Groupe | Ce qui y va | Sections (ordre) |
| --- | --- | --- |
| Architecture & compatibilité (`architecture_compat`) | architecture vocale, piles et modes historiques, invariants (délégation, orchestration du cerveau), réglage fin VAD/tampon/vérificateur | `architecture_compat` ([`voice-audio.md`](voice-audio.md)) |
| Prompts & instructions (`prompts`) | atelier des prompts : chaque couche contrôlée par JARVIS (enregistrer / revenir au défaut, `POST /api/prompts/<id>`, charges `edit` et `reset` inchangées), prompt effectif par canal ; les instructions des rôles de sous-agent restent dans Agents & modèles › Rôles des sous-agents (aucune couche `subagent_role.*` dans l'atelier) | `prompts` (ID de section = ancien ID d'onglet) |
| Runtime & CLI (`runtime_cli`) | commande et chemin du CLI, re-détection, permission, profils et ordre des candidats, source des listes | `runtime_cli` ([`agents-models.md`](agents-models.md)) |
| Diagnostics (`diagnostics`) | état constaté, en lecture seule, fait de parties (`registerSettingsDiagnostic`) : Voix, Mot d'éveil, Mémoire, Bare Hands | `diagnostics` |
| Labs & outils de test (`labs`) | porte de test de la scène et redémarrage du brain, promotion des Work Methods, essais Bare Hands (lecture à l'écran, test, enregistrement), futurs outils expérimentaux qui ne sont pas des préférences | `scene_gate`, `work_methods`, `barehands_lab` ([`interface-interactions.md`](interface-interactions.md)) |

Aucune de ces sections ne double un contrôle éditable d'une autre catégorie : la porte `scene.enabled` n'existe
qu'ici (Thème & scène visuelle ne règle que l'apparence locale de la scène), les champs Voix et Agent/CLI ont une
seule destination servie ou figée par test, la promotion des Work Methods n'est offerte qu'ici. Plus aucun onglet de
premier niveau : le système d'onglets est retiré depuis la Slice 09 ; `prompts` est l'ID de sa section, `experimental`
et `routing` ne sont plus des alias ([`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md)).

> **Note de remplacement (Slice 09).** Les consommateurs de
> `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` (navigation à six onglets, redirection
> programmatique `routing` → `cli` de la fixture `agent-cli-ui.json`) lisent désormais
> [`navigation-registry.md`](navigation-registry.md) : six catégories, sections enregistrées, et la seule table
> `LEGACY_TAB_ALIASES` (`memory` → `recall`). Les métadonnées d'options de ce contrat restent valides.
Régression : `tests/unit/test_advanced_settings_browser.py` (vrai Chrome),
`tests/unit/test_control_center_settings_registry_js.py`, `tests/unit/test_scene_settings_ui.py`,
`tests/unit/test_control_center_prompts.py`.

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

Since `jarvis-settings-ui-reorganization` Slice 04 there is no `Agent / CLI` tab: its
settings are registered sections, one destination each
([`agents-models.md`](agents-models.md)). `agents_models` › `main_agent` (CLI identity,
availability, main model), `agent_behavior` (verbosity, politeness/formality, agenda
reminders), `subagent_models` (Auto/Dupliqué mode, sub-agent model catalog);
`advanced_diagnostics` › `runtime_cli` (command, resolved path, re-probe, permission
mode, profiles and candidate ordering). Delegation and behavior controls are
generated from `cli.delegation_mode_metadata` and `cli.behavior.fields`; the
page contains no duplicate option vocabulary. The canonical draft is unchanged,
shared by these sections and sent by the footer « Enregistrer »:
`cli={agent,settings,delegation_mode,behavior}` plus
`routing={profiles}`—the legacy `routing.enabled` alias is never sent beside
the canonical mode.

Profile activation, ordered candidates and General fallback remain available
under `Configuration avancée des sous-agents`, in Runtime & CLI. The compatibility
candidates endpoint stays internal, including saved unavailable candidates. The
inventory mounts `JarvisCatalog` with `surface=subagents` and `role=subagent`;
it loads independently from settings save and exposes no request/add action.
Each section renders before CLI/model probes finish. CLI and model hydration
replaces and rebinds only the `#cliTechnical` container of Agent principal or
Runtime & CLI. Failures stay local and expose retry controls. The
candidates endpoint is called only when the advanced disclosure opens, with
its own local retryable error.
The catalog controller is created by the Modèles des sous-agents section and
destroyed by its `destroy` (section or category switch, modal close), so
requests and delegated handlers cannot outlive their surface. The old IDs
`cli` and `routing` are no longer aliases (retired in Slice 09): callers use `main_agent` and `runtime_cli`.

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

## Sub-agent roles and Work Methods

Section `agents_models` › `subagents` (label `Rôles des sous-agents`, `save: 'self'`, no footer save
button; the old tab ID `subagents` is its ID). It reads `GET /api/subagent-roles` (v2) and
`GET /api/agent/tasks`, and writes nothing but role instructions, through the existing prompt route with
optimistic revisions (`base_revision` + `expected_effective_revision`). Capabilities and Work Methods are
labelled read-only. A non-editable default Work Method is shown as appended after the editable
instructions. Sub-agent models are set in `agents_models` › `subagent_models`. Observed approaches and
their explicit promotion live in `advanced_diagnostics` › `work_methods` (group `labs`), the same module
with `view: 'work_methods'`. Full contract, states and error codes:
[`../subagent-roles.md`](../subagent-roles.md) § 8 and [`agents-models.md`](agents-models.md).
Regression: `tests/unit/test_control_center_subagents_settings_js.py`,
`tests/unit/test_agents_models_settings_browser.py`,
`tests/integration/test_settings_redesign_migration.py` (assembled navigation).

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
