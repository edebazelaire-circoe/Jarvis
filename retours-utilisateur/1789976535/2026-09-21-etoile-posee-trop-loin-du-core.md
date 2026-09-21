# L'étoile d'une nouvelle tâche est posée beaucoup trop loin du Core

- **Date** : 2026-09-21
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain` (`.env`)
- **Session** : `retours-utilisateur/1789976535`, Control Center lancé à 09:42:15
  (07:42:15 UTC).
- **Périmètre** : la scène « constellation », et précisément le placement automatique
  des étoiles agent/job par l'AutoResolver du navigateur (`placed_by = resolver`).
- **Demande** : fiche seulement. Aucun code n'a été modifié (un autre agent implémente
  dans ce checkout au même moment).

## Comportement constaté

Mots de l'utilisateur, rapportés par le cerveau vocal :

> « L'étoile de cette tâche est arrivée beaucoup trop loin du corps center »

« corps center » est très probablement « du Core, au centre » : l'orbe centrale de
JARVIS. Interprétation du cerveau, non confirmée par l'utilisateur.

Faits rapportés par le cerveau :

- La scène venait d'être **entièrement archivée** : elle était vide.
- La nouvelle étoile de l'agent « [code] Couleurs d'état de l'orbe, relance » a été
  posée automatiquement à **x -3, y -51 (w 6, h 6)**, soit un centre à (0, -48).
  Repère : origine au centre, y vers le bas, zone sûre y -72..68. L'étoile apparaît
  donc tout en haut, aux deux tiers du chemin entre le centre et le bord haut de la
  zone sûre.
- Le cerveau l'a ensuite déplacée à la main à **y -28** (centre à -25).

## Comportement attendu

Ce que l'utilisateur doit constater une fois réparé : **sur une scène vide, la première
étoile d'une tâche apparaît juste à côté de l'orbe centrale, comme un satellite collé à
elle**, pas au loin vers le haut de l'écran. Et les suivantes s'égrènent autour, au plus
près.

Mesure proposée pour une reprise : sur une scène vide, `resolveLayout` avec un seul
agent sans géométrie doit rendre une boîte dont le centre est à une distance de (0, 0)
comparable à celle que le cerveau a jugée juste (≈ 25 unités), et non 48. À confirmer
par une capture d'écran réelle : c'est à l'œil, sur l'orbe visible, que l'utilisateur
juge « trop loin ».

## Contexte

### Reproduction (lecture seule)

Le placement est **déterministe** et se reproduit exactement en exécutant la logique
pure du rendu avec node (`jarvis/runtime/control_center_scene_layout.js`,
`window.JarvisSceneLayout.resolveLayout`) sur une scène de trois agents sans
géométrie ni relation :

```
a → { x: -3, y: -51, w: 6, h: 6 }   (haut)
b → { x: 45, y: -3,  w: 6, h: 6 }   (droite)
c → { x: -3, y: 45,  w: 6, h: 6 }   (bas)
```

La première étoile tombe **exactement** sur la boîte rapportée (-3, -51). Ce n'est donc
ni un aléa, ni un reste de l'ancienne scène : c'est ce que le résolveur produit à chaque
fois sur une scène vide.

### Comment le résolveur choisit

- `homeOf` (l.763) : une étoile sans ancre part de (0, 0).
- `rootCandidates` (l.774) : spirale carrée sur un réseau de pas `taille + gap`. Pour
  une étoile de 6 × 6, le premier réseau essayé est **espacé, gap 10, donc pas de
  16 unités** ; les candidats sont triés par distance puis par angle, haut d'abord
  (commentaire l.785-787).
- `pick` (l.831) : premier candidat qui ne chevauche **ni objet ni `FACE_ZONE`**.
- `FACE_ZONE` (l.43) : carré **-34..34** sur les deux axes, soit 68 × 68 unités, 38 %
  de la hauteur du cadre de référence.
- `docs/scene-model.md` l.548 décrit ce contrat : « first free ring outside the face
  zone ±34 ».

Déroulé pour la première étoile, vers le haut :

| Anneau | Centre | Boîte y | Chevauche le visage ? |
| --- | --- | --- | --- |
| 1 | (0, -16) | -19..-13 | oui |
| 2 | (0, -32) | -35..-29 | **oui, d'une seule unité** (-35 < -34) |
| 3 | (0, -48) | -51..-45 | non → choisie |

## Pistes

**Hypothèse, non démontrée à l'écran** : l'écart vient de la combinaison de deux choix
du résolveur, tous deux dans `control_center_scene_layout.js`.

1. **La zone du visage est probablement plus grande que l'orbe que l'utilisateur voit.**
   `FACE_ZONE` réserve ±34 unités, mais la position que le cerveau a jugée juste
   (boîte y -31..-25) est **à l'intérieur** de cette zone : l'orbe visible s'arrête donc
   vraisemblablement bien avant ±34. Le visage est une iframe plein écran
   (`control_center.html:42`, `.face{inset:0}`) ; la taille réelle de l'orbe dessinée
   dedans n'a pas été mesurée ici. À vérifier par une capture.
2. **Le réseau espacé de 16 unités quantifie la distance.** L'anneau 2 (centre à 32)
   n'est refusé que pour **1 unité** de chevauchement avec la zone du visage ; le pas
   suivant saute alors d'un coup à 48. Le plus près possible hors zone serait un centre
   à 37 (34 + demi-taille 3). Même avec la zone actuelle, la première étoile est donc
   ~11 unités plus loin que nécessaire.
3. **Le tri « haut d'abord »** (commit `a9496f3`, 2026-09-18) envoie cette première
   étoile vers le haut de l'écran, déjà chargé par la barre et le dock Cosmos ; c'est
   ce qui rend l'écart plus visible, pas ce qui le crée.

Piste de correction possible, pour mémoire seulement : ramener `FACE_ZONE` à la taille
mesurée de l'orbe, et/ou autoriser des candidats hors réseau au plus près du bord de la
zone. Tests concernés : `tests/unit/test_scene_renderer_logic.py` (épingle probablement
les positions actuelles) et le contrat de `docs/scene-model.md` l.548.

## Ce dont je doute

- **« corps center » = « Core, au centre »** est l'interprétation du cerveau ; elle est
  cohérente avec le déplacement vers le centre qu'il a fait ensuite, mais l'utilisateur
  ne l'a pas confirmée.
- **La taille visible de l'orbe n'a pas été mesurée** : la piste 1 repose sur le seul
  fait que le cerveau a posé l'étoile à l'intérieur de `FACE_ZONE` sans que cela gêne.
  Si l'orbe occupe réellement ±34 à certaines tailles de fenêtre ou dans le thème
  Cosmos, réduire la zone ferait chevaucher les étoiles et l'orbe.
- La distance « juste » n'est pas connue : y -28 est le choix du cerveau, pas celui de
  l'utilisateur.
