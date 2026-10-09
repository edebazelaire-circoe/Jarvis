# 07 - Integration Map (Slice 01, evidence-backed)

Written by Slice 01 against `origin/main` 9721b3ca (branch `task/jarvis-interactive-presentation-studio`).
Every claim cites `path:line` or a symbol. `docs/06-resolved-architecture.md` stays binding **except where section 1
lists a correction**: those corrections win over 06, and the PM folds them in at the next amendment.
Companion pages: `08-slice-capability-matrix.md` (what each later Slice calls/extends), `09-canonical-names.md`
(exact names). Proposed prerequisite Slices: `slices/proposed/`. Tool Brain Issue: `Issues/ISSUE-01-restore-brain-service-ui-intent-channel.md`.

Legend: **[V]** verified by reading code; **[E]** verified by an experiment run in this Slice; **[U]** not verified
(spec/doc knowledge only, say so before relying on it).

## 1. Verification of docs/06 (corrections)

| # | 06 says | Reality | Impact |
| --- | --- | --- | --- |
| C1 | R5: the authority rule is enforced by `PresentationOutputPolicy` whose `authorizes_actions` is a fixed `ClassVar False` | `PresentationOutputPolicy` (`jarvis/domain/presentation_policy.py:64`) has a **bool field** `authorizes_action` (line 75), set `True` on five rows (lines 159-201); the invariant is in `__post_init__`: `authorizes_action and not requires_explicit_address` raises `presentation_policy_ambient_authority` (lines 129-131). The `ClassVar[bool] = False` pins are on `AmbientUtterance` (`jarvis/domain/ambient_observation.py:267`), `AmbientTrigger` (:305), `AmbientAnalysis` (:339), `AddressedWindow` (`jarvis/domain/presentation_addressed_turn.py:247`), `AddressedTurnContext` (:439), `PresentationOutputIntent` (`jarvis/domain/presentation_intent.py:190`), the attention carriers (`jarvis/domain/presentation_attention.py:328,369,473`) | The "three places" are real but are: `decide_turn_authority` (`presentation_addressed_turn.py:1016`), `BrainTurnInput.__post_init__` (`jarvis/domain/v2.py:680-681`), and the policy-matrix invariant (`presentation_policy.py:129`), **plus** the structural `ClassVar` pins on every ambient-side carrier and the closed `AmbientTriggerKind` enum (`ambient_observation.py:108`, no "execute" value; `test_aucun_declencheur_ambiant_n_autorise_une_action` iterates it). A cue matcher must not introduce a carrier of room text with `authorizes_actions=True`: its only output is a typed cue id |
| C2 | Section 1: `webbrowser.open` at `jarvis/app.py:1572` | `jarvis/app.py:1575` [V] | cosmetic |
| C3 | R7: UI effects use `ui_intent_publish` / `ToolBrainIntake`; "use the existing `ToolBrainActionQueue` triggers" | (a) `BrainOrchestrator.publish_ui_intent` **does not exist on main** (lost by commit `9721b3ca`, section 10): MCP tool `ui_intent_publish` and `POST /v1/ui-intents` fail today, and so does `list_ui_intents`, which `jarvis/runtime/tool_brain_wiring.py:180` needs as soon as `JARVIS_TOOL_BRAIN` is not `off`. (b) `ToolBrainIntake` (`jarvis/runtime/tool_brain_intake.py:52`) is **not wired anywhere in production** (no caller outside tests) and has no Core route (its own docstring calls that "S08's first task"). (c) The vocabulary is closed and tiny: `UiIntentKind` = reveal/attention/relevance/dismiss (`jarvis/domain/ui_intent.py:34`), `UiIntentRefKind` = object/board (:47); `DisplaySemantic` = reveal_prepared/show_attention only (`presentation_intent.py:93`). (d) `ToolBrainActionQueue` only accepts `(server, tool)` pairs that have an executor adapter (`default_adapters`, `jarvis/runtime/tool_brain_executor.py:227`, built on `scene_and_surface_adapters`, `jarvis/runtime/tool_brain_adapters.py:254`: scene_update_object/update_many/pin/archive/link/unlink + surface tools) | R7 must be **narrowed**: studio navigation/edit/playback operations are NOT semantic UI intents and cannot ride the Tool Brain. They are Core service operations behind a new MCP server. The Tool Brain seam is limited to (i) respecting ownership (section 10) and (ii) optionally `reveal`/`attention` of the displayed scene object. Slice 21 must not depend on `ui_intent_publish` for anything essential |
| C4 | R8: "`jarvis-display` has a 19-tool ceiling" | `jarvis-display` has **20** tools today (`ui_intent_publish` joined) [V: `mcp_tool_meta.DISPLAY.tools`]. The real ceiling is a **byte budget**: `DISPLAY_CONTEXT_BASELINE_BYTES = 40_000` (`tests/unit/test_mcp_catalog.py:350`) against 39 516 B measured (comment above it), i.e. **~484 B** of headroom. A new server needs its own `*_CONTEXT_BUDGET_BYTES` / `*_INSTRUCTIONS_BUDGET_BYTES` constants like `WORKSPACE_*` (test_mcp_catalog.py:223-225) | A new server is mandatory (06 was right) and must fit its own byte budget: consolidate into ~12-16 discriminated tools, not 40 |
| C5 | R6: "auxiliary resources shown to the audience go through the stager and are retired" | The stager port is artifact-only: `HiddenSceneStager.stage_hidden(category, title, summary)` (`jarvis/core/presentation_speculative.py:236`; `DisplaySceneStager.stage_hidden` `jarvis/runtime/presentation_staging.py:74`), no prefab argument. `reveal` is fixed (`update_object(visibility="visible")`, presentation_staging.py:98-103) | Slice 12 either extends the stager port with a prefab-capable `stage_hidden` or calls `SceneDisplayTools.create_object(kind="window", visibility="hidden", prefab=...)` itself. The crash-reclaim precedent to reuse is `StagedObjectLedger` / `LedgeredSceneStager` (`jarvis/runtime/presentation_runtime.py:206,355`): a scene object is durable, so a studio window left by a killed process must be reclaimable by an id list (never by a filter) |
| C6 | R2: Tier 3 = publish a new immutable prefab revision through `PrefabService.save`, then re-pin | Mechanically true (`jarvis/core/prefab_service.py:491`, `_publish` :616), but the library has **hard caps and no deletion**: `MAX_VERSIONS_PER_ID = 64` (`jarvis/domain/prefab.py:61`), `MAX_PREFAB_IDS = 512` (:60), version <= 9999, and no prune/GC anywhere (`jarvis/adapters/file_prefab_library.py`, `jarvis/ports/prefabs.py`). Tier-3 edits, per-variant source forks, scene-local variants and promotion exhaust the 64 versions of a scene id after 64 source edits | **True contract gap G1** -> proposed Slice `01a-prefab-capacity-for-studio` (section 11) |
| C7 | R4: fullscreen = browser Fullscreen API; "Escape is the browser's emergency exit" | Confirmed, with new evidence (section 5.3): the prefab frame has `sandbox="allow-scripts"` and **no `allow="fullscreen"`**, so inside the frame `document.fullscreenEnabled === false` ("Disallowed by permissions policy") [E, Chrome 154]; fullscreening a **host-side ancestor element** passes the policy and fails only on missing user activation [E]. `allow-fullscreen` is not a sandbox token (the control is the `allow`/`allowfullscreen` attribute) [E for behaviour, U for the spec wording] | Slice 03 fullscreens a host element that contains the frame, never requests it from inside the frame, and adds no `allow-*` sandbox token |
| C8 | R3: v9 in `sqlite_state.py` with `tests/schema/jarvis_state.v9.sql` | Confirmed: `_SCHEMA_VERSION = 8` (`jarvis/adapters/sqlite_state.py:31`), snapshots `tests/schema/jarvis_state.v3..v8.sql` + `scene.v1.sql`. `scene.sqlite3` is at v1 with an empty `_MIGRATIONS` (`jarvis/adapters/sqlite_scene.py:106,112`) | none |
| C9 | R9: events registered in `_SPECS` + JS mirror | Confirmed, plus two missing rules: `ATTRIBUTE_KEYS` is an **allowlist** (`jarvis/domain/conversation_events.py:276`): every new attribute key (e.g. `presentation_id`, `cue_id`) must be added; `ConversationActor` is closed (:74-83): use `SYSTEM` (precedent `system.mode.changed`, :234) | section 8 |
| C10 | R10: "Authority tables follow `ALLOWED_SCENE_OPS`/`SceneActor`" | `SceneActor` (`jarvis/domain/scene.py:240`) = runtime/brain/user and governs **scene** ops only. The relay forces actor `user` for every Control Center write (`jarvis/runtime/prefab_relay.py`, docs/prefabs.md "Control Center routes (relay)") and MCP stamps `brain`; the studio needs its own small actor enum in its domain | `09-canonical-names.md` |
| C11 | Section 1: "no fullscreen code exists anywhere" | Confirmed [V]: case-insensitive search for `requestFullscreen`, `fullscreen`, `getScreenDetails`, `Permissions-Policy`, `allowfullscreen` over `jarvis/` finds nothing | none |
| C12 | Section 1 / R6: "one global scene" | Confirmed (`SceneRefKind.GLOBAL`, `jarvis/domain/workspace_board.py:223-225`; `SceneSnapshot.scene_id/revision`, `jarvis/domain/scene.py:887`; `SceneService.epoch`, `jarvis/core/scene_service.py:214`). Capacity: `MAX_SCENE_OBJECTS = 512` shared with every star/window (`scene.py:97`); archived tombstones kept 4096 (`:103`) | one stable stage window per presentation (patched), not create+archive per slide (section 4.5) |
| C13 | R6/presentation docs: `docs/prefabs.md` says the stager's `reveal` is broken (Issue `presentation-stager-reveal-calls-missing-set-visibility`) | Stale: fixed by the presentation task (`presentation_staging.py:98-103`, `tests/unit/test_presentation_staging_contract.py`); `docs/presentation-mode.md` already says "done". `docs/prefabs.md` corrected in this Slice (three places: Legacy windows table, Consumers status, Consumers non-goals) | none after the fix |

