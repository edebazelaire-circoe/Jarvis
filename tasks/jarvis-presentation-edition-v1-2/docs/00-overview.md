# V1.2 overview

## Goal
Amend the first Presentation Edition productionization task so the shipped product behaves like a project-oriented Presentation assistant rather than a generic developer agent with a slide tool.

## Mental model
`Board = durable Presentation project`.

The user works in one project over time. Voice/chat are only interaction surfaces. Sessions may come and go. The Board memory and Dossier are the durable project context. Several presentations and research documents may belong to the same Board.

The product brain should be able to:
- interview and clarify;
- search existing local/shared documentation;
- orchestrate documentary/web research in the background;
- use CIRCOE Mail/Calendar and approved connectors where useful;
- create durable research/project documents;
- conceptualize and author presentations;
- produce bounded Remotion/prefab code through Presentation capabilities.

It should **not** be able to act as a general Jarvis developer or arbitrary machine shell.

## What already exists
Current `main` already has Level-3 Board memory/Dossier, Sessions, background Board brains, agent roles, Research Lead, nested sub-agents, relations, research Work Methods, workspace MCP tools and Presentation infrastructure. V1.2 strengthens contracts and fills product gaps; it must not duplicate these systems.

## Main deltas
1. Presentation-specific brain/capability scope.
2. Board-as-project continuity convention and resume behavior.
3. Research reuse/freshness policy and traceable orchestration.
4. Durable research documents in the Board Dossier.
5. Product voice lifecycle: Off / Sleep / Active + chat behavior.
6. Simpler novice-facing product surface while preserving full Settings.
7. Bug-report diagnostic bundle and support-send flow.
8. macOS portability/build validation path.

## Non-goals
No second research orchestrator, no second project database, no general document Artifact kind by default, no cloud split, no removal of support/debug Settings, no arbitrary source-code development ability in the distributed product.