# Slice 06 — Evidence

Branch `task/jarvis-generic-mcp-plugin-runtime`. Commits `13e38b0` (relay + callback page),
`35b05f0` (« Plugins externes » tab), then the docs/evidence commit. Date 2026-09-30.
Headless Chrome 153.0.8010.54 over CDP (script driver, no extension), axe-core 4.10.2.

## 1. Tests (foreground, `-q -p no:cacheprovider`)

| Command | Result |
| --- | --- |
| `test_control_center_mcp_plugins_api.py` (new) | **89 passed** |
| `test_control_center_mcp_plugins_js.py` (new, node) | **33 passed** |
| all `tests/unit/test_control_center*.py` (15 files, incl. the two new, `_mcp_api` amended, `_mcp_inspector_js` unchanged) | **492 passed** |
| `test_mcp*.py` + `test_tools_*.py` (10) + `test_app.py` + `test_v2_architecture.py` + `tests/integration/test_remote_mcp_connector.py` | **544 passed** |
| files touching the relay transport: `test_board_brains_control_center`, `test_board_switch_control_center`, `test_settings_mcp`, `test_scene_renderer_logic`, `tests/integration/test_board_session_e2e.py` | **160 passed** |
| every other unit test that reads `control_center.html` (30 files) | **636 passed, 3 failed** → 2 are READINESS « not yours » (`test_barehands_interaction_js`); 1 was mine (`test_barehands_palette_js`: my function `refreshTools` matched a banned dead-code name) → renamed `rereadPluginTools`, file re-run **46 passed** with the plugins JS file |

Deliberate test amendment (ARCH §14 C5): `test_control_center_mcp_api::test_only_get_routes_exist_under_the_mcp_prefix`
→ `…_under_the_catalog_and_the_plugin_set_is_pinned`: the catalog stays GET-only, the plugin
route/method set is pinned exactly, no route ends in `call`/`execute`/`invoke`. `test_writing_methods_are_refused_on_the_catalog`
(« read-only (GET) ») and the `mcp_tool_unknown` 404s for `/api/mcp`, `/api/mcp/servers` are unchanged and green.
`test_control_center_mcp_inspector_js.py` unchanged, green (inspector still GET-only, one `fetch`).

## 2. Acceptance → evidence

| Acceptance bullet | Evidence |
| --- | --- |
| One MCP button, one dialog; internal view unchanged; external cards (icon/letter, name, host, connection + auth badge, toggle, tool count, Gérer) | `test_the_served_page_carries_the_tabs_the_panel_and_the_module_after_the_inspector` (one `#mcpInspector`, tablist, two tabpanels); `test_cards_show_icon_or_letter_…` on real payloads; inspector test file unchanged green. Live: `s6_07_cards.png` (4 states: disabled, connected no-auth, connected OAuth, connected bearer, error) |
| Add by URL → create → connect: no-auth connected; OAuth opens a new tab and turns connected after the callback; manual Bearer/header write-only | `test_add_by_url_creates_connects_and_lands_on_the_new_card`, `test_oauth_opens_a_noopener_tab_polls_every_two_seconds_and_lands_connected`, `test_a_refused_connect_opens_the_manual_form_and_the_secret_never_stays` (value sent once, in the `PUT` body only; field emptied; absent from state, DOM, logs, toasts), `test_the_custom_header_form_needs_a_name_and_sends_it`, `test_the_credential_form_is_write_only`. Live §3 (a)–(c) |
| Enable/disable, reconnect, disconnect, remove (confirmed) reflect Core after reload | `test_the_switch_toggles_enabled_and_rereads_core`, `test_disconnect_of_an_authorized_plugin_is_confirmed_…`, `test_remove_asks_first_and_only_deletes_once_confirmed`, API `test_the_full_lifecycle_through_a_real_core`. Live §3 (d): state re-read after `Page.reload` |
| Plugin tools open in the inspector detail renderer; no tool-name literal | `test_manage_lists_the_plugin_tools_through_the_inspector_read_only_client` (rows + detail from `/api/mcp/tools[/plugin/name]`, ids `mcpi-mcpp-t-N-t`), `test_the_module_parses_and_names_no_tool_server_or_provider` (both modules: no catalog tool or server name, no `circuit|circoe|drive|google`). Live `s6_08_tool_detail.png` |
| Inspector still refuses non-GET / non-catalog paths (§10.7) | `test_control_center_mcp_inspector_js.py` unchanged and green (`fetch` count, GET-only guard); new export `toolRowsHtml` has no network |
| Cross-origin writes refused 403 coded; callback works cross-site; replayed callback shows the coded failure | API: `test_every_method_of_the_plugin_routes_is_guarded` (9 routes × 4 attacks), `test_the_callback_is_reached_by_a_cross_site_navigation_and_never_echoes_code_or_state`, `test_a_real_oauth_round_trip_then_its_replay_is_refused`. Live §3 (e) |
| Core down: coded error + « Réessayer »; internal view still works | `test_core_down_shows_the_coded_error_and_retry_reloads`, API `test_core_unreachable_is_a_coded_503_on_every_route`. Live §3 (f), `s6_11_core_down.png` |
| Keyboard + screen reader, < 700 px, reduced motion, page tokens only | `test_the_view_tabs_switch_by_click_and_arrows_…`, `test_escape_steps_back_before_the_dialog_closes`, `test_a_background_reread_never_wipes_a_typed_address`, `test_the_view_uses_page_tokens_…`. Live §3 (g), axe §4, `s6_09`/`s6_10` at 375 px |

