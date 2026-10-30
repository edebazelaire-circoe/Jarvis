# 00 - Overview

## Problem statement

Jarvis already has sophisticated voice, Bare Hands and scene semantics, but ordinary desktop interaction is not yet a first-class path. The missing layer is mostly product interaction and composition, not a new scene runtime.

The feature should make three actions immediate:

1. manipulate and organize selected objects with familiar mouse/keyboard conventions;
2. inspect one or several visual/document objects without destructively rearranging the Board;
3. inspect a running agent as a public task state rather than as an opaque star.

## Success state

A user can work for a full session with mouse and keyboard only, while retaining parity with the scene's existing semantic operations. A multi-selection can be organized in one action. Any viewable object can be opened in a calm, full-viewport viewer. A running agent can be inspected without asking Jarvis verbally what the agent is doing.

## Design principles

- Reuse canonical scene/work/mission/artifact truth.
- Prefer one semantic action over a sequence of per-object mutations.
- Preserve the Board while inspecting content.
- Make public progress visible; never expose or infer private reasoning.
- Keep viewer chrome sparse and high-level.
- Preserve keyboard accessibility and reduced-motion behavior.
- Avoid creating parallel ownership for fullscreen, work state, missions, prefabs or chat.

## Planning baseline

Repository evidence was checked on `main` at commit `c0858a8000e2ca23b57231edb8f46c643080ad07`. Slice 00 must re-audit before dispatch because several active tasks touch nearby Control Center surfaces.

