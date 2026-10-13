# Slice 07 — Voice generation and re-edit on the master path

## Goal

Make the normal spoken/text workflow produce a master-ready Remotion video and allow later voice edits to refresh/re-export it without Remotion Studio.

## Context

The user explicitly accepts scene-level durable source edits as the write mechanism for now, provided the result behaves like one Remotion video for Studio/export.

## Canonical Concepts

Native authoring profile, presentation_source read/write/preview, master readiness/status, explicit-user export trust rule.

## Scope
### In Scope

- authoring guidance/defaults that intentionally use one compatible master video spec across newly generated scenes;
- agent-visible master readiness/reason through an existing or additive inspect surface;
- whole-video export selection when user asks to generate/export the video;
- source re-edit changes exact pin/project key automatically;
- real trace: create -> export -> voice edit -> re-export.

### Out of Scope

- direct arbitrary writes to the master workspace;
- agent opening unsandboxed native Studio by itself;
- changing voice wake/routing architecture unrelated to presentation authoring.

## Dependencies

`03-master-project-planner`, `06-whole-variant-render-export`.

## Implementation Steps

1. Refresh current presentation author playbook/native guide and tool contracts.
2. Teach generation to keep scene dimensions/fps/master-relevant config compatible by construction, without reintroducing the old restrictive guided content model.
3. Add/read master readiness in the agent workflow before claiming full-video capability.
4. On explicit user export instruction, route to whole-variant render rather than one scene when ready.
5. Keep scene `presentation_source write` as the durable edit door; after a standing edit, prove project key/readiness update without an extra manual sync command.
6. Give actionable refusal wording when legacy/current variant is incompatible; never auto-mutate it.
7. Run real agent traces including one user correction/edit and second export.

## Files Likely Touched

`jarvis/runtime/presentation_playbooks.py`, `jarvis/domain/presentation_studio_authoring_guide.py`, `jarvis/runtime/presentation_studio_mcp_tools.py`, Remotion MCP export/status tooling, prompt/tool docs and agent trace tests.

## Architecture Constraints

Do not make the agent pretend the master workspace is canonical. Do not add content-style restrictions unrelated to master technical compatibility. Studio remains an explicit user surface, not a hidden agent requirement.

## Automated Validation

Prompt/tool unit tests; no-catalog-budget regression; real agent trace analysis; source repin changes project key; export after edit uses new snapshot/source; refusal trace for incompatible legacy variant.

## Acceptance Criteria

A user can say, in effect, "make me a video", then later "change scene 2 / change the style / fix this text", and receive a refreshed whole-video Remotion export without opening Studio. The agent accurately reports what it did.

## Documentation Updates

Update presentation authoring and MCP tool contract docs, including what "native" means in this A+B architecture.

## Handoff Notes

Coding/agent-runtime Slice: `/caveman` + `/coding-guideline`; mandatory QA + code-review + runtime-validation where tools touch runtime + **real `agent-trace-analysis`**. Human check `HV-RMP-07-01` only after trace gates.
