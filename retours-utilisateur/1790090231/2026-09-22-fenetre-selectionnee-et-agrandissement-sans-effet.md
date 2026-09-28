# « Cette fenêtre » : JARVIS ne sait pas laquelle, l'agrandit sans effet, et l'agrandir ne fera jamais lire

- **Date** : 2026-09-22, 15h28-15h32 UTC (17h28-17h32, heure de Paris)
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain` (`.env`)
- **Session** : `retours-utilisateur/1790090231`, Control Center lancé à 17:17:11
  (15:17:11 UTC).
- **Périmètre** : la scène « constellation ». Un seul objet affiché en fenêtre :
  l'artefact roadmap `brain-artifact-edeec23eca40`, « Huit chantiers ouverts sur
  Jarvis, du plus utile au moins utile », créé à 15:28:22 UTC (révision 1279).
- **Demande** : fiche seulement. **Aucun fichier de code n'a été modifié.**

Trois défauts, dans l'ordre d'importance pour l'utilisateur. Le troisième contient
une redéfinition de la demande, signalée comme telle.

## 1. La sélection de l'utilisateur ne quitte jamais la page

C'est le point que l'utilisateur met en tête, et il précise que c'était déjà sa
demande plus tôt dans la conversation.

Ses mots, la phrase étant arrivée coupée au début :

> « …sélectionner. Et récemment implémenté quelque chose qui est censé te donner la
> possibilité de voir, donc quand je te dis "cette fenêtre", c'est celle que je suis
> en train de sélectionner, ou la dernière que j'ai sélectionnée. Voilà, du coup
> t'es censé normalement comprendre ce genre de choses. Donc ça c'est la première
> chose, c'est ce que je t'avais demandé tout à l'heure. »

Ce qu'il décrit : quand il dit « cette fenêtre », « ça », « celui-là », le cerveau
devrait résoudre le démonstratif vers l'objet sélectionné, ou à défaut le dernier
sélectionné. C'est ce qui aurait évité tout l'incident décrit plus bas : le cerveau
a **deviné** la cible au lieu de la lire.

### Son souvenir est exact — mais il porte sur l'écran, pas sur la transmission

La sélection existe, et elle est bien faite. Dans
`jarvis/runtime/control_center_scene_page.js` (l.961-966) : un tableau `selection`
tenu dans l'ordre d'entrée, et `selectedId` qui en est **le dernier** — exactement
la notion de « dernier sélectionné » dont parle l'utilisateur. Sélection multiple au
rectangle et au Ctrl-clic, ancre du menu et du clavier, `applySelection` (l.2553),
« sélectionner toute la constellation » (l.2660). Côté logique pure,
`nextSelection` (`control_center_scene_interact.js` l.510-529).

Elle a bien été faite récemment : commits `3aeb314` et `595b352` (2026-09-19), puis
`059e8dd` (2026-09-20) qui la réconcilie avec les cadres tenus à mains nues. **Ces
commits ne touchent que le navigateur** : aucun ne modifie `jarvis/domain/scene.py`,
`display_mcp.py`, `sqlite_scene.py`, `claude_local.py`, ni un point d'entrée HTTP.
Ce qui a été implémenté, c'est le geste et le rendu.

### Où la chaîne s'arrête, exactement

`souris ou main nue` → `nextSelection` → `applySelection` → **deux variables
JavaScript et une classe CSS `sc-selected`** → **fin**.

La coupure est avant le réseau, et elle est délibérée. Le commentaire du code le dit
lui-même (`control_center_scene_page.js` l.2659) :

> `Rien n'est envoyé à Core : une sélection ne vit que dans la page.`

Les vérifications convergent, et sont toutes négatives :

- **Pas d'opération** : les `SceneOp` (`jarvis/domain/scene.py` l.232-253) sont au
  nombre de douze, aucune n'est `select`. Une telle commande serait un 400 sur
  `POST /api/scene/commands`.
- **Pas de champ dans le modèle** : `SceneObject` n'a rien de tel ; la ligne d'objet
  rendue par `scene_inspect` et `scene_get` (`display_mcp.py` l.1875-1892) a
  quatorze colonnes — `object_id, kind, category, origin, exec_state,
  representation, geometry, layer, order, visibility, pinned_by_user, placed_by,
  live_signal, title` — et **aucune ne dit « sélectionné »**.
- **Pas de persistance** : le schéma sqlite (`jarvis/adapters/sqlite_scene.py`
  l.124-142) n'a ni colonne ni table pour cela.
