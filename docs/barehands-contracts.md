# Bare Hands V1 — contrats, schémas et frontière clean-room

**« Bare Hands » (deux mots) est le sous-système natif dont parle ce document.**
« Barehands » (un mot) est le tableau amont AGPL, un processus séparé qui n'a
rien de commun avec lui sauf le nom. La convention est énoncée une seule fois,
dans `docs/ARCHITECTURE.md`, « Two subsystems, one word ». Les identifiants
(`barehands_test_mode`, `/api/barehands`, `JarvisBarehands`) ne la suivent pas
et ne le peuvent pas : la règle porte sur la prose.

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
…_BAREHANDS_CONTRACTS_JS__ → …_BAREHANDS_HAND_ART_JS__
→ …_BAREHANDS_TARGET_JS__
→ …_BAREHANDS_CALIBRATION_JS__
→ …_BAREHANDS_RECORDER_JS__
→ …_BAREHANDS_JS__ → …_BAREHANDS_HUD_JS__
→ …_BAREHANDS_COMMANDS_JS__ → …_SCENE_PAGE_JS__
```

**Huit modules de page, et une seule balise `<script>` pour tout.** La page
servie concatène ces huit-là, les six modules de scène, la chronologie, le Test
Lab et ~2500 lignes de logique de page dans **un** `<script>` : une levée non
rattrapée au chargement d'un module y avorte donc tout ce qui suit, alors que
sous node, où chaque module est un `require()` séparé, elle ne tuait que le
module. Tout refus de chargement est par conséquent **confiné** — la cause part
dans la console sous un nom cherchable, ce module seul reste absent, le reste de
la page vit. Le refus n'est pas adouci, son rayon l'est. Le module qui lève le
plus tôt n'est même pas un module Bare Hands : c'est
`control_center_scene_interact.js`, inséré bien avant, et une levée nue y
blanchissait le Control Center entier.

(`…_BAREHANDS_TUTORIAL_JS__` est arrivé à la Slice 09 et **reparti à la
Slice 07B** : le parcours de tutoriel a été retiré, son module supprimé, son
repère avec. L'enregistreur suit donc désormais directement la calibration.
Voir § 13.)

(`…_BAREHANDS_CALIBRATION_JS__` est arrivé à la Slice 08 : le parcours de
calibration et la coque de surimpression. Il lit les contrats et **se fait
lire** par le pointeur, qui pose `JarvisBarehands.calibrate()` sur sa surface —
et cette surface est **gelée**, donc impossible à compléter après coup. Servi
trop tard, la page casse à l'insertion et non trois clics plus tard, ce qui est
exactement le but.)

(`…_BAREHANDS_COMMANDS_JS__` est arrivé à la Slice 12 : le canal de commandes
du cerveau lit `window.JarvisBarehands`, que le pointeur pose, donc il vient
après lui. Son bloc navigateur **refuse de s'installer** sans cette surface,
pour que l'ordre casse à l'insertion et non trois clics plus tard.)

(`…_BAREHANDS_TARGET_JS__` est arrivé à la Slice 05 : il lit les contrats et se
fait lire par le pointeur, donc il vit exactement entre les deux.)

(`…_BAREHANDS_HAND_ART_JS__` est arrivé avec la carte d'aide : c'est le
vocabulaire de dessin des mains schématiques, § 15 ci-dessous. Il ne lit
**rien** — pas même les contrats — donc son rang n'est contraint que par ses
lecteurs, et ils sont de part et d'autre de la page : la calibration (servie
très tôt) et le contrôle du haut-gauche (servi très tard). Il passe donc en
tête, juste après les contrats, par convention de rangement. Servi trop tard,
c'est la calibration qui casserait à l'insertion.)

(`…_BAREHANDS_HUD_JS__` est arrivé avec le contrôle de cycle de vie de la barre
du haut : il lit `window.JarvisBarehands` **et** la couture de diffusion du
cycle de vie que le pointeur pose dessus, donc il vient après lui. Son bloc
navigateur refuse de s'installer sans l'une ou l'autre, et refuse aussi sans
l'emplacement `#barehandsHud` déclaré dans la page — trois refus nommés plutôt
qu'un contrôle muet ou posé au hasard du `body`. L'ordre est asserté par
`test_barehands_hud_js::test_the_page_serves_the_pointer_before_the_hud_that_subscribes_to_it`.)

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

**On en sort aussi en éteignant**, et il a fallu le dire : `setEnabled(false)`
appelle `controller.disable()` quel que soit l'état de départ. Ce qui protège
« Caméra refusée » d'être écrasé par « Barehands arrêté — caméra libérée » n'est
pas une garde à l'appel, c'est `wasOn = isEngagedState(state)` **dans**
`disable()` : depuis `ERROR` rien n'est tenu, donc `disable()` émet `off` et non
`disabled`, et `off` n'est pas notifié par `onStatus` — aucun toast ne part, et
celui de la panne garde l'écran avec sa cause réelle. Conditionner l'appel
laissait au contraire le contrôleur garé en panne après une extinction
explicitement demandée : interrupteur à faux, écran rouge, c'est-à-dire l'état
courant qui ment pour continuer de décrire un événement passé. Le toast est le
journal de l'événement ; l'état est l'état.

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
| `off` | `sleep` | « Veille » sur le contrôle de la barre du haut (`enable()`), ou `activate()` qui allume d'abord |
| `sleep` | `active` | posture en C tenue `WAKE_HOLD_MS`, ou « Actif » sur le contrôle de la barre du haut (`activate()`) |
| `active` | `sleep` | « Veille » sur le contrôle de la barre du haut (`sleep()`), ou `SLEEP_TIMEOUT_MS` sans main exploitable |
| `sleep` / `active` / `starting` / `error` | `off` | « Éteint » sur le contrôle de la barre du haut (`disable()`), ou `pagehide` |
| `sleep` / `active` / `starting` | `error` | caméra refusée, occupée, coupée, modèle absent, suivi en échec |
| `error` | `sleep` | rallumage explicite depuis le contrôle de la barre du haut |

Allumer mène à `sleep`, jamais directement à `active` : rien n'interagit tant
que l'utilisateur n'a pas réveillé. Le guetteur de `SLEEP` ne lance son
inférence qu'une fois par `wakeIntervalMs` (200 ms, soit 5 images/s) et ne
calcule ni jeton, ni survol, ni clic ; `ACTIVE` suit chaque image.

### Le sélecteur de cycle de vie visible par l'utilisateur

**Le contrôle de la barre du haut est la surface canonique du cycle de vie.**
`control_center_barehands_hud.js` dessine, en haut à gauche de l'écran
principal, un bouton carré de 64 px à icône de main en trait, et ouvre au clic
un sélecteur visuel à trois pastilles — le **même** motif de main, dans ses
trois variantes, directement cliquables. Ce n'est ni une liste déroulante, ni
un cycle aveugle, et ce n'est pas un bouton du `.dock` : le dock reste à
droite, la main est du côté gauche, avec la palette d'outils.

| Présentation | Quand | Rendu |
|---|---|---|
| `off` | `lifecycle === 'off'` | gris fortement atténué, aucun halo |
| `sleep` | `lifecycle === 'sleep'` | bleu Jarvis ordinaire, aucune emphase |
| `active` | `lifecycle === 'active'` | bleu électrique plus clair **et** halo discret. **Pas vert** |
| `starting` | `state === 'starting'` | bleu, bande de progression animée et **compteur de secondes** |
| `error` | `lifecycle === 'error'` | rouge, pastille d'alerte, `code` du motif affiché |

`starting` et `error` ne sont pas des modes sélectionnables : le sélecteur n'y
coche **aucune** pastille. Peindre une caméra refusée ou un démarrage en vol
comme un `off` dirait « l'utilisateur l'a voulu », ce que `ERROR` existe
précisément pour empêcher (§ 1). Le compteur de `starting` est une exigence de
la RÈGLE ZÉRO, pas une décoration : l'attente porte sur `getUserMedia`, donc sur
une invite de permission que rien ne borne, et sans compteur « ça travaille » et
« c'est figé » s'écrivent pareil.

Ce que chaque choix fait, sur les **mêmes portes** que le panneau et que la voix :

| Choix | Appels | Pourquoi |
|---|---|---|
| Éteint | `disable()` | écrit l'interrupteur maître à faux **et** rend la caméra : c'est le seul mode où la posture en C ne peut rien, et le seul qui survive au rechargement. Depuis `ERROR` aussi — voir plus bas |
| Veille | `sleep()` si actif, puis `enable()` **s'il reste quelque chose à faire** | `enable()` ne fait pas sortir d'`ACTIVE`, donc `sleep()` d'abord. `enable()` fait deux choses — écrire le maître et armer le guetteur — et n'est appelé que si l'une au moins manque : maître vrai **et** moteur vivant, il n'y a rien à écrire ; maître vrai mais moteur éteint (panne, démarrage avorté), il faut rarmer, et c'est le seul chemin public qui le fasse |
| Actif | `activate()`, puis `enable()` **si le maître est faux et que l'allumage a tenu** | `activate()` porte la chaîne entière (allumer, guetter, réveiller) en une attente ; `enable()` vient **après**, sans quoi il laisserait le contrôleur en `starting`, où `activate()` n'a rien à réveiller. Là il n'est plus que de la persistance : un allumage qui vient d'échouer ne s'enregistre pas comme un souhait exaucé, et le réécrire relancerait un second démarrage pour la même panne |

Aucun de ces chemins n'écrit un réglage qui ne changerait rien : une écriture
par clic n'est pas une garantie de plus, c'est un aller-retour serveur. La garde
se lit sur le **dernier instantané de la couture** — l'autorité — jamais sur une
copie tenue par le contrôle.

Le contrôle **ne tient aucun cycle de vie** : pas de variable d'état, pas
d'optimisme local. Une seconde mémoire ici est la dérive que la décision 7
interdit — un réveil en C, un retour en veille après 30 s ou une caméra refusée
changeraient l'état sans que le bouton le sache.

### Les quatre actions rapides du clic droit (décisions 8 à 10, Slice 02)

Le **même** bouton porte, au clic droit, les quatre destinations secondaires de
Bare Hands — et rien d'autre :

| Entrée | Porte appelée | Note |
|---|---|---|
| Réglages… | `JarvisBarehands.showSettings()` | ouvre l'onglet Expérimental |
| Calibrer… | `JarvisBarehands.calibrate()` | la porte du bouton **et** de la voix, inchangée |
| Aide · Gestes… | `JarvisBarehands.showHelp()` | crochet stable ; la Slice 04 en remplace le corps par la carte visuelle de la décision 15 |
| Diagnostic… | `JarvisBarehands.showDiagnostics()` | ouvre la **surface** d'enregistrement (§ 14) ; ni la sémantique ni la rétention ne changent |

**Deux absences font partie du contrat.** Aucune entrée d'activation ou de mode
(décision 9) : le cycle de vie appartient au clic gauche, et deux commandes pour
un même état finiraient par se contredire. Aucune entrée Tutoriel (décision 10) :
le parcours séparé cesse d'être une destination, la calibration enseigne
(décision 17).

Le menu n'est pas fabriqué par le module : `control_center.html` en possède un
seul, partagé (`.ctxmenu`, rang 80, au-dessus du sélecteur de mode qui est à 36),
et ce contrôle en devient un consommateur de plus par son point d'échappement
`run(act)`. `showMenu` et `closeMenu` sont **injectés** comme la surface et
l'horloge ; absents, le clic droit refuse sous `barehands_hud_menu_missing` et
le dit à l'écran, mais le bouton s'installe quand même — perdre les actions
rapides est moins grave que perdre le cycle de vie (décision 1).

**Équivalent clavier obligatoire** : la touche Menu et Maj+F10 sur le bouton
ouvrent le même menu, aux mêmes entrées. Comme la touche Menu produit *aussi* un
`contextmenu` dans les navigateurs, une garde de 700 ms — locale à ce contrôle,
sur le modèle des cartes d'agents — empêche l'ouverture double.

Une entrée qui ne se choisit pas **dit pourquoi** : elle porte sa raison dans son
libellé et se marque `aria-disabled` plutôt que `disabled`, pour rester
atteignable au clavier — un bouton réellement désarmé n'est jamais lu par un
lecteur d'écran, donc sa raison ne l'est pas non plus. Deux des trois refus de
`startCalibration` sont connaissables d'avance et sont affichés sous leur code du
moteur — `barehands_calibration_disabled` pour le réglage décoché,
`barehands_calibration_lifecycle_off` pour Bare Hands éteint ; le troisième,
`barehands_calibration_no_camera`, ne l'est **pas** et reste un refus à
l'exécution, parce que depuis une panne `activate()` peut parfaitement reprendre
la caméra et que griser l'entrée dirait « ça ne marchera pas » là où la vérité
est « il faut essayer pour savoir ».

### Ce que l'onglet Expérimental n'est plus (décision 14, Slice 02)

L'onglet est de la **configuration**, pas un tableau de bord d'interaction.
Trois blocs en sont sortis et ne doivent pas y revenir :

| Sorti | Où c'est désormais | Ce qui reste stocké |
|---|---|---|
| interrupteur maître `#f_barehands` et bandeau `#barehandsLifecycle` | le contrôle de la barre du haut (décision 1) | `enabled` — écrit, relu, normalisé |
| section **Outils** `#barehandsTools` | la palette de gauche de la Slice 03 | `tool` — `JarvisBarehands.tool()` inchangé |
| section **Tutoriel** `#barehandsTutorial` | rien : la calibration enseigne (décisions 10 et 17) | `tutorial_seen` — champ de compatibilité, § 13 |
| case **« Tutoriel déjà vu »** `#bh_tutorialSeen` (Slice 07B) | rien : le parcours qu'elle cochait n'existe plus | `tutorial_seen` — persisté, plus écrit |

**La propriété de l'écran a changé de main ; celle de la donnée, non.**
`SCHEMA_VERSION = 2` de `barehands_test_mode.py` ne bouge pas, les trois champs
restent écrits et relus. La migration de la commande `tutorial` a été faite à
la **Slice 07B** : alias déprécié vers la calibration, § 13. Ce qui reste dans
l'onglet : l'état, les assets, la dernière commande vocale, les six réglages
encore dessinés, la calibration et l'enregistrement de diagnostic.

Les sections que le menu sait viser sont nommées une seule fois, dans `SECTION`
de `control_center_barehands.js`, et publiées sur la surface gelée : un appelant
désigne une section par sa clé, jamais par un identifiant HTML recopié.

### La couture de diffusion du cycle de vie

`onStatus` est le seul point par lequel **toutes** les transitions passent :
l'écran, la voix et le canal MCP (qui appellent les mêmes portes), le réveil en
C dans la boucle d'images, le retour en veille après `SLEEP_TIMEOUT_MS`, la
panne et la reprise, l'arrêt au déchargement. Jusqu'ici elles n'atteignaient
l'écran que par `refreshPanel()`, qui ne peint **que l'onglet Expérimental
ouvert** : un contrôle vivant hors du modal n'avait rien à quoi se lier.

La surface gelée porte donc, sur le modèle exact de la couture de mesures
(§ 14) :

- `openLifecycleSeam(nom, consommateur)` — inscrit un consommateur sous un nom,
  et lui remet l'instantané **courant tout de suite**. Sans ce rejeu, un
  contrôle installé après la dernière transition partirait d'un état d'usine
  jusqu'à la suivante — c'est-à-dire, au rechargement, indéfiniment. Un
  consommateur qui n'est pas une fonction est refusé
  (`barehands_lifecycle_seam_invalid`) ;
- `closeLifecycleSeam(nom)` — retire ce nom-là, et seulement lui ;
- `lifecycleSeam()` — **qui** écoute. Sans lecture, « le bouton écoute » et
  « quelqu'un l'a effacé » s'écrivent pareil ;
- `lifecycleStatus()` — l'instantané, lisible sans s'abonner.

L'instantané porte `lifecycle`, `state`, `starting`, `code`, `title`,
`message`, `enabled` et `busy`. `starting` s'y dit explicitement parce que
`LIFECYCLE` ne le nomme pas et n'a pas à le nommer (§ 1) : le publier ici évite
que chaque abonné redécouvre un nom du moteur hors du moteur. Un instantané
identique au précédent **ne se republie pas** : `refreshPanel` est appelé par
des chemins qui ne touchent pas au cycle de vie (un curseur qu'on tire), et un
abonné ne doit pas avoir à distinguer « ça a changé » de « on a repeint ». Un
consommateur qui lève est journalisé et sauté ; il n'emporte ni l'autre, ni le
rafraîchissement du panneau.

### La couture de diffusion de l'outil courant (Slice 03)

Une **seconde** couture, et non un champ de plus dans la première. L'outil
n'est pas du cycle de vie : le contrat le range dans les réglages (§ 8), la
Slice 03 le dit mot pour mot — « le choix d'outil est une intention de session,
pas un cycle de vie » — et le canal de commandes refuse justement de router
`tool` avec les transitions (§ 12). Les fondre aurait fait repeindre le bouton
de cycle de vie à chaque changement d'outil et, pire, aurait fait de « l'outil
a changé » un événement de cycle de vie que le prochain lecteur croirait
autoritaire.

Elle publie **un seul fait** : `{tool}`, l'outil que les réglages appliquent.
Tout le reste — installé ou non, libellé, capacité — appartient au contrat et
se lit chez lui (`describeTools()`), jamais recopié dans un instantané qui
dériverait. La disponibilité (`busy`, `lifecycle`) voyage déjà sur la couture
de cycle de vie ; un abonné qui a besoin des deux **ouvre les deux**, ce qui
est exact plutôt que commode — c'est ce que fait la palette.

- `openToolSeam(nom, consommateur)` — inscrit sous un nom et rejoue
  l'instantané courant tout de suite. Sans ce rejeu, la palette afficherait
  « pointeur » jusqu'au premier changement, c'est-à-dire mentirait sur un
  réglage persisté à chaque rechargement. Un consommateur qui n'est pas une
  fonction est refusé (`barehands_tool_seam_invalid`) ;
- `closeToolSeam(nom)`, `toolSeam()`, `toolStatus()` — mêmes rôles et mêmes
  raisons que leurs homologues du cycle de vie.

`publishTools()` est appelé dans `refreshPanel()`, **juste après**
`publishLifecycle()` et **avant** le garde-fou `SET.open` : tout ce qui change
l'outil — `saveSettings` (l'écran, la palette, la console, la voix) et
`applyServerState` (le chargement, la réponse du serveur) — y finit, et publier
après le garde-fou n'aurait atteint la palette que l'onglet Expérimental
ouvert, c'est-à-dire précisément jamais. Même déduplication, même confinement
des levées : un consommateur qui lève est journalisé et sauté, sans emporter
son voisin ni le rafraîchissement du panneau.

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
- `x`/`y` n'est jamais le point de visée que le jeton reporte pendant un
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

**Le jeton pendant un pincement : reporté, plus gelé.** Le point d'affichage
(`x`/`y` du jeton) se détachait du bout de l'index dès l'approche — il le faut,
l'index parcourt un demi-palme rien qu'en se refermant — mais il se **gelait**
jusqu'au relâchement. Le clic tombait bien ; tout ce qui dure plus qu'un clic
mentait à l'écran. Une main qui emportait un cadre laissait son curseur planté à
l'endroit de la prise, puis celui-ci sautait au relâchement, là où le doigt
venait de rouvrir — cent pixels et plus, lus par l'utilisateur comme « la
fenêtre ne se pose pas où je l'ai lâchée ».

Le jeton vaut donc `ancre + (paume − paume à l'ancrage)` : le même vecteur que
celui que la Slice 06 applique au cadre (`manipulate`, ancres reconstruites sur
les paumes), pris sur la paume **brute**, comme celle que le moteur reçoit. Le
curseur et ce qu'il tient ne se décollent plus, et une main immobile ne bouge
toujours pas d'un pixel — une paume ne se referme pas.

Et l'**ancre est le dernier point visé avant que les doigts ne commencent à se
refermer**, pas le premier que le détecteur appelle `pinching` : à cet
instant-là, l'index est déjà à mi-chemin du pouce. « Avant la fermeture » se lit
sur le rapport de pincement lui-même — tant qu'il ne descend pas (à
`AIM_SETTLE_RATIO`, 0,02 paume, près, pour le tremblement), la main pointe et le
point de visée se met à jour. La boucle se referme ainsi d'elle-même : départ et
arrivée sont la même posture de doigt, donc il n'y a plus rien à rattraper au
relâchement. Une main vue **déjà** en train de pincer n'a pas de point de visée
d'avant et garde le comportement antérieur, le seul disponible.

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
`{hands:[{handTrackId, landmarks, worldLandmarks, x, y, palmX, palmY, anchorX,
anchorY, stillness, quality}], now, aspect}` — `worldLandmarks` (les points 3D de
MediaPipe, en mètres) est facultatif.

**Faux contacts devant le visage ou le torse.** Le suivi de la main y reste bon,
mais les bouts de doigt y mentent : le rapport image se lit sur une
**projection**, et une information *présente mais fausse* était crue là où une
information *absente* était déjà traitée avec prudence. Trois règles :

