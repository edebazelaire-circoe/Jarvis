# 06 - Exhaustive Functional Specification

This document is the primary feature checklist for the page.

## A. Page shell and navigation

- Page title: **Architecture & Agents**.
- Exactly two internal tabs: **Architecture** and **Sous-agents**.
- No permanent Brain/Brains tab.
- Use the global Settings visual shell when it lands; do not create a second Settings shell.
- Keep the approved dark/neon/glass visual language.
- Keep the global circular profile/avatar control if that is part of the new Settings shell; it is not a brain selector.
- No inspirational quote block.

## B. Architecture tab - graph canvas

### B1. Real topology

- Render nodes/endpoints from the runtime architecture snapshot.
- Show actual current wiring, not a hand-authored decorative network.
- Audio input is visible as ingress.
- Audio output is visible as egress.
- Show Voice Brain, Core Brain and Tool Brain when the live main audit confirms them.
- Do not show speculative Routing/Reflex/Vision/Task brains unless they actually exist at runtime.
- Future brain types must be representable without redesigning the entire page.

### B2. Node interactions

- Brain nodes are draggable on a 2D canvas.
- Dragging persists UI layout only.
- Node active/health/readiness state is visible.
- Activation/deactivation is available only when the runtime declares it safe/mutable.
- Locked/system nodes communicate why they cannot be disabled/deleted.
- Right click/context action opens a menu with brain-specific actions (minimum: inspect/configure; enable/disable only if allowed).
- Optional creation/removal of non-system brains is supported only if the runtime registry exposes a legal operation. The contract must allow future addition even if v1 hides the action.

### B3. Connection semantics

Each rendered link exposes:

- source and target;
- arrow direction;
- semantic purpose/channel;
- enabled/disabled state;
- mutability;
- optional short label such as audio, text request, response, tool call, result, event/impulse when that is the real channel;
- reason/impact text on inspection.

Required visual states:

1. required/locked;
2. editable active;
3. editable disabled;
4. creatable/removable when supported.

The graph should include a compact legend so a user can understand the states without guessing.

### B4. Connection edits

- Toggle an editable link on/off.
- Remove a removable link.
- Create a connection by selecting/dragging between compatible ports when supported.
- Reject incompatible source/target/channel combinations.
- Reject edits to locked links.
- Display the runtime-provided reason for rejection.
- Refresh from the authoritative snapshot after mutation.
- If a mutation fails to apply in the runtime, do not leave a false visual state.
- A connection change must have real behavioral consequences; final QA proves at least one end-to-end path.

### B5. Connection inspection / impact

- Selecting a link exposes its meaning and mutability.
- For editable links, show a concise impact description (for example which capability stops working) when the runtime can provide it.
- A disabled link remains visible as disabled when useful for understanding the configured topology.

### B6. Architecture state/supporting UI

The page may show compact architecture status/health and a change journal if those use real existing data. They must not displace the graph.

Reference-image controls such as presets, reset, test-flow and analytics are **not automatically required**. Add them only if current runtime capabilities justify them and the PM records the decision.

## C. Brain configuration popup

### C1. Launch/placement

- Open from the selected brain's right-click/context action.
- Float over the Architecture page rather than navigating to a third tab.
- Window may be draggable; on constrained viewports it may adapt to a centered overlay/drawer.
- Keep enough graph context visible for the user to understand what is being edited.

### C2. Identity/status

- Brain id/type (read-only stable identity).
- Display name/label where editable.
- Current active/readiness state.
- System/locked badge where relevant.

### C3. Model/provider

- Provider/harness/model selection only from server-described compatible candidates.
- Availability state and unavailable reason.
- Optional fallback model only if that brain/runtime actually supports one; do not invent a generic fallback field.
- Never hard-code mockup examples such as GPT-4o/Claude/Gemini/Whisper as the catalog truth.

### C4. Mission and prerogatives

- Mission/responsibility text.
- Supported permissions/prerogatives/capabilities exposed by the brain contract.
- Brain-specific prompt/instructions where the runtime supports an editable prompt.
- Validation limits come from the backend contract.

### C5. Delegation behavior

The popup controls how likely this brain is to use sub-agents:

- Never;
- Rare / occasional;
- Standard;
- Proactive;
- Exploratory / spread.

This setting may map internally to thresholds/prompt/routing policy, but the UI vocabulary remains user-facing and consistent.

The brain may also expose a simple `sub-agents allowed` capability if necessary, but it must not duplicate the global role -> candidate configuration.

### C6. Connection summary

