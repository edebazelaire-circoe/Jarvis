# 01 — Decision Log

## D01 — Prefabs before presentation-specific integration

**Status:** Locked.

Build the reusable window/prefab substrate as a separate task. Presentation mode consumes it later.

**Rationale:** The prefab contract is lower-level and reusable outside presentations. Presentation behavior already has independent semantics and active task material.

## D02 — Shared library, not board-local library

**Status:** Locked.

Prefab definitions live in one shared library available across boards/sessions. Board-specific state belongs to instances or board content, not the prefab catalog.

## D03 — HTML means HTML + CSS + JavaScript

**Status:** Locked.

A prefab can own structure, appearance, and behavior. It is not a static HTML snippet.

## D04 — Variables/inputs are first-class

**Status:** Locked.

Common customization must use declared inputs rather than source edits. Color is the canonical example.

## D05 — Structured data is required

**Status:** Locked.

Inputs must support structured JSON/list payloads in addition to primitives. Checklist population is the canonical example.

## D06 — Reuse first, create second

**Status:** Locked.

Jarvis should search for an exact/close prefab before generating a new one. It may fork/modify a close prefab or create from scratch if needed.

## D07 — Save as new prefab

**Status:** Locked.

An ad-hoc or modified object can be promoted into the shared prefab library for later reuse.

## D08 — Base prefab mutation requires explicit user intent

**Status:** Locked.

Normal customization modifies an instance or creates a variant/fork. Changing a base/system prefab requires an explicit user request naming that intent.

## D09 — Scene owns lifecycle and placement

**Status:** Locked from Rework FENETRES direction.

The Brain or responsible task agent decides what should be visible through the scene contract. The scene/runtime owns mount, placement, visibility, cleanup, and ownership semantics.

## D10 — Prefab behavior cannot directly own Jarvis authority

**Status:** Locked architectural recommendation.

Prefab JavaScript may manage local UI behavior and emit controlled events. It must not become an unrestricted path to filesystem/tools/runtime authority.

## D11 — Window families are the first major prefab family, not the entire abstraction

**Status:** Locked.

Existing window types should become reusable prefab bases, but the same system should be able to host other reusable scene objects such as indicators/lights and later data-driven objects.

## D12 — Do not redefine Session / Board / Context

**Status:** Locked user correction.

Those concepts already exist and are outside this task.

## D13 — Preserve existing Presentation interaction semantics

**Status:** Locked compatibility constraint.

The existing Presentation task concerns interaction behavior. This task exposes the visual/object substrate it can later consume; it does not replace or redesign that task.
