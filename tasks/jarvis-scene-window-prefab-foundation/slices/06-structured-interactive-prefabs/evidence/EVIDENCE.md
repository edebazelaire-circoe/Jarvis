# Slice 06 — preuve navigateur (`jarvis.checklist`)

## Montage

- Vrai Chrome installé, `--headless=new`, profil jetable `--user-data-dir`
  (supprimé après), piloté par CDP : `browser_probe.mjs` (harnais des Slices
  03-05). Aucune fenêtre ouverte dans le Chrome de l'utilisateur. Fenêtre
  1600 × 1000.
- Core (`python -m jarvis core`, `JARVIS_CORE_PORT=18993`, hôte
  `127.77.0.1`) et Control Center (`python -m jarvis control-center`,
  `JARVIS_UI_PORT=18994`, `JARVIS_SCENE_ENABLED=1`,
  `JARVIS_VISUALIZER_ENABLED=0`) lancés depuis le worktree `bpf`,
  `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un scratch de session **neuf**
  pour la passe finale. Ports 17653/17654 jamais touchés ; serveurs et Chrome
  de la preuve arrêtés après (plus aucune écoute sur 18993/18994).
- `jarvis.checklist@1` vient du **paquet livré** (`jarvis/prefabs/base/`,
  verrouillé) : rien n'est publié dans la bibliothèque de scratch.
- Aucun glisser (examen QA en cours sur la capture du pointeur au-dessus d'un
  cadre) : clics et touches dans le cadre seulement.
- Les cadres sandboxés peuvent partager une cible CDP : le harnais lit chaque
  **contexte d'exécution** (un par document) au lieu de chaque cible.

Relance : `node browser_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" . http://127.77.0.1:18993 <runtime>/core.token`

## Résultats (`browser-results.json`, captures PNG)

| Preuve | Observé |
| --- | --- |
| Création | `ck-1` par la page comme l'utilisateur (`POST /api/scene/commands`, `200 applied`) : 6 éléments, un coché, une note sur deux lignes — `checklist-initial.png` |
| a11y | `role=group` « Liste de contrôle » ; 6 `role=checkbox` avec `aria-checked`, noms = libellés (`aria-labelledby`), note en description (`aria-describedby`) ; cases `aria-hidden` ; `role=progressbar` « Progression », `aria-valuetext` « 1 sur 6 cochés » ; note d'état `role=status` `aria-live=polite` ; **un** arrêt de tabulation |
| Souris | vrai clic sur la ligne 2 (point touché : l'iframe) : `aria-checked` vrai **à la lecture qui suit le clic** ; Core : `wal` coché |
| Clavier | Tab sort de la liste (focus −1), Maj+Tab revient sur la ligne 2 (`:focus-visible` vrai, deux filets `rgb(220,236,244)`), ↓ → ligne 3, Espace → cochée, écrite dans Core ; puis ↓ Espace ×3 → liste complète — `checklist-keyboard-focus.png` |
| Complétion | 5 `item_toggled` `applied` puis **un** `checklist_completed` `{count: 6}` `recorded` dans l'anneau de Core (`GET /api/prefabs/events`) ; toujours un seul 600 ms plus tard ; « Terminé · 6/6 », barre pleine, collée en haut quand la liste défile — `checklist-complete.png` |
| Rechargement | après `Page.reload`, les 6 cases cochées (l'état vient de Core) |
| Jarvis remplace la liste | `POST {Core}/v1/scene/commands` acteur `brain` avec jeton : `200 applied` ; le cadre montre les 3 nouvelles lignes, **même iframe** (marqueur conservé), 1 iframe dans la fenêtre, 0 `scene.prefab_mounted` pendant les écritures de Jarvis |
| Accent | Jarvis passe `accent` à `#ff7a59` : `--jv-accent` = `#ff7a59` dans le même cadre, aucune source modifiée — `checklist-brain-accent.png` |
| Coche sur la liste de Jarvis | clic sur la ligne 1 : écrite (révision 10) — la base du cadre suivait la scène |
| Thèmes | `checklist-circuit.png`, `checklist-cosmos.png` : le corps du cadre ne dépend pas du thème, la chrome de la page oui |
| Liste vide | Jarvis écrit `items: []` : « Aucun élément. », barre masquée, même cadre — `checklist-empty.png` |
| Console | aucune erreur ni exception (page et cadres), aucun `scene.prefab_error` / `scene.prefab_event_failed` |

## Constats hors périmètre (rapportés au PM, non corrigés)

- **Fenêtre prefab courte → capsule.** Après la liste vidée, l'ajustement de
  la page (`fitBrainWindows`, Slice 04) ramène `ck-1` à sa hauteur de contenu
  (h 17,1 unités ≈ 85 px), sous le seuil de lisibilité de la page
  (`READABLE.windowHeight` 96 px) : la fenêtre devient une capsule
  (`sc-capsule sc-compact`) et le cadre est démonté — `checklist-empty-after-fit.png`.
  Une fenêtre prefab au contenu court ne reste donc pas une fenêtre.
- **Fenêtre posée petite → capsule en orbite.** Une seconde liste de 44 × 24
  puis 48 × 36 unités posée par l'utilisateur est dessinée en capsule
  `sc-compact sc-orbit` (politique de la scène) ; l'état vide est donc prouvé
  sur `ck-1`.
- Premier chargement sur un scratch neuf : un clic calculé pendant
  l'ajustement initial de la fenêtre a manqué sa ligne une fois ; la preuve
  attend maintenant une géométrie stable (`settled`) avant de cliquer.
