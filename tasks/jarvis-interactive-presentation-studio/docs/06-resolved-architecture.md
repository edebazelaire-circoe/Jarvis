# 06 - Resolved Architecture (Slice 00, binding)

Written by the Project Manager at Slice 00 from a blind audit of `origin/main` (9721b3ca),
done before reading this handoff's docs. Where this page and `02-architecture.md` disagree,
**this page wins**. It narrows `02`; it never changes locked user intent (D01-D22).
Names below are the repository's real names; Slice 01 confirms them, it does not rediscover them.

> **Slice 01 corrections (read before relying on R5, R6, R7, R8):** `07-integration-map.md` section 1 lists C1-C13.
> The ones that change what a later Slice may do: C1 (R5 identity of the enforcement points), C3 (R7: the Tool Brain cannot carry studio operations and
> `ui_intent_publish` is broken on main), C4 (R8: byte budget, not 19 tools), C5 (R6: the stager is artifact-only), C6 (R2: prefab library caps, proposed Slice 01a), C7 (R4: frame fullscreen policy).
> Exact names: `09-canonical-names.md`. Per-Slice reuse: `08-slice-capability-matrix.md`.

## 1. Stale premises of the handoff (repository reality)

| Handoff says | Repository says |
| --- | --- |
| `jarvis-scene-window-prefab-foundation` is an active dependency | Merged into `main` (`0e199a77`). Contracts: `docs/scene-model.md`, `docs/prefabs.md`. No external wait. |
| Tool Brain handoff is in legacy storage | `docs/tool-brain-contracts.md` is Level 3 and implemented (`jarvis/runtime/tool_brain_*`, `jarvis/domain/ui_intent.py`, `ui_intent_publish`). Mode `JARVIS_TOOL_BRAIN` defaults `off`; production still wires `DirectSceneDisplaySink`. |
| Desktop host may give "real borderless fullscreen" | There is no desktop host. The Control Center is a web page opened with `webbrowser.open` (`jarvis/app.py:1572`). No fullscreen code exists anywhere. |
| Per-scene source revisions, scene ownership | One global scene (`SceneRefKind.GLOBAL`), scene-level `revision`/`epoch`, no per-object revision. Prefab versions are immutable and pinned exactly. |
| "Artifact" vocabulary | `Artifact` already means capture evidence (`docs/artifacts.md`, `ArtifactKind`, `jart_` ids). Do not reuse it. |

## 2. Binding decisions

**R1 Terminology and module naming.** The new aggregate is a *Presentation* with *Variants*, *Scenes*, a *Score*.
Existing `presentation_*` modules and `docs/presentation-*.md` belong to the PRESENTATION *interaction mode*.
All new code uses the prefix `presentation_studio` (domain/core/runtime modules, tests, `docs/presentation-studio.md`).
Never reuse `ArtifactKind`/`ArtifactService`; a Presentation is not a capture artifact.

**R2 Scenes are prefab instances.** A presentation scene's rendering is a prefab (`manifest.json`, `template.html`,
`style.css`, `behavior.js`) shown by a scene `window` object carrying `ScenePayload.prefab = {id, version, props, data}`.
- Tier 1 edit (declared control) = `manifest.inputs.props/data` patch -> existing `host.update`, no remount.
- Tier 3 edit (source) = publish a new immutable prefab *revision* through `PrefabService.save`, then re-pin the
  exact version -> the existing remount rule (version change) is the scene-local hot reload. State preservation
  across that remount is the part Slice 06 must add; it may not weaken the iframe sandbox/CSP or the `jv:1` protocol.
- No second renderer, no second prefab catalog, no `srcdoc` path other than `control_center_prefab_host.js`.
- The studio's logical scenes are NOT global-scene objects. Only the currently displayed scene (plus auxiliary
  resources) is a scene `window` object. Slice 04 fixes the exact mapping.

**R3 Persistence.** Presentation state is not a capture artifact and must survive restart (continuous autosave, D14).
Slice 02 chooses between (a) a file store under `<data_root>/presentations/` using
`file_replace.replace_with_retry` atomic writes (prefab-library precedent, no schema bump) and (b) a new `_MIGRATIONS`
step in `sqlite_state.py` (v9) with `tests/schema/jarvis_state.v9.sql`. Whichever is chosen: nothing under the repo,
no committed base, CLAUDE.md migration rules apply, crash durability is proven with a real subprocess kill.
Runtime handles/DOM/playback state never enter persistence.