- **Relâchement confirmé.** Un contact tenu ne tombe plus sur une seule image au
  dessus de `releaseRatio` : il faut `releaseFrames` (2) observations d'affilée
  couvrant `releaseMs` (60 ms). Durée, déplacement et immobilité du geste sont
  lus à la **première** image ouverte : la confirmation n'allonge pas le contact
  et ne change pas le verdict clic/glissement. Elle ne déplace pas non plus le
  cadre tenu (22/09/2026) : le canal publie `releasing` dans ses contacts, et le
  moteur d'interaction garde, pour la main qui s'ouvre, la paume de sa dernière
  image **pincée** — la main qui s'ouvre et se retire n'emporte plus le cadre à
  côté de là où on l'a vu en lâchant. Si le pincement revient, la main reprend
  là où elle est.
- **Doute gelé.** Pendant un contact, une image dont la qualité de suivi passe
  sous le plancher ne vaut ni pour ni contre le relâchement — dans la limite de
  `releaseDoubtMaxMs` (400 ms) de doute continu, au-delà de laquelle les
  observations comptent de nouveau.
- **Veto de profondeur.** Quand `worldLandmarks` est fourni, le même rapport relu
  en 3D (`worldPinchRatioFor`) au-dessus de `worldVetoRatio` (0,5 — une
  demi-paume, ~4 cm) empêche un contact de **commencer**. Veto seulement, à
  l'entrée seulement : la profondeur est elle-même estimée. `0` le coupe.
  Réglage d'usine à confirmer sur des traces réelles (`primaryWorldRatio`).

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

**Quel point porte l'événement** : `approach` et `down` visent l'**ancre** (la
cible ne glisse pas sous les doigts au moment de cliquer) ; `move` et `up`
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
taille de la paume, `intent: click`. Le détecteur hérité (`createPinchDetector`)
mesure toujours l'entrée du contact, mais ne livre plus de clic (voir « La
compatibilité DOM »).

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

**Décision 3 bis : savoir ce qu'on vise avant de le prendre.** La règle ci-dessus
refusait un curseur permanent, et elle a raison ; elle interdisait aussi, sans le
vouloir, la seule question qu'une main nue ne peut pas résoudre autrement :
*suis-je sur le bord, ou dans le corps ?* Les deux prises ne font pas la même
chose (décisions 8 à 11), elles sont séparées par quatorze pixels, et rien ne les
distinguait tant que les doigts n'avaient pas commencé à se refermer — trop tard
pour corriger sa visée. Le résolveur accepte donc un troisième état de main,
`hover`, qui se résout comme une visée (même géométrie, même hystérésis de zone)
mais ne se latche jamais (`locked` reste faux).

Trois bornes le gardent honnête, et c'est ce qui laisse la décision 3 vraie là où
elle visait :

- il n'est demandé que pour le canal **primaire** — le secondaire est une
  intention de clic droit, pas une visée ;
- seul ce qui a des **zones de manipulation** (capsule, fenêtre) le reçoit : un
  bouton, un lien, un champ survolés ne dessinent toujours rien, et le contour
  hérité continue de les souligner sous intention ;
- il ne va **qu'au dessin**. `targets()` — ce que la Slice 06 ouvre en capture, ce
  que la Slice 09 mesure, ce que la Slice 10 enregistre — reste vide hors
  intention. Les confondre aurait fait compter un cadre survolé pour une cible
  atteinte dans le taux de clics visés.