Not contradicted (verified): R1 naming collision (`Artifact`/`jart_`, `jarvis/domain/artifacts.py:50,136`), R2 sandbox/CSP, R3 data-root rules,
R5 "ambient is structurally separate" (the lane exposes only `AmbientUtterance`/`AmbientTrigger`), R6 durability split
(`docs/presentation-speculative-preparation.md:130-146`), R8 "new server" (touchpoints in 7.2).

## 2. Process topology (governs where each Slice's code lives)

| Process | Owns | Evidence |
| --- | --- | --- |
| **Core** (`python -m jarvis core`) | scene service, prefab service/events, conversation events, brain orchestrator, SQLite stores, `<data_root>` | `jarvis/core/v2_app.py:271-286` (`self.prefabs`, `self.scene`, `self.prefab_events`); `docs/ARCHITECTURE.md` "Processes" |
| **Voice** (`python -m jarvis voice`) | mic, wake word, `SpeechScheduler`, **the whole PRESENTATION stack: ambient lane, working set, addressed-turn service, speech gate** | `docs/ARCHITECTURE.md` ("It lives in the Voice process"); `jarvis/runtime/presentation_runtime.py:1607` (`PresentationComposition`), :396 (`PresentationStack`) |
| **Control Center** (`python -m jarvis control-center`) | the web page, relays to Core, the Brain CLI whose MCP servers are its children | `jarvis/app.py:1575`, `jarvis/runtime/control_center.py` |

