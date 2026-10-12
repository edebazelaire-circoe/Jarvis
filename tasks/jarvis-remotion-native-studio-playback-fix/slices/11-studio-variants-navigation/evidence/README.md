# Slice 11 evidence — first-class Remotion Studio and Variants choices

Base `873e0cc0` (Slices 00–10). Commits: `a12c9672` (code and tests), `cbbfadc6` (docs), `6ac55b1c` (regression fixes: Remotion Studio
is read only once a Remotion scene is on screen; menu expectations of two rail browser tests; the Studio guard test admits the user door).
Contract: `docs/presentation-studio.md` › *Remotion Studio from Variants (Level 3, Slice 11)*. Every run used isolated Cores (free loopback
ports, throw-away data roots) and headless Chrome; the live Jarvis and the user's own Remotion Studio were never started, stopped or
contacted. No schema change, no Core route change.

## What changed, per SLICE step

1. **Navigation, active state, return path, browser permission.** « Remotion Studio » on Variants' scene row beside « Présenter »
   (§ 6 #22); `data-state="here"` and the name « Remotion Studio, ouvert sur cette scène » when Remotion Studio shows this pin; the rail
   menu « Remotion Studio… » (opens Variants, then the same door). The tab opens only while the confirmation click is a live user
   activation; after a long start the line offers the real link « Ouvrir l'onglet Remotion Studio ». The return path is Jarvis's tab:
   Variants is never closed or re-selected, and `focus` / `visibilitychange` re-read Remotion Studio.
2. **One identity.** The door opens the scene on screen at its exact pin; it reads the pin's library entry once (Remotion or not,
   provenance); another version of the same source, another scene, and files modified in Remotion Studio (« pas publiés ») are said,
   never corrected.
3. **Health, readiness, errors, confirmation, in Variants.** Start counter « Remotion Studio démarre… 12 s (2 min au plus). »; failures
   with the code's sentence, the code, « Réessayer » and Remotion Studio's log; refusals at the click (not Remotion, no Remotion Studio on
   this Core, environment not ready, a run); the card's confirmation (risk, exact version, provenance; reinforced for a version not
   written by the user) inside Variants' layer.
4. **Native Remotion Studio untouched.** Its own tab, nothing of it drawn in Variants (asserted: no iframe on its address), no timeline
   cloned.
5. **Tree, preview, provenance preserved; one authority.** Variant, scene and tree unchanged across the open (node and real Chrome);
   the video is paused after the confirmation only; edits never reach the variant (Slice 12).

PX-1: the MCP card and every sentence of `JarvisRemotionStudioCore` now say « Remotion Studio » (« Ouvrir Remotion Studio », « Fermer
Remotion Studio », « Ouvrir cette scène dans Remotion Studio », « Démarrage de Remotion Studio… »).

## Screenshots (SHA in each file name)

| File | What it shows |
| --- | --- |
| `before-873e0cc0-variants-{1280x720,800x600}.png` | the base: the 2-scene Remotion deck in Variants, the scene row « Scène 1 sur 2 », title, « Présenter » only |
| `after-a12c9672-variants-{1280x720,800x600}.png` | Slice 11: « Remotion Studio » beside « Présenter » on the scene row, nothing else moved |
| `after-a12c9672-confirm-1280x720.png` | the confirmation inside Variants (risk, « Scène 1 sur 2 « Remotion » · source v1 », provenance, « pas publié ») |
| `after-a12c9672-open-here-1280x720.png` | after the open: the button's dot, « Remotion Studio est ouvert sur cette scène (source v1), dans un autre onglet. », the link |
| `after-a12c9672-failed-1280x720.png` | a start that failed: the sentence, `remotion_studio_start_timeout`, « Réessayer », the log |
| `{before-873e0cc0,after-a12c9672}-scene-row-inventory.json` | the scene row's controls (name, box) at both sizes, overflow, the rail menu entry |

The before shots were made from a `git archive` of `873e0cc0` (outside the repository), the after ones from `a12c9672` with the same
script and deck; the confirm / open / failed ones by `test_variants_remotion_studio_browser.py::test_evidence_…`
(`JARVIS_VARIANTS_REMOTION_EVIDENCE_DIR`). The red veil in the preview is the isolated Core's honest « Remotion n'est pas disponible »
(no Remotion runtime wired there); the automated Remotion Studio is Core's fake process (`FakeStudioRunner`) serving a stand-in page.
Home path and user name are redacted at write time.

Measured (inventories): at 1280×720 the button sits at x 1058–1172 on the scene row (y 478–508, the row of « Présenter »), at 800×600
it fits too; no horizontal overflow at either size; the transport row is unchanged.

## Mutants (each reverted after its run)

| Mutant | Killed by |
| --- | --- |
| no confirmation (`ok=true`) | 7 node tests (cancel, Échap, pause-after-confirm, …) |
| the pin's version + 1 sent to Core | 3 node tests (exact pin) |
| the tab opened even without user activation | `test_a_long_start_offers_the_link…` |
| the door left visible during a run | `test_a_run_hides_the_door…` |
| unpublished files not said | 2 node tests |

