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
…_BAREHANDS_CONTRACTS_JS__ → …_BAREHANDS_TARGET_JS__ → …_BAREHANDS_JS__ → …_SCENE_PAGE_JS__
```

(`…_BAREHANDS_TARGET_JS__` est arrivé à la Slice 05 : il lit les contrats et se
fait lire par le pointeur, donc il vit exactement entre les deux.)

La Slice 06 n'ajoute **aucun** module de page, mais elle ajoute une dépendance :
le bloc navigateur du pointeur lit `JarvisSceneInteract` au chargement (la
géométrie de la scène, où vivent les décisions 18 et 19). Ce module est inséré
bien plus haut (`…_CONTROL_CENTER_SCENE_INTERACT_JS__`), et l'ordre est
asserté par
`test_barehands_interaction_js::test_the_page_serves_the_scene_geometry_before_the_pointer_that_reads_it` :
servi après le pointeur, la page casserait à l'insertion — pas à l'usage.

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
| `targetClass` / `targetZoneClass` | `jh-target` / `jh-target-zone` | aperçu de cible (Slice 05) : le cadre visé, puis le **seul** bord ou coin retenu |
| `noteClass` | `jh-note` | ce qui a été **refusé** : geste étouffé pendant une manipulation, avec sa raison |

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
  l'assistance s'y réfèrent, jamais à un score propre au traqueur. Calculée
  par `JarvisBarehandsCore.handQuality` depuis la Slice 03 — voir §3 bis.
- `HAND_QUALITY_FLOOR = 0,25` et `isUsableQuality(value)` — **le seul** endroit
  qui dise à partir d'où une main *compte*. C'est ce que la décision 7
  appelait « une main exploitable » : la Slice 02 a dû l'approximer en « une
  main quelconque », faute de qualité à lire. Le moteur le recopie sous
  `DEFAULTS.qualityFloor` et le test de parité refuse la dérive.
- `raw` garde les points bruts pour le diagnostic et le rejeu (§12). **Aucun
  moteur n'a le droit de les lire.**

Refus (`BareHandsSchemaError`, champ `code`) : `barehands_frame_invalid`,
`barehands_hand_invalid`, `barehands_frame_time_invalid`,
`barehands_hand_track_id_missing`, `barehands_hand_track_id_duplicate`,
`barehands_too_many_hands`, `barehands_point_invalid`.

## 3 bis. Identité, filtrage et mouvement (§2, §3, Slice 03)

Le `HandFrame` de la §3 dit *ce qu'on voit*. Cette section dit **comment on
sait que c'est la même main d'une image à l'autre**, et ce que vaut ce qu'on en
mesure. Implémentation : `jarvis/runtime/control_center_barehands.js`
(`createHandTrackManager`, `createPointerFilter`, `createStillness`,
`handQuality`, `createHandTracker`), couverte par
`tests/unit/test_barehands_tracking_js.py`.

### Identité de piste

La latéralité ne fait pas une identité — le contrat le disait déjà, le moteur
s'en servait quand même comme clé. Un traqueur réétiquette une main vue de
profil, deux mains qui se croisent, une paume qui se retourne : les deux mains
échangeaient alors leur jeton, leur pincement et leur `pointerId` au milieu
d'un geste, sans que rien ne le dise.

L'identité vient de la **continuité spatiale**, mesurée au **centre de la
paume** (milieu poignet ↔ base du majeur) et non au bout de l'index, qui
parcourt plusieurs paumes pendant un pincement — une main qui pince se lirait
comme une main qui saute, c'est-à-dire comme une autre main.

À chaque image :

1. chaque piste prédit sa position (dernière position + vitesse, extrapolation
   bornée à `predictMs`) ;
2. le coût d'un appariement est la distance prédiction ↔ détection **en
   paumes** — invariante à la distance à la caméra, comme le pincement et le
   C — et **rien d'autre** ;
3. la porte (`matchRadiusPalms`) se juge sur cette distance : au-delà, ce n'est
   pas un appariement du tout ;
4. l'attribution retenue minimise la distance **totale**, pas la meilleure
   paire d'abord : au croisement, le glouton prend la paire la plus proche et
   impose la pire à l'autre. Recherche exhaustive, bornée par `MAX_HANDS` ;
   au-delà de quatre détections l'image se refuse (`tracking_failed`) plutôt
   que de laisser une factorielle grandir en silence ;
5. **la latéralité ne départage qu'à distance totale égale.** Elle est la clé
   *secondaire* de l'attribution — à somme d'écarts égale, celle qui compte le
   moins de désaccords d'étiquette gagne ; une étiquette absente d'un côté ou
   de l'autre ne compte ni pour ni contre. Elle ne peut donc rien renverser.
   Jusqu'à la reprise de la Slice 03 elle était une prime (`0,35` paume)
   **soustraite au coût**, et une prime soustraite est une clé déguisée : deux
   étiquettes qui basculent sur la même image — ce que fait MediaPipe quand
   deux mains se recouvrent — faisaient payer l'échange `(d − 0,35) × 2` contre
   `0` pour l'appariement juste, si bien que l'échange gagnait **sous 0,35
   paume de séparation** (≈ 3 cm). Le pincement, la capture et le `pointerId`
   partaient alors à l'autre main, définitivement au-delà de ~330 ms ;
6. **les coûts sont des distances, donc positifs ou nuls**, et c'est ce qui
   rend l'élagage de la recherche légitime : un total partiel minore le total
   final. Avec la prime soustraite il ne le minorait plus, et la recherche
   jetait de vrais optimums (670 sur 300 000 matrices 2×2 tirées au hasard) —
   le même appariement pouvait alors dépendre de l'ordre dans lequel le
   traqueur rend ses mains. Une troisième clé, les écarts triés du plus grand
   au plus petit, départage ce que les deux premières laissent à égalité, pour
   que l'ordre de la liste ne décide jamais.

Les identifiants sont des **entiers à partir de 0** — `0` est une identité, et
c'est le premier qu'émet un traqueur qui numérote ses pistes.

Une piste sans détection survit `lostGraceMs` : un trou d'une image ne coûte
pas l'identité, donc ne casse ni une capture ni un glissement. Elle revient
avec sa continuité retombée, parce qu'on *suppose* que c'est la même main.
La purge se fait **avant** l'appariement, pas après : purger après ne regarde
que les images reçues, et la première image du retour d'un onglet en
arrière-plan retrouverait une piste vieille de dix secondes encore posée là où
la main était — ressuscitée, avec sa capture. Même règle que la Slice 02 : la
grâce se compte contre l'observation, pas contre le nombre d'appels.

La latéralité de la piste, elle, se **vote** (gain `1/qualityWarmupFrames`) :
une image contraire ne retourne pas une étiquette installée, trois d'affilée
oui. Une étiquette absente ne vote pas — l'absence d'indice n'est pas un indice
contraire.

### Filtre adaptatif

`smoothing: 0,45` a disparu. Un coefficient fixe ne peut pas tenir les deux
promesses : bas, il calme le repos et traîne ; haut, il suit le geste et laisse
passer le tremblement. `options()` **refuse** désormais `smoothing`
(`RangeError`) au lieu de l'ignorer, pour qu'un réglage sans effet ne soit pas
indiscernable d'un réglage appliqué.

Le filtre One Euro (Casiez, Roussel & Vogel, CHI 2012 — réimplémenté depuis la
formule publiée, aucune ligne de l'amont, décision 33) fait varier la coupure
avec la vitesse. Mesuré contre l'ancien lissage, sur les deux fronts à la fois :

| | tremblement résiduel au repos (±3 px) | retard à 1 500 px/s |
|---|---|---|
| `smoothing: 0,45` | 1,31 px | 29,3 px |
| One Euro | 0,68 px (**0,52×**) | 9,2 px (**0,31×**) |

Les deux sont assertés dans le **même** test : gagner sur l'un en perdant sur
l'autre n'est pas un progrès, c'est le compromis qu'on refuse.

**La vitesse publiée n'est pas la dérivée interne du filtre.** One Euro mesure
sa dérivée contre sa propre sortie précédente, qui traîne : sur une rampe elle
lit la vitesse *plus* le retard divisé par dt — 1 400 px/s pour une main à 900,
et jusqu'à 40 px/s sur une main immobile qui tremble de trois pixels. C'est un
signal de commande, pas une mesure. `vxPxPerSec` / `vyPxPerSec` sont la dérivée
du **point filtré**, lissée au même `dCutoffHz` : sans biais en régime établi
(899 px/s mesurés pour 900 réels) et déjà débarrassée du tremblement.

#### Temps d'établissement de la vitesse — à lire avant de s'en servir

Le régime établi est exact ; le **transitoire ne l'est pas**, et il est lent.
La vitesse publiée est lissée à `dCutoffHz` = 1 Hz, soit une constante de temps
τ = 1/(2π·1) ≈ **159 ms**. C'est structurel, pas un réglage mal choisi : la même
coupure basse est ce qui empêche le tremblement du repos de se lire comme un
mouvement. Mesuré sur des images de 16 ms, main à 900 px/s :

| Événement | Ce que la vitesse publiée dit |
|---|---|
| arrêt net | `stillness` franchit 0,5 à **~250 ms**, atteint 1 à **~585 ms** |
| arrêt net | `stillMs` ne commence à courir qu'à ce **~585 ms** |
| inversion franche | la vitesse garde le **mauvais signe ~120 ms** |
| inversion franche | elle atteint 90 % de la nouvelle vitesse à **~490 ms** |

Conséquences, à prendre comme des contraintes et non comme des surprises :

- `stillMs` ne peut pas servir à reconnaître une immobilité **plus courte que
  ~600 ms** après un geste franc. Une main qui arrive vite et pince aussitôt se
  lit *en mouvement, `stillMs` = 0* ;
- `stillness` est le seul des deux utilisable dans la demi-seconde qui suit un
  geste, et encore : il vaut 0 pendant ~130 ms puis monte en rampe ;
- la **position** filtrée, elle, ne traîne pas de la même façon : à 900 px/s
  son retard est de l'ordre de 8 px et il se referme en deux ou trois images.
  Un consommateur qui a besoin de savoir « la main a-t-elle bougé » plutôt que
  « à quelle vitesse » doit lire un déplacement (`travelPx`), pas une vitesse.

`test_the_published_velocity_takes_its_time_to_admit_a_stop_or_a_reversal`
épingle ces quatre nombres : ils bornent ce que les Slices 04 à 06 peuvent
décider, et une retouche de `dCutoffHz` les déplace tous.

### Qualité de suivi

`handQuality(landmarks, aspect, continuity)` est le **minimum** de quatre
témoins — pas leur moyenne, qui laisserait trois bons chiffres cacher celui qui
dit que la main sort du cadre :

| Témoin | Ce qu'il lit | Réglage |
|---|---|---|
| échelle | paume minuscule ou dégénérée : les rapports mesurés en paumes n'ont plus de sens | `qualityPalmMin` |
| cadrage | le point utile le plus proche d'un bord de l'image ; une main qui sort du cadre rend des points extrapolés, et rien dans le résultat ne le dit | `qualityEdge` |
| complétude | les 21 points, pas seulement les quatre qu'on lit | `qualityComplete` |
| continuité | une main qui vient d'apparaître ou qui revient d'un trou est une main qu'on *suppose* être la même | `qualityWarmupFrames` |

La bande de cadrage est étroite (4 %) **exprès** : la marge de `toScreen`
(12 %) existe pour qu'on puisse viser le bord de l'écran, et une qualité qui
s'effondrerait là endormirait une session en plein usage — une panne pire que
celle qu'elle corrige.

Le score de latéralité du traqueur n'y entre **pas** : il répond à « suis-je
sûr que c'est une main *gauche* », pas à « suis-je sûr que c'est une main ».

**Ce que la qualité change, et ce qu'elle ne change pas.** Le minuteur de la
décision 7 ne se réarme plus que sur une main au-dessus du plancher : la
Slice 02 avait noté cette approximation, elle est fermée. Les clics et le
survol, eux, ne sont **pas** encore filtrés par la qualité — l'intention
appartient aux Slices 04 et 05, qui liront `quality` et `stillMs` pour décider.

**Le guetteur de `SLEEP` lit la même qualité que le minuteur d'ACTIVE**, et
c'est une reprise : il ne lisait longtemps que la présence des points. La
décision 7 était donc fermée d'un côté et rouverte de l'autre, et une main que
l'interaction refuse pouvait la **démarrer** — cycle mesuré sur une main de
qualité 0,125 tenant un C à 0,93 : `active` → 30 s → `sleep:idle_sleep` →
réveil une seconde plus tard → sans fin, chaque tour détruisant toutes les
identités, réallouant les fentes de pointeur et émettant deux pastilles. Le
budget d'images (§1) ne bouge pas pour autant : une inférence par
`WAKE_INTERVAL_MS`, plus une mesure de qualité qui ne coûte qu'une boucle sur
les points déjà rendus. En veille la **continuité vaut 1** — aucune piste ne
tourne, il n'y a pas d'identité à mettre en doute, et la seconde de maintien du
C est le témoin de continuité du guetteur. Une main refusée **reste dessinée**,
l'anneau n'avance pas.

Et le changement se **voit** : un jeton sous le plancher se dessine pâle et
pointillé, et la pastille compte les mains crues à part (« MAINS · 1/2 »). Sans
cela, l'utilisateur verrait son jeton, se croirait suivi, et la session
s'endormirait sous ses yeux sans explication.

### `createMotionSample({handTrackId, rawX, rawY, x, y, vxPxPerSec, vyPxPerSec, speedPxPerSec, stillness, stillMs, quality, t})`

→ objet gelé `{schemaVersion, kind:'motion', …}`. La forme nommée que les
Slices 04 à 06 liront, plutôt que dix champs libres — `INTERACTION` a montré ce
que coûte un nom sans forme.

- **Deux positions, pas une.** `rawX`/`rawY` est le point tel que le traqueur
  l'a rendu, `x`/`y` le point **filtré**. Les deux sont nécessaires : la
  calibration mesure le tremblement sur leur écart (`jitterPx`, §10) et le banc
  de rejeu (§12) compare l'erreur de l'un à l'erreur de l'autre. Un filtre dont
  on ne voit que la sortie ne se règle pas.
- `x`/`y` n'est jamais l'ancre de visée que le jeton fige pendant un
  pincement : cet échantillon décrit la main, pas l'affichage.
- **Unités** : positions en **pixels de la fenêtre** (comme `clientX`) ; les
  vitesses portent la leur dans leur nom.
- `stillness` 1 = main posée, 0 = main qui file ; `stillMs` dit **depuis
  quand**. C'est la durée, et non l'instantané, qui distingue un clic d'un
  début de glissement : une vitesse passe sous le seuil une image au milieu
  d'un geste franc.
- Refus : `barehands_motion_invalid`, `barehands_hand_track_id_missing`,
  `barehands_motion_position_missing` — une position absente ne se remplace pas
  par (0,0), le coin de l'écran étant un endroit plausible où une immobilité
  mesurée serait indiscernable d'une vraie.

### Réglages du moteur (Slice 03)

Ils vivent dans `JarvisBarehandsCore.DEFAULTS`, pas dans le contrat : seul le
plancher de qualité est partagé. Ils sont épinglés par
`test_the_controller_states_and_timings_still_match_the_contract` pour la même
raison que `WAKE_INTERVAL_MS` — un défaut que personne n'affirme se mute sans
rien faire tomber. **Changer l'un d'eux, c'est le reporter ici.**

| Réglage | Défaut | Rôle |
|---|---|---|
| `minCutoffHz` | 1,2 | coupure au repos : plus bas = plus calme |
| `betaCutoff` | 0,012 | gain de réactivité : plus haut = moins de retard |
| `dCutoffHz` | 1 | coupure de l'estimation de vitesse |
| `filterResetMs` | 400 | trou au-delà duquel le filtre repart au lieu de croire la vitesse |
| `stillSpeedPx` | 28 | px/s sous lesquels la main est posée |
| `moveSpeedPx` | 420 | px/s au-dessus desquels elle file franchement |
| `matchRadiusPalms` | 1,6 | porte d'appariement, en paumes |
| `predictMs` | 120 | extrapolation bornée de la vitesse d'une piste |
| `trackVelocityBlend` | 0,5 | lissage de cette vitesse |
| `qualityFloor` | 0,25 | recopie de `HAND_QUALITY_FLOOR` |
| `qualityEdge` | 0,04 | bande d'image où le cadrage se dégrade |
| `qualityPalmMin` | 0,06 | paume minimale crédible |
| `qualityComplete` | 0,6 | fraction de points finis en dessous de laquelle la main est devinée |
| `qualityWarmupFrames` | 3 | images consécutives avant qu'une piste soit installée |

`lostGraceMs` (250, antérieur à cette Slice) est devenu la **grâce
d'identité** : c'est lui, et lui seul, qui décide combien de temps une main
perdue reste la même main. L'état par main (pincement, filtre, ancre) vit
exactement aussi longtemps que son identité — une seule horloge au lieu de deux
qui se répondaient à quelques millisecondes près.

C'est **la Slice 08** qui calibre ces nombres, et
`window.JarvisBarehands.diagnostics()` est ce qu'elle lira : les traits du
dernier instant, par main, sous la forme de `createMotionSample`.

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

### Le moteur (Slice 04)

`JarvisBarehandsCore.createGestureEngine(options)` — logique pure, horloge
injectée, aucun DOM. Une image entre
(`{hands:[{handTrackId, landmarks}], now, aspect, captured}`), trois listes
sortent : `events`, `suppressed` et `postures`. Les **liaisons** geste → effet
n'y sont pas : elles appartiennent aux Slices 05 et 06, et c'est ce qui les
garde découplées de la reconnaissance.

La posture en C n'est pas réimplantée : le moteur appelle `cPoseScore`, la
mesure de la Slice 02, avec sa bande effective et son balayage. Une seconde
lecture aurait fait deux jeux de seuils, et la Slice 08 n'aurait pas su lequel
calibrer.

| Geste | Ce qui le distingue | Phases émises |
|---|---|---|
| `c_pose` | `cPoseScore` : écart pouce-index dans la bande, index tendu | `hold` (progression), `start`, `end`, `cancel` |
| `open_palm` | les quatre doigts **tendus** et le pouce au-delà de `wakeGapMax` | idem |
| `fist` | les quatre doigts **repliés** (le pouce n'y entre pas) | idem |
| `double_close` | deux `fist:start` dans `doubleCloseMs` | `end` |
| `clap` | deux paumes à moins de `clapPalms`, **en rapprochement** à `clapSpeedPalms` | `end` |

Trois propriétés qui ne sont pas des réglages heureux mais des exclusions par
construction :

- **poing contre main ouverte** : l'un veut l'extension nulle, l'autre
  l'extension pleine ;
- **C contre main ouverte** : `wakeGapMax` est, par sa propre définition
  (Slice 02), « l'écart où le score du C tombe à zéro côté main ouverte ». La
  main ouverte le relit comme plancher, donc les deux ne peuvent pas être vraies
  ensemble sans qu'un seul nombre bouge ;
- **une main qui pince n'est aucune posture** : si l'un des deux canaux passe
  sous `releaseRatio`, `open_palm` vaut 0, et `c_pose` descend en **rampe** vers
  0 entre `releaseRatio` et `pressRatio` — zéro sous `pressRatio`, c'est-à-dire
  au seuil où le contact entre réellement. C'était un `return 0` sec au-dessus
  de `releaseRatio`, la seule frontière non adoucie du fichier : une main dont
  le pouce passe près du majeur sans rien pincer clignotait 1 ↔ 0 sur le
  tremblement du traqueur, n'aboutissait jamais au maintien d'une seconde, et
  ne disait pas pourquoi. Mesuré sur 1 152 poses en C géométriquement valides,
  la falaise en annulait **167** (un C qui s'ouvre vers le bas) ; la rampe en
  rend 45 au-dessus du seuil de maintien et donne aux 122 autres un score
  gradué. Un pincement secondaire franc reste exactement à 0. Le canal primaire
  était
  déjà couvert par construction (`wakeGapMin` > `releaseRatio`, Slice 02) ; le
  **secondaire ne l'était pas**, et il ne pouvait pas l'être — il pousse le
  pouce *de côté*, pas vers l'index. Mesuré : un clic droit franc laisse l'écart
  pouce-index à 0,72 paume, en plein milieu de la bande du C, donc **un clic
  droit tenu une seconde réveillait la veille** ; le même avec l'index écarté a
  quatre doigts tendus et le pouce au large, c'est-à-dire une main ouverte. La
  garantie est maintenant dite, et `cPoseScore` la porte lui-même pour que le
  guetteur de veille en profite aussi.

Les scores sont des **rampes**, jamais des seuils nus : un doigt à moitié plié
donne un score moyen, donc une posture qui n'aboutit pas, plutôt qu'un geste qui
clignote. `postureHoldMs` finit le travail, et — troisième application de la
leçon de la reprise de la Slice 02 — **le temps non observé ne compte jamais** :
une posture qui apparaît ne crédite pas le temps passé sans elle, et un trou plus
long que `lostGraceMs` la fait recommencer. Une image malformée est **sautée**,
jamais lue comme un relâchement.

### Arbitrage : `GESTURE_RULES`

L'architecture §4 exige qu'« un geste global ne vole pas la main à une
manipulation capturée, **sauf autorisation explicite** ». La table est dans le
contrat — moteur, retour visuel et liaisons doivent lire la même — et se consulte
par `gestureScope(gesture)`, `gestureAllowedDuringCapture(gesture)` et
`isGestureSuppressed(gesture, handTrackId, captured)`.

| Geste | Portée | Permis pendant une capture |
|---|---|---|
| `c_pose` | `hand` | non |
| `open_palm` | `global` | **oui** |
| `fist` | `hand` | non |
| `double_close` | `hand` | non |
| `clap` | `global` | non |

- `global` se tait dès que **n'importe quelle** main tient une capture ;
- `hand` se tait quand **cette** main en tient une, et reste permis pendant que
  l'autre manipule (décision 12 : deux mains indépendantes).

La seule autorisation accordée est la **main ouverte**, et ce n'est pas un cas
d'école : une manipulation qu'on ne peut pas abandonner est un piège, et le geste
universel pour lâcher doit fonctionner exactement quand quelque chose est tenu.
Ouvrir la porte à un autre geste est une décision produit, pas un réglage.

L'arbitrage se décide **à la publication**, pas à la reconnaissance : la posture
garde sa progression pendant la capture, sinon relâcher ferait réapparaître un
geste à moitié construit. Ce qui est étouffé part dans `suppressed` avec sa
raison (`capture_active`) plutôt que de disparaître : un geste qui s'évanouit
sans trace est indiscernable d'un geste non reconnu, et c'est la première
question qu'on se posera.

Depuis la Slice 05, cette raison **arrive à l'écran** : la surimpression écrit
« GESTE IGNORÉ · une main manipule » sous la pastille (`DOM.noteClass`), et une
raison inconnue s'y affiche telle quelle plutôt que d'être remplacée par une
phrase générique — ce nom est la seule information que cette ligne transporte.

**L'arbitrage ne s'applique qu'aux phases qui demandent d'agir.** `start` et
`hold` sont des demandes : les étouffer ne coûte que l'action qui n'a pas eu
lieu. `end` et `cancel` **rendent** quelque chose sur quoi le consommateur a
déjà agi : les étouffer le laisse accroché pour toujours. Mesuré avant
correction : un poing annoncé alors que rien n'était capturé, puis une capture
prise, puis la main ouverte → `fist:end` étouffé et plus rien ensuite ; sur une
perte de main, `fist:cancel` étouffé **et** l'état de la main effacé dans la
foulée, si bien que plus rien ne pouvait corriger. `isGestureSuppressed` ne
connaît pas les phases : elle répond pour `start`/`hold`, et pour la fin des
deux gestes **ponctuels** (`clap`, `double_close`), qui n'ont que celle-là et
dont elle *est* la demande.

> **Invariant.** Tout `start` publié reçoit **exactement une** phase terminale
> (`end` ou `cancel`), et aucune phase terminale n'arrive sans `start`. La
> seconde moitié n'est pas décorative : un `start` étouffé produisait tout de
> même un `end`, et un consommateur qui apparie les deux croyait relâcher ce
> qu'il n'avait jamais pris.

Un geste sans règle dans la table ne lève pas dans la boucle d'images — ce
serait `tracking_failed`, caméra rendue, pour un nom manquant. Il retombe sur
la règle la plus **silencieuse** : portée `global`, aucune autorisation pendant
une capture, donc il ne peut jamais voler la main à une manipulation. Le
contrat, lui, refuse un geste inconnu (`barehands_gesture_unknown`) : c'est la
bonne réponse hors de la boucle, là où le refus se lit.

`captured` est la couture de la **Slice 06**, qui possède les captures ; vide
tant qu'elles n'existent pas, donc rien n'est étouffé aujourd'hui.

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
- `PINCH_INTENT` = `undecided` | `click` | `drag`, porté par l'événement avec
  `travelPx` et `durationMs`. Une intention **inconnue** se refuse
  (`barehands_pinch_intent_unknown`) ; absente, elle vaut `undecided` — jamais
  `click`, qui est une conclusion, pas un défaut. Le clic droit n'y est pas :
  c'est un **canal**, décidé par le doigt (décision 22). Le défilement non plus :
  il dépend de la cible, que la Slice 05 résout et que la Slice 06 consomme — ce
  contrat fournit les ingrédients, pas la conclusion.

### Le moteur (Slice 04)

`JarvisBarehandsCore.createPinchIntentEngine(options)`, deux canaux par main
(`createPinchChannel`), logique pure. Entrée :
`{hands:[{handTrackId, landmarks, x, y, palmX, palmY, anchorX, anchorY,
stillness, quality}], now, aspect}`.

**Ce qui sépare les deux canaux n'est pas un seuil, c'est une marge.** Les deux
se mesurent pareil — du pouce à un bout de doigt, rapporté à la paume — et
partagent donc `pressRatio` / `releaseRatio`. Une main qui se **ferme
entièrement** rapproche le pouce de l'index *et* du majeur : les deux rapports
tombent ensemble sous le seuil, et un moteur qui regarderait chaque canal
isolément lirait un clic droit dans un poing. La **confiance** d'un canal est
donc l'écart qui le sépare de l'autre (`ramp(autre − sien, 0,
pinchMarginRatio)`), nulle quand les deux se valent, et il faut
`pinchConfidenceMin` pour descendre en contact.

**Mais la marge ne peut pas porter cela toute seule**, et la mesure l'a dit :
avec `pinchMarginRatio` à 0,18 le poing du dépôt n'était écarté que de **0,02
paume**, un poing un peu moins serré passait, et le poing le plus courant — le
pouce replié *en travers* de la paume, sans toucher l'index — produisait un
clic droit de confiance **1,0**. Le même nombre, tiré dans l'autre sens,
bloquait un pincement primaire légitime dès que le majeur suivait l'index à
moins de 8°. Deux contraintes contradictoires sur une seule constante.

La fermeture de main entière est donc lue par un **second témoin** :
`handClosure(landmarks, aspect)` = `1 − max(extension des quatre doigts)`, la
même mesure et les mêmes deux constantes (`fingerCurledPalms`,
`fingerExtendedPalms`) que le score `fist` du vocabulaire des gestes — un poing
*est* « tous les doigts repliés », ce n'est pas une coïncidence de seuils. La
confiance est multipliée par `1 − handClosure`.

> **Garantie.** Quatre doigts à `fingerCurledPalms` (1,15 paume du poignet) ou
> en deçà ⇒ confiance **exactement** nulle sur les deux canaux, quelles que
> soient la marge et les deux distances. **Marge :** mesurée à 1,000 sur toute
> la famille des poings (doigts à 0,7 / 0,8 / 0,9 paume, pouce sur l'index comme
> replié en travers) et 0,000 sur tous les pincements francs et sur le C — pleine
> échelle, là où la marge seule offrait 0,02 paume. Un poing devrait lever un
> doigt de 0,9 à plus de 1,15 paume (~22 mm) avant de seulement commencer à
> compter. Et cela ne coûte rien à un vrai pincement : il lui reste au moins un
> doigt tendu.

Libérée de la fermeture, `pinchMarginRatio` ne répond plus qu'à sa vraie
question — **de quel doigt s'agit-il** — et descend à 0,12, soit 0,06 paume
d'écart exigé (~5 mm sur une paume de 90 mm) : au-dessus du tremblement d'un
bout de doigt, en dessous de l'écart qu'un pincement délibéré produit. Sur le
balayage « le majeur suit l'index », tout est admis jusqu'à 3° de séparation,
contre 8° avant.

**Une image malformée se saute par canal, pas par image.** Les deux canaux ne
lisent pas le même bout de doigt (`INDEX_TIP` pour le primaire, `MIDDLE_TIP`
pour le secondaire) : n'en perdre qu'un laissait l'image passer et donnait
`null` au canal aveugle — ce qui faisait retomber son hystérésis à `open` et
**émettait un `up`**. Mesuré : pendant un clic droit, perdre `MIDDLE_TIP` une
seule image produisait `secondary:up intent=click`, or c'est le point le plus
probablement occulté d'un pincement pouce-majeur, le pouce étant devant. Un
canal dont le rapport ne se lit pas ne reçoit rien : son état, son intention et
son contact traversent l'image intacts. `contacts` le publie avec
`ratio: null`.

Un contact ne **commence** ni sur une main que le suivi ne croit pas
(`usableQuality`, décision 7) ni sur une fermeture de main entière. Un contact
**en cours** ne s'interrompt pas pour une note qui baisse : une main qui sort à
moitié du cadre au milieu d'un glissement doit pouvoir le finir. Il ne se termine
que par un relâchement ou par la perte de la main — et la perte donne un
`cancel`, jamais un `up`, sans quoi l'arrêt déclencherait l'action qu'il vient
d'interrompre.

**Quel point porte l'événement** : `approach` et `down` visent l'**ancre** figée
(la cible ne glisse pas sous les doigts au moment de cliquer) ; `move` et `up`
suivent la position **filtrée** (un glissement resté sur l'ancre ne déplacerait
rien).

**Et quel point mesure le déplacement : ni l'un ni l'autre.** `travelPx` se lit
sur `palmX`/`palmY`, le **centre de la paume** en pixels de la fenêtre. Il se
lisait sur le bout de l'index — c'est-à-dire sur le doigt qui *fait* le
pincement primaire, qui parcourt un demi-palme en se refermant sans que la main
ait bougé. Mesuré de bout en bout, main parfaitement immobile, en 1920×1080 :
un pincement textbook marquait **39,4 px** contre un `dragSlopPx` de 26, et
`dragSlopPx` latche `drag` sans retour — `intent: click` était **inatteignable
pour une vraie main**, quelle que soit la taille de la paume, dès que l'index
faisait la moitié de la fermeture. C'est le défaut que la Slice 03 a corrigé une
couche plus haut, dans les mêmes termes : elle ancre l'identité sur le centre de
la paume « parce que l'index parcourt plusieurs paumes pendant un pincement ».
Ici il se lisait comme une main qui glisse, là comme une main qui saute — même
repère, même raison. Le jeton, lui, continue de suivre l'index : c'est ce que
l'utilisateur vise.

Sur le même pincement, le même de bout en bout : `travelPx` 0 à 8,7 px selon la
taille de la paume, `intent: click`, et le chemin de clic hérité
(`createPinchDetector`) continue de produire son clic unique.

`palmX`/`palmY` absents, le moteur retombe sur `x`/`y` : un déplacement
**sur-évalué**, donc un faux `drag`, jamais un faux `click`. Le sens de l'erreur
reste le bon.

**Clic contre glissement** (décision 22), sur les traits que la Slice 03 publie —
jamais sur une dérivée recalculée, la dérivée interne du filtre One Euro lisant
40 px/s sur une main immobile :

- `drag` se tranche **en cours de route**, dès que le déplacement maximal depuis
  la descente franchit `dragSlopPx` : une main qui revient d'où elle est venue a
  tout de même glissé ;
- `click` ne se tranche qu'au **relâchement**, et demande les trois :
  `durationMs ≤ clickMaxMs`, `travelPx ≤ clickSlopPx` et
  `stillness ≥ clickStillnessMin`. Sans le troisième, un geste franc dont le
  pincement se ferme une image au passage se lirait comme un clic.

**Ce que le temps d'établissement de la vitesse coûte au clic.**
`stillness ≥ 0,5` veut dire « vitesse publiée ≤ 224 px/s », et après une
approche à 900 px/s cette vitesse-là met **~250 ms** à retomber sous 224
(§ Temps d'établissement). Donc, mesuré :

| Contact après une approche franche | Verdict |
|---|---|
| relâché moins de ~250 ms après l'arrêt de la main | **`drag`**, même avec 0 px de déplacement |
| relâché entre ~250 ms et `clickMaxMs` après la descente | `click` |

Cette fenêtre est la **seule** contrainte qui reste sur le clic. Elle ne
s'applique qu'après une approche franche : une main déjà posée a `stillness` à 1
et clique en 144 ms, mesuré de bout en bout. Le déplacement, lui, ne bloque plus
rien depuis qu'il se lit sur la paume (§ *Quel point mesure le déplacement*) —
il valait 39,4 px pour 26 autorisés sur une main strictement immobile, et
c'était lui, et non `stillness`, qui rendait le clic inatteignable.

Un clic délibéré **reste possible** — la fenêtre `[~250 ms, 400 ms]` n'est pas
vide — mais un *tapotement* immédiat après un geste rapide est lu comme un
glissement. C'est un faux `drag`, jamais un faux `click` : le sens de l'erreur
est le bon, l'utilisateur voit « rien ne s'est passé » plutôt qu'un clic qu'il
n'a pas demandé. `clickStillnessMin` est le seul nombre qui déplace cette
frontière, et la Slice 08 le calibre devant une caméra réelle : le baisser
élargit la fenêtre du clic et rapproche du faux clic sur un geste franc.

### Réglages du moteur (Slice 04)

Mêmes règles que ceux de la Slice 03 : ils vivent dans
`JarvisBarehandsCore.DEFAULTS`, ils sont épinglés par
`test_the_controller_states_and_timings_still_match_the_contract`, et **changer
l'un d'eux, c'est le reporter ici**.

| Réglage | Défaut | Rôle |
|---|---|---|
| `pinchMarginRatio` | 0,12 | écart entre les deux canaux qui donne la pleine confiance |
| `pinchConfidenceMin` | 0,5 | confiance exigée pour descendre en contact |
| `clickMaxMs` | 400 | au-delà, un contact n'est plus un clic |
| `clickSlopPx` | 12 | déplacement toléré dans un clic |
| `dragSlopPx` | 26 | au-delà, le contact **est** un glissement |
| `clickStillnessMin` | 0,5 | immobilité exigée au relâchement pour conclure à un clic |
| `fingerCurledPalms` | 1,15 | portée en dessous de laquelle un doigt est replié |
| `fingerExtendedPalms` | 1,6 | portée au-dessus de laquelle il est tendu |
| `postureScore` | 0,7 | score minimal pour qu'une posture compte |
| `postureHoldMs` | 250 | durée tenue avant qu'une posture s'annonce |
| `doubleCloseMs` | 600 | écart maximal entre deux fermetures d'un double |
| `clapPalms` | 1,4 | distance des deux centres de paume, en paumes |
| `clapSpeedPalms` | 2,5 | vitesse de rapprochement exigée (paumes/s) |
| `gestureCooldownMs` | 500 | anti-rebond des gestes discrets |

Deux d'entre eux ne sont pas libres, et **les deux se refusent à la
construction** (`RangeError`) : `fingerCurledPalms < fingerExtendedPalms`
(quatrième invariant de paire d'`options()`) et `clickSlopPx <= dragSlopPx`
(cinquième). Le second ne faisait que s'écrire ici : `clickSlopPx` au-dessus de
`dragSlopPx` est **silencieusement tronqué**, puisque le contact est déjà `drag`
quand le test du clic s'exécute — `createPinchIntentEngine({clickSlopPx: 100})`
était accepté et ne changeait rien. C'est la **troisième** apparition de cette
classe de défaut sur cette tâche, après `smoothing` et
`wakeIntervalMs`/`wakeGraceMs` ; l'égalité reste permise, elle ne tronque rien.
La **Slice 08** calibre ces nombres ; `window.JarvisBarehands.gestures()` et
`.pinch()` sont ce qu'elle lira.

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
   il y avait quelque chose à montrer. Côté Slice 05, cette obligation est
   désormais une **porte** et non un classement : le résolveur écarte la
   candidate non actionnable, `targets()` ne la publie donc pas, et l'aperçu la
   refuse aussi. Le classement reste ici pour tout autre appelant de
   `pickRegion`, mais plus rien de non actionnable ne l'atteint par ce chemin.
2. **priorité de région** : coin > bord > corps (`REGION_PRIORITY` = 3/2/1,
   `regionPriority`). Une région hors table vaut 0 et **n'est pas une
   candidate** : `pickRegion` la saute.
3. **la plus proche** (`distancePx`). À distance égale, la première citée
   gagne encore.

`createTargetCandidate({objectId, kind, region, zone, boundsPx, actionable,
representation, distancePx})` → ajoute `axes`. `objectId` est l'identité de la
scène (`data-object-id`) ; aucun élément DOM ne traverse ce contrat.

Elle n'ajoute **pas** de `feedback`, et c'est structurel : le rôle de couleur
dépend du canal (décision 23), qu'une candidate ne porte pas — le canal
appartient à la main, pas à la partie du cadre qu'elle vise. Le champ a existé,
avec la valeur `region === body ? body : zone`, c'est-à-dire une seconde règle
aveugle au canal qui rendait « jaune » là où l'écran affichait « rouge ». Qui
dessine appelle `feedbackRole(region, channel)`.

**Unités.** `boundsPx` et `distancePx` sont en **pixels de la fenêtre**, comme
`clientX` / `clientY` — jamais en unités de scène (±160 × ±90, qui vivent dans
`control_center_scene_interact.js`). Le suffixe est dans le nom pour qu'une
confusion se voie à la lecture, au lieu de se déboguer comme un défaut de
géométrie dans le mauvais module.

`boundsPx` est le cadre de l'**objet entier**, pas celui de la zone : la zone
est entièrement décrite par `region` + `zone`, et sa bande se redérive de ce
cadre (`JarvisBarehandsCore.targetBand`). Deux rectangles pour une même chose
auraient divergé.

`hasManipulationZones(representation)` : seules `capsule` et `window` ont des
zones (décision D3 de la Slice 00) ; `point` et `signal` restent
déplaçables seulement.

Retour visuel (décision 23) par **rôle**, la valeur vivant dans le thème :

| Rôle | Variable CSS | Repli | Sens |
|---|---|---|---|
| `body` | `--bh-feedback-body` | `#6ee7ff` | corps / normal (bleu) |
| `zone` | `--bh-feedback-zone` | `#ffd166` | zone de manipulation (jaune) |
| `secondary` | `--bh-feedback-secondary` | `#ff5d73` | clic droit (rouge) |