Consequences: (a) the cue matcher (Slice 13) must run in Voice next to `AmbientIngestionLane`, but the armed cue set and score live with the durable state in Core, so a
**Core->Voice delivery of the armed set** and a **Voice->Core `cue_satisfied` call** are new seams (the `SpeechScheduler` is the only `/v1/events` subscriber of the Voice process,
`jarvis/runtime/speech_scheduler.py:408`, so either a new event on that stream or a small Core route; Slice 12 decides, 13 implements). (b) Playback state belongs in Core (needs the
scene service, survives a Voice crash) as in-memory state of a Core service (R6). (c) Scripted Jarvis voice goes through Core's `BrainOrchestrator` because the scheduler consumes
`brain.speech.requested` (3.4).

## 3. PRESENTATION mode (ambient lane, explicit address, speech policy)

### 3.1 Mode vocabulary
`InteractionMode` = `assistant` (label SIMPLE) / `presentation` / `meeting` (`jarvis/domain/interaction_mode.py:52-62`, labels :83-87). Live truth in Core `InteractionModeService`
(`jarvis/core/interaction_mode.py:174`), event `interaction.mode.changed`; Voice copy `InteractionModeObserver`. The presentation stack exists only while the effective mode is PRESENTATION.

### 3.2 Ambient lane (Slice 13 seam)
- `AmbientIngestionLane` (`jarvis/runtime/ambient_lane.py:356`) has two callbacks: `on_utterance(AmbientUtterance, AmbientAnalysis)` (:376, **unused in production**) and `on_trigger(AmbientTrigger)`.
  Production wires only `on_trigger=speculative.submit_trigger` (`presentation_runtime.py:1755`). `_emit` (`ambient_lane.py:974`) isolates consumer failures.
- Each callback is one callable: a cue matcher uses `on_utterance` (free today) or a small fan-out. Text exists only inside the Voice process and never goes in a trace
  (`docs/presentation-ambient-lane.md`; `tests/unit/test_dropped_transcript_privacy.py`).
- `AmbientTriggerKind` is closed: checkable_claim / external_reference / open_question / new_topic (`ambient_observation.py:108-123`). A cue match is **not** a trigger kind and must not be added to it.
- Ambient transcription exists only on an OpenAI voice stack; elsewhere the lane is deaf (`docs/presentation-mode.md` "Known limitations"). User-presenter cue following is therefore
  **environment-gated**; Human checks must record the stack used.
- Working set / transcript tail: `PresentationWorkingSetStore` (`jarvis/core/presentation_working_set.py:180`), in memory only, never memory or recording (`docs/presentation-working-set.md` "This is not memory").
  Rehearsal speech (Slice 15) must not become durable content through it.

### 3.3 Explicit address (preemption signal for Slice 13)
`PresentationAddressedTurnService` (`jarvis/core/presentation_addressed_turn.py:384`): `arm(trigger)` (:491), `window_live()` (:457), `consume_window` (:1156), `open` (:688).
`decide_turn_authority(window_live, vocative)` (`presentation_addressed_turn.py:1016`) returns `TurnAuthority` EXPLICIT_ADDRESS / VOCATIVE_ADDRESS / AMBIENT (:973); only the first two `admits_turn`.
`PresentationWakeRouter` (`presentation_runtime.py:709`) arms the service from `ExplicitAddressLane.triggers()`. The cue consumer asks `window_live()` and `is_vocative_address(text)`
(`presentation_addressed_turn.py:1003`) **before** matching and stands down immediately; it never arms or consumes a window.

### 3.4 Speech policy (Slice 14 constraint, true gap G3)
- Gate: `PresentationSpeechGate` (`jarvis/runtime/presentation_speech_gate.py:116`), enforced in `SpeechScheduler._enqueue` (`speech_scheduler.py:2405`, call at :2421; results at :2721),
  built at :438. Outside PRESENTATION everything passes (`mode_not_presentation`, `presentation_speech_gate.py:222`).
