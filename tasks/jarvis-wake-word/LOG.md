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

## 2026-10-07 — Slice 02 (implémenteur, worktree `bww`)

- `OpenWakeWordEngine` et `openwakeword_engine_factory` dans `jarvis/adapters/wakeword_openwakeword.py` : contrat `WakeWordEngine` tenu (`frame_length` 1280, `sample_rate` 16000, `process` -> 0/-1, `delete`), `Porcupine` et `SharedPcmWakeWordBackend` inchangés, rien câblé dans `app.py`, `presentation_runtime.py` ni `voice_v2.py`.
- Seuil = 0,9 - 0,8 x sensibilité (0,5 -> 0,5, valeur recommandée par openWakeWord) ; sensibilité hors 0..1 refusée (`wake_config_invalid`), jamais bornée. Cooldown en trames de 80 ms (défaut 2000 ms = 25 trames), fenêtre fixe ouverte par la détection ; compteurs `cooldown_ignored`, `below_threshold`, `detections`, `failures`, `slow_calls` ; `last_score` exposé.
- Codes stables : `wake_engine_unavailable` (avec `cause_code` : `wake_package_missing`, `wake_package_failed`, `wake_model_missing`, `wake_model_mismatch`, `wake_model_load_failed`), `wake_config_invalid`, `wake_frame_invalid`, `wake_inference_failed`, `wake_engine_closed`. Le backend les rend en `wake_engine_unavailable` (construction) ou `wake_engine_failed` (inférence) sans toucher le micro.
- D7 : chaque `process` est chronométré ; au-delà de `DEFAULT_SLOW_CALL_MS = 40` une trace `wake.openwakeword.slow_inference` (niveau warning, code `wake_inference_slow`, durée et seuil, jamais d'audio) part vers le journal injecté, au plus une par 12 trames ; `slow_calls` compte tout.
- Écart assumé : le SLICE.md dit « le moteur ne journalise pas lui-même » ; la consigne de la Slice demande une trace de lenteur, donc le moteur accepte un `journal` facultatif (même `DiagnosticSink` que le backend). Sans journal, il reste muet.
- Tests : `tests/unit/test_openwakeword_engine.py` (78 passent, 2 `live` ignorés), commit rouge `test:` séparé puis `feat:`. Test `live` exécuté une fois à la main dans un venv jetable hors dépôt (openwakeword 0.6.0, onnxruntime 1.30.0, voix de synthèse en-US « Hey Jarvis ») : silence jamais détecté, la phrase de référence détectée une seule fois. Aucun enregistrement committé.
- Environnement : pytest-asyncio absent de l'interpréteur système ; la suite a été lancée avec un venv jetable hors dépôt (`--system-site-packages`, pytest-asyncio, openwakeword, aiohttp, httpx). Aucun `pip install` dans l'environnement principal ni dans le `.venv` du JARVIS vivant.
- Statut : livrée, en attente de QA critical (pas de fusion).
