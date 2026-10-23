# 05 - Documentation Levels

## Canonical concepts and current level

| Concept | Current evidence | Target level |
| --- | --- | --- |
| Sub-agent roles | `docs/subagent-roles.md`, `jarvis/domain/subagent_roles.py`, tests | Level 3 - reuse, do not fork |
| Task-profile routing | `jarvis/domain/routing.py`, `jarvis/runtime/agent_routing.py`, tests | Level 3 for current mechanism; document role-oriented compatibility/migration |
| Model/provider catalog | `jarvis/runtime/model_catalog.py`, provider catalog code | Level 3 - reuse |
| Tool Brain ownership | `tool_brain_ownership.py`, `tool_brain_brief.py`, related contracts | Level 2/3 - preserve runtime ownership truth |
| Brain topology graph | No single generic editable graph contract proven by audit | Raise to Level 2 contract + Level 3 implementation in Slice 01 |
| Generic brain config | Current config is implementation-specific, not one generic contract | Raise to Level 2/3 in Slice 02 |
| Role-specific candidate policy | Current routing is task-profile based | Raise to Level 2/3 in Slice 03 while preserving compatibility |
| Architecture Settings UX | Only mockups/discussion | Raise to Level 2 product contract in this handoff and Level 3 UI implementation |

## Documentation obligations

- New topology/brain-config/role-routing contracts get dedicated repository documentation.
- Existing `docs/subagent-roles.md` is updated by reference; do not copy its full contract into another competing document.
- `docs/settings/INDEX.md` or the current canonical Settings IA documentation must point to `Architecture & Agents` and its two tabs.
- Old `Agents & modeles` documentation is marked superseded or rewritten, not left as a contradictory source.
