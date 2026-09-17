# Overview

## Goal

Replace the current routing-centric/dense settings experience with technical-first Agent/CLI configuration, rich personalization, reusable model/sub-agent comparison catalogs, and categorized voice settings while preserving backend routing correctness.

## Scope

- Remove the user-facing “Aiguillage” section; keep routing implementation internally if still required by the runtime.
- Move sub-agent delegation configuration into the agent/CLI configuration area, with technical options shown before personality/behavior options.
- Expose an Auto vs Dupliqué sub-agent mode switch, bound to the live runtime semantics rather than inventing a second routing engine.
- Provide extensive personalization, including verbosity and politeness/formality, while keeping technical controls visually prioritized.
- Reorganize the overloaded voice-model settings page into top sub-tabs/categories.
- Provide interactive catalog/comparison tables for sub-agents/models and voice models, with sorting, filtering, tags/descriptions, prices/capabilities when trustworthy, and clear availability state.
- Distinguish loaded/usable models from models that are discoverable/relevant but not currently configured, and provide an explicit “request/add model” workflow rather than pretending unavailable models are usable.
- Reuse shared catalog/table components across text/sub-agent and voice model surfaces.

## Non-goals

- Do not remove the backend routing policy merely because the “Aiguillage” UI is removed.
- Do not hard-code a stale active model list; live provider/CLI discovery remains authoritative for usability.
- Do not fabricate model prices, benchmark scores, or capability claims without a source/freshness field.
- Do not expose every low-level voice knob by default; Advanced/Diagnostic tabs may contain expert settings.
- Do not reimplement speech arbitration inside settings; consume the supported turn-taking contract from the voice task when available.

## Mental model

The current repository already has `model_catalog.py` fetching live provider model lists, `cli_catalog.py`, a routing domain/runtime/hook, and a large `control_center.html`/`control_center.py` settings surface. The recent routing task also added a user-facing “Aiguillage” tab. This handoff changes the **product information architecture** while preserving the working backend policy.

Target IA: Agent/CLI configuration contains a technical-first options panel (delegation mode Auto/Dupliqué and other supported technical controls) followed by behavior/personality controls (verbosity, politeness/formality, explanation depth, confirmations/proactivity as supported). A dedicated **Sous-agents / Modèles** catalog presents the inventory rather than exposing routing internals. The voice section gains top sub-tabs such as Architecture, Conversation, Turn-taking & interruptions, Models, Audio, Advanced, Diagnostic; exact final labels are refined with `/impeccable` but the categorical separation is locked.

A shared catalog view model merges authoritative live availability from provider/CLI discovery with optional metadata overlays (cost, qualitative tags, descriptions, capability hints, recommended uses). Every non-live metadata field must carry source/freshness/provenance or be explicitly marked unknown. States distinguish `usable/loaded`, `available but not configured/wired`, and `requestable/known candidate` only when the backend can support those meanings. The table component supports sorting/filtering/comparison and is reusable for voice models.
