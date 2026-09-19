# Bare Hands V1 — contrats, schémas et frontière clean-room

Contrat de référence des interfaces Bare Hands V1. Implémentation canonique :
`jarvis/runtime/control_center_barehands_contracts.js`
(`window.JarvisBarehandsContracts`), logique pure, sans DOM ni réseau ni
horloge, couverte par `tests/unit/test_barehands_contracts_js.py`.

Ce module **nomme**, il n'exécute pas. Les moteurs (suivi, gestes, pincement,
résolution de cible, interaction, outils, calibration) arrivent dans les Slices
suivantes et se branchent derrière ces noms. Aucun module n'a le droit de
redéfinir localement un nom qui vit ici.

## Un refus codé plutôt qu'un défaut plausible

Règle qui traverse tout ce fichier, et le seul endroit où la lire.

Partout où une valeur fausse deviendrait **indiscernable d'une valeur vraie**,
le contrat lève un `BareHandsSchemaError` portant un `code` stable,
journalisable tel quel — il ne rend pas un défaut d'apparence normale. Une
piste sans identité, une zone hors table, un état de capture inconnu, un
pincement sans coordonnées, un numéro de schéma étranger, une calibration
impossible : refus.

L'**absence**, elle, reste permise partout où un défaut a un sens : un champ
non fourni prend le défaut documenté, parce que personne n'a rien dit. C'est
l'inconnu qui se refuse, pas le silence.

Deux exceptions assumées, parce qu'elles normalisent un schéma **stocké** et
non un événement : `normalizeSettings` et `normalizeHandProfile` bornent les
valeurs hors plage au lieu de les refuser, et `normalizeTool` retombe sur
`pointer`. Un événement d'interaction, lui, refuse un outil inconnu.

Décisions produit adossées à ce contrat :
`tasks/jarvis-bare-hands-v1/docs/01-decision-log.md` (citées ci-dessous par leur
numéro) et `tasks/jarvis-bare-hands-v1/docs/02-architecture.md` (par leur §).

## Frontière clean-room

- Aucune ligne de l'amont Barehands (AGPL) n'est reprise, ni dans ce contrat ni
  dans le reste de l'implémentation native (décision 33). Les vocabulaires
  (gestes, régions, phases) sortent du journal de décisions, pas d'une source
  amont.
- `third_party/barehands/` est entièrement ignoré par git ; seuls `README.md` et
  `LOCK.json` sont versionnés.
- MediaPipe (Apache-2.0) n'atteint la page qu'à travers la liste blanche fermée
  de `jarvis/runtime/barehands_test_mode.py::ASSETS` : un nom absent de cette
  table répond 404, quel que soit l'état du disque.
- Les indices de points MediaPipe ne figurent **que** dans
  `adapters.MEDIAPIPE_LANDMARK`. Au-dessus de cette ligne, tout est exprimé en
  `HandFrame` neutre.

## Insertion dans la page

La page du Control Center ne charge aucun script externe : chaque module est un
repère commenté dans `control_center.html`, substitué côté serveur par
`ControlCenter.index()`. Le contrat a le couple
`BAREHANDS_CONTRACTS_SCRIPT_FILE` / `BAREHANDS_CONTRACTS_SCRIPT_MARKER`
(`jarvis/runtime/control_center.py`) et **précède** ses deux lecteurs :

```
…_BAREHANDS_CONTRACTS_JS__  →  …_BAREHANDS_JS__  →  …_SCENE_PAGE_JS__
```

L'ordre est vérifié par
`test_barehands_contracts_js::test_the_page_serves_the_contracts_before_everything_that_reads_them`.

## 1. Cycle de vie

`LIFECYCLE` = `off` | `sleep` | `active` | `error`. Les trois premiers sont les
états d'usage de la décision 4 : `OFF` libère la caméra, `SLEEP` garde un
guetteur léger, `ACTIVE` interagit. Implémenté par `createController` dans
`jarvis/runtime/control_center_barehands.js` (Slice 02).

`ERROR` s'y ajoute à la Slice 02 : sans lui, une caméra refusée, une webcam
occupée ou un modèle absent se liraient `off`, c'est-à-dire « l'utilisateur l'a
voulu », et la panne disparaîtrait de l'état. Comme `OFF` il ne tient rien — la
caméra, le modèle, la vidéo et la boucle d'images sont rendus **avant** qu'il
soit publié — mais il dit « arrêté sans l'avoir demandé ». Le motif précis vit
à côté, dans le `code` du statut (`camera_denied`, `camera_busy`,
`camera_missing`, `camera_ended`, `assets_missing`, `tracking_failed`…), jamais
aplati dans l'état. On en sort en rallumant : le bouton du bandeau devient
« Réessayer » et `activate()` rallume avant de réveiller.