`feedbackRole(region, channel)` est la décision 23 entière en une ligne, et
c'est le **canal** qui passe devant la région : un coin visé au pouce-majeur est
rouge, pas jaune, parce que « clic droit » est une intention et non une partie
du cadre. Canal absent = `primary` (règle d'absence) ; canal ou région inconnus
se refusent — une couleur inventée dirait à l'utilisateur qu'il va faire autre
chose que ce qu'il fait.

C'est la **seule** source de la décision 23. `createTargetCandidate` en a porté
une seconde copie, aveugle au canal ; la documentation la désignait comme « le
cas primaire » de `feedbackRole`, ce qui était impossible à tenir puisque la
fabrique ne reçoit pas de canal. Seule la réécriture du champ par l'adaptateur
rendait `targets()` juste ; un consommateur passant par la fabrique — le point
d'entrée documenté — obtenait du jaune pendant que l'écran affichait du rouge.
Le champ est retiré, et l'aperçu redemande le rôle au contrat plutôt que de
retomber sur « bleu » quand il manque.

### Le résolveur (Slice 05)

`JarvisBarehandsCore.createTargetResolver(options)` — logique pure, aucun DOM.
La moitié navigateur (collecte des candidates et dessin) vit dans le **nouveau
module de page** `jarvis/runtime/control_center_barehands_target.js`
(`window.JarvisBarehandsTarget`), inséré **entre** les contrats et le pointeur :

```
…_BAREHANDS_CONTRACTS_JS__ → …_BAREHANDS_TARGET_JS__ → …_BAREHANDS_JS__ → …_SCENE_PAGE_JS__
```

Couverture : `tests/unit/test_barehands_target_js.py`.

**Deux étapes, et l'ordre n'est pas indifférent.**

1. **Quel objet** — le plus proche (`distancePx`), actionnable d'abord, et à
   égalité le premier cité.
2. **Quelle partie** — `pickRegion` sur les candidates de **cet** objet, qui
   sont toutes à la même distance : coin > bord > corps.

La priorité de région ne participe pas au premier choix, et c'est le cœur de la
Slice : « en recouvrement » veut dire *au même point*. Appliquée entre objets,
elle fait gagner le coin d'un cadre situé à 11 px sur le corps du bouton que le
doigt touche réellement — priorité 3 contre 1, la distance n'étant lue qu'en
troisième. Mesuré et épinglé
(`test_priority_settles_an_overlap_inside_one_object_never_between_two`).

Le bloc pur ne peut pas lire le contrat : il ne **réimplante** donc pas la
priorité, il la **reçoit** (`options.pickRegion`), et un résolveur construit
sans elle se refuse plutôt que d'en inventer une seconde.

**Géométrie des zones.** Dedans, les côtés dont on est à moins d'une bande, au
plus un par axe — le plus proche, sinon un point tiendrait « gauche » et
« droite » du même cadre, donc un coin qui n'existe pas. Dehors, les côtés
**franchis**, ce qui donne le bord qu'on approche et le coin quand on approche
en diagonale. Zéro côté = corps. Tout en **pixels de la fenêtre** :
`getBoundingClientRect` fait la conversion une fois, et les unités de scène
n'entrent jamais dans ce chemin.

**`elementFromPoint` participe sans décider.** Il dit seulement quelle candidate
est au-dessus au point visé, et celle-là est citée en tête pour que l'égalité de
distance ne se tranche pas sur l'ordre de création.

**Décision 3, tenue par la structure.** Une main dont aucun canal n'est
`pinching` ou `pressed` n'a **pas de cible** : il n'y a alors aucun élément
d'aperçu dans l'arbre — pas « caché », pas « transparent » : absent. C'est aussi
ce qui paie la performance : la lecture du DOM n'a lieu que sous intention.

La règle vaut aussi pour le **contour hérité** (`DOM.hoverClass`,
`jarvis-hand-hover`), et c'est là qu'elle manquait : il s'ajoutait pour tout
jeton suivi au-dessus d'un élément interactif, sans pincement ni geste, si bien
qu'une main qui traverse la page entourait chaque bouton au passage. La preuve
« aucun élément d'aperçu dans l'arbre » ne parlait que du nouveau mécanisme.
Il suit désormais l'intention — et seulement là où l'aperçu n'entoure pas déjà
l'élément, parce qu'un contour d'accent autour d'un cadre bleu, jaune ou rouge
ajouterait une quatrième couleur à une règle où la couleur *est* le sens
(décision 23). Le chemin du clic — `hovered`, fentes de pointeur,
`pointerover` / `mouseover`, `createPinchDetector` — n'est pas touché : seule la
présentation a changé.

Ce qu'un consommateur reçoit est aussi **actionnable** : voir `pickRegion`
ci-dessus, la décision 3 y est une porte.

**Dynamique jusqu'à la descente, stable ensuite.** Sous contact (`pressed`), le
descripteur est **figé** — objet, région, zone, cadre et nom — quoi que fasse la
main et même si la collecte ne voit plus l'objet. C'est ce que la Slice 06
latche (décision 13) : sans le gel, un glissement de 30 px changerait l'objet
capturé au milieu du geste. Une entrée par main **et par canal** : le gel de
l'un ne gèle pas l'autre.

**Ce que la Slice 06 consomme** : `window.JarvisBarehands.targets()` rend, par
main et par canal, une `createTargetCandidate` (donc `objectId`, `region`,
`zone`, `axes`, `representation`, `boundsPx`, `distancePx`, `actionable`) plus
`handTrackId`, `channel`, `locked` et `feedback`. `createCapture({handTrackId,
channel, state, objectId, region, zone, t})` se construit directement dessus, et
`combineCaptures` prend la suite.

**Métadonnée de composant.** Un objet de scène déclare ce qu'il accepte par
`data-object-id` et `data-representation`, posés par
`control_center_scene_page.js`. La représentation n'est **pas** déduite des
classes : `sc-capsule` est la forme *dessinée*, qui retombe en capsule puis en
point quand la place manque — une fenêtre compacte perdrait alors ses zones sans
que sa géométrie ait changé. Représentation illisible ⇒ corps seul : refuser des
zones qu'on n'a pas su lire échoue du bon côté.

### Réglages du moteur (Slice 05)

Mêmes règles que ceux des Slices 03 et 04 : ils vivent dans
`JarvisBarehandsCore.DEFAULTS`, ils sont épinglés par
`test_the_controller_states_and_timings_still_match_the_contract`, et **changer
l'un d'eux, c'est le reporter ici**. Tous en **pixels de la fenêtre** : une zone
se vise à l'œil, pas à la paume.

| Réglage | Défaut | Rôle |
|---|---|---|
| `targetZonePx` | 14 | bande d'un bord : il faut y **entrer** pour prendre la zone |
| `targetZoneHoldPx` | 20 | bande qui la **garde** (hystérésis) |
| `targetZoneMaxRatio` | 0,3 | la bande **tenue** ne prend jamais plus que cette fraction du petit côté |
| `targetAssistPx` | 24 | portée d'assistance hors du cadre |

**Comment les trois se composent** (`JarvisBarehandsCore.targetBand`) :

```
tenue  = min(targetZoneHoldPx, min(w, h) × targetZoneMaxRatio)
entrée = tenue × (targetZonePx / targetZoneHoldPx)
```

Le plafond proportionnel ne borne que la bande **tenue** : c'est elle qui décide
du corps qui survit à une zone prise, donc c'est elle qui doit tenir dans la
fraction — la garantie « au moins 40 % de corps sur le petit côté » est celle
d'avant, au pixel près. La bande d'entrée s'en déduit en gardant le rapport des
deux réglages, si bien que **l'hystérésis ne peut plus s'annuler** sur un petit
objet.

Les deux bandes étaient auparavant plafonnées séparément par la même fraction,
et rendaient donc le même nombre dès que `0,3 × petit côté ≤ targetZonePx`,
c'est-à-dire sur tout objet de moins de 46,7 px : capsule (24 à 42 px dessinés,
`CAPSULE_MIN_HEIGHT_PX`) et fenêtre compacte (28 px, zonée) avaient une
hystérésis **nulle**, et l'aperçu clignotait entre le bord et le corps sur un
demi-pixel de tremblement. Elle ne survivait que sur les grands objets, là où le
clignotement gêne le moins.