Le coût est borné par le même raisonnement : la collecte se sépare en un
**balayage** (`survey`, la lecture d'arbre) et un **filtrage par point** (`near`,
de l'arithmétique). Sous intention, les deux sont refaits à chaque image ; en
survol, le balayage est échantillonné (90 ms) et seul le filtrage suit la main —
hors intention, aucune manipulation n'est en cours, donc aucun cadre ne bouge
qu'un balayage de 90 ms raterait. L'aperçu de survol est dessiné à voix basse
(`data-hover="1"`), la visée sous intention à pleine intensité.

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
descripteur est **figé** — objet, région, zone et nom — quoi que fasse la main et
même si la collecte ne voit plus l'objet. C'est ce que la Slice 06 latche
(décision 13) : sans le gel, un glissement de 30 px changerait l'objet capturé au
milieu du geste. Une entrée par main **et par canal** : le gel de l'un ne gèle
pas l'autre.

**Décision 3 ter : le surlignage est un enfant de ce qu'il surligne.**
`boundsPx` n'est pas un descripteur — c'est *où l'objet est*, et l'objet, pendant
la prise, est justement en train de bouger. Figé avec le reste, le cadre jaune
restait planté à l'endroit de la saisie pendant que la fenêtre partait ailleurs.

La première correction a été de relire le rectangle de l'élément à chaque image.
Elle marchait, et elle était **fausse de structure** : deux objets dont l'un
mesure l'autre. L'aperçu est dessiné au début de l'image, la manipulation est
appliquée à la fin — le cadre porte donc toujours la position d'avant, une image
de retard, quelle que soit la finesse du suivi. Et il ne sait rien de ce que le
navigateur fait sans lui : `.sc-node` glisse en 420 ms (`transition:transform`)
et tourne sur son orbite (`animation`) ; un poursuivant verrait ces deux-là
comme une suite de sauts.

Le cadre est donc **un enfant du nœud qu'il surligne**, collé à ses quatre bords
(`inset:0`), et il n'écrit plus une seule coordonnée. Le parent porte la
position, la taille, sa transition et son orbite ; l'enfant les reçoit dans la
même peinture, exactement comme le titre d'une fenêtre suit la fenêtre. La barre
de zone suit la même règle : elle est posée par **insets** (« collée à droite,
du haut au bas, épaisse de la bande ») et non par un `left` calculé, si bien
qu'elle reste sur le bord tenu pendant qu'on l'étire. Visuellement l'aperçu est
au-dessus de l'objet ; hiérarchiquement il est dedans.

Trois conséquences, et chacune est un choix :

- **La feuille de style n'est plus portée par `#jarvisHands`.** Un cadre
  imbriqué vit sous la scène, hors de la surimpression : une règle qui
  commencerait par la racine ne l'atteindrait plus — elle ne serait pas moins
  précise, elle serait sans effet. Les classes `jh-` suffisent, elles sont à
  nous.
- **Le nœud visé passe devant ses frères** (`.sc-node:has(> .jh-target:not([data-hover="1"]))`),
  parce qu'un objet dont un voisin recouvre le bord ne répond pas à la question
  qu'on lui pose. Un objet seulement **survolé** ne bouge pas d'un cran : une
  main qui traverse la scène ferait sinon passer devant tout ce qu'elle croise.
  `!important`, parce que le placement de la scène écrit `z-index` en ligne à
  chaque rendu.
- **L'étiquette se pose dans le cadre** quand il est imbriqué : une fenêtre et
  une capsule coupent ce qui dépasse (`overflow:hidden`), et un nom invisible
  est, pour l'utilisateur, une cible sans nom. Sous 22 px de haut elle n'est pas
  dessinée du tout — elle recouvrirait la cible au lieu de la nommer.

**Ce qui ne peut pas porter son cadre** le garde dans la surimpression, positionné
comme avant : un élément remplacé ou vide (`input`, `select`, une image) n'a pas
d'enfants, et un élément `position:static` ferait résoudre `inset:0` contre un
tout autre ancêtre — le cadre ne serait pas en retard, il serait ailleurs. Ce
repli est sans conséquence parce qu'il couvre exactement les cibles qui **ne
bougent pas** sous la main : on ne déplace pas un bouton, on le clique. Ce qu'une
main nue déplace ou étire est un nœud de scène, et un nœud de scène est
`position:absolute`. Si cela cessait d'être vrai, le module le **dit** une fois à
la console plutôt que de laisser le retard revenir en silence.

La relecture du rectangle reste, mais elle a changé de rôle : elle n'est plus ce
qui fait suivre le cadre, seulement ce qui garde `boundsPx` honnête pour le repli
et pour ce que `targets()` publie. Un élément disparu du dessin rend un rectangle
vide : on garde alors le **dernier mesuré**, jamais celui de la prise — une
fenêtre qui disparaît au milieu d'un déplacement laisserait sinon son cadre
revenir d'un bond là où la main l'avait saisie.

Le ré-attachement, lui, se vérifie à chaque image : la scène réécrit le contenu
d'un nœud (`el.replaceChildren()` dans son `fill`) dès qu'un titre ou un état
d'exécution change, et emporte l'enfant avec. C'est un `parentNode !==` par
image, et c'est ce qui rend l'imbrication réparable au lieu de fragile — le cadre
revient tout seul à l'image suivante.

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

**Mais le seuil dit *si* la main glisse, jamais *de combien*.** Le plan s'ancrait
sur les paumes de l'image où il s'ouvre, c'est-à-dire après que le seuil eut été
franchi : les vingt-six pixels (et davantage si la main est partie vite) étaient
perdus pour de bon, le curseur devançait le cadre de cette distance-là pendant
tout le geste, et le cadre se posait en arrière de la main qui le lâchait. Le
premier ancrage lit donc la paume **à la descente** (`downPalm`, relevée à
l'ouverture de la capture) et le cadre rattrape sa course à l'image où il s'arme
— ce que fait une souris depuis toujours.

La condition sur l'image compte autant que la paume : un plan qui s'ouvre
**longtemps** après l'armement — la prise avait d'abord été refusée, la fenêtre
n'était pas mesurable, l'objet n'était pas dessiné — commence là où la main est.
La main a voyagé pendant ce refus, et lui rendre cette course téléporterait le
cadre. Seul le plan qui s'ouvre *sur l'image même de l'armement*
(`armedFrame === frameIndex`) reçoit sa descente ; tous les autres ancrages sont
ceux de la décision 19.

**Trois repères, trois rôles**, et les confondre est le piège de cette couche :
la **paume** (`palmX`/`palmY`) est où la main *est*, donc ce qui déplace un
cadre ; le bout de l'index est ce qu'elle *vise*, donc le pointeur ; l'ancre est
ce qu'elle visait avant de se refermer, reportée sur la paume (§3). La phase dit
lequel un événement porte.

**Ce que produit une capture**, selon ce qu'elle tient :

| Ce qui est tenu | Effet |
|---|---|
| une zone, une main | déplacement du cadre entier (décision 10) |
| deux zones compatibles, même objet | redimensionnement contraint (11, 16, 17) |
| le corps d'une capsule ou d'une fenêtre | **contenu** (décision 8) : jamais le cadre |
| le corps d'une étoile `point`/`signal` | déplacement : c'est sa seule prise (D3) |
| deux corps sur une étoile `point`/`signal` | la **première** main continue ; la seconde est un refus |
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
ne produit **rien sur une capsule ou une fenêtre** — chaque main y fait son
interaction de contenu — mais sur une étoile `point`/`signal`, dont le corps
n'est pas du contenu mais sa seule prise, la **première** main (la plus ancienne
à la descente) continue de la déplacer et la seconde est refusée
(`star_moves_with_one_hand`) : geler le geste en cours punirait la main qui
avait raison, et le figer sans un mot était indiscernable d'une panne ;
`same_zone_rejected` et `axes_all_neutralized` sont des **refus**, et un motif
inconnu en est un aussi — jamais un silence. Un refus s'écrit à l'écran, sur la
ligne qui porte déjà les gestes étouffés (RÈGLE ZÉRO).

Quatre refus sont **du moteur** et non du contrat : `object_not_drawn` (rien à
tenir dans la scène), `frame_not_resizable` (décision D3),
`viewport_unavailable` (la fenêtre de la scène ne se mesure pas — sans elle,
`pxToUnits` retomberait à 1:1, soit six fois trop de course, en silence) et
`side_held_twice` (l'invariant des décisions 16/17, qui **se dit et se saute**
au lieu de terminer la session). S'y ajoute `target_not_actionable`, une
défense en profondeur : le résolveur de la Slice 05 est la porte de la décision
3 et ne publie plus rien de non actionnable, mais ce moteur est injectable et ne
suppose pas son appelant.

**Rebasage, et ses deux déclencheurs.** À chaque changement de plan — une main
qui entre, une main qui se retire, l'armement lui-même, une main re-détectée
sous une **autre** identité de piste — la référence devient le cadre **tel qu'il
est** et les mains **là où elles sont** (`rebaseManipulation`). La décision 19
(`RESIZE → MOVE`) en est le cas nommé ; le cadre ne saute à aucun.

Le second déclencheur est ce que la signature (`mode | axes | qui tient quels
côtés`) ne peut pas voir : **un plan qui n'a pas tourné à l'image précédente**.
Un plan survit à ses suspensions — une prise refusée (`same_zone_rejected`,
`axes_all_neutralized`, `frame_not_resizable`, `viewport_unavailable`,
`side_held_twice`), et surtout une main que le suivi perd le temps d'un
clignement puis retrouve **sous le même identifiant**, ailleurs. La main, elle,
continue de voyager ; sans rebasage à la reprise, tout ce voyage s'appliquait en
une image (mesuré : 68 unités pour un clignement de trois images). Le plan porte
donc le **numéro de l'image** où il a conduit pour la dernière fois, et un trou
vaut un changement de signature.

**Toutes les mains du couple, ou aucune.** Une main sans paume à cette image
(un trou du suivi, pas un relâchement : la capture vit jusqu'à `lostGraceMs`) ne
laisse pas l'autre tirer seule. Son côté ferait sinon office d'ancre — le cadre
se redimensionnait de travers pendant le clignement — et publier pour une main
sans paume posait `barehands_interaction_invalid`, mot pour mot, à l'écran. La
manipulation **se suspend** pour cette image, en silence (un trou d'une image ne
mérite pas une ligne qui clignote), et reprend rebasée.

**Géométrie et unités.** `manipulateBox` est le **seul** endroit où des pixels de
la fenêtre deviennent des unités de scène (`pxToUnits`, `vp.scale` ≈ 6 px/unité
en 1080p). Il reçoit `combineCaptures().axes` tel quel — un axe neutralisé par
la décision 17 n'y est pas, donc il ne bouge pas — et, pour un
redimensionnement, le déplacement de chaque **côté** déjà attribué.
`resizeBySides` borne à `MIN_SIZE`/`MAX_SIZE` : la taille finale est donc
toujours positive, et deux mains qui se croisent s'arrêtent à la taille minimale
au lieu de retourner le cadre (décision 18). Il ne connaît plus de bord (22/09/2026) :
l'écran visible et les commandes de la page sont les bords de la **tenue** de la
scène (`JarvisSceneInteract.createHold`), communs à la souris, à la main et au
clavier — la zone sûre, calibrée pour 1280 × 720, n'en est plus un. `MAX_SIZE` sous `MIN_SIZE`
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
| `click` | `pointerdown`/`mousedown`/`pointerup`/`mouseup`/`click` sur l'élément sous le **point visé à la descente**, livré après l'image |
| `context` | `contextmenu`, bouton 2 |
| `drag_start`/`drag_move`/`drag_end` | `pointerdown`/`move`/`up`, ou `pointercancel` sur annulation |
| `scroll` | défilement **réel** du premier ancêtre défilable, plus un `wheel` |
| `select` | focus et sélection d'un champ ; ailleurs, l'événement sémantique seul |
| `move` / `resize` | **aucune** : la scène les applique par sa couture |

**Le clic n'a qu'une source : le moteur d'intention.** Le détecteur hérité
(`createPinchDetector`) cliquait à l'**entrée** du contact, sur le rapport brut —
sans qualité de suivi, sans rejet du poing, sans marge entre canaux — si bien que
deux images d'un pouce frôlant l'index devant le visage suffisaient, et que
chaque prise commençait par un clic sur ce qu'elle saisissait. Il reste mesuré
(`token.click`), jamais livré. `CLICK` part au **relâchement** d'une capture qui
n'a ni conduit un cadre ni glissé (`armed` : le glissement que le canal décide en
cours de route sur la course de la paume), au point visé à la descente — au
relâchement, le point filtré suit l'index qui se rouvre. L'adaptateur le range
(`takeClicks`) et le contrôleur le livre après l'image, pour qu'un clic qui
éteint Bare Hands n'interrompe pas une image à moitié traitée. Une zone refusée
qui a glissé ne clique donc plus. Et le corps d'une **étoile** n'émet aucune séquence de
pointeur : la page de scène lirait un glissement sur `.sc-node` comme un
déplacement de cadre, c'est-à-dire exactement ce que la décision 8 interdit, par
un autre chemin.

### La couture de la scène (Slice 06)

`window.JarvisScene.frames` (`control_center_scene_page.js`) :
`begin(objectId)` → `{box, representation}` ou `null`,
`preview(objectId, box, mode)`, `commit(objectId, box, mode)`,
`cancel(objectId)`, `viewport()`. Elle tient le cadre par **la même tenue que la
souris et le clavier** (le bureau des tenues
`JarvisSceneInteract.createHoldDesk` : `take`, `to`, `drop`, `cancel`) au lieu
d'une seconde géométrie, donc l'épinglage, les
bords, l'objet figé pendant la tenue et l'affichage optimiste sont les mêmes partout.

**Les boîtes de la couture sont dans le repère du dessin** (22/09/2026). `begin`
rend la boîte telle qu'elle est **dessinée** à la prise — tour et ampleur de
l'orbite compris —, celle que la main voit et saisit ; le moteur calcule dedans
(`manipulateBox`), et `preview`/`commit` reçoivent des boîtes de ce même repère.
C'est la page qui en déduit, au lâcher, la place à enregistrer
(`JarvisSceneLayout.holdPlace` : le tour défait). Avant, `begin` rendait la place
enregistrée et `commit` l'enregistrait telle quelle : l'objet sautait de 300 à
400 px au lâcher, en miroir du geste. `mode` accompagne `preview` parce qu'un
déplacement (la tenue glisse d'un bloc le long d'un bord) et un
redimensionnement (chaque côté s'arrête à son bord) se bornent différemment.
Comme pour la souris, l'objet tenu est figé à l'écart de sa prise (`sc-held`)
pendant que le reste du champ tourne, et sa place est calculée pour le tour du
lâcher. Si la fenêtre ou le champ changent pendant la tenue, elle se refonde
(`rebase`) : la boîte suivante du moteur devient la référence, et seuls ses
écarts à elle comptent (`createRelay`, ancré sur le départ de la tenue refondue :
si la refonte a borné le cadre au bord, la main le rattrape en revenant, comme
contre un mur) — le cadre ne saute pas. Une prise pendant le dégel d'un clic
l'arrête et part de ce qui est affiché (QA 5 : 12 → 144 px avant). Le pointeur étant
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

`TOOL` = `pointer` | `pan` | `select`,
`TOOL_DEFAULT = 'pointer'`, `normalizeTool(value)` retombe sur le défaut. Les
outils disent « ce que la main veut dire » et restent distincts des réglages :
un outil se choisit en pleine session et ne se calibre pas ; un réglage se
persiste et dit comment Bare Hands se comporte. **L'écran tient désormais les
deux à deux endroits distincts** (décisions 11 et 14, Slices 02 et 03) : les
réglages dans l'onglet Expérimental, les outils dans la palette de gauche,
atteignable en pleine session — ce qu'un modal de réglages n'est pas. La
distinction se voit donc encore plus qu'elle ne s'écrivait. Le champ `tool`,
lui, ne bouge pas : même porte (`saveSettings`), même normalisation, même
refus nommé pour un outil inconnu.

### La palette d'outils du bord gauche (décisions 11 à 13, Slice 03)

**La palette de gauche est la surface canonique de sélection d'outil en V1.**
`control_center_barehands_hud.js` — le même module que le contrôle de cycle de
vie, parce que c'est la même famille et le même coin d'écran — dessine sous la
main une bande verticale **fixe** de trois icônes en trait, dans l'emplacement
`#barehandsPalette` que `control_center.html` déclare (rang d'empilement 30,
sous le contrôle à 32 et sous son sélecteur à 36, que la palette ne doit jamais
recouvrir).

| Ce qu'elle garantit | Comment |
|---|---|
| exactement les outils **installés** | peuplée par `describeTools()` à chaque peinture ; aucune liste en dur |
| un outil sans moteur n'est **pas** un contrôle | état `absent` : gris, barré, `aria-disabled="true"`, motif `UNAVAILABLE` dans l'infobulle, clic sans effet et journalisé |
| l'outil actif est **immédiatement** lisible | trois canaux : l'échelle de tons, un **rail** de forme, et le **nom** écrit sous la bande |
| un seul chemin d'écriture | le clic appelle `JarvisBarehands.tool(id)`, donc `saveSettings({tool})` — aucun magasin d'outils parallèle |
| synchronisation **bidirectionnelle** | abonnée à `openToolSeam` (l'outil) **et** `openLifecycleSeam` (la disponibilité) ; un `tool()` de console, une réponse de serveur ou un rechargement repeignent la bande, l'onglet de réglages fermé |
| indépendance des réglages | la palette ne lit ni n'ouvre `SET` ; ouvrir les réglages n'est requis pour rien |

**Les trois états** sont écrits une seule fois dans la feuille et portés par
`data-bh-tool-state`, exactement comme la Slice 01 porte ses cinq tons sur
`data-bh-tone` : `active` (fond, halo, rail), `idle` (trait bleu sobre),
`absent` (gris, barré, sans halo). Le bouton, son halo, son rail et son libellé
lisent la même définition par héritage de propriétés personnalisées ; « actif »
ne peut donc pas vouloir dire deux choses à deux endroits.

**Clavier.** `role="toolbar"`, `aria-orientation="vertical"`, un seul arrêt de
tabulation (curseur mouvant), flèches dans les deux axes, `Home`/`End` aux
bouts, `aria-pressed` sur chaque bouton. Les flèches **déplacent le focus sans
choisir** — c'est le changement assumé par rapport au `moveTool()` supprimé des
réglages, qui enregistrait à chaque touche : dans un formulaire c'était la
sémantique d'un groupe de radios, sur l'écran principal c'eût été une écriture
réseau par frappe et le sens de la main qui change sous les doigts. Le
sélecteur de mode de la Slice 02 a tranché la même question pour la même
raison. Les outils sans moteur restent **sur** le chemin du clavier
(`aria-disabled`, pas `disabled`) : `moveTool()` les sautait, et leur motif
n'était alors lisible que par une souris qui survole.

**Bare Hands indisponible.** La palette **ne disparaît pas** et **ne fait pas
semblant d'agir**. Éteinte, en panne ou en démarrage, elle s'atténue
(`data-bh-live="false"`), perd le halo — le halo veut dire « quelque chose
tourne » depuis la Slice 01 — et garde son rail et son nom, parce que l'outil
choisi reste vrai : c'est un réglage persisté, et il s'appliquera au réveil.
Elle reste donc **utilisable** : préparer son outil avant d'allumer est un
choix légitime, et le désarmer aurait forcé un détour par les réglages, ce que
la décision 11 supprime. La veille s'arrête à `sleep` : là, la caméra est tenue
et la posture en C rend la main tout de suite. La palette ne **redit jamais**
le cycle de vie à l'écran — le contrôle qui le porte est dans la même colonne,
100 px au-dessus, et son étiquette dit déjà ÉTEINT / DÉMARRAGE / INTERROMPU ;
ce qu'elle ajoute est ce que le contrôle ne dit pas, à savoir ce que devient
**l'outil** pendant ce temps-là.

**Déplacer, ancrer, pivoter sont reportés** (décision 13), donc rien n'en
esquisse l'affordance : pas de poignée, pas de `draggable`, pas de bascule
d'orientation. Sous 700 px la bande suit le contrôle sur le bord gauche et
resserre ses icônes ; elle reste verticale.

**Les refus sont confinés.** La palette s'installe dans son **propre** bloc
`try` : son emplacement absent ou la couture d'outil manquante donnent
`barehands_palette_host_missing` / `barehands_palette_seam_missing` à la
console, et le contrôle de cycle de vie — le plus important des deux
(décision 1) — reste entier. Un outil installé dont ce module n'a pas le dessin
reste **choisissable** (c'est son dessin qui manque, pas son moteur), porte un
substitut en pointillés et se dit sous `barehands_palette_icon_missing` au
chargement.

**Un outil est une exigence sur la cible, et rien d'autre.** `TOOL_CAPABILITY`
donne la capacité de chacun, et cette capacité **est** un mode de contenu du
moteur (`CONTENT_MODE` dans `control_center_barehands.js`) — sauf
`TOOL_CAPABILITY_CONTEXTUAL`, qui est l'absence d'exigence :

| Outil | Capacité | Installé | Ce qu'il exige de la cible |
|---|---|---|---|
| `pointer` | `contextual` | oui | rien : le moteur décide de ce qu'il y a sous la main |
| `pan` | `scroll` | oui | que la cible défile |
| `select` | `select` | oui | un champ de saisie ou une étoile de la scène |

**La couche d'annotation est délibérément hors du périmètre V1.** `highlighter`
et `draw` ont été **retirés** de `TOOL`, `TOOL_CAPABILITY`, `TOOL_LABEL`, de la
palette et du miroir serveur (`barehands_test_mode.TOOLS`). Ils y étaient
déclarés, refusés partout et possédés par **aucune Slice** : la Slice 07 en
était le seul propriétaire et elle a livré. Deux outils sur cinq étaient donc
une promesse que rien n'allait tenir, et un outil grisé pour toujours se lit
comme une panne permanente. La palette offre maintenant exactement ce qui
marche : `pointer`, `pan`, `select`. Un nom retiré n'est pas « déclaré sans
moteur », il est **inconnu** : `toolCapability('draw')` et
`POST /api/barehands {"tool":"draw"}` rendent tous deux
`barehands_tool_unknown`.

**La recette d'extension, elle, est conservée** — c'est le mécanisme qui refuse,
pas les deux noms, qui avait de la valeur. Restent en place et testés :
`SERVED_CAPABILITIES` (distinct de `TOOL_CAPABILITY`), `toolInstalled`,
`INSTALLED_TOOLS`, le `reason` de `describeTool`, le refus serveur
`barehands_tool_not_installed`, le grisé motivé de la palette et la porte
`tool_not_installed` de `openCapture`. Ajouter demain une couche d'annotation,
c'est : une entrée dans les trois tables, puis servir `annotate` dans le moteur
et l'ajouter à `SERVED_CAPABILITIES`. Tant que la dernière marche manque,
l'outil est **déclaré, grisé avec son motif, et refusé partout** plutôt
qu'enregistré sans effet. Trois tests l'exercent en déclarant l'outil qu'une
Slice future déclarerait — `ink`, capacité `annotate`, non servie — plutôt
qu'en l'affirmant :
`test_barehands_tools_settings_js::test_a_tool_declared_without_an_engine_refuses_every_capture`
(par la couture `contracts` du moteur) et
`test_barehands_test_mode::test_a_tool_declared_without_an_engine_is_still_refused_by_its_own_name`
couvrent le **mécanisme de refus**, chacun par un maillon : le premier remplace
`toolCapability` seul, le second élargit `TOOLS` seul. Aucun des deux n'exécute
les trois étapes déclarées ci-dessus, si bien que ni `INSTALLED_TOOLS`, ni
`describeTool`, ni `describeTools` — ce que la palette dessine — n'avaient
jamais vu l'outil futur : la recette *comme recette* n'était exercée par rien.
`test_the_extension_recipe_is_walked_end_to_end_and_not_only_its_refusal` écrit
donc la Slice future dans le contrat lui-même et la lit **dans les deux sens** :
déclaré sans être servi, l'outil est grisé avec son motif et refusé partout ;
sa capacité ajoutée à `SERVED_CAPABILITIES`, la porte s'ouvre. C'est cette
bascule qui est la promesse, et elle ne tenait que par lecture du code.

`SERVED_CAPABILITIES` liste les capacités que le moteur sert ;
`toolInstalled(tool)` n'est donc pas un drapeau écrit à la main mais une
lecture de cette table, et `INSTALLED_TOOLS` s'en déduit. `describeTools()`
rend ce que la palette dessine — nom, capacité, disponibilité et **le motif**
d'une indisponibilité (`barehands_tool_not_installed`), parce qu'un outil grisé
sans motif est indiscernable d'une panne. `toolCapability(value)` **refuse** un
nom inconnu (`barehands_tool_unknown`) : ce n'est pas un schéma stocké, c'est
une question sur une table ; `normalizeTool` garde sa tolérance documentée.

**Ajouter un outil**, c'est : une entrée dans `TOOL`, une dans
`TOOL_CAPABILITY`, une dans `TOOL_LABEL` ; puis, pour qu'il soit *installé*,
servir sa capacité dans le moteur et l'ajouter à `SERVED_CAPABILITIES`. Un test
de parité refuse un outil sans capacité et une capacité servie sans outil, et
un second compare la table du contrat à son miroir serveur
(`barehands_test_mode.TOOLS` / `INSTALLED_TOOLS`) **en exécutant** le contrat.

**Ce qu'un outil ne touche pas.** Les zones de manipulation (décisions 9 à 11)
et le corps d'une étoile `point`/`signal` (décision D3) sont des **poignées de
cadre**, pas du contenu : un bord reste un bord quel que soit l'outil, et le
corps d'une étoile reste sa seule prise. Les rendre à l'outil actif ferait
disparaître le redimensionnement dès qu'on choisit la Main, et immobiliserait
les étoiles sous tout autre outil que le pointeur — en silence.

**Une combinaison outil/cible impossible se refuse et se dit.** `openCapture`
rend `tool_target_unsupported` (la cible ne peut pas honorer la capacité) ou
`tool_not_installed` (le moteur ne sert pas cette capacité, défense en
profondeur : ce moteur est injectable et ne suppose pas que son appelant a
filtré). Les deux remontent sur la ligne `jh-note` qui porte déjà les gestes
étouffés de la Slice 04 et les prises refusées de la Slice 06, avec **leur
propre phrase** — une main qui se pose et ne fait rien serait indiscernable
d'une panne. L'outil actif voyage aussi sur chaque `INTERACTION` publiée
(§ 7) : un consommateur qui reçoit un `scroll` peut savoir s'il vient du
contenu ou de l'outil Main.

## 9. Réglages (§9), version 2

> **Vous implantez un point d'entrée de parcours (Slice 08, Slice 09) ?** Lisez
> d'abord le contrat `flow_unconfirmed` du § 12. En un mot : un appel qui ne
> lève pas n'est **pas** une preuve, donc un parcours doit **confirmer** en
> résolvant `true` ou `{ok:true}`. Tout le reste — `undefined`, `null`, `false`,
> un objet muet comme `{}` ou `{ok:false}` — est un refus
> `barehands_flow_unconfirmed`, et JARVIS dira à l'utilisateur que ça n'a pas
> démarré. C'est le prix d'entrée pour être annoncé.

`SETTINGS_SCHEMA_VERSION = 2`. `normalizeSettings(raw)` accepte l'absence et le
partiel, et rend toujours une valeur complète et bornée :

| Clé | Défaut | Bornes | Ce qu'elle fait vraiment |
|---|---|---|---|
| `enabled` | `false` | — | allume/éteint ; éteint, la caméra est rendue |
| `targetPreview` | `true` | — | décision 24 : éteint, l'aperçu est retiré **tout de suite** ; la cible continue d'être résolue |
| `sleepTimeoutMs` | `30000` | 5 000 – 600 000 | décision 7 : le délai réel du retour en veille (`controller.configure`) |
| `tool` | `pointer` | `TOOLS` installés | § 8 |
| `assistance` | `0.5` | 0 – 1 | portée d'assistance = `targetAssistPx × 2 × assistance` |
| `sensitivity` | `1` | 0,25 – 4 | **divise** `clickSlopPx` et `dragSlopPx` |
| `tutorialSeen` | `false` | — | persisté ; **compatibilité** — plus écrit ni dessiné depuis la Slice 07B (§ 13) |
| `calibrationEnabled` | `true` | — | décision 27 ; **lu par la Slice 08** : décoché, le bouton « Calibrer… » est grisé et `JarvisBarehands.calibrate()` refuse |
| `diagnostics` | `false` | — | §12 : lecture à l'écran (`jh-diag`), présente ou **absente** de l'arbre |

`SETTINGS_BOUNDS` tient les bornes une seule fois : l'écran dessine ses
curseurs dessus, `normalizeSettings` borne dessus, le serveur refuse dessus.
**Une borne inversée se refuse au chargement du module** — `clamp(v, lo, hi)`
rend `lo` quand `lo > hi`, donc tous les réglages seraient épinglés sur une
valeur unique, sans exception ni test rouge. Même classe que `MIN_SIZE`/
`MAX_SIZE` à la Slice 06 : il n'y a pas de constructeur là où vit la table.

**Il n'en reste qu'un décoratif, et l'écran le dit toujours.**
`calibrationEnabled` est **vivant depuis la Slice 08** : décoché, le bouton
« Calibrer… » est grisé avec son motif et `JarvisBarehands.calibrate()` refuse
`barehands_calibration_disabled` — c'est la décision 27 rendue exécutable, et
c'est bien ce réglage-là que le code nomme depuis l'affinage d'UI, l'extinction
de Bare Hands ayant pris le sien (`barehands_calibration_lifecycle_off`, § 10).
`tutorialSeen` traverse toujours la route, le fichier et la normalisation, et
**plus personne ne l'écrit** depuis la Slice 07B : le parcours qu'il décrivait a
été retiré. Sa case a quitté l'onglet avec lui — une case qui interroge
l'utilisateur sur l'achèvement d'un parcours inexistant n'est pas un réglage.
Il reste au schéma pour ne pas imposer une montée de version à trois fichiers
pour un seul booléen inerte (§ 13,
`docs/legacy/barehands-tutorial-retirement.md`). Tous les autres sont
**vivants** :
`applyToEngine(settings)` est le seul endroit qui les porte au moteur, et un
réglage qui n'y trouverait pas sa ligne n'aurait pas sa place dans la table.

**Et « le seul endroit » n'est pas une preuve : chaque réglage a un test qui
part de l'écran et finit sur un comportement.** La reprise de la Slice 07 a
mesuré que cinq lignes de `applyToEngine` pouvaient disparaître sans qu'un seul
test tombe, parce que les tests appelaient la **porte du moteur**
(`overlay.showDiagnostics(true)`, `targetAssistance(0)`, `configure({…})`), ce
qui prouve la méthode et jamais le câblage. La règle est donc : un réglage se
vérifie en l'écrivant **là où l'utilisateur l'écrit** — une case, un curseur,
un bouton de palette — puis en regardant ce que la main fait. Et le moteur se
relit : `controller.options()`, publié par `JarvisBarehands.engine()`, rend ce
qu'il applique vraiment (`sleepTimeoutMs`, `clickSlopPx`, `dragSlopPx`,
`wakeHoldMs`, `wakeIntervalMs`), en lecture seule — sans elle, la seule façon
de relire le moteur était de le reconfigurer, donc « réglage enregistré » et
« réglage appliqué » n'étaient pas distinguables.

**Écrire un réglage : trois refus nommés, aucun silence.**

| Ce qui arrive | Ce que fait `saveSettings` |
|---|---|
| une écriture est déjà en vol (`view.busy`) | rend `null`, **avec** bandeau, toast et ligne de console — les contrôles de l'écran sont désarmés, donc seul un appelant sans écran (voix, console) y arrive, et c'est lui qui n'a rien à lire |
| `patch.tool` est un nom **inconnu** | `toolCapability` lève `barehands_tool_unknown` **avant** la normalisation : la valeur ne part pas sur le fil et ne retombe jamais sur `pointer` |
| le serveur refuse ou le réseau tombe | l'ancienne valeur revient au moteur (`applyToEngine(previous)`) **et** à l'écran |

`normalizeTool` garde sa tolérance : elle sert à relire un schéma stocké. Une
**écriture** est une question posée à la table des outils (§8), et la réponse
est non. Un outil déclaré mais **sans moteur** passerait cette porte et se
ferait refuser par le serveur, seul à savoir ce qu'il sert : les deux refus
gardent leur phrase et leur auteur. La table n'en déclare aucun depuis que la
couche d'annotation est hors V1 (§8), mais la porte reste la recette
d'extension.

**`enabled` est le seul dont l'état moteur ne passe pas par `applyToEngine`**, et
son échec d'écriture a donc sa propre règle. Décocher libère la caméra *avant*
l'écriture, exprès (l'objectif n'attend pas le réseau). Si l'écriture échoue,
on **ne rallume pas** : rouvrir la caméra — et son invite de permission — parce
qu'un *enregistrement* a échoué ferait faire à la machine ce que personne n'a
demandé. L'écran suit donc le moteur (la case se décoche), et la divergence qui
reste — le serveur, lui, dit toujours « allumé » — est **nommée** dans le
bandeau et dans un toast : Bare Hands sera de nouveau allumé au prochain
chargement. Le toast est nécessaire parce que ce chemin s'atteint panneau
fermé, par `JarvisBarehands.disable()`.

**`sensitivity` divise les deux tolérances, pas une.** Le même facteur des deux
côtés, donc l'invariant `clickSlopPx <= dragSlopPx` (Slice 04) traverse intact
quelle que soit la sensibilité ; n'en diviser qu'une le ferait **refuser** aux
sensibilités hautes. Et `1` rend exactement les défauts du moteur — règle posée
par l'assistance à la Slice 05 : quand un réglage stocké multiplie une
constante du moteur, c'est le défaut du réglage qui doit rendre le défaut du
moteur, sans quoi brancher le champ serait à soi seul une régression invisible.

**Septième paire dangereuse : `sleepTimeoutMs <= wakeHoldMs`.** C'est la
première que les réglages rendent atteignable. Sous `wakeHoldMs`, la seconde de
posture en C coûte plus cher que tout le temps qu'elle achète : on réveille, et
la veille a déjà repris la main à l'image suivante. La session **cycle** en
détruisant à chaque tour les identités de piste et les fentes de pointeur —
exactement la panne que la reprise de la Slice 03 a mesurée par un autre
chemin. `options()` la refuse, donc `createController` **et**
`controller.configure` la refusent, chacun là où le réglage arrive ; la borne
basse du contrat (5 000 ms) est cinq fois au-dessus, ce qui protège l'écran
mais pas un appelant, et c'est pour ça que le refus est au moteur.

**Le numéro de schéma est lu, pas seulement estampillé, et c'est la couture de
migration.** `schemaVersion` absent vaut « écrit par nous ». `1` est
**converti** (`SETTINGS_MIGRATED_VERSIONS`) : côté page la v1 portait déjà les
neuf clés, la conversion est donc une re-estampille ; côté serveur un bloc v1
ne portait que `enabled`, et les huit autres clés prennent leur défaut. Tout
autre nombre lève `barehands_schema_version_unsupported`, dans
`normalizeSettings`, dans `fromServerState` et dans `normalizeProfile`. C'est
ce refus qui est devenu le point d'entrée de la prochaine migration : y
accepter la version précédente et la convertir, plutôt que de la laisser passer
muette. Côté serveur, `load` est **tolérant** (un fichier abîmé ne rend pas
Bare Hands injoignable) : une version étrangère n'est pas devinée, on n'en
garde rien et Bare Hands reste éteint ; c'est `apply` qui refuse, avec son code.

**Une version stockée étrangère est ARCHIVÉE, puis remplacée par les défauts.**
Tolérant ne veut pas dire muet. `load` rendait les défauts en silence et la
première écriture ordinaire remplaçait le bloc — `apply` part de `load()`,
c'est-à-dire des défauts, et réécrit la clé entière. Un utilisateur qui monte
de version, redescend et recoche Bare Hands perdait ses réglages sans qu'un mot
passe à l'écran ni dans le journal. Trois choses ferment ça :

| Ce qui manquait | Ce qui le porte |
|---|---|
| distinguer « défauts parce qu'illisible » de « défauts parce que neuf » | `barehands_test_mode.inspect(settings)` → `{present, stored_schema_version, unreadable, archive_key}`, publié par `describe()` sous `stored_schema_version` (`null` si rien n'est enregistré), `unreadable` et `archived` |
| ne pas détruire | `archive_unreadable(settings)`, appelé par `apply` **avant** l'écriture : le bloc part **tel quel** sous `barehands_test_mode_archived_v<N>`, à la racine du fichier de réglages |
| le dire | bandeau de l'onglet Expérimental (`storedHtml`), et deux lignes de journal : `settings.barehands.foreign_version` à la lecture (une par processus, la lecture étant fréquente) et `settings.barehands.archived` à l'écriture |

`schema_version` reste **ce que ce serveur écrit** : il valait 2 quoi qu'il ait
lu, et c'est précisément ce qui rendait les deux situations indiscernables.
Points fixés : la clé d'archive porte la **version archivée**, donc deux
retours en arrière depuis deux versions différentes laissent deux archives ; un
numéro non numérique va sous `…_vunknown` plutôt que sous `…_v-1` ; une archive
de la même version est remplacée par la plus récente, et la ligne de journal le
dit (`replaced_previous_archive`) ; un refus d'écriture n'archive **rien**, une
archive étant une conséquence de l'écriture et non de la tentative. Le bloc est
archivé **sans normalisation** — le normaliser reviendrait à perdre ce qu'on
prétend garder, à commencer par les clés que cette version ne connaît pas.

**Asymétrie connue, et laissée telle quelle.** Le contrat JS compare la version
après conversion numérique : `"2"` et `schemaVersion: 1` passent. Le serveur,
lui, compare la valeur reçue et refuse les deux. Sans conséquence aujourd'hui
— `toServerPayload` estampille toujours un nombre, donc une chaîne ne traverse
jamais le fil — mais une v3 qui supposerait la symétrie trébucherait ici.
Durcir le côté page refuserait au passage un bloc stocké en `"2"` qui
fonctionne : le rapprochement appartient à la migration qui en aura besoin, pas
à un durcissement isolé.

**La route accepte les neuf réglages depuis la Slice 07.** `toServerPayload`
reste le **seul chemin légal** vers `POST /api/barehands` : il normalise,
borne, renomme en `snake_case` (`SETTINGS_WIRE_KEYS`, la seule table de
passage, testée aller-retour) et estampille `schema_version`. `fromServerState`
fait le chemin inverse. Élargir encore la route, c'est monter
`barehands_test_mode.SCHEMA_VERSION` **et** `SETTINGS_SCHEMA_VERSION` dans le
même changement. Le serveur refuse, avec un `code` stable repris dans
`X-Jarvis-Error-Code` : `barehands_bad_payload`, `barehands_unknown_field`,
`barehands_enabled_missing`, `barehands_enabled_not_boolean`,
`barehands_setting_not_boolean`, `barehands_setting_not_a_number`,
`barehands_setting_out_of_range`, `barehands_tool_unknown`,
`barehands_tool_not_installed`, `barehands_schema_version_unsupported`. Une
clé **absente** garde ce qui est enregistré : `{"enabled": false}` seul reste
une écriture valide, ce qui est la raison d'être de cette route.

Rappel de la Slice 00 (constat F5) : `barehands_test_mode` n'est
délibérément **pas** dans `/api/settings`. Sa paire de routes dédiée applique le
réglage à chaud sans dépendre de la validité du reste des réglages. Et l'onglet
« Expérimental » reste une surface **partagée** : Bare Hands le crée
(`TABS.push`) et enveloppe `renderTab` ; `control_center_scene_settings.js`,
inséré après, enveloppe à son tour et **préfixe** sa section. La Slice 07
n'ajoute aucun module de page et ne touche pas à cette chaîne : elle écrit deux
sections de plus dans le même `modalContent.innerHTML`, donc l'ordre
d'injection documenté à `control_center.py:224-226` est intact.

## 10. Profil de calibration (§10, décisions 28-32)

> **Le parcours de calibration sera appelé par la voix autant que par le bouton**
> (§ 12). Son point d'entrée `JarvisBarehands.calibrate()` doit donc **confirmer**
> son démarrage en résolvant `true` ou `{ok:true}` ; `undefined`, `null`,
> `false` et l'objet muet sont des refus `barehands_flow_unconfirmed`. Tant que
> le point d'entrée n'existe pas, le canal refuse proprement avec
> `barehands_flow_absent` — rien à faire pour que ça marche, tout à faire pour
> que ce soit annoncé honnêtement.

`PROFILE_SCHEMA_VERSION = 2`. Un seul profil visible, valeurs internes par main
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
| `travelSlopNorm` | **fraction de la largeur de l'image** (0..1) | 0,002 – 0,15 |
| `reachNorm` | `{x,y,w,h}` en **coordonnées normalisées 0..1 de l'image**, comme les points d'un `HandFrame` — jamais des pixels | 0 – 1 |
| `quality` | 0..1, confiance de la mesure | 0 – 1 |

**Version 2 (Slice 08)**, et la v1 se **convertit** (`PROFILE_MIGRATED_VERSIONS`)
au lieu de se refuser : ses six mesures restent valides, `travelSlopNorm` et
`stages` prennent leur défaut — ce qui est exactement ce que dit un profil
dérivé avant que le parcours n'existe. Deux ajouts :

- **`travelSlopNorm` règle le résidu pixels-contre-paumes de la Slice 04.**
  `clickSlopPx`/`dragSlopPx` sont en pixels de la fenêtre quand tout le reste du
  moteur mesure en paumes : le même geste vaut ~3 fois plus de pixels en 1920
  qu'en 640. **La paume n'est pas la réponse** pour autant. Aucune des deux
  unités n'est invariante aux deux variables — la paume l'est à la distance à
  la caméra mais pas à la résolution, la fraction d'image l'inverse — et c'est
  pour ça que la question était restée ouverte. Ce qu'on borne ici est un
  déplacement **à l'écran**, donc une grandeur d'écran ; et la distance à
  laquelle l'utilisateur se tient est déjà dans la mesure, puisque c'est lui qui
  l'a faite, à sa place habituelle. Application :
  `clickSlopPx = travelSlopNorm × largeur de la fenêtre`, `dragSlopPx` gardant
  le rapport d'usine, donc l'invariant `clickSlopPx <= dragSlopPx` traverse
  intact comme il traverse `sensitivity`. Résidu nommé : un utilisateur qui se
  rapproche franchement de la caméra après s'être calibré doit recalibrer —
  strictement moins que la constante unique d'avant, qui valait pour toutes les
  résolutions et tous les utilisateurs à la fois.
- **`stages` dit quelles étapes ont abouti** (décision 31). `STAGE` =
  `neutral` | `c_pose` | `pinch_primary` | `pinch_secondary` | `aim` | `drag` |
  `resize` ; chacune porte `{status, reason, samples}` avec
  `STAGE_STATUS` = `ok` | `failed` | `skipped` (les trois mots de `FLOW_STATUS`,
  et l'inclusion est tenue par un test — voir § 11) et un `reason` de la liste fermée
  `STAGE_REASON` (`barehands_stage_no_hand`, `…_timeout`,
  `…_too_few_samples`, `…_not_separable`, `…_out_of_band`, `…_needs_two_hands`,
  `…_cancelled`, `…_scene_unavailable`). `skipped` n'est pas `failed` : une étape qu'on n'a pas jouée
  et une étape jouée qui n'a pas abouti ne demandent pas la même chose à
  l'utilisateur. Un `ok` portant un motif, ou un `failed` **muet**, se refusent
  (`barehands_stage_report_inconsistent`) — un échec sans raison ne se distingue
  pas d'une panne.

**`null` est une absence, pas un zéro.** `Number(null)` vaut `0`, qui est fini :
une valeur non mesurée était bornée sur son **minimum** au lieu de rester nulle.
Sans conséquence tant que rien ne relisait un profil — l'entrée venait toujours
d'un objet partiel où la clé *manquait*. Mais un profil persisté est du JSON, et
du JSON porte des `null` explicites : relire un profil vierge rendait les huit
mesures « calibrées » à leur plancher, `calibrated` vrai sans qu'une mesure ait
eu lieu, `updatedAt` au 1<sup>er</sup> janvier 1970, et `profileValue` rendant
ce plancher **au lieu du défaut du moteur** — la décision 31 défaite par une
conversion de type. La Slice 08 est la première à relire un profil ; c'est elle
qui a trouvé la mine. L'assertion qui la tient est un **aller-retour** :
`normalizeProfile(JSON.parse(JSON.stringify(toProfilePayload(p))))` doit rendre
`p`.

**Aucune image ni vidéo** : seulement des paramètres dérivés et des métriques
(décision 32) — et c'est tenu **en structure**, pas en intention. Deux gardes,
qui ne se doublent pas :

1. `normalizeProfile` est une **liste blanche** : il reconstruit le profil clé
   par clé, donc une clé que le schéma ne nomme pas n'atteint jamais le fil —
   pas parce qu'on la refuse, parce qu'on ne la recopie pas. `reachNorm` est
   rebâtie de ses quatre nombres. `toProfilePayload` est le seul chemin légal
   vers la route du profil, comme `toServerPayload` l'est pour les réglages.
2. Ce que la liste blanche ne protège pas, c'est le **schéma lui-même** : rien
   n'empêchait une Slice ultérieure d'ajouter à `HAND_PROFILE_DEFAULTS` une clé
   acceptant un objet libre, et la décision 32 serait tombée sans qu'une ligne
   change ailleurs. `assertDerivedOnly` est donc posée sur la **forme**, au
   chargement du module — même idiome que l'inversion de `SETTINGS_BOUNDS` — et
   sa sonde est **pilotée par le schéma** : elle présente à chaque clé mesurable
   et à chaque champ d'étape une suite de points, une image en base64 et un
   objet libre, puis vérifie ce que la normalisation en laisse passer. Un profil
   rempli à la main ne dirait rien d'une clé que personne n'aurait pensé à
   remplir. Mesuré : ajouter une clé `sampleFrames` qui recopie son entrée fait
   **refuser le chargement du module**.

   **Une sonde refusée avant le gate n'est pas une couverture.** Un refus de la
   normalisation est une réponse *sûre* — la valeur n'est pas passée — mais le
   `catch(_refused){continue}` avalait justement les deux champs que la
   décision 32 nomme comme le risque : une `reachNorm` portant une sonde brute
   dégénère (`w`/`h` à zéro) et se fait refuser avant d'atteindre le gate, et
   `reason` était systématiquement accompagné de `status:'ok'`, ce qui rend le
   rapport incohérent et le fait refuser lui aussi. La sonde présente donc en
   plus deux formes **bien formées** — une portée valide qui porte une clé de
   trop, et un motif libre sous un statut non `ok` — qui traversent la
   normalisation entière et arrivent au gate à tous les coups. Mesuré des deux
   côtés : une `reachNorm` qui recopie son entrée, ou un `reason` qui cesse
   d'être borné à sa liste fermée, font refuser le chargement du module.

La poser en plus sur chaque charge utile serait la « seconde vérité » que ce
dépôt refuse (Slice 12) : par-dessus la liste blanche, elle ne pourrait pas
échouer.

- `normalizeProfile(raw)` : une valeur non mesurée vaut `null` ; `calibrated`
  est vrai dès qu'**une** mesure **calibrante** existe, quelle qu'elle soit —
  une calibration partielle est valide (décision 31) — et faux si rien n'a été
  mesuré, quoi qu'annonce l'entrée. La liste des clés est lue du profil
  lui-même, donc une mesure ajoutée par une Slice ultérieure (Slice 08,
  `secondaryPressRatio`, décisions 21-22) compte sans qu'on y repense. Elle
  n'en citait que trois sur sept : le drapeau et la donnée se contredisaient,
  et une porte qui teste `calibrated` relançait la calibration pour toujours
  tout en utilisant déjà la mesure.

  **`quality` ne lève pas le drapeau** (`PROFILE_METRIC_KEYS`, miroir
  `METRIC_KEYS` côté route). C'est une *métrique* de la séance et non un seuil —
  aucun `profileValue` du moteur ne la lit — mais `deriveProfile` l'écrit pour
  **tout seau de main ayant vu une image**. Une séance dont les sept étapes
  avaient échoué persistait donc `calibrated: true` : l'onglet affichait
  « Calibré le … », le toast annonçait « Bare Hands utilise vos mesures »
  (faux), la branche « sans aucune mesure » du journal ne tirait jamais, et
  « Effacer le profil » s'activait pour un profil sans une seule mesure. Le
  drapeau répond à « le moteur a-t-il été adapté à cette main ? » ; une
  métrique qui ne l'adapte pas n'a pas le droit d'y répondre oui. Elle reste
  bornée, persistée et affichée. **L'exclusion s'écrit, jamais l'inclusion** :
  une clé ajoutée demain calibre par défaut. Le compte du récapitulatif
  (`measuredCount`) et celui du journal (`measured`) suivent la même règle,
  faute de quoi la coque et le profil se contredisaient.
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

### Le parcours (Slice 08)

`jarvis/runtime/control_center_barehands_calibration.js`
(`window.JarvisBarehandsCalibration`). Deux choses y vivent, et c'est la
**décision 26** qui les met ensemble : la **coque** de surimpression, et le
**parcours**. La coque ne sait rien de la calibration — elle affiche des
étapes — et c'est ce qui permettra au tutoriel (Slice 09) de la reprendre sans
la modifier. `createFlowOverlay({document, now, setInterval, clearInterval})`
rend `open/step/progress/note/target/buttons/report/expired/elapsedMs/close/isOpen`,
plus `regions/mount/clear/flash/flashing` depuis la refonte ci-dessous, et
`deadline` depuis la machine à phases (Slice 06). Rien n'a jamais été retiré ni
renommé : le tutoriel (§13) reçoit la même coque sans une ligne de changement.

#### La coque plein cadre et ses cinq régions (refonte, Slice 05)

**Décisions 18 à 21, architecture §6.** La composition d'origine — une carte
centrée de 560 px, avec son fond, son ombre et son rayon de 20 px, posée au
milieu d'un noir plat — a été **refusée par l'utilisateur**. Pas réglée :
remplacée. Ce qui la remplace n'est pas une carte plus grande, c'est
l'absence de carte.

**Le voile** (`jf-veil`). Une couche à part, sous la mise en page, qui porte le
flou et l'assombrissement. Le point qui fait la différence : l'assombrissement
passe par `backdrop-filter: brightness(.76)` et non par une nappe opaque, donc
la scène JARVIS garde sa **couleur** derrière au lieu d'être recouverte de gris
— « plus atmosphérique, moins noir mort » est une propriété du filtre, pas du
dosage d'un noir. `saturate(118%)` l'empêche de virer au gris, une teinte bleue
en haut dit que c'est un mode JARVIS et non un voile générique, et la nappe
posée par-dessus reste légère (`.52`). Un `@supports not (backdrop-filter…)`
l'opacifie là où le flou n'existe pas : sans lui, la scène traverserait le
titre qu'elle doit laisser lire.

**La mise en page** (`jf-step`, le nom n'a pas bougé parce qu'il n'a jamais
désigné une boîte). Une grille plein cadre en trois rangées —
`auto / minmax(0,1fr) / auto` : bandeau haut, **scène au milieu**, pied en bas.
Elle déclare `max-width:none; background:none; border:0; border-radius:0;
box-shadow:none`, et ces cinq déclarations sont lues par un test : c'est la
seule façon de distinguer « la carte a été retirée » de « la règle a été
oubliée ailleurs ».

**Les cinq régions nommées** — le contrat que les parcours suivants lisent au
lieu d'inventer chacun leur géométrie dans le centre laissé libre :

| région | classe | qui la remplit |
|---|---|---|
| `demo` | `jf-demo` | le parcours, par `mount()` — la démonstration |
| `exercise` | `jf-exercise` | le parcours, par `mount()` — la cible de l'exercice |
| `feedback` | `jf-feedback` | la coque y tient `jf-note` ; le parcours peut y ajouter |
| `progress` | `jf-progress` | **la coque seule** (`progress()`) |
| `controls` | `jf-controls` | **la coque seule** (`buttons()`) |

- `regions()` rend les nœuds eux-mêmes (`demo, exercise, feedback, progress,
  controls, stage, header`), ou `null` si la coque est fermée — et **ne la
  construit pas** : une image qui arrive après Échap ne doit pas faire
  réapparaître une surimpression que l'utilisateur vient de quitter.
- `mount(région, nœud)` place, `clear(région)` retire **exactement ce que
  `mount` a posé** : vider `feedback` en bloc emporterait la ligne de
  commentaire de la coque, et la RÈGLE ZÉRO perdrait sa phrase sans que
  personne l'ait demandé.
- `mount('progress'|'controls', …)` **lève**, et le message nomme le
  propriétaire. Les y laisser monter serait le défaut plausible par excellence :
  les deux sont réécrites à chaque étape, donc le contenu disparaîtrait sans un
  mot.
- `step()` vide `demo`, `exercise` et l'ajout de `feedback`, exactement comme il
  redessine les boutons. Une démonstration qui survivrait à son étape montrerait
  la main d'une **autre** consigne, et l'utilisateur ferait le geste affiché.
- La scène porte `color: var(--jf-accent)`. C'est le crochet du dessin de main
  de la Slice 04 : ses tracés sont en `currentColor`, donc une main montée dans
  `jf-demo` est bleue sans rien savoir de la coque. La coque ne dessine **aucune
  main** elle-même — `control_center_barehands_hand_art.js` est le seul
  alphabet de formes, et en poser un second était la faute à éviter.

**Décision 21 : le bleu guide, le vert félicite brièvement.** `flash(ms)` pose
`data-flash="ok"` sur la racine pour une durée **bornée** (`FLASH_MAX_MS`,
2000 ms) ; l'horloge qui peint déjà le compteur l'éteint. Une durée absente,
nulle, négative ou non finie se **refuse** ; une durée excessive est ramenée au
plafond plutôt que levée, parce que lever au milieu d'une image *réussie*
tuerait le parcours pour un geste que l'utilisateur a bien fait. `flashing()`
lit l'échéance et non l'attribut. Le changement d'étape et la fermeture
l'éteignent. Il n'existe aucun chemin qui laisse le vert allumé, et c'est
exprès : l'ACTIVE vert a été retiré par l'utilisateur lui-même (décision 5)
parce qu'une couleur de succès permanente cesse de signaler un succès.

**La RÈGLE ZÉRO traverse la refonte inchangée** : le rail de progression et les
segments d'étape disent que ça tourne, le titre et la consigne disent quoi —
grands et **hauts** (décision 19) —, `12 s` / `8 s restantes` disent depuis
combien de temps, mot pour mot comme avant, et la croix permanente (au coin de
l'**écran** désormais, plus d'une carte), Échap et le bouton de l'étape disent
comment sortir.

**Adaptation et mouvement.** Deux paliers, parce que ce n'est pas seulement la
largeur : `max-width:720px` (gouttière de 16 px, commandes pleine largeur) et
`max-height:560px` — une fenêtre basse manque de hauteur, et un titre qui
mangerait la scène rendrait l'exercice injouable. Sous
`prefers-reduced-motion`, tout s'arrête, mais ce qui *portait l'information* est
**remplacé** plutôt que supprimé : la cible perd sa pulsation et gagne un halo
fixe plus marqué, parce qu'« accessible » ne peut pas vouloir dire
« inutilisable ».

**L'empilement ne bouge pas** : coque 2147482000, surimpression des mains
2147483000. Les jetons dessinent **au-dessus** de la coque, exprès — une
calibration pendant laquelle on ne voit pas sa propre main ne sert à rien.

**`note(text, kind, holdMs)` — la seule ligne qui puisse être tenue**
(Slice 10). Les deux parcours la réécrivent à **chaque image**, puisque leur
`paint()` est appelé par la cadence de la caméra : une phrase posée par
quelqu'un d'autre vit 16 à 33 ms. C'est ce qui est arrivé au reçu d'une
commande vocale pendant un tutoriel — et la coque couvre le panneau
(`z-index` 2147482000 contre 70), sans toast posé dans ce cas, donc le refus
n'était lisible nulle part, dans le seul cas qu'on regarde. `holdMs` tient la
phrase un temps **borné** : les notes sans `holdMs` — toutes celles des deux
parcours — ne l'effacent pas avant son échéance, et rien d'autre ne change
pour elles ; une note **avec** `holdMs` remplace toujours la précédente, le
plus récent de ce que l'utilisateur a demandé étant ce qu'il attend de lire.
Jamais infinie : un état qui dure toujours est interdit par la même règle que
celui qu'on ne voit pas, et l'étape doit pouvoir reprendre la parole. La tenue
est remise à zéro à l'ouverture et à la fermeture de la coque.

**Décision 27 : optionnelle et explicite.** Rien ne mesure avant qu'on l'ait
demandé. Deux portes, une seule implantation : le bouton « Calibrer… » de
l'onglet Expérimental et `JarvisBarehands.calibrate()`, que le canal de
commandes appelle (§ 12). `calibrate()` **confirme** en résolvant
`{ok:true, flow:'calibration', step, steps}` dès que la coque est à l'écran et
que la première étape tourne — le **démarrage**, pas la fin : l'échéance du
canal est de trois secondes et un parcours en prend trente. Deux refus, rendus
`{ok:false, code}` (donc `barehands_flow_unconfirmed` côté canal) **et** dits à
l'écran, parce que c'est le seul endroit où leur cause exacte survit :
`barehands_calibration_disabled` (`calibrationEnabled` décoché) et
`barehands_calibration_no_camera`.

> **Un code par cause, depuis l'affinage d'UI.** Ces deux-là étaient trois :
> `barehands_calibration_disabled` servait **à la fois** le réglage décoché et
> l'interrupteur éteint, et seule la phrase les distinguait. Un code existe
> pour qu'une machine puisse brancher dessus ; un code qui ne discrimine rien
> que la phrase ne dise déjà mieux ne fait pas son métier — et c'est la voix
> qui le payait, puisque le canal ne remonte au cerveau qu'un code et un
> `reason`. Les deux remèdes sont incompatibles : cocher « Proposer la
> calibration », ou choisir Veille/Actif sur le contrôle en haut à gauche.
> L'interrupteur éteint prend donc `barehands_calibration_lifecycle_off`,
> nommé d'après le cycle de vie pour qu'aucun lecteur ne le confonde avec le
> réglage. Le module HUD avait déjà tranché dans ce sens en inventant
> `barehands_hud_surface_missing` pour sa troisième cause plutôt que de la
> déguiser en « décoché » : on suit ce précédent au lieu de le contredire.
> L'alias déprécié `tutorial` hérite du nouveau code tel quel (§ 13).

Un second appel pendant que la
coque est ouverte **confirme** (`already:true`) : répondre « non » ferait dire à
JARVIS que ça n'a pas démarré devant une coque ouverte à l'écran.

**Le parcours réveille, il n'allume pas.** `calibrate()` réveille (`activate`
est déjà dans la table du canal) mais **ne touche pas** l'interrupteur maître :
le § 12 garde `enable`/`disable` hors du canal parce que ce canal transporte le
cycle de vie (veille, réveil, parcours), pas les réglages — et un parcours qui
allumerait au passage ferait entrer l'interrupteur par un autre nom, sans reçu
ni refus propres. Ce n'est pas une prérogative de l'utilisateur : l'interrupteur
est un réglage que le cerveau lit et écrit, par sa propre route (§ 12).

**Les sept étapes, ce qu'elles mesurent, et comment elles échouent**
(décision 31 : chacune réussit ou échoue **seule**, et ce qui n'est pas mesuré
garde le défaut du moteur) :

| Étape | Mesure | Clé(s) du profil | Échecs propres |
|---|---|---|---|
| `neutral` | tremblement au repos, 95e centile de l'écart **brut ↔ filtré** | `jitterPx` | trop peu d'échantillons |
| `c_pose` | **vérifie**, ne calibre pas : écart, portée et score contre la bande effective | *(aucune)* | majeur trop près du pouce, écart trop bas/haut, index replié |
| `pinch_primary` | bande parcourue entre ouvert et fermé | `pressRatio`, `releaseRatio` | états inséparables |
| `pinch_secondary` | idem sur le canal pouce-majeur | `secondaryPressRatio`, `secondaryReleaseRatio` | idem |
| `aim` | déplacement de la paume pendant un clic délibéré | (moitié de `travelSlopNorm`) | échéance |
| `drag` | **sous-étape 6A** : un bord ou un coin saisi d'**une** main déplace le cadre d'entraînement | (autre moitié de `travelSlopNorm`) | clic et glissement inséparables, `barehands_stage_scene_unavailable` |
| `resize` | **sous-étape 6B** : **deux** zones distinctes et compatibles redimensionnent le même cadre | *(aucune)* | `barehands_stage_needs_two_hands`, `barehands_stage_scene_unavailable` |

**Sept étapes mesurées, six écrans d'exercice** (Slice 07, décisions 26 et 29).
`drag` et `resize` ne sont plus deux écrans génériques (« déplacez la main vers
la droite », « écartez vos deux mains ») : ce sont les deux **sous-étapes** d'un
seul écran public, « Manipulation de fenêtre », qui partagent un même cadre
d'entraînement. Le vocabulaire persisté ne bouge pas — un profil dit toujours
laquelle des deux a abouti, et c'est ce que la décision 31 demande — mais le
parcours compte désormais **six exercices plus le rapport**, qui devient le
septième écran au lieu de se superposer au dernier exercice.

**Le cadre d'entraînement est le vrai cadre, pas un jouet** (décision 30). Il
n'a aucune géométrie à lui : il porte `.sc-node.sc-window` et
`data-representation="window"`, donc le **vrai** résolveur de cible le collecte
(`.sc-node[data-object-id]`, § 6), le **vrai** `combineCaptures` décide ce que
ses zones produisent (§ 7), et le **vrai** `manipulateBox` / `resizeBySides`
calcule sa boîte en unités de scène. Taille minimale, non-inversion et
suspension quand une main est perdue en découlent, elles ne sont pas réécrites.
Deux zones identiques (`same_zone_rejected`), deux captures de corps
(`both_captures_are_body`) ou une seule main (`missing_capture` → `move`) ne
produisent donc **pas** de redimensionnement, et 6B ne se solde pas.

Ce qu'il **n'a pas** : d'existence dans la scène. Il vit dans la région
`exercise` de la coque, son monde est un bac à sable
(`JarvisBarehandsCore.createPracticeFrame`) qui intercepte `begin`/`preview`/
`commit`/`cancel` **avant** `JarvisScene.frames`, donc `commitUserGeometry`
n'est jamais appelé pour lui et aucune commande ne part vers Core. Il est absent
de l'état persisté de la scène avant comme après la calibration, ce qu'un test
affirme.

**`barehands_stage_scene_unavailable`, et pourquoi c'est un refus** (Slice 07,
divergence D4). Cette étape est la première du parcours à dépendre de la scène :
elle emprunte son **échelle** (`JarvisScene.frames.viewport()`), seule source
des pixels par unité, parce qu'un geste calibré contre une fausse échelle ne
calibre rien. Scène éteinte, cette échelle vaut `null`, et les deux replis
possibles sont des défauts plausibles : une échelle inventée fait partir le
cadre six fois trop loin (`viewport_unavailable`, § 7), un faux cadre fait
« réussir » une étape qui n'a pas mesuré le vrai geste. L'étape se marque donc
`skipped` — l'utilisateur n'a rien raté — et le rapport nomme la cause au lieu
de la taire.

`reachNorm` et `quality` se dérivent de **toute** la séance, pas d'une étape :
la portée est ce que la main a atteint pendant qu'on lui demandait autre chose.
C'est aussi pourquoi `quality` ne compte pas pour `calibrated` (§ 10) : elle est
écrite dès qu'une image a été vue, donc par une séance qui n'a rien mesuré.

**Une étape porte toujours une échéance, et deux mécanismes la tiennent.**
Elle ne peut donc pas dépendre de la seule couture d'images : le contrôleur ne
tire `deps.onMeasure` qu'en ACTIVE **et seulement s'il a observé une main**, si
bien qu'un utilisateur sorti du cadre coupait la seule chose qui regardait la
montre. L'étape 1 sur 7 restait alors ouverte indéfiniment (mesuré à
200 000 ms, dix fois `stageTimeoutMs`) sous un compteur figé sur « 0 s
restantes », et `barehands_stage_no_hand` était **injoignable dans le scénario
qui porte son nom** — seule une main mal suivie l'atteignait.

