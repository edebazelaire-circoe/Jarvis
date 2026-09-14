# Execution Log

## 2026-09-14 — Slice 00 readiness audit

Readiness state: `HUMAN_DECISION_REQUIRED`.

### Live repository reconciliation

- Audited branch: `main`.
- Audited SHA: `f0aec1067542ac4beae7dcced74a336fcfaa7fdf`.
- `main` matches `origin/main`.
- The handoff source SHA (`c33207281a5b6a10a6630b8914f19855ea096473`) is stale: the live repository now includes the switchable voice architecture work.
- Existing unrelated worktrees were left untouched.
- The only untracked path in the primary worktree before this audit was this task bundle.

### Product-contract findings

- The current Control Center still exposes a primary `Aiguillage` tab and a dedicated `/api/routing/candidates` endpoint.
- Runtime routing is already centralized in `jarvis/runtime/agent_routing.py`, `jarvis/domain/routing.py`, and `jarvis/runtime/routing_hook.py`; removing the UI must not remove this enforcement.
- Live provider and CLI discovery already exist through `model_catalog.py` and `cli_catalog.py` and remain authoritative.
- No existing setting or runtime contract named `Auto` / `Dupliqué` was found. The existing persisted switch only enables or disables profile-based routing. Therefore `Auto` / `Dupliqué` must be specified as a new canonical contract before Slice 02; it cannot be inferred from current behavior.
- The voice surface is newer than the handoff snapshot and already exposes architecture selection, role/model selection, stack-specific settings, turn mode, authorization, capture/device diagnostics, and runtime switch state. Slice 01/06 must map the live payload, not the older predicted shape.
- No separate `jarvis-voice-turn-arbitration` bundle was found. The live voice architecture/settings contracts and their tests are the freshness source unless the missing handoff is supplied.

### Workspace Task Type blocker

- Every Slice metadata file has `task_type: null` and explicitly forbids invented values.
- No valid Workspace Task Type vocabulary was found in the repository, Codex/Claude CLI help, available tools, skills/plugins, MCP resources, or local Codex metadata stores.
- `local_agent` / `local_bash` are runtime event kinds, not proven Workspace Task Types.
- QA labels (`qa-verification`, `code-review`, `runtime-validation`, `agent-trace-analysis`) are requirements, not proven Task Types.
- Per the Slice 00 gate, no implementation Slice was dispatched.

Required human decision: provide the canonical Workspace Task Type IDs/slugs for Slices 01–07, or explicitly remove that dispatch gate from this handoff.

### 2026-09-14 — Human override and resumed execution

The user explicitly authorized execution using best judgment. The Workspace Task Type dispatch gate is waived for this task; `task_type` remains `null` rather than fabricating values. Slice 00 is now `READY`.

Working Auto/Dupliqué contract:

- `Auto`: reuse the existing enabled profile-based routing policy; JARVIS may rewrite the requested sub-agent model to the first allowed and usable candidate.
- `Dupliqué`: compatibility/inheritance mode; preserve the caller/CLI model choice and launch one sub-agent. It does not fan out the same task to two agents.

This maps to the existing canonical `agent_routing.enabled` behavior and avoids a second routing engine. The contract must be named and tested in Slice 01/02 before UI exposure.

### Baseline QA

