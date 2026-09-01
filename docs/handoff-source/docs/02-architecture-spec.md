# 02 - Architecture specification

## Topology

```text
                +----------------+
Mic / PTT ----> | AudioCapture   |
                +-------+--------+
                        |
                        v
                +------------------------+
                | TranscriptionBackend   |
                | OpenAI first           |
                +-----------+------------+
                            |
                            v
+-------------+      +---------------+       +----------------+
| Memory      | <--> |  JarvisCore   | <---- | GestureBridge  |
| Backend     |      | Session       |       | Barehands      |
+------+------+      +---+-------+---+       +----------------+
       |                 |       |
       |                 |       +----------> ActionBroker
       |                 |
       |                 +------------------> AgentBackend
       |
       +--> Markdown + local search index

JarvisCore ----> StatePublisher ----> runtime signal files ----> Visualizer
     |
     +---------> TTSBackend --------> Speakers
     |
     +---------> BoardClient -------> Barehands /cmd
```

## Package boundaries

Recommended skeleton:

```text
jarvis/
  app.py
  config.py
  domain/
    events.py
    messages.py
    actions.py
    results.py
  core/
    session.py
    orchestrator.py
  audio/
    capture.py
    ptt.py
  ports/
    transcription.py
    agent.py
    tts.py
    memory.py
    actions.py
    state.py
    board.py
  adapters/
    openai_transcription.py
    openai_agent.py
    local_tts.py         # provisional name
    markdown_memory.py
    file_state_bus.py
    barehands_board.py
  security/
    policy.py
    session_token.py
  diagnostics/
    logger.py
    health.py
  runtime/
    .gitkeep
third_party/
  barehands/             # pinned or submodule
  ai-visualizer/         # pinned or submodule
config/
  jarvis.example.toml
scripts/
  dev_start.*
tests/
  unit/
  integration/
  e2e/
```

## Core contracts

### TranscriptionBackend

```python
class TranscriptionBackend(Protocol):
    async def transcribe(self, audio: AudioClip) -> TranscriptionResult: ...
```

Result should contain at least `text`, `duration_ms`, `provider`, `model`, `diagnostics`.

### AgentBackend

```python
class AgentBackend(Protocol):
    async def respond(self, turn: UserTurn, tools: ToolRegistry) -> AgentResult: ...
```

The core must not depend on a provider-specific response object.

### TTSBackend

```python
class TTSBackend(Protocol):
    async def speak(self, text: str, *, interrupt: CancellationToken) -> SpeechResult: ...
```

### MemoryBackend

Operations V1:

- `search(query, limit)`
- `read(memory_id)`
- `append_note(title, body)`
- `rebuild_index()`

### ActionBroker

Every mutation is represented as an `ActionRequest` with typed fields:

- `action_id`
- `kind`
- `summary`
- `risk`
- `payload`
- `requires_confirmation`

The broker returns `Approved`, `Denied`, `Executed`, or `Failed` typed results.

### StatePublisher

Publishes state independent of UI. File bus V1 maps states to runtime artifacts.

## State machine

```text
idle
  -> listening
  -> transcribing
  -> thinking
  -> awaiting_confirmation (optional)
  -> thinking
  -> speaking
  -> idle

any state -> error -> idle/retry
speaking -> listening when user interrupts
```

## Runtime config

No secret in committed config.

Suggested variables:

- `OPENAI_API_KEY`
- `OPENAI_TRANSCRIPTION_MODEL`
- `OPENAI_AGENT_MODEL`
- `JARVIS_PTT_KEY`
- `JARVIS_MEMORY_DIR`
- `JARVIS_RUNTIME_DIR`
- `JARVIS_LOG_LEVEL`
- `JARVIS_LOG_CONTENT=false`

## Upstream seam

Do not make core imports from `barehands` or `ai-visualizer`. Integrate through local HTTP/file contracts only.
