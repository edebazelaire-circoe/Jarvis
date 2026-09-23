# Slice 03 — Implementation report

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Scope | The Control Center mode button and its three-choice selector. **No Presentation behaviour, no audio, no meeting behaviour.** |
| Canonical doc | `docs/interaction-mode.md` § "The Control Center selector (Slice 03)" |
| New suite | `tests/unit/test_interaction_mode_hud_js.py` (35) |
| Human check | `HV-PRES-MODE-01` — **not** marked done; the manual checklist is in §8 |

## 1. Files touched, and why

| File | Why |
| --- | --- |
| `jarvis/runtime/control_center_interaction_mode.js` | **New.** The whole control: pure projection (`viewOf`, `captionOf`, `subOf`, `labelOf`, `noteOf`, `optionsOf`), the stylesheet, the DOM binding (`createModeControl`), and the browser install block. |
| `jarvis/runtime/control_center.html` | Five edits: the stacking registry names the control and its two ranks; the `#interactionModeHud` host element is declared; the insertion marker is placed; `api()` now surfaces `X-Jarvis-Error-Code` as `e.code`; `refreshStatus` gains the `gate` / `statusLost` pair. |
| `jarvis/runtime/control_center.py` | `INTERACTION_MODE_SCRIPT_FILE` / `_MARKER` constants plus the `html.replace` in `ControlCenter.index`. |
| `tests/unit/test_interaction_mode_hud_js.py` | **New.** 35 tests: pure projection under node, a DOM/keyboard/ARIA world, the write paths, the install refusal, and the served-page assertions. |
| `docs/interaction-mode.md` | A Slice 03 section: the seam decision, the four presentations, the data-driven reservation, the write outcomes, the placement, the limits. |

Nothing else was touched. No other slice's files, no `voice_composition.py`, no
`_apply_voice`, no `PERSISTABLE_OPTION_IDS`.

## 2. The seam decision (G6) — the 1 Hz status poll, deliberately

**Chosen: bind to the existing `setInterval(refreshStatus, 1000)`.** Not a
generalised seam.

`openLifecycleSeam` is Bare Hands-specific and lives in
`control_center_barehands.js` — another slice's file. Generalising it would have
meant editing that module to invent a push mechanism nothing else would consume,
for a setting changed twice a day, and would have coupled the interaction mode
to a camera's lifecycle.

The repository already has a canonical answer for "a module that must follow
`/api/status`", used by **three** modules: a guarded `gate(block)` call inside
`refreshStatus`, and a `statusLost()` call in its `catch`
(`JarvisScene`, `JarvisBarehandsCommandChannel`, `JarvisBarehands`). I reused
that pattern verbatim rather than adding a fourth idiom. `statusLost()` is not
decoration: without it the page would keep a mode on screen that nothing
confirms any more.

**The price, written down rather than hidden:** up to one second between a
change made elsewhere and its appearance — except right after a click, where the
module calls `refreshStatus()` itself instead of waiting for the next beat. This
is stated in the module header, in `docs/interaction-mode.md`, and in
`control_center.py`'s comment.

**Zero local state.** `block` (the last `interaction_mode` snapshot) is written
in exactly three places — its declaration, `gate`, `statusLost` — and a test
asserts that count. Everything else the module holds is display: the open/closed
flag, the keyboard cursor, the in-flight request and its counter, the last
refusal sentence.

## 3. How each binding constraint is discharged

