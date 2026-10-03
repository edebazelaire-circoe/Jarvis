# Slice 05 — reprise QA (F1–F8) : preuve

## Montage

- Worktree `bwt`, branche `fix/pf-s5-rework` (depuis `6596371`). Core
  (`JARVIS_CORE_PORT=18963`) et Control Center (`JARVIS_UI_PORT=18964`,
  `JARVIS_SCENE_ENABLED=1`, `JARVIS_VISUALIZER_ENABLED=0`) lancés depuis `bwt`,
  `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un scratch de session. Ports
  17653/17654 jamais touchés ; serveurs et Chrome arrêtés après (plus aucune
  écoute sur 18963–18965).
- Vrai Chrome installé, `--headless=new`, profil jetable `--user-data-dir`
  (supprimé après), piloté par CDP. **Vraie souris CDP**
  (`Input.dispatchMouseEvent`) : les cadres de prefab sont hors processus,
  comme chez l'utilisateur.
- `drag_probe.mjs` (sonde de la QA S05, reprise) : `legacy-1` fenêtre classique,
  `pw-1` / `pw-2` `jarvis.window@1` côte à côte (`spec-window.json`).
  `drag-before.json` = même sonde sur `6596371` (code non corrigé),
  `drag-after.json` = après correction.
- `layout_probe.mjs` : parité `legacy-1` / `pw-1` à 280 × 220 px dans les deux
  thèmes, `pw-tall` (fenêtre du cerveau plus haute que son contenu), `doc-1`,
  `tbl-1` ; résultats dans `layout-results.json`.

Relance : `node drag_probe.mjs http://127.0.0.1:18964/ "<chrome.exe>" . after "$(cat spec-window.json)"`
puis `node layout_probe.mjs http://127.0.0.1:18964/ "<chrome.exe>" .`

Sorties brutes des tests en échec avant correction : `fails-before.txt`.

## F1 — gestes qui traversent un cadre de prefab

| Scénario (vraie souris) | Avant (`drag-before.json`) | Après (`drag-after.json`) |
| --- | --- | --- |
| poignée de la fenêtre classique tirée dans le cadre voisin | rien d'enregistré, objet resté tenu (`sc-gesture` encore posé), lâcher perdu dans le cadre | enregistré, posé **au point de lâcher** (écart bord droit/bas 0/0 px) |
| poignée d'une fenêtre prefab tirée dans le cadre voisin | rien d'enregistré, objet resté tenu | enregistré, écart 0/0 px |
| tête de la fenêtre classique traînée à travers deux cadres | rien d'enregistré, objet resté tenu | enregistré, écart 0/0 px |
| tête d'une fenêtre prefab traînée au-dessus d'un cadre | enregistré | enregistré, écart 0/0 px |
| fenêtre quittée (`blur`) en plein redimensionnement | **enregistré** quand même | annulé, rien d'enregistré, bouclier tombé |
| rectangle de sélection lâché au-dessus d'un cadre | rectangle resté ouvert, rien de sélectionné | fermé, `legacy-1` + `pw-2` sélectionnés |

Pendant chaque geste, `pointer-events` de **tous** les cadres = `none`
(`sc-gesture` sur la scène) ; après, `auto`. Console : aucune erreur.

Correction : `syncHolding` compte aussi le rectangle de sélection, règle
`.scene.sc-gesture .sc-prefab-frame{pointer-events:none}`, écoute `blur` de la
page (annule le geste souris comme `pointercancel`, abandonne le rectangle).
Les mains de Bare Hands (`JarvisScene.frames`) et le clavier passent par le
bureau (`desk.heldIds()`), déjà comptés par `syncHolding`.
Test : `tests/unit/test_scene_gesture_shield_js.py` (vraies fonctions de la
page sous node : appui/lâcher, `pointercancel` et `lostpointercapture` avant et
après mouvement, `blur`, main qui tient encore, rectangle lâché/annulé/abandonné).

## F2 — clic dans un cadre