- In PRESENTATION: `admit_presentation_speech(situation, kind)` (`jarvis/domain/presentation_response.py:190`): `situation=None` (speech attached to no addressed turn) admits only
  `UNADDRESSED_SAFETY_KINDS = (SpeechKind.ERROR,)` (`presentation_policy.py:228`); a classified turn admits per `PRESENTATION_POLICY` (:146). Row invariants: `voice_allowed => requires_explicit_address`
  (code `presentation_policy_spontaneous_speech`, `presentation_policy.py:~121-124`). `LOCKED_DECISIONS` is closed to D01..D14 of the **2026-09 handoff** (`presentation_policy.py:41`): a new row cites
  one of them or the set is extended after a decision-log entry.
- Therefore **a score-scripted Jarvis line (Slice 14) is withheld in PRESENTATION mode today**: no addressed turn and not an ERROR. Verbatim speech already has a Core path:
  `BrainOrchestrator.announce_notice(text, kind=SpeechKind, supersedes_key=, ttl_s=, ...)` (`jarvis/core/brain_service.py:889`; the text is "jamais reformulé", used for fixed Control Center phrases),
  which becomes `brain.speech.requested` consumed by the scheduler. Two options, recorded before Slice 14 codes: (A) run the Jarvis-presenter role only in ASSISTANT mode (no policy change, ambient lane
  off during that run), or (B) amend the matrix with a situation whose authority is the **user's explicit "present"/"continue" request** (explicit-address-derived grant, bounded lifetime), plus a
  `LOCKED_DECISIONS` extension. -> proposed Slice `01c-presenter-speech-authority`.
- `SpeechKind` = ack/progress/question/result/error (`jarvis/domain/v2.py:326`). Floor/interruption facts are `mouth.speech.*`/`mouth.floor.*`; `jarvis/runtime/tool_brain_speech.py` is a read-only
  projection (chunk plan, `played_ms`) reusable for locked-sequence sync (Slice 14) without a second TTS stack.

### 3.5 Display sink and hidden staging
`PresentationDisplaySink` (`jarvis/core/presentation_display.py:67`: `publish`, `withdraw_speculative`), production adapter `DirectSceneDisplaySink` (`jarvis/runtime/presentation_display_sink.py:37`) handles only
REVEAL_PREPARED/SHOW_ATTENTION. Studio playback does **not** use this sink: it is the speculative-resource reveal path of the addressed turn. The studio may consume it only to reveal a prepared resource during a detour.

## 4. Scene and prefab

### 4.1 Instance block
`ScenePrefabRef(prefab_id, version, props, data)` (`jarvis/domain/scene.py:583`) inside `ScenePayload.prefab` (:627); valid only on kind `window` (`PREFAB_KIND_MESSAGE` :728, check :786). Exact pin, never "latest"
(`docs/prefabs.md` "Instance block"). Bounds: compact payload <= `MAX_PAYLOAD_BYTES = 16_384` (`scene.py:93`), i.e. **title + props + data of one scene <= 16 KiB**; JSON depth 8, key 64 (`scene.py:534-535`).
Validation hook: `SceneService._check_prefabs` (`jarvis/core/scene_service.py:387`) -> `PrefabService.validate_instance` (`prefab_service.py:472`). Id grammar: `PREFAB_ID` = 2-4 dot segments, each
`[a-z][a-z0-9_-]{0,31}`, total <= 96 (`jarvis/domain/_checks.py:37`); `jarvis.` is the reserved base namespace (`prefab.py:48`).

### 4.2 Definition publication
`PrefabService.save(candidate, actor in {brain,user}, derived_from=)` (`prefab_service.py:491`; `SAVE_ACTORS` :79): new id -> `custom`/`fork`; existing id -> `revision` of `known[-1]`
(version = max occupied + 1, `_publish` :616). `edit_base` (:536) is brain-only behind explicit confirmation + witness and is **never** used for studio scenes (custom ids). `ProvenanceOrigin` =
base/custom/fork/revision/base_edit (`prefab.py:137`). Limits: template/style 32 KiB each, behavior 64 KiB, manifest 32 KiB (`prefab.py:89-92`), 64 versions/id, 512 ids, no GC.
Storage: `<data_root>/prefabs/<id>/<version>/{manifest.json,template.html,style.css,behavior.js,publication.json}`, staged in `.staging-*` then `os.rename` (`file_prefab_library.py:15-30,267`).
Routes: Core `/v1/prefabs*` (`jarvis/protocol/prefab_routes.py`), CC relay `/api/prefabs*` forcing actor `user` (`jarvis/runtime/prefab_relay.py`, `CorePrefabTransport` :87), brain tools `prefab_*` in
`jarvis-display` (`jarvis/runtime/display_prefabs.py`). The custom family is `family: window`; base catalogue (`jarvis.window/document/table/checklist/browser`) has no slide-shaped family.

### 4.3 Remount rules and hot reload (Slice 06)
Frame host (`jarvis/runtime/control_center_prefab_host.js`): one iframe per object id; props/data/theme change = `host.update` (JSON-diffed, `update` :416), **remount only on a `(prefab id, version)`
change**, container change, shape change or removal (`mount` :385; docs/prefabs.md "Lifecycle"). `LIVE_CAP = 24` frames (:74), LRU, beyond that a paused placeholder. Bundles cached per `id@version`.
`host.reload(objectId)` (:473) is "Recharger". `jv:1` has **no state-export message**: frame->host = ready/event/resize/open_url/error (`jarvis/runtime/control_center_prefab_protocol.js:49`),
host->frame = init/update/teardown/event_result (:48). State preservation across a version remount can only use what the studio already owns (`props`/`data`, committed through `state` events) or a host-side
snapshot; extending `jv` is a protocol change that must keep sandbox/CSP (R2). `teardown` gives the frame <= 50 ms.

