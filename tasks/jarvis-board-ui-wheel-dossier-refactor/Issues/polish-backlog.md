# Polish backlog (for Slice 08)

Non-blocking findings, kept here so Slice 08 (integration, accessibility, regression) picks them up. Each is
outside the acceptance of the Slice that found it.

## From Slice 01a QA (fixed Board type, schema v9)

- **No log line says the database was migrated.** The v9 step (like every SQL-string step) leaves no
  diagnostic; only the `.v8.bak` and the version row tell. Suggestion: one `core.state.migrated` info line
  per applied step, with `from`, `to` and, for a data step, the number of rows changed.
- **The brain brief writes the internal value.** `jarvis/runtime/board_brief.py` renders `Type : presentation.`
  / `Type : meeting.`; it should use the user words « Présentation » / « Réunion ».
- **`requested_kind` is logged with extra quotes.** `core.board.kind_change_refused` carries
  `preview(value)`, which quotes a string (`"'presentation'"`); log the bounded raw value instead.
- **`runtime/trace.jsonl` holds interleaved non-JSON lines** (seen during the 01a sandbox run): find the writer
  that bypasses the journal and make every line one JSON object.
- **The `.v8.bak` stays in WAL mode and a plain read creates `-wal` / `-shm` next to it.** The pre-migration
  copy should be switched to `journal_mode=DELETE` (or opened read-only by the procedures that inspect it) so
  that reading a backup never adds files beside it.

## From Slice 01b QA and sandbox run (derived interaction mode)

- **No end-to-end test that a `switch_noop` stops a Studio run.** `test_board_switch.py:314-329` covers the
  mode service only. Add to `test_presentation_studio_playback_service.py`: run on an Assistant Board, switch
  to the active Board, assert stop `mode_changed_by_user` and assistant mode.
- **`docs/presentation-studio.md` §6 (~l. 1819)** does not say a switch to the already-active Board also stops
  the run (only the failure table l. 1826 and `interaction-mode.md` do).
- **The brain is not told the mode was re-applied on `switch_noop`.** `workspace_boards.py:333-335` answers
  `unchanged` (« Déjà sur … ») although a Studio run may have stopped; relay `mode` / `mode_source`.
- **Stale comments** in `jarvis/runtime/control_center.html:1944-1946` (« sélecteur à trois choix ») and
  `:2245-2246` (409 reserved / 503 saved-not-applied cases that no longer exist); docstring
  `jarvis/domain/presentation_studio_roles.py:189` (« Board preference was reapplied »).
- **`settings_get` / `settings_describe` answer « Réglage inconnu » for `interaction_mode`** while
  `settings_set` gives the guiding `interaction_mode_derived` refusal; return the same code and sentence.
- **Core refusal trace logs a missing field as `"NoneType"`** (`_mode_value`); log `null` / `absent`.
- **Versioned `jarvis_local_v1.egg-info/SOURCES.txt:317`** still lists the deleted `interaction_mode_settings.py`
  (pre-existing generated file).
- **Agent behaviour, cross-cutting (Issue candidate, not 01b):** when a Board session is resumed after a switch
  announced in a previous turn was executed and then left, the brief's « Déjà dit » still carries « La bascule
  se fera à la fin de ce message » and the model claimed a switch was « déjà programmé » (sandbox evidence
  `s01b/evidence/trace-turn-b2.txt`). The Board-session context should mark an announced switch as done/left,
  or the brain should verify `board_get_active` before stating a switch state.

## From Slice 05 QA (Dossier contract and projection) — targets Slices 07/08