- **Pas de contexte non plus** : les consignes données au cerveau
  (`claude_local.py` l.88-112) ne mentionnent ni sélection, ni objet actif, ni
  démonstratif. Elles disent au contraire « la scène change sans toi (…, actions de
  l'utilisateur) : relis-la avec `scene_inspect` » — c'est-à-dire : relis l'état,
  personne ne te dira ce que l'utilisateur vient de désigner.
- **Les mains nues n'y changent rien** : leur geste `select`
  (`control_center_barehands.js` l.4382-4389) fait un `focus()` dans le DOM et
  retombe dans le même mécanisme de page.
- **La documentation l'assume** : `docs/ARCHITECTURE.md` l.3177 liste le geste
  `select` avec une colonne « commande » à `none` ; `docs/mcp/plan-outils-interface.md`
  l.197 a la même colonne vide, seule ligne du tableau dans ce cas. Aucun document
  du dépôt ne parle de démonstratif, de deixis ni d'objet désigné.

Des deux lectures possibles — « le mécanisme existe mais n'arrive pas aux outils »
et « il n'a jamais été branché côté cerveau » — c'est la première qui est vraie,
mais poussée plus loin qu'attendu : il ne manque pas un dernier maillon, il en
manque trois (le transport, le modèle, l'exposition). Aujourd'hui, le cerveau n'a
**aucune** source pour savoir ce que l'utilisateur désigne ; au mieux, il devine à
partir du dernier objet dont il a parlé lui-même. C'est précisément ce qui s'est
passé.

> **QUESTION** (ne bloque rien) : l'utilisateur veut-il que le démonstratif se
> résolve sur la **sélection courante** — qui se vide dès qu'on clique dans le vide,
> donc souvent vide au moment où il parle — ou sur le **dernier objet touché**, qui
> survit à la désélection ? Seule la première est mémorisée aujourd'hui, et les deux
> se codent différemment.

## 2. Un agrandissement rendu `applied` peut ne laisser aucune trace

### Comportement constaté

Mots de l'utilisateur, au départ :

> « JARVIS, tu peux m'agrandir cette fenêtre s'il te plaît »

Le cerveau appelle `scene_update_object` avec une nouvelle géométrie. L'outil répond
`outcome: applied`, révision 1295. Le cerveau annonce que c'est agrandi. Réponse de
l'utilisateur :

> « Euh non. C'est pas agrandi. Je te parle de la fenêtre que je sélectionne en ce
> moment. »

À la relecture, la fenêtre était revenue à 64 × 40 et avait changé de position.

### Ce que montre la trace (`runtime/trace.jsonl`)

| Heure (UTC) | Source | Opération | Révision |
| --- | --- | --- | --- |
| 15:29:41.689 | Control Center | `set_geometry` applied | 1294 |
| **15:29:56.283** | **cerveau** (`scene_update_object`) | `set_geometry` applied | **1295** |
| **15:29:56.339** | **Control Center** | `set_geometry` applied | **1296** |
| 15:30:00.703 | Control Center | `set_geometry` applied | 1299 |
| **15:30:27.558** | **cerveau** (`scene_update_object`) | `set_geometry` applied | **1300** |
| 15:30:49 → 15:33 | Control Center | 20 `set_geometry` de plus | 1303 → 1342 |

**La géométrie posée par le cerveau a vécu 56 millisecondes.** Elle a été suivie, au
même dixième de seconde, d'une écriture venue du Control Center.

Contexte de densité : entre 15:20 et 15:33, le Control Center a émis **63
`set_geometry`**, 11 `pin` et 9 `set_representation`, tous `applied`. Les deux
commandes du cerveau sont deux gouttes dans ce flux.

Pendant la rédaction de cette fiche, l'objet a continué de bouger : lu à la révision
1322 il était à `[-125.1, -46.5, 64, 40]`, et relu directement dans
`data/state/scene.sqlite3` un peu plus tard à `[-126.5, -72.0, 64, 40]`. Dans les
deux cas : `placed_by: user`, `pinned_by_user: true`.

### Ce qui est écarté

- **Le résolveur automatique du navigateur est hors de cause**, et triplement. Il ne
  propose que des objets **sans** géométrie (`control_center_scene_layout.js`
  l.1455-1469), `resolveLayout` recopie telle quelle la géométrie des objets déjà
  placés — il n'y a pas de reflow (l.1113-1126) —, et le serveur refuserait de toute
  façon un placement `resolver` sur un objet placé autrement
  (`explicit_placement`, `jarvis/domain/scene.py` l.1430-1437). La base le confirme :
  `placed_by` vaut `user`, pas `resolver`.
- **Ce n'est pas non plus un objet resté à sa taille par défaut faute d'avoir été
  placé.** La position finale le dit : `y = -72,0` est exactement le bord de la zone
  sûre (`SAFE_AREA.y0`), et `x = -126,5` est sur la grille du dixième. C'est la
  signature d'un geste borné par la page (`control_center_scene_interact.js`
  l.103-115, l.275-309), pas d'un balayage du résolveur, qui procède par pas de deux
  unités.

### Ce qu'on ne peut toujours pas dire : qui, exactement

`64 × 40` est `DEFAULT_SIZE.window`, la taille par défaut d'une fenêtre
(`control_center_scene_layout.js` l.46-51, dupliquée dans
`control_center_scene_interact.js` l.41-42). Trois scénarios restent compatibles :

1. **Un glissement ou un redimensionnement déjà en cours** pendant l'écriture du
   cerveau. Le geste capture la boîte au `pointerdown` et une couche optimiste masque
   la géométrie du serveur jusqu'au relâchement ; au relâchement, la page renvoie la
   taille **de départ**, donc l'ancien `64 × 40`
   (`control_center_scene_interact.js` l.207-209, l.735-800). Les 56 millisecondes
   collent parfaitement. C'est le scénario le plus probable.
2. **Un changement de forme par le menu** (`control_center_scene_page.js`
   l.2670-2680), qui recalcule une boîte neuve `64 × 40` **à une place libre
   différente** — soit, à la lettre, « taille d'origine et position différente ».
   Plutôt écarté pour cet instant précis : cela aurait été journalisé en
   `set_representation`, or à 15:29:56.339 c'est bien un `set_geometry`. Il y en a eu
   néanmoins à 15:29:02 et 15:29:24.
3. **Un glissement de sélection multiple**, qui emmène tous les objets sélectionnés,
   une commande chacun — cohérent avec les rafales de trois `set_geometry` en 20 ms
   observées vers 15:32. L'artefact aurait alors été emmené sans être visé.

Ce qui manque pour trancher : **le journal `scene.command` ne consigne pas
l'identifiant de l'objet** (`jarvis/runtime/scene_view.py` l.598-602 : seulement
`op`, `outcome`, `reason`, `revision`). Rien ne prouve donc que la commande 1296
visait cet artefact ; la corrélation ne tient qu'à `placed_by = user`, à la taille
`64 × 40` et à l'horodatage. C'est le premier point à instrumenter.

### Ce qui n'est pas en cause

- **`applied` n'est pas un mensonge : l'écriture a bien été persistée sur disque.**
  Le service n'écrit en mémoire qu'**après** avoir écrit en base
  (`jarvis/core/scene_service.py` l.288-304 : `commit` puis affectation du snapshot),
  et un échec lève au lieu de rendre `applied`. De plus la révision n'avance que s'il
  y a un changement réel (`jarvis/domain/scene.py` l.1300-1305 : plan vide →
  `duplicate`). Le serveur n'applique aucun clamp : les valeurs sont stockées telles
  qu'envoyées. La géométrie demandée par le cerveau a donc bien existé en base.
- **L'épingle n'a pas bloqué le cerveau.** Une épingle protège la place contre un
  placement *automatique* seulement (`docs/scene-model.md` l.240-246,
  `jarvis/domain/scene.py` l.1424-1431). Symétriquement, **une géométrie posée par un
  agent n'est protégée de rien** : le chemin utilisateur la réécrit sans condition et
  repose `placed_by = user` (l.1403-1405).
- Le défaut est donc ailleurs, et il est double :
  - **L'outil rend compte de l'instant, jamais de la durée de vie.** Rien dans sa
    réponse ne prévient que la géométrie sera peut-être reprise dans la seconde.
  - **Il ne peut structurellement pas le dire.** `display_mcp.py` (l.1984-1996)
    calcule bien un indice `scene_changed` — mais en **excluant l'objet visé**
    (`exclude={object_id}`). L'outil est donc aveugle exactement là où il faudrait
    qu'il regarde : sur la réécriture de la géométrie qu'il vient de poser. (Et cet
    indice signifie « la scène a bougé depuis ta dernière lecture », non « la scène a
    changé grâce à toi » — piège à connaître pour qui reprendra le journal.)
- **Enfin, le cerveau et l'utilisateur ont la même autorité sur la géométrie**, sans
  « dernier arrivé perd » ni révision attendue sur `set_geometry`. Une écriture
  d'agent pendant un geste humain est donc structurellement perdante. C'est un choix
  de conception, pas un bug — mais c'est lui qui rend l'annonce fausse possible.

## 3. Agrandir ne rendra jamais ce texte lisible — la demande est à redéfinir

C'est le point qui compte le plus pour l'utilisateur : il agrandissait la fenêtre
précisément pour lire, et il ne peut toujours pas.

### Comportement constaté

Après le second agrandissement (86 × 96, révision 1300), toutes les lignes restent
coupées à droite par des points de suspension, comme avant.

### L'agrandissement a bien eu lieu, et le texte en profite — un demi-caractère par unité

Mesuré au pixel sur `runtime/scene-captures/capture-20260922T153035219Z-63f2a646.png`
(15:30:35 UTC) : la fenêtre occupe 293 × 327 pixels pour une échelle de
3,394 px/unité, soit **86,3 × 96,3 unités**. La commande a donc bien atteint le rendu.

Mais les polices sont figées en pixels (9,5 / 11 / 12 / 13 px), sans aucune mise à
l'échelle. À 3,394 px/unité et ~6,8 px par caractère, **une unité de scène vaut
environ un demi-caractère**. Passer de 64 à 86 unités fait donc passer une entrée de
~28 à ~39 caractères affichés — sur des libellés qui font **70 à 137 caractères**.

Onze caractères gagnés sur cent vingt : les « … » restent collés au bord droit, au
même endroit relatif. À l'œil, rien n'a bougé. C'est ce que l'utilisateur a vu, et
il a raison de le voir ainsi.

### La redéfinition, signalée plutôt que passée sous silence

Pour afficher un libellé de 120 caractères sur une seule ligne, il faudrait une
fenêtre d'environ **220 unités de large** — alors que la zone sûre de la scène n'en
fait que 290. **Agrandir ne peut pas résoudre ce problème.** La demande telle qu'elle
arrive (« la fenêtre grandit, le texte devrait suivre ») ne peut pas être satisfaite
par le redimensionnement : seul le **repli du texte sur plusieurs lignes** le peut.

Le vrai défaut est donc ailleurs que dans la largeur :
`control_center_scene_page.js` l.846,
`.sc-items .sc-item-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}` :
**une entrée = une ligne, jamais repliée**. La référence voisine (l.847) mange
jusqu'à 45 % de la ligne, la liste est bornée à 45 % de la hauteur (l.862), le titre
est limité à deux lignes (l.807-808). Et aucune infobulle ne rattrape la perte :
`itemRow` (l.1609-1631) ne pose pas d'attribut `title` sur le libellé.

Le résumé, lui, se replie et défile correctement à l'écran (`.sc-summary`, l.812).

### Le texte n'est pas tronqué à la source

Vérifié deux fois : par `scene_get`, et directement dans
`data/state/scene.sqlite3` (table `scene_objects`). Les huit entrées y sont
**entières**, de 70 à 137 caractères, sans aucun `…`. Exemple : « 1. Interruption
impossible en GPT-Live : ce mode ne signale jamais le début de parole. Diagnostic
écrit, code intact. » La seule borne côté Python, `MAX_ITEM_LABEL_CHARS = 160`
(`jarvis/domain/scene.py` l.69 et 474), **refuse** au lieu de couper — le journal en
garde la trace à 15:28:06 (`label exceeds 160 characters`).

### Un biais de mesure à connaître, pour la suite

Ce que le cerveau voit par `scene_capture` **n'est pas une photo de la page** :
l'image est redessinée sur un canvas à partir du modèle de vue
(`control_center_scene_page.js` l.3282 ; `control_center_scene_capture.js`). Ce
dessin coupe chaque ligne avec `fit()` (l.38-43, vrai U+2026, métrique à chasse fixe)
et **n'enroule jamais rien** : un bloc markdown = une ligne dessinée
(`markdownLines`, `control_center_scene_layout.js` l.321).

Conséquence : dans une capture, **même le résumé apparaît coupé alors qu'il se
replie correctement à l'écran**. Les entrées, elles, sont bel et bien coupées dans
les deux cas. Tout constat visuel que le cerveau tire d'une capture doit donc être
lu en connaissant cet écart.

> **QUESTION** (ne bloque rien) : l'utilisateur a-t-il constaté la troncature **à
> l'écran** ou sur une **capture** que JARVIS lui a montrée ? Les deux chemins
> coupent, mais pas au même endroit ni pour les mêmes raisons, et la réponse change
> la correction à faire — pas le diagnostic.

## Comportement attendu, dans les termes de l'utilisateur

1. Quand il dit « cette fenêtre », JARVIS agit sur **la fenêtre qu'il a
   sélectionnée** — ou, à défaut, la dernière sélectionnée — sans avoir à la nommer,
   et sans que JARVIS devine.
2. Quand JARVIS annonce « c'est agrandi », la fenêtre **est** plus grande à l'écran,
   et elle **le reste**. Si sa géométrie est reprise par autre chose, JARVIS le sait
   et le dit, au lieu d'annoncer une réussite.
3. Il peut **lire le contenu d'un artefact en entier**. C'est le besoin ; agrandir
   n'en était que le moyen supposé.

## Pistes

Aucune n'est démontrée ; rien n'a été implémenté ni modifié.

- **Point 1** : il manque trois maillons, pas un. Un transport (une opération de
  scène, ou plus simplement un état de page remonté sans passer par le journal des
  commandes), une place dans le modèle, et une exposition. Pour la voix, l'exposer
  dans le **contexte du tour** sert mieux que dans un outil : le démonstratif doit
  être résolu **avant** que le cerveau choisisse d'appeler quoi que ce soit.
- **Point 2**, trois leviers indépendants :
  - **Consigner l'identifiant de l'objet dans `scene.command`**
    (`jarvis/runtime/scene_view.py` l.598-602). Sans lui, aucun incident de ce genre
    ne pourra jamais être tranché. C'est le moins cher et le plus utile.
  - **Cesser d'exclure l'objet visé du calcul de `scene_changed`**
    (`display_mcp.py` l.1984-1996), pour que l'outil puisse dire à l'agent « ta
    géométrie a été réécrite depuis ». Ou, plus simplement, relire la géométrie après
    un court délai avant de rendre la main.
  - **Donner à `set_geometry` une révision attendue** (dans l'esprit d'un
    `If-Match`), pour qu'une écriture d'agent tombant au milieu d'un geste humain
    échoue franchement au lieu d'être silencieusement recouverte.
- **Point 3** : lever `white-space:nowrap` sur les entrées pour qu'elles se replient,
  et/ou leur donner une infobulle portant le texte complet, et/ou une vue « lire
  l'artefact en entier ». L'agrandissement, lui, n'est pas le levier.
- Mesure qui échouerait aujourd'hui, à faire avant toute correction : sélectionner un
  objet dans la scène, puis dire « archive ça » sans le nommer. Le cerveau doit soit
  demander lequel, soit se tromper de cible.

## Ce dont je doute

- **Sur le point 2**, l'écrivain qui a repris la géométrie 56 ms plus tard est
  identifié comme l'acteur `user` (le Control Center), et le résolveur automatique
  est écarté par preuve. Mais **quel geste**, exactement, reste indécidable : le
  journal ne porte pas l'identifiant de l'objet, donc rien ne prouve même que la
  commande 1296 visait cet artefact. Le scénario du geste déjà en cours, qui renvoie
  la boîte de départ au relâchement, est le plus probable — ce n'est pas une preuve.
- **Sur le point 1**, la preuve est une absence documentée (recherches négatives sur
  les opérations de scène, la ligne d'objet des outils, le schéma sqlite, les
  consignes du cerveau), convergente et cohérente avec un commentaire de code
  explicite — mais ce n'est pas un échec observé en direct. La mesure proposée
  ci-dessus comblerait cela.
- **Sur le point 3**, le calcul « une unité ≈ un demi-caractère » repose sur l'échelle
  de cette session (3,394 px/unité), qui dépend de la taille de la fenêtre du
  navigateur. L'ordre de grandeur tient, la valeur exacte non. Et l'observation
  d'origine — « coupé exactement au même endroit qu'avant » — n'a pas pu être
  revérifiée : une seule capture subsiste dans `runtime/scene-captures`, celle
  d'après.
- Enfin, cette fiche redéfinit en partie la demande du point 3 : elle affirme
  qu'agrandir ne peut pas rendre ce texte lisible. C'est une conclusion tirée d'une
  mesure sur une capture, pas sur l'écran de l'utilisateur. Si l'échelle réelle de
  son affichage est très différente, le calcul est à refaire — la conclusion, elle,
  changerait de degré, pas de nature : un libellé de 137 caractères ne tient pas sur
  une ligne de fenêtre.