1. **Les images** (`feed`), seules capables de construire un enregistrement de
   scalaires (décision 32) ;
2. **une horloge** (`tick`, cadencée à `watchdogMs`), que le parcours ouvre
   dans `start()` et referme dans `stop()`. Elle ne fabrique **pas** d'image :
   un `feed({hands:[]})` de complaisance affirmerait « aucune main » sans rien
   en savoir, et l'écrirait à l'écran. Elle est posée une fois pour tout le
   parcours, donc elle survit à chaque entrée dans une étape, y compris à une
   étape rejouée.

`createCalibration` **refuse de se construire sans `setInterval`/`clearInterval`**,
au même titre que sans `overlay` ou sans `save` : une garantie que chaque
appelant doit se rappeler de respecter n'est pas une garantie, c'est une
convention — la leçon que la Slice 09 a tirée de la croix de sortie.

**Le vocabulaire du rapport est celui de la coque.** `STAGE_STATUS` doit rester
inclus dans `FLOW_STATUS` : depuis la Slice 09 la coque **lève** sur un mot
qu'elle ne sait pas dessiner, donc une huitième issue d'étape ferait tomber le
parcours au moment précis où l'utilisateur attend son rapport. L'inclusion
tenait par coïncidence ; un test la pose.

**Le C ne pose aucun seuil, et c'est délibéré.** La bande de réveil
(`wakeGapMin`/`wakeGapMax`/`wakeIndexMin`) est lue par le guetteur de veille,
c'est-à-dire **avant** qu'une main ait une identité ou une latéralité : un seuil
par main n'y aurait aucun lecteur, et la décision 28 ne veut qu'un profil
visible. L'étape répond donc à la question que l'utilisateur se pose — « est-ce
que mon C réveille ? » — et sa réponse vit dans le rapport. Elle recalcule la
bande **effective** depuis les défauts du moteur plutôt que de la recopier
(citer 1,35 pour la portée se trompe de 10 %), et elle tient compte du
**gating pouce-majeur** de la Slice 04 : `handPosture` annule toute posture dès
qu'un des deux rapports passe sous `releaseRatio`, donc un C dont le majeur
reste près du pouce marque zéro alors que son écart pouce-index est parfait.
Cette cause est nommée **en premier** et en toutes lettres, parce que
l'utilisateur ne peut pas la deviner et qu'elle rend les deux autres mesures
trompeuses.