1. **Title of a Ranger note** shows the file name with its digest suffix (`pistes-de-financement-2352da72`) instead of the `#` heading of the note (Slice 07 view, or a title read from the heading).
2. **After `no_visible_page`** the agent promised « je la rouvre dès que l'interface est visible »: harden the `ERROR_SENTENCES["no_visible_page"]` sentence (nothing reopens by itself; say so, no promise).
3. **The agent read a note with `Read` on an absolute path** instead of `board_memory_read` (prompt/tool guidance, Slice 08 agent trace).
4. **An explicit drop on the Board** is listed as « ajouté automatiquement (Board actif à sa création) »: the drop links with `origin=active_board`; tell a drop apart (upload `provenance`) in the Dossier provenance.
5. **`present` echoes `entry_id` in the received case**, not canonicalized to the file name on disk (`Summary.md` vs `summary.md`).
6. **`memory/stat` gives no `sha256`**: an editor must `memory/read` the whole file to get the `expected_sha256` of a safe replace.
7. **Navigation doc** « 200 `{state…}` » reads as if every answer were a 200; say first that `no_visible_page` / `command_expired` are 504 refusals (`docs/dossier.md` › *Agent -> UI navigation*).
8. **`dry_run` / `backing` does not check the active Board**: it answers `rangeable` where Ranger then refuses 409 `dossier_board_not_active`; say the Board rule in the preview.
9. **Ranger of an Artifact window presented from Board A while B is active** links the Artifact to B without the user seeing it; consider refusing or saying the cross-Board link.
10. **`boards_of_artifact(limit=500)`** in `_resolve_entry`: an Artifact linked to more than 500 Boards would read as not in this Dossier; use a direct link lookup.
11. **Duplicate comment on the `DOSSIER_PAGE_TOKEN_MARKER` line of `control_center.py`** — fixed in the S05 rework commit (explorer comment restored on its own line).
12. **Brain, outside the Slice:** the 8 s turn budget was exceeded, and a stray text block « Single small file read is allowed. » appeared in the answer.

- **Resolved in Slice 07**: items 1 (a Ranger note is titled by its `#` heading, else the slug without the
  digest), 2 (`no_visible_page` sentence: « rien ne l'ouvrira de soi-même », no promise), 4 (an upload's
  `metadata.provenance` gives « déposé sur le Board » / « joint dans la conversation »), 5 (`present` and
  `dossier_view` use the entry id as stored on disk) and 7 (`docs/dossier.md`: only a page receipt is a 200).
  Item 3 is narrowed, not closed: `BRAIN_WORKSPACE_PROMPT` now says « une note se lit par board_memory_read »,
  yet in the S07 sandbox the brain still read a note once with `Read` and once with `Bash cat` on the absolute
  path before calling `dossier_view` (Slice 08 agent trace). Item 6 is handled in the UI (the editor reads the
  whole file to get `sha256`), the route still gives none.

## From Slice 02 QA (Board card, shell cleanup)

1. **Target Slice 03 — the open wheel (rank 37) sits under the open Board panel (rank 39)**: with both open, the
   wedges the panel covers cannot be reached. The wheel redesign decides which wins (close the panel when the wheel
   opens, or the reverse) and the registry follows.
2. **One Escape closes both the wheel and the Board panel** when both are open; it should close the topmost only.
   - Items 1 and 2: **resolved in Slice 03** — the wheel and the Board panel are exclusive surfaces (opening one
     closes the other, anchor hover does not reveal while the panel is open), so one Escape closes the only open one
     (`docs/control-center-shell.md` › *Exclusive surfaces*). Item 3 stays open (not a wheel concern).
3. **Long Board titles are cut at 1440 and 1920 px** (card capped at 236 px) while the same title fits at 600 px
   (`max-width: calc(100vw - 102px)` there); consider a wider cap on large screens, within the status-centre insets.

## From Slice 03 QA (orbital wheel) — targets Slices 04/08

1. Clicking the inert « … — pas encore branché » row closes the wheel (`item_inert` then close). Pre-existing
   behaviour for any disabled row; goes away as Slices 04/06/07 wire the trees.
2. Keyboard entry into a tree can focus the row under a motionless pointer (ArrowRight on Capture focused Audio at
   1280 and 600) instead of the first row — hover→focus pattern, likely pre-existing.
3. No browser test covers « two open recordings → stop list on primary click » through the new row menu (proved at
   runtime only). Add one in Slice 04 when Capture is rewired.
