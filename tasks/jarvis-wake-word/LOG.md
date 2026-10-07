# Execution Log

Reserved for implementation agents. Record only real implementation progress, evidence, decisions, and deviations.

## 2026-10-07 — Slice 00 (agent 0, orchestrateur)

- Slice 00 faite : audit à l'aveugle (`docs/01-blind-audit.md`), `slices/00-project-manager/READINESS.md`, `slices/TODO.md`.
- Baseline au point de branche `3bc7acf` : tests/unit 421 fichiers / 12 539 tests, 6 échecs hérités ; tests/integration 73 fichiers / 669 tests, 0 échec (un test intermittent connu : `test_stopping_the_server_releases_a_pending_long_poll`). Liste des échecs hérités dans READINESS.md.
- Aucun `slices/` ni `SLICE.md` reçu du handoff : le découpage (Slices 01 à 09) et leurs contrats (`SLICE.md`, `metadata.json`, `human-validation.json` pour 07 et 09) ont été écrits par la Slice 00.
- Décisions D1-D7 prises par l'agent 0 (recommandations appliquées) : à confirmer par le Human.

## 2026-10-07 — Slice 01 (implémenteur, worktree `bww`)

- Faisabilité d'openWakeWord sur Python 3.14.6 : OUI. `openwakeword 0.6.0` (roue pure Python) + `onnxruntime 1.30.0`, `numpy 2.5.3`, `scipy 1.18.1`, `scikit-learn 1.9.1` s'installent en roues, sans compilation, dans un venv jetable hors dépôt. Rien n'a été installé dans l'environnement du JARVIS vivant.
- Modèles : trois ONNX de la publication amont `v0.5.1`, SHA-256 et tailles épinglés dans `jarvis/adapters/wakeword_model_catalog.py` (erreurs `wake_model_missing`, `wake_model_mismatch`, `wake_model_download_failed`, `wake_model_install_failed`), installation à la demande sous `runtime/wake-word/models/`. Extra `wakeword` déclaré dans `pyproject.toml` (`numpy>=2.0,<3`, `onnxruntime>=1.30,<2`, `openwakeword>=0.6,<0.7`), absent des dépendances obligatoires et de `voice`.
- Licence : code Apache-2.0, modèles CC BY-NC-SA 4.0, confirmé à la source (README amont, section « License ») le 2026-10-07. Notice dans `third_party/README.md`.
- Coût par trame de 80 ms (ONNX, CPU de ce poste, à vide) : p50 2,7 à 3,2 ms, p95 3,3 à 4,3 ms, p99 3,8 à 6,2 ms, max 11,5 ms. Décision D7 proposée : `engine.process` reste sur la boucle asyncio, avec trace dite si un appel dépasse un seuil à spécifier ; à confirmer par le Human. Détail et tableau dans `slices/01-feasibility-dependencies/SLICE.md` (section « Résultat Slice 01 »).
- Rééchantillonnage 24 -> 16 kHz linéaire : écart de pic de score inférieur à 0,011 contre un rééchantillonnage filtré (nul sur deux voix anglaises de synthèse). La voix française de synthèse ne dépasse pas 0,22 dès la référence : le modèle est anglophone.
- Tests : 18 tests neufs verts (catalogue 14, déclaration de dépendance 4), écrits rouges d'abord (commit `test:` séparé). Aucune base SQLite, aucune migration, aucune ligne de `jarvis/` modifiée hors `wakeword_model_catalog.py`.
- Écart : `pip install .[wakeword]` dans un venv jetable a régénéré `jarvis_local_v1.egg-info/` (suivi par git, étonnamment) et créé `build/` ; restaurés/supprimés avant commit.
- Statut : livrée, en attente de QA critical (pas de fusion).
