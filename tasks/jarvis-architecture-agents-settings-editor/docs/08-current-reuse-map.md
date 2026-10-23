# 08 - Current Reuse / Move / Replace Map

Audit source: live GitHub connector against `edebazelaire-circoe/Jarvis` `main` plus the existing Drive task `jarvis-settings-ui-reorganization`.

| Current area | Current capability | Target decision |
| --- | --- | --- |
| `jarvis/domain/subagent_roles.py` | Seven canonical roles, identity, mission, tools, skills, Work Methods, loadout, capabilities | **KEEP as source of truth** |
| `docs/subagent-roles.md` | Role contract and Settings behavior | **KEEP/UPDATE** with new page destination |
| `control_center_subagents_settings.js` | Role list/detail, instructions, optimistic revisions, robust errors, Work Method candidate UI | **REUSE behavior, redesign surface** |
| `jarvis/domain/routing.py` | Task profiles, candidate refs, availability checks, fallback selection | **REUSE selection primitives**, add role-oriented layer |
| `jarvis/runtime/agent_routing.py` | Stored policy, ordered candidates, fallback, `Auto`/`Duplique` projection | **REUSE compatibility and candidate mechanics; replace ordinary UI concept** |
| `jarvis/runtime/model_catalog.py` | Provider/model catalog and capability roles | **KEEP authoritative** |
| `jarvis/runtime/agent_settings.py` | CLI command/model/permission persistence | **REUSE only what maps to real brain/model config; keep command/permission Advanced** |
| `jarvis/runtime/tool_brain_brief.py` + Tool Brain ownership | Tool Brain runtime presence/ownership/fallback | **KEEP as runtime truth; expose Tool Brain in graph when active/available** |
| `docs/ARCHITECTURE.md` | Core/Voice process ownership and current architecture | **KEEP as audit input; update with generic editable graph contract** |
| Existing Settings task Slice 04 | `Agents & modeles` including behavior/personality | **SUPERSEDED by this handoff** |
| Existing Settings shell Slice 02 | New full-screen neon Settings shell | **SOFT REQUIREMENT** for final integration |
| Voice architecture compatibility settings | Legacy/simple/front/duplex compatibility details | **ADVANCED**, not normal Architecture & Agents UX |
| Raw CLI paths/permission/re-probe | Operator/runtime setup | **ADVANCED** |
| Tone/politeness/verbosity | User-facing personality behavior | **MOVE/KEEP in Personalization/Voice, never here** |

## Role inventory at creation time

`docs/subagent-roles.md` currently documents:

- interviewer;
- research;
- web-research;
- coder;
- concept;
- research-lead;
- qa;
- compatibility alias `reviewer -> qa`.

Slice 00 must treat this inventory as evidence, not an eternal hard-coded list: re-audit `main`, then render whatever the canonical registry returns.

## Current routing compatibility

Current routing uses task profiles and stores ordered `CandidateRef(agent, model)` values with general fallback. The current `delegation_mode` is only a projection over `agent_routing.enabled`:

- `auto` - uses routing policy on the Claude host;
- `duplicate` - inherits caller CLI/model and does not actually duplicate execution.

The new UX must not misrepresent these historical names as the new per-brain delegation intensity. Migration must preserve existing settings while introducing the new role-oriented policy and brain delegation contract.
