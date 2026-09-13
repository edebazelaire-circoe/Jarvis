# Reconstructed Grill Session — JARVIS Voice Architecture

> This is a reconstructed grill session based on the uploaded 11 September 2026 voice transcript and the subsequent design discussion in chat. The exact original voice transcript is preserved separately in `sources/transcript-2026-09-11.md`. Where the discussion did not lock a numeric value or exact class/file name, this document marks it as unresolved rather than inventing it.

## 1. Starting diagnosis

The transcript exposed two major classes of failure:

- **Voice / brain divergence.** Backend answers were sometimes ready but the voice layer improvised a different answer. In the sample, eight of eighteen backend answers were replaced by voice improvisation. Several of those improvisations incorrectly claimed there was no delimited text to read.
- **Conversation serialization / stale playback.** Responses could be ready quickly yet wait tens of seconds behind older speech, then play after the conversational context had changed. A long lookup performed directly by the brain also blocked subsequent conversational turns.

The trace additionally showed false local speech detections caused by a bus/noise, failed output cancellation, `speech_output_stalled`, and duplicated reflex acknowledgements.

## 2. User correction: the backend brain should not own speech directly

The design moved away from giving the heavy backend brain absolute control over the voice. The user proposed three roles:

- a **mouth/ear** that handles audio reception, transcription, and immediate voice generation;
- a **front brain** that owns conversational state, understands what the user said and what JARVIS actually said, decides whether/when to speak, and mediates between voice and backend;
- a **back brain** that owns reasoning-heavy tasks, tools, sub-agents, and durable work, and returns relevant data rather than directly deciding every spoken sentence.

A crucial decision was that the front/conversation layer must receive what the mouth **actually spoke**, not merely what another component asked it to speak. The user's heard conversation is the ground truth.

## 3. Reflex behavior must become selective, not automatic

The user explicitly rejected systematic canned acknowledgements such as “I understand”, “I’m checking”, or reflex replies to a simple “OK”. The desired behavior is a gate that can choose among:

- `WAIT` — say nothing;
- `BACKCHANNEL` — minimal conversational signal when genuinely useful;
- `SPEAK` — immediate substantive answer;
- `PREAMBLE` — one short natural sentence only when noticeable work is about to happen;
- `DELEGATE` — send work to the back brain while keeping the conversation path free.

The system should exploit the time while the user is still speaking. Partial transcript deltas can be analyzed speculatively, response plans can be revised as speech continues, and final speech can be ready near end-of-turn. Partial transcripts must never trigger irreversible actions by themselves.

## 4. Realtime Mini as a capable conversation frontend

The currently used `gpt-realtime-2.1-mini` should be tested as more than a constrained reflex surface. OpenAI Realtime exposes turn-management and prompting primitives relevant to the desired behavior, including Semantic VAD and a `wait_for_user` pattern.

## 5. Front Brain architecture

The second architecture adds a separate fast analysis model to the realtime conversational model. Initial candidate: GPT-5.6 Luna.

The fast model can consume transcript deltas and maintain compact hints such as current intent, whether the user is addressing JARVIS, likely need for backend delegation, urgency, and likely response mode. It should not become an additional independent source of truth or direct speech producer.

The front-brain analysis must run in parallel, not as an extra serial hop between audio and speech.

## 6. GPT-Live / Duplex architecture

GPT-Live 1 maps closely to the intended full-duplex design: it manages the spoken conversation and delegates reasoning/tool work to a backend. JARVIS should use **client delegation** so the existing backend can remain Claude/JARVIS/sub-agents rather than forcing the backend into one provider.

GPT-Live should be integrated through the same JARVIS frontend contract as Realtime, not as a separate application.

Relevant result classes:

- quiet/context update to Live — equivalent to `session.thinking.append`;
- result that should be spoken — equivalent to `session.commentary.append`;
- behavioral redirect/stop — equivalent to `session.instructions.append`.

## 7. Three switchable architectures in Settings

### Simple

One conversational voice model. Current/expected candidates include OpenAI Realtime 2.1 Mini, OpenAI Realtime 2.1, and existing Gemini voice capability in the project. Exact Gemini model identifiers are to be discovered from the code rather than guessed.

### Front Brain

Two conversational-layer models:

- **Reflex / realtime model** — handles audio and immediate conversation.
- **Front Brain / analysis model** — fast text/reasoning model that helps gate speech, infer intent, and prepare context.

Settings must expose both selectors and their relevant prompts/settings.

### Duplex

A full-duplex conversation model with backend delegation. Initial model: GPT-Live 1. Architecture must allow future duplex-capable providers through a capability registry rather than hard-coded UI assumptions.

## 8. Prompt visibility in Settings

The user wants to inspect and edit all JARVIS-controlled initial prompts from the same configuration surface:

- JARVIS/back-brain prompt;
- Simple/realtime conversation prompt;
- Reflex model prompt in Front Brain mode;
- Front Brain analysis prompt;
- GPT-Live/Duplex frontend prompt;
- provider/model-specific prompt additions.

The UI should show both the individual layers and the resolved/effective prompt, with provenance. Provider-internal hidden system prompts cannot be shown and must not be implied to be available.

## 9. GPT-Live cost and lifecycle safety

Because GPT-Live is billed by active session time, the user requires strong visibility and hard stop controls:

- conspicuous “GPT-Live active” indicator;
- continuously visible elapsed active time;
- manual Stop control always available while billable Live is active;
- auto-close policy after inactivity or when conversation is clearly over;
- server/runtime watchdog to close orphaned sessions;
- clean shutdown on app exit, mode switch, exception, or network loss;
- trace of every open/close/reconnect transition;
- benchmark/cost counters so an accidentally running background session is obvious.

Exact idle timeout is **unresolved** and must be configurable rather than silently hard-coded.

## 10. Benchmarking is a first-class product feature

The architecture selector doubles as an A/B/C benchmark tool. JARVIS should record per-session architecture/model configuration and metrics including latency, unnecessary reflex speech, stale speech, false barge-ins, backend blocking, delegation behavior, interruptions, and cost/usage.

The same replay/scenario suite should be runnable against Simple, Front Brain, and Duplex.

## 11. Final instruction

Create an implementation handoff that covers all of the above, with GPT-Live as a principal target, while continuing to improve the reflex/realtime path rather than abandoning it. The implementation should be sliced into small tasks so independent coding agents can execute it safely.