- `SLEEP_TIMEOUT_MS = 30000` — 30 s sans main exploitable ramène `ACTIVE` à
  `SLEEP` (décision 7). Jugé avant la lecture de la vidéo : une caméra figée
  rendort aussi.
- `WAKE_HOLD_MS = 1000` — durée de maintien de la posture C (décision 5).
- `WAKE_INTERVAL_MS = 200` — cadence du guetteur de `SLEEP`, soit les
  **5 images par seconde** promises ici et à l'écran. La valeur vit dans le
  contrat pour qu'un seul endroit la fixe : c'est une promesse affichée.
- `FAILURE_CODES` / `isFailureCode(value)` — le vocabulaire des `code` que porte
  un statut `error` : `camera_denied`, `camera_missing`, `camera_busy`,
  `camera_ended`, `camera_unsupported`, `assets_missing`, `tracking_failed`,
  `overlay_failed`, `start_failed`. Le moteur possède les messages, le contrat
  possède les noms, et la parité est testée dans les deux sens : chaque code a
  son message, et toute autre clé de `MESSAGES` raconte le cycle de vie
  (`off`, `starting`, `sleep`, `active`, `woken`, `idle_sleep`, `disabled`) au
  lieu de motiver une panne.
- `overlay_failed` existe parce que la surimpression n'est pas le suivi : un
  anneau qui lève sortait sous `tracking_failed`, c'est-à-dire « caméra
  libérée », une cause inventée à la place de la vraie.
- `LIVE_LIFECYCLES` = `['sleep','active']` et `isLiveLifecycle(value)` — « Bare
  Hands fonctionne ». Un appelant teste ceci plutôt que `!== OFF`, qui rendrait
  une panne pour un fonctionnement : depuis `error`, couper l'interrupteur
  annonçait « Barehands arrêté — caméra libérée » par-dessus « Caméra refusée »,
  c'est-à-dire une phrase fausse à la place de la seule information utile.
  Côté moteur, `LIVE_STATES` / `isLiveState` en sont le miroir (le bloc pur est
  chargé seul par les tests node), et `isEngagedState` répond à l'**autre**
  question, que `!== OFF` confondait avec celle-ci : « quelque chose est-il tenu
  et à rendre ? » — la veille, l'interaction, et aussi un **démarrage encore en
  vol**, dont l'annulation est ce qui libère la caméra qui arrive. `error` n'en
  est pas : il a déjà tout rendu.
- `lifecycleOfControllerState(state)` lit les états du contrôleur
  (`off` / `starting` / `sleep` / `active` / `error`) dans ce vocabulaire.
  `starting` vaut `off` : rien n'interagit tant que la première image n'est pas
  suivie. `running`, l'ancien nom d'`active`, reste compris pour qu'un état
  journalisé avant la Slice 02 se relise encore.

### Transitions (Slice 02)

| De | Vers | Déclencheur |
|---|---|---|
| `off` | `sleep` | l'interrupteur « Activer Barehands », ou `activate()` qui allume d'abord |
| `sleep` | `active` | posture en C tenue `WAKE_HOLD_MS`, ou le bouton « Activer l'interaction » |
| `active` | `sleep` | bouton « Mettre en veille », ou `SLEEP_TIMEOUT_MS` sans main exploitable |
| `sleep` / `active` | `off` | l'interrupteur, ou `pagehide` |
| `sleep` / `active` / `starting` | `error` | caméra refusée, occupée, coupée, modèle absent, suivi en échec |
| `error` | `sleep` | rallumage explicite (interrupteur ou bouton) |

Allumer mène à `sleep`, jamais directement à `active` : rien n'interagit tant
que l'utilisateur n'a pas réveillé. Le guetteur de `SLEEP` ne lance son
inférence qu'une fois par `wakeIntervalMs` (200 ms, soit 5 images/s) et ne
calcule ni jeton, ni survol, ni clic ; `ACTIVE` suit chaque image.

## 2. Identité de main et de pointeur

L'expérience de clic envoyait **tous** ses événements sous `pointerId 9001`.
Ce littéral n'était pas un détail interne : `control_center_scene_page.js` et
`control_center.html` le lisaient (Slice 00, constat F2). Il devient une plage
possédée par ce contrat.

