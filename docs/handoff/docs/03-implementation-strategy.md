# 03 - Implementation strategy

## Principle

Construire un vertical slice tres tot, puis remplacer les fakes un par un.

## Phase A - Skeleton and contracts

- freeze upstream snapshots ;
- create package structure ;
- define typed ports/results ;
- add fake backends ;
- prove state machine with unit tests.

Output: Jarvis can run a fake text turn without audio or UI.

## Phase B - Voice loop

- capture push-to-talk ;
- OpenAI transcription adapter ;
- initial agent backend ;
- TTS backend ;
- interruption semantics.

Output: usable voice conversation from terminal.

## Phase C - Safe actions and memory

- ActionBroker ;
- Markdown memory ;
- local index ;
- tools `memory_search`, `memory_append` and `board_present` only.

Output: Jarvis can remember and present information without general machine access.

## Phase D - Visual + gestures

- pin Barehands ;
- vendor remote assets ;
- add token auth ;
- bridge board commands ;
- integrate visualizer state bus.

Output: hands + face work without changing core logic.

## Phase E - Demo hardening

- launcher ;
- health checks ;
- e2e scenario ;
- failure cases ;
- security review ;
- final implementation report.

## Deliberate deferrals

Do not add open mic, vision, Gmail, calendar, browser automation, shell, wake word, mobile UI, or a vector database before the V1 scenario passes end-to-end.
