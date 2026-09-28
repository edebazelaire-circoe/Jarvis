# ISSUE-04 — `verify_release.py` refuse `subprocess.run(` dans `barehands_replay.py`

Découvert en Slice 10 (2026-09-26), hors périmètre : **antérieur à cette tâche**.

- Le contrôle statique de `scripts/verify_release.py` (« dangerous execution
  primitive in Jarvis package ») cherche `subprocess.run(`, `os.system(` et
  `shell=True` dans tout `jarvis/**/*.py` hors de la liste permise de l'outil
  de banc vocal (`speaker_benchmark.py`, `speaker_benchmark_fixtures.py`).
- `jarvis/runtime/barehands_replay.py:144` appelle
  `subprocess.run([binary, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_S, check=False)`
  pour exécuter sous node le rejeu d'une trace Bare Hands (contrat, enregistreur,
  vrais moteurs). Ajouté par `d49c634` (2026-09-20, « S10: une trace qui ne
  porte aucun point de main, et un rejeu qui mesure les vrais moteurs », tâche
  d'affinage d'UI), donc présent au point de départ de cette tâche (`5ee06d7`)
  et inchangé depuis.
- Conséquence : `verify_release.py` échoue sur ce seul contrôle dès que son
  étape pytest passe. Tous les autres contrôles statiques passent (vérifié en
  Slice 10, étape pytest remplacée par un bouchon).

Pas de `shell=True`, un argv en liste, une échéance, un binaire résolu par
`shutil.which` : l'appel n'est pas dangereux en soi, c'est la règle du script
qui est totale.

**À décider par l'Humain / le mainteneur** : soit ajouter `barehands_replay.py`
à une liste permise (comme l'outil de banc vocal, avec la même garde « aucun
module de production ne l'importe »), soit refactorer le rejeu (par exemple
`asyncio.create_subprocess_exec`, ou le sortir du paquet `jarvis/` vers
`scripts/`). Attention : il est importé par `jarvis/app.py` et
`jarvis/testlab/barehands/runners.py`, donc la garde « aucun module de
production ne l'importe » de la liste permise actuelle ne s'appliquerait pas
telle quelle. Aucune des deux options n'appartient à la Slice 10.