**Les réglages du parcours se refusent à la construction, pas au premier
utilisateur qui les rencontre.** Sept combinaisons échouent toutes de la même
façon — en silence, en retombant sur les défauts, ce qui se lit
« l'utilisateur s'y prend mal » : `stageTimeoutMs <= stageHoldMs` (9),
`pressAt >= releaseAt` (10), `travelSlopMin >= travelSlopMax` (11),
`stageMinSamples < 1`, `travelSlopMargin < 1`, plus les trois que le retour de
la Slice 09 a nommées :

- `watchdogMs >= stageTimeoutMs` (**14**, la treizième lue de ce côté-ci) : le
  chien de garde plus lent que l'échéance qu'il surveille laisse « 0 s
  restantes » à l'écran pendant une échéance de plus ;
- `pinchRepeats < 1` (**15**) : l'étape de pincement se solde à la première
  image, `deriveHysteresis` n'a qu'un échantillon et rend `TOO_FEW_SAMPLES`, et
  **les deux étapes de pincement échouent pour tout le monde** — en accusant
  l'utilisateur. À zéro, `progress(repeats/0)` vaut en plus `NaN`, donc la
  barre ne dit même plus où on en est ;
- `sampleQualityMin` hors `[0,1]` et `separationMinPalms` hors `]0,1[` : aucune
  image ne passe le filtre dans le premier cas, aucune main ne sépare assez
  dans le second. Même panne universelle et silencieuse.

**Refuser plutôt que raboter.** `deriveHysteresis` exige
`separationMinPalms = 0,12` entre l'ouvert et le fermé : deux états qu'on ne
distingue pas ne donnent pas un seuil médiocre, ils donnent un seuil qui fait
**clignoter** le contact, donc des clics qu'on n'a pas demandés. De même,
`deriveTravelSlop` exige que le clic le plus agité reste sous le glissement le
plus sage. `pressAt = 0,35` place le seuil d'appui au tiers de la bande : un
pincement **confortable**, pas entièrement fermé, compte déjà.

**Une hystérésis se calibre par paire, ou pas du tout.** Mélanger un seuil
mesuré et un défaut du moteur peut inverser `press < release`, que `options()`
refuse à la construction : une calibration partielle ferait alors **tomber** le
moteur au lieu de le laisser retomber sur ses défauts. La règle est écrite aux
trois étages — le parcours n'écrit que des paires, la page n'applique que des
paires, et le serveur refuse la demi-mesure avec
`barehands_profile_thresholds_incomplete`. **Et la lecture la laisse tomber**,
comme elle laisse tomber une paire inversée : elle ne gardait que la seconde,
si bien qu'un fichier édité à la main ou un profil v1 portant une moitié rendait
`calibrated` vrai et faisait lister par l'onglet un seuil que le moteur, lui,
ignorait — « profil enregistré ≠ profil appliqué ».

**`NaN` n'est ni une mesure ni une absence**, et la lecture tolérante le
laissait passer : `min`/`max` le propagent en silence, le `json` de la
bibliothèque standard l'écrit **et** le relit, et un seuil `NaN` rend toute
comparaison du moteur fausse — donc un pincement qui ne se déclenche jamais,
sans une ligne nulle part. L'écriture le refusait déjà par accident (aucune
comparaison de borne n'est vraie face à lui) ; les deux portes le nomment
maintenant. Même famille que `Number(null)`, et même règle : une valeur fausse
se refuse, elle ne se remplace pas — c'est aussi pourquoi `quality` illisible
rend `null` des deux côtés au lieu d'être posée sur son **plancher** `0`, qui
était une valeur inventée indiscernable d'une qualité mesurée nulle.

**Application, et elle est relisible.** `controller.options()` rend désormais
`hands.{left,right,unknown}.{primary,secondary}.{pressRatio,releaseRatio}` en
plus des cinq valeurs de la Slice 07 : sans cela, « profil enregistré » et
« profil appliqué » n'étaient pas distinguables, et un profil par main est plus
invisible encore, puisque rien à l'écran ne le montre. Les seuils par main
entrent par `deps.handOverrides(handedness, channel)`, que le moteur interroge
pour chaque main qu'il construit **et** quand la latéralité d'une piste change
— sans quoi une main garderait les seuils de la latéralité qu'on lui avait
d'abord prêtée.

**Trois paires dangereuses de plus** (neuvième, dixième, onzième de la tâche),
refusées à la construction de `JarvisBarehandsCalibration.options()`. Elles
échouent toutes de la même façon — en silence, en retombant sur les défauts, ce
qui se lit « l'utilisateur s'y prend mal » :

- `stageTimeoutMs <= stageHoldMs` : l'étape expire pendant que l'utilisateur
  tient la pose. Même espèce que `sleepTimeoutMs <= wakeHoldMs`.
- `pressAt >= releaseAt` : chaque calibration dérive un
  `pressRatio >= releaseRatio` que le contrat refuse — et l'échec se lirait
  « votre pincement n'est pas mesurable ».
- `travelSlopMin >= travelSlopMax` : `clamp` rend la borne basse à tout le
  monde, donc **tous** les utilisateurs reçoivent la même tolérance et
  « calibré » devient indiscernable de « pas calibré ». Même espèce que
  `SETTINGS_BOUNDS` inversé.

**Persistance.** `jarvis/runtime/barehands_profile.py` et
`GET`/`POST`/`DELETE /api/barehands/profile`, sous la clé
`barehands_calibration_profile`. Route et clé **distinctes** de celles des
réglages : un profil n'est pas un choix mais une mesure, il porte son propre
numéro de schéma, et l'écrire ne doit pas revalider les neuf réglages. La forme
du module est reprise de `barehands_test_mode` — `load` tolérant, `apply`
strict à code stable, `describe`, et l'archivage d'un bloc en version étrangère
avant de le remplacer. Une écriture remplace le profil **en entier**,
contrairement aux réglages : fusionner deux séances de mesure sur une même main
sans le dire, alors que la seconde est celle que l'utilisateur vient de juger
nécessaire. Codes de refus :
`barehands_profile_bad_payload`, `barehands_profile_unknown_field`,
`barehands_profile_not_derived`, `barehands_profile_out_of_range`,
`barehands_profile_thresholds_invalid`,
`barehands_profile_thresholds_incomplete`, `barehands_profile_reach_invalid`,
`barehands_profile_handedness_unknown`, `barehands_profile_stage_unknown`,
`barehands_profile_stage_inconsistent`,
`barehands_profile_schema_version_unsupported`.

**Appliquer et effacer sont explicites.** Le parcours montre son rapport et
n'écrit **rien** tant que « Appliquer et enregistrer » n'a pas été pressé ;
quitter (bouton ou Échap) n'écrit rien du tout. Un échec d'enregistrement garde
la coque ouverte avec « Réessayer » — la refermer jetterait une minute de
mesures. « Effacer le profil » (`DELETE`) **retire** le bloc au lieu de le
remplir de nulls, pour que « aucun profil » et « profil vide » se relisent
pareil — et **range** d'abord un bloc en version étrangère sous sa clé
d'archive, exactement comme l'écriture. Il ne le faisait pas : `load` rend un
profil vierge pour une version qu'il ne sait pas lire, donc `calibrated` valait
`False` et le journal annonçait « il n'y avait rien de calibré » **en
détruisant** une calibration écrite par un Jarvis plus récent — l'inverse exact
du constat R6. Le bouton était désarmé pour ce cas, la route et la voix ne
l'étaient pas.

**Décision 30 : aucun apprentissage continu.** La couture `deps.onMeasure` du
contrôleur n'est posée que **pendant** un parcours et retirée à sa fin ; le
contrôleur teste `typeof deps.onMeasure === 'function'` avant de construire quoi
que ce soit, donc hors calibration le budget d'images est exactement celui
d'avant — l'acquis mesuré de la Slice 02 est intact.

#### Les phases d'une étape (Slice 06, décisions 22 à 24, architecture §7)

**« Étape ouverte = test en cours » était faux, et l'Humain l'a refusé mot pour
mot** : *« le flux actuel commence à chronométrer pendant que l'utilisateur
lit. C'est refusé. »* L'échéance de vingt secondes partait à l'affichage du
titre, donc la consigne se lisait avec une montre déjà lancée contre soi — et
quelqu'un qui gardait les mains sur les genoux échouait à une épreuve qu'il
n'avait jamais commencée.

Une étape traverse maintenant cinq phases, et **une seule chronomètre** :

| Phase | Ce qui tourne | Échéance de mesure |
| --- | --- | --- |
| `INTRO` | lecture, démonstration, barre de lecture | **aucune** |
| `ARMED` | rien ; l'étape attend l'utilisateur | **aucune** |
| `RUNNING` | mesure, chien de garde, compte à rebours | `stageTimeoutMs` |
| `RESULT` | le verdict, tenu `resultMs` | **aucune** |
| `NEXT` | on avance | — |

`createCalibration(...).phase()` rend la phase de l'étape courante, ou `null`
hors étape (récapitulatif, parcours fermé). Elle est publiée parce que
« l'étape est ouverte » et « l'étape mesure » sont devenus deux faits
différents : sans cette porte, un appelant ne pourrait que les deviner.

**Où vit chaque durée.** `introMs` (2 800 ms) est la lecture minimale ;
`resultMs` (1 100 ms) la tenue du verdict ; `stageTimeoutMs` (20 000 ms) ne
court qu'en `RUNNING`, armé par `overlay.deadline(ms)` au moment de la
transition et retiré (`null`) partout ailleurs. La coque n'affiche donc aucun
compte à rebours tant que rien n'est mesuré : un « 0 s restantes » sous une
consigne qu'on lit serait un mensonge. Et l'échéance part **entière** — trois
secondes de lecture ne retirent pas trois secondes à l'exercice.

`overlay.deadline(ms|null)` est la sixième méthode de la coque (après
`regions/mount/clear/flash/flashing`). Elle existe parce que `step()` pose une
échéance *et* vide la scène : une étape qui n'arme sa mesure qu'au moment de
l'engagement ne peut pas repasser par lui sans effacer la démonstration que
l'utilisateur est en train de regarder. La coque garde la montre, le parcours
dit quand elle part. Une durée nulle, négative ou non finie est refusée
(`RangeError`).

**Le chien de garde garde deux emplois**, tous deux invisibles sans lui : c'est
**lui** qui fait finir `INTRO` (personne ne nourrit une étape pendant qu'on la
lit — les mains sont justement sur les genoux), et c'est lui qui solde une
mesure dont les mains ont disparu. D'où la paire dangereuse n° 17 :
`watchdogMs < introMs`, sans quoi c'est la cadence de la montre qui décide du
moment où l'exercice s'arme.

**Ce qui compte comme « l'utilisateur a commencé ».** Un prédicat par étape,
déterministe, qui ne lit que des scalaires déjà publiés par la couture
`deps.onMeasure` et ne réemploie que des seuils qui existent déjà — `band`
(recalculée depuis les défauts du moteur par `wakeBandOf`) et le seuil
d'immobilité du maintien. **Aucun modèle de geste n'est inventé, aucun
algorithme de reconnaissance n'est touché.**

| Étape | Engage quand | Signal lu |
| --- | --- | --- |
| `neutral` | la main est posée | `stillness >= 0.35` |
| `c_pose` | l'écart pouce-index entre dans la bande de réveil | `gapPalms ∈ [band.gapMin, band.gapMax]` |
| `pinch_primary` | le canal primaire se ferme | `primaryRatio < band.releaseRatio` |
| `pinch_secondary` | le canal secondaire se ferme | `secondaryRatio < band.releaseRatio` |
| `aim` | un pincement pouce-index (décision 28) | `primaryRatio < band.releaseRatio` |
| `drag` | idem | `primaryRatio < band.releaseRatio` |
| `resize` | une main sûre est vue | `hands.length >= 1` |

Il faut `engageFrames` images **consécutives** ; une image qui ne qualifie pas
remet le compteur à zéro, donc une main qui passe devant l'objectif
n'accumule pas. Le `c_pose` s'arme sur l'écart seul et **pas** sur le score,
délibérément : exiger le score rendrait injoignable l'échec le plus instructif
de l'étape — un C que le majeur étouffe — puisque l'étape ne démarrerait
jamais. Le `resize` s'arme sur une main et pas deux, pour que
`barehands_stage_needs_two_hands` reste joignable dans le seul scénario qui
porte son nom.

**L'image qui arme n'est pas mesurée.** Le seau part vide à l'entrée en
`RUNNING`, ce qui rend « la mesure commence quand l'utilisateur a commencé »
littéralement vrai — et garde `barehands_stage_no_hand` joignable pour une
étape qui s'arme puis perd ses mains, c'est-à-dire le seul cas où « montrez vos
mains à la caméra » est le conseil utile.

**RÈGLE ZÉRO pendant une phase sans échéance.** La règle interdit un état qui
dure pour toujours *parce qu'un utilisateur ne peut pas distinguer « ça
attend » de « c'est bloqué »*. `ARMED` porte cette distinction autrement :
la démonstration continue de mimer le geste (*ça tourne*), le bandeau de phases
montre « Prêt » allumé et « Mesure » éteint (*quoi*), le compteur de séance de
la coque continue de compter (*depuis combien de temps*), la phrase dit en
toutes lettres que la mesure ne démarre qu'au moment où l'on commence, et trois
sorties restent à l'écran — « Passer cette étape », « Quitter », la croix
permanente, plus Échap (*comment en sortir*). Surtout, `ARMED` **n'est pas un
état de travail** : rien n'y tourne qui puisse se coincer, et la seule chose
qui en sort est un geste de l'utilisateur ou l'une de ses commandes. Y poser
une échéance serait un compte à rebours contre quelqu'un qui n'a rien commencé.

#### Les exercices 1 à 5 et ce qu'ils montrent (Slice 06, décisions 20, 27, 28)

Chaque étape monte sa démonstration dans la région `demo` de la coque, après
`step()` — qui vide la scène — et jamais avant : une main qui survivrait à son
étape ferait faire à l'utilisateur le geste d'une autre consigne. Les postures
viennent **toutes** de `control_center_barehands_hand_art.js` (§15) ; le lien
étape → posture vit dans la calibration, jamais dans le vocabulaire, qui ne
connaît pas les gestes.

| Étape | Postures | Ce qui doit se lire |
| --- | --- | --- |
| Main au repos | `rest` | une main ouverte, immobile |
| Posture de réveil | `wake_c` | **pouce et index seuls** dessinent le C (décision 27) |
| Pincement pouce-index | `pinch_primary_open` ↔ `pinch_primary_closed` | fermer et rouvrir, le majeur dressé hors du geste |
| Pincement pouce-majeur | `pinch_secondary_open` ↔ `pinch_secondary_closed` | même grammaire, index replié, aucun doigt levé |
| Viser et cliquer | `pinch_primary_open` ↔ `pinch_target` | on **pince** la cible, jamais un index tendu (décision 28) |

L'alternation des trois dernières est une **animation CSS**, pas une minuterie :
rien de plus à fermer à la sortie, et `prefers-reduced-motion` l'arrête en
posant les deux postures côte à côte plutôt qu'en supprimant l'information —
figé, un mime ne montrerait qu'une des deux moitiés de « fermer, rouvrir ».
L'invariant n° 1 du vocabulaire (ouvrir et fermer un pincement ne bouge **que**
les deux doigts qui pincent) est ce qui rend l'empilement des deux postures
légitime.