Avant : clic au centre du cadre de `pw-2` → sélection vide, focus dans le cadre.
Après : sélection `["pw-2"]`, le focus reste dans le cadre (`IFRAME`).
Correction : `blur` de la page avec un `.sc-prefab-frame` en
`document.activeElement` → `onFocusIn` (même chemin que le focus d'un nœud).
Même fichier de test (fenêtre sélectionnée et cadre repris, focus laissé au
cadre, pas de menu ; sélection multiple qui la contient gardée).

## F3, F4 — `jarvis.window` : références entières, mise en page de la fenêtre classique

`side-by-side-circuit.png`, `side-by-side-cosmos.png` (280 × 220 px, même titre,
même corps de 412 px, mêmes entrées) :

- entrées **épinglées en bas** dans les deux (écart au bas 0 px), corps qui
  défile au-dessus et s'efface (`data-more`), comme `.sc-summary` ;
- références `docs/local-data.md` (109 px), `WAL` (18 px), `r1` (12 px)
  **entières** (`scrollWidth = clientWidth`) — avant : `r…`, `docs/lo…` ; la
  fenêtre classique, elle, coupe `WAL` à 0 px ;
- molette dans le corps du cadre (`window-body-scrolled-to-end.png`) : corps
  0 → 337 = fin, dernière ligne visible, fondu tombé, la page ne bouge pas ;
- hauteur rapportée = hauteur naturelle (cale `win-sizer` 583 px, cadre
  dessiné 167 px = conteneur) ;
- `window-taller-than-content.png` : fenêtre du cerveau de 300 px, contenu
  164 px → ajustée **une fois** au contenu (cadre 164 px, conteneur 167 px),
  les deux entrées entières (voir « Ajustement » ci-dessous).

Limite assumée : à 280 × 220, les libellés passant à la ligne (écart voulu,
D-FAMILIES) prennent 64/48/32 px ; plafonnées à 55 % du cadre (≈ 45 % de la
fenêtre, la règle de `.sc-items`), les entrées en montrent une entière, les
autres défilent. La fenêtre classique en montre trois, coupées sur une ligne.

Polices réellement rastérisées (`CSS.getPlatformFontsForNode`) : **Consolas**
pour le résumé et les entrées de la fenêtre classique comme pour le corps et
les entrées du cadre.

Tests : `test_prefab_base_catalog.py` (règles `.win-ref`, `.win`, `.win-body`,
`.win-items`, `.win[data-clamped] .win-items`, cale après `</main>`),
`test_prefab_base_behaviors_js.py` (cale = somme des parties visibles mesurées
sous `data-measure`, `data-clamped`, `--win-body-natural`, `data-more` au
défilement, recalcul au `resize`, état vide).

## Ajustement d'une fenêtre du cerveau (trouvé pendant la preuve F4)

Avant : une fenêtre de 300 px dont le contenu demandait 217 px finissait à
162 px — deux ajustements à 13 ms d'écart (43,9 puis 32,3 unités) : le second
lisait déjà la hauteur optimiste dans l'état et l'ancienne hauteur dessinée.
Après : un seul ajustement (43,9), entrées entières. Défaut antérieur à cette
Slice (pont de la Slice 04), révélé par une fenêtre `jarvis.window` honnête sur
sa hauteur. Test : `tests/unit/test_scene_window_fit_js.py` (avant : `[43.9, 32.3]`).

## F5 — anneau de focus du document

`document-focus-ring.png` : Tab dans le cadre → `doc` a le focus,
`:focus-visible`, contour `solid 1px rgb(220, 236, 244)` décalé de 2 px —
l'anneau de la coquille, comme tout prefab. Test : aucun prefab de base ne
retire `outline` sur un sélecteur `:focus*`.

## F8 — captures du tableau, couleurs

`table-selected.png` (ligne 3, `scrollTop` 0) et `table-scrolled-selected.png`
(ligne 17 après 14 × ↓ puis Entrée, `scrollTop` 563) : empreintes différentes.
Les deux captures de la première passe étaient identiques octet pour octet ;
elles sont retirées et `EVIDENCE.md` renvoie ici. Couleurs : plus aucune
valeur écrite en dur dans les styles des prefabs de base ; jetons ajoutés à la
coquille : `--jv-veil`, `--jv-title`, `--jv-link`.

## F6, F7 — publication de base et CSS de la coquille / de l'hôte

Voir `fails-before.txt` : CR dans le verrou ou une publication refusé (2 tests
en échec avant) ; chaque garde (publication, verrou) désactivée seule fait
échouer son propre test (mutants) ; `[hidden]` sans `!important` ou un cadre en
`flex:0 0 auto` font échouer les tests F7.