| objet | dessiné | entrée | tenue | hystérésis |
|---|---|---|---|---|
| capsule minimale @1080p | 96×30 | 6,30 | 9,00 | 2,70 |
| capsule par défaut @1080p | 240×42 | 8,82 | 12,60 | 3,78 |
| capsule par défaut @720p | 160×28 | 5,88 | 8,40 | 2,52 |
| fenêtre compacte @1080p | 384×28 | 5,88 | 8,40 | 2,52 |
| fenêtre par défaut @1080p | 384×240 | 14,00 | 20,00 | 6,00 |

La dernière ligne est inchangée : c'était le seul cas où le plafond ne mordait
pas.

Deux relations, et les deux **se refusent à la construction** :

- `targetZonePx <= targetZoneHoldPx` — **quatrième** apparition de cette classe
  de défaut sur cette tâche, après `smoothing`, `wakeIntervalMs`/`wakeGraceMs` et
  `clickSlopPx`/`dragSlopPx`. Inversées, la zone se perd **plus tôt** qu'elle ne
  se prend et l'aperçu clignote précisément là où l'hystérésis existe pour qu'il
  ne clignote pas. Rien ne lève, rien ne tombe, et le symptôme se lit comme un
  tremblement de main. L'égalité reste permise : elle vaut « pas
  d'hystérésis ».
