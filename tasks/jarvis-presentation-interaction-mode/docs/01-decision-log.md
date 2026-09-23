# Decision Log

## D01 - Product mode is independent from voice architecture
Locked. Presentation is an interaction/use mode, not a Simple / Front Brain / Duplex architecture. Architectures should expose the same product capabilities where practical.

## D02 - Three user-facing mode labels
Locked UI labels: `SIMPLE`, `PRESENTATION`, `REUNION`. `SIMPLE` maps to current assistant behavior and is the default. `REUNION` is future/reserved in this V1 and must not silently alias to fabricated meeting behavior.

## D03 - Ambient speech is never an action command
Locked. Ambient statements can trigger understanding, research, or fact-check preparation but cannot authorize user-visible or persistent actions merely because they contain imperative language.

## D04 - One audio stream, independent lanes
Locked. Avoid a single synchronous queue. Continuous capture fans out to ambient processing and explicit-address detection. Ambient enrichment may lag; command latency must not.

## D05 - Wake word/key means priority explicit address
Locked. In Presentation mode Jarvis is already listening. Wake word or configured manual wake key marks the following turn as explicitly addressed and high priority.

## D06 - Fresh transcript tail plus enriched working set
Locked. The explicit turn receives both slower committed/enriched context and a fresh transcript tail, preventing stale deictic resolution.

## D07 - Speculative work stays agentic
Locked. Presentation mode can delegate background sub-agents for research, code inspection, fact-checking, document lookup, web/news lookup, data preparation, and display preparation.

## D08 - Speculative work is sacrificial
Locked. Explicit interaction has absolute priority. Speculative jobs may be deprioritized, paused, cancelled, or capacity-limited to protect the priority lane.

## D09 - Quiet-by-default manifestation
Locked. Visual commands should normally execute silently. The system must support a successful brain turn with zero speech request.

## D10 - Speech is for actual semantic value
Locked. Genuine questions may be answered vocally, with useful detail and caveats. The objective is avoiding speech that adds no value.

## D11 - Fact-check alerts are discreet in V1
Locked. A meaningful contradiction/mismatch creates a small audible cue and floating warning/attention indicator. Jarvis does not spontaneously explain aloud.

## D12 - Reuse existing UI/runtime primitives
Locked where compatible. Reuse Scene/display MCP for prepared visual artifacts and visibility staging. Reuse/extend the background-event notification system for attention signaling. Reuse wake backend abstraction but remove duplicate microphone ownership in Presentation.

## D13 - Session working set is ephemeral
Locked. Presentation cache is bounded and session-scoped. It is not canonical long-term memory and must not be appended automatically.

## D14 - Simple mode is a regression boundary
Locked. Existing ordinary assistant behavior and existing wake/manual semantics outside Presentation must remain intact.
