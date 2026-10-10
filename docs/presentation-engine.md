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
- The authoring planner (`presentation_draft_assemble`) assembles **Remotion scenes** since Remotion Slice 15 and creates the Presentation with engine
  `remotion` (`build_presentation`, `create_assembled`). Until then it assembled HTML prefab scenes, which are Slidecar sources, and kept the legacy engine
  (labelling HTML scenes `remotion` would have been a lie the engine gate would have to refuse). It now **refuses** an HTML source or pin
  (`prefab_engine_mismatch`) and `create_assembled` refuses a document that names Slidecar: Slidecar is made only by the human experiment path.
  Decks the planner assembled as Slidecar before Slice 15 are legacy documents: read and edited in Slidecar as before, never converted.
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

1. **No agent tool carries an engine (or actor) argument.** `jarvis-presentation` and `jarvis-remotion` (Slice 21: install, Studio pointer, export, import, upgrades; it only READS the default engine) have none, and a parity test over every native server fails if one appears. Only a Human UI
   action can pass `requested` to the policy (Slice 20: [Human engine control](#human-engine-control-slice-20)). A Core create body of `title` alone names nothing and is `remotion`; an `engine` is accepted only with the Human actor the Control Center relay sets.
2. **No silent fallback, in any direction.** `resolve_engine(engine, availability)` returns the engine asked for or raises. It reads the state of that engine
   only. No function in the module maps one engine to another: an AST test scans every function of the module (`legacy_html_compatibility`, a fixed table, and `select`, the policy, are excluded by name), and a stricter one scans `resolve_engine` for any concrete engine.
3. A Remotion failure is a visible failure to fix, with the adapter's real reason and repair. Never a Slidecar result.
   This includes an **edit** (Slice 14): a Remotion scene source that does not build is refused with the typed code
   `presentation_studio_source_build_failed` (HTTP 422, `diagnostics` = `file:line:column`) before anything is published, and an
   unready engine refuses the edit with `presentation_studio_engine_unavailable`; the version on screen keeps playing and no
   Slidecar scene is ever substituted ([presentation-studio.md](presentation-studio.md) > *Hot reload contract* > *Remotion sources*).
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
| Human toggle, diagnostics, persisted-identity migration of old data | **wired** (Slice 20): see [Human engine control](#human-engine-control-slice-20) below. The Control Center card « Présentations · moteur » is the only door that names an engine; `EngineSelectionPolicy.select` is now called by the create path (`EngineChoice.decide`) with the actor the relay set; every Slidecar creation, copy and use is journaled; a Remotion failure is shown with its real reason and a one-click `install` / `repair`, never a Slidecar window; legacy documents were migrated by the v2 -> v3 step (first save keeps `presentation.json.v<N>.bak`). |

`compile_runtime_unavailable` (the compiler's own state) is said `engine_unavailable` at the Core boundary; a sandbox port that cannot be bound is also `engine_unavailable` with the bind error. The user sees the same typed state in the stage window (title, real reason, repair, retry): never a blank frame and never a Slidecar window.

## Human engine control (Slice 20)

Who can name an engine, where, and what is recorded. Code: `jarvis/domain/presentation_studio_engine_request.py` (the create body), `jarvis/core/presentation_studio_engine_choice.py`
(`EngineChoice`, `SlidecarLedger`), `PresentationStudioService.create / create_experiment / engine_overview`, relay `jarvis/runtime/presentation_studio_relay.py`, card
`jarvis/runtime/control_center_presentation_studio_engine.js`.

**The door.** `POST /api/presentation-studio/presentations` (Control Center) is the only way to name an engine. The relay keeps the page keys `{title, engine?, experimental_confirmed?, reason?}`
(anything else is `invalid_request`, nothing reaches Core), **replaces** any `actor` with `user`, and forwards to Core's `POST /v1/presentation-studio/presentations`. Core maps `actor: user` to
`EngineActor.HUMAN`; everything else (`brain`, `system`, an unknown value, **no actor at all**) is refused by `POLICY.select` as `presentation_studio_engine_selection_refused` (403) as soon as an
`engine` is named, even `remotion`. A body of `{title}` alone (an agent, a script) names nothing and is `remotion`. No agent tool has an engine or an actor argument (parity test), the
`jarvis-presentation` MCP server and the brain adapter never contain the confirmation flag or the experiment route (source scan), and the authoring planner creates through `create_assembled`, which takes no engine.

**Honest limit.** `actor` is a declaration, not an authentication, the same threat model as `display_mcp.py` and `docs/SECURITY.md`: the brain runs under the same account as Core and could read
`core.token` and forge `actor: user` on a raw HTTP call to Core. A second door, the Control Center relay, forces `actor: user` itself, so any local process that can reach the Control Center port could
name Slidecar through it. Two casual-access barriers narrow that, neither a boundary: the Slice 11 guard (loopback Host, loopback Origin, never `Sec-Fetch-Site: cross-site`) and, on the routes that
**name an engine** (create with `engine`, `/experiment`) and on `install|repair`, a required `Sec-Fetch-Site: same-origin` (a browser always sends it for the page's own fetch; curl, a python client
or an agent's shell do not, and get 403 `presentation_studio_engine_selection_refused` / `forbidden_origin`). A client that forges that header passes. The guarantee is for an honest caller: no tool,
no prompt and no relay path of the brain can carry an engine, and a forged body on any non-Human route (`PUT` presentation, variant, edits, source-edits, undo, redo) is refused as an unknown key. A real
boundary would need a credential the brain cannot read; that is out of this Slice.

**Slidecar is an explicit experiment.** Creating one needs `experimental_confirmed: true` on top of the Human actor (`400` otherwise, the message carries the warning). The page shows it only inside a
closed « Expérimental : Slidecar » area with the warning text always visible when opened, then a confirmation dialog (risk, no fallback, journaled). Cancelling sends nothing.

**Immutable, copy instead of convert.** There is no engine field in any update body. « Dupliquer en expérience Slidecar » is `POST .../presentations/{id}/experiment` `{actor, experimental_confirmed, reason?}`:
a NEW Slidecar document titled `<source> (Slidecar)` with no scene (a Remotion scene source is not `native` in Slidecar), the source document is neither read for writing nor changed (byte-identity test).

**Observability.** Each diagnostic is `core.presentation_studio.<kind>` with `{engine, actor, reason, ...}` (ids and codes, never content):

| Kind | Level | When |
| --- | --- | --- |
| `engine_chosen` | info | a Human named an engine (Remotion or Slidecar) |
| `engine_selection_refused` | warning | a non-Human named an engine, or an unknown actor; `{requested, actor, code}` (a typo such as `Slidecar` or a missing confirmation is NOT a policy refusal: `engine_request_invalid`, info) |
| `slidecar_created` | info | after the write: `{engine: slidecar, presentation_id, actor, reason}`, `actor: human` with the line the person typed (or a default). **Never `actor: agent` since Slice 15**: the carve-out of the Slice 20 rework (a draft the planner assembled from HTML scenes, reason `agent authoring (HTML scenes) until Slice 15`) is closed; an assembled draft is a Remotion document and its `core.presentation_studio.created` diagnostic carries `{engine: remotion, actor: agent}` |
| `slidecar_experiment_created` | info | the copy: adds `derived_from`, `source_engine`; the source is untouched |
| `slidecar_used` | info | a stored Slidecar document is played, edited or previewed (`StudioEngineGate` call sites, once per presentation and action per minute); `origin` and `reason` are truthful: `human` (created by the user in this Core run), `legacy` (anything else: an older document, an older agent-assembled deck, or an earlier run: Core cannot tell more, the document carries only its engine). `agent_authored` existed between the Slice 20 rework and Slice 15 and no longer does |

`GET /v1/presentation-studio/engine` (relayed read-only) returns `{default_engine, engines: {slidecar, remotion: {ready, reason, repair}}, experimental, slidecar: {events, total, kept, durable: false}}`:
the journal ring (100 entries, process memory) is for display; what survives a restart is the document's own `engine`, in every listing, shown as a badge.

**Fail closed, visibly.** The card turns the adapter's real reason into guidance: capability not installed (button **Installer Remotion**, ~270 MB, confirmation), install failed / repair needed / crashed
(failure code translated, detail shown, button **Réparer Remotion**), invalid sandbox settings or no adapter or disabled (steps to do yourself, no button: restarting Core is the user's act), always with
« Aucune présentation Slidecar n'est affichée à la place ». The two buttons call `POST /api/local-capabilities/remotion/install|repair`, relayed with an empty body (`remotion_studio_relay.py`); a compile error
of a scene stays in the stage window with the compiler's message ([remotion-isolation.md](remotion-isolation.md) section 10). While installing, the card shows a spinner and the elapsed time (15 min limit).

**Legacy documents.** A stored document without an engine reads as `slidecar` (v2 -> v3, unchanged); reads never rewrite it; the first save writes the new schema and keeps the exact old bytes once in
`presentation.json.v<N>.bak`; the variant files are not touched by a manifest save (`tests/unit/test_presentation_studio_engine_migration.py`, on the frozen v1 and v2 fixtures).

## Conformance

`tests/unit/test_presentation_studio_engine.py` (policy, no-fallback, legacy default, capability and compatibility triage, manifest identity, upgrade),
`tests/unit/test_presentation_studio_engine_tools.py` (agent surface carries no engine/actor argument, create route takes title only),
`tests/unit/test_presentation_studio_engine_docs.py` (this page vs the code). Slice 10: `tests/unit/test_remotion_player.py` (availability, gate, `adapter` refused in both directions, every stored scene re-checked), `tests/unit/test_remotion_gate_call_sites.py` (one default-suite test per gate call site with a refusing stub, plus a source scan that fails when a call is deleted), `tests/unit/test_remotion_app_wiring.py` (production composition), `tests/unit/test_remotion_player_realpage_browser.py` (real Chrome: engine unavailable, compile error, nothing plays as HTML). Slice 12: `tests/unit/test_remotion_timeline*.py` and `tests/unit/test_remotion_timeline_realpage_browser.py` (real Chrome: the score drives the Player). Slice 20: `tests/unit/test_presentation_studio_engine_human.py` (real Core and Control Center chain: only the Human actor names an engine, forged bodies, confirmation, immutability, experiment, diagnostics, repair door), `tests/unit/test_presentation_studio_engine_migration.py` (legacy v1/v2 documents, `.bak`, Slidecar use journal), `tests/unit/test_control_center_presentation_studio_engine_js.py` (card logic and served page), `tests/unit/test_control_center_presentation_studio_engine_browser.py` (real Chrome on an isolated Core: create, confirmation, copy, badges, reload, repair).
