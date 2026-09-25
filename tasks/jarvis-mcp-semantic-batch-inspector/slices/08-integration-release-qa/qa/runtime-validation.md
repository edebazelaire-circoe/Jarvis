# Slice 08 — Runtime validation (page, D1, D-S5-1, inspector, parity)

HEAD `a9a5b16`, 2026-09-25. Product source was not modified. The only change made during this slice was the docs fix `aa4c7dd`.

**Verdict: PASS.**

## Environment

- **Phase A** (live brain, scene page): isolated Core `127.77.0.1:17683` and CC `127.0.0.1:17685`. The CC's own brain was disabled. The page ran in headless Chrome 153 (fresh profile, 1280×720) over CDP on port 9333. An in-page sampler ran every 200 ms (`evidence/scripts/sampler.js`) and recorded every `.sc-node` rect, its `sc-orbit` class and the scene revision. It also wrapped `fetch` for `/api/scene/commands` and mirrored console warn/error.
- **Phase B** (inspector): the same ports with fresh data. The CC launched its own brain through the `JARVIS_CLAUDE_CLI` wrapper (`brain_wrapper_main.py`), which strips `--chrome` and points to a fake Messages endpoint on `17689` with a dummy key. This cost $0. The MCP servers were the real ones. Scripts: `evidence/scripts/i8.py`, `i8b.py`, `parity.py`.
- One instance ran at a time. Everything started was stopped (Core, CC plus brain and MCP children, fake API, Chrome), and nothing of mine remains. The live Jarvis (17653/17654) was untouched and still listening at the end. Stray processes from 2026-09-24 16:39 were left alone.

## Scene page during the live brain turns (`evidence/page/page-analysis.txt`)

| Turn | Rev | Rendered-set changes during the turn | Result |
|---|---|---|---|
| T1 hide constellation | 25→26 | 1: orion, budget, equipe, planning gone together (risques was already hidden) | PASS (`t1-*.png`) |
| T2 show constellation | 26→27 | 1: all 5 back together | PASS |
| T3 move to left edge | 27→28 | 0 (rigid move) | PASS, see D-S5-1 |
| T4 archive finished stars | 28→29 | 1: 3 stars gone together | PASS |
| T5 unpin all | 29→30 | 0 (pin icons only) | PASS |
| T6 refusal | 30→30 | 0 | PASS |
| T7 move back | 30→31 | 0 | PASS |
| T8 settings read | 31→31 | 0 | PASS |

- The page sent **0** scene commands during brain turns.
- The page saw revisions 25…31 one by one.
- No console error or warning came from the page (1 206 samples, 241 s).

## Re-checks

| Check | Result | Evidence |
|---|---|---|
| **D-S5-1**: brain moves the constellation to the edge, then back | **PASS**. After T3, `orion-budget` sits at the safe-area edge. It is held still (`sc-orbit` = 0) at x 32–208 px, on-screen in 306/306 samples (61 s), and after that through T4–T6. Its dotted link to Projet Orion stays attached (`t4-before.png`). The other 4 members keep orbiting and stay on-screen. After T7 (dx +100), `orion-budget` orbits again (`sc-orbit` = 1), still on-screen (156 + 228 samples). | `page-analysis.txt`, `t3-after.png`, `t4-before.png`, `t8-after.png` |
| **D1**: user corner drag of an orbiting group | **PASS**. Ctrl-click selected {orion, budget, equipe, planning}, then a drag of −900,−500 px toward the top-left. The page sent **one** `translate_selection` (`pin:true`) with delta (−50.9, −7.6): the common delta was bounded by the members' orbits, and revision 31→32. Then 1 322 samples over **264 s**, more than one full 240 s orbit period: **0 off-screen samples** for every member, and all members orbiting. | `d1-analysis.json`, `d1-after-corner-drag.png`, `d1-orbit-later.png` |
| Inspector compact + detailed `scene_update_many` (1440×900) | **PASS**. Server chips: display *Annoncé* 13 · 31 864 o, console *Annoncé* 3 · 2 918 o, barehands *Désactivé* 5 · 4 107 o, drive *Connu* 7 · 2 126 o. Tabs: Général / Étoiles·Scène 13 / Réglages 3 / Bare Hands 5 / Externe 7. The Scène tab has 13 rows with correct badges (Lot atomique on update_many, move, archive, pin). The detail shows facts, a 9-parameter table, the `select` structure (15 keys, ConstellationArg, NearArg), rules and the output tree. | `i1-compact-general.png`, `i2-compact-scene.png`, `i3-detail-scene_update_many.png`, `evidence/inspector/i8.json` |
| Focus kept on a row toggle during a background refresh ("Actualiser" while focused) | **PASS**: 20/20 samples (2 s) on `mcpi-1-t` | `i8.json` `focus_during_refresh` |
| Focus kept in search during background indexing | **PASS**: typing `radius` started indexing (`paramètres indexés 1/28 → 16/28 → 21/28`), and focus stayed on `#mcpiSearch` for all 30 samples. Result: 5 tools, matched on `near.radius` / `select.near.radius`, with counts `5/13`, `0/3`… | `i8.json`, `i4-search-radius.png` |
| Esc with focus on `<body>` | **PASS**: `activeElement` = BODY, Escape → dialog hidden, focus returns to `#openMcpInspector` | `i8.json` `esc_on_body` |
| Reopen refreshes availability after a brain restart | **PASS**. Bare Hands on, brain running → *Configuré · redémarrage* and the pending-restart notice (`i5-pending-restart.png`). After `POST /api/agent/restart`, the brain reports `barehands_tools:true`. Reopening issues a new `GET /api/mcp/tools` and shows Bare Hands *Annoncé*, with no notice. | `i6-reopen-after-restart.png` |
| 360 px | **PASS**. No horizontal page scroll (`scrollWidth` 360 = `clientWidth`) in the list or the detail. The server strip and tabs scroll horizontally inside themselves. The detail text wraps. | `i7-360-list.png`, `i8-360-detail.png` |
| Read-only | **PASS**: 0 non-GET requests under `/api/mcp` | `i8.json` `non_get_mcp` |

Two things in the phase B browser log are expected and not defects. The console-error list in `i8.json` holds entries replayed by `Log.enable` from the phase A page while its CC was stopped (connection refused, `scene.view_degraded`), plus a favicon 404. The « Caméra refusée » toast comes from Bare Hands being on in headless Chrome, which has no camera.

## Parity: inspector vs actual tools/list (`evidence/inspector/parity.json`)

- **Names and counts vs the live CLI `system/init`:**
  - CC-launched brain (display + console + barehands): 13/13, 3/3 and 5/5, with equal names.
  - Real brain from phase A (display + console, plus the user-scope drive): 13/13, 3/3, and drive 7/7, with equal names.
- **Schemas vs what the model received.** 21 native definitions were captured on the fake endpoint. Each `input_schema` and `description` equals `GET /api/mcp/tools/{server}/{name}`, and bytes equal `context_bytes` for all 21. The only textual difference comes from the CLI: it rewrites `…` to `...` in 2 tools (`scene_move`, `settings_describe`), with the same byte count. Definition keys are `description`, `input_schema`, `name`, and there is no `outputSchema` or annotation anywhere.

## Not verified

- Scene switched off, because `JARVIS_SCENE_ENABLED=1` pins it on. Slice 06 covered that configuration.
- The Cosmos theme in this slice (Slice 07 covered it).
- Claude-in-Chrome in the user's real browser.
- Visual rigidity was not measured pixel by pixel. Orbits move the members independently, so rigidity was checked through the stored geometry (one common delta, one revision).
