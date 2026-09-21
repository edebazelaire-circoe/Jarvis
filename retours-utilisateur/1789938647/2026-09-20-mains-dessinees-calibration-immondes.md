# Les mains dessinées de la calibration Bare Hands sont immondes

- **Date** : 2026-09-20
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain` (`.env`)
- **Session** : `retours-utilisateur/1789938647`, Control Center lancé à 23:10:47
  (21:10:47 UTC).
- **Périmètre** : la surimpression de calibration de Bare Hands (le parcours guidé
  plein écran), et précisément les illustrations de mains qui y sont dessinées.
- **Demande explicite de l'utilisateur** : ceci est à **noter**, pas à corriger. Aucun
  code, aucun dessin n'a été modifié.

## Comportement constaté

L'utilisateur lance la calibration de Bare Hands et rejette l'interface à vue. Ses mots :

> « je n'aime pas du tout la nouvelle interface de calibration, je pense qu'il y a
> beaucoup de changements. Les mains dessinées sont vraiment immondes, c'est pas du tout
> les images de mains que j'avais en tête. Il faut noter dans les tâches, dans les
> retours utilisateurs, que les mains sont vraiment immondes. »

Trois choses distinctes dans cette phrase, à ne pas confondre :

1. **Le rejet des mains dessinées** — « vraiment immondes », répété deux fois, et c'est
   l'objet de cette fiche.
2. **Un écart à une intention qu'il avait** — « c'est pas du tout les images de mains que
   j'avais en tête ». Il ne dit pas que le dessin est raté dans l'absolu : il dit qu'il
   ne ressemble pas à ce qu'il attendait. **Cette référence n'a jamais été écrite nulle
   part** ; elle n'existe que dans sa tête. Voir « Ce dont je doute ».
3. **Une impression de dérive générale** — « je pense qu'il y a beaucoup de
   changements ». Constat factuellement exact : tout le lot Bare Hands (coque de
   calibration, démonstrations gestuelles, module de dessin) a atterri le même jour,
   2026-09-20.

## Comportement attendu

Ce que l'utilisateur doit pouvoir constater quand ce sera repris : **les mains montrées
pendant la calibration ressemblent à des mains.** Assez pour qu'il reconnaisse le geste
sans lire la légende, et assez pour que ce ne soit pas la première chose qu'il commente
en ouvrant l'écran.

En négatif, et c'est plus sûr que le positif : il ne doit plus avoir l'impression de
regarder un pictogramme d'icône agrandi de force au milieu de l'écran.

Il n'y a pas de mesure automatique de ce retour. C'est un jugement visuel, et la seule
preuve recevable est que l'utilisateur regarde l'écran et ne dise plus « immonde ».

## Contexte

### Où vit le dessin

Toutes les mains de la page viennent d'un seul module, créé la veille du retour :
`jarvis/runtime/control_center_barehands_hand_art.js` (503 lignes,
`window.JarvisBarehandsHandArt`). Il n'existe **aucun asset graphique de main sur
disque** — pas de `.png`, `.svg`, `.webp` dans le dépôt : tout est du SVG produit par
code.

L'overlay de calibration lui-même est
`jarvis/runtime/control_center_barehands_calibration.js` ; il monte les mains via
`demoNode()` (ligne 1548), qui appelle `art.handSvg()` à la ligne 1585.

### Comment les mains sont construites

- `viewBox` **24×24** (`VIEWBOX`, l.44), épaisseur de trait **1,5** (`STROKE_WIDTH`,
  l.45) — les proportions d'un glyphe d'icône de barre d'outils.
- La paume est **un seul `path` littéral** réutilisé par les sept postures (`PALM`,
  l.69), plus un trait de phalanges (`KNUCKLES`, l.70, un segment horizontal droit).
- Chaque doigt est une **polyligne de 2 ou 3 points** dont les coordonnées sont écrites
  à la main dans des tables (`FOLD` l.87, `STRAIGHT` l.101, `THUMB_READY` l.120,
  `THUMB_PINCH` l.125). Pas de courbe : des segments droits.
- Les articulations sont des **cercles pleins** de rayon 0,95 (`JOINT_R`, l.51).
- Sept postures au total (`POSE_ORDER`, l.138) : `rest`, `wake_c`,
  `pinch_primary_open` / `closed`, `pinch_secondary_open` / `closed`, `pinch_target`.

### Le facteur d'agrandissement

`demoNode()` demande `size: art.SIZE_DEFAULT * 8`, soit **192 px** rendus depuis un
`viewBox` de 24 (`calibration.js:1585`), puis la CSS retaille à
`clamp(128px, 24vh, 232px)` (`calibration.js:1386`). Un dessin dont toute la géométrie a
été posée pour 24 px occupe donc jusqu'à **232 px de haut, au centre de l'écran**, avec
un trait de 1,5 unité et des doigts en segments droits. C'est l'écart le plus visible
entre ce que le dessin est et l'usage qu'en fait la calibration.

Un commentaire du module (l.66-68) reconnaît d'ailleurs que la paume est provisoire :
aucune posture ne la remplace encore.

### Où elles apparaissent

`DEMO` (`calibration.js:548`) associe les postures aux étapes :

| Étape | Mains montrées |
| --- | --- |
| Main au repos | `REST`, statique |
| Posture de réveil | `WAKE_C`, statique |
| Pincement pouce-index | ouvert ↔ fermé, animé |
| Pincement pouce-majeur | ouvert ↔ fermé, animé |
| Viser et cliquer | ouvert ↔ cible, animé |
| Manipulation de fenêtre (6A / 6B) | une main, puis deux mains en miroir |

L'alternance est une animation CSS de 2,4 s (`@keyframes jfMime`, l.1497). Les mêmes
mains servent aussi à la carte d'aide du HUD (`control_center_barehands_hud.js:566`,
`:2187`, `:2200`), mais à **26 et 54 px** — donc à une taille proche de celle pour
laquelle elles ont été dessinées. Le HUD n'a pas été critiqué ; la calibration l'a été.

### Historique

- `005bed2` (2026-09-20) — création du module de dessin des mains.
- `c5a598d` (2026-09-20) — « les cinq premiers exercices montrent enfin le geste » :
  c'est ce commit qui fait entrer les mains dans la calibration.
- `57409d8` (2026-09-20) — la calibration perd sa carte centrée et passe plein cadre.
- Lot fusionné par `e684a46`, « Bare Hands — affinage de l'interface et de la
  calibration ».

L'impression de « beaucoup de changements » correspond donc à une refonte réelle et
récente, concentrée sur une seule journée.

### Voisinage : l'orange

Dans le même tour, l'utilisateur a aussi signalé que **l'orange a remplacé le bleu**
comme couleur principale de cette interface. **Ce point est pris en charge par un autre
agent et ne fait pas l'objet de cette fiche.** Il est noté ici parce qu'il touche les
mêmes pixels : les mains tracent en `currentColor`, la coque pose
`color: var(--jf-accent)` (`calibration.js:769`), et `--omega-accent` est réécrit à
l'exécution selon l'état vocal (`control_center_work.js:108-113`,
`speaking: [255,151,61]`). La couleur des mains **est** l'accent courant. Conséquence
pour la présente fiche : une partie de ce que l'utilisateur voit comme « immonde » peut
tenir à la teinte plutôt qu'au tracé, et les deux retours ne pourront pas être jugés
séparément à l'œil.

## Pistes

Aucune correction n'est engagée : l'utilisateur a demandé que ce soit noté, pas
implémenté. Ce qui suit sert seulement à cadrer une reprise éventuelle.

1. **L'écart taille de conception / taille d'affichage est le fait le plus concret.**
   Un tracé pensé pour 24 px affiché à ~200 px ne gagne aucun détail en grandissant : il
   grossit ses simplifications (paume unique, doigts en segments droits, articulations
   en pastilles). C'est une observation, pas une cause démontrée — personne n'a demandé
   à l'utilisateur ce qui le gêne précisément.
2. **La paume est déjà signalée comme provisoire par son auteur** (commentaire
   `hand_art.js:66-68`) : un `path` unique partagé par les sept postures, qui ne bouge
   jamais quelle que soit la position des doigts.
3. **Le HUD et la calibration partagent la même source de dessin à des échelles très
   différentes** (26/54 px contre 192 px). Toute reprise devra décider si c'est le même
   dessin qui sert aux deux, ou deux dessins distincts.
4. **Trois tests épinglent ces fichiers** :
   `tests/unit/test_barehands_hand_art_js.py`,
   `tests/unit/test_barehands_calibration_js.py`,
   `tests/unit/test_barehands_palette_js.py`.
   Ils contraindront toute refonte du tracé. La doc correspondante est
   `docs/barehands-contracts.md` §15.

## Ce dont je doute

**La question centrale n'a pas de réponse dans le dépôt : à quoi ressemblent « les
images de mains qu'il avait en tête » ?** L'utilisateur ne décrit aucune référence — ni
style, ni source, ni exemple. Aucun document du projet ne fixe l'aspect attendu de ces
illustrations. Tant que cette référence n'est pas donnée, toute reprise du dessin serait
un second coup dans le noir, avec les mêmes chances de se faire rejeter.

**QUESTION à lui poser avant toute reprise** : ces mains, il les voit comment ?
Photographiques, silhouettes pleines, trait épais façon illustration, rendu 3D, main
schématique avec points d'articulation ? Et a-t-il un exemple à montrer — une capture,
un lien, n'importe quoi de visuel ?

Deuxième doute, plus petit : **le retour porte peut-être sur l'ensemble de l'écran
autant que sur les mains.** Il ouvre par « je n'aime pas du tout la nouvelle interface de
calibration » avant de nommer les mains. Les mains sont ce qu'il a désigné, donc c'est
ce que cette fiche enregistre — mais il n'est pas acquis que reprendre les mains seules
lui fasse dire que l'écran est bon.

Aucun code ni asset n'a été modifié : fiche seulement, conformément à sa demande.