| Constraint | Discharge | Test |
| --- | --- | --- |
| **G6 — no framework, no generic seam** | Bound to the 1 Hz poll through the repository's own `gate`/`statusLost` pattern; no new poll, no second source | `test_le_sondage_a_1hz_remet_le_bloc_au_controle_et_dit_quand_il_tombe` (asserts both calls on the **served** page, that the mode gate is in its own `try`, and that the page never fetches `/api/interaction-mode` a second time), `test_un_changement_venu_d_ailleurs_repeint_le_bouton_sans_clic` |
| **G6 — a module that throws at insert time takes down the others** | The install block catches its own refusal and logs a searchable code | `test_le_module_refuse_son_absence_d_emplacement_sans_emporter_la_page` — actually `require`s the module twice under node, once without a host (no throw escapes, `interaction_mode_host_missing` on the console, nothing installed) and once with one (installs, paints, exposes `gate`/`statusLost`) |
| **G6 — no dependency on Bare Hands** | The module names no other page module | `test_le_module_ne_depend_d_aucun_autre_module_de_page` — strips comments, then refuses `JarvisBarehands`, `openLifecycleSeam`, `JarvisScene`, `JarvisSceneClient` in the code |
| **z-index registry** | The registry comment names the control (32) and its selector (36), with the reason they share Bare Hands' ranks yet can never overlap | `test_le_registre_d_empilement_nomme_le_controle_et_ses_deux_rangs`, and `test_les_rangs_du_module_sont_exactement_ceux_du_registre` — which checks the **stylesheet** against the prose, and that no rank sits on the host element itself (that would trap the selector under the button's own stacking context) |
| **No overlap with Bare Hands / Scene / notifications / live banner** | Bottom left; Bare Hands owns the top of the left edge | `test_le_controle_n_occupe_pas_le_coin_de_bare_hands` — asserts Bare Hands is top-anchored in both breakpoints, this control bottom-anchored in both, the selector opens upward, and the narrow offset clears the voice hint |
| **Read the right field — `core_reachable: false` is a local fallback** | `tone: unconfirmed`, **no chip checked**, dashed border, and the banner names `source`, the missing revision and the error code | `test_core_injoignable_ne_coche_rien_et_dit_que_la_valeur_est_locale` |
| **`stored` vs `label` — REUNION must not vanish** | `stored_label` is what was chosen, `label` what is running; divergence is shown on the button's second line and in the banner | `test_le_mode_choisi_et_le_mode_en_vigueur_restent_nommes_a_part` |
| **REUNION driven from `modes`, not a hard-coded string** | `implemented === true` is the only gate | `test_reunion_est_presente_partout_et_choisissable_nulle_part` — flips `meeting` to implemented (becomes selectable) **and** `assistant` to unimplemented (becomes reserved, and stops being checked) without a code change |
| **Wait for authoritative status; never paint optimistically** | `POST`, then re-read canonical status; the chip moves only because the status moved | `test_un_changement_attend_le_statut_canonique_au_lieu_de_se_peindre`, and `test_un_statut_qui_contredit_une_ecriture_reussie_gagne` — a successful write whose next status says otherwise paints what the status says |
| **200 / 409 / 503 / 400 handled distinctly** | Keyed on `e.code` from `X-Jarvis-Error-Code`, with per-family copy | `test_un_409_sur_un_mode_annonce_implemente_est_dit_comme_un_conflit`, `test_un_503_dit_enregistre_mais_pas_applique_et_non_echec`, `test_un_echec_laisse_le_mode_canonique_precedent_coche_et_dit_pourquoi` |
| **503 is persisted — say so** | "Mode enregistré, mais pas encore appliqué", never "échec"; and the status is re-read **after the refusal too**, so the choisi/en-vigueur divergence appears immediately rather than a second later | `test_un_503_dit_enregistre_mais_pas_applique_et_non_echec` asserts the word `échoué` is **absent** |
| **Failures leave the prior canonical mode selected** | Structural: there is no optimistic state to roll back | asserted in all four failure tests, plus the deadline test |
| **`role="menu"` + `menuitemradio`, roving tabindex, not `radiogroup`** | Copied with its reasoning | `test_les_fleches_deplacent_le_focus_sans_jamais_choisir` — six focus moves, then asserts **zero network calls** and an unchanged checked chip; plus `test_le_curseur_de_tabulation_vaut_le_mode_courant_au_repos` |
| **An undergone state checks nothing** | `unconfirmed`, `unknown` and `meeting` all leave `selected = null` | the three tests above, plus `test_un_statut_illisible_ne_retombe_sur_aucun_mode_plausible` (7 shapes of garbage) |
| **Refusal sets a live region, logs, and reopens the chooser on the reason** | `refuse()` does all three | every failure test asserts the chooser reopened, the note text, the announcement, and the journal line and level |

## 4. RULE ZERO — the waiting states

A write in flight shows all four required things: the sweep bar moves, the
button's second line says **what** (`PRESENTATION · 3 S`) and **how long**, the
chooser's banner repeats it in a sentence, and the options are disabled so a
second click cannot start a second request.

And the wait has a **deadline**. `fetch` has none; without
`WRITE_DEADLINE_MS = 12 s` a server that never answers would leave the control
disarmed and the screen with no way out. On expiry the control says how long it
waited, reopens the chooser, releases, and a late response can no longer paint
anything.