- `0 < targetZoneMaxRatio < 0,5` — à la moitié du côté, les deux bandes opposées
  d'un axe se rejoignent : il n'existe plus un seul point de **corps** dans une
  capsule de 24 px de haut, et la décision 8 devient inatteignable sur l'objet
  le plus courant de la scène.

`assistance` (§ 9, défaut **0,5**) multiplie `targetAssistPx` par `2 ×
assistance` : 0,5 rend exactement la portée par défaut, 0 coupe l'assistance et
1 la double. Le facteur 2 est ce qui fait du défaut des réglages le défaut du
moteur — sans lui, brancher le réglage à la Slice 07 aurait divisé la portée par
deux sans que personne n'ait rien changé.

Décision 24 : `window.JarvisBarehands.targetPreview(bool)` éteint le **dessin**,
pas la résolution — sans cette séparation, couper une aide visuelle couperait
aussi la manipulation. La Slice 07 y branchera `settings.targetPreview`, et
`targetAssistance(value)` à `settings.assistance`.

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

### Le moteur (Slice 06)

`JarvisBarehandsCore.createInteractionEngine(deps)` — logique pure, aucun DOM.
Il tient les captures, coordonne les mains et publie des `INTERACTION` ; la
moitié navigateur (les événements du DOM, et la scène qui tient le cadre) vit
dans le bloc navigateur de `control_center_barehands.js`. Couverture :
`tests/unit/test_barehands_interaction_js.py`.

