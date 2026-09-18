# Issue — scene-model doc overstates error-message bound

Found by Slice 01 QA re-verification (non-blocking nit).

`docs/scene-model.md` says refusal messages "never echo more than 80 characters of a received value". Patch replay and relation errors echo already-validated ids up to 128 characters (`jarvis/domain/scene.py` ~700, ~1026, ~1030). Bounded, but not to 80.

Also: `test_scene_module_is_pure_domain` allows importing `jarvis.domain._checks` but does not parse `_checks.py` itself (it imports only `re` today).

Resolution target: Slice 11 documentation pass (or any earlier Slice touching `scene.py` docs/tests).

## Résolution — Slice 11 (fermée)

- `docs/scene-model.md` (table des bornes et paragraphe de décodage) et `docs/ARCHITECTURE.md` disent maintenant la vraie règle : valeur reçue non validée recopiée sur 80 caractères au plus puis `…` ; noms de champs inconnus 40 caractères chacun, cinq au plus ; identifiant déjà validé (rejeu de patch, erreurs de relation) cité en entier, donc ≤ 128 caractères ; tout message sur entrée hostile < 300 caractères.
- `test_scene_module_is_pure_domain` analyse aussi `jarvis/domain/_checks.py` (imports permis : `__future__`, `re` ; aucun `open/print/input/exec/eval`). Contrôle par mutation : un `import os` ajouté à `_checks.py` fait échouer le test.
- Nouveau `test_validated_identifiers_echoed_in_replay_errors_stay_bounded` : une erreur de rejeu cite un identifiant de 128 caractères en entier et reste < 300 caractères.
