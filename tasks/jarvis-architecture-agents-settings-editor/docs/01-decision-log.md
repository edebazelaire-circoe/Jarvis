# 01 - Decision Log

## Locked decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D01 | Page name is `Architecture & Agents`. | Replaces the rejected generic Agents/models concept. |
| D02 | Exactly two page tabs: `Architecture` and `Sous-agents`. | Brain settings are contextual, not a third navigation destination. |
| D03 | No `Brains` tab. | Explicit user correction. |
| D04 | Brain configuration opens from a brain context action/right click in a floating overlay/panel. | Keeps architecture visible and configuration attached to the selected brain. |
| D05 | The architecture graph is an operational control surface. | A connection represents real runtime behavior, not decoration. |
| D06 | Links are directional, typed and expose mutability. | The user must understand who calls whom and why. |
| D07 | Required links are visibly locked and cannot be disabled or removed. | Prevent impossible/broken configurations. |
| D08 | Editable links can be enabled/disabled and, where supported, created/removed. | Topology editing changes the runtime architecture. |
| D09 | Default graph contains only currently real brains/endpoints after a fresh main audit. | No fictional future topology. |
| D10 | Audio input/output are first-class graph endpoints. | The requested architecture must show ingress and egress. |
| D11 | Current Tool Brain must be represented if the main audit still confirms its live runtime role. | Explicit user request and current repo evidence. |
| D12 | Node drag position is UI layout state only. | Moving a box must not accidentally rewire the system. |
| D13 | Brain config controls model/provider, mission, brain rules/prompts, valid activation, and delegation tendency. | Matches user mental model. |
| D14 | Delegation tendency has five conceptual levels: never, rare/occasional, standard, proactive, exploratory/spread. | Explicit requested granularity. |
| D15 | Brain config determines **when/how much** to delegate, never the exact role/model candidate. | Keeps responsibilities clean. |
| D16 | Global Sous-agents config determines role and ordered harness/model candidates/fallbacks. | Exact sub-agent choice is global. |
| D17 | Reuse the current seven-role registry. | Canonical repo data already exists and is richer than the mockup. |
| D18 | Old user-facing `Auto` / `Duplique` is not the target product model. | Replace with brain delegation + role routing while preserving compatibility internally. |
| D19 | Tone/politeness/formality/verbosity/humor are forbidden on this page. | They belong to Personalization/Voice. |
| D20 | Raw CLI path/command/permission/re-probe/diagnostics remain Advanced. | Keep the normal page product-oriented. |
| D21 | Model/provider and role catalogs remain server-owned. | No duplicated frontend truth. |
| D22 | Approved images are visual references, not literal feature truth. | Avoid copying illustrative role/model names or the obsolete Brains tab. |

## Corrections to earlier concepts

- Remove the `Brains` tab shown in an earlier generated mockup.
- Remove decorative all-to-Jarvis connections.
- Do not make the graph a status dashboard only; every edge must map to a real runtime relationship.
- Do not place personality controls under brain/model settings.
- Do not simplify the current role registry to `Code/Research/QA/Web/Concept` only.

## Provisional choices

These are not blockers and must be resolved by live audit or implementation evidence:

- Exact default x/y positions of nodes.
- Which current edges are locked versus editable. The runtime, not the mockup, decides.
- Whether a generic `Add brain` action is immediately enabled in v1 or only the underlying registry contract is implemented.
- Whether optional reference-image widgets (preset save/load, test-flow, analytics) are omitted or reused from existing runtime capabilities.
- Exact migration representation from current task-profile routing to role-specific policy.

## External task relationship

`jarvis-settings-ui-reorganization` remains the umbrella Settings reorganization. Its Slice 04 is obsolete after this handoff and must not be implemented in parallel. Its shell/navigation work remains relevant and is a soft integration requirement for Slice 07.