La démonstration est de la **présentation seule** (architecture §8) : elle ne
traverse jamais `feed()`, `KEEP` ne la connaît pas, et rien de ce qu'elle
montre n'atteint un profil.

**L'étape de visée** pose `aimTargets` (3) points répartis sur la surface utile
de la fenêtre (`AIM_SPOTS`, en fractions — la même consigne doit valoir sur un
portable et sur un écran large). Ils n'apparaissent qu'à la **fin de la
lecture** (décision 24) : demander de viser sous une phrase qu'on est en train
de lire, c'est demander de viser avant d'avoir lu. Un seul point est vivant à
la fois (`jf-target`, celui de la coque, qui pulse) ; les autres sont annoncés
en pointillés (`jf-ghost`) et passent au trait plein une fois touchés — le
pointillé dit une région visée, le plein un fait constaté, exactement comme la
mire de `pinch_target` et l'icône d'outil absente de la palette. Rien ne
verdit durablement : le vert reste l'instant d'une reconnaissance (décision 21).

Si l'échéance tombe alors qu'**au moins un** point a été touché, l'étape est
tenue pour réussie : un déplacement de clic a bien été mesuré, et le déclarer
raté ferait retomber la tolérance clic/glissement de quelqu'un qui a
correctement cliqué sur le défaut d'usine. Les règles de repli ne changent pas
pour autant — une visée sans **aucun** clic échoue exactement comme avant, et
une étape ratée laisse toujours ses clés nulles (décision 31).

**Deux feuilles de style, deux propriétaires.** `jarvisFlowStyle` habille la
coque, qui ne sait rien du parcours qu'elle porte — c'est ce qui permet au
tutoriel de la réutiliser telle quelle. `jarvisFlowStepsStyle`
(`DOM.flowStepsStyleId`) habille les démonstrations, le bandeau de phases et le
champ de cibles, qui sont de la calibration et d'elle seule. Les fondre ferait
entrer les gestes dans la coque par la bande.

**Ce que `createCalibration` exige en plus depuis cette slice** : `document`
(le parcours dessine) et `control_center_barehands_hand_art.js` inséré avant
lui. Les deux sont refusés absents à la construction (`RangeError`), comme la
coque et l'horloge : une calibration qui s'ouvrirait sans eux montrerait une
consigne écrite au-dessus d'un centre vide, et « formez un C » ne dirait jamais
lequel.


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
  **filtrée** du jeton, pas son `x` d'affichage, qui se reporte sur l'ancre
  de visée pendant un pincement.

## 12. Canal de commandes du cerveau (décision 6, Slice 12)

Seule section sans `§` d'architecture : elle n'existait pas au découpage. Le
constat **F1** de la Slice 00 a montré que la décision 6 (« le bouton
d'interface **et la voix** activent/désactivent Bare Hands ») n'avait aucun
substrat — ni registre de commandes vocales, ni routeur d'intention, et une
surface Realtime sans aucun outil en `continuous_brain` (Décision 34). Le
chemin réel d'une commande vocale est donc :

```
parole → cerveau (CLI Claude) → outil MCP `jarvis-barehands`
       → POST /api/barehands/commands (Control Center)
       → long-poll de la page → window.JarvisBarehands → reçu
```

**Vocabulaire**, fermé des deux côtés (`jarvis/domain/barehands_command.py`
pour les noms, `control_center_barehands_commands.js` pour ce qu'ils
déclenchent ; test de parité) :

| Commande | Outil du cerveau | Point d'entrée de la page | États de fin acceptés | Aujourd'hui |
|---|---|---|---|---|
| `activate` | `barehands_activate` | `JarvisBarehands.activate()` | `active` | vivant |
| `deactivate` | `barehands_deactivate` | `JarvisBarehands.sleep()` | `sleep` **ou** `off` | vivant |
| `calibrate` | `barehands_calibrate` | `JarvisBarehands.calibrate()` | — (confirmation) | **vivant** (Slice 08) |
| `tutorial` | `barehands_tutorial` | `JarvisBarehands.tutorial()` | — (confirmation) | **alias déprécié** vers la calibration (Slice 07B, § 13) |
| `exit_overlay` | `barehands_exit_overlay` | `JarvisBarehands.exitOverlay()` | — (confirmation) | **vivant** (Slice 09) |

**Un ensemble d'états de fin, pas un état unique.** `sleep()` ne fait rien hors
d'`ACTIVE` : depuis `off` — l'état de **tout onglet fraîchement ouvert** — la
page reste en `off`. Exiger `sleep` faisait de « mets les mains en veille » un
refus `barehands_lifecycle_refused`, dont la phrase rendue au cerveau accuse la
caméra ; personne n'avait touché la caméra, la main ne tournait simplement pas.
« Ne pilote plus » est vrai en `sleep` comme en `off`, donc les deux sont
acceptés et rien à faire se dit `duplicate`. `error` n'est **pas** accepté :
là, quelque chose est cassé, et c'est le seul cas où la phrase sur la caméra
dit la vérité. `duplicate` est choisi sur « l'état n'a pas changé », pas sur
« l'état vaut la cible ».

Ce sont **exactement** les points d'entrée du bouton : `#barehandsWake` appelle
`setAwake`, et `JarvisBarehands.activate`/`sleep` *sont* `setAwake(true/false)`.
Conséquence visible et testée : une commande vocale redessine le panneau
Expérimental, parce que `setAwake` finit par `refreshPanel()`.

**Quatre portes de la surface restent délibérément hors de la table.**
`enable`/`disable` : non parce que l'interrupteur appartiendrait à
l'utilisateur — il ne lui appartient plus —, mais parce que ce canal transporte
le **cycle de vie** (veille, réveil, parcours) et que l'interrupteur maître est
un **réglage**. Le cerveau le lit et l'écrit par le serveur MCP de réglages, qui
passe par `GET`/`POST /api/barehands` sur la clé `barehands_test_mode.enabled`,
appliquée à chaud. Ce qu'il faut savoir avant d'écrire, et que le cerveau peut
dire à l'utilisateur, tient dans une **asymétrie mesurée** : éteindre prend
effet tout de suite — le courtier de commandes relit le réglage à chaque appel
et refuse `barehands_disabled` (409) —, tandis qu'**allumer** ne fait pas
apparaître les outils `jarvis-barehands` dans la session en cours, parce que les
arguments `--mcp-config` sont figés au lancement du CLI ; ils n'arrivent qu'au
prochain (re)démarrage du cerveau. Éteindre par la voix lui retire donc, tout de
suite, l'outil qui vient de servir : c'est une conséquence à annoncer, pas un
motif de refus. `settings` et `tool` : la QA de la Slice 07 a mesuré que `tool('scissors')` normalisait vers
`pointer`, enregistrait, n'affichait rien et **rendait un succès**, ce qui
rendait le refus serveur `barehands_tool_unknown` inatteignable par la page.
**La porte est réparée depuis** (elle refuse un nom inconnu avant de
normaliser, §9), et la décision tient quand même : la défense en profondeur
voulue par la Slice 12 — un canal qui ne transporte que ce qu'il sait vérifier
— ne dépend pas de la solidité de la porte d'en face. Une commande d'outil
n'entrera ici que quand elle aura son propre refus et son propre reçu.

**Issues et codes.** Un reçu porte `outcome` (`applied` | `duplicate` |
`refused`) et le `lifecycle` **relu après l'appel** — jamais l'état demandé.
Les codes de refus de la page sont une liste fermée, refusée côté serveur si
elle s'en écarte :

| Code | Sens |
|---|---|
| `barehands_flow_absent` | le point d'entrée n'existe pas dans cette version |
| `barehands_flow_unconfirmed` | le parcours a été appelé et n'a **pas confirmé** |
| `barehands_lifecycle_refused` | l'état visé n'a pas été atteint (caméra, erreur) |
| `barehands_command_unknown` | la page ne connaît pas ce nom de commande |

Côté serveur : `barehands_disabled` (409), `barehands_command_unknown` (400),
`barehands_command_busy` (409), `barehands_no_visible_page` (504),
`barehands_unknown_command` (404), `barehands_command_expired` (410),
`barehands_command_cancelled` (503), `barehands_bad_request` (400),
`barehands_bad_receipt` (400), `barehands_forbidden_origin` (403) ; côté outil,
`barehands_channel_unreachable`. `barehands_command_expired` a **deux** emplois,
et c'est la même panne vue de deux bouts : 504 pour le cerveau dont la commande
a échu chez une page qui l'avait prise, 410 pour la page dont le reçu arrive
après l'échéance alors que la commande est encore en place (course étroite ; le
reçu tardif ordinaire reçoit 404, la commande ayant déjà quitté la place).
Chaque refus HTTP porte son code dans le corps **et** dans
`X-Jarvis-Error-Code` : le corps est ce qu'un humain lit, l'en-tête ce que le
serveur MCP lit sans analyser une phrase française.

**Un appel qui ne lève pas n'est pas une preuve.** Pour `activate`/`deactivate`
la preuve est l'état relu (`lifecycle()`), parce qu'il en existe un ; `setAwake`
avale ses erreurs dans `view.error` et ne rejette jamais, donc son retour ne dit
rien. Pour un parcours, il n'y a pas d'état observable : il doit **confirmer**
en résolvant `true` ou `{ok:true}`, sans quoi c'est `barehands_flow_unconfirmed`.
Les Slices 08 et 09 héritent de ce contrat — c'est le prix d'entrée pour être
annoncé à l'utilisateur.

**Transport.** Échéance **3 s** (`COMMAND_DEADLINE_S`), plus courte que les 5 s
d'une capture de scène : une capture doit dessiner et téléverser une image, une
commande n'a qu'à traverser un long-poll déjà ouvert. En face, la commande naît
d'une phrase prononcée et le cerveau bloque dessus pendant que la conversation
attend — une commande qui s'exécute quatre secondes après que l'utilisateur est
passé à autre chose est pire qu'un refus. Une commande à la fois ; identifiant
aléatoire à **usage unique**.

**Remise exclusive : une commande, une page.** Le premier long-poll qui la
demande l'emporte ; tout autre onglet reçoit `{"command": null}` et ne la voit
jamais. Ce n'est pas une limite de cadence — la version initiale rationnait la
redistribution à une par seconde sous une échéance de trois, donc une commande
partait jusqu'à **trois** fois, chaque onglet servi appelait le point d'entrée,
et seul le premier reçu était accepté : pour `activate` c'était inoffensif, pour
`tutorial`/`calibrate` deux parcours démarraient et le cerveau n'en voyait
qu'un. Ce qui est perdu en échange est nommé plutôt que caché : une remise qui
n'arrive pas à destination n'est plus rattrapée, et le cerveau l'apprend comme
telle.

**Deux échéances, deux causes, et `deliveries` les sépare.** `deliveries: 0` :
aucun long-poll n'a emporté la commande, donc `barehands_no_visible_page`, et la
phrase (fenêtre fermée, onglet caché, page pas chargée) est vraie.
`deliveries: 1` : une page l'a prise et n'a pas rendu son reçu — typiquement
l'invite d'autorisation caméra du navigateur, qui tient `activate()` bien
au-delà de trois secondes — donc `barehands_command_expired`, et la phrase dit
que l'issue est **inconnue** : ni « c'est fait », ni « ça a échoué ». Le code
unique d'avant envoyait l'utilisateur chercher une fenêtre qu'il avait sous les
yeux.

**Porte, et inertie.** Éteint, il n'y a ni serveur MCP ni consigne système (le
cerveau ne sait pas que ces outils existent), la route refuse
`barehands_disabled` **avant** toute attente, et la page n'ouvre aucun
long-poll. L'interrupteur voyage par `/api/status` (`barehands.enabled`), le
seul battement déjà permanent de la page : **aucune minuterie n'est ajoutée**.
La boucle ne vit que pendant que l'interrupteur est vrai *et* que l'onglet est
visible — un onglet caché ne doit pas prendre une commande qu'il ne peut pas
honorer, et le serveur dira « aucune page visible », ce qui sera vrai.

