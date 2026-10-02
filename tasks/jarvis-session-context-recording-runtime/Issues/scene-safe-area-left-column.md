# La zone sûre de la scène ignore la colonne de gauche

**Statut : écart V1 accepté (décision PM, reprise QA de la Slice 10), à montrer
à l'Humain avant `HV-REC-UI-001`.**

Constaté pendant la Slice 10 (rail de capture), hors de son périmètre.

- `SAFE_AREA` (`control_center_scene_layout.js`, parité `SCENE_SAFE_AREA` dans
  `jarvis/domain/scene.py`) vaut x ∈ [−152, 138] : à 1280 × 720 (4 px par unité)
  son bord gauche est à 32 px de l'écran.
- La colonne de gauche occupe x 18–82 px : contrôle Bare Hands (y 76–158), palette
  (y 168–345) — déjà avant cette tâche — et maintenant le rail de capture
  (y 355–541), ou à côté de la colonne (x 82–146) sur un écran court.
- Les gestes de l'utilisateur s'arrêtent contre ces commandes (`CONTROL_SELECTOR`,
  mesurées) ; le **résolveur**, lui, peut proposer une place dessous, et le
  cerveau lit une zone sûre qui les inclut.

Correction possible : mesurer la colonne comme les autres commandes de la
calibration (§ *Composition safe area* de `docs/ARCHITECTURE.md`) et reculer
`x0`, ou faire tenir compte au résolveur des rectangles déjà mesurés. C'est un
changement de contrat de la scène (parité Python, consigne du cerveau), donc
hors de la Slice 10.

## Mesure de la QA (Slice 10) et décision

- QA S10, 1280 × 720 : la colonne de gauche (contrôle Bare Hands, palette, rail
  de capture) descend jusqu'à **y 541** ; la scène peut encore y placer du
  contenu (le résolveur et la zone sûre du cerveau ne l'excluent pas).
- Décision PM : écart **accepté pour la V1**. La correction (mesurer la colonne
  dans la calibration de la zone sûre, parité Python, consigne du cerveau)
  reste hors de la Slice 10. L'écart est **montré à l'Humain avant
  `HV-REC-UI-001`**, qui décide s'il bloque la recette.
- Documenté dans `docs/capture.md` › *Interface: the left capture rail*.