**Rien n'est réimplanté, tout est injecté.** Le bloc pur est chargé seul par
node et ne peut lire ni les contrats ni la géométrie ; il les **reçoit**, comme
`createTargetResolver` reçoit `pickRegion`, et se refuse (`RangeError`) sans
eux :

| Dépendance | Ce qu'elle apporte |
|---|---|
| `contracts` | `combineCaptures`, `createCapture`, `createInteractionEvent`, `SIDE_AXIS`, `zoneSides`, `INTERACTION` |
| `geometry` | `JarvisSceneInteract` : `manipulateBox`, `rebaseManipulation`, `resizable`, `sameBox` |
| `world` | la scène qui tient le cadre (`window.JarvisScene.frames`) |
| `dom` | la sortie de compatibilité (`scrollable`, `emit`) |
| `slotOf` / `onRelease` | la fente de pointeur de la main ; le relâchement de la cible figée |

**Cycle d'une capture.** Elle s'ouvre sur un `down` de la Slice 04, sur la cible
**figée** de la Slice 05 (décision 13 : sans le gel, un glissement de 30 px
changerait l'objet au milieu du geste) ; elle se ferme sur `up` (l'action
part : clic, contexte, sélection) ou sur `cancel` (rien ne part — la perte n'est
jamais un relâchement court). Une capture par main **et par canal**.

