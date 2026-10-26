# Slice 04 — Agent confinement and product capability policy

## Goal
Make Presentation Edition safe to run with high automation by removing general filesystem/shell/process authority from the distributed brain and sub-agents, while preserving all capabilities required to research, author, edit, present and export a Presentation.

## Context
Current conversation-agent defaults include Claude `bypassPermissions` and Codex `danger-full-access`. Repository docs explicitly state `--add-dir` is not a security boundary. Board/Context filesystem adapters are strongly bounded, but a broadly privileged CLI can bypass those adapters.

## Canonical Concepts
- agent execution settings: `jarvis/runtime/agent_settings.py`;
- Claude local runtime and restricted profiles: `jarvis/runtime/claude_local.py`;
- tool gateway/capability discovery: `jarvis-tools`, `tool_brain` docs/runtime;
- product edition capability policy from Slice 01;
- export service from Slice 03.

## Scope
### In Scope
- define a Presentation product agent execution profile/capability manifest;
- remove arbitrary Bash/PowerShell/general write/edit/process tools from normal product brain turns;
- ensure sub-agents/jobs cannot regain broader ambient privileges unless a narrowly specified internal role requires and enforces a bounded workspace;
- keep read/search/document research, Presentation authoring/editing, Board memory, bounded internal document writes, explicit export and allowed connectors;
- enforce tool availability at launch/config/tool-catalog layers, not prompt text alone;
- add traceable refusals/absence for out-of-policy actions.

### Out of Scope
- no OS sandbox product rewrite;
- no generic computer-use feature;
- no weakening Presentation authoring quality to avoid solving capability routing.

## Dependencies
Hard `depends_on`: `01-product-edition-and-board-lock`, `03-internal-documents-and-export-boundary`.

## Implementation Steps
1. Inventory every tool/permission path available to conversation brain, per-turn agents, background jobs and Presentation author/reviewer roles.
2. Create one Presentation product capability manifest mapped to actual CLI/tool arguments and MCP servers.
3. For Claude, select/build a permission/tool configuration where unavailable general write/shell tools are not exposed. Do not rely on `bypassPermissions` as a product security boundary.
4. For Codex or alternate CLIs, either implement equivalent confinement or mark them unavailable for Presentation Edition until the boundary is real.
5. Ensure Presentation authoring writes happen through the canonical Presentation source/workspace APIs/services under AppData, not arbitrary filesystem paths.
6. Wire explicit export tool/capability from Slice 03; no generic path write.
7. Make sub-agent inheritance explicit: tool gateway and Presentation tools may be inherited only according to role policy; shell/write authority must not appear through delegation.
8. Add prompt text explaining capabilities only after enforcement exists; prompts must not describe unavailable tools.
9. Add real agent traces for normal authoring/export and hostile outside-write/shell requests.
10. Document residual risks and any narrowly-scoped subprocesses owned by Jarvis itself (Remotion/FFmpeg) versus model-callable process tools.

## Files Likely Touched
- `jarvis/runtime/agent_settings.py`;
- `jarvis/runtime/claude_local.py`;
- CLI catalog/tool argument builders;
- prompt catalog/agent role routing;
- Presentation authoring MCP/runtime wiring;
- tool gateway policy/tests;
- security docs.

## Architecture Constraints
- capability absence must be enforceable without trusting the model;
- Jarvis-owned Remotion/FFmpeg subprocesses are not equivalent to model-accessible shell;
- sub-agent delegation cannot bypass the parent product policy;
- maintain enough read/search capability for document research and IGuard/Drive use.

## Automated Validation
- launch-argument/tool-catalog tests for Presentation product profile;
- tests proving shell/general write/process tools are absent;
- delegation inheritance tests;
- real agent trace: create/edit/export a Presentation without forbidden capabilities;
- hostile trace: ask to write Desktop file, run PowerShell, delete arbitrary path; verify no executable capability is present and no file/process side effect occurs.

## Acceptance Criteria
- product brain cannot write outside bounded Jarvis internal/export services through any advertised tool;
- arbitrary shell/process execution is not model-callable in Presentation Edition;
- normal Presentation research/author/edit/export still works;
- sub-agents cannot escalate beyond the product capability policy.

## Documentation Updates
Raise Presentation product agent capability/confinement to Level 3 with a manifest, launch enforcement and trace-based conformance tests.

## Handoff Notes
Coding Slice: `/caveman`, `/coding-guideline`. Required QA: `qa-verification`, `code-review`, `runtime-validation`, and **mandatory `agent-trace-analysis` with real trace evidence**.

## Slice 00 amendments (2026-10-26)
- Reuse the existing restricted-profile flags (`--tools`, `--allowedTools`, `--strict-mcp-config`, `dontAsk`; `jarvis/runtime/claude_local.py:379-437,1203-1239`) instead of building a parallel mechanism.
- The conversation launch (`claude_local.py:1247-1282`) currently has no `--tools` and no `--strict-mcp-config`. The user's personal MCP servers load (`:1627-1630`), as does `--chrome`. All three must be closed in the product profile.
- E9: agent CLI settings are global and editable from the UI (`control_center.py:1848-1865`). The edition must impose the product profile; a UI setting must not be able to widen it.
- Paths outside the conversation brain that must be closed too: Back Brain jobs (`back_brain_worker.py:59-71`), self-dev (`self_dev.py:293-304`), the debug console (`claude_local.py:888-896`) and sub-agents inherited through `Agent`/`Task`.
- E4: Codex is recommended as unavailable in the Presentation edition until it has real confinement.