| Case | Test |
| --- | --- |
| the counter really climbs | `test_le_compteur_de_l_attente_monte_vraiment` (0 to 4 s, then back to empty) |
| the second click | `test_un_second_clic_pendant_une_ecriture_ne_part_pas` — one call, one body |
| the deadline | `test_une_attente_sans_reponse_finit_par_rendre_la_main` — releases at 12 s, a retry really leaves, the late response paints nothing |
| no network gate at all | `test_une_page_sans_porte_reseau_le_dit_au_lieu_de_ne_rien_faire` |
| an unusable `modes` catalogue | `test_un_catalogue_illisible_laisse_le_mode_visible_et_dit_qu_il_n_y_a_rien_a_choisir` |

The expected path is logged too, at info (`interaction_mode.requested`,
`interaction_mode.hud_installed`), not only failures.

## 5. Two defects the tests found before a human could

Recorded because they are the two that mattered.

1. **The busy state never appeared.** `paint()` painted a projection that was
   only recomputed when a status arrived, so the beginning of a write painted a
   view from *before* the request: no counter, no sweep bar, nothing moving —
   RULE ZERO's exact failure mode. `paint()` now recomputes the projection
   itself, and carries a comment naming the test that caught it.
2. **The normal announcement overwrote the refusal.** The repaint that follows
   a refusal rewrote the live region with the ordinary sentence, so a screen
   reader user never heard why their choice was not taken. `speak()` now gives
   a live refusal priority, and `gate()` clears it when the effective mode
   actually moves — but *not* after a 503, where the mode does not move and
   "saved, not yet applied" stays true.

Also found and fixed before review: `const api = ...` inside the module would
have shadowed the page's own `api()` network helper in the single concatenated
`<script>`, making the control believe no write was possible. The export is
named `MODE_API`, with the reason written next to it.

## 6. Validation

All foreground, narrow file lists (the host runs under 2 GB free).

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| `test_interaction_mode_hud_js.py` | **35 passed** |
| `test_barehands_hud_js.py test_scene_renderer_logic.py` | **83 passed** |
| `test_control_center_mvp.py test_control_center_quality.py` | **96 passed** |
| `test_interaction_mode_control_plane.py test_documented_routes.py` | **102 passed** |
| `test_control_center_testlab_js.py test_control_center_timeline_js.py test_control_center_timeline_ui.py test_control_center_appearance.py` | **110 passed** |
| `test_settings_endpoints.py test_control_center_catalog_ui.py test_control_center_voice_architecture.py test_control_center_prompts.py` | **90 passed** |
| `test_control_center_quality.py test_documented_routes.py test_interaction_mode_contract.py test_interaction_mode_protocol.py` (re-run after the doc edit) | **188 passed** |
| `test_barehands_interaction_js.py test_barehands_tutorial_retired_js.py` (baseline probe) | **3 failed, 50 passed** — exactly the 3 declared at the branch point |

Every mandated re-run suite is in the table. The four extra batches exist because
`api()` is shared by the entire page: changing it without exercising the
timeline, the Test Lab, the catalogue and the settings screens would have been a
blind edit. **Zero new failures.** None of the 26 pre-existing baseline failures
was touched, fixed, or added to.

Impeccable's mechanical detector, run once over the finished module, returned an
empty finding list:

```
node C:\DevTools\skills-lib\impeccable\scripts\detect.mjs --json jarvis/runtime/control_center_interaction_mode.js
[]
```

## 7. Reuse — and what was deliberately not reused

**Reused**

- `control_center_barehands_hud.js` as the pattern, not as code: zero local
  state, a pure projection separated from the DOM binding, injected
  dependencies (document, clock, timers, network gate), `role="menu"` +
  `menuitemradio` with roving `tabindex` and its written rationale,
  `aria-disabled` rather than `disabled` for an option that must still explain
  itself, an undergone state checking nothing, the live counter, the refusal
  that reopens the chooser, and the caught install refusal.
- The page's `gate` / `statusLost` seam convention (3 existing callers).
- The page's `api()` helper — extended by one line rather than bypassed with a
  private `fetch`.
- The page's design tokens (`--accent`, `--warn`, `--muted`, `--line`,
  `--panel`, `--danger`), its monospace type scale, its `color-mix` idiom and
  its `prefers-reduced-motion` block.
- Slice 02's status contract in full: `mode`, `label`, `revision`, `epoch`,
  `source`, `core_reachable`, `error`, `stored`, `stored_label`, `modes`, and
  the stable codes in `X-Jarvis-Error-Code`. Not one was re-derived.