**Rien ne bouge avant que la main ait glissé.** Une manipulation s'arme quand
l'intention du contact devient `drag` — `dragSlopPx` de la Slice 04, mesuré sur
la **paume**, pas un seuil de plus. C'est ce qui garantit qu'un clic sur un bord
ne déplace pas le cadre, et ne l'**épingle** donc pas (toute géométrie de
l'utilisateur épingle, décision 9).

**Trois repères, trois rôles**, et les confondre est le piège de cette couche :
la **paume** (`palmX`/`palmY`) est où la main *est*, donc ce qui déplace un
cadre ; le bout de l'index est ce qu'elle *vise*, donc le pointeur ; l'ancre
figée est ce qu'elle visait à la descente. La phase dit lequel un événement
porte.

**Ce que produit une capture**, selon ce qu'elle tient :

| Ce qui est tenu | Effet |
|---|---|
| une zone, une main | déplacement du cadre entier (décision 10) |
| deux zones compatibles, même objet | redimensionnement contraint (11, 16, 17) |
| le corps d'une capsule ou d'une fenêtre | **contenu** (décision 8) : jamais le cadre |
| le corps d'une étoile `point`/`signal` | déplacement : c'est sa seule prise (D3) |
| canal secondaire | `context` au relâchement, jamais une manipulation (21, 23) |