### 4.4 Event bridge
Frame -> host -> CC relay (actor forced `user`) -> `PrefabEventService` (`jarvis/core/prefab_events.py:216`). `state` events write declared top-level `data` keys with a `basis` compare-and-set under the scene lock via
`SceneService.apply_if(plan)` (`scene_service.py:346`); `notify` events are logged and surface at the next brain turn (`BrainContext.prefab_events`), never wake the brain. Limits: host 10 events/s/frame,
Core bucket 30/s, state payload <= 16 KiB, notify <= 8 KiB. **Rule for the Semantic Edit API (Slice 05):** every studio write to `prefab.data` runs read-modify-write inside `apply_if`, otherwise it races a frame
`state` event and loses the user's click. `scene_update_object(prefab={props,data})` *replaces* given props/data (docs/prefabs.md "Consumers").

### 4.5 Stage-window model (recommendation for Slices 04/12)
Show each logical scene by patching **one stable stage window object** per presentation (`update_object(prefab={id, version, props, data})`, which triggers the remount rule) rather than create+archive per slide:
archive leaves history rows and tombstones (`scene.py:103,1343`), the object cap is shared (512), and a window left by a crash is durable (`StagedObjectLedger` precedent). Frame keys are **not** relayed
(docs/prefabs.md "Library UI": "the frame protocol relays no keys"), so keyboard slide navigation is bound on the host element, not the frame.

## 5. Browser host

### 5.1 What the host is
The Control Center is one HTML page assembled by splicing script files at markers (`jarvis/runtime/control_center.py:560-600` markers, splice :2060-2108), opened by `webbrowser.open(url)` (`app.py:1575`), served over
`http://127.0.0.1:<ui_port>/` with only a `frame-src` CSP header (`frame_src_policy`, `control_center.py:325`, header :2119) and no Permissions-Policy header [V]. Full-screen "views" (`PFB`, `WSP`, Test Lab, MCP
inspector) are **CSS dialogs** making the rest of the page `inert` (docs/prefabs.md "Library UI" Shell): exactly what R4 forbids reporting as fullscreen. New pages use the script-marker pattern
(`*_SCRIPT_FILE`/`*_SCRIPT_MARKER`, e.g. `PREFABS_SCRIPT_FILE` `control_center_prefabs.js`) and a dock button + full-screen dialog (`openPrefabs`, control_center.html:1542).

### 5.2 Brain/voice -> page command channel (precedent for Slices 03/21)
Bare Hands already implements brain -> MCP -> CC -> **page** commands with receipt, expiry and refusal codes: `GET/POST /api/barehands/commands` (`control_center.py:1249-1251`, `barehands_commands_poll` :4098),
closed vocabulary (`jarvis/domain/barehands_command.py` + `control_center_barehands_commands.js`), long-poll, reports "what the page observes, never what was asked", route inside `READ_GUARDED_ROUTES`
(`control_center.py:268`); contract `docs/barehands-contracts.md` (command channel, ~lines 2930-3080). The fullscreen "armed request" (R4) is a **sibling** of that channel (same long-poll + receipt + expiry design),
not a new transport and not an extension of the Bare Hands vocabulary.

### 5.3 Fullscreen feasibility [E: Chrome 154.0.8037.98, `--headless=new`, scratch page in the Slice scratchpad]
A page with three `sandbox="allow-scripts"` srcdoc frames and one host container, each calling `requestFullscreen()` with no user gesture:

| Target | `document.fullscreenEnabled` | `requestFullscreen()` |
| --- | --- | --- |
| frame exactly like prefab frames (`sandbox="allow-scripts"`, no `allow`) | **false** | `TypeError: Disallowed by permissions policy` |
| same frame + `allow="fullscreen"` | true | `TypeError: Permissions check failed` (no user activation) |
| same frame + `allowfullscreen` | true | `TypeError: Permissions check failed` (no user activation) |
| host container element (ancestor of the frames) | true | `TypeError: Permissions check failed` (no user activation) |

Conclusions: (1) a prefab frame cannot fullscreen itself today (permissions policy) and `sandbox` has no fullscreen token, so the answer is never to touch `sandbox`; (2) the target is a **host element** containing the
frame(s); (3) every path needs **transient user activation**: a voice/agent request alone cannot enter fullscreen, so the design is an "armed request": record it (5.2), show a visible one-click prompt with deadline and
cancel (RULE ZERO of the `coding-guideline` skill), and call `requestFullscreen()` inside the click handler; the page reports `entered | needs_gesture | unsupported | refused` from what it observes (`fullscreenchange`,
`document.fullscreenElement`), never from what was asked; (4) headless cannot prove a *granted* request: entry, exit/focus restore and Esc need a real-browser Human check. **[U]** `window.getScreenDetails()` /
`requestFullscreen({screen})` (Window Management API) needs a `window-management` permission prompt, is Chromium-only, secure context (`http://127.0.0.1` is potentially trustworthy); not exercised (no multi-monitor, headless).
Slice 03 treats display selection as best-effort (`display_selection: unavailable|denied|granted`) and otherwise fullscreens on the current display. Esc exits fullscreen with no app code; the app learns from `fullscreenchange`.