| Nom | Valeur | Rôle |
|---|---|---|
| `MAX_HANDS` | `2` | mains suivies en V1 |
| `POINTER_ID_BASE` | `9001` | identifiant de la fente 0 |
| `POINTER_ID_MAX` | `9002` | dernière fente |
| `POINTER_TYPE` | `'mouse'` | la sortie DOM reste une compatibilité (§7) |

- `pointerIdForSlot(slot)` — `0 → 9001`, `1 → 9002`. Hors plage : refus
  `barehands_slot_out_of_range`.
- `isBareHandsPointerId(id)` / `slotForPointerId(id)` — **le seul** test permis
  chez un consommateur. Personne ne recopie le littéral ; un test le vérifie
  sur `control_center_barehands.js`, `control_center_scene_page.js` et
  `control_center.html`.
- `createSlotAllocator(max)` — objet **gelé** portant `capacity`, `slot`,
  `pointerId`, `forget`, `retain`, `size` et `clear`. Une main garde sa fente
  tant qu'elle vit ; une fente libérée est réutilisée. Au-delà de `MAX_HANDS`
  la main surnuméraire reçoit `null` : elle est suivie, pas pointée, plutôt
  que de voler l'identité d'une autre.
  - `capacity` est une **constante** (les fentes qui existent) ; `size()` est
    l'**occupation** de l'instant (les fentes prises). Les deux se lisaient
    « size ».
  - `max` absent vaut `MAX_HANDS`. Toute autre valeur doit être un entier de
    1 à `MAX_HANDS` : `0`, `-1` et `'oops'` rendaient un allocateur qui marche
    alors que l'appelant s'est trompé. Refus
    `barehands_slot_capacity_invalid`.
  - `slot`, `pointerId`, `forget` et `retain` exigent une identité de main
    utilisable (`barehands_hand_track_id_missing`). `0` **en est une** ;
    `null`, `undefined` et la chaîne vide n'en sont pas. Deux clés normalisées
    différemment laissaient une piste fantôme occuper la fente 0 pour
    toujours — et la main suivante repartait à `9002`.
  - `pointerId` n'utilise pas `this` : `const {pointerId} = allocator` marche.

**Compatibilité.** La fente 0 vaut exactement l'identifiant d'hier : une main
seule produit les mêmes événements qu'avant la Slice 01. La seconde main, qui
parlait sous la même identité, a désormais la sienne.

### Formes du DOM (contrat inter-modules)

`DOM` possède les noms que trois modules partagent :

| Clé | Valeur | Lecteur |
|---|---|---|
| `rootId` / `rootSelector` | `jarvisHands` / `#jarvisHands` | `control_center.html` (exemption du balayage `inert`) |
| `tokenSelector` | `#jarvisHands .jh-token` | `control_center_scene_page.js` (`barehandsActive()`) |
| `badgeSelector` | `#jarvisHands .jh-badge` | CSS de la scène (décalage de `.sc-status`) |
| `tokenClass`, `ringClass`, `badgeClass`, `styleId`, `hoverClass` | — | surimpression |
| `wakeClass` | `jh-wake` | anneau de progression du réveil en veille (Slice 02) — un seul, il ne suit aucune main en particulier |

`isOverlayRoot(el)` est le test que fait `confirmInertCandidate` : la
surimpression des mains reste vivante derrière une boîte de confirmation, sans
quoi on ne pourrait plus y répondre à mains nues.

Les feuilles de style écrivent ces sélecteurs en clair — une feuille ne peut pas
lire le contrat. `test_the_style_sheets_agree_with_the_dom_names_the_contract_owns`
le fait à leur place et tombe si un nom diverge.

## 3. HandFrame (§1, §2)

`createHandFrame({t, source, hands})` → objet gelé
`{schemaVersion, t, source:{width,height,aspect,tracker}, hands:[…]}`.

Chaque main : `createHandObservation({handTrackId, handedness,
handednessConfidence, quality, points, raw})`.

- `handTrackId` est l'identité persistante (la Slice 03 la rendra stable par
  continuité spatiale) ; la latéralité n'est qu'un **indice**, jamais
  l'identité (§2). **`0` est une identité**, c'est même le premier qu'émet un
  traqueur qui numérote ses pistes : seuls `null`, `undefined` et une chaîne
  vide ou blanche valent « absente ».
