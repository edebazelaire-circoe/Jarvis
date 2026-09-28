# ISSUE-01 — Glisser un groupe dans la scène lève `ReferenceError: orbitTurns`

Découvert en Slice 00 (2026-09-25), hors périmètre de la tâche.

- `control_center_scene_interact.js:1414`, dans `orbitGroupDelta`, appelle `orbitTurns` ; `orbitReach`/`orbitInset` (ligne suivante) ne sont pas définis non plus dans ce fichier. `orbitTurns` n'existe que privé dans `control_center_scene_layout.js:842`.
- Probable mauvaise fusion de `fix/scene-deplacement-2d` (`fd76479`, commit `53c5d5d`) sur la refonte de layout `734d10a`.
- Symptôme : 4 tests de `tests/unit/test_scene_group_drag_js.py` échouent sur `main` ; le 5ᵉ (`…single_drag_unchanged`) cherche une sous-chaîne de `onPointerUp` qui n'existe plus.
- Effet utilisateur probable : déplacer un groupe d'objets orbitants casse le geste.