### 5.4 Sandbox facts a presenter prefab lives with
Frame `sandbox="allow-scripts"` only, opaque origin (`control_center_prefab_protocol.js:44`, applied before srcdoc, `control_center_prefab_host.js:288`), CSP
`default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'` (:45): **no network, no external images/fonts/media, no eval**.
Visuals must be CSS/SVG/inline data (gap G2 for rich DA/cinematics, section 11). D22 (no video generation) makes this tolerable, so G2 is a conditional proposal, not blocking.

## 6. Persistence conventions

| Convention | Evidence | Use for Slices 02/08/16 |
| --- | --- | --- |
| Data root outside the repo, one per repo copy | `jarvis/data_root.py:52-66`, `docs/local-data.md`; layout `state/jarvis.sqlite3`, `state/scene.sqlite3`, `history/`, `memory/`, `sessions/...`, `artifacts/<id>/`, `prefabs/<id>/<v>/`, `CONTEXT_GLOBAL/` | new tree `<data_root>/presentations/` |
| File stores: temp file + `fsync` + `replace_with_retry` | `jarvis/adapters/file_prefab_library.py:83-93` (`_write_file`), `jarvis/adapters/file_replace.py:54` (8 attempts, backoff), staged dir + `os.rename` for immutable publication (:15-30) | autosave of the active variant = temp + fsync + `replace_with_retry` |
| Folder defenses (no links/junctions, Windows path limit) | `jarvis/adapters/safe_folders.py:76,86,117` (`check_file_path`, `ensure_folder_tree`, `check_existing_tree`) | mandatory for any new tree |
| Versioned schema inside a file store | `MANIFEST_SCHEMA = "jarvis.prefab"`, `SCHEMA_VERSION = 1` (`prefab.py:43,46`) | `{"schema": "jarvis.presentation_studio.<kind>", "schema_version": 1}` in every file + a forward migration function per version (no `_MIGRATIONS` for files) |
| SQLite versioned migrations | `sqlite_state.py:31,41` (v8 now), `tests/schema/jarvis_state.v8.sql`, repo `CLAUDE.md` | only if (b) is chosen: v9 + snapshot + `tests/unit/test_schema_migrations.py` |
| Never delete data without a copy | repo `CLAUDE.md` "Donnees locales"; R8 "no undo for archive" | variant "deletion" = move to `presentations/<id>/archive/`, never `rmtree` |
| Evidence/Artifacts are another thing | `jarvis/domain/artifacts.py` (`jart_`), `artifacts/<id>/` | do not reuse (R1) |

**Recommendation (Slice 02 decides, evidence only):** (a) file store. Reasons: no schema bump; atomic replace and staged publication are precedent; per-variant isolation (D15/D16) maps to one file per variant; Core is the
single writer. Risk to prove: no multi-file transaction, so order writes (variant file first, manifest last) and reconcile on scan; a real subprocess-kill test is mandatory (R3). Runtime handles, DOM and playback state never
enter files.

## 7. Agent tool registration

### 7.1 Metadata model
`ToolMeta(label, side_effect, idempotent, atomicity, output_format, parameter_rules, output_notes, deprecation, ui_surface, reversibility, preconditions, choice_providers)` and
`ServerMeta(server, module, category, condition, registration, tools)` (`jarvis/runtime/mcp_tool_meta.py:99-125`). Registry tuple `SERVERS` (:540); order of `tools` = registration order in `build_server`
(parity test). `registration` in {jarvis, operator, managed, tool_brain} (:37). Choice providers are ids in `CHOICE_PROVIDERS` (:65), implemented in `jarvis/runtime/tool_brain_choices.py` (a test pins one
implementation per id); preconditions in `UI_PRECONDITIONS` (:73). `ui_surface=None` keeps a tool out of the Tool Brain manifest (precedent `ui_intent_publish`).

### 7.2 Touchpoints of a new server (precedent: `jarvis-workspace` / `jarvis-capture`) [V]
1. `jarvis/runtime/<name>_mcp.py`: `SERVER_NAME`, `TOOL_NAMES = tool_names(SERVER_NAME)`, `build_server(target=None, *, tools=None)`, `serve_stdio()` (`capture_mcp.py:43,493,637`).
2. `mcp_tool_meta.py`: a `ServerMeta` and an entry in `SERVERS`; a category in `CATEGORY_LABELS` if new.
3. `mcp_catalog.py`: `AGENT_SNAPSHOT_FLAGS` (:46-60) and the `build_introspection_server` branch (:82-90).
4. `jarvis/app.py`: `_xxx_mcp()` + CLI dispatch (`workspace-mcp` at :199, :1749) and a `ConsoleMcpTarget` passed to `ControlCenter(...)` (:1556-1559).
5. `jarvis/runtime/control_center.py`: ctor parameter + `agent.<x>_mcp = ...` (:975, :1445-1447); relay class + `*_GUARDED_PREFIXES` in `READ_GUARDED_ROUTES` (:268).
6. `jarvis/runtime/claude_local.py`: `_xxx_mcp_args()` (:1223), the tools-gateway server list (:975-979), the brain prompt constant (`BRAIN_WORKSPACE_PROMPT` :217) and its `prompt_catalog.py` descriptor (:173).
7. Core: service in `jarvis/core/`, wired in `v2_app.py` (:271-286 pattern), routes in `jarvis/protocol/<x>_routes.py` registered in `protocol/server.py` (:40,:241), typed method in `protocol/client.py`.
8. Docs/tests: `docs/mcp/tool-contract.md` section per server; `tests/unit/test_mcp_catalog.py` (server tuple :108, byte budgets :223-226), `tests/unit/test_<x>_mcp.py`.
**Limit [V]:** these servers are declared to the **Claude local brain** only (`AGENT_SNAPSHOT_FLAGS` comments "Claude seulement"); other brain backends do not get them. Slice 21 must record which voice/brain stack its live check ran on.