- `points` porte les rôles de `POINT_ROLES` : `wrist`, `thumbTip`, `indexTip`,
  `middleTip`, `middleMcp`, `ringMcp`, `pinkyMcp`. Un rôle non fourni est
  absent ; le moteur qui en a besoin se déclare indisponible.
- `quality` ∈ [0,1] : 0 main devinée, 1 main franche. Les seuils et
  l'assistance s'y réfèrent, jamais à un score propre au traqueur.
- `raw` garde les points bruts pour le diagnostic et le rejeu (§12). **Aucun
  moteur n'a le droit de les lire.**

Refus (`BareHandsSchemaError`, champ `code`) : `barehands_frame_invalid`,
`barehands_hand_invalid`, `barehands_frame_time_invalid`,
`barehands_hand_track_id_missing`, `barehands_hand_track_id_duplicate`,
`barehands_too_many_hands`, `barehands_point_invalid`.

## 4. Gestes (§4, décision 5)

`GESTURE` = `c_pose` | `open_palm` | `fist` | `double_close` | `clap`.
`GESTURE_PHASE` = `start` | `hold` | `end` | `cancel`.
`GESTURE_SCOPE` = `global` | `hand` (liste : `GESTURE_SCOPES`) — un geste
global ne vole pas la main à une manipulation capturée.

`createGestureEvent({gesture, phase, scope, handTrackId, t, progress,
confidence})`. Refus : `barehands_gesture_unknown`,
`barehands_gesture_phase_unknown`, `barehands_gesture_scope_unknown`,
`barehands_hand_track_id_missing`.

`scope` absent vaut `global` ; `scope` **inconnu** se refuse, parce que le
repli silencieux était le plus dangereux des deux : `'Hand'` (majuscule) se
lisait `global`, et le geste volait la main à une manipulation en cours.

## 5. Intention de pincement (§5, décisions 20-22)

Le pincement est un **flux de contact**, pas une commande de clic. La durée et
le déplacement pendant le contact décident clic, glissement ou défilement. Le
clic droit est un canal, jamais un appui long (décision 22).

- `PINCH_CHANNEL` = `primary` (pouce + index, décision 20) | `secondary`
  (pouce + majeur, décision 21). Doigts dans `PINCH_FINGERS`, en rôles de
  points, jamais en indices de traqueur.
- `PINCH_PHASE` = `approach` | `down` | `move` | `up` | `cancel`.
- `createPinchEvent({channel, phase, handTrackId, slot, x, y, t, progress,
  confidence})` calcule `pointerId` depuis `slot`. `x` / `y` sont des
  **pixels de la fenêtre**, comme `clientX` / `clientY` — jamais des unités de
  scène. Ils sont **requis** pour `approach`, `down`, `move` et `up` ; seul
  `cancel` n'a rien à viser. Sans eux, un clic partait en (0,0), le coin de
  l'écran, où il y a toujours quelque chose à cliquer. Refus :
  `barehands_pinch_channel_unknown`, `barehands_pinch_phase_unknown`,
  `barehands_hand_track_id_missing`, `barehands_pinch_position_missing`,
  `barehands_slot_out_of_range`.

## 6. Cible et régions (§6, décisions 3, 8, 9, 16, 23)

`REGION` = `body` | `edge` | `corner`. `EDGE` = `top`/`right`/`bottom`/`left`,
`CORNER` = `top_left`/`top_right`/`bottom_right`/`bottom_left`.

Une zone tient un ou deux **côtés** du cadre (`ZONE_SIDES`) et chaque côté
contraint un axe (`SIDE_AXIS`). Raisonner en côtés, et non en axes, est ce qui
rend les décisions 16 et 17 décidables. `zoneSides(zone)` / `zoneAxes(zone)`.

`pickRegion(candidates)` choisit la meilleure candidate sur trois critères,
dans cet ordre :

1. **actionnable d'abord** (décision 3). Une candidate non actionnable
   n'appelle aucun retour visuel : c'est une obligation du **consommateur**,
   que le contrat ne peut pas tenir à sa place — il l'aide en classant ces
   candidates derrière. Les laisser gagner, c'est ne plus rien afficher là où
   il y avait quelque chose à montrer.
2. **priorité de région** : coin > bord > corps (`REGION_PRIORITY` = 3/2/1,
   `regionPriority`). Une région hors table vaut 0 et **n'est pas une
   candidate** : `pickRegion` la saute.
3. **la plus proche** (`distancePx`). À distance égale, la première citée
   gagne encore.