4. Stop row truncated (« Arrêter — écran princip… ») within the 256 px row width.
5. JARVIS / Capture / Paramètres panels overflow above/below their sector and cover part of the outer ring (x≈94).
6. `control_center_boards.js` logs `panel_yield` with a bare `console.info` instead of the module journal.
7. In the QA harness, Enter on the anchor opened the wheel but left focus on the anchor (ArrowRight works; unchanged
   code, keyboard tests pass) — recheck in Slice 08 accessibility pass.
8. Visual gap to the reference (honest QA appraisal): smaller, sober wheel without large orb/rings; monospace
   everywhere (reference uses a sans-serif for row titles); placeholder trees look empty; panel top/bottom edges are
   straight. Human visual check in Slice 09.
9. Not verified at runtime: real video (no ffmpeg on the machine; error path shown correctly), audio (needs mic),
   collision with the Studio.
   - Items 1 and 3: **resolved in Slice 04** — an inert row (status row, disabled entry) no longer closes the wheel
     (`tool_wheel.item_inert`, `test_an_inert_row_keeps_the_wheel_open_an_active_row_closes_it`); two open screen
     recordings → primary click opens the stop list, covered by
     `test_capture_wheel_browser.py::test_two_open_screen_recordings_primary_click_opens_the_stop_list`. Item 4 (stop
     row « Arrêter — écran princip… » cut, full text in the name and tooltip) and item 5 stay for Slice 08.

## From Slice 04 QA (JARVIS, Capture, top-left recording HUD) — targets Slice 08

- **P1. Under about 600 px the top-left refusal note covers the launcher** (375×667: CNV, AGT, ERR and « Plus d’outils »;
  500×800: CNV and AGT). `test_capture_wheel_browser.py::test_indicators_cover_no_neighbouring_control` calls
  `dismiss()` first, so it never sees the note. Lead: bound `.ri-note` by `--shell-launcher-w` like the host
  (`max-width: calc(100vw - 2 * gutter - --shell-launcher-w - 12px)`), and measure the note in that test.
- **P3. `test_capture_wheel_browser.py::test_audio_toggle_start_stop_matches_status` is unstable under load**: the
  fake source is released at 4 s while « starting » is awaited within 3 s; widen the window or gate on the click.
- **P4. During a lost status the bottom pills keep their counts** (pre-existing, before Slice 04): they should say
  the counts are unconfirmed, as the JARVIS submenu now does.
- **No Veille / Réveil control in the JARVIS submenu**: there is no Voice lifecycle API (sleep / wake) in Core or the
  Control Center. Candidate for a separate Issue: a canonical Voice lifecycle route first, then a control row.

## From Slice 06 implementation (Sélection actions) — targets Slices 07/08

1. **The page selection does not reach the brain.** « masque ça » / « range ça » are resolved by the brain from the
   scene, not from what the user selected (no page → Core selection channel; perception `surfaces` gap G1). In the
   sandbox, « masque ça » hid the only drawn window and the brain said « la seule fenêtre ouverte » while two
   windows were drawn as stars. Candidate Issue: report the page selection with the turn (bounded ids), then let
   `scene_*` / `dossier_ranger` default to it.
2. **« Réduire » is ambiguous**: the brain maps « réduis-les » to `point` (étoile). The wheel says Capsule = « titre
   seul » and Étoile = « réduite à un point » to stay consistent; the tool descriptions could say the same.
3. **Focus after a removal selects the neighbour** (`planFocusAfterRemoval` → focus → `anchorSelection`): after
   « Retirer du Board », an unrelated signal became the selection. Consider focusing without selecting.
4. **The selection count words follow the representation** (« 2 étoiles ») and not the kind: a group drawn as a point
   reads « étoile ». Fine for forms; a kind word may help in mixed selections.
5. **Brain turn over budget** on « masque ça » (9.4 s vs 8 s) — pre-existing brain latency, not Slice 06 code.
6. Sélection holds 8 rows with a selection (arc limit 9): any new action must go into a second level.
   - Item 3: **resolved in Slice 07** (see Slice 06 QA item 1).

## From Slice 06 QA (Selection actions) — targets Slices 07/08