### 7.3 Destructive / confirmation precedents
`confirm=true` strictly typed boolean on `scene_update_many` (`display_mcp.py:985,1003,2730`); `confirmed_by_user` + quoted `user_request` + witness lookup for base edits (`prefab_service.py:536-600`,
`jarvis/core/prefab_witness.py`); Tool Brain `DestructiveGuard` (`jarvis/runtime/tool_brain_guardrails.py:131`) for irreversible UI actions. Branch deletion (Slices 16/21) = `confirm=true` plus archive-not-delete (section 6).

## 8. Conversation events (Python + JS)
Add the enum value in `ConversationEventType` (`conversation_events.py:100`), a `_SPECS` row via `_spec(actor, shape, visibility, required, content)` (:166; `content="forbidden"` for anything that could carry
user/room text), allowlist attributes in `ATTRIBUTE_KEYS` (:276; forbidden segments such as `prompt`, `token`, `args` are refused anywhere, :289), mirror in `jarvis/runtime/control_center_timeline.js` (`SPECS` :25,
`DOT_TYPES` :248, label map :276); `tests/unit/test_control_center_timeline_js.py:85` (`test_the_event_table_mirrors_the_python_contract`) and `tests/unit/test_conversation_events.py` fail on drift; catalog
table in `docs/conversation-events.md`. Presentation precedents: `system.mode.changed`, `system.attention.raised/cleared` (actor SYSTEM, INSTANT, DIAGNOSTIC, content forbidden). Timeline adapter:
`jarvis/runtime/presentation_timeline.py` (`PresentationTimeline`). Core emits through `core.conversation_event_emitter`.

## 9. Resource-reference conventions
- **Presentation-side reference (reuse for Slices 02/09):** `ResourceReference(kind, locator, title, descriptor)` + `ResourceKind` document/web_page/chart_descriptor/scene_object/dataset/note
  (`jarvis/domain/presentation_working_set.py:247,653`), `ALLOWED_LOCATOR_SCHEMES` allowlist (:195; http/https/file/doc/chart/scene/dataset/note; a bare path or id has no scheme), `<` refused, `MAX_REFERENCE_CHARS = 300` (:132),
  `safe_reference_text` (:330); contract `docs/presentation-working-set.md` "Prepared resources are references, never payloads". References, never payloads, never executable.
- Scene items: `ScenePayloadItem.ref` <= 256 and `url` http(s) only (`scene.py:506`, `MAX_ITEM_REF_CHARS` :90).
- Tool Brain refs: `{kind: object|board, id}`, `_REF_ID` = `[A-Za-z0-9][A-Za-z0-9_.:-]*`, <= 128 (`jarvis/domain/ui_intent.py:28-31`).
- Prefab refs: exact `(id, version)` (`PrefabRef` `prefab.py:237`, `PrefabInstanceRef` :260).
- Artifacts: `jart_` ids and `payload_ref = artifacts/<artifact_id>/<name>` relative to the data root (`docs/artifacts.md`); memory files by POSIX path relative to `memory/` <= 240 (`mcp_tool_meta.py:378`); Drive by connector id (`jarvis-drive`).
- Rule for the studio: store **typed references** (`ResourceReference`, `PrefabRef`, `jart_` ids), never copied payloads; an unavailable locator is a visible `resource_unavailable`, never silently dropped.

## 10. Tool Brain seam and the broken channel

State: `JARVIS_TOOL_BRAIN` is `off` by default and any value other than `shadow`/`active` is `off` (`jarvis/runtime/tool_brain_wiring.py:62-68`); production presentation display is `DirectSceneDisplaySink`
(`presentation_runtime.py:1763`). Ownership: when `active` and healthy, Jarvis's delegated scene tools are refused `ui_delegated` (`DelegationGate`, `jarvis/runtime/tool_brain_ownership.py:372`; `jarvis_delegated_tools` :350 =
tools with `ui_surface`, non-read, with an executor adapter; refusal raised at `display_mcp.py:2025-2030`). Studio implication: studio tools have no `ui_surface`, so they keep working when the Tool Brain owns the screen, but two
actors could then write the scene. Decision to record in Slice 12/21: studio-owned window objects are written only by the studio service and are marked (category/annotation) so the Tool Brain `scene_*` adapters and
`DestructiveGuard` ignore or refuse them (verify with the arbiter test pattern `tests/unit/test_tool_brain_ownership.py`). Low urgency while the mode is `off`.

