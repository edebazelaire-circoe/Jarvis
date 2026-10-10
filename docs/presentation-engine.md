# Presentation engine - semantics, selection policy, failures (Level 2 contract, domain Level 3)

Status: **Level 2 contract** with a **Level 3 domain** (`jarvis/domain/presentation_studio_engine.py`, conformance
`tests/unit/test_presentation_studio_engine*.py`). Written by Remotion Slice 02 (handoff `jarvis-remotion-presentation-integration`).
Entry page: [presentation-studio.md](presentation-studio.md). The engine **adapters** (Remotion Player host: Slice 10, [remotion-isolation.md](remotion-isolation.md) section 10; Studio, export) and the Human toggle
are built by Slices 03 to 20 and must obey this page. Nothing in this page starts, installs or probes Remotion.

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
   only. No function in the module maps one engine to another: an AST test scans every function of the module (`legacy_html_compatibility`, a fixed table, and `select`, the policy, are excluded by name), and a stricter one scans `resolve_engine` for any concrete engine.
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
editability was requested. The prefab manifest field that stores the declaration, and the shop UI, are Slices 17 and 18; this page fixes the triage they use. A Remotion scene source (manifest `schema_version` 2, [remotion-source.md](remotion-source.md)) already carries `source.engine` (the Remotion and React versions and the lock digest it was written for).

## Runtime wiring status (what is and is not enforced yet)

| Seam | Status |
| --- | --- |
| Identity on the document, upgrade, summary | **wired** (Slice 02) |
| `new_presentation` default, create route (title only) | **wired** (Slice 02) |
| Policy, matrix, typed failures, triage, manifest identity | **domain + tests** (Slice 02) |
| Gate before play / edit / preview (`resolve_engine`) | **wired** (Slice 10): `StudioEngineGate` (`jarvis/core/presentation_studio_engine_gate.py`) reads the only availability source, `RemotionPlayerService.availability()` (compiler wired, local capability `ready`/`running`, sandbox listener configured), for the Presentation's OWN engine. `PresentationStudioService.require_engine` is called before **play** (`PresentationStudioPlaybackService._start`, before anything is compiled or staged), **edit** (`PresentationStudioEditService.edit`, `render_overlay`) and **preview** (`show_preview`). A `remotion` document without a ready adapter fails with `presentation_studio_engine_unavailable` (409) carrying the adapter's reason and repair; **nothing plays in its place** (no Slidecar stage, no HTML window: tested end to end, `test_without_the_runtime_nothing_plays_and_nothing_falls_back_to_html`). |
| Scene vs engine compatibility (`require_native`) | **wired** (Slice 10, reworked): a presentation USES only sources that are **`native`** for its engine. `adapter` is a declared state, not a usable one: no visible, explicit adapter step exists yet, and an "adapted" HTML bundle in a `remotion` document is an HTML window (an unsupported use is visible, not guessed: it is refused with `presentation_studio_engine_unsupported`, "declared, not usable"). Checked at **scene-add / modify** (`PresentationStudioService._check_scenes`, before value validation, scene-local variants included), at **play start for every stored scene and local variant** (`require_native_scenes`: a document stored before the check, or written by a path that skipped it, is refused at start), and on **every path that puts a block on the stage** (`require_native_pin`): the scene shown (`_sync_stage`, which also covers overlays, hot-reload follow-ups and scene-variant selection), a detour block (`detour` is refused 422 `detour_invalid` before the catalogue is asked, `_show_aux` re-checks), a scene-variant preview (`show_preview`); the hot reload goes through `check_scenes` before anything is written or patched. The triage `require_compatible` / `classify_compatibility` is unchanged (it still reports `adapter`: the library keeps showing `adaptateur`). |
| Remotion adapter in Core | **wired** (Slice 10): `RemotionCompiler` + `RemotionSandboxServer` (dedicated loopback origin, lazy) + `RemotionPlayerService` built by `JarvisCoreApplication` from the `RemotionFactory` (`jarvis/ports/remotion.py`) that `jarvis/app.py` injects (`jarvis/runtime/remotion_composition.py`); routes `GET /v1/remotion/sandbox`, `GET /v1/remotion/player/{id}/{version}`; the window host mounts the stage page and the sandboxed frame ([remotion-isolation.md](remotion-isolation.md) section 10). The gate **fails closed**: a Core built without the Remotion composition (testlab harness, scripts) still has the gate and reports "no Remotion adapter", so it refuses a `remotion` document and never plays HTML for it; skipping the gate is an explicit `engine_gate=False` (the historical HTML test worlds do it in `tests/conftest.py` by patching `ENGINE_GATE_DEFAULT`; tests of the gate carry `@pytest.mark.engine_gate`). A bad `JARVIS_REMOTION_SANDBOX_HOST/PORT` does not stop Core: the engine is composed without a sandbox and says why (`engine_unavailable`, typed and visible). |
| Score -> Remotion timeline | **wired** (Slice 12): an adapter only (`domain/remotion_timeline.py`): the score, the playback table and the sequence clock stay the masters; anchors (`ScoreAnchor.at_ms`) map to frames with the manifest composition, the playback view carries a `timeline`, the browser seeks / plays up to a stop frame / pauses the Player and the sandbox reports its position as untrusted advice ([presentation-studio.md](presentation-studio.md) › Remotion timeline bridge, [remotion-isolation.md](remotion-isolation.md) section 11). |
| Human toggle, diagnostics, persisted-identity migration of old data | Slice 20 |

`compile_runtime_unavailable` (the compiler's own state) is said `engine_unavailable` at the Core boundary; a sandbox port that cannot be bound is also `engine_unavailable` with the bind error. The user sees the same typed state in the stage window (title, real reason, repair, retry): never a blank frame and never a Slidecar window.

## Conformance

`tests/unit/test_presentation_studio_engine.py` (policy, no-fallback, legacy default, capability and compatibility triage, manifest identity, upgrade),
`tests/unit/test_presentation_studio_engine_tools.py` (agent surface carries no engine/actor argument, create route takes title only),
`tests/unit/test_presentation_studio_engine_docs.py` (this page vs the code). Slice 10: `tests/unit/test_remotion_player.py` (availability, gate, `adapter` refused in both directions, every stored scene re-checked), `tests/unit/test_remotion_gate_call_sites.py` (one default-suite test per gate call site with a refusing stub, plus a source scan that fails when a call is deleted), `tests/unit/test_remotion_app_wiring.py` (production composition), `tests/unit/test_remotion_player_realpage_browser.py` (real Chrome: engine unavailable, compile error, nothing plays as HTML). Slice 12: `tests/unit/test_remotion_timeline*.py` and `tests/unit/test_remotion_timeline_realpage_browser.py` (real Chrome: the score drives the Player).
