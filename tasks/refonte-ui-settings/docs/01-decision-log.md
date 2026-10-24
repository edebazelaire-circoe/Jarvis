# 01 — Decision log

## 2026-10-24 — User correction

**Locked:** The Settings refactor must contain explicit UI Slices and the reference images themselves. High-level "redesign" language is insufficient.

## 2026-10-24 — Task identity

**Locked:** Create a new implementation handoff named `refonte-ui-settings` under the Jarvis project task queue.

## 2026-10-24 — Visual acceptance model

**Locked:** Each supplied reference receives its own focused frontend Slice and Human validation check. Screenshot evidence is required.

## 2026-10-24 — Reference vs runtime conflicts

**Locked:** Mockups are authoritative for visual direction, layout and hierarchy, but not for invented runtime data. Existing canonical contracts win for role counts, provider availability, settings ranges, architecture rules and persistence semantics.

## 2026-10-24 — Architecture tabs

**Locked:** Do not reintroduce a standalone `Brains` tab solely because one sub-agent mockup shows it. The current canonical Architecture & Agents decision remains: `Architecture` + `Sous-agents`, with brain configuration contextual to the graph.

## 2026-10-24 — Implementation style

**Locked:** Avoid one huge monolithic Settings rewrite. Establish shared primitives once, then refactor each page/view in a separate Slice and converge in final integration.