Seules les captures du canal **primaire** sur un objet identifié entrent dans un
couple. Le corps y entre aussi, et c'est voulu : c'est `combineCaptures` qui doit
dire que corps + zone déplace et que corps + corps ne produit rien. Le filtrer
avant rendrait les décisions 8, 10 et 14 inatteignables et les réécrirait dans le
moteur.

**Chaque motif du contrat est traité**, y compris ceux que le chemin réel
n'atteint pas : `same_hand_twice` écarte la capture du couple (une main ne se
couple pas à elle-même) et la première tient seule ; `object_unidentified` et
`different_objects` laissent les mains indépendantes ; `both_captures_are_body`
ne produit **rien** ; `same_zone_rejected` et `axes_all_neutralized` sont des
**refus**, et un motif inconnu en est un aussi — jamais un silence. Un refus
s'écrit à l'écran, sur la ligne qui porte déjà les gestes étouffés (RÈGLE ZÉRO).

**Rebasage.** À chaque changement de plan — une main qui entre, une main qui se
retire, l'armement lui-même — la référence devient le cadre **tel qu'il est** et
les mains **là où elles sont** (`rebaseManipulation`). La décision 19
(`RESIZE → MOVE`) en est le cas nommé ; le cadre ne saute à aucun des trois.

**Géométrie et unités.** `manipulateBox` est le **seul** endroit où des pixels de
la fenêtre deviennent des unités de scène (`pxToUnits`, `vp.scale` ≈ 6 px/unité
en 1080p). Il reçoit `combineCaptures().axes` tel quel — un axe neutralisé par
la décision 17 n'y est pas, donc il ne bouge pas — et, pour un
redimensionnement, le déplacement de chaque **côté** déjà attribué.
`resizeBySides` borne à `MIN_SIZE`/`MAX_SIZE` et à `SAFE_AREA` : la taille finale
est donc toujours positive, et deux mains qui se croisent s'arrêtent à la taille
minimale au lieu de retourner le cadre (décision 18). `MAX_SIZE` sous `MIN_SIZE`
**se refuse au chargement** du module : `clamp(v, lo, hi)` rend `hi` quand
`lo > hi`, donc le maximum gagnerait et la décision 18 s'inverserait sans un mot.