1. **(assigned to Slice 07, first step)** After Masquer / Retirer / Ranger, an unrelated neighbouring object becomes
   the selection (`dossier-memory-…` after « 2 objets masqués », `brain-window-cachee` after Retirer); the next wheel
   action would act on it. Same as Slice 06 polish item 3.
2. Voice/UI parity: « retire-la du Board » makes the brain call `dossier_ranger` (writes a `notes/…` file, then
   archives) whereas the UI « Retirer du Board » writes nothing to the Dossier. Safe and truthfully reported, but the
   same words do not give the same operation. Brain prompt/tool wording, Slice 08.
3. Registry image window: a screenshot renders as a ~60×34 px thumbnail in a mostly empty window.
4. « Aucun objet masqué » row shows an orphan small circle at 600×800.
5. `docs/mcp/tool-contract.md` §10.18 could say that `dry_run` returns `refused dossier_board_not_active` on a Board
   that is not displayed.
6. `backing.reason` (e.g. « un groupe n'est qu'un cadre : rangez ses objets un par un ») is not shown; the UI shows
   only the generic message.
7. Seen in the sandbox, not compared with the base: a click / Ctrl+click on a star produced `set_representation`.
8. Not verified: a real agent star (actor `brain` refused by `execution_node`, `runtime` forbidden over HTTP).
   - Item 1: **resolved in Slice 07** (commit `5028bb20`): after Masquer, Retirer or Ranger the focus moves to
     the neighbour without selecting it; the selection keeps only what stayed drawn
     (`test_after_masquer_or_retirer_the_focus_moves_but_nothing_unrelated_is_selected`).

## From Slice 07 implementation (full-screen Dossier) — targets Slice 08

1. **Each `python -m jarvis control-center` start opens a browser tab** (`webbrowser.open` in `jarvis/app.py`,
   unconditional). That tab then keeps polling the navigation channels (Dossier, Variantes) of its port, even
   for a sandbox: in the S07 sandbox, tabs of the user's Chrome left on 27654 / 27674 took Jarvis's
   `open_entry` commands and answered `opened` in their own DOM. Proposal: an opt-out (`JARVIS_OPEN_BROWSER=0`)
   for sandboxes and tests; meanwhile operators set `BROWSER` to a no-op (`docs/OPERATIONS.md`). The tabs the
   S07 sandbox opened in the user's Chrome (ports 27654, 27674, 28654; earlier sandboxes likely did the same) are hers to close.
2. **Two parallel `dossier_view` calls** can collide on the broker (one command in flight → `command_busy` 409).
   Seen serialised in the sandbox (the second waits for its own `…/entry` read), not guaranteed. The tool could
   retry once on `command_busy`, or the broker could queue one.
3. **The brain still reads notes by path** (`Read`, `Bash cat`) before `dossier_view` (S05 polish 3), and once
   emitted an English working sentence (« Note decision-budget plus arbitrages-licences, side by side. ») and
   the known « previous response had no visible output » retry; turns over the 8 s budget (9-15 s).
4. **The brain cannot see which pane has focus**: « Affiche cette note sur le Board » with two notes side by side
   is answered by a question (honest). A page → turn context (active Dossier entry) would let « cette note »
   resolve; same gap as Slice 06 polish 1 (page selection).
5. **After an external archive the brain guessed** « la note apparaît sans doute deux fois » instead of reading
   the scene: `dossier_present` answers `created` but the brain does not check `scene_inspect`.
6. `Images et médias`: audio and video play the registry payload with the native controls; not exercised with a
   real recording in the sandbox (no capture made). A PDF opens in a new tab (no in-page viewer: `frame-src` CSP).
7. List titles of ordinary notes stay the file stem (« decision-budget ») while the open document shows its `#`
   heading (« Décision budget »); reading every note's head in the list would cost one read per entry. The
   service could cache headings, or the UI could fill row titles as documents are read.
8. `test_brain_capability_parity` was already failing before Slice 07 (Dossier tools and `ui_intent_publish`
   absent from the brain prompt); the Dossier tools are now named, `ui_intent_publish` (display, S4 of another
   handoff) still is not.

