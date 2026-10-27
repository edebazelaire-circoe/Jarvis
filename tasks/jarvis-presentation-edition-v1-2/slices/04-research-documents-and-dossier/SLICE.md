# Slice 04 — Durable research documents in the Board Dossier

## Goal
Ensure substantial research leaves clean, durable source documents inside the project so future presentation work can reuse them directly.

## Context
The user asked for research “artifacts/documents”. Current registry Artifacts are a closed evidence/capture model, while Board memory owns revisable project files and Dossier already unifies Board memory with linked Artifacts. The least contradictory V1.2 design is therefore a Board-memory research document surfaced through Dossier.

## Canonical Concepts
- `docs/boards.md` Board memory and Dossier.
- `docs/artifacts.md` closed Artifact kinds and evidence semantics.
- `workspace_mcp.py` dossier and board-memory tools.
- Slice 03 freshness/provenance rules.

## Scope
### In Scope
- define a durable research-document location such as `memory/documents/research/<topic>.md`;
- produce a document after substantial research, not after every trivial lookup;
- include title/scope, concise executive summary, findings, source list with URLs/paths and relevant dates, last checked time, uncertainties/contradictions and reuse/freshness note;
- keep the document human-readable and machine-discoverable through existing Board memory search/Dossier;
- link important research documents from the project digest when they become key project sources;
- allow later Presentation generation to cite/read the existing document instead of re-running research;
- support update/refresh of an existing document using conditional Board-memory writes.

### Out of Scope
- inventing a generic registry `document` Artifact kind in this Slice;
- duplicating the same document into AppData and `Documents/Jarvis` exports;
- automatic export outside AppData.

## Dependencies
- `02-board-project-continuity`;
- `03-research-reuse-freshness-orchestration`.

## Implementation Steps
1. Define the research-document template/metadata convention and naming/path rules.
2. Update Research Lead completion behavior: when the mission is substantial, synthesize the durable document after agent evidence converges.
3. Write via `board_memory_write`/bounded workspace APIs; use conditional replace on refresh.
4. Ensure Dossier lists the document naturally and `dossier_view`/`dossier_present` can display it without special copying.
5. Update `summary.md` Documents clés when the research becomes a key source.
6. Make future research discovery inspect these documents first and read freshness metadata.
7. Add error behavior: if document persistence fails, report the research result but mark durability failure visibly; do not pretend it was stored.

## Files Likely Touched
Research Lead/role instructions, Board-memory helper/template code if needed, Dossier tests only if current behavior is insufficient, docs/tests.

## Architecture Constraints
- Board memory is the single owner of revisable research docs;
- Dossier is the human projection; do not create a second document registry;
- no external export unless explicitly requested.

## Automated Validation
- substantial research -> one durable document in correct Board;
- small lookup -> no unnecessary document;
- Dossier list/view returns the research document;
- later presentation authoring uses existing research doc without redundant search;
- refresh updates/checks the same source document safely;
- write failure is observable and does not corrupt previous version.

## Acceptance Criteria
A user can open the Board later, see the research document in the Dossier, understand when/sources it came from, and use it as presentation source material without repeating the original research.

## Documentation Updates
Document the research-document convention beside Board/Dossier and research-role contracts.

## Handoff Notes
If Slice 00 finds a newer canonical document owner already merged into `main`, use it instead; do not force this path against newer architecture.