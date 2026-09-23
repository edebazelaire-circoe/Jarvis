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
| **Read the right field — `core_reachable: false` is a local fallback** | `tone: unconfirmed`, **no chip checked**, dashed border, and the banner names the error code (corrected in the rework: it never named `source` or the missing revision, and those two fields are now gone from the projection because nothing rendered them) | `test_core_injoignable_ne_coche_rien_et_dit_que_la_valeur_est_locale` |
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

2. **The registry comment is not asserted by `tests/unit/test_scene_renderer_logic.py`.**
   *(Confirmed by the coordinator during the rework review; the claim came from
   the Slice 00 audit and `READINESS.md` has been corrected in place.)* That test parses **CSS
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

---

# Slice 03 — rework pass (second commit)

Three blocking defects and twelve smaller items, all inside this slice's own
surface plus two shared files it already touches. `a3e5583` is untouched.

## BL1 — a hung write permanently disarmed the control

One `deadlineTimer` per instance, but `choose()` calls overlap by design: the
deadline callback releases `choosing` while the first fetch is still in flight,
so a retry starts and writes **its** ticket into the same variable. When the
first late request finally settled, its `finally` cancelled whatever the
variable then held — the retry's deadline. The retry became unbounded, and the
button stayed busy with every option disabled for the life of the page.

Each call now holds its ticket in its own closure; a `Set` exists only so that
the `finally` can tell "my ticket is still armed" from "it already fired".

The new test drives the reported shape exactly: two writes that never answer,
overlapping. It asserts the second expires too, that both timeouts are
journalled, that a third attempt really leaves, and that the two late responses
paint nothing when they finally settle an hour later. The previous deadline test
could not see this, because its retry resolved immediately once the fake plan
was exhausted.

*Found while writing it:* my first patch created the ticket but never added it
to the set, so the `finally` never cancelled anything. The test caught it.

## BL2 — the bottom-left corner was not free, and the claim was in three places

The audit read `control_center.html` and missed three JS-injected stylesheets.
All three share this control's `left: 18px`:

| Element | Position |
| --- | --- |
| `#jarvisHands .jh-badge` | `bottom:18px`, host at `z-index: 2147483000` — paints over this control |
| `#jarvisHands .jh-note` | `bottom:46px` — landed inside the button |
| `.sc-status` | `bottom:18px`, moving to `52px` when the hands badge is present |

The repository already had a dodge convention for this rail, keyed off the Bare
Hands contract selector and governed by a test. **This module joins it** rather
than inventing a second offset: `body:has(…)` rules moving `--im-rail` up one
rung (52 px, above a single occupant) or two (86 px, above both, or above the
suppressed-gesture word, which implies the badge). Never a third rung — beyond
that the rail is overloaded and rationing it is not one occupant's decision.

`tests/unit/test_barehands_contracts_js.py` now asserts this module's rules
alongside the scene's, composing the note selector from `rootSelector` +
`noteClass` so the contract file itself did not have to change.

The false claim is gone from the module header and from
`docs/interaction-mode.md`, both of which now carry the table above.

Two tests replace the one that was wrong: one on the shared rail (the three
occupants, the convention, and that the rungs actually clear them), one on the
Bare Hands column that asserts what is true at full width and **names the limit**
below 700 px, where the column becomes centre-relative. Both read the
**produced** stylesheet, not the source, because the selectors are interpolated.

## BL3 — a 503 and the REUNION reservation were painted in the danger red

`refusalOf` computed `{tone:'warn'}` for both and nothing read it: `refuse()`
took only text and level, and `noteOf` hard-coded `tone:'bad'`. There was no
`[data-im-note=bad]` rule at all, so everything fell through to the base
`.im-note`, which was red.

The tone now travels with the text from `refusalOf` through `refuse()` into
`noteOf`, the base `.im-note` is neutral, and `bad` / `warn` / `wait` each have
a rule. The test that pinned `tone == "bad"` is rewritten to pin all four cases,
and the 409 and 503 tests now assert both the tone **and** the rendered
`data-im-note` attribute — asserting the text alone is what let this pass.

*Found while fixing it:* `speak()` still treated `failure` as a string, so once
it became an object the live region received `[object Object]`. The existing
failure test caught it immediately.

## The twelve