## Tests (one file per process, fresh `JARVIS_DATA_ROOT` each)

| File | Result |
| --- | --- |
| `test_variants_remotion_studio_js.py` (new) | 14 passed |
| `test_variants_remotion_studio_browser.py` (new, real Chrome) | 7 passed, 1 skipped (evidence, opt-in; run once: passed) |
| `test_variants_remotion_studio_docs.py` (new) | 5 passed |
| `test_control_center_remotion_studio.py`, `test_remotion_mcp_tools.py` (updated) | 26, 40 passed |
| `test_remotion_studio_rework.py` (guard updated: the user door allowed, the page command channel has no Remotion action) | 42 passed |
| `test_control_center_presentation_rail_js.py`, `_browser.py`, `test_presentation_rail_e2e_browser.py` (menu entry) | 9, 13, 3 passed |
| `test_variants_controls_js.py` / `_browser.py` / `_docs.py` (readout audit knows the state line) | 5 / 7 + 1 skipped / 5 passed |
| `test_variants_transport_js.py` / `_browser.py` (gate runtime) | 29 / 5 passed |
| `test_variants_run_js.py` / `_browser.py` | 9 / 6 passed |
| `test_variants_media_js.py` / `_media_fullscreen_browser.py` (gate runtime) | 21 / 7 passed |
| `test_presentation_studio_explorer_{js,view_js,lifecycle_js,actions_js,rework_js,core_js,upgrades_js,compare_js,compare_core_js}.py` | 1, 15, 19, 23, 9, 14, 8, 12, 3 passed |
| `test_presentation_studio_explorer_browser.py` | 18 passed (it caught the 503 console noise fixed in `6ac55b1c`) |
| `test_presentation_studio_{presenter,inspector,explorer_compare,explorer_upgrades}_browser.py` | 2, 16, 3, 3 passed |
| `test_presentation_studio_inspector_behaviour_js.py`, `_presenter_js.py`, `_player_js.py`, `test_interaction_mode_hud_js.py`, `test_barehands_contracts_js.py`, `test_workspace_presentations_js.py`, `test_continuous_sequencing_js.py` | 34, 6, 9, 48, 26, 23, 21 passed |
| `test_fullscreen_browser.py`, `test_workspace_presentations_browser.py`, `test_control_center_presentation_studio_engine_browser.py`, `test_remotion_player_realpage_browser.py` | 8, 2, 4, 7 passed |
| `test_remotion_studio.py`, `_routes.py`, `_docs.py`, `test_remotion_mcp_{docs,ownership,server}.py` | 42, 19, 10, 4, 6, 18 passed |
| `test_presentation_studio_mcp_ops.py`, `_mcp.py`, `_mcp_policy.py`, `test_mcp_catalog.py`, `test_documented_routes.py` | 27, 23, 11, 92, 3 passed |
| privacy: `test_task_evidence_privacy.py`, `test_remotion_no_fallback_privacy.py` | 2, 25 passed |
| every `*_docs.py` of presentation / remotion / variants / routes (37 files) | all passed |

Not run: the release gate (`test_presentation_playback_release_gate_browser.py`): nothing in playback changed; the real `remotion studio`
process with this door (≈ 600 MB; the host had < 2 GB free with QA's Chrome running) — it is HV-RFX-11-01.

## Decisions (decided by agent 0's Work Agent, for review)

- **The door reuses the card's core** (`JarvisRemotionStudioCore`: client, confirmation, phrases) rather than a second client.
- **No rail mark for Remotion Studio**: Core's Studio state knows a pin, not a presentation; the rail keeps its existing active state
  (the row Variants shows), the button carries the Remotion Studio side. Rail geometry unchanged.
- **The video pauses** when the user confirms (one playback at a time); the frame is kept.
- **The tab opens by itself only while the click is fresh**; otherwise the link (a blocked `noopener` tab cannot be detected).
- **Installing Remotion stays the engine card's gesture**: Variants says where, it does not install.
- **The MCP card keeps its library-level scene picker**; its subtitle points to Variants for a scene of a presentation.
- **Remotion Studio is read only when a Remotion scene is on screen** (no 503 noise for HTML decks or Cores without it).

## Flags for QA and agent 0

- **MCP behaviour change (words only):** `remotion_studio` now answers `where` = Variants' button (or the rail entry) and a new `say`;
  tool names, schemas, descriptions and budgets unchanged; it still never calls `open`. An agent-trace check of the first real
  « ouvre la scène dans Remotion Studio » turn is advisable.
- `CaptureStack` / `Core` test fakes accept `core_options`; the CDP harness `_fullscreen_browser.mjs` gained `{targets}` (open tabs).
- The rail entry waits ≤ 15 s for Variants' preview, then says where to click.
- Human check HV-RFX-11-01: in the real browser, open a Remotion presentation in Variants, « Remotion Studio » → confirm → the native
  Remotion Studio tab on that scene; edit there, come back: Variants says « pas publiés », still on the same variant and scene; try
  « Plein écran » and « Fermer » around it. Requires the user to restart Jarvis to load the new page.
