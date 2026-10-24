# 00 — Overview

## Goal

Make the Jarvis Settings experience visibly match the approved futuristic dark/glass/neon design direction shown in the five supplied references, while retaining live product semantics and data.

## Scope

This task covers:

- shared Settings visual primitives and layout rules;
- Personalisation;
- Architecture & Agents / Sous-agents;
- Architecture & Agents / Architecture;
- Mémoire & connaissances / Mémoire;
- Mémoire & connaissances / Memory Center;
- responsive behavior, accessibility, state handling and screenshot regression for those views.

## Non-goals

- No new memory model.
- No new role registry.
- No new model/provider catalog.
- No fake hard-coded runtime values to match screenshots.
- No restoration of deprecated/forbidden navigation concepts purely because an older mockup contains them.
- No broad rewrite of unrelated Settings categories.

## Mental model

The reference images define **visual intent and information hierarchy**. The live repository and existing canonical Settings tasks define **behavior and data truth**. Implementation must satisfy both by mapping real state into the target visual composition.

## Success condition

A reviewer should be able to open each targeted Settings page, compare it side-by-side with its reference image, and recognize the same hierarchy, density, spacing, neon/glass treatment and interaction affordances without losing real Jarvis functionality.
