# Jarvis V1 - Task board

## Context

This project builds a local V1 Jarvis assistant from the audit of `jaredrhod/fullstack-agent`. The target is a safe, modular prototype rather than a direct fork.

## Mandatory working mode

Start with `00-orchestrator`. The active implementation agent must remain in **orchestration mode**: complete one task, run its tests, update status, then move to the next task only when acceptance criteria are met.

The orchestrator may edit this plan when implementation reality requires it. If it creates, splits, reorders, or changes a task, it must update this file and record the reason in `docs/01-decision-log.md` or an implementation note.

## Skills for every coding task

Before coding, load these two skills from `~/ai/skills/`:

- `/caveman`
- `/coding-guideline`

Treat that requirement as mandatory for tasks 01-11 whenever code is changed.

## Global implementation rules

- core imports no provider SDK types ;
- every external system sits behind a port/adapter ;
- return typed result objects, not provider dictionaries ;
- all writes go through ActionBroker ;
- no general shell tool ;
- no runtime CDN ;
- loopback only ;
- no transcript/prompt content logs by default ;
- keep upstream provenance and license information ;
- add tests with every behavior change ;
- never make UI availability a prerequisite for the voice loop.

## Ordered tasks

- [ ] 00 - Orchestrator and plan ownership
- [ ] 01 - Pin upstream snapshots and establish third-party boundaries
- [ ] 02 - Create Jarvis core skeleton and typed contracts
- [ ] 03 - Implement state machine and file signal bus
- [ ] 04 - Implement push-to-talk and OpenAI transcription
- [ ] 05 - Implement AgentBackend and minimal tool registry
- [ ] 06 - Implement TTS and interruption loop
- [ ] 07 - Implement ActionBroker and confirmation flow
- [ ] 08 - Implement Markdown memory and local search index
- [ ] 09 - Harden and integrate Barehands
- [ ] 10 - Integrate visualizer, launcher and health diagnostics
- [ ] 11 - Run E2E security/quality gates and produce final report

## Picking the next task

Always take the first unchecked task whose dependencies are complete. Do not skip ahead to attractive UI work while core contracts or security gates are incomplete.

## Completion protocol

After each task:

1. run required tests ;
2. update this checklist ;
3. document deviations ;
4. record files changed ;
5. leave handoff notes for the next task.

At the end, produce a report using `templates/final-implementation-report-template.md`.
