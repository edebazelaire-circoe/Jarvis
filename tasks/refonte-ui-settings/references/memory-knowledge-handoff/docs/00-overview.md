# Overview

## Goal

Turn the existing memory stack into an understandable **Mémoire & connaissances** Settings experience without rewriting the underlying memory system.

## Mental model

The product should present four distinct things clearly:

1. **Canonical memory** — durable Markdown notes; the truth.
2. **Recall machinery** — lexical, optional semantic and optional external retrieval legs; derived and replaceable.
3. **Knowledge sources** — Wiki, CodeGraph and Skills; not canonical memory.
4. **Agent access policy** — loadouts deciding which scopes and knowledge kinds each agent/role can see.

Memory Center is the owner-facing inspection workspace over those concepts.

## In scope

- redesign Memory settings;
- redesign knowledge-source and loadout settings;
- redesign Memory Center presentation;
- relocate low-level diagnostics to Advanced;
- preserve canonical APIs, validators and security semantics;
- preserve candidate review workflow;
- improve source availability truthfulness.

## Non-goals

- no new memory store;
- no replacement of FTS5/RRF/hybrid recall;
- no new embedding provider invented by UI;
- no automatic deletion or rewriting of canonical notes;
- no direct Brain write to canonical memory;
- no Tencent redesign beyond relocating its operator configuration;
- no personality/voice configuration here.