- Show the brain's current incoming/outgoing connection summary and locked/editable status.
- Canonical connection editing remains on the graph; the popup should deep-link/focus the connection rather than create a second independent persistence path.

## D. Sous-agents tab

### D1. Canonical role roster

Render the current role registry, not a mockup-only list. At handoff creation, `main` documents seven active roles:

1. `interviewer` - Intervieweur
2. `research` - Recherche documentaire
3. `web-research` - Recherche web
4. `coder` - Developpement
5. `concept` - Conceptualisation
6. `research-lead` - Direction de recherche
7. `qa` - Controle qualite

Preserve aliases such as `reviewer -> qa` as compatibility metadata, not a second role.

### D2. Role identity/detail

For each role expose, using canonical data:

- name/id/marker and visual identity;
- mission;
- when-relevant guidance;
- capabilities;
- `can_spawn` / Mission Owner capability where relevant;
- tools;
- skills;
- knowledge/loadout role;
- Work Methods and default Work Method;
- current editable role instructions and modified/conflict state;
- whether offered to the brain/sub-agents;
- concise active instance context when useful.

### D3. Role candidate routing

The ordinary UI configures, per role:

- ordered preferred harness/agent + model candidates;
- priority represented by candidate order rather than a separate duplicate truth where possible;
- availability/readiness and why an item is unavailable;
- fallback candidate/order;
- inherited/default policy provenance during migration;
- ability to restore role policy to inherited/default behavior.

The live model catalog is authoritative.

### D4. Global policy visualization

A routing matrix or compact overview may visualize role -> preferred candidate mapping. It is a projection of the same policy, not a second editable database.

The approved reference also depicts global switches such as automatic intent analysis, load awareness, automatic fallback and result validation, plus global cost/timeout/knowledge/collaboration controls. Treat these as **candidate controls only**: expose a control only when Slice 00/current runtime proves there is one canonical setting and real behavior behind it. Do not invent a frontend-only switch. Automatic fallback is already conceptually supported by current routing and may be surfaced through the new role policy. Load-aware balancing, cost limits, validation orchestration and collaboration require separate runtime evidence before entering the normal page. A generic creativity/personality setting is explicitly forbidden here.

Existing profile routing can remain visible in Advanced/diagnostic mode if needed for compatibility. The normal tab speaks in role concepts.

### D5. Role instruction editing robustness

Preserve the existing UI's strong behavior:

- loading, timeout and unreachable states;
- partial payload/version warning;
- optimistic revision conflict handling;
- user draft preservation after conflict/refusal;
- explicit unknown outcome and forced re-read after a write with no response;
- reset to default instructions;
- server error codes/reasons;
- role registry remains usable if active-instance context fails.

### D6. Work Methods

- Display canonical Work Methods relevant to the role.
- Ordinary selection/default behavior may stay if it is already a normal role property.
- Candidate promotion/learning operator tooling stays Advanced unless the fresh audit proves it has become a normal user setting.

## E. Legacy/current Settings redistribution

### Keep/reuse on this page

- compatible model selection;
- role registry and role instructions;
- role candidate/fallback configuration;
- concise brain/runtime availability needed to make a choice.

### Move/remain in Advanced

- CLI command/path;
- Claude/Codex permission/sandbox mode;
- re-probe/re-detect;
- raw model/provider catalog source diagnostics;
- legacy compatibility stack values;
- low-level routing internals not needed for role configuration;
- Work Method promotion/learning diagnostics if operator-only.

### Must not appear here

- tone/politeness/formality;
- verbosity/response length/personality;
- humor;
- voice/persona choice;
- unrelated audio tuning;
- generic diagnostics dashboards;
- the old `Auto` / `Duplique` choice as the primary product concept.

## F. Persistence and safety

- Every visible editable value has one canonical backend owner.
- Frontend state is never the sole source of truth for runtime topology.
- Config writes are revisioned/validated when concurrent editing can occur.
- Existing valid settings are preserved during migration.
- Unknown/unavailable models/candidates remain inspectable with a reason.
- Invalid stored combinations are reported, not silently rewritten into a different behavior.

## G. Accessibility and interaction quality

- Keyboard access to tabs, nodes, context actions and popup controls.
- A non-right-click path to the same brain menu for keyboard/touch users.
- Focus management when popup opens/closes.
- Color is not the only encoding for locked/active/disabled link types; use icon/line style/label too.
- Tooltips/labels explain technical state without forcing the user to infer from glow colors.
- Respect reduced-motion where relevant.