**Journal** (`runtime/trace.jsonl`, `code` stable dans `data`, identifiant court
commun à toutes les lignes d'une même commande) : `barehands.command_requested`,
`barehands.command_delivered`, `barehands.command_applied`,
`barehands.command_applied`, `barehands.command_expired`,
`barehands.command_abandoned`, `barehands.receipt_refused`, plus
`barehands.tool` / `barehands.tool_failed` et `barehands.server_started` /
`barehands.server_stopped` côté serveur MCP.

**Un événement, un `kind`.** Trois refus de natures différentes partageaient
`barehands.command_refused` avec trois formes de `data` : filtrer la trace
dessus mêlait les refus de transport aux refus de la page. Ils sont séparés —
`barehands.command_disabled` (l'interrupteur est éteint),
`barehands.command_busy` (une autre commande est en vol) et
`barehands.command_refused`, qui ne désigne plus que **la page a dit non**.

**L'identifiant court traverse les deux moitiés.** Il est dans le corps de la
réponse 200 **et** dans le corps d'erreur des refus qui concernent une commande
née, donc `barehands.tool` et `barehands.tool_failed` le portent : la moitié MCP
de la trace se recolle à la moitié courtier autrement que par adjacence de
dates. Un reçu à identifiant **hors forme** laisse lui aussi sa ligne
(`id: null`, `id_chars`) : sans elle, l'attaque la plus grossière était la seule
invisible, alors qu'un identifiant bien formé mais forgé se voyait.

## 13. Tutoriel — retiré, et ce qui reste de son nom (décisions 10 et 17, Slice 07B)

> **Il n'y a qu'un parcours guidé : la calibration.** Le tutoriel séparé a été
> retiré. Son module (`control_center_barehands_tutorial.js`, dix étapes) est
> **supprimé**, son insertion dans la page aussi, et aucun global ne le publie
> plus. Ce n'est pas une désactivation : il n'existe plus de code capable de
> construire une seconde surimpression, ce que l'architecture §9 exige en
> toutes lettres — « ne jamais garder deux parcours ». Une coquille de
> compatibilité qui aurait gardé `createTutorial` aurait laissé la seconde
> machine à états **constructible**, c'est-à-dire vivante.

Ce que la Slice 09 avait construit ici — dix étapes, la liste blanche
d'observation, `assertTeachingOnly`, les deux paires dangereuses, le
récapitulatif — est parti avec le module. La calibration (§ 10) enseigne
désormais : six exercices et un rapport, et ses cinq premiers montrent le geste.

### L'alias déprécié

**Le nom `tutorial` reste au vocabulaire**, et cela relève d'un arbitrage, pas
d'un oubli. Il est miroité sous une assertion de parité qui tourne **au
chargement du module** en trois endroits :

| Fichier | Table |
|---|---|
| `jarvis/runtime/control_center_barehands_commands.js` | `ENTRY_POINTS`, `COMMANDS` |
| `jarvis/domain/barehands_command.py` | `COMMANDS` |
| `jarvis/runtime/barehands_mcp.py` | `TOOL_NAMES`, `TOOL_COMMANDS`, assertion en fin de module |

Le retirer est une rupture coordonnée sur trois fichiers plus leurs tests, et
une désynchronisation fait **échouer l'import** du serveur MCP. L'alias tient le
contrat *et* l'exigence produit : une seule surface visible.

**Il ouvre la calibration, et il le dit.** Le canal rapporte ce que la page
constate, jamais ce qu'on lui a demandé (§ 12) ; un alias qui rendrait `{ok:true}`
nu ferait dire à JARVIS « j'ai lancé le tutoriel » devant une calibration.
`JarvisBarehands.tutorial()` décore donc la confirmation de `startCalibration()`
de `{deprecated:true, reason}`, où `reason` est :

> Commande dépréciée : le parcours de tutoriel a été retiré, c'est la
> calibration qui a été ouverte.

**Un reçu de succès peut désormais porter un `reason`.** Jusqu'ici il ne portait
que la cause d'un refus. Aucun contrat n'a eu à bouger : `parse_receipt` ne
réservait `code` qu'aux refus et acceptait déjà `reason` pour toute issue. Le
canal **recopie** cette phrase, bornée à 200 caractères comme
`MAX_REASON_CHARS` ; il n'en fabrique aucune, et un parcours muet laisse
`reason` nul. Le courtier la renvoie dans son corps 200, et `barehands_mcp` la
colle à sa phrase d'issue : le cerveau lit *« Fait. Commande dépréciée : … c'est
la calibration qui a été ouverte. »*

**Il réveille, contrairement à l'ancien `startTutorial()`.** Celui-ci ne
réveillait délibérément pas : sa première étape *était* le geste de réveil.
Cette étape n'existe plus, et ce qui s'ouvre maintenant est une calibration, qui
ne peut rien mesurer sans voir des mains. Garder la non-veille protégerait une
garantie sans objet et ferait refuser `barehands_calibration_no_camera` à toute
commande vocale `tutorial`.

**Ses refus gardent le nom de ce qui a refusé** —
`barehands_calibration_disabled`, `barehands_calibration_lifecycle_off`,
`barehands_calibration_no_camera` — parce que c'est la calibration qui a refusé.
Les renommer en `barehands_tutorial_*` cacherait lequel des parcours a échoué.
Un refus n'est **pas** décoré : seule une confirmation porte la dépréciation.

L'outil MCP `barehands_tutorial` garde son nom et change sa description : elle
annonce la dépréciation, nomme `barehands_calibrate` comme l'outil à préférer,
et prévient que les refus portent des codes en `barehands_calibration_*`.

Plan de retrait complet et conditions de suppression :
`docs/legacy/barehands-tutorial-retirement.md`.

### `tutorial_seen` : champ de compatibilité

Le réglage persisté (§ 9, `SCHEMA_VERSION = 2`) **reste au schéma et n'est plus
écrit par personne**. Il ne dit plus que « cet utilisateur avait traversé
l'ancien tutoriel avant son retrait », et rien ne le lit pour décider quoi que
ce soit — il ne déclenchait déjà aucun lancement automatique. **Sa case
« Tutoriel déjà vu » a quitté l'onglet** : une case qui interroge l'utilisateur
sur l'achèvement d'un parcours qui n'existe plus n'est pas un réglage.

Le supprimer exigerait de monter `SCHEMA_VERSION` **et**
`SETTINGS_SCHEMA_VERSION` dans le même changement, et ferait refuser
`validate()` (« champ inconnu ») sur toute sauvegarde venue d'une page ouverte
avant le déploiement : une panne réelle, à 400, pour gagner un booléen inerte.
C'est le même arbitrage que pour la commande, et il tombe du même côté.

### Les points d'entrée qui subsistent (§ 12)

| Porte | Rend | Refus |
|---|---|---|
| `JarvisBarehands.tutorial()` | ce que `calibrate()` rend, plus `{deprecated:true, reason}` | ceux de la calibration, sous leurs propres codes |
| `JarvisBarehands.exitOverlay()` | `{ok:true, flow, closed:true}` ; `{ok:true, flow:null, closed:false, already:true}` si rien n'était ouvert | — |
| `JarvisBarehands.tutorialState()` | `{retired:true, replacedBy:'calibration', running:false, seen}` | — |
| `JarvisBarehands.measuring()` | `true` si la couture `deps.onMeasure` du contrôleur est posée, donc si une **calibration** mesure | — |

`tutorialState()` est **gardé** parce que la surface est gelée : retirer un
membre apprendrait moins à son appelant qu'une réponse honnête. Sa **forme**
change, et c'est le point : `installed:false`, `steps:0` et `observed:0` se
liraient comme une panne d'insertion, alors que la vérité est un retrait. C'est
« un refus codé plutôt qu'un défaut plausible » appliqué à un accesseur public.
Aucun code de production ne le lit — la Slice 09 affirmait que le canal de
commandes l'utilisait, ce qui était faux : le canal ne lit que `lifecycle()` et
les méthodes de sa table.

`exitOverlay()` **confirme même quand rien n'était ouvert**, et c'est le
raisonnement de `deactivate` au § 12 : ce que l'appelant demande est qu'il n'y
ait pas de surimpression, et il n'y en a pas. Répondre « non » ferait dire à
JARVIS que ça n'a pas marché devant un écran qui montre l'état demandé.
**Et « rien n'a changé » se dit `duplicate`.** Un parcours n'a pas d'état
relisible (pas de `targets`), donc sa **confirmation** est le seul endroit où la
distinction puisse voyager : le canal lit `already === true` et rend `duplicate`
au lieu d'`applied`. Sans cela JARVIS disait « je l'ai ouvert » à qui redemandait
devant une coque déjà ouverte, et « je l'ai fermée » devant un écran où il n'y
avait rien. Seul le drapeau `already === true` compte ; une valeur vaguement
vraie reste `applied`. Le champ `closed` garde son sens : ce que la page a fait.

### Une commande vocale se voit à l'écran

Issue R13 de la Slice 12, refermée à la Slice 09 et **toujours en vigueur**. Le
canal remet son reçu à la page (`deps.onReceipt` ; `channel.last()` le republie,
`state().last` garde sa forme), et `JarvisBarehands.voice.record(entry)` le
dessine sur trois surfaces, parce qu'aucune seule ne suffit : la **coque** quand
un parcours est ouvert — elle est au-dessus des toasts (`z-index` 2147482000
contre 70), donc c'est la seule qu'on regarde —, un **toast** panneau fermé, qui
est le cas ordinaire d'une commande vocale, et une **ligne du panneau
Expérimental** qui survit au toast et porte l'heure, le nom, l'issue, le code du
refus et le cycle de vie relu. `JarvisBarehands.voice.last()` la rend à la
console.

## 14. Enregistrement, rejeu et mesures (architecture §12, décision 32, Slice 10)

> **Rendre Bare Hands réglable par des faits.** Jusqu'ici un seuil se changeait
> à l'estime : on refaisait le geste, on disait « c'est mieux », et personne ne
> pouvait comparer deux réglages autrement qu'en les revivant. Une séance
> enregistrée une fois se rejoue autant qu'on veut, sous autant de
> configurations qu'on veut, et rend des **nombres comparables**.

`jarvis/runtime/control_center_barehands_recorder.js`
(`window.JarvisBarehandsRecorder`). Inséré après le tutoriel, avant le
pointeur. Miroir serveur : `jarvis/runtime/barehands_trace.py`. Pilote de rejeu :
`jarvis/runtime/barehands_replay.py`. Diagnostic du Test Lab :
`barehands.input_quality` (`jarvis/testlab/official/barehands/`).

### Ce qu'une trace contient — et ce qu'elle ne contient pas

**Aucun point de main. Aucune image. Aucune vidéo. Aucun identifiant.**

La Slice écrivait pourtant « schéma de trace contenant horodatages, **points de
main**, latéralité/confiance, points bruts et filtrés, vitesse/immobilité, états
de geste et de pincement, candidates de cible, captures et issues ». Huit de ces
neuf éléments sont des scalaires dérivés que le contrôleur produit déjà
(§10, couture `deps.onMeasure`). Le neuvième — les vingt et un points d'une
main — est une **reconstruction de la main de l'utilisateur**. Il n'est pas
enregistré, et l'argument est en trois points :

1. **Aucun rejeu nommé par la Slice n'en a besoin.** Le filtre se nourrit de
   `rawX`/`rawY` et d'un horodatage ; l'hystérésis de pincement
   (`createPinchChannel`) d'un **ratio** scalaire ; le résolveur d'une position
   et de rectangles. Aucun des trois ne reçoit de points dans le moteur réel.
   Les points ne serviraient qu'à dériver des traits qui n'existent pas encore,
   c'est-à-dire à changer l'extracteur — hors périmètre de la Slice.
2. **La décision 32 dit « seulement des paramètres dérivés et des mesures de
   qualité ».** Un tableau de points n'est ni l'un ni l'autre.
3. **Et la garantie ne serait pas tenable par intention.** Un enregistreur qui
   *pourrait* recevoir des points n'a besoin que d'une Slice distraite.

Trois mécanismes le tiennent, qui ne se doublent pas — les mêmes que la
Slice 08, dans le même ordre :

- **Une couture qui réduit avant que l'enregistreur ne voie quoi que ce soit.**
  Il est nourri par `deps.onMeasure`, qui a déjà réduit l'image à un
  enregistrement de scalaires. Il ne reçoit pas de points parce qu'il n'en a
  jamais eu : `createRecorder` n'accepte qu'une **liste blanche** de six
  dépendances (`options`, `now`, `log`, `onStop`, `setTimeout`, `clearTimeout`)
  et refuse tout autre nom avec `barehands_trace_cannot_carry_raw_input`.
- **Une liste blanche qui reconstruit clé par clé.** `readFrame`, `readHand`,
  `readCandidate`, `readEvent`, `readGesture`. Ce que le schéma ne nomme pas
  n'atteint jamais la trace — pas parce qu'on le refuse, parce qu'on ne le
  recopie pas. Elle est **idempotente** : une trace relue du disque ou rejouée
  repasse par elle et en ressort identique, sans quoi la géométrie d'une
  candidate (envoyée dans `boundsPx`, stockée à plat) et `onObject` (envoyé
  comme `objectId`, stocké en booléen) disparaîtraient au second passage.
- **Une garde de forme au chargement du module**, pilotée par le schéma :
  `assertDerivedOnly` présente à **chaque clé** de **chaque forme** une suite de
  points, une image en base64 et un objet libre, et porte ses **jumelles bien
  formées** qu'aucun lecteur ne peut refuser en chemin (leçon de la reprise de
  la Slice 08). Refusée, le module **ne s'installe pas** ; la levée est
  contenue, comme au § 13.

Deux réductions de plus : `handTrackId` devient une **fente** (`slot`, 0 ou 1),
et une candidate garde sa géométrie et trois mots de vocabulaires fermés —
jamais son `objectId`, jamais son libellé.

> **`slot` n'a qu'un sens dans ce dépôt, et c'est celui du § 6** : la voie
> stable d'une main, attribuée par `createSlotAllocator` — « une main garde sa
> fente tant qu'elle vit ; une fente libérée est réutilisée ». `traceFrame`
> appelle `interactionView.slotOf(handTrackId)`, le même allocateur que les
> fentes de pointeur et que les évènements de pincement ; l'enregistreur lit la
> fente **portée** et n'a jamais connaissance de `handTrackId`.
>
> Ce paragraphe a décrit un temps une correspondance qui n'existait pas :
> l'enregistreur numérotait les mains par leur **rang dans le tableau de
> l'image**. Le traqueur renumérotant ses mains dès que l'une sort du cadre, la
> fente changeait alors de main en cours de séance — et la voie 0, qui porte
> l'historique du filtre d'une main, se faisait nourrir les coordonnées de
> l'autre. Le mot `slot` voulait donc dire « voie stable » au § 6 et « rang de
> l'image » ici : deux sens pour un mot, exactement ce que ce module interdit
> ailleurs pour `p95`. Un même enregistrement mesurait jusqu'à cinq fois pire
> selon **laquelle** des deux mains quittait le cadre.
>
> La trace d'or ne pouvait pas l'attraper : sa main gauche occupe la fente 0 sur
> ses 225 images. `test_a_hand_keeps_its_lane_when_the_other_leaves_the_frame`
> exerce la perte et le retour, et compare les deux attributions sur les mêmes
> images.

Pour la candidate, son `kind` passe par un vocabulaire
**fermé à nous** (`TRACE_KINDS`), parce que le contrat le laisse en texte libre
(§6) et qu'un type libre est la porte par laquelle un libellé entrerait ; ce qui
n'y est pas devient `other`. Un test de parité le compare à
`JarvisBarehandsTarget.KINDS`.

| Niveau | Clés |
|---|---|
| trace | `schema`, `schemaVersion`, `startedAt`, `durationMs`, `stoppedBecause`, `viewport`, `observedFrames`, `droppedFrames`, `frames` |
| image | `t` (**relatif** au début), `lifecycle`, `hands`, `candidates`, `events`, `gestures` |
| main | `slot`, `handedness`, `primaryRatio`, `secondaryRatio`, `primaryConfidence`, `secondaryConfidence`, `primaryWorldRatio`, `secondaryWorldRatio`, `cPose`, `closure`, `gapPalms`, `indexReachPalms`, `palmNorm`, `rawX/Y`, `filteredX/Y`, `palmX/Y`, `quality`, `stillness`, `speedPxPerSec` |
| candidate | `ref`, `kind`, `region`, `representation`, `actionable`, `x`, `y`, `w`, `h` |
| issue | `type`, `channel`, `onObject` (**booléen**), `axes` (**compte**) |
| geste | `name`, `phase`, `suppressed` |

### Et l'utilisateur le sait

RÈGLE ZÉRO, appliquée à une fonctionnalité qui observe : ce qui observe sans le
dire est ce que personne n'accepte. L'enregistrement est **éteint par défaut**,
ne s'allume que par le bouton « Enregistrer une séance… » de l'onglet
Expérimental ou par `JarvisBarehands.record.start()` — la **même** porte —, et
la section dit en permanence qu'il tourne, combien d'images il a retenues sur
combien vues, depuis combien de temps, dans combien de temps il s'arrêtera, et
ce qu'il ne retient pas. Le bouton « Arrêter » est la sortie.

**Il finit toujours**, de trois façons, et chacune le dit : `asked` (le bouton),
`deadline` (l'échéance, armée par `setTimeout` et **indépendante des images** :
une caméra figée laisserait sinon l'enregistrement en cours pour toujours) et
`max_frames` (le plafond, qui **arrête** au lieu de tronquer en silence — une
trace coupée sans le dire se relit comme une séance courte).

**Deux paires dangereuses de plus** (quinzième et seizième de la tâche),
refusées à la construction :

- `sampleEveryMs >= maxDurationMs` : l'enregistrement dure son temps et rend une
  seule image ; chaque mesure du rejeu serait nulle ou dégénérée et le banc
  d'essai accuserait une configuration là où rien n'a été mesuré ;
- `maxFrames` sous ce que l'échéance annoncée réclame : l'écran promet deux
  minutes, le plafond tombe au bout de vingt secondes. Même espèce que
  `watchdogMs >= stepTimeoutMs` : le budget accordé doit couvrir le temps exigé.

### Ce que cela coûte quand personne n'enregistre : rien

La couture de mesures est **posée sur les dépendances du contrôleur**, pas dans
une branche qu'il évaluerait. Elle a deux consommateurs depuis cette Slice — la
calibration et l'enregistreur —, tenus par un **registre nommé** :
`openMeasureSeam(nom, sink)` / `closeMeasureSeam(nom)`. Deux propriétaires d'une
clé unique auraient fait qu'arrêter l'un arrête l'autre : fermer une
surimpression aurait coupé une séance en cours sans que rien ne le dise.
`JarvisBarehands.measureSeam()` relit **qui** écoute ; sans cette lecture,
« l'enregistreur écoute » et « quelqu'un a fermé la couture sous lui »
s'écrivent pareil.

Hors enregistrement **et** hors calibration, la clé n'existe pas : le contrôleur
ne construit aucun enregistrement de scalaires, et le budget d'images est
exactement celui d'avant. Un test le mesure sur le vrai contrôleur.

### Le rejeu

`JarvisBarehands.record.replay(trace, config)` et `.compare(trace, configs)`
côté console ; `python -m jarvis barehands-replay <trace> --config NOM=JSON …`
côté terminal ; `barehands_replay.compare()` côté code.

**Il ne réimplante rien** : les moteurs du rejeu sont `createPointerFilter`,
`createPinchChannel` et `createTargetResolver` du bloc pur, reçus par
`deps.core`. Un rejeu qui referait le filtre dans son coin mesurerait sa propre
copie, et le jour où les deux divergeraient c'est le banc d'essai qui aurait
raison contre le produit. C'est aussi pourquoi le pilote Python **appelle node**
au lieu de traduire : une traduction est une seconde implantation.

**Déterminisme** : ni horloge, ni hasard, ni réseau, ni DOM — il lit les
horodatages de la trace. Deux exécutions rendent des nombres identiques, ce
qu'un test affirme en les comparant sérialisés.

**Quatre axes**, fermés et publiés (`REPLAY_AXES`) : `filter`, `thresholds`,
`assistance`, `resolver`. Un axe inconnu est **refusé** : accepté, il serait une
configuration sans effet, et deux colonnes identiques se liraient « ce réglage
ne change rien » au lieu de « ce réglage n'a pas été appliqué ».

**Une version inconnue se refuse** (`barehands_trace_version_unsupported`),
elle ne se devine pas : devinée, elle rendrait des nombres sans rapport avec ce
qui a été enregistré — et ils seraient crus, parce qu'ils ont la forme de
mesures.

### Les mesures

Douze, toutes des **faits** : un compte, un quantile ou un rapport de comptes.
Rien n'est pondéré, rien n'est noté. Une mesure qu'on ne peut pas établir rend
`null` — jamais zéro, qui se lirait « mesuré, et parfait ». Les distances sont
en **fraction de la largeur d'image**, la seule unité qui survive à un
changement de résolution (même choix que `travelSlopNorm`, §10).

| Mesure | Unité | Ce qu'elle dit |
|---|---|---|
| `replay.frames_count` | compte | combien d'images ont été mesurées — ce qui dit ce que vaut le reste |
| `click.target_success_ratio` | rapport | clics et clics droits qui avaient une candidate **résolue** sous la main |
| `pointer.error_p50_norm` | rapport | médiane de l'écart du point filtré au point brut |
| `pointer.error_p95_norm` | rapport | 95e centile du même écart |
| `pointer.stationary_jitter_p95_norm` | rapport | le même, **seulement** quand la main est immobile |
| `pinch.false_primary_hz` | Hz | cycles pouce-index appuyé-relâché trop courts pour avoir été voulus |
| `pinch.false_secondary_hz` | Hz | le même, sur le canal pouce-majeur |
| `gesture.false_positive_hz` | Hz | gestes globaux **étouffés** parce qu'une capture était tenue (§4) |
| `interaction.latency_p50_ms` | ms | du contact à son issue |
| `hand.loss_recovery_p95_ms` | ms | de la perte d'une fente à son retour |
| `drag.continuity_ratio` | rapport | part des images de glissement qui en continuaient un |
| `resize.two_hand_stability_ratio` | rapport | part des images de redimensionnement qui avaient encore deux mains |

### Où la trace va

`POST /api/barehands/traces` → `<runtime>/barehands-traces/<horodatage>-<empreinte>.json`,
et **une** ligne dans `runtime/trace.jsonl` par enregistrement
(`barehands.trace_recorded`, code stable dans `data`). Le serveur repasse le
document par la liste blanche : le module JS est de notre côté, le réseau ne
l'est pas — même partage des rôles qu'au § 10. Trois refus codés, rendus dans
`X-Jarvis-Error-Code` : `barehands_trace_schema_unknown`,
`barehands_trace_version_unsupported`, `barehands_trace_invalid`. Un échec
d'envoi est dit à l'écran, journalisé, et la trace **reste lisible dans la
page** (`record.trace()`) : une séance ne se perd pas par une panne de réseau.

### Le banc d'essai

`barehands.input_quality` v1, profil `virtual`, aucune capacité requise, coût
nul. Il rejoue une **trace d'or synthétique**
(`jarvis/testlab/fixtures/barehands/golden.v1.json`) sous la configuration que
ses cinq paramètres décrivent. Elle est synthétique exprès : une trace d'or
versionnée dans un dépôt ne doit être la séance de personne. Elle contient
délibérément un clic **de peu à côté** — trente pixels sous un bouton —, sans
quoi changer l'assistance ne changerait aucun nombre et le banc d'essai
conclurait « ce réglage ne sert à rien » d'une séance incapable de le montrer.

Trois assertions bloquantes : assez d'images mesurées, le tremblement au repos
sous un centième de largeur d'écran, et la majorité des clics sur leur cible.
Node absent rend `MeasurementUnavailable` — une mesure qu'on n'a pas pu prendre
n'est pas une mesure à zéro.

### Ajouter un autre traqueur au même banc

Rien du rejeu ne connaît MediaPipe : il lit une trace. Un traqueur futur
(gant, caméra de profondeur, autre modèle) n'a donc qu'à **produire le même
schéma** — les mêmes scalaires dérivés, par la même couture `deps.onMeasure` —
pour être mesuré par les mêmes douze mesures et comparé au précédent sur une
séance identique. Ce qui changerait, si son vocabulaire différait, est une
version de schéma : `schemaVersion` monte, l'ancien rejeu **refuse** la nouvelle
plutôt que de la deviner, et les deux versions cohabitent sur le disque.

## 15. Mains schématiques (décision 20 de l'affinage d'UI)

Implémentation canonique :
`jarvis/runtime/control_center_barehands_hand_art.js`
(`window.JarvisBarehandsHandArt`), logique pure, sans DOM tant qu'on ne lui
passe pas de document. Couverte par `tests/unit/test_barehands_hand_art_js.py`.

**Un seul vocabulaire de dessin pour toute la fonctionnalité.** La Slice 01
avait tracé une main en trait pour l'icône du contrôle de cycle de vie ; la
carte d'aide en demande cinq de plus et la calibration en demandera autant. Ce
module est l'endroit unique où ces mains existent. Deux jeux auraient dérivé au
premier ajustement, et le symptôme aurait été un utilisateur qui ne reconnaît
pas, dans la calibration, la main apprise dans l'aide.

**Décision 20, littéralement :** trait schématique, presque robotique, et
surtout pas d'anatomie. Moins précis qu'une photo, délibérément. Ce qu'un
dessin doit faire comprendre, c'est *quels doigts bougent et où ils se
touchent*.

### Le vocabulaire

Grille `0 0 24 24`, trait `1.5`, bouts et jointures ronds, `currentColor`.
Point plein (`r = .95`) à l'articulation de chaque doigt. Anneau au trait
(`r = 1.5`) au point de contact d'un pincement fermé. Anneau **en pointillés**
(`r = 3`, motif `2.5 2.5`) pour une région visée — le même motif discontinu que
l'icône d'outil sans moteur de la palette, et pas un troisième langage.

Une posture est **une ligne de table**, pas un SVG dessiné à la main : cinq
doigts, chacun une polyligne de deux à quatre points, plus un point
d'articulation par doigt et d'éventuelles marques. Un seul traceur les
sérialise toutes.

### Les sept postures

| `POSE` | ce qu'elle montre |
| --- | --- |
| `rest` | main ouverte au repos. **Exactement** le tracé servi depuis la Slice 01 : c'est l'icône du bouton et des trois pastilles du sélecteur. |
| `wake_c` | la posture en C (décision 27) : pouce et index, et eux seuls, dessinent un C largement ouvert ; les trois autres doigts sont repliés. |
| `pinch_primary_open` / `pinch_primary_closed` | pincement pouce-index. Le majeur reste **tendu**, hors du geste. |
| `pinch_secondary_open` / `pinch_secondary_closed` | pincement pouce-majeur. L'index est **replié** et le majeur descend : aucun doigt dressé, silhouette franchement différente. |
| `pinch_target` | le pincement visé (décision 28) : le primaire fermé, doigt pour doigt, **plus** un anneau de mire. Jamais un doigt qui pointe. |

### Les invariants, et ce qu'ils achètent

Trois sont épinglés par des tests parce qu'ils sont ce qu'un consommateur peut
supposer sans relire le fichier :

1. **Ouvrir et fermer un pincement ne bouge que les deux doigts qui pincent.**
   Sans lui, une animation ferait sauter la main entière d'une image à l'autre.
2. **Le point de contact est le même pour les deux canaux.** Ce qui distingue
   un pincement de l'autre est le chemin, donc le doigt, donc le sens.
3. **L'ouverture du C se situe entre celle d'un pincement ouvert et celle
   d'une main ouverte**, ce qui est exactement ce que `cPoseScore` mesure : en
   dessous de `wakeGapMin` c'est un pincement en cours, au-dessus de
   `wakeGapMax` c'est une main ouverte (§ 4).

### La surface

`pose(id)` · `poses()` · `handShapes(spec)` · `handSvg(document, spec)` ·
`handMarkup(spec)`, plus les tables `POSE`, `POSE_ORDER`, `DIGIT`,
`DIGIT_ORDER`, `POSES`. `spec` = `{pose, size, mirror, className, title}`.

`handSvg` et `handMarkup` lisent tous deux `handShapes` : **deux sérialiseurs,
un seul dessin**, et un test les compare forme par forme. Un `title` fourni
rend l'image annoncée (`role="img"`) et lui retire `aria-hidden` ; sans lui
elle est décorative, ce qu'est une icône à côté de son libellé. `mirror` pose
la transformation sur un `<g>` interne, jamais sur la racine, qui emporterait
le `<title>`.

**Ce module ne connaît pas les gestes.** Il ne lit pas les contrats, ne nomme
aucun `GESTURE` et ne dit à personne ce qu'une posture déclenche : c'est un
alphabet de formes. Lier une posture à une action appartient à qui affiche. Si
le dessin connaissait les gestes, l'aide aurait un second contrat de gestes,
et c'est ce que le § 16 existe pour empêcher.

**Un refus codé plutôt qu'un défaut plausible :** une posture inconnue lève
`barehands_hand_pose_unknown` et ne retombe **pas** sur `rest`. Un écran qui
montre une main ouverte là où on attendait un pincement enseigne le mauvais
geste, et rien ne le signale.

## 16. Aide et diagnostic rapides (décisions 15 et 16 de l'affinage d'UI)

Implémentation : `control_center_barehands_hud.js` — le même module que le
contrôle de cycle de vie et la palette, pour la même raison qu'à la Slice 03 :
même famille, même feuille, mêmes jetons de ton, et les phrases du sélecteur de
mode y sont déjà écrites une fois. Couverte par
`tests/unit/test_barehands_cards_js.py`.

Une seule carte ouverte à la fois, un seul emplacement (`#barehandsCards`,
rang 82 — au-dessus du menu contextuel qui les ouvre, en dessous de la
confirmation en page). Elles s'installent dans un **troisième** `try` : un
emplacement oublié coûte les cartes, jamais le contrôle de cycle de vie.

### L'aide n'est pas un second contrat de gestes

C'est la contrainte dure, et elle vaut plus que la mise en page. Tout ce qui
peut être lu du contrat l'est :

- les trois états et leurs conséquences sont les phrases du sélecteur de mode
  (`MODE_HINT`, `CAPTION`), pas une seconde rédaction ;
- les durées viennent de `WAKE_HOLD_MS`, `SLEEP_TIMEOUT_MS`,
  `WAKE_INTERVAL_MS`. Le retour en veille est annoncé comme un **défaut**,
  parce qu'il est réglable (§ 9) ;
- les doigts de chaque canal viennent de `PINCH_FINGERS` ;
- les couleurs viennent de `feedbackRole()` **appelée** et de
  `FEEDBACK_TOKENS`, jamais d'une table recopiée ;
- la liste des gestes vient de `GESTURES`.

Ce qui ne peut pas se lire du contrat, c'est la **liaison** geste → action :
elle vit dans le moteur d'interaction. Une seule table la porte
(`GESTURE_BOUND`), et les gestes **non liés sont déduits par soustraction**.
Conséquence voulue : un geste ajouté demain au contrat arrive « sans effet
annoncé » plutôt que promis. Promettre une action que personne n'a branchée est
la faute que cette règle existe pour empêcher.

Aujourd'hui, `GESTURE_BOUND = [c_pose]` — le réveil, par `createWakeDetector` /
`cPoseScore` dans `watch()`. Main ouverte, poing, double fermeture et
claquement sont mesurés et publiés à chaque image et **rien ne les écoute** :
la carte les nomme, sans dessin et sans verbe, dans un bloc qui dit son nom.

Le **pincement secondaire**, lui, est présenté comme une commande au même rang
que le primaire, parce qu'il en est une : il publie `INTERACTION.CONTEXT` (§ 7)
et le pointeur le dépose en un vrai `contextmenu` du DOM.

### Ce que la Slice 04 a supprimé, et pourquoi

Le bloc « Gestes » de l'onglet Expérimental et sa clé `SECTION.gestures` sont
**partis**. Deux de ses phrases étaient devenues fausses :

- il rangeait le pincement pouce-majeur parmi les « reconnus, pas encore
  agissants » — il est lié ;
- il annonçait « pas de glisser-déposer ni de défilement » — `DRAG_START`,
  `DRAG_MOVE`, `DRAG_END` et `SCROLL` sont tous implantés (§ 7), et `SCROLL`
  défile vraiment l'hôte.

Une aide fausse est pire qu'une aide absente : elle se lit comme un contrat.
Rien de l'ancien bloc n'a donc été recopié. La clé n'est pas conservée « au cas
où » non plus : publiée sans que rien ne la dessine, `showSettings` aurait rendu
`{ok:true}` après n'avoir rien montré. `showHelp()` **refuse** sous
`barehands_help_unavailable` quand la carte manque, faute de tout repli.

### Les quatre phrases vraies qui étaient parties avec, et où elles sont

Le bloc supprimé portait deux phrases fausses — c'est ce qui l'a tué — mais
**quatre phrases vraies** sont mortes avec lui. Elles n'avaient pas leur place
dans une carte de gestes, et les y remettre aurait rouvert le mur de texte que
la Slice 04 a eu raison de fermer. Elles ont donc chacune leur place, et le
critère est **la question à laquelle elles répondent** :

| Phrase | Question | Où elle vit |
|---|---|---|
| Le jeton rond suit l'index, grossit au survol, son anneau se remplit au pincement, il se fige pour viser, le clic dépose une onde | « qu'est-ce que je regarde ? » | carte d'aide, bloc **« Ce que vous voyez à l'écran »** (`helpModel().reading`) |
| Le jeton pâle et pointillé est une main que le suivi ne tient pas pour sûre : affichée, cliquable, mais elle ne retarde pas le retour en veille | idem | idem |
| Une liste déroulante ne s'ouvre pas au pincement | « pourquoi ça n'a pas marché ? » | réglages, bloc **« Deux limites connues »** (`limitsHtml()`) |
| L'iframe ai-visualizer ne reçoit pas les clics | idem | idem |

**Pourquoi les deux premières ne sont pas allées aux réglages.** C'est la RÈGLE
ZÉRO qui tranche : un jeton pâle qu'on ne sait pas lire est exactement le cas
où « ça marche » et « c'est cassé » se ressemblent. La réponse doit donc être à
un clic de l'écran où la question se pose — clic droit, Aide — et non dans un
modal de configuration que personne n'ouvre en pleine session.

**Pourquoi les deux dernières ne sont pas allées à l'aide.** Ce sont des
**limites**, pas une légende : elles ne décrivent rien à l'écran, elles disent
ce qui ne marchera pas. La décision 14 range cela du côté des réglages — cet
onglet est de la configuration, et une limite assumée est de la documentation,
pas une action de session. Le bloc **ferme** la section plutôt que de
s'intercaler entre deux contrôles, ne porte ni case ni curseur, et n'entre donc
pas dans le compte des « six réglages ci-dessus » que le bouton de
réinitialisation annonce.

Les deux limites sont **structurelles**, pas des défauts à corriger un jour :
le navigateur réserve l'ouverture d'un `<select>` à un événement de confiance,
et `document.querySelectorAll` ne traverse pas la frontière d'une iframe — le
visage ai-visualizer en est une (`control_center.html:730`). Si l'une des deux
cessait d'être vraie, c'est la phrase qu'il faudrait retirer, pas la limite.

La contrainte du § 16 tient dans les deux nouveaux blocs : les doigts viennent
de `PINCH_FINGERS`, la durée de veille de `SLEEP_TIMEOUT_MS`. Et la pastille
des mains est décrite par **ce qu'elle compte**, jamais par son littéral
« MAINS · 1/2 » — ce libellé vit dans `control_center_barehands.js`, n'est pas
un contrat, et le citer ferait mentir l'aide le jour où il change. Couvert par
`test_the_token_legend_returns_the_true_sentences_slice_04_deleted` et
`test_the_settings_carry_the_two_known_limits`.

### Le diagnostic, et la RÈGLE ZÉRO

Décision 16 : un raccourci vers l'enregistreur existant, pas une seconde
implantation. La carte appelle `record.start()`, `record.stop()` et
`record.state()` — **les mêmes portes** que les deux boutons de l'onglet, qui
restent en place pour le rejeu et la comparaison (§ 14). Rien de ce qui est
retenu ni de ce qui est conservé ne change.

La Slice 02 avait refusé de démarrer une capture depuis un menu qui se
referme : rien à l'écran ne l'aurait datée ni arrêtée. Ce raisonnement tient, et
la carte le **satisfait** au lieu de le contourner. Pendant une capture elle
porte les quatre exigences : un témoin qui bat et une barre qui balaie (ça
tourne), « Enregistrement en cours » (quoi), le temps écoulé **et** le temps
restant relus chaque seconde (depuis combien de temps), un bouton Arrêter, Échap
et l'échéance (comment en sortir). L'échéance et le plafond d'images sont
annoncés **avant** de démarrer, lus de `DEFAULTS` de l'enregistreur et non
écrits ici.

Le battement d'une seconde n'est pas un détail : c'est lui qui voit une séance
arrêtée par son échéance ou par son plafond d'images, que personne n'a
demandée. Sans lui, la carte annoncerait une capture terminée comme si elle
durait.

La phrase de confidentialité est reprise **mot pour mot** de l'onglet : deux
formulations de la même promesse finissent par ne plus promettre la même chose.

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

La Slice 05 implante la résolution de cible et le retour visuel de visée
(§6, décisions 3, 8, 9, 16, 23, 24). Elle est en **deux moitiés, et c'est le
sujet** : la géométrie et l'hystérésis sont pures et vivent dans
`JarvisBarehandsCore.createTargetResolver` (`control_center_barehands.js`), où
node les teste sans DOM ; la lecture de l'arbre et le dessin vivent dans un
**module de page à part**, `control_center_barehands_target.js`
(`window.JarvisBarehandsTarget`). C'est la première Slice à ajouter un module,
donc la première à faire compter l'ordre d'insertion (constat F3 de la
Slice 00) : il se place après les contrats, qu'il lit, et avant le pointeur,
qui le lit.

Deux raisons de le séparer du pointeur plutôt que de l'y fondre : il **lit la
page entière** (nœuds de scène, boutons, onglets, champs), ce qui n'est pas une
responsabilité du suivi des mains ; et son coût — un `querySelectorAll` et un
rectangle par candidate — n'est jamais payé par une session au repos. C'est la
décision produit qui paie la performance : sous intention (décision 3) le
balayage est refait à chaque image ; en survol (décision 3 bis) il est
échantillonné à 90 ms et seul le filtrage par point suit la main. D'où la
séparation de `survey()` (la lecture d'arbre) et de `near(liste, point, portée)`
(l'arithmétique), `collect(point, portée)` restant leur composition.

Elle apporte aussi le constat F4 de la Slice 00, corrigé : `.sc-node` était
**absent** du sélecteur de survol historique, donc une étoile de la scène était
cliquable sans n'avoir jamais été surlignée. Elle est ici la candidate la plus
intéressante de toutes, puisque c'est la seule qui ait des zones. Couverte par
`tests/unit/test_barehands_target_js.py`. Trois constantes nouvelles dans
`DEFAULTS` (`targetZonePx`, `targetZoneHoldPx`, `targetZoneMaxRatio`), chacune
avec son invariant refusé à la construction.

La Slice 06 implante le moteur de captures (§7) : `createInteractionEngine` dans
le bloc pur, la sortie de compatibilité DOM et l'adaptateur de scène dans le bloc
navigateur, la couture `window.JarvisScene.frames` dans la page de scène, et
`resizeBySides` / `manipulateBox` / `rebaseManipulation` dans
`control_center_scene_interact.js` — la géométrie existante étendue, pas une
seconde. Couverte par `tests/unit/test_barehands_interaction_js.py`. Aucun module
de page n'est ajouté ; une dépendance de chargement l'est (voir « Insertion dans
la page »). Aucune constante nouvelle dans `DEFAULTS`.

La Slice 07 implante les outils et les réglages (§8, §9, décisions 24 et 25) :
`TOOL_CAPABILITY` / `SERVED_CAPABILITIES` / `describeTools` / `SETTINGS_BOUNDS`
/ `SETTINGS_WIRE_KEYS` / `fromServerState` dans le contrat ; `setTool` et la
porte outil/cible dans `createInteractionEngine` ; `controller.configure` et la
septième paire dangereuse dans le contrôleur ; la palette, les réglages et la
lecture de diagnostic dans le bloc navigateur ; et les neuf réglages dans
`jarvis/runtime/barehands_test_mode.py` (schéma v2, `load` tolérant, `apply`
strict). Couverte par `tests/unit/test_barehands_tools_settings_js.py`. **Aucun
module de page ajouté** — le constat F3 ne s'applique pas, l'ordre
`contracts → target → barehands → scene page` est intact — et **aucune
constante nouvelle dans `DEFAULTS`** : les deux nombres que les réglages
déplacent (`sleepTimeoutMs`, et `clickSlopPx`/`dragSlopPx` par `sensitivity`)
existaient déjà.

La Slice 08 implante la calibration (§ 10, § 11, décisions 26 à 32) :
`control_center_barehands_calibration.js` — **un module de page ajouté**, donc
l'ordre d'insertion a changé (voir « Insertion dans la page ») —,
`jarvis/runtime/barehands_profile.py` avec ses trois routes,
`JarvisBarehands.calibrate()` / `.profile()` / `.calibration()`, la couture
`deps.onMeasure` du contrôleur, les seuils par main dans
`createPinchIntentEngine`, et le profil en **version 2**. Couverte par
`tests/unit/test_barehands_calibration_js.py` et
`tests/unit/test_barehands_profile.py`. Aucune constante nouvelle dans
`DEFAULTS` du moteur : les nombres du parcours vivent dans les siens, et les
deux tolérances qu'il déplace existaient déjà.

`window.JarvisBarehands.calibrate()` est **branché** : la voix et le bouton
passent par la même porte, et le canal de la Slice 12 n'a pas changé d'une
ligne pour ça — c'était la promesse de sa table.

> **Périmé depuis la Slice 07B pour tout ce qui concerne le tutoriel** : le
> module et son fichier de tests ont été supprimés, et la commande est devenue
> un alias déprécié vers la calibration (§ 13). Le paragraphe est gardé comme
> trace de ce qui a existé.

La Slice 09 implante le tutoriel et les deux dernières portes de la voix
(§ 13, décisions 6 et 26) : `control_center_barehands_tutorial.js` — **un
module de page ajouté**, donc l'ordre d'insertion a changé (voir « Insertion
dans la page ») —, `JarvisBarehands.tutorial()` / `.exitOverlay()` /
`.tutorialState()` / `.voice`, la section Tutoriel et la ligne « dernière
commande vocale » de l'onglet Expérimental, et deux ajouts ailleurs : la coque
**refuse** un statut de rapport qu'elle ne sait pas dessiner (§ 13), et le
canal de la Slice 12 **remet son reçu** à la page (`deps.onReceipt`,
`channel.last()`) sans que `state().last` change de forme. Couverte par
`tests/unit/test_barehands_tutorial_js.py`. Aucune constante nouvelle dans
`DEFAULTS` du moteur : le tutoriel n'en règle aucun, il en parle.

`window.JarvisBarehands.tutorial()` et `.exitOverlay()` sont **branchés** : les
cinq commandes du § 12 ont désormais leur point d'entrée, et le canal n'a
changé que pour *donner* son reçu à l'écran — jamais pour router une commande.
`tutorialSeen` est **lu** pour la première fois (§ 13).

La Slice 10 implante les diagnostics enregistrés (§ 14, architecture § 12,
décision 32) : `control_center_barehands_recorder.js` — **un module de page
ajouté**, donc l'ordre d'insertion a changé (voir « Insertion dans la page ») —,
`JarvisBarehands.record` (`start` / `stop` / `state`), le rejeu hors ligne
`python -m jarvis barehands-replay` (`jarvis/runtime/barehands_replay.py`), les
mesures et le banc d'essai. Couverte par
`tests/unit/test_barehands_recorder_js.py` et `tests/unit/test_barehands_trace.py`.

**Une trace ne contient que des scalaires dérivés** : jamais une image, jamais
un point de repère, jamais un identifiant de machine (§ 14). C'est la même
promesse que le profil de calibration, tenue par le même moyen — ce qui sort de
la caméra est réduit avant d'être écrit, et rien ne remonte la pente.

La Slice 12 implante le canal de commandes du cerveau (§ 12, décision 6) :
`jarvis/domain/barehands_command.py` (vocabulaire, bornes, codes),
`jarvis/runtime/barehands_commands.py` (le courtier, calqué sur
`jarvis/core/scene_capture.py`), trois routes sur `/api/barehands/commands`,
`jarvis/runtime/barehands_mcp.py` (serveur stdio `jarvis-barehands`, cinq
outils) et `jarvis/runtime/control_center_barehands_commands.js` — **un module
de page ajouté**, donc l'ordre d'insertion a changé (voir « Insertion dans la
page »). Couverte par `tests/unit/test_barehands_command_channel.py` et
`tests/unit/test_barehands_commands_js.py`. Aucune constante nouvelle dans
`DEFAULTS` : le canal ne règle rien, il transporte.

`window.JarvisBarehands.activate()` / `.sleep()` / `.lifecycle()` sont
désormais **branchés** : la voix et le bouton passent par le même `setAwake`.
`.settings(patch)` et `.tool(name)` restent **hors** du canal tant que leur
succès n'est pas vérifiable (§ 12) ; `.captures()` / `.interactions()` /
`.diagnostics()` sont ce que la Slice 10 lira.


---

## Ce que l'affinage d'UI a changé, et ce qu'il a fermé

Le registre ci-dessus raconte **Bare Hands V1**, livré et fusionné dans `main`.
Ce qui suit raconte la tâche d'**affinage d'UI et de calibration** qui s'est
posée dessus. Les deux tâches numérotent leurs Slices à partir de 1, donc
« Slice 08 » ne désigne pas la même chose dans les deux moitiés : la Slice 08 de
V1 est la calibration, la Slice 08 de l'affinage est l'intégration. Les Slices
de cette moitié-ci sont nommées « affinage » quand la confusion est possible.

L'affinage n'ouvre **aucune sémantique d'interaction** : les captures, les
gestes, le suivi, le canal de commandes et le profil sont ceux de V1, et aucun
outil n'est entré dans la palette. Ce qui change est l'**architecture d'accès**
— où l'on allume, où l'on choisit un outil, où l'on obtient de l'aide — et
l'**UX de la calibration**.

**La hiérarchie finale de l'interface**, en quatre surfaces et pas une de plus :

| Surface | Ce qu'on y fait | Où |
|---|---|---|
| Contrôle de cycle de vie | allumer, endormir, activer, éteindre | contrôle autonome à **icône de main**, en haut à gauche, hors du dock |
| Palette d'outils | choisir Pointeur / Main / Sélection, en un clic | bande verticale **fixe** au bord gauche, sous la main |
| Actions rapides | Réglages, Calibration, Aide · Gestes, Diagnostic | **clic droit** sur le contrôle de cycle de vie |
| Réglages | configurer — et rien d'autre | onglet Expérimental, ouvert depuis les actions rapides |

La règle qui les sépare est la décision 14 : l'onglet est de la
**configuration**, pas un tableau de bord d'interaction. Trois blocs en sont
sortis et ne doivent pas y revenir — l'interrupteur et le bandeau de cycle de
vie (deux commandes pour un même état se contredisent le jour où l'une des deux
ne se rafraîchit pas), les **outils** (une palette atteignable en pleine
session, ce qu'un modal n'est pas), et le **tutoriel** (§ 13).

La Slice 01 (affinage) implante le contrôle de cycle de vie et la **couture de
diffusion** `openLifecycleSeam` / `closeLifecycleSeam` / `lifecycleSeamNames`,
modelée sur `openMeasureSeam` qui existait déjà juste à côté. C'est du travail
**neuf**, pas du recâblage : avant elle, aucune souscription au cycle de vie
n'existait, et le panneau n'était repeint que par des appels impératifs depuis
l'intérieur du module. Un bouton vivant hors du modal n'avait donc rien à quoi
se lier. Couverte par `tests/unit/test_barehands_hud_js.py`.
`control_center_barehands_hud.js` — **un module de page ajouté**.

La Slice 02 (affinage) sort les quatre destinations dans le **menu du clic
droit** et rend les réglages à leur métier. Les sections que le menu sait viser
sont nommées une seule fois, dans `SECTION` ; un identifiant renommé dans le
HTML ferait donc tomber un test plutôt que de laisser un raccourci muet.

La Slice 03 (affinage) implante la **palette d'outils** du bord gauche et la
couture `openToolSeam`. Elle n'est **pas** fondue dans la couture de cycle de
vie : le contrat range l'outil sous les réglages (§ 8), le canal de commandes
refuse de router `tool` à côté des transitions, et les fondre ferait passer
« l'outil a changé » pour un événement de cycle de vie. Deux faits, deux
propriétaires. Couverte par `tests/unit/test_barehands_palette_js.py`.

La Slice 04 (affinage) implante la **carte d'aide** et la **carte de
diagnostic** (§ 16), et sort le vocabulaire graphique des mains dans
`control_center_barehands_hand_art.js` (§ 15) — **un module de page ajouté**,
inséré après les contrats et **avant** la calibration, précisément pour que la
calibration puisse le lire. Elle supprime le bloc « Gestes » des réglages, dont
deux phrases étaient devenues fausses ; les quatre phrases **vraies** qui sont
parties avec lui ont été replacées par la Slice 08 (§ 16). Couverte par
`tests/unit/test_barehands_cards_js.py` et
`tests/unit/test_barehands_hand_art_js.py`.

Les Slices 05 à 07 (affinage) refondent la **calibration** en un mode
plein-cadre : coque plein écran à cinq régions (§ 10), phases
`INTRO` / `ARMED` / `RUNNING` / `RESULT` qui laissent **lire avant de mesurer**,
sept écrans, et une étape de fenêtre qui manipule un **vrai** cadre par
`JarvisScene.frames.*` — ou se marque `skipped` avec une raison nommée quand la
scène est éteinte, plutôt que d'inventer un cadre plausible (divergence D4 de la
readiness, et la règle fondatrice du § 1 : un refus codé plutôt qu'un défaut
plausible).

La Slice 07B (affinage) **retire le tutoriel** : le module et son fichier de
tests sont supprimés, la commande devient un **alias déprécié** vers la
calibration, et `tutorial_seen` reste un champ de compatibilité que plus
personne n'écrit (§ 13, `docs/legacy/barehands-tutorial-retirement.md`).

La Slice 08 (affinage) **ferme la tâche** : elle replace les quatre phrases
vraies (§ 16), sépare les deux causes qui partageaient
`barehands_calibration_disabled` (§ 10), remet ce registre en ordre narratif, et
prouve la migration — un profil v1 et un bloc de réglages d'une version
antérieure survivent à tout ce qui précède.

**Ce qui reste à venir : rien pour Bare Hands.** Les quatorze Slices de V1 et
les huit de l'affinage sont livrées. Les dettes encore ouvertes ne sont pas des
Slices manquantes mais des arbitrages : la divergence délibérée de
`control_center_scene_page.js` — une souris glisse toute la sélection, une main
nue ne porte que l'objet nommé — attend un arbitrage humain, et quatre Issues de
la tâche V1 restent ouvertes sous `tasks/jarvis-bare-hands-v1/Issues/`.

**Ce que la machine ne valide pas, et ne peut pas valider.** `node` ne peut pas
pousser le contrôleur au-delà de `starting` : `createLandmarker` importe le
bundle MediaPipe et il n'y a pas de caméra, donc `enable()` finit toujours en
`camera_unsupported`. Les présentations `sleep` et `active` n'ont **jamais** été
rendues contre un contrôleur vivant, et tout critère visuel de l'affinage — « l'outil
actif est immédiatement évident », « la calibration se lit comme un mode Jarvis
plein écran », « la main schématique est assez simple », « la pratique de
fenêtre ressemble à la vraie interaction » — est **argumenté et testé
structurellement, jamais constaté à l'œil**. La liste de ce qui doit passer
devant une vraie webcam est tenue à part, avec les vérifications par Slice.