**Aucun réglage nouveau.** La Slice 06 n'ajoute aucune constante à `DEFAULTS` :
l'armement réutilise `dragSlopPx`, la grâce d'identité `lostGraceMs`, et les
tailles viennent de `MIN_SIZE`/`MAX_SIZE` de la scène.

### La compatibilité DOM (Slice 06)

Architecture § 7 : *ne pas encoder tout le comportement en `PointerEvent`
synthétiques*. Le modèle de manipulation est le sien ; les événements du DOM
restent une sortie de **compatibilité** pour le contenu, là où la page écoute
déjà une souris.

| Interaction | Sortie DOM |
|---|---|
| `click` | **le chemin hérité** (`createPinchDetector`), inchangé |
| `context` | `contextmenu`, bouton 2 |
| `drag_start`/`drag_move`/`drag_end` | `pointerdown`/`move`/`up`, ou `pointercancel` sur annulation |
| `scroll` | défilement **réel** du premier ancêtre défilable, plus un `wheel` |
| `select` | focus et sélection d'un champ ; ailleurs, l'événement sémantique seul |
| `move` / `resize` | **aucune** : la scène les applique par sa couture |

Deux absences volontaires. Le **clic** n'est pas publié en DOM par le moteur :
le détecteur hérité en rend un à chaque relâchement, et l'émettre ici aussi en
enverrait deux. En revanche sa **livraison** attend : une main qui a conduit un
cadre ne clique pas dessus en le relâchant — sans cette porte, tout déplacement
se terminait par un clic sur l'objet qu'on venait de poser. Le détecteur, lui,
n'est pas touché. Et le corps d'une **étoile** n'émet aucune séquence de
pointeur : la page de scène lirait un glissement sur `.sc-node` comme un
déplacement de cadre, c'est-à-dire exactement ce que la décision 8 interdit, par
un autre chemin.

### La couture de la scène (Slice 06)

`window.JarvisScene.frames` (`control_center_scene_page.js`) :
`begin(objectId)` → `{box, representation}` ou `null`, `preview(objectId, box)`,
`commit(objectId, box, mode)`, `cancel(objectId)`, `viewport()`. Elle
**réutilise** ce que la souris utilise — `drawnBox`, `previewAt`, `holdNode`,
`commitUserGeometry` — au lieu d'une seconde géométrie, donc l'épinglage, le
bornage et l'affichage optimiste sont les mêmes des deux côtés. Le pointeur étant
inséré **avant** la page de scène, il la lit à l'appel et non au chargement.
Une souris qui se pose sur un cadre tenu à mains nues **gagne** : la tenue
s'annule, parce que c'est le geste le plus explicite des deux. Une annulation
(main perdue, veille, extinction) rend le cadre à sa place et n'envoie rien, la
même réponse que `pointercancel`.

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
  `HandFrame`. `meta.trackIds` est le crochet par lequel la Slice 03 impose son
  identité persistante — **y compris `0`** ; `createHandTracker().update()`
  rend ces identités sous `trackIds`, alignées sur `result.landmarks`, trous
  compris. Sans elle, la latéralité sert
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
- `adapters.motionFromCoreToken(token)` — jeton de `createHandTracker()` →
  `createMotionSample` (§3 bis). Même rôle que `pointersFromCoreTokens` pour
  l'identité de pointeur : le moteur garde sa forme de travail, le contrat
  possède celle qui traverse les Slices. `x`/`y` prennent la position
  **filtrée** du jeton, pas son `x` d'affichage, qui se fige sur l'ancre
  pendant un pincement.

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

La Slice 03 implante le deuxième moteur : l'identité de main persistante, le
filtrage adaptatif et les traits de mouvement (§3 bis), dans le même fichier
— `createHandTrackManager`, `createPointerFilter`, `createStillness`,
`handQuality`, `createHandTracker` réécrit — couverts par
`tests/unit/test_barehands_tracking_js.py`. Elle **ferme l'approximation de la
décision 7** que la Slice 02 avait dû laisser ouverte : « une main
exploitable » se lit enfin sur une qualité mesurée plutôt que sur la
présence d'un jeton. Aucun module de page n'est ajouté, donc l'ordre
d'insertion (« Insertion dans la page ») est inchangé.

La Slice 04 implante les deux moteurs sémantiques (§4, §5) dans le même
fichier — `handPosture`, `createGestureEngine`, `createPinchChannel`,
`createPinchIntentEngine`, plus `pinchRatioFor` et l'hystérésis partagée
`createContactState` — couverts par `tests/unit/test_barehands_gestures_js.py`.
Elle ne dessine rien et ne lie rien : la Slice 05 possède le retour visuel
(décision 23) et la Slice 06 les actions. Le contrôleur ne les fait tourner
qu'en ACTIVE, le budget d'images de la veille étant un acquis mesuré de la
Slice 02. Aucun module de page n'est ajouté, donc l'ordre d'insertion est
inchangé.

La Slice 06 implante le moteur de captures (§7) : `createInteractionEngine` dans
le bloc pur, la sortie de compatibilité DOM et l'adaptateur de scène dans le bloc
navigateur, la couture `window.JarvisScene.frames` dans la page de scène, et
`resizeBySides` / `manipulateBox` / `rebaseManipulation` dans
`control_center_scene_interact.js` — la géométrie existante étendue, pas une
seconde. Couverte par `tests/unit/test_barehands_interaction_js.py`. Aucun module
de page n'est ajouté ; une dépendance de chargement l'est (voir « Insertion dans
la page »). Aucune constante nouvelle dans `DEFAULTS`.

Restent à venir : outils et réglages, calibration, tutoriel, diagnostics et le
canal de commandes de la voix (Slices 07 à 12).
`window.JarvisBarehands.activate()` / `.sleep()` / `.lifecycle()` sont le point
d'entrée que la Slice 12 branchera, et `.captures()` / `.interactions()` ce que
la Slice 10 lira.