### Root cause of the missing `publish_ui_intent` (evidence)
- Introduced by `33b3fea9` (2026-10-07 11:35, edebazelaire-circoe) "S4: canal d'intention d'interface de Jarvis": adds `BrainOrchestrator.publish_ui_intent`/`list_ui_intents`, the imports `UiIntentRefused, UiIntentRegistry`,
  `UiIntentDraft`, and `self.ui_intents = UiIntentRegistry(...)` to `jarvis/core/brain_service.py` (+46 lines).
- Present in main's history through `5ee43450` (2026-10-07 16:46, merge of `task/jarvis-tool-brain-ui-orchestrator`), `73144880` and `d53c0bd4` [verified: `git show <sha>:jarvis/core/brain_service.py` contains `def publish_ui_intent`].
- **Removed by `9721b3ca`** (2026-10-07 16:54, author `edebaze <e.debaze@gmail.com>`, message "no message", single parent `d53c0bd4`: a plain linear commit, not a merge). Its diff on `brain_service.py` deletes exactly the S4
  insertion points: both imports, the registry line in `__init__`, and the whole `publish_ui_intent` + `list_ui_intents` block, replacing it with the agenda-reminder `last_user_turn_at` / `wake_for_agenda` code. No other S4/Tool Brain
  file is touched by that commit (13 files, all agenda reminders). Hunks that coincide with the S4 insertion points and nowhere else are the signature of a **file copied from a base that predates S4 / the Tool Brain merge**
  (stale-copy overwrite or lost merge side), not of a deliberate removal. Inference, not proven: the author machine's pre-merge copy.
- Not lost everywhere: the method still exists on `feat/mik-s02..s10a`, `task/jarvis-memory-intelligence-knowledge` and `task/jarvis-tool-brain-ui-orchestrator` (forked before `9721b3ca`). **Merging them into main will not restore it**
  (main's side deleted it after their merge base). Restore explicitly.
- Blast radius [V]: `POST/GET /v1/ui-intents` (`jarvis/protocol/server.py:185-186,647-676`) -> `AttributeError`/500; MCP `ui_intent_publish` -> `display_internal_error`; `tool_brain_wiring.py:180`
  (`core.brain.list_ui_intents`) -> broken intent source and `DestructiveGuard` when `JARVIS_TOOL_BRAIN=shadow|active`; `tests/unit/test_tool_brain_intents.py`: 3 failed / 32 passed (re-run in this Slice, 9 s).
  With the default `off` the live product is unaffected, except when the model calls `ui_intent_publish`, which is still declared to it.
- Blocks Slice 21? Only if Slice 21 routes something through `ui_intent_publish`/the Tool Brain, which C3 says it must not depend on. It must still be repaired **before Slice 21 closes** (21 owns agent-trace evidence over the display tool surface and
  its QA runs the catalog). Proposed: Issue `Issues/ISSUE-01-restore-brain-service-ui-intent-channel.md`, a 46-line restoration (`git show 33b3fea9 -- jarvis/core/brain_service.py` is the exact patch), executed by the PM as a
  standalone repair on a `fix/` branch independent of the studio Slices. Not fixed here (docs-only Slice).

## 11. True contract gaps -> proposed prerequisite Slices (drafts in `slices/proposed/`)

| Gap | Evidence | Proposal | Blocks |
| --- | --- | --- | --- |
| **G1** prefab library capacity: 64 versions/id, 512 ids, no GC, versus Tier-3 edits, variants, scene-local variants, promotion | 4.2, C6 | `proposed/01a-prefab-capacity-for-studio` | 06 (hard), 08, 16, 17, 20 |
| **G2** frame assets: CSP `img-src data:` only, payload <= 16 KiB, template/style <= 32 KiB, no network/media | 5.4 | `proposed/01b-frame-asset-delivery` (conditional: only if rich media is wanted; otherwise Slice 09 documents CSS/SVG-only DA) | 09, 14 (quality only) |
| **G3** Jarvis-presenter speech withheld in PRESENTATION mode | 3.4 | `proposed/01c-presenter-speech-authority` | 14, 15 |
| **G4** `publish_ui_intent` missing on main | 10 | Issue text, standalone repair | 21 (before close) |
| Decision, not a gap: Core<->Voice bridge for armed cues | 2 | decided inside 12 (state), implemented in 13 | 13 |

## 12. What could not be verified
- A *granted* fullscreen entry, exit focus restore and Esc behavior (headless Chrome cannot grant); multi-monitor `getScreenDetails()`.
- Behavior of a `prefab.data` replace racing an in-flight frame `state` event beyond the documented `apply_if` guarantee (read from docs/tests, not exercised).
- The "ambient transcription only on an OpenAI voice stack" claim (taken from `docs/presentation-mode.md`).
- Growth of the archived-object history in `scene.sqlite3` (tombstones are capped at 4096; history rows not measured).
- The author-machine explanation for `9721b3ca` (inferred from the diff only).
- No `docs/CONTEXT.md` nor `documentation-level-registry.yaml` exists in this repo (the `coding-guideline` skill mentions both): documentation level is declared per page (`Status: Level N`), so `docs/presentation-studio.md`
  carries the level table itself.
