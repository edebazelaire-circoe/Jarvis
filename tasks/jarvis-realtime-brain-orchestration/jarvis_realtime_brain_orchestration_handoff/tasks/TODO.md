# Jarvis Realtime + Async Brain - Implementation TODO

## Orchestration mode

A fresh implementation agent must start with Task 00 and remain in orchestration mode for this handoff. Do not jump directly to a coding slice.

Before every coding task:

1. load `/caveman`;
2. load `/coding-guideline`;
3. inspect the current repository state rather than assuming this snapshot is still exact;
4. run the narrow pre-change tests for the layer being modified;
5. make one focused architectural change;
6. run the specified tests and relevant regression gates;
7. update this TODO/status and any raw task plan if discoveries require a safer split;
8. only then move to the next task.

Skills are expected under `~/ai/skills/`.

## Locked project intent

- Realtime is the fast mouth/ears/reflex surface.
- Core owns the asynchronous brain, truth, intent, work state, and task orchestration.
- A completed Realtime response does not end continuous LIVE mode.
- `Jarvis Mute` stops/suspends Voice, not Core work.
- Ambient noise never counts as useful activity.
- User interruption stops speech quickly but does not auto-cancel work.
- No raw chain-of-thought is stored or exposed.
- Single brain/orchestrator now; multi-agent later.
- Keep ports/adapters and provider-neutral Core boundaries.

## Source snapshot to verify before edits

The handoff was built from these inspected files on `main`:

- `jarvis/runtime/voice_v2.py` - response completion currently calls `mute()`.
- `jarvis/runtime/realtime_audio.py` - blocking `claude_task`, closes mic after auto-turn commit.
- `jarvis/adapters/openai_realtime.py` - direct WebSocket, completed transcript only, current `send_context()` behavior.
- `jarvis/runtime/claude_gateway.py` - final-response HTTP call to Control Center.
- `jarvis/domain/v2.py` - conversations/jobs/protocol envelope/lifecycle.
- `jarvis/ports/v2.py` - provider-neutral ports.
- `jarvis/core/v2_services.py` - CoreEventBus, ConversationService, JobService.
- `jarvis/core/v2_app.py` - Core composition root.
- `jarvis/protocol/server.py` - loopback API and `/v1/events` WebSocket.
- `jarvis/protocol/client.py` - local API client/event consumer.
- `jarvis/v2_config.py` - Realtime model/voice/turn config.
- `tests/unit/test_v2_voice_toggle.py` - current one-response-to-background assertions.

If these files have materially changed, update the plan before coding. Do not force stale line-level assumptions.

## Task order

- [ ] Task 00 - Orchestrate the handoff
  - Path: `tasks/00-orchestrate-handoff/TASK.md`
  - Depends on: none
  - Status: not started
- [ ] Task 01 - Add typed brain and speech contracts
  - Path: `tasks/01-brain-speech-contracts/TASK.md`
  - Depends on: Task 00
  - Status: not started
- [ ] Task 02 - Add Core-owned BrainOrchestrator skeleton
  - Path: `tasks/02-core-brain-orchestrator/TASK.md`
  - Depends on: Task 01
  - Status: not started
- [ ] Task 03 - Add authoritative brain-turn protocol ingress
  - Path: `tasks/03-brain-turn-protocol/TASK.md`
  - Depends on: Task 02
  - Status: not started
- [ ] Task 04 - Extend Realtime event and output-control adapter
  - Path: `tasks/04-realtime-controls/TASK.md`
  - Depends on: Task 01
  - Status: not started
- [ ] Task 05 - Introduce continuous LIVE lifecycle
  - Path: `tasks/05-continuous-live/TASK.md`
  - Depends on: Task 04
  - Status: not started
- [ ] Task 06 - Enforce strict Realtime reflex policy
  - Path: `tasks/06-surface-reflex-policy/TASK.md`
  - Depends on: Task 04, Task 05
  - Status: not started
- [ ] Task 07 - Move Claude/strong brain ownership into Core
  - Path: `tasks/07-migrate-claude-brain/TASK.md`
  - Depends on: Task 02, Task 03, Task 05
  - Status: not started
- [ ] Task 08 - Add Voice SpeechScheduler for brain output
  - Path: `tasks/08-speech-scheduler/TASK.md`
  - Depends on: Task 03, Task 04, Task 07
  - Status: not started
- [ ] Task 09 - Implement barge-in and intent revision
  - Path: `tasks/09-barge-in-intent-revision/TASK.md`
  - Depends on: Task 05, Task 08
  - Status: not started
- [ ] Task 10 - Add structured work progress and public brain state
  - Path: `tasks/10-progress-working-state/TASK.md`
  - Depends on: Task 07, Task 08
  - Status: not started
- [ ] Task 11 - Add end-to-end async conversation scenarios
  - Path: `tasks/11-integration-scenarios/TASK.md`
  - Depends on: Tasks 05-10
  - Status: not started
- [ ] Task 12 - Add telemetry, rollout gates, and repository docs
  - Path: `tasks/12-rollout-docs/TASK.md`
  - Depends on: Task 11
  - Status: not started

## How to select the next task

Pick the lowest-numbered unchecked task whose dependencies are complete. If implementation discovery makes a task unsafe or too broad, Task 00 authorizes the orchestrator to split/reorder tasks and update this TODO, provided the locked decisions remain intact or an explicit decision change is documented.

## Global testing expectations

- Use fakes for Core/brain/provider unit tests.
- Never require real OpenAI or Claude for the default test suite.
- Preserve/strengthen Core provider-neutral architecture gates.
- Add concurrency tests for mute, interruption, stale speech, and brain completion after Voice disconnect.
- Run relevant existing voice tests whenever Voice/Reatime code changes.
- Do not declare hardware acoustic behavior solved without workstation testing.

## Reporting

At the end of every coding task, record:

- files changed;
- behavior changed;
- tests run and result;
- architectural decisions changed/added;
- remaining risks;
- exact next task.

Use `templates/final-implementation-report-template.md` after Task 12.
