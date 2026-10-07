# Overview

## Problem

During a real presentation, ordinary assistant behavior is wrong in two opposite ways: a passive assistant misses the context needed to help quickly, while an eager conversational assistant interrupts too often and treats room speech as commands.

Presentation mode needs a third behavior: Jarvis should continuously understand what is happening, prepare likely useful support in the background, and respond immediately when explicitly addressed, while otherwise remaining unobtrusive.

## Goal

Provide a production-ready Presentation interaction mode that:

- maintains low-latency awareness of the live presentation;
- separates ambient context from addressed commands/questions;
- maintains a bounded session-scoped presentation working set;
- prepares research/fact-check/visual resources without blocking the presenter;
- applies deterministic priority/preemption rules;
- emits the right manifestation policy: silence, speech, visual display or discreet attention;
- delegates concrete UI action choice/timing to Tool Brain;
- uses scene/prefab objects for visual output;
- emits traceable decisions into canonical observability.

## Mental model

Presentation mode is primarily a **policy + context layer** above existing capture/transcription and below the final speech/UI manifestation paths.

It should not become another monolithic Brain. The main Brain still answers explicit questions and owns general reasoning/non-UI tool use. Presentation-specific runtime state and policy determine what context to supply, what speculative work may run, and what output modality is appropriate.

## In scope

- mode activation/effective-state integration;
- ambient presentation-context consumption;
- addressed-vs-ambient authority boundary;
- fresh transcript tail;
- enriched presentation working set;
- speculative/background task orchestration and preemption;
- manifestation policy;
- contradiction/attention policy;
- Tool Brain semantic intent integration;
- scene/prefab visual-result integration;
- mode UI if not already complete;
- observability and deterministic replay tests.

## Non-goals

- implementing meeting/REUNION behavior;
- redesigning the voice architecture;
- implementing explicit audio/screen recording;
- redefining Board, Session or Context;
- implementing a second UI tool executor;
- implementing a presentation-only window/prefab system;
- turning ambient transcript into permanent long-term memory;
- automatic unsolicited spoken fact-check interruptions;
- per-user interruption preference learning in V1.