Read-only targeted baseline, `PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled:

- Control Center: 98 passed.
- Routing and hooks: 70 passed.
- Catalog/settings endpoints: 80 passed.
- Voice settings/architecture: 138 passed.
- Total: 386 passed, 0 failed, 0 skipped.

The full suite and `scripts/verify_release.py` were intentionally deferred to the final integration gate. Real-browser and multi-viewport validation remain required for frontend Slices.

## 2026-09-14 — Slice 01 Settings IA/options contract

State: `COMPLETE`.

### Live contract reconciliation

- Audited live Control Center payload/save paths, Agent/CLI resolution, profile routing/hook, self-development gate, voice stack field registry, versioned voice architecture/capability registry, authorization/verifier settings, devices, shortcuts, prompts and credentials.
- Canonical machine-readable contract: `docs/settings-ia-contract.json`.
- Human reference and category map: `docs/06-settings-ia-options.md`.
- No backend or UI implementation changed.

### Locked semantics

- `Auto` projects to `agent_routing.enabled=true` and reuses existing profile routing. One Agent/Task call still has one winner; model may be rewritten to first allowed and usable candidate.
- `Dupliqué` projects to `agent_routing.enabled=false`: compatibility/inheritance preserves caller/CLI model. It never means duplicate execution or fan-out.
- Missing routing state defaults to Dupliqué. Switching modes preserves profile candidates.
- `Aiguillage` is removed from target navigation; old navigation redirects to Agent/CLI delegation section. Internal routing endpoint/persistence may remain during compatibility window.
- Verbosity and politeness/formality are required contracts with `inherit` default, but current runtime has no consumer. They must remain hidden/unpersisted until Slice 02 wires and tests one central consumer.
- Unsupported parallelism, generic timeout, cost/latency/quality, extra fallback, confirmation and proactivity knobs are explicitly deferred; no placebo control is allowed.
- Every live voice field is assigned once across Architecture, Conversation, Tours & interruptions, Modèles, Audio, Avancé, Diagnostic. Legacy voice configuration is projected without automatic write migration.

### Observability / Test Contract

- Slice 01 changes documentation/tests only: no runtime event or temporary probe.
- Future contract keeps `settings.update`, `agent.routing.decided`, and `agent.routing.failed`; Agent/CLI validation gets a dedicated warning event rather than misusing the current broad `voice.settings.rejected` path.
- Delegation correlation uses existing `tool_use_id`. No synthetic HTTP correlation ID is invented.
- Official LogBroker CLI check was attempted and is unavailable in this repository: `ModuleNotFoundError: No module named 'observability'`. Raw JSONL was not substituted.

### Validation

- Added migration fixture `slices/01-settings-ia-contract/fixtures/aiguillage-migration.json` and contract regression coverage in `tests/unit/test_settings_ia_contract.py`: required metadata, live Agent/CLI inventory, exact live voice field coverage, unique writable mapping, non-mutating Auto/Dupliqué projection/single-winner wording, and navigation migration.
- Targeted routing/settings/voice validation: **206 passed in 3.53 s**, 0 failed.
- Initial system-Python attempt could not collect six modules because `aiohttp` was absent. Re-run used repository `.venv`, the supported workspace runtime, and passed completely.

## 2026-09-14 — Slice 02 Agent / CLI backend settings

State: `COMPLETE`.

### Canonical persistence and migration

- Added the read-only `delegation_mode` projection: `auto` maps to the existing `agent_routing.enabled=true`; `duplicate` maps to `false`. No `delegation_mode` field is persisted.
- Mode writes reuse the existing routing writer, preserve all profile candidates and never add a second routing/fan-out path.
- Canonical and legacy switches may coexist only when equivalent; contradictory values reject the whole save with `agent_settings_conflicting_delegation_mode`.
- Slice 01 review correction locks Auto to the active/host CLI. Existing `routing_hook.decide` already enforces that boundary and denies policies containing only another CLI; cross-CLI work remains the self-development workflow.

### Behavior consumer

- Added tolerant reads and strict atomic writes for `agent_behavior.response_verbosity` and `agent_behavior.politeness_formality`.
- `inherit` generates no instruction. Context-free Control Center turns and owned background-agent jobs retain their original prompt bytes under inheritance.
- Explicit choices are composed once through the existing shared `backend.turn.addition` layer for Claude and Codex. Persisted prompt overrides are not mutated and stale prompt text is not revived.
- `/api/settings` exposes current values and complete render metadata for delegation and behavior.

### Observability / Test Contract

- Successful saves keep existing `settings.update` at info with top-level keys only.
- Agent/CLI, routing and behavior validation failures emit `settings.agent.rejected` at warning with stable `code` only; invalid saves leave the prior settings file unchanged.
- Existing `agent.routing.decided` / `agent.routing.failed` semantics, `tool_use_id` correlation, fail-open recovery and single-winner behavior remain unchanged.
- No temporary probe or new logging subsystem was added.
- Official CLI attempts for errors, summary and correlation query all failed because `observability.cli` is not installed (`ModuleNotFoundError`). Raw JSONL was not substituted for release evidence; tests exercise `RuntimeJournal` output.

### Slice 01 review corrections

- Added explicit `voice_stack` and `voice_arch` compatibility metadata, versioned-vs-compatibility precedence, valid enum defaults/placeholders and exclusive `owner_threshold > 0` metadata.
- Strengthened contract tests from subset/text checks to exact live persistence inventories, structured invariants and production `agent_routing` projections.
- Removed the unsupported backend deep-link redirect claim, added migration sentinels and recorded the global task-type waiver in `slices/TODO.md`.

### Validation

- Combined Slice 01/02 backend, prompt, routing, settings, owned-worker and voice-architecture validation: **357 passed in 10.52 s**, 0 failed.
- Python import/compile paths were exercised by the test suite; `git diff --check` reports no whitespace error (only repository line-ending warnings).

### QA rework — bounded composition and direct send

- Fixed combined-layer overflow: an 8,192-character saved `backend.turn.addition` plus generated behavior is now rejected before either Settings or Prompts invokes its atomic writer. Stable code: `agent_settings_behavior_prompt_too_large`.
- Settings rejection preserves both file bytes and active-agent prompt memory. Reverse ordering is covered: a Prompt edit cannot create the same invalid combination when behavior is already active.
- Added `prompt_runtime.compose_agent_turn` as shared composition for `/api/agent/ask`, `/api/agent/send`, and owned background jobs. `inherit` returns original text unchanged; explicit behavior applies to both Claude and Codex jobs.
- Direct-send blank input is still rejected before generated instructions could make it non-empty.
- Clarified event scope: `settings.agent.rejected` covers owning CLI/routing/self-development/behavior validators on Settings save; Slice 02 lists only its newly introduced stable codes. Prompt edits keep existing `prompt.override.rejected`.
- QA targeted validation: **30 passed in 1.49 s**, 0 failed.
- Expanded Slice 01/02 validation after concurrent Slice 03 integration settled: **369 passed in 10.58 s**, 0 failed, 0 deselected. Slice 02 changed no catalog file.
- Official `observability.cli` errors, summary and correlation queries were retried; module remains unavailable (`ModuleNotFoundError`).

### QA re-review — prompt evidence propagation

- `/api/agent/send` now forwards composed evidence through existing `set_next_prompt_evidence` when supported, before `send`; legacy agents without that API remain compatible.
- Owned jobs now pass `prompt_evidence` to `ask` after signature capability detection, including `**kwargs` support. Agents with legacy `ask(text, timeout_s=...)` signatures still execute normally.
- Real controlled Claude and Codex wrappers prove evidence consumption: underlying `prompt_applications` receives the turn fingerprint and existing `_JobJournal` emits one matching `job.agent.prompt` correlated by `job_id`, without prompt text.
- No new event channel, fallback, retry or temporary probe was added. Existing `agent.prompt` / `job.agent.prompt` channels carry bounded IDs, revisions and fingerprints only.
- Combined validation after observability re-review: **375 passed in 10.93 s**, 0 failed.

## 2026-09-14 — Slice 03 sourced catalog view model

State: `IMPLEMENTED_AWAITING_QA`.

### Contract and implementation

- Added provider-neutral versioned contract in `jarvis/domain/catalog.py`: opaque deterministic identity keys, sourced values, explicit surface/role, availability evidence and five honest states (`usable`, `configured_unverified`, `available_not_configured`, `unavailable`, `unknown`).
- Added strict optional metadata boundary in `jarvis/runtime/catalog_metadata.py`. No production metadata table was added. Existing `PricingMetadata` and `TokenPricingMetadata` parsers remain authoritative; invalid, wrong-model or unsourced pricing stays `null`.
- Added read-only `CatalogViewService` in `jarvis/runtime/catalog_view.py`. It consumes complete provider envelopes, CLI probes, saved structured candidates and voice registry descriptors. It performs no network I/O, persistence, routing, installation or request creation.
- Added deterministic `VoiceCapabilityRegistry.descriptors()` read access so voice comparison uses the existing registry instead of duplicating its inventory.
- Added canonical documentation and feature index in `docs/catalog/`; linked voice architecture index.
- Initial implementation avoided `control_center.py` during parallel Slice 02 work; final integration now exposes complete source envelopes through `/api/catalog`.

### Truth and compatibility decisions

- Live or TTL-fresh provider evidence plus ready runtime path is required for `usable`.
- A stale catalog can keep an item visible but cannot prove usability or removal. A saved model absent only from stale/missing evidence remains `configured_unverified`, never falsely “removed”.
- A CLI `--version` probe does not prove authentication or its default model; default CLI entries are `configured_unverified`.
- Current provider availability with missing CLI/adapter is `available_not_configured`.
- Curated metadata cannot set availability, roles, capabilities or selectability.
- No request/add sink exists. Every item emits `actions: []`; no `requestable` state, fake ticket or inert persistence was introduced.
- Shared catalog remains presentation-only. Routing hook now reuses its current-evidence eligibility so stale data cannot authorize execution.

### Observability / Test Contract

- Domain, metadata and assembly paths are pure and perform no I/O. They emit no normal or failure event, create no correlation ID, add no permanent channel and require no temporary probe.
- HTTP integration reuses existing `provider.models_failed` diagnostics; pure projection evidence remains deterministic return values.
- Official LogBroker CLI remains unavailable: `ModuleNotFoundError: No module named 'observability'`. Raw JSONL was not substituted. Ruff is also not installed in the repository environment.

### Validation

- New `tests/unit/test_catalog_view.py`: opaque delimiter-safe keys, sub-agent and voice availability matrices, stale/saved truth, missing credentials, cache TTL/corruption, role/surface filtering, strict sourced metadata/pricing, no secret projection, and empty actions.
- Targeted regression command recorded in Slice metadata: **265 passed in 3.99 s**, warnings as errors, 0 failed.
- Python compile check passed for all three new modules.
- QA rework below closes the reported Slice 03 findings.

### QA rework and canonical endpoint

- State: `COMPLETE`.
- CLI availability now accepts exact booleans only; malformed probe values become non-selectable `unknown`.
- `SourcedValue` owns a recursively immutable copy and returns detached JSON snapshots.
- Provider labels are bounded; failure/unknown evidence uses `provider_failure`; inferred roles use `role_classifier` or runtime-registry provenance.
- Routing and catalog projections share `ProviderCatalogSnapshot.current_models()`: stale catalogs keep saved choices visible but cannot authorize or force them.
- Added read-only `GET /api/catalog` for `subagents` and `voice`, with bounded role and optional refresh. Existing `/api/models` and `/api/routing/candidates` remain unchanged.
- Provider failures reuse `provider.models_failed` warning events and preserve stable failure codes inside stale/unknown source provenance. No success event, correlation ID, temporary probe, fallback, price data, request action, or new channel was added.
- Regression validation: **283 passed in 5.21 s**, warnings as errors, 0 failed. `git diff --check` clean except existing line-ending warnings.
- Official LogBroker CLI errors/summary checks remain unavailable: `ModuleNotFoundError: No module named 'observability'`.

### Final re-review corrections

- `/api/routing/candidates` now consumes `ProviderCatalogSnapshot.current_models()` and the same saved-choice non-verification reason as the runtime hook. Stale or failed evidence is never projected as an eligible legacy candidate.
- `/api/catalog` now allowlists roles per surface. Typos and cross-surface roles reject with HTTP 400 / `catalog_role_invalid` before any provider or CLI probe.
- One cross-surface regression proves stale saved-model behavior across canonical catalog, legacy routing endpoint, and offline runtime hook.
- Final Slice 03 regression: **287 passed in 4.24 s**, warnings as errors, 0 failed. Metadata remains `COMPLETE` only after this green run.

### Final fixture correction

- Updated routing-screen test doubles marked `source=live` to include a current `fetched_at`, matching the real `ModelCatalog` envelope required by freshness validation.
- No production code changed. Expanded Slice 03/settings/routing/voice suite: **296 passed in 4.85 s**, 0 failed.

## 2026-09-14 — Slice 04 shared catalog table

State: `COMPLETE`.

### Shared frontend component

- Added `jarvis/runtime/control_center_catalog.js`, injected into the same
  version-coherent Control Center document as the existing work/live modules.
- One renderer supports sub-agent and voice envelopes with caller-selected
  columns. Slice 04 intentionally does not restructure Agent/CLI or Voice tabs;
  Slices 05/06 own those integrations.
- Pure production exports cover accent-insensitive search, OR-within/AND-across
  provider/role/capability/tag/availability filters, stable name and price
  sorting, deterministic facets, comparison reconciliation, UI-state
  projection, escaped accessible HTML and a fetch-backed controller.
- Unknown prices remain last for ascending and descending sorts. Different
  currency/unit groups are never converted. Token price display preserves
  input/output values; their mean is only a stable within-group sort key.
- Compare selection trusts only backend `availability.selectable`; every
  non-selectable state is disabled and rejected by pure selection helpers.
- Availability reason/evidence and sourced-claim provenance stay visible.
  Missing metadata is `Inconnu`, never zero/free/unsupported. Missing
  credentials produce a visible warning without hiding returned inventory.
- Action controls are created only from the item's backend `actions` array.
  No request/install sink, fabricated action, availability rule, persistence or
  routing decision was added in JavaScript.

### Responsive and accessibility contract

- Reused current Control Center variables, controls, typography and status
  colors. Added labelled search/sort/filter controls, table caption/headers,
  live status summaries, keyboard focus outlines and disabled compare inputs.
- Under 700 px the same semantic rows become labelled cards; there is no forked
  mobile component or data path. Reduced-motion behavior remains inherited.
- `/impeccable` and Claude frontend routing were not supported by the available
  skills/tools. This was handled as an explicit fallback to the existing design
  system and local Node/Python validation.

### Observability / Test Contract

- Projection/rendering functions are pure and perform no I/O. They emit no
  normal/failure event, create no correlation ID, add no permanent channel and
  require no temporary probe.
- The controller maps request failure to a visible error state; `load()` or
  `refresh()` is recovery. Existing `/api/catalog` provider failure logging
  remains authoritative.
- Production module tests execute through Node against
  `fixtures/catalog-states.json`, covering all five backend availability states,
  search, multi-filter, price ordering, unknown-last, comparison safety,
  provenance, escaping, backend-only actions, view states, configurable columns,
  responsive CSS, injection and syntax.
- Final targeted catalog/endpoint/Control Center regression: **189 passed in
  6.74 s**, 0 failed.
- Node syntax, Python compile and `git diff --check` passed; diff check reported
  only repository line-ending warnings.
- Official LogBroker errors/summary commands remain unavailable:
  `ModuleNotFoundError: No module named observability`. Raw JSONL was not used.

### Independent QA rework — controller lifecycle

- Search input no longer triggers whole-component `innerHTML` replacement.
  Only result and live-summary regions change, preserving the actual input node,
  focus/caret selection and composition state while typing.
- `load()` / `refresh()` now use both `AbortController` and a monotonic request
  generation. Old success, HTTP failure, JSON failure or custom-fetcher rejection
  cannot overwrite a newer request, even when abort is ignored.
- Delegated input/change/click handlers are named and removed by `destroy()`.
  Destruction aborts pending work, invalidates the current generation and guards
  every render/state commit against late promise completion. Destroy/recreate
  returns to exactly one handler per event.
- Accessibility correction: model cells are `<th scope="row">`; search and
  filter groups carry explicit roles and labels. Responsive CSS supports both
  row headers and data cells.
- Added true `createCatalogTable` controller tests using a bounded fake DOM and
  deferred promises: retained search-node/caret, OLD-vs-NEW result race, old
  error after latest success, abort signals, pending destroy, listener removal,
  no resurrection and clean recreation.
- Final warnings-as-errors catalog/endpoint/Control Center suite after rework:
  **192 passed in 9.60 s**, 0 failed.

## 2026-09-14 — Slice 05 Agent / CLI settings surface

State: `COMPLETE`.

### Unified information architecture

- Replaced separate CLI and routing navigation with one `Agent / CLI` tab. The
  previous navigation ID is normalized to `cli` only for legacy programmatic
  calls; no URL deep-link behavior is claimed and no former routing label
  remains in user-facing HTML.
- Kept Voice and Config structure unchanged for Slice 06.
- Locked visible order to Technique, Comportement, Sous-agents / Modèles.
  Modal subtitle now describes each tab instead of applying a Voice message to
  every saveable surface.
- `/impeccable` and Claude frontend routing were unavailable. Existing Control
  Center layout, controls, colors, responsive rules and accessibility patterns
  were used as the explicit fallback.

### Canonical bindings and advanced policy

- Agent draft is exactly `agent`, `settings`, `delegation_mode`, `behavior`.
  Policy draft is `routing={profiles}`; the page never sends the legacy
  `routing.enabled` beside the canonical mode.
- Delegation labels/options/help render only from
  `cli.delegation_mode_metadata`. Behavior fields, values, option IDs, labels
  and help render only from `cli.behavior`; no frontend option vocabulary or
  runtime policy was duplicated.
- Existing active CLI, command, model and CLI-specific permission controls stay
  in Technique. Profile activation, ordered candidates, saved unavailable
  candidates and General fallback moved under `Configuration avancée des
  sous-agents`, backed by the existing internal candidates endpoint.
- Permanent browser-draft/backend regression changes Auto to Dupliqué plus both
  behavior choices while preserving disappeared/unknown saved candidates,
  non-default Voice/audio state and an unknown future setting. It also proves
  `routing.enabled` is absent from the browser payload.

### Shared catalog lifecycle

- Sous-agents / Modèles mounts `JarvisCatalog.createCatalogTable` with
  `surface=subagents`, `role=subagent` and no action column. Load/refresh is
  independent and never awaited by settings save.
- Technique, Comportement and the catalog shell render synchronously; CLI and
  model discovery replace/rebind only the Technique container with
  generation/open guards. They never call the full tab renderer, change its
  revision or remount the shared catalog, preserving search/filter/compare
  state. CLI failures expose a local retry and are never cached permanently.
  Advanced candidates load only when their disclosure opens, update only its
  body and expose an independent retryable last-request-wins error.
- Dedicated controller is destroyed before every tab render/switch and modal
  close. Closing invalidates settings, CLI, model, advanced and render
  generations, so late requests cannot publish state, render or mount a catalog.
- Catalog request failures remain inside its accessible component error state;
  no request/add action or fallback inventory was introduced.

### Observability / Test Contract

- UI projection introduces no runtime decision, persistence layer, LogBroker
  event, correlation ID or temporary probe. Existing `settings.update`,
  `settings.agent.rejected`, `agent.routing.decided/failed` and catalog provider
  diagnostics remain authoritative.
- Added fixture-driven navigation/order/payload/catalog contract tests, actual
  legacy programmatic-ID execution, production-escape XSS metadata rendering,
  canonical combined backend round-trip, catalog mount/destroy/refresh,
  close-before-settings-resolve, lazy advanced error/race/recovery and stale
  CLI/model hydration runtime tests. A production-function Node probe proves
  first-failure/second-success CLI recovery, one catalog mount, stable catalog
  controller state, unchanged render revision and one binding per replaced
  control, plus responsive/accessibility checks.
- Final warnings-as-errors UI/settings/routing/catalog regression:
  **281 passed in 12.73 s**, 0 failed.
- Served-page JavaScript syntax and `git diff --check` passed; only repository
  line-ending warnings were reported.
- Official LogBroker errors/summary commands remain unavailable:
  `ModuleNotFoundError: No module named observability`. Raw JSONL was not used.

## 2026-09-14 — Slice 06 Voice settings backend projection

State: `BACKEND_COMPLETE_UI_PENDING`.

### Additive Settings schema

- Added an ordered, registry-backed `voice.categories` projection and one
  normalized `voice.option_metadata` inventory: 44 existing persistable
  options plus 9 existing computed diagnostic projections.
- Every persistable stack, architecture, authorization, audio and wake control
  maps to exactly one category. Drift guards compare mappings against the live
  registries; OpenAI stack metadata retains every field, including
  `ack_delay_ms`.
- Model options expose identity, selectability, adapter status and availability
  without duplicating nested architecture `settings_fields`. Existing
  `voice.stacks`, `voice.settings`, compatibility fields and POST shapes remain
  unchanged.
- Added `voice.effective_stack`, derived by `resolve_voice_composition` without
  mutating saved settings. The stored compatibility `voice.stack` remains
  visible independently.
- Echo-cancellation applicability now uses that effective composition. An
  explicit architecture deriving OpenAI therefore no longer reports AEC as
  inapplicable solely because the inactive legacy stack is Gemini.

### Safety, observability and validation

- Projection is detached, read-only, secret-free and performs no provider I/O.
  It adds no event, correlation ID or diagnostic channel; current authorization,
  AEC, switch and catalog diagnostics remain authoritative.
- POST regression proves projection-only keys are never persisted and legacy
  stack selection/save behavior is unchanged.
- New exact contract tests cover category/inventory equality, required metadata,
  normalized options, valid enum defaults and numeric bounds, architecture and
  stack field coverage, no duplicated `settings_fields`, detached projections,
  effective stack for compatibility/Simple/Front Brain/Duplex, the legacy-Gemini
  AEC mismatch, and endpoint immutability.
- Expanded Voice/Settings/architecture suite under warnings-as-errors:
  **285 passed in 9.68 s**, 0 failed. Python compile and scoped diff checks
  passed; diff check reported only the repository line-ending warning.
- UI implementation, responsive checks and human validation remain pending, so
  Slice 06 is deliberately not marked complete.

### QA rework — AEC report correlation

- `PersistentVoiceRuntime` now publishes the effective architecture and exact
  composition ID with each capture report. It retains the legacy operational
  `arch` field, which legitimately remains `legacy` for explicit Simple, Front
  Brain and Duplex execution.
- Control Center accepts a Voice AEC result only for the current composition
  ID. An old-format report without an ID is accepted solely for compatibility
  `continuous_brain`; a mismatched configuration remains visible but requests
  restart and cannot mask the settings-derived state.
- Regression proves an explicit Duplex/OpenAI composition with stored Gemini,
  `arch=legacy` and real `aec_failed` is reported degraded from Voice. Separate
  checks prove wrong-ID rejection and production publication of both identity
  fields.
