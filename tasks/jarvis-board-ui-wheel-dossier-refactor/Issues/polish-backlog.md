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
