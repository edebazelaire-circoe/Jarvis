# Jarvis — Mémoire & connaissances Settings UI

## Project

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Source branch audited: `main`
- Source SHA: `20292e5c292dc8ab9a012ccf00ecb82b5c7f820e`
- Canonical Drive destination: `Jarvis/task/to-do/jarvis-memory-knowledge-settings-ui/`
- Related task: `Jarvis/task/to-do/jarvis-settings-ui-reorganization/`
- This handoff **supersedes/refines Slice 05 (`memory-knowledge-reorganization`)** of that broader Settings reorganization task. It does not supersede the rest of that task.

## Mission

Rebuild **Mémoire & connaissances** as a clear product-facing Settings page while preserving the existing memory architecture and canonical contracts.

The page must expose three user goals:

1. **Mémoire** — how Jarvis recalls and consolidates information.
2. **Connaissances** — which knowledge sources exist and which agents may access them.
3. **Memory Center** — inspect notes, review candidates and test recall in a dedicated workspace.

Detailed index/runtime/Tencent diagnostics must no longer dominate the ordinary page. They move to **Avancé & diagnostic**.

## Locked product decisions

- Canonical memory remains the Markdown store. Derived indexes are disposable and must never be presented as authoritative memory.
- Default recall remains functional in lexical-only mode.
- Semantic retrieval is optional. Current provider support is `none` / OpenAI; do not invent providers.
- Consolidation continues to create **candidates** before canonical memory. Manual review remains first-class.
- User-facing memory settings keep recall enablement, recall quantity, semantic enable/provider/private-data permission, consolidation mode/confidence/candidate budget.
- Raw `recall.timeout_ms` is not a primary preference. Prefer a simple user-facing recall profile if one is introduced; raw milliseconds belong in Advanced.
- Knowledge sources distinguish **enabled preference** from **runtime availability**. In current `main`, Wiki and Skills are wired; CodeGraph is not mounted until a repository provider exists.
- Loadouts become a real graphical Settings editor. They define what memory scopes and knowledge types each Brain/role can access.
- Architecture/Brains own **who talks to whom**. Memory & connaissances owns **what information each Brain/role may access**.
- Memory Center remains distinct from ordinary toggles. It is an inspection/decision workspace, not a giant preference form.
- Memory Center keeps Notes, Candidates, Knowledge and Recall Test. Detailed index health is secondary and may deep-link to Advanced.
- Tencent URL/service id/mirror state, detailed capability codes, environment/file/default provenance and raw index timings belong in Advanced diagnostics.
- Secrets remain in Connections/API credential management. Memory Settings may only show presence/absence and link to the credential home.
- Existing write semantics, schema-driven ranges/options, optimistic candidate decisions and security rules remain authoritative.

## Visual direction

Use the validated conversation mockups as **reference**, not as literal specifications. The user will attach final visuals separately.

Key visual rules extracted from the references:

- same dark neon/glass language as the new Jarvis Settings pages;
- large page title, restrained breadcrumb, circular profile/avatar button top-right;
- no decorative quote;
- modular heterogeneous tile composition on a disciplined grid;
- tabs: `Mémoire`, `Connaissances`, `Memory Center`;
- cards show plain-language state first, technical details second;
- source cards clearly differentiate `Actif`, `Désactivé`, `Indisponible`;
- loadouts use a readable matrix/cards, not raw `memory_scopes` strings;
- Memory Center can be denser than normal Settings because it is an inspection workspace.

See `references/README.md` for the visual interpretation notes.

## Existing implementation to reuse

- `jarvis/domain/memory_settings.py`
- `jarvis/runtime/memory_settings.py`
- `jarvis/runtime/control_center_memory_settings.js`
- `jarvis/runtime/control_center_memory.js`
- `jarvis/core/memory_hybrid.py`
- `jarvis/core/memory_wiring.py`
- `jarvis/core/loadout_resolver.py`
- `jarvis/protocol/memory_routes.py`
- `docs/memory.md`
- `docs/settings/memory.md`
- `docs/skills-and-loadouts.md`

Do not create a second memory model, a second loadout vocabulary or browser-only copies of backend ranges/options.

## Async execution model

The receiving agent is the Project Manager and executes Slice `00-project-manager` itself.

No implementation work is dispatched until Slice 00 reaches `READY` after a blind audit of current `main` and reconciliation with this handoff.

After `READY`, dispatch all parallel-safe Slices whose hard dependencies are satisfied.

Initial intended ready set:

- `01-memory-preferences-ui`
- `02-knowledge-loadouts-ui`
- `03-memory-center-ui`
- `04-memory-advanced-diagnostics`

These Slices deliberately build on separate modules/adapters where possible and defer shared Settings wiring to Slice 05.

Main hard chain:

`00 -> {01,02,03,04} -> 05 -> 06`

## QA doctrine

Per-Slice validation is lightweight: review, static/build checks and narrow runtime smoke evidence as appropriate. Do **not** run the full unit suite at individual Slice boundaries.

Slice 06 owns the complete unit, integration and E2E campaign once, in the final validation phase. Unit and E2E should run concurrently when isolation/resources allow.

Human validation never substitutes for machine QA.
