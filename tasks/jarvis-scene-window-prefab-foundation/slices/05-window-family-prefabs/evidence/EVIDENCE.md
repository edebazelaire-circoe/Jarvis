# Slice 05 — preuve navigateur (prefabs de base de la famille fenêtre)

## Montage

- Vrai Chrome installé, `--headless=new`, profil jetable `--user-data-dir`
  (supprimé après), piloté par CDP : `browser_probe.mjs` (méthode des Slices
  03-04, plus un délai de 15 s par commande CDP). Aucune fenêtre ouverte dans le
  Chrome de l'utilisateur. Fenêtre 1600 × 1000 (5 px par unité de scène).
- Core (`python -m jarvis core`, `JARVIS_CORE_PORT=18993`) et Control Center
  (`python -m jarvis control-center`, `JARVIS_UI_PORT=18994`,
  `JARVIS_SCENE_ENABLED=1`, `JARVIS_VISUALIZER_ENABLED=0`) lancés depuis le
  worktree `bpf`, `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un scratch de
  session **neuf** pour la passe finale. Ports 17653/17654 jamais touchés ;
  les deux serveurs et le Chrome de la preuve arrêtés après (plus aucune écoute
  sur 18993/18994).
- Les trois prefabs viennent du **paquet livré** (`jarvis/prefabs/base/`,
  verrouillé) : rien n'est publié dans la bibliothèque de scratch.
- La page crée elle-même les quatre fenêtres comme l'utilisateur
  (`POST /api/scene/commands`, 4 × `200 applied`) : `legacy-1` (fenêtre
  classique : titre, résumé markdown, 3 entrées), `pw-1` (`jarvis.window@1`,
  **même** titre, même corps, mêmes entrées), `doc-1` (`jarvis.document@1`,
  ~11 000 caractères), `tbl-1` (`jarvis.table@1`, 8 colonnes × 64 lignes).

Relance : `node browser_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" .` puis, sur la même scène,
`node wheel_probe.mjs http://127.0.0.1:18994/ "<chrome.exe>" <dossier>` (molette du tableau ; dans la
passe principale, la molette envoyée juste après le défilement clavier n'a pas déplacé le tableau).

## Résultats (`browser-results.json`, captures PNG)

| Preuve | Observé |
| --- | --- |
| Côte à côte, Circuit imprimé | `side-by-side-circuit.png`, `overview-circuit.png` : même tête (`research`), même titre, même boîte 280 × 220 px ; corps du cadre : pile `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` rastérisée en **Consolas** sur ce poste Windows (ni `ui-monospace`, ni SF Mono, ni Menlo n'y existent ; mesuré par `CSS.getPlatformFontsForNode` dans la reprise, identique pour la fenêtre classique), texte `rgb(179,203,214)`, libellés `rgb(220,236,244)` — **identiques** au résumé et aux entrées de la fenêtre classique (`legacyTypography`) |
| Côte à côte, Cosmos | `JarvisThemeAPI.activate('cosmos')` : `side-by-side-cosmos.png`, `overview-cosmos.png` (rayon 14 px de la fenêtre, page) ; le cadre ne dépend pas du thème, la chrome de la page oui |
| Libellés | classique : 2 libellés sur 3 coupés (`scrollWidth > clientWidth`) ; prefab : les mêmes **passent à la ligne** (`wrapped [true,true,false]`, lignes de 48/48/16 px), hôte `sqlite.org` et flèche de sortie |
| Fondu | un cadre plus haut que sa fenêtre efface sa dernière ligne (`data-jv-more`), comme `.sc-summary` (captures côte à côte) |
| Document long | fenêtre 320 px, cadre 267 px = conteneur (le conteneur ne défile pas : `slotScroll [267,267]`) ; le document fait 6 059 px, au-delà du plafond `resize` de 4 000 px, et se lit en entier **dans** le cadre |
| Clavier du document | clic dans le cadre (focus `doc`) puis vraies touches CDP : Page bas 0 → 227 → 454, Page haut → 227, Fin → 5 792 = max, dernière ligne « FIN-DU-DOCUMENT » **visible**, position de lecture `scaleX(1)` ; Début → 0 ; molette → 600 (la page ne bouge pas) — `document-top.png`, `document-end.png` |
| Tableau 8 × 64 | 64 lignes, 8 colonnes, largeur 480 = largeur du cadre (pas de défilement horizontal) ; cellules courtes entières (`modifié`, `61,4 Ko`), chemins coupés après `/` ; en-tête collé en haut quand le cadre a défilé (`headerTop 0`, `scrollTop 56` après ↓ ↓, la ligne choisie entière entre l'en-tête et le fondu grâce au `scroll-padding`) — `table-8x64.png` ; les deux captures « choisie » et « défilée et choisie » de cette passe étaient identiques octet pour octet (constat QA F8) : remplacées par `rework/table-selected.png` et `rework/table-scrolled-selected.png` (ligne 3 en haut, puis ligne 17 après 14 × ↓, `scrollTop` 0 → 563, empreintes différentes). Molette (`wheel_probe.mjs`, `wheel-results.json`, même scène) : `scrollTop` 0 → 500 → 1000, avant et après le focus d'une ligne |
| `row_selected` | vrai clic sur la ligne 3 puis ↓ ↓ Entrée : anneau de Core `GET /api/prefabs/events?object_id=tbl-1` = `{index: 2}` puis `{index: 4}`, `class notify`, `outcome recorded` ; pied « 64 lignes · 8 colonnes · ligne 5 choisie » |
| Agrandir | 56 × 44 → 80 × 66 (révision 6) : cadre 197 px dans un conteneur de 277 px, plus rien ne défile, libellés re-coupés sur la nouvelle largeur (32/32/16 px) — `window-grown.png` |
| Accent et densité | patch utilisateur `accent #f0cf78`, `density compact` : **même** iframe (marqueur conservé), `--jv-accent` = `#f0cf78`, hôte du lien teinté — `window-accent-compact.png` |
| Rétrécir | 80 × 66 → 50 × 26 (révision 8) : cadre 77 px = conteneur, contenu 289 px qui défile dans le cadre — `window-shrunk.png` |
| Console | aucune erreur ni exception (page et cadres) ; `scene.prefab_mounted` × 3, `scene.prefab_event` × 2, `scene.user_resized` × 2 |

## Remarques

- **Redimensionnement à la souris.** Le glisser de la poignée `.sc-grip` par
  `Input.dispatchMouseEvent` ne se termine pas dans ce Chrome sans tête : le
  point de la poignée est bien touché (`elementFromPoint` = son `svg`), la
  fenêtre est sélectionnée, l'aperçu bouge d'une vingtaine de pixels, puis
  aucun `scene.user_resized`. La Slice 04 a prouvé ce même glisser sur une
  fenêtre prefab (après un glisser de la tête) ; le code du geste n'est pas
  touché par la Slice 05. Le redimensionnement est donc conduit par la couture
  `JarvisScene.frames` (`begin` / `preview` / `commit` en mode `resize`, le
  chemin Bare Hands), qui passe par la même commande et le même journal
  `scene.user_resized`. À regarder en HV-WINDOW-FAMILIES-01 avec une vraie
  souris.
- **Ajustement.** Les quatre fenêtres sont posées par l'utilisateur : la page
  ne les ramène pas à leur contenu (`fitBrainWindows` ne réduit qu'une fenêtre
  plus haute que son contenu, une fois par hauteur). Le cadre rapporte sa
  hauteur naturelle (`reported` 4000 px pour le document, plafonnée) et rétrécit
  à la fenêtre ; l'ajustement lui-même est celui de la Slice 04, inchangé.
- Un cadre sandboxé ne se rastérise pas depuis la page : la capture de la scène
  montre le repli (limite documentée, `docs/prefabs.md` › *Capture*).

## Reprise QA

Constats F1–F8 de la QA de la Slice 05 : corrections, tests et preuve navigateur dans
[`rework/EVIDENCE.md`](rework/EVIDENCE.md). La mise en page de `jarvis.window` a changé
(entrées en bas, corps qui défile au-dessus) : les captures côte à côte de cette passe
montrent l'ancienne ; celles de `rework/` la nouvelle.

## Note de la Slice 09 (confidentialité)

Les données d'exemple de la colonne « Auteur » du tableau utilisaient le nom de session de la
machine ; elles disent maintenant « Utilisateur » (sondes et `browser-results.json` corrigés). Les
11 captures PNG de ce dossier ont été **regénérées** par la même sonde `browser_probe.mjs`, inchangée
par ailleurs, sur le code de la Slice 09 (racines de scratch neuves, Core 18993 / CC 18994 isolés,
arrêtés après) : les 38 étapes passent ; `browser-results.json` reste celui de la passe d'origine,
au nom près. Balayage : `../../09-integration-hardening/evidence/privacy_sweep.py`.