**R4 Fullscreen = browser Fullscreen API.** "Real borderless" here means `Element.requestFullscreen()` (and the
Window Management API `getScreenDetails()` for display selection where Chrome grants it). Hard constraints Slice 03
must design around: a user-activation gesture is required (a voice/agent request alone cannot enter fullscreen:
design an "armed request" the next user gesture or a one-click prompt satisfies), exit must restore prior layout/focus,
Escape is the browser's emergency exit. A CSS overlay must never be reported as fullscreen (`docs/prefabs.md` calls the
existing dialog a CSS overlay; that is the thing to avoid). Host limits are documented as failure modes, not hidden.
If real fullscreen is unavailable the result is an explicit `unsupported`/`needs_gesture` state.

**R5 Ambient cue authority (D09) is a new, structurally separate path.** The current rule is enforced in three places:
`decide_turn_authority` (`jarvis/domain/presentation_addressed_turn.py`), `BrainTurnInput.__post_init__`
(`jarvis/domain/v2.py`), `PresentationOutputPolicy` (`authorizes_actions` is a fixed `ClassVar False`).
None may be loosened. The cue matcher is a new consumer of `AmbientIngestionLane` observations that:
only compares against the finite armed-cue set, emits only a typed `score.cue_satisfied(cue_id)`, and never builds a
`BrainTurnInput`, tool call or UI intent from text. The bound action is resolved from canonical score state and must
be pre-authorized and reversible. `docs/presentation-addressed-turn.md` section 12 gets an explicit, narrow amendment
in the same Slice (13), and a structural test proves ambient text with no armed cue produces nothing.

**R6 D23 validated.** The repo already splits committed state (every scene command, persisted with a revision) from
ephemeral state (Tool Brain queue, working set, prefab `notify` ring, view prefs). A staged scene object, even hidden,
is durable (`docs/presentation-speculative-preparation.md` 130-140). Therefore: playback position, reveal progress,
detours and the auxiliary-resource stack live in the in-memory playback runtime; auxiliary resources shown to the
audience go through the stager and are *retired* (archived) when the detour ends; only an explicit edit intent
writes to the active Variant. No product decision is needed; Slice 12 pins it with tests.

**R7 Tool Brain seam.** Studio operations are semantic and go through the canonical display/agent surface. If
`JARVIS_TOOL_BRAIN` is `active`, the ownership arbiter's `ui_delegated` refusal must be honoured, and UI effects
use `ui_intent_publish`/`ToolBrainIntake`; otherwise `PresentationDisplaySink`/scene tools are used. No second
scheduler, no second action queue. Use the existing `ToolBrainActionQueue` triggers rather than new timers where a
cue/timing trigger fits.

**R8 Agent tool surface.** `jarvis-display` has a 19-tool ceiling for the main brain's context. Studio tools live in
a new MCP server registered in `jarvis/runtime/mcp_tool_meta.py` (`ServerMeta`/`ToolMeta`), snake_case
`presentation_<verb>`, strict schemas, catalog parity tests, constrained choices from current state
(`tool_brain_choices.py` precedent). Destructive branch deletion uses the existing confirmation boundaries
(`confirm=true` pattern / `DestructiveGuard` precedent); there is no undo for archive, so branch deletion needs the
confirmation and Slice 16 decides retention.

**R9 Events.** New conversation event types are registered in both `jarvis/domain/conversation_events.py` (`_SPECS`)
and the JS mirror `control_center_timeline.js`. Parity tests exist; run them.

**R10 Voice/GUI parity (D13).** One semantic operation layer in Core; Control Center routes call it as actor `user`,
MCP tools call it as actor `brain`. Authority tables follow `ALLOWED_SCENE_OPS`/`SceneActor` precedent.

## 3. Plan repairs applied (Slice 00)

1. Every cross-task "blocked until foundation lands" gate is cleared (merged). Slice 03/04/17/20 external-dependency
   notes are satisfied; their contracts are bound to sections R2/R4/R5 above.
2. Slice 01 keeps its place but is narrowed: it **confirms and completes** this page (names, file paths, interfaces,
   conventions) and produces `docs/presentation-studio.md` Level 2 skeleton; it does not re-audit what is recorded here.
3. Slices 03 (fullscreen) gets the R4 constraint; 12/13 get R5/R6; 21 gets R7/R8.
4. Terminology fixed by R1 across all Slices.
5. Task Types: vocabulary absent; waived (see READINESS.md).
6. Frontend Slices (03, 07, 18, and UI parts of 06/19) must load `/impeccable`; every coding Slice `/caveman` and
   `/coding-guideline`; sub-agent mirror of those skills is the orchestrator's responsibility in each prompt.