## 3. Runtime validation (isolated instance)

Setup (all under the session scratchpad `s6_iso/`): `JARVIS_DATA_ROOT`, `JARVIS_RUNTIME_DIR`, Core
`127.77.0.1:17863`, Control Center `127.0.0.1:17864` (`JARVIS_UI_PORT`), `JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`,
`JARVIS_DRIVE_PROVIDER=none`, visualizer off, browser launch and brain CLI disabled by the launcher (no API
cost). Three `tests/fakes/fake_remote_mcp.py` worlds on loopback: `none`, `oauth` (fake AS, auto-consent),
`bearer` (static `SENTINEL-SECRET-7f3a-static`). The user's Jarvis (17653/17654) was never touched.
Every process started was stopped (tree kill); no listener left on 17863/17864/9333 or the fake ports.

- **(a) Add no-auth, keyboard only.** Tab/Arrow to « Plugins externes », Enter on « Ajouter un plugin »
  (focus → address field). `https://10.0.0.5/mcp` → « Adresse interdite · mcp_endpoint_forbidden · HTTP 400 »,
  typed address kept, focus back on the field (`s6_02_add_error.png`). Real fake URL + « Atelier » →
  connected, 2 tools, focus lands on the new card's « Gérer ».
- **(b) OAuth.** « Agenda » → 202 → a new tab opened by `window.open` (not blocked), `window.opener===null`,
  the fake AS redirected to `/api/mcp/oauth/callback` → « Autorisation reçue, vous pouvez fermer cet onglet. »
  (`s6_04_oauth_callback.png`), page HTML contains neither `code` nor `state`. The card showed the wait
  (`s6_03_oauth_waiting.png`: « reste 4 min 59 s », reopen link, « Ne plus attendre »), then « Agenda
  connecté ». **Finding fixed:** with plain `noopener` the callback tab's `document.referrer` was the Control
  Center URL, i.e. the AS got a `Referer` naming it → now `noopener,noreferrer`.
- **(c) Bearer fallback.** The bearer fake also publishes OAuth metadata, so `auto` ran OAuth, got a token,
  and the server refused it → `failed / mcp_plugin_reauthorization_required`. **Finding fixed:** the tab did
  not offer the manual form after a failed OAuth wait → it now opens « Gérer » with the form, focus in the
  password field (`s6_05_manual_token.png`). Typed the static value, Enter → `PUT …/credential` then
  connect → `connected / authorized / bearer`; field empty, `S.cred=null`. Sentinel: only in that one
  `PUT` request body; in **no** response body (23 captured), not in the DOM, not in the tab's state.
- **(d) Lifecycle.** Keyboard Space on a switch → disabled (`aria-checked="false"`, « désactivé : outils
  retirés »), focus kept on the switch (**finding fixed:** it was lost because the switch is `disabled`
  while its request runs; the intent is now held until it is enabled). Re-enable from the Manage view →
  Core reconnected it; Enter on a tool row → inspector detail (params table, effect, atomicity), ArrowDown to
  the next row (`s6_08_tool_detail.png`). Escape → back to the list, focus on « Gérer ». Disconnect « Agenda »
  → page confirmation (« Annuler » focused) → `disconnected / unknown / none`, `enabled` kept; Reconnect →
  new OAuth tab → `authorized`. Remove a plugin in error (`/crash` → `mcp_remote_unreachable`): Cancel keeps it,
  Confirm (danger dialog) deletes it, focus → « Ajouter un plugin ». `Page.reload` → the three plugins read
  back from Core with their states.