`createTargetCandidate({objectId, kind, region, zone, boundsPx, actionable,
representation, distancePx})` → ajoute `axes` et `feedback`. `objectId` est
l'identité de la scène (`data-object-id`) ; aucun élément DOM ne traverse ce
contrat.

**Unités.** `boundsPx` et `distancePx` sont en **pixels de la fenêtre**, comme
`clientX` / `clientY` — jamais en unités de scène (±160 × ±90, qui vivent dans
`control_center_scene_interact.js`). Le suffixe est dans le nom pour qu'une
confusion se voie à la lecture, au lieu de se déboguer comme un défaut de
géométrie dans le mauvais module.

`hasManipulationZones(representation)` : seules `capsule` et `window` ont des
zones (décision D3 de la Slice 00) ; `point` et `signal` restent
déplaçables seulement.

Retour visuel (décision 23) par **rôle**, la valeur vivant dans le thème :

| Rôle | Variable CSS | Repli | Sens |
|---|---|---|---|
| `body` | `--bh-feedback-body` | `#6ee7ff` | corps / normal (bleu) |
| `zone` | `--bh-feedback-zone` | `#ffd166` | zone de manipulation (jaune) |
| `secondary` | `--bh-feedback-secondary` | `#ff5d73` | clic droit (rouge) |

## 7. Interaction et capture (§7, décisions 10-19)

`INTERACTION` = `hover`, `click`, `context`, `drag_start`, `drag_move`,
`drag_end`, `scroll`, `select`, `move`, `resize`.
`CAPTURE_STATE` = `idle` | `captured` | `released` — une capture est latchée
jusqu'au relâchement (décision 13).

`createCapture({handTrackId, channel, state, objectId, region, zone, t})` valide
l'identité, la région et la zone. `channel` et `state` absents prennent leur
défaut (`primary`, `captured`) ; **inconnus**, ils se refusent — `state`
retombait sur `captured`, l'état latché, donc la capture ne se relâchait plus
jamais (décision 13) et rien ne disait pourquoi. Refus :
`barehands_capture_invalid`, `barehands_hand_track_id_missing`,
`barehands_region_unknown`, `barehands_zone_invalid`,
`barehands_capture_state_unknown`, `barehands_pinch_channel_unknown`.

### `combineCaptures(a, b)`

→ `{mode, axes, byHand, reason}`. Décide ce que produisent deux captures.

`axes` reste l'**union** : ce que le cadre peut bouger. `byHand` dit **quelle
main tient quoi**, indexé par `handTrackId`, chaque entrée portant
`{sides, axes}` : les côtés du cadre que cette main tire, et les axes qui en
découlent.

`byHand` existe parce que l'union seule ne sait pas exprimer la décision 16 :
bord droit + coin haut-droit et bord haut + coin bas-droit rendaient le même
`{resize, [x,y]}` alors qu'ils demandent des attributions **opposées**. Sans
lui, le moteur de la Slice 06 redériverait `ZONE_SIDES` / `SIDE_AXIS` chez lui
— exactement la duplication que ce module existe pour éviter.

Les **côtés** sont la donnée utile : deux mains peuvent tenir le même axe par
deux côtés opposés (le bas et le haut), ce qui est un redimensionnement
légitime et non un conflit.

| Situation | `mode` | `axes` | `reason` |
|---|---|---|---|
| une seule capture (état normal à une main) | `null` | — | `missing_capture` |
| la même main deux fois | `null` | — | `same_hand_twice` |
| un `objectId` absent des deux côtés (décision 12) | `independent` | — | `object_unidentified` |
| objets différents (décision 12) | `independent` | — | `different_objects` |
| **les deux** sont BODY (décision 8) | `null` | — | `both_captures_are_body` |
| une seule est BODY (décisions 10, 14) | `move` | `x,y` | `body_is_not_a_resize_handle` |
| même zone (décision 15) | `null` | — | `same_zone_rejected` |
| deux bords distincts | `resize` | union | — |
| bord + coin se recouvrant (décision 16) | `resize` | union — le bord garde le côté partagé, le coin ne garde que l'autre | — |
| deux coins sur un même côté (décision 17) | `resize` | union **moins** l'axe de ce côté, que ni l'un ni l'autre ne garde | — |
| deux coins opposés | `resize` | `x,y` | — |

Deux refus, et non des `reason`, parce qu'une entrée fausse y serait
indiscernable d'une vraie :