## From Slice 07 QA (full-screen Dossier) — targets Slice 08

Blocking findings B1 (a Jarvis order after a Board switch dropped an unsaved edit) and B2 (the 9th tab evicted
the edited one; `close()` did not ask) are **fixed in Slice 07** (`S7: fix - …`), with the two trivial ones
(« Renommé : … » never shown; the 600 px organisation drawer under the masked excerpt). Recorded, not fixed:

1. When Core is really stopped while the Control Center answers, `coreLost` stays false: no « Core ne répond
   pas » notice, Afficher sur le Board gives a wrong reason (« pas le Board affiché »), Enregistrer goes to the
   network and gets an honest 503. The wheel does say « Board inconnu ».
2. Narrow races without a generation check remain in `openById`, `move`, `remove` and `loadAdvanced`.
3. Link mode: the page does not re-check the URL scheme (`check_link_url` does upstream); defence in depth only.
4. A stale « Déjà sur le Board » flash stays visible during an edit or a conflict.
5. Brain: turns of 10-18 s, the « Your previous response had no visible output » retry, and on `created:false`
   it says « remise en avant », a slight embellishment.
6. `test_selection_actions_browser::test_ranger_refused_whole_or_kept…` is unstable (one failure, then two
   passes). Also seen in the QA fix pass: `test_mcp_plugin_service::test_stop_is_bounded_even_with_a_hanging_owner`
   failed once in a large lot, passed alone (timing under load).
7. Outside the Slice, Issue candidate: the brain is launched with `claude … --chrome`, which may give it access
   to the user's Chrome.

## Slice 08 triage (2026-10-18) — every item above

`fixed in S8 (<commit>)`, `→ Issue <file>` (in `Issues/`), `won't fix: <reason>`, or `resolved in S0x` when an
earlier Slice already closed it (said above).