| | Fix |
| --- | --- |
| **1** | The Bare Hands column becomes centre-relative below 700 px wide, so "they hold the top, I hold the bottom" stops being guaranteed on a short viewport. The test that claimed both sizes now asserts both — and **names the limit** instead of implying there is none. The control shrinks itself under `max-width:700px and max-height:640px`; it cannot know the palette's height, and that residual is written in the module, in the doc and in the manual checklist. |
| **2** | `close()` clears `failure`. It outlived everything because `gate()` only drops it when the effective mode moves — right for a 503, wrong after a locally refused REUNION, where the mode never moves and a Core that went unreachable afterwards stayed hidden behind a stale sentence. The 503 survival is kept. Test: `test_un_refus_cesse_de_masquer_ce_que_l_on_subit_ensuite`. |
| **3** | The 12 s deadline no longer steals focus. It goes through the page's `toast()`, injected like every other page gate and guarded by `typeof`. Every *other* refusal still reopens the chooser, which is right: the click just happened. The deadline test now asserts the chooser stays closed, the focus stays put, and the toast carries the sentence. |
| **4** | `.im-pop` gains `max-height: calc(100vh - var(--im-rail) - var(--im-lift) - 96px)` and `overflow-y: auto`, as `.bgpop` does. It opens upward, so without them its top clipped off-screen with no way back. |
| **5** | Offline **and** a diverging stored value are both shown: `NON CONFIRMÉ · CHOISI : REUNION`. And the banner no longer says "ceci est la préférence enregistrée", which was **literally false** in exactly that state — the server returns `behaving(stored)`, and the two differ only on REUNION, the value decision 02 exists to protect. It now says the shown value is the mode that *would apply*, and names the choice beside it. Test: `test_core_injoignable_ne_fait_pas_disparaitre_le_mode_choisi`. |
| **6** | The 503 banner shows the server's sentence verbatim instead of re-prefixing it. The test asserts the word `enregistré` appears exactly once. |
| **7** | The `api()` edit is now **executed**, not grepped: the function is cut out of the served page on its braces and run against a `Response`-shaped double over six cases — 409 and 503 with the header, a JSON body carrying `code` and no header, a non-JSON body, a JSON success and an empty body — asserting `e.code`, `e.status` and `e.message` each time. Cutting on braces rather than a line window matters: the old window held about ten unrelated functions. |
| **8** | Deleted: `view.epoch`, `view.reasonMessage`, `view.pendingMode`, `option.disposition`, `option.effective`, the exported `snapshot()` and `destroy()`. `view.source` and `view.revision` are **dropped** rather than rendered — `live` plus `reason` is what the screen actually needs, and the REPORT claim that the banner named them is corrected above. `implemented`/`selectable`/`reserved` collapse to `reserved`, the word the screen uses. |
| **9** | `[data-im-tone=other]` exists. An unknown-but-implemented server mode is in force, so it is not desaturated, but it carries the plain text colour and no halo — painting it as SIMPLE asserted it behaves like SIMPLE. Test: `test_un_mode_inconnu_de_cette_page_ne_se_peint_pas_comme_simple`. |
| **10** | The lift above the voice hint now happens below **820 px**, not 700. The hint is centred at `bottom:22px` at every width and the page never moves it, so 701→820 was a window where both held overlapping halves and this control covered it (32 against 31). |
| **11** | The test reads the voice hint's `bottom` from `control_center.html` **and** from `control_center_work.js`, where the Cosmos theme moves it to 18 px, and takes the maximum. It also asserts the page's 700 px block does not mention it. The arithmetic is corrected too: clearance must beat the hint's **top**, not its bottom. |
| **12** | Option labels and glyphs follow the server on every paint. The name was stamped once at construction while `aria-label` was rewritten every paint, so a server-side label change made the visible name and the screen-reader name disagree — structurally the same mistake as the stale projection. Test renames a mode mid-flight and asserts both agree. |

**Accessibility.** Each option now carries its own visually hidden description
and points `aria-describedby` at it. The `.im-hint` banner was the target of no
`aria-describedby` at all, so a screen-reader user heard the label and the
reservation and never what the mode does. The description follows the server's
`summary` on every paint, like the label.

**Docs.** `docs/interaction-mode.md`: `other` added to the tones table with its
reason; the Placement section rewritten around the shared rail, with the table
of its three occupants, the dodge convention, the two rungs, the 820 px lift,
the chooser's scroll, and the **short-viewport residual** stated rather than
glossed; the write section gains the tone rule, the per-call deadline ticket,
the toast path and the refusal-expiry rule; Limits now says the runtime
dependency is nil while the *stylesheet* does name Bare Hands' and the scene's
selectors, and why that is not the same thing.

## Validation, rework pass

All foreground, narrow file lists (the host runs under 2 GB free). Node v24.18
is present, so nothing skipped.

```
.venv/Scripts/python.exe -m pytest <files> -q -p no:cacheprovider
```