- **(e) Guard and callback (curl).** Cross-origin POST, cross-site DELETE, rebinding Host GET → `403
  forbidden_origin`. `PUT /api/mcp/plugins` → `405`, `Allow: GET, HEAD, POST`, `method_not_allowed`.
  `/api/mcp/plugins/127/tools` → `404 not_found`. Fresh authorization: first callback (cross-site
  navigation headers) → 200 with `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, CSP `default-src 'none'…`; replay → 400 page `mcp_oauth_state_invalid`; code/state
  found 0 times in either page; Host `evil.example.com` → 403 page `forbidden_host`.
- **(f) Core down.** Core tree killed while the dialog was open: « Actualisation impossible — Cœur de
  JARVIS injoignable · core_unreachable · HTTP 503 », « Réessayer », last list kept and labelled « (dernière
  lecture) » (`s6_11_core_down.png`); `GET /api/mcp/tools` meanwhile: natives served (50 tools), `plugins`
  `described=false, error=core_unreachable`. Core restarted: the three plugins reconnected at boot without
  any interaction (none, OAuth with stored token, bearer).
- **(g) Keyboard / reading.** From the dock: Enter opens, Shift+Tab reaches the view tabs; Arrow switches
  views; Tab order in the plugin view: tab → close → Actualiser → Ajouter → (switch, Gérer) per card →
  wraps (focus trap). Escape ladder: manual form → Manage view → list; add form → list; then the dialog closes
  and focus returns to the dock button; reopening restores the plugin view with focus on its tab. 375 px:
  no horizontal overflow (`scrollWidth = clientWidth = 375`) in the list and the Manage view
  (`s6_09_narrow_cards.png`, `s6_10_narrow_manage.png`). `prefers-reduced-motion: reduce`: spinner
  `animation-name: none`, switch knob `transition-duration: 0s`.
- **Sentinel sweep.** `grep -rl SENTINEL-SECRET-7f3a` over the whole isolated tree (SQLite, Core and CC
  `trace.jsonl`, Chrome profile, outputs) → **0 files**. CC trace: 22 `mcp.plugin.relayed`, 6
  `mcp.oauth.callback`, 3 `mcp.plugin.core_unreachable` / 3 `core_restored` (one per outage).

## 4. Accessibility (axe-core 4.10.2, scoped to `#mcpInspector`)

0 violations in: the card list (4 plugins), the Manage view with the manual form open, the add form, and
the Manage view at 375 px. `/impeccable` detector: no finding on `control_center_mcp_plugins.js`; its three
findings on `control_center.html` are on pre-existing lines (64, 206, 252), none in the new CSS.

## 5. Deviations and choices

- **Relay-local codes** added to the vocabulary: `core_timeout` (504, outcome unknown), `core_unconfigured`
  (503), `not_found` / `method_not_allowed` under the plugin prefixes, `forbidden_host` (callback page),
  `oauth_timeout` (UI only). All use Core's `{"error":{code,message}}` envelope; the guard keeps its own
  `{ok:false, code:"forbidden_origin"}` shape. The JS reads both.
- **`GET /api/mcp/plugins/{id}`** is relayed too (Core has it; guarded like the rest).
- **Callback without HEAD** (`allow_head=False`): a bodiless probe cannot consume a `state`.
- **Body bound**: the relay reads in a bounded loop; `board_routes.py` has the same single `read(n)` that
  a chunked body passes (found by my test; not changed here — Board scope).
- **Disconnect confirmation** when the plugin holds an access (its tokens/key are forgotten), in addition to
  the required remove confirmation.
- **« Relancer l’autorisation »** on a card whose Core state is still `authorizing` while the UI no longer
  waits (deadline passed or page reloaded).
- **`/` in the plugin view**: the inspector's shortcut still moves focus to its (hidden) search — nothing
  visible happens; left as is to keep the inspector untouched beyond its one export.

## 6. What HV-06-01 should look at

1. The card grid at desktop width: can each state be read at a glance (connected / authorized / error /
   disabled), is « désactivé : outils retirés » next to a « Connecté » badge clear enough?
2. The add flow wording and the OAuth wait block (« reste … », reopen link, « Ne plus attendre »).
3. The manual form: Bearer ↔ en-tête, the reassurance text, the auto-open after a refused OAuth.
4. The Manage view: action order and weight (« Supprimer » in danger style), the facts list, the tool rows
   reused from the inspector.
5. Keyboard-only pass and the Escape ladder; the 375 px layout.
6. With the real Circuit Toolbox (Slice 07, HV-07-01): the consent tab and the callback page.