- The per-mode explanatory sentence comes from the server's `summary`, not from
  a table copied into the page — two descriptions of one mode would eventually
  contradict each other.

**Deliberately not reused, with the argument**

- **The Bare Hands browser doubles** (`test_barehands_target_js.ELEMENTS`,
  `test_barehands_tools_settings_js.BROWSER_HEAD`,
  `test_barehands_lifecycle_js.WORLD`). `ELEMENTS.getAttribute` special-cases
  `aria-label` and returns a *fixture field* rather than what `setAttribute`
  wrote — every ARIA assertion in this slice would have passed while proving
  nothing. `BROWSER_HEAD` builds nodes by parsing the Experimental tab's markup
  with a five-tag regex, and its world requires a camera. Reusing either would
  have made the tests lie, so this suite carries its own small double, and the
  reason is in its module docstring.
- **`openLifecycleSeam`** — §2.
- **A second `/api/status` poll** — one source, one beat.
- **A hard-coded list of modes** — the catalogue is the server's.
- **Firing a request for REUNION to collect the 409** — a deliberate product
  reservation must not be dressed up as a failed round trip, and it would file
  an error line for a button doing exactly what it advertises. The 409 branch is
  kept and tested for the real case: this page's catalogue is a one-second-old
  photograph, and an older Core can refuse a mode it advertises.

## 8. Manual visual checklist — `HV-PRES-MODE-01`

Not performed by me, and **not marked done**. Open the real Control Center:

1. **Placement.** The mode button sits at the bottom left. It does not touch the
   Bare Hands control or its tool palette (top left), the GPT-Live banner
   (top centre), the voice hint (bottom centre), the dock, the background pills
   or the toasts (all right). The constellation scene, when enabled, passes
   behind it.
2. **SIMPLE to PRESENTATION.** Click the button; the selector opens **upward**.
   Choose PRESENTATION. The button briefly shows a moving sweep bar and a
   climbing counter, then settles on `PRESENTATION` in amber with a slow halo.
   Nothing turns amber before the server answers.
3. **Back to SIMPLE.** The halo stops, the colour returns to the ordinary blue,
   the label reads `SIMPLE`.
4. **REUNION.** It is listed, greyed, with a dashed badge and
   `Réservé · planned`. Clicking it or pressing Enter on it changes nothing,
   opens the reason in the banner, and — check the Network tab — sends **no
   request**.
5. **Keyboard.** Tab to the button, press Down: the selector opens and focus
   lands on the current mode. Up, Down, Home and End move focus across all three
   options, REUNION included, **without changing the mode**. Enter or Space
   chooses. Escape closes and returns focus to the button.
6. **Core unreachable.** Stop Core. Within a second the button desaturates, its
   border turns dashed, an amber dot appears, and the second line reads
   `NON CONFIRMÉ`. Open the selector: no option is checked, and the banner says
   this is the stored preference, with the error code. Choose a mode: the answer
   is "enregistré, mais pas encore appliqué", and the second line becomes
   `CHOISI : ...` while the label stays on what is running.
7. **Status lost.** Stop the Control Center backend: the button reads `MODE ?` /
   `STATUT INDISPONIBLE` rather than holding a stale value.
8. **Multi-tab.** Two tabs open; change the mode in one. The other follows
   within a second, with no click.
9. **Narrow.** Below 700 px the control moves to `left: 10px` and sits **above**
   the voice hint; the selector still opens upward and fits the viewport.
10. **Reduced motion.** With the OS setting on, the halo and the sweep stop; the
    counter keeps climbing.

## 9. Where SLICE.md and the live repository disagreed

Stated, not silently resolved.

1. **The dispatch brief says `control_center.html`'s `api()` helper "already
   surfaces" `X-Jarvis-Error-Code`. It did not.** `api()` read only the response
   body — `new Error(value.error || value.code || text || HTTP n)` plus
   `e.status`. It never touched response headers, and a grep for
   `Jarvis-Error-Code` across `control_center.html` and every
   `jarvis/runtime/*.js` returned nothing. Meanwhile the routes put the stable
   code **only** in the header and write a French sentence in the body
   (`raise error(text=str(exc), headers={SETTINGS_ERROR_CODE_HEADER: exc.code})`).
   Distinguishing 409 from 503 would have meant comparing French prose. I
   extended `api()` by one additive line (`e.code = header || value.code || null`)
   rather than opening a private `fetch`, and pinned it with
   `test_la_porte_reseau_de_la_page_expose_le_code_stable_du_refus`. This is a
   shared helper; the change adds a property and alters no existing behaviour,
   and the six page suites re-run in section 6 cover its callers.

