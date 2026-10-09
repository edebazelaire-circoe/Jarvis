# Presentation engine - semantics, selection policy, failures (Level 2 contract, domain Level 3)

Status: **Level 2 contract** with a **Level 3 domain** (`jarvis/domain/presentation_studio_engine.py`, conformance
`tests/unit/test_presentation_studio_engine*.py`). Written by Remotion Slice 02 (handoff `jarvis-remotion-presentation-integration`).
Entry page: [presentation-studio.md](presentation-studio.md). The engine **adapters** (Remotion Player, Studio, export, host) and the Human toggle are
**not built here**: Slices 03 to 20 implement them and must obey this page. Nothing in this page starts, installs or probes Remotion.

## Vocabulary

| Term | Meaning |
| --- | --- |
| **Engine** | What plays, edits and exports a Presentation. Closed set: `slidecar`, `remotion`. |
| **Slidecar** | The existing HTML-prefab engine. Canonical spelling is `Slidecar` (never "Sidecar"). Experimental, kept readable and editable. |
| **Remotion** | The React/TSX engine. Forced default for every new presentation and every scene the agent makes. |
| **Actor** | Who is asking: `human` (Control Center), `agent` (brain, sub-agent, any tool call), `system` (Core itself). |
| **Support** | `native` (the engine does it), `adapter` (only through an explicit, visible adapter step), `unsupported` (reported, never guessed). |

Scene, Prefab, Cue, DA, Variant and Core ownership are **unchanged**: the engine is an attribute of a Presentation, not a second domain.

## Where the identity lives (decision)

On the **Presentation document** (`presentation.json`, manifest `schema_version` **3**): one `engine` string for the whole presentation.
Not on the prefab manifest (a closed key set at v1, shared across presentations), not on the scene or the variant (a presentation mixing engines would
make "no fallback" and "no forced conversion" contradict each other, and a variant branch would have to be re-engined). Consequences:

- A **stored document that names no engine is `slidecar`** (legacy). The v2 -> v3 upgrade step (`UPGRADES[presentation][2]`, the existing chain, no new
  store) writes `"engine": "slidecar"`; nothing else changes. It is **not** a fallback: nothing was ever asked of Remotion for it.
  It is edited in its own engine only; it is never converted.
- A **new** presentation (`new_presentation`, the `POST` create route) is `remotion`.
- The authoring planner (`presentation_draft_assemble`) still assembles **HTML prefab scenes**, which are Slidecar sources: it keeps the legacy engine until
  Slice 15 (Remotion one-shot authoring) produces Remotion scenes and flips it. Labelling HTML scenes `remotion` would be a lie the engine gate would then
  have to refuse.
- Engine is immutable after creation in this Slice (no field in an update body). A conversion, if ever wanted, is a new Slice with its own contract.

Frozen-source / export manifests carry `EngineIdentity.to_dict()`: `{engine, engine_version, capabilities}` (version `null` until the adapter pins one;
`capabilities` is derived from the matrix and a document that disagrees with it is refused).

## Capability matrix (design contract)

| Capability | Slidecar | Remotion |
| --- | --- | --- |
| `rendering` (live preview / playback) | native | native |
| `authoring` (props patch, source edit) | native | native |
| `motion` (frame-deterministic timeline) | adapter | native |
| `export` (MP4 / still / PDF from a frozen source) | unsupported | native |

This is what each engine is *designed* to do. Whether an engine is *ready* right now is a separate runtime fact (`EngineAvailability`), reported by its adapter.

## Selection policy (`EngineSelectionPolicy.select(requested, actor)`)

| `requested` | Actor | Result |
| --- | --- | --- |
| nothing | any | `remotion` |
| `remotion` or `slidecar` | `human` | that engine (Slidecar is the explicit experimental option) |
| anything | `agent` | **`presentation_studio_engine_selection_refused`** (an agent has no say, not even for the default) |
| anything | `system` | refused (Core reads stored engines, it does not choose one) |
| anything | unknown actor | refused (fail closed) |
| not an engine name | `human` | `presentation_studio_invalid` naming the allowed values |

Rules that bind later Slices:

1. **No agent tool carries an engine (or actor) argument.** `jarvis-presentation` has none today and a parity test fails if one appears. Only a Human UI
   action can pass `requested` to the policy (Slice 20 adds that toggle and its diagnostics). The Core create route takes `title` only.
2. **No silent fallback, in any direction.** `resolve_engine(engine, availability)` returns the engine asked for or raises. It reads the state of that engine
   only. No function in the module maps one engine to another, and a test scans for it.
3. A Remotion failure is a visible failure to fix, with the adapter's real reason and repair. Never a Slidecar result.
4. An opt-in Slidecar presentation is observable: the `engine` is in `Presentation.summary()` and so in every listing.

## Typed failures

All are `PresentationStudioError` (the existing vocabulary, `presentation_studio_checks.py`), so they reuse the HTTP mapping, the visible-error path and
the logs.

| Code | HTTP | When |
| --- | --- | --- |
| `presentation_studio_engine_unavailable` | 409 | the presentation's own engine is not ready or reports no state; message = engine, adapter reason, repair |
| `presentation_studio_engine_unsupported` | 409 | `require_capability` on an `unsupported` capability, or `require_compatible` on an `unsupported` source |
| `presentation_studio_engine_selection_refused` | 403 | the policy refused the caller |

## Compatibility triage (prefab / source vs engine)

`classify_compatibility(declared, engine)` -> `native` | `adapter` | `unsupported`, from what the source **declares** (`{engine: support}`).
Undeclared is `unsupported`, never guessed. A pre-Remotion HTML prefab declares nothing: callers pass `legacy_html_compatibility()`
(`slidecar: native`, `remotion: unsupported`) explicitly. `require_compatible` raises `engine_unsupported` instead of flattening to a screenshot when
editability was requested. The prefab manifest field that stores the declaration, and the shop UI, are Slices 17 and 18; this page fixes the triage they use.

## Runtime wiring status (what is and is not enforced yet)

| Seam | Status |
| --- | --- |
| Identity on the document, upgrade, summary | **wired** (Slice 02) |
| `new_presentation` default, create route (title only) | **wired** (Slice 02) |
| Policy, matrix, typed failures, triage, manifest identity | **domain + tests** (Slice 02) |
| Gate before play / edit / export (`resolve_engine`) | **not wired**: no Remotion adapter exists, so playback still runs the Slidecar stage. Slice 10 (Player host) wires it for `remotion` documents and **must** refuse an unavailable engine with `engine_unavailable`. Until then an empty `remotion` presentation is not playable with scenes: scene add is guarded in Slice 10, not here. |
| Human toggle, diagnostics, persisted-identity migration of old data | Slice 20 |

## Conformance

`tests/unit/test_presentation_studio_engine.py` (policy, no-fallback, legacy default, capability and compatibility triage, manifest identity, upgrade),
`tests/unit/test_presentation_studio_engine_tools.py` (agent surface carries no engine/actor argument, create route takes title only),
`tests/unit/test_presentation_studio_engine_docs.py` (this page vs the code).