| Files | Result |
| --- | --- |
| `test_interaction_mode_hud_js.py test_barehands_contracts_js.py test_barehands_hud_js.py` | **88 passed** (this suite 35 → 41; contracts 25 → 26) |
| `test_scene_renderer_logic.py test_control_center_mvp.py test_control_center_quality.py` | **158 passed** |
| `test_control_center_timeline_js.py test_control_center_testlab_js.py test_settings_endpoints.py` | **159 passed** |
| `test_interaction_mode_control_plane.py test_documented_routes.py test_interaction_mode_contract.py` | **202 passed** |
| `test_barehands_interaction_js.py test_barehands_tutorial_retired_js.py test_barehands_palette_js.py test_barehands_cards_js.py` (baseline probe) | **3 failed, 76 passed** — exactly the 3 declared at the branch point |

Every mandated suite is in the table. `test_barehands_palette_js.py` and
`test_barehands_cards_js.py` were added to the probe because the rail dodge is
keyed off Bare Hands' own elements. **Zero new failures.** The 26 baseline
failures are untouched.

Impeccable's detector over the reworked module: `[]`.

## Corrected manual checklist — `HV-PRES-MODE-01`

Replaces §8. Still **not** marked done. The earlier step 6 asserted the opposite
of what the code does, and the list did not exercise the contended rail at all.

**Set-up matters now: the check needs Bare Hands ON and the scene ON**, because
the control shares its rail with both.

1. **Bare Hands off, scene off.** The button sits at the bottom left, clear of
   the voice hint (bottom centre), the dock, the pills and the toasts (right),
   and the GPT-Live banner (top centre). Bare Hands' control and tool palette
   are at the **top** of the same edge and do not touch it.
2. **Turn Bare Hands on.** Its `MAINS` badge appears at the very bottom left and
   the mode button **steps up** to clear it. Nothing overlaps.
3. **Turn the scene on as well.** The scene indicator inserts itself; the mode
   button steps up a second rung. Still nothing overlaps, and the button is
   still fully readable.
4. **Trigger a suppressed gesture** (a pinch during a manipulation). The
   yellow word appears above the badge; the mode button is already clear of it.
5. **SIMPLE to PRESENTATION.** The selector opens **upward**. A sweep bar and a
   climbing counter show during the write, then the button settles on
   `PRESENTATION` in amber with a slow halo. Nothing turns amber before the
   server answers.
6. **Core unreachable, with PRESENTATION stored.** Stop Core. The button
   desaturates, its border turns dashed, an amber dot appears and the second
   line reads `NON CONFIRMÉ`. Open the selector: **no option is checked**, and
   the banner says the shown value is the mode that *would apply* — it must
   **not** say "ceci est la préférence enregistrée". Now store REUNION (or start
   with it stored): the second line must read `NON CONFIRMÉ · CHOISI : REUNION`
   — the stored choice must not vanish.
7. **503.** With Core down, choose a mode. The banner is **amber, not red**, and
   says "enregistré, mais pas encore appliqué" **once**. The second line becomes
   `CHOISI : …` while the label stays on what is running.
8. **REUNION.** Listed, greyed, dashed badge, `Réservé · planned`. Activating it
   changes nothing, shows an **amber** banner, and sends **no request** (check
   the Network tab). Close the chooser, then stop Core: the banner must now show
   the Core message, not the stale REUNION sentence.
9. **A hung write.** Throttle the network to offline mid-write. At 12 s the
   button releases and a **toast** appears — the chooser must **not** reopen and
   the focus must **not** jump. Retry twice in a row and confirm the control is
   still alive after both.
10. **Keyboard.** Down opens and focuses the current mode. Up/Down/Home/End
    traverse all three, REUNION included, **without changing the mode**. Enter
    or Space chooses. Escape closes and returns focus to the button. With a
    screen reader, each option should announce what the mode *does*, not only
    its name.
11. **Narrow and short.** At ~750 px wide the button lifts above the voice hint
    and does not cover it. Below 700 px it moves to `left: 10px`. **At ~700×600
    with several Bare Hands tools installed, check the tool palette does not
    descend into the button** — this is the known residual limit, and the point
    of the check is to record whether it bites in practice.
12. **Short viewport, chooser open.** At ~500 px high, open the selector: it
    must scroll rather than clip off the top.
13. **Status lost.** Stop the Control Center backend: `MODE ?` /
    `STATUT INDISPONIBLE`, not a stale value.
14. **Multi-tab and reduced motion.** Two tabs follow each other within a
    second; with reduced motion on, the halo and sweep stop while the counter
    keeps climbing.

## Still not satisfied

One thing, stated rather than hidden: **below 700 px wide on a short viewport,
the Bare Hands tool palette can descend into this control's band.** The palette
is centre-relative at that width and its height depends on how many tools are
installed; no CSS this module owns can clear an unknown height. The control
shrinks itself there, the limit is written in the module, in
`docs/interaction-mode.md` and in step 11 above, and the honest test asserts
what is true at full width instead of claiming both.