- une **zone hors table** d'un seul côté lève `barehands_zone_invalid`. Elle
  produisait un redimensionnement sûr de lui (`corner:top_left` +
  `edge:bogus` → `{resize, [x,y]}`) ; le motif `zone_unknown` que promettait
  ce tableau ne se déclenchait que si les **deux** zones étaient inconnues.
- une capture **sans identité de main** lève
  `barehands_hand_track_id_missing`, et une région hors table
  `barehands_region_unknown`. `byHand` est indexé par identité : sans elle,
  il n'y a pas d'attribution à rendre.

Deux BODY sur le même objet ne produisent **rien** : décision 8, BODY est de
l'interaction de contenu, pas une poignée de cadre. Avant, deux mains dans le
contenu d'une fenêtre emportaient la fenêtre entière. Quand une seule est
BODY, le déplacement appartient à la **seule main qui tient la zone**
(décision 10), et c'est elle seule qui apparaît dans `byHand`.

Décisions 18 et 19 (pas d'inversion, bornage à la taille minimale, rebasage
`RESIZE → MOVE`) appartiennent au moteur de la Slice 06 : la géométrie vit dans
`control_center_scene_interact.js`, en unités de scène (±160 × ±90), pas ici.

### `createInteractionEvent({type, handTrackId, slot, objectId, x, y, dx, dy, channel, tool, axes, t})`