| Origin | Item | Outcome |
| --- | --- | --- |
| S01a QA | no log line for a migration | fixed in S8 (`70337449`): `core.state.migrated {from, to, rows}` per applied step (sandbox: « jarvis.sqlite3 migrée de v8 à v9 (3 lignes changées) ») |
| S01a QA | brief writes `Type : presentation` | fixed in S8 (`70337449`): « Présentation » / « Réunion » |
| S01a QA | `requested_kind` quoted | fixed in S8 (`70337449`): bounded raw value |
| S01a QA | non-JSON lines in `runtime/trace.jsonl` | → Issue `pre-existing-test-failures.md` (multi-process appends, not this task) |
| S01a QA | `.v8.bak` in WAL mode | fixed in S8 (`70337449`): backup written in `journal_mode=DELETE` (sandbox header bytes 18-19 = 1/1) |
| S01b | no e2e test that `switch_noop` stops a Studio run | won't fix: covered at the service level (`test_board_switch.py`) and by the Studio's `foreign_change` classification tests; only the protocol can send a no-op switch (the card never, the brain answers `unchanged` first); now said in `presentation-studio.md` §6 |
| S01b | `presentation-studio.md` §6 silent on a switch to the active Board | fixed in S8 (`70337449`) |
| S01b | brain not told the mode was re-applied on `switch_noop` | won't fix: the brain's `board_switch` answers `unchanged` before any request when the Board is already active (`workspace_boards.py`), so no `switch_noop` comes from the brain |
| S01b | stale comments (`control_center.html`, `presentation_studio_roles.py`) | fixed in S8 (`70337449`) |
| S01b | `settings_get` / `settings_describe` « Réglage inconnu » for `interaction_mode` | fixed in S8 (`70337449`): same `interaction_mode_derived` refusal as `settings_set` |
| S01b | `NoneType` in the refusal trace | fixed in S8 (`70337449`): `absent` |
| S01b | `SOURCES.txt` lists the deleted module | fixed in S8 (`70337449`) |
| S01b | stale « Déjà dit » after a left switch | → Issue `brain-behaviour-follow-ups.md` |
| S05 QA | 1, 2, 4, 5, 7 | resolved in S07 |
| S05 QA | 3 note read with `Read` | → Issue `brain-behaviour-follow-ups.md` (still seen in the S08 trace) |
| S05 QA | 6 `memory/stat` gives no `sha256` | won't fix: the editor must read the whole file anyway (256 KiB bound) and gets the sha there; no other consumer |
| S05 QA | 8 `dry_run` and the active Board | resolved in S06; documented in `tool-contract.md` §10.18 in S8 (`5e43882c`) |
| S05 QA | 9 cross-Board Artifact link on Ranger | fixed in S8 (`5e43882c`): the Ranger report says « l'Artifact est désormais aussi dans le Dossier de ce Board » |
| S05 QA | 10 `boards_of_artifact(limit=500)` | fixed in S8 (`5e43882c`): direct `link_of(board, artifact)` lookup |
| S05 QA | 11 | resolved in S05 |
| S05 QA | 12 brain over budget, stray text | → Issue `brain-behaviour-follow-ups.md` |
| S02 QA | 1, 2 | resolved in S03 |
| S02 QA | 3 long Board titles cut at 1440 / 1920 | fixed in S8 (`2c3329df`): from 1400 px the card goes to 320 px and the title to two lines; status centre insets 338 px |
| S03 QA | 1, 3 | resolved in S04 |
| S03 QA | 2 keyboard focus lands under a motionless pointer | fixed in S8 (`b87995c9`): a trusted `pointerover` without movement is ignored until a real `pointermove` |
| S03 QA | 4 stop row truncated | fixed in S8 (`d7163d91`): title « Arrêter », target and timer in the note |
| S03 QA | 5 panels flare above / below their sector | won't fix: the tree stays inside the wheel's height so every row stays on screen at 720 px; its concave edge (238 px) clears the disc (224 px) and crosses only the decorative outer ring (S08 screenshots `roue-jarvis-*`, `roue-settings-*`); for the Slice 09 visual check |
| S03 QA | 6 `panel_yield` through `console.info` | fixed in S8 (`2c3329df`): one module journal |
| S03 QA | 7 Enter on the anchor | fixed in S8 (`b87995c9`): with a parked pointer, Enter focuses JARVIS (browser test and real page) |
| S03 QA | 8 visual gap to the reference | won't fix in S8: human judgement, Slice 09 (qualitative comparison in the S08 LOG entry) |
| S03 QA | 9 real video / microphone not run | won't fix: no ffmpeg and no microphone in the sandbox; real refusal path shown (`refus-capture-*`), recordings covered with Core's fake sources |
| S04 QA | P1 refusal note over the launcher under 600 px | fixed in S8 (`d7163d91`): the note is bounded like its host; measured at 375, 500, 600, 1280 (test and real page) |
| S04 QA | P3 unstable audio toggle test | fixed in S8 (`d7163d91`): the fake source is released 3.5 s after Core holds the start, not 4 s after Chrome starts |
| S04 QA | P4 pills keep their counts while the status is lost | fixed in S8 (`91974994`): « compte non confirmé » |
| S04 QA | no Veille / Réveil | → Issue `voice-lifecycle-api.md` |
| S06 impl | 1 page selection does not reach the brain | → Issue `page-selection-and-focus-to-brain.md` |
| S06 impl | 2 « Réduire » ambiguous | → Issue `brain-behaviour-follow-ups.md` |
| S06 impl | 3 | resolved in S07 |
| S06 impl | 4 count words follow the form | won't fix: deliberate (the row says what is drawn) |
| S06 impl | 5 brain over budget | → Issue `brain-behaviour-follow-ups.md` |
| S06 impl | 6 Sélection holds 8 rows | won't fix: a constraint, recorded in `control-center-shell.md` › *Selection actions* |
| S06 QA | 1 | resolved in S07 |
| S06 QA | 2 « retire-la du Board » parity | fixed in S8 (`1e9c06ed`): the `dossier_ranger` description names `scene_archive`; real trace → `scene_archive` |
| S06 QA | 3 registry image as a small thumbnail | fixed in S8 (`8a96ac68`): the image takes the window (aspect kept) |
| S06 QA | 4 orphan circle by « Aucun objet masqué » | fixed in S8 (`8a96ac68`): status rows carry an icon, aligned with the others |
| S06 QA | 5 `tool-contract` §10.18 and `dry_run` | fixed in S8 (`5e43882c`) |
| S06 QA | 6 `backing.reason` not shown | fixed in S8 (`8a96ac68`): the reason follows the code sentence, in the row and the report; Core's own reasons now French |
| S06 QA | 7 click on a star gave `set_representation` | won't fix: not reproduced in S08 (a click selected the object, « 1 objet sélectionné », no command) |
| S06 QA | 8 real agent star not verified | won't fix: the `brain` actor is refused by `execution_node` by design |
| S07 impl | 1 a browser tab at every Control Center start | fixed in S8 (`f620f736`): `JARVIS_OPEN_BROWSER=0` (journal `ui.browser`), default unchanged |
| S07 impl | 2 parallel `dossier_view` → `command_busy` | fixed in S8 (`5e43882c`): two retries 0.6 s apart |
| S07 impl | 3 notes read by path, English sentence, retry | → Issue `brain-behaviour-follow-ups.md` |
| S07 impl | 4 the focused pane is not visible to the brain | → Issue `page-selection-and-focus-to-brain.md` |
| S07 impl | 5 guess after an external archive | → Issue `brain-behaviour-follow-ups.md` |
| S07 impl | 6 audio / video / PDF not exercised | won't fix: no recording in the sandbox; PDF in a new tab is the `frame-src` CSP choice |
| S07 impl | 7 list titles are file stems | fixed in S8 (`0c95e5fe`): a note read once is listed by its `#` heading (the service list keeps the stem: one read per entry otherwise) |
| S07 impl | 8 `test_brain_capability_parity` | → Issue `pre-existing-test-failures.md` |
| S07 QA | 1 Core stopped not said, wrong reason | fixed in S8 (`0c95e5fe`): `dossier.core_lost`, « Core ne répond pas », nothing sent (test and real page) |
| S07 QA | 2 races without a generation check | fixed in S8 (`0c95e5fe`): every answer checks `S.gen` |
| S07 QA | 3 link scheme not re-checked | fixed in S8 (`0c95e5fe`): `safeLinkUrl`, http(s) only |
| S07 QA | 4 stale « Déjà sur le Board » | fixed in S8 (`0c95e5fe`) |
| S07 QA | 5 brain wording | → Issue `brain-behaviour-follow-ups.md` |
| S07 QA | 6 unstable `test_ranger_refused_whole_or_kept…` / `test_mcp_plugin_service` | fixed in S8 (`8a96ac68`) for the Ranger test (it waits on the page, not on fixed delays); `test_mcp_plugin_service` → Issue `pre-existing-test-failures.md` (timing, not this task) |
| S07 QA | 7 brain launched with `--chrome` | → Issue `brain-launched-with-chrome.md` |

## From Slice 08 QA — non-blocking (recorded, not fixed unless said)

Blocking findings B1 (two visible pages starved `/api/status`: the Dossier long-poll was the sixth held
connection; `refreshStatus` had no in-flight guard nor deadline) and B2 (« Affichage sur le Board… » left
forever after a Board switch) are **fixed in Slice 08** (`S8: fix - …` commits after `4b6a95f9`).

1. **P1** On a second page load, the registry image window is drawn small (h 21.6 scene units, about 95 px).
2. **P2** `JarvisDossier.gate(null)` (no `boards` block in the status) was taken as « Core perdu » — **fixed in S8**
   (B1/B2 fix commit): only a block that says `available: false` or carries an `error` means Core lost; no block
   means nothing is known.
3. **P3** After a page reload the Dossier list shows file stems again (headings are learnt by reading, per page).
4. **P4** `#barehandsHud` and `#barehandsPalette` are mounted but hidden by CSS while the wheel is shown.
5. **P5** A mixed `settings_get` list containing `interaction_mode` is refused as a whole
   (`interaction_mode_derived`); the tool's documentation should say so.
