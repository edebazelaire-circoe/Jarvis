# 04 - Testing and quality

## Quality gates

No task is complete because the happy path runs once. Each adapter has a fake and contract tests.

## Unit tests

Required coverage areas:

- state transitions ;
- exact confirmation parsing ;
- deny-by-default behavior ;
- config validation ;
- path containment for memory/media ;
- log redaction ;
- provider error mapping ;
- cancellation during TTS ;
- action allowlist.

## Contract tests

Each adapter must satisfy the same port-level behaviors. Provider SDK objects must not leak into `core/`.

## Integration tests

1. fake audio -> transcription adapter mock -> agent fake -> TTS fake.
2. real OpenAI transcription with a fixture audio behind opt-in environment flag.
3. Barehands local server accepts an authenticated `present` and rejects missing/bad token.
4. state publisher produces states consumed by visualizer.
5. memory index rebuild from Markdown source.

## E2E smoke test

Scenario required before V1 is considered usable:

1. launch all components ;
2. hold PTT and ask `Quel est mon projet Jarvis ?` ;
3. hear a spoken response ;
4. ask `Affiche un resume sur le board` ;
5. see a card appear ;
6. manipulate the card with hand tracking ;
7. ask `Memorise que la demo V1 a fonctionne` ;
8. receive explicit confirmation request ;
9. approve ;
10. restart Jarvis ;
11. ask what was remembered ;
12. retrieve the persisted note.

## Failure scenarios

- OpenAI unavailable -> clear spoken/visible error, no crash loop.
- microphone absent -> preflight failure, not silent.
- Barehands down -> voice remains usable.
- visualizer down -> voice remains usable.
- malformed memory file -> skip/index diagnostic, not total failure.
- invalid action -> denied before execution.

## Diagnostics

Every operation should have a correlation/turn id. Logs contain timings and error classes, but not content by default.

Recommended timing metrics:

- audio_capture_ms
- transcription_ms
- agent_first_token_ms
- agent_total_ms
- tts_first_audio_ms
- turn_total_ms