L'événement que le moteur de la Slice 06 publiera sous les noms
d'`INTERACTION` → objet gelé `{schemaVersion, kind:'interaction', type,
handTrackId, slot, pointerId, objectId, x, y, dx, dy, channel, tool, axes, t}`.

- `x` / `y` — **pixels de la fenêtre**, requis : une interaction se produit
  quelque part.
- `dx` / `dy` — déplacement de défilement, en pixels de la fenêtre. Requis
  pour `scroll`, `0` ailleurs.
- `axes` — les axes contraints d'un `move` ou d'un `resize` : ce que rend
  `combineCaptures().axes`, repris tel quel.
- `channel` / `tool` — défauts `primary` / `pointer` quand ils sont absents,
  **refusés** quand ils sont inconnus. Un événement n'est pas un réglage :
  `normalizeTool` tolère l'inconnu parce qu'il normalise un schéma stocké.

Refus : `barehands_interaction_invalid`, `barehands_interaction_unknown`,
`barehands_hand_track_id_missing`, `barehands_interaction_position_missing`,
`barehands_interaction_delta_missing`, `barehands_axis_unknown`,
`barehands_tool_unknown`, `barehands_pinch_channel_unknown`,
`barehands_slot_out_of_range`.

## 8. Outils (§8, décision 25)

`TOOL` = `pointer` | `pan` | `highlighter` | `draw` | `select`,
`TOOL_DEFAULT = 'pointer'`, `normalizeTool(value)` retombe sur le défaut. Les
outils disent « ce que la main veut dire » et restent distincts des réglages.

## 9. Réglages (§9), version 1

`SETTINGS_SCHEMA_VERSION = 1`. `normalizeSettings(raw)` accepte l'absence et le
partiel, et rend toujours une valeur complète et bornée :

| Clé | Défaut | Bornes |
|---|---|---|
| `enabled` | `false` | Bare Hands reste éteint par défaut |
| `targetPreview` | `true` | décision 24 |
| `sleepTimeoutMs` | `30000` | 5 000 – 600 000 (**pas encore actif**, voir ci-dessous) |
| `tool` | `pointer` | `TOOLS` |
| `assistance` | `0.5` | 0 – 1 |
| `sensitivity` | `1` | 0,25 – 4 |
| `tutorialSeen` | `false` | — |
| `calibrationEnabled` | `true` | décision 27 : optionnelle |
| `diagnostics` | `false` | §12 : enregistrement sur demande |

**`sleepTimeoutMs` est exposé mais pas encore branché.** Le contrôleur de la
Slice 02 reçoit la constante `SLEEP_TIMEOUT_MS`, pas la valeur des réglages :
écrire `{sleepTimeoutMs: 120000}` normalise et persiste correctement, et ne
change rien au délai réel. **La Slice 07 possède les réglages** ; c'est elle
qui câblera le champ. D'ici là, ne pas le supposer vivant.

**Le numéro de schéma est lu, pas seulement estampillé.** `schemaVersion`
absent vaut « écrit par nous » ; tout autre nombre lève
`barehands_schema_version_unsupported`, dans `normalizeSettings` comme dans
`normalizeProfile`. Avant, des réglages en version 99 revenaient en version 1,
champs inconnus jetés, sans que rien ne le dise — alors que l'en-tête du module
promet qu'« un producteur et un consommateur qui ne partagent pas ce nombre ne
partagent pas ce contrat ». Le jour où une migration devient nécessaire, c'est
ce refus qui devient le point d'entrée : y accepter la version précédente et
la convertir, plutôt que de la laisser passer muette.

**Le serveur ne connaît aujourd'hui que `enabled`** :
`barehands_test_mode.apply()` refuse tout autre champ
(`barehands_unknown_field`). `toServerPayload(settings)` est donc le seul chemin
vers `POST /api/barehands`. Élargir la route, c'est monter
`barehands_test_mode.SCHEMA_VERSION` et `SETTINGS_SCHEMA_VERSION` dans le même
changement ; `GET /api/barehands` annonce la version sous `schema_version`.

Rappel de la Slice 00 (constat F5) : `barehands_test_mode` n'est
délibérément **pas** dans `/api/settings`. Sa paire de routes dédiée applique le
réglage à chaud sans dépendre de la validité du reste des réglages.

## 10. Profil de calibration (§10, décisions 28-32)

`PROFILE_SCHEMA_VERSION = 1`. Un seul profil visible, valeurs internes par main
(décision 28). Un seau **par latéralité de `HANDEDNESS`** : `hands.left`,
`hands.right` et `hands.unknown`. Le troisième existe parce que
`createHandObservation` retombe sur `unknown` dès que le traqueur n'étiquette
pas la main (§2 : la latéralité est un indice, pas une identité) — sans lui,
toute main non étiquetée perdait sa calibration en silence.

| Clé par main | Unité | Bornes |
|---|---|---|
| `pressRatio`, `secondaryPressRatio` | sans unité (fraction de la paume) | 0,05 – 0,9 |
| `releaseRatio`, `secondaryReleaseRatio` | sans unité (fraction de la paume) | 0,05 – 1,5 |
| `jitterPx` | **pixels de la fenêtre** | 0 – 200 |
| `reachNorm` | `{x,y,w,h}` en **coordonnées normalisées 0..1 de l'image**, comme les points d'un `HandFrame` — jamais des pixels | 0 – 1 |
| `quality` | 0..1, confiance de la mesure | 0 – 1 |

**Aucune image ni vidéo** : seulement des paramètres dérivés et des métriques
(décision 32).

- `normalizeProfile(raw)` : une valeur non mesurée vaut `null` ; `calibrated`
  est vrai dès qu'**une** mesure existe, quelle qu'elle soit — une calibration
  partielle est valide (décision 31) — et faux si rien n'a été mesuré, quoi
  qu'annonce l'entrée. La liste des clés mesurables est lue du profil
  lui-même, donc une mesure ajoutée par une Slice ultérieure (Slice 08,
  `secondaryPressRatio`, décisions 21-22) compte sans qu'on y repense. Elle
  n'en citait que trois sur sept : le drapeau et la donnée se contredisaient,
  et une porte qui teste `calibrated` relançait la calibration pour toujours
  tout en utilisant déjà la mesure.
- **Une mesure impossible se refuse**, elle ne s'applique pas :
  - `pressRatio >= releaseRatio` (le pincement ne pourrait jamais se
    relâcher, la main resterait collée à l'objet capturé) →
    `barehands_profile_thresholds_invalid`, pour le canal primaire comme pour
    le secondaire ;
  - `reachNorm` de largeur ou de hauteur nulle (tout l'écran ramené sur un
    point, ce qui défait le repli qu'elle devait remplacer) →
    `barehands_profile_reach_invalid`.
- `profileValue(profile, handedness, key, fallback)` : le seuil calibré s'il
  existe, sinon le défaut du moteur (décision 31). Une latéralité hors
  `HANDEDNESS` lève `barehands_handedness_unknown` et une clé hors profil
  `barehands_profile_key_unknown` — sans quoi une faute de frappe rendait le
  défaut du moteur et se lisait comme « pas calibré ».
- V1 est statistique/seuils, sans apprentissage personnalisé ni apprentissage
  continu (décisions 29, 30).

## 11. Adaptateurs

Seul étage qui connaisse un traqueur ou l'expérience actuelle.

- `adapters.MEDIAPIPE_LANDMARK` — table d'indices, pas un contrat ; un autre
  traqueur apporte la sienne.
- `adapters.handFrameFromMediapipe(result, meta)` — résultat MediaPipe →
  `HandFrame`. `meta.trackIds` permettra à la Slice 03 d'imposer son identité
  persistante — **y compris `0`** ; sans elle, la latéralité sert
  d'identifiant de repli, comme aujourd'hui. Une main aux points incomplets
  est ignorée, pas devinée. Une **troisième** main se refuse
  (`barehands_too_many_hands`) au lieu d'être tranchée en silence :
  l'adaptateur et `createHandFrame` appliquaient deux politiques opposées au
  même événement, et la seconde main disparue n'aurait laissé aucune trace.
- `adapters.pointersFromCoreTokens(tokens, allocator)` — jetons de
  `JarvisBarehandsCore.createHandTracker()` → `{handTrackId, slot, pointerId,
  pointerType, isPrimary, x, y, channel, phase, progress}`. C'est le chemin de
  compatibilité : l'expérience de clic garde sa forme, chaque main y gagne son
  identité.
  - **`allocator` est obligatoire** (`barehands_allocator_required`). Il
    était optionnel, et un allocateur neuf à chaque image donne la fente 0 à
    qui passe en premier cette image-là : les deux mains échangent leur
    `pointerId` en plein glissement, sans que rien ne le dise. L'appelant
    tient un `createSlotAllocator` pour toute la durée de vie de la session —
    c'est ce que fait `createInteraction` dans
    `control_center_barehands.js`.
  - Un jeton **sans `token.id`** lève `barehands_hand_track_id_missing`. Il
    occupait auparavant la fente 0 sous une clé fantôme que `retain` ne
    pouvait pas évincer : la main suivante repartait à `9002`, et la garantie
    de compatibilité de ce contrat était perdue définitivement, en silence.

## Ce qui est implémenté, et ce qui ne l'est pas

La Slice 01 n'a apporté aucun moteur : elle a fixé les noms — et, à sa reprise,
la règle qui les tient : un refus codé plutôt qu'un défaut plausible.

La Slice 02 implémente le premier : le cycle de vie `OFF`/`SLEEP`/`ACTIVE`
(+ `ERROR`) et le réveil par la posture en C, dans
`jarvis/runtime/control_center_barehands.js` — `cPoseScore`,
`createWakeDetector`, `createController` — couverts par
`tests/unit/test_barehands_lifecycle_js.py`.

La posture de réveil se lit sur deux mesures, toutes deux rapportées à la paume
donc indépendantes de la distance à la caméra : l'écart pouce-index, et la
portée de l'index depuis le poignet — celle qui écarte le poing, dont l'écart
pouce-index tomberait par hasard dans la bande.

Quatre défauts du moteur la décrivent : `wakeGapMin` (0,46 — au-dessus du
relâchement du pincement, pour qu'un pincement en cours ne réveille jamais),
`wakeGapMax` (0,85 — au-delà, main ouverte), `wakeIndexMin` (1,35 paume) et
`wakeSoft` (0,2). **Ce ne sont pas les seuils de réveil** : ce sont les points
où le score atteint zéro. Les deux plages s'adoucissent sur `wakeSoft` de leur
largeur, et il faut tenir `wakeScore` (0,5) pour que la posture compte. La
bande qui **soutient réellement un maintien** est donc plus étroite :

| Mesure | Bande effective | Zéro du score | Formule |
|---|---|---|---|
| écart pouce-index | **0,499 à 0,811 paume** | 0,46 à 0,85 | `wakeGapMin + s·wakeScore` … `wakeGapMax − s·wakeScore` |
| portée de l'index | **≥ 1,485 paume** | 1,35 | `wakeIndexMin · (1 + wakeSoft·wakeScore)` |

avec `s = (wakeGapMax − wakeGapMin) · wakeSoft = 0,078`. C'est cette bande que
la **Slice 08** calibre : citer 1,35 pour la portée se trompe de 10 % sur le
nombre à mesurer. Un balayage la recalcule et la compare à ce tableau
(`test_the_band_that_actually_sustains_a_hold_is_the_one_documented`) ; changer
un des quatre défauts sans reporter la bande ici fait tomber ce test.

Restent à venir : pincement secondaire, résolveur sémantique,
déplacement/redimensionnement, calibration, tutoriel, diagnostics et le canal
de commandes de la voix (Slices 03 à 12). `window.JarvisBarehands.activate()` /
`.sleep()` / `.lifecycle()` sont le point d'entrée que la Slice 12 branchera.