2. **The brief says the registry comment "is asserted by
   `tests/unit/test_scene_renderer_logic.py`", and that failing to register
   would fail that test. It is not, and it would not.** That test parses **CSS
   numbers** over a fixed selector list in `control_center.html`,
   `control_center_work.js`, `control_center_scene_page.js` and
   `control_center_barehands.js`. It never reads the comment text, and this
   element's CSS lives in its own module, so nothing there would have moved
   either way. The only assertion on the registry's **prose** is
   `test_barehands_hud_js.py:983`, and it covers the Bare Hands line only. I
   registered the control anyway — it is the right thing to do, and the registry
   itself claims to be verified — and closed the gap the brief assumed existed
   with two tests of my own: one asserting my line is in the registry, one
   asserting the module's stylesheet carries exactly the ranks the prose
   promises. A registry that drifts from the stylesheet is worse than an absent
   one.

3. **SLICE.md's "Files Likely Touched" lists `control_center.py` for
   "injection". That was accurate, but there is no asset list to extend** — no
   tuple, no `_asset` helper. `ControlCenter.index` is a flat chain of twenty
   `html.replace(MARKER, file.read_text())` calls, so registering a module is
   three separate edits (two constants, one `replace`, one marker in the HTML).
   I followed the existing shape rather than refactoring twenty call sites in a
   UI slice.

4. **SLICE.md scopes "a dedicated host near existing left-side controls".** The
   top of the left edge is fully taken: `#barehandsHud` at `top: 76px` and
   `#barehandsPalette` at `top: 168px`, the latter with a height that depends on
   how many Bare Hands tools are installed. "Below the palette" is not a
   position anyone can promise. I took the bottom of the same edge, which is the
   only free left-edge slot, and documented the audit in the module, the page
   comment and the registry. This is the one placement judgement a reviewer
   should look at.

5. **The `coding-guideline` documentation chain names `docs/CONTEXT.md` and
   `docs/documentation-level-registry.yaml`, neither of which exists here** —
   already reported by Slices 01 and 02. The repository convention (a dedicated
   `docs/<concept>.md` linked from `docs/ARCHITECTURE.md`) was followed:
   `docs/interaction-mode.md` was extended, not replaced.

6. **The `error-handling` skill's contract does not exist in this repository** —
   already reported by Slice 02 (`send_error_response`, `obsClientLog`,
   `docs/observability/error-handling.md`, `/api/error-logs`: none of them are
   here). I followed the *rules* through this page's actual machinery: every
   failure is seen on screen, announced to screen readers, logged through the
   module's injected `log` into the browser console under a dotted kind, and the
   control is always released in a `finally`.

## 10. Judgement calls worth a reviewer's eye

- **PRESENTATION is amber, not cyan and not green.** Green was explicitly
  rejected for the Bare Hands active state and the same reasoning applies; red
  would read as a fault. Amber says "something other than the default is in
  force", which is exactly what the collapsed button exists to say at a glance.
  The `unconfirmed` state is additionally **dashed**, so the most important
  distinction in this control does not depend on colour vision.
- **`core_reachable: false` checks no chip.** A defensible alternative was to
  check the fallback value and merely annotate it. I read the brief's rule —
  an undergone state leaves nothing checked — as applying here, which makes
  "never present a local value as authoritative" structural instead of cosmetic.
- **A stored REUNION checks SIMPLE, not REUNION.** The chip means *in force*,
  which REUNION never is. REUNION instead carries a `Choisi` tag, the button's
  second line reads `CHOISI : REUNION`, and the banner names both. Checking
  REUNION would have claimed it was running; checking nothing would have erased
  the user's choice from the selection.
- **A live mode with an unusable `modes` catalogue still displays.** `mode`
  comes from Core and does not depend on the catalogue, so hiding it would
  remove the only information still reliable. Nothing is checked, and the
  selector says why it is empty.
- **`gate()` clears a stale refusal when the effective mode moves, but not
  otherwise** — so a 503's "saved, not yet applied" survives, because it stays
  true.

## 11. Nothing refused

Every acceptance criterion in SLICE.md is implemented and covered. The
exclusions are untouched by design: no Presentation behaviour, no audio, not a
line of meeting behaviour, and no duplicate control in Settings.
