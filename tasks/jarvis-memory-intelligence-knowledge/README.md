# Jarvis Memory Intelligence + Knowledge

Project: **Jarvis**  
Repository: `edebazelaire-circoe/Jarvis`  
Planning snapshot: `main@2ced8dd53519c8fe4e0f6c14ddc943d044ff5e05` (2026-09-12)  
Upstream evaluated: `TencentCloud/TencentDB-Agent-Memory@0468a2a5b50eaafc54758ed1e2e6609472e5b6ce`

## Purpose

Evolve Jarvis from the current Markdown + SQLite FTS memory MVP into a trustworthy memory system with semantic recall, hierarchical consolidation, provenance, optional TencentDB MemoryCore integration, and first-class Wiki, CodeGraph and Skill assets for Jarvis and its sub-agents.

The central invariant is non-negotiable: **Jarvis-owned canonical memory remains human-readable and locally controllable. Derived semantic indexes and external/sidecar memory services must be disposable and rebuildable.**

This handoff also includes the product surface. The implementation must expose useful memory controls and visibility through quick settings and/or a dedicated Memory Center. The exact visual design is intentionally not prescribed. The Work Agent must explore, implement, test, and then submit the result to an independent user-perspective critic agent.

## Locked decisions

- Keep Jarvis canonical memory local and human-readable; do not replace it wholesale with TencentDB Agent Memory.
- Separate canonical storage from retrieval/intelligence concerns instead of expanding the current monolithic `MemoryBackend` indefinitely.
- Add hybrid lexical + semantic recall with RRF or an equivalent explicitly documented fusion strategy; embeddings remain optional and the local lexical path must keep working without them.
- Treat L0/L1/L2/L3 as an abstraction hierarchy orthogonal to Jarvis retention classes (`short_term_memory`, `long_term_memory`, `traumatic_memory`, `eternal_memory`, `plastic_memory`). Do not silently delete the existing class model.
- Add provenance, timestamps, confidence/quality signals, versioning and contradiction handling before automatic long-term consolidation is trusted.
- Memory recall is bounded by count/size/token/time budgets and must not turn the prompt into a memory dump.
- Integrate memory into the authoritative V2 Brain path; do not insert Tencent MemoryProxy as a second hidden orchestrator in front of Jarvis Brain.
- Implement **Wiki, CodeGraph and Skills in this handoff**, not as a deferred future idea.
- Knowledge and Skills are loadout-able per agent/task so a coder, reviewer and research agent can receive different assets.
- Tencent MemoryCore/MemoryKnowledge integration is optional and adapter-bounded. Jarvis must degrade cleanly to local-only operation.
- Prefer Tencent APIs/SDKs or a sidecar boundary over vendoring upstream internals. Any vendoring requires an explicit license/update strategy.
- Memory-related settings and visualization are in scope. The UI may use quick settings, a dedicated Memory Center, or both; implementation choice is evidence-driven.
- A dedicated critic agent must exercise the user-visible memory experience like a real user and report confusing or broken flows before the task can be considered ready.

## Explicit non-goals

- Replacing all Jarvis state/history with TencentDB.
- Routing every LLM request through Tencent MemoryProxy.
- Making remote embeddings mandatory.
- Allowing the reflex/surface voice model to bypass Brain ownership and directly mutate durable memory.
- Automatically sharing private memories or extracted Skills across agents without policy.
- Treating raw conversation history as a substitute for curated long-term memory.

## How the Project Manager starts

Open `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md` personally. Do not delegate Slice 00. The Project Manager performs an independent blind audit of the current repository before reading this handoff's documentation-level conclusions, reconciles drift, and reaches `READY` before dispatching implementation.

The repository moved during planning: the handoff is anchored to the SHA above, but every Slice requires a targeted freshness check immediately before dispatch.

## QA doctrine

- Every implemented Slice receives a baseline `qa-verification` pass.
- Code changes additionally receive `code-review`.
- User-visible or runtime behavior additionally receives `runtime-validation`.
- Agent prompts, tools, routing, memory injection, knowledge loadouts, extraction, or agent runtime changes additionally receive `agent-trace-analysis` with real trace evidence.
- Frontend work requires `/impeccable` and a Claude Work Agent when the host supports that routing rule.
- Coding Work Agents must use `/caveman` and `/coding-guideline`.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and may not be parked in `Issues/`.
- Human validation is never a substitute for machine QA. Before asking a human to inspect the Memory Center, maximize automated/browser/trace validation and clear machine-detectable issues first.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed to this planning environment. Slice metadata therefore leaves `task_type` null and records a blocker. Slice 00 must map each `work_intent` to a valid existing Task Type before dispatch. Do not invent a Task Type.
