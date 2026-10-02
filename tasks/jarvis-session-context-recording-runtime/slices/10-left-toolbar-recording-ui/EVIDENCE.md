# Slice 10 — Preuves (rail de capture du bord gauche, 2026-10-01)

Implémenteur frontal (sous-agent Claude pour « Claude Work Agent », limite D-TT). Skills chargées :
`/caveman`, `/coding-guideline`, `/impeccable` (pas de PRODUCT.md : affinage sur le monde visuel
existant, la palette Bare Hands ; détecteur `impeccable/scripts/detect.mjs` : 0 constat sur
`control_center_capture_rail.js`).

## 1. Ce qui est livré

- `jarvis/runtime/control_center_capture_rail.js` : hôte frère `#captureRail` (déclaré dans
  `control_center.html` juste après `#barehandsPalette`), inséré par `CAPTURE_RAIL_SCRIPT_MARKER`
  (`control_center.py`). Trois `<button>` : capture d'écran (action), audio, écran (bascules).
- `#captureRail` ajouté à `CONTROL_SELECTOR` (`control_center_scene_page.js`).
- Docs : `docs/capture.md` › *Interface: the left capture rail (Slice 10)*,
  `docs/barehands-contracts.md` (les commandes de capture ne sont pas des outils),
  `docs/ARCHITECTURE.md` (zone sûre : la colonne de gauche n'est pas calibrée) + Issue
  `Issues/scene-safe-area-left-column.md`.
- Aucun changement à `BH.TOOL`, `describeTools()`, `#barehandsPaletteStrip`, au `.dock`.
  `tests/unit/test_barehands_palette_js.py` inchangé et vert.

## 2. Décisions

- **Placement** (mesuré, `slotOf`) : *sous* la colonne Bare Hands (même colonne 64 px, filet,
  10 px) ; si cela sort de l'écran ou touche une commande (bouton de mode, indication vocale,
  dock, pastilles, barre du haut, bandeau GPT-Live, statut de scène) : *à côté* de la colonne,
  aligné sur son haut, puis sur son bas. Bare Hands non monté : *en haut de la colonne*
  (`alone`, 18/76 px ; sous 700 px, 10 px / 50 % − 41 px). Bare Hands éteint ou allumé :
  même géométrie (la palette ne fait que s'atténuer). Mesures : 1440×900 → `below`
  (rail 355–541 px, palette 168–345) ; 1280×600 → `beside` (x 82–146, y 76–262) ;
  375×667 → `beside` (x 74–138, y 293–457, bouton de mode 523–583).
- **Sondage** et non flux : `/api/status` ne porte pas les captures et la page n'a pas de flux
  poussé générique. `GET /api/captures/status` toutes les 1 s (5 s onglet caché), échéance 6 s,
  un seul sondage en vol, relecture immédiate après chaque écriture et au retour de l'onglet.
- **Modèle d'état** (`viewOf`, pur) : `idle`, `starting`, `active`, `stopping`, `stuck`, `error`,
  `unknown` (+ `busy`, `done` pour la capture d'écran). `aria-pressed="true"` seulement si Core
  liste une capture continue ouverte du canal. Chronomètre depuis `activated_at` (sinon
  `created_at`), figé à `stop_requested_at`. Statut perdu : tout en `unknown`, démarrages
  refusés, arrêt d'une capture connue ouverte encore proposé.
- **Textes d'erreur** (`refusalText`, `noteText`) : « <commande> non démarré — <cause> (<code>). »
  ; `source_unavailable` → micro / écran indisponible, ou « ffmpeg manquant : installez l'extra
  « capture » ou définissez JARVIS_FFMPEG_EXE » ; `permission_denied`, `storage_full`,
  `already_active` (note d'avertissement, pas d'erreur), `core_unreachable`, `core_timeout`,
  code inconnu → `échec (<code>)`.
- **Indices non colorés** : carré d'arrêt + barre latérale + chronomètre dans le bouton pour un
  canal ouvert ; `!` pour erreur / arrêt bloqué ; `?` + bordure en tirets pour inconnu ; coche
  2,5 s pour la capture faite ; balayage + compteur de secondes pour une attente. Ambre (`--warn`)
  pour l'enregistrement, comme la carte de diagnostic Bare Hands.

## 3. Validation en direct (instance isolée)

- Core (sources factices `FakeCaptureSources`, aucune capture réelle de l'hôte) sur
  127.0.0.1:18953 + vrai `ControlCenter` sur 127.0.0.1:18954, lancés par un script de travail
  (`<s10>/live.py`, non versionné) ; `JARVIS_DATA_ROOT=<s10>/data`, `JARVIS_RUNTIME_DIR=<s10>/runtime`.
  Drapeaux de fichier : refus de la source écran (`source_unavailable`), arrêt / reprise du
  serveur de Core. Pilote CDP `<s10>/drive.mjs` (Chrome sans tête, page
  `http://127.0.0.1:18954/` seulement). Deux passes : PID 43016 puis 39008, arrêtés par le
  drapeau `quit` (« STOPPED » au journal) ; ports 18953/18954 libres ensuite (netstat).
- Comparaison interface / vérité de Core à chaque étape (`GET /api/captures/status`) :

| Étape | Interface | Core |
| --- | --- | --- |
| repos | 3 × `idle`, légende CAPTURE, `below`, palette `data-bh-live=false` | aucune capture |
| capture d'écran | `done` (coche) | `screen:one_shot:complete` |
| audio | `active`, `aria-pressed=true`, 0:01 | `audio:active` |
| + écran | deux `active` (0:05 / 0:04), REC 2 | deux ouvertes |
| capture pendant les deux | `done`, les deux toujours `active` | 2 captures ponctuelles |
| arrêt audio | audio `idle`, écran `active` 0:06 | seul `screen:active` |
| arrêt écran | tout `idle` | aucune ouverte |
| écran refusé | `starting`, puis `error` + note « Enregistrement d'écran non démarré — écran indisponible (source_unavailable). » | ligne `starting` puis `screen:continuous:failed:source_unavailable` |
| Core arrêté (audio ouvert) | 3 × `unknown`, ÉTAT ?, audio « tenter l'arrêt » | relais 503 `core_unreachable` |
| Core revenu | audio `active` 0:07, compteur de Core | `audio:active` |
| 375×667 | `beside`, chronomètre continu ; arrêt audio → `idle` | idem |

- Défauts trouvés en direct et corrigés : (1) un démarrage refusé par Core passe par une ligne
  ouverte (`starting` → `stopping` → `failed`, `start_failed`) que le sondage voyait disparaître :
  la note disait « interrompu » au lieu de « non démarré », et le bouton passait par
  « arrêt en cours » ; (2) à 375 px la note d'erreur glissait sous le dock. Les deux ont un
  test navigateur (`…ligne_ouverte…`, `…note_d_erreur_reste_dans_l_ecran…`).
- Journal console `[capture]` de la passe : `installed`, `placed {below}`, `status_received`,
  `screenshot_requested/taken` ×2, `start_requested/started` ×3, `stop_requested/stopped` ×3,
  `start_failed {source_unavailable, 503}`, `status_lost {core_unreachable}`,
  `status_restored`, `placed {beside}` à 375 px.
- Captures de la page isolée (seulement elle, jamais le bureau) : `<s10>/live/01…12-*.png`,
  hors dépôt. Décrites : la colonne gauche montre main / palette / filet / rail ; deux boutons
  ambre avec carré d'arrêt et chronomètres, coche verte pour la capture ; à 375 px le rail est
  à droite de la colonne, la note rouge à sa droite, avant le dock.

## 4. Accessibilité

axe-core 4.10.2 (hors dépôt, `JARVIS_AXE_JS`), portée `#captureRail` : **0 violation** au
repos, pendant un enregistrement avec une note d'erreur ouverte, et en état inconnu, à 1440×900
et 375×667. Clavier (vraies frappes CDP) : Tab depuis la palette arrive sur le rail ; un seul
arrêt de tabulation ; flèches, Début/Fin, boucle ; Entrée et Espace démarrent ; Échap ferme
la note. Mouvement réduit : `crBreathe` et `crSweep` → `none`, chronomètre et barre d'attente
présents. `forced-colors` : carré d'arrêt et barre latérale présents.

## 5. Tests

- Nouveaux : `test_capture_rail_js.py` 35, `test_capture_rail_browser.py` 19 (dont axe) :
  **54 verts**.
- Bare Hands / mode / présentation / relais : `test_barehands_palette_js.py` (inchangé),
  `test_barehands_hud_js.py`, `test_barehands_contracts_js.py`, `test_interaction_mode_hud_js.py`,
  `test_interaction_mode_hud_browser.py`, `test_presentation_attention_browser.py`,
  `test_capture_relay.py` : **168 verts** (le cas mouvement réduit du contrôle de mode, connu
  pour dépendre de l'hôte, est passé dans cette course et a échoué dans une autre).
- `test_presentation_attention_browser.py::test_ecarter_l_avertissement_n_emet_aucune_requete` :
  liste blanche élargie à `GET /api/captures/status` (le rail sonde son statut, en lecture) ;
  un `GET /favicon.ico` intermittent du navigateur l'a fait échouer une fois, sans lien.
- Scène : `test_scene_renderer_logic`, `_interaction_logic`, `_hold_desk`, `_hold_contract`,
  `_hold_rework`, `_hold_rework2`, `_settings_ui`, `_view`, `_capture_logic` : **225 verts**.
- CC : `test_control_center_mvp`, `_appearance`, `_timeline_ui`, `_catalog_ui`,
  `test_boards_hud_browser`, `test_board_alerts_browser`, `_mcp_plugins_js`, `_mcp_inspector_js` :
  verts ; échecs connus seulement : `test_scene_group_drag_js.py` (5),
  `test_barehands_interaction_js.py` (2).

## 6. Non fait / limites

- Pas de panneau d'aide du CC qui liste les commandes : rien à mettre à jour.
- La zone sûre de la scène ne tient pas compte de la colonne de gauche (préexistant, aggravé
  par la hauteur du rail) : Issue `scene-safe-area-left-column.md`.
- Sous ~410 px de large, la pile des notifications (rang 70) couvre déjà toute la largeur, la
  palette comprise ; aucune exigence de non-recouvrement de la carte de présentation à ces largeurs.
- HV-REC-UI-001/002 restent à l'Humain (vrai Control Center, Bare Hands réel, sources réelles).
