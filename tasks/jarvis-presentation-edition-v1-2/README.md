# Jarvis Presentation Edition V1.2 — amendments handoff

## Project
- Project: `Jarvis`
- Repository: `edebazelaire-circoe/Jarvis`
- Source branch audited: `main`
- Source SHA at task creation: `2d6ca879afac7a0e773598cff0872b4f819fa876`
- Handoff slug: `jarvis-presentation-edition-v1-2`
- Parent baseline handoff: `Jarvis/task/to-do/jarvis-presentation-edition-v1/`
- Target Drive queue: `Jarvis/task/to-do/jarvis-presentation-edition-v1-2/`

## Purpose
This handoff is the **V1.2 amendment layer** for Jarvis Presentation Edition. It does not replace the first V1 productionization task wholesale. It records the product corrections and behavioral requirements clarified after that first pass, then turns them into focused implementation Slices.

When this handoff conflicts with the earlier `jarvis-presentation-edition-v1` planning, V1.2 is the newer product decision. Slice 00 must reconcile both tasks with current `main` before dispatching code.

## Locked amendments
1. A Presentation Board is a **project**, not merely a conversation container. Jarvis must reopen it already knowing its purpose, objectives, decisions, current state, useful documents, open questions and next steps.
2. Use the existing Board memory architecture. `summary.md` becomes the canonical Presentation-project digest convention because it is already automatically hydrated on every turn; do not create a second competing project-state store without evidence that one is required.
3. Jarvis remains Presentation-focused, but it is not reduced to slide generation. It may interview, reason, search, read shared documentation, use CIRCOE Mail/Calendar, Google Drive and IGuard/documentary connectors when available, and help structure the project.
4. Distributed Presentation Edition must not behave as a general development agent. It must not edit the Jarvis repository or perform arbitrary coding. Code execution is allowed only through bounded Presentation production capabilities such as Remotion/prefab authoring and rendering.
5. Preserve and actively use the existing organic agent system: Interviewer, Research, Web Research, Research Lead, Concept, QA, nested sub-agents, delegation/communication/adversary/QA/handoff relations and background execution. Do not build a second research orchestrator.
6. Before launching new research, the research path must first inspect reusable existing material: current Board memory/Dossier, Jarvis/global knowledge, connected shared documentation, Drive/IGuard when applicable, and prior research documents.
7. Reuse is **freshness-aware**. A previous document is not automatically valid because it exists. The system must consider when it was checked, source dates, topic volatility and explicit requests such as “latest/current”. Reuse, partial refresh or full refresh must be an intentional decision.
8. A substantial research job must leave a durable, clean research document in the Board Dossier so it can become source material for later presentations without repeating the same research.
9. Keep the current Settings surfaces, including transcription/voice/debug-oriented settings. They are useful for support and field debugging. Simplify the ordinary user path through progressive disclosure; do not solve usability by deleting diagnostic settings.
10. Normal application launch starts Jarvis services and leaves voice in **Sleep** with wake-word detection armed, unless the user explicitly persisted Voice Off. Closing the application stops Core/Voice/child runtimes. Chat remains usable while voice is Sleep or Off and must not silently re-enable microphone/TTS.
11. Add a simple **Report a problem** flow. It produces an AI-assisted diagnostic report plus a ZIP snapshot of the Jarvis AppData context, with secrets/credentials excluded or redacted, then offers a configured support-send path and a manual-save fallback.
12. Keep the original storage decision: installed internal/canonical state, Board documents, `CONTEXT_GLOBAL`, artifacts and working files live under Jarvis AppData. `Documents/Jarvis` is export-only.
13. macOS must be treated as a real portability target. Development can stay on Windows, but CI must build/test on macOS. Do not claim macOS supported until a real Mac acceptance pass covers launch, permissions, voice, Presentation and packaging.
14. No long-lived Windows-vs-Mac product branches. Platform differences live behind explicit adapters/packaging directories.

## Existing implementation evidence that V1.2 must reuse
- `docs/boards.md`: Board/Session contract, Board memory hydration, Dossier, background Board work and workspace tools are already Level 3 concepts.
- `jarvis/domain/subagent_roles.py`: existing Interviewer, research, web-research, research-lead, concept, coder and QA roles; current research roles already write to a shared mission dossier.
- `jarvis/domain/work_methods.py`: quick/deep/comparative research and adversary/QA relation hints already exist.
- `jarvis/runtime/workspace_mcp.py`: delegated agents already inherit Board memory/Dossier/relations tools.
- `docs/artifacts.md`: registry Artifacts are evidence/capture objects with a closed kind set. Revisable project research documents should therefore use Board memory/Dossier unless a separate contract explicitly justifies a new Artifact kind.

## Project Manager entrypoint
Start at `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md` yourself. No implementation dispatch below `READY`.

The Project Manager must first audit current `main` blindly, then reconcile:
- current code/docs;
- parent task `jarvis-presentation-edition-v1`;
- this V1.2 amendment task;
- any overlapping current/to-do Jarvis tasks.

## Global QA doctrine
Every implemented Slice gets `qa-verification`. Code changes add `code-review`. User-visible/runtime changes add `runtime-validation`. Agent prompts, routing, tools, roles, work methods or agent runtime changes add `agent-trace-analysis` with real trace evidence.

QA agents return evidence and findings; the Project Manager decides approve, rework, continue, split/new Slice, Issue or Human escalation. A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.

Human validation is never a substitute for machine validation. Before a Human check, exhaust reasonable automated/runtime validation and clear everything a machine could have caught.

## Coding/frontend requirements
- Every coding Slice requires `/caveman` and `/coding-guideline`.
- Every frontend Slice also requires `/impeccable` and should use a Claude Work Agent where the host supports that routing rule.
- Workspace Task Type vocabulary is not exposed at task creation. Slice 00 must resolve valid existing Task Types before dispatch; never invent one.

## External inputs / blockers
- IGuard-specific implementation still requires its real transport/endpoint/authentication contract if it is not already present by execution time. Research behavior must degrade cleanly without it.
- The exact support recipient/channel for “Report a problem” is not locked here. Bundle generation and manual save are not blocked; automatic send must use configuration, never a hard-coded guessed address.
- Wake-word model/runtime licensing for a distributed product must be resolved before shipping.
- macOS signing/notarization credentials and a real-Mac acceptance machine are required before claiming a supported macOS release.

## Non-goals
- Rebuilding the existing organic orchestration stack.
- Creating a second Board/project database.
- Creating a generic “document Artifact” solely to avoid using Board memory/Dossier.
- Giving the product brain general repository/shell/filesystem authority.
- Removing Settings needed for support/debugging.
- Cloud/server split or cross-device sync.