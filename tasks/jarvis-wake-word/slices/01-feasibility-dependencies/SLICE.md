# Slice 01 — Faisabilité openWakeWord, dépendance, catalogue de modèle, licence, coût d'inférence

## Goal

Prouver qu'openWakeWord et son modèle `hey_jarvis` sont installables et exécutables dans l'environnement réel (Python 3.14), déclarer la dépendance facultative, épingler le modèle par SHA-256, documenter la licence, et mesurer le coût d'inférence par trame pour décider de l'exécuteur (D7).

## Context

Audit §7 : `openwakeword` est absent (pyproject et environnement) ; `onnxruntime 1.30.0` est présent mais non déclaré ; le Python de l'environnement est 3.14 et la compatibilité des roues n'est pas vérifiée. Le modèle est CC BY-NC-SA 4.0 d'après le handoff (non vérifié hors ligne). La section « Speaker verification (Solo Owner) » de `third_party/README.md:13` et `jarvis/adapters/sherpa_model_catalog.py` sont les modèles à copier.

## Canonical Concepts

`WakeWordEngine`, extra optionnel `pyproject.toml`, catalogue de modèle à SHA-256 épinglé, artefact hors dépôt (`runtime/`, git-ignoré par `.gitignore:6`), installation à la demande.

## Scope

### In Scope

- Essai d'installation d'`openwakeword` et de ses dépendances dans un environnement JETABLE (venv sous le répertoire scratch ou `runtime/`), jamais dans `C:/Projects/jarvis/jarvis/.venv` (le JARVIS vivant).
- Si aucune roue Python 3.14 n'existe : ne pas improviser ; rapporter au PM les options (version de Python, pipeline onnxruntime direct avec les trois modèles mel/embedding/hey_jarvis, autre moteur). La décision appartient au PM/Human.
- Extra `wakeword` dans `pyproject.toml` (`[project.optional-dependencies]`, `:16`), bornes de version mesurées.
- Nouveau `jarvis/adapters/wakeword_model_catalog.py` : spec (id, url, SHA-256, taille, licence, source de licence), vérification AVANT installation, erreur dite `wake_model_mismatch`, installation sous `runtime/wake-word/models/`, import paresseux, aucun accès réseau à l'import ni dans les tests.
- Section « Wake word (openWakeWord) » dans `third_party/README.md` : paquet Apache-2.0, modèle `hey_jarvis` CC BY-NC-SA 4.0 (confirmer à la source), non vendored, pin dans le code, usage privé non commercial, voie de remplacement.
- Mesure du coût d'`engine.process` par trame de 1280 échantillons (80 ms, 16 kHz) sur ce poste : médiane, p95, p99 ; script d'outillage `scripts/measure_wakeword_inference.py` ; résultat consigné dans `LOG.md` et dans cette Slice, avec la décision D7 (boucle asyncio ou exécuteur).
- Vérifier que rééchantillonner 24 kHz → 16 kHz avec `StreamingPcm16Resampler` (`jarvis/audio/resampling.py:39`, linéaire sans anti-repliement) ne dégrade pas la détection d'une phrase de référence ; chiffrer l'écart, ne rien corriger ici.

### Out of Scope

- Le moteur lui-même (Slice 02) ; tout câblage Voice (04, 05) ; réglages (03).
- Entraînement d'un modèle personnalisé ; distribution commerciale.
- Ajout de `openwakeword` aux dépendances obligatoires ou à l'extra `voice`.

## Dependencies

- `00-project-manager`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `pyproject.toml:16` (`voice`), `:28-34` (modèle d'extra facultatif `speaker`) : ajouter `wakeword`.
- `third_party/README.md:13` (section « Speaker verification (Solo Owner) ») : modèle de la nouvelle section.
- `jarvis/adapters/sherpa_model_catalog.py` (`SherpaModelSpec`, `download_spec` `:210`, erreur `speaker_model_mismatch` `:205`) et `jarvis/adapters/sherpa_speaker_embedder.py:89` (`file_sha256`) : modèle de vérification SHA-256.
- `jarvis/adapters/wakeword_shared_pcm.py:80-90` (`WakeWordEngine`), `:93-101` (`porcupine_engine_factory`, seule importatrice de `pvporcupine`) : forme que le moteur de la Slice 02 devra respecter ; non modifiés ici.
- `jarvis/audio/resampling.py:39` (`StreamingPcm16Resampler`).
- `.gitignore:6` (`/runtime/`) : l'artefact reste hors dépôt.
- Nouveaux : `jarvis/adapters/wakeword_model_catalog.py`, `scripts/measure_wakeword_inference.py`, `tests/unit/test_wakeword_model_catalog.py`, `tests/unit/test_wakeword_dependency_declaration.py`.

## Implementation Steps

1. Créer un environnement jetable et tenter `pip install openwakeword` ; consigner version de Python, version du paquet, roues ou compilation requise, dépendances tirées (onnxruntime/tflite).
2. Si impossible, arrêter et rapporter au PM (voir Scope).
3. Récupérer `hey_jarvis` et ses modèles de support, calculer les SHA-256, lire la licence à la source.
4. Écrire les tests rouges (catalogue, déclaration de dépendance, import paresseux).
5. Implémenter `wakeword_model_catalog.py`, déclarer l'extra, rédiger la notice.
6. Écrire et lancer `scripts/measure_wakeword_inference.py` ; consigner les chiffres et trancher D7.
7. Mesurer l'effet du rééchantillonnage 24→16 kHz sur un enregistrement de référence (jamais committé s'il contient une voix).

## Architecture Constraints

L'import d'`openwakeword`/`onnxruntime` est paresseux (construction du moteur), jamais au chargement de `jarvis.*` ; sans l'extra, Voice démarre comme aujourd'hui. Aucun téléchargement sans action explicite. Calquer les noms d'erreur sur `speaker_model_*`.

## Acceptance Criteria

- `pip install` dans l'env jetable réussit sur Python 3.14, ou le blocage est documenté et escaladé au PM sans contournement.
- `pyproject.toml` déclare `wakeword` avec bornes mesurées ; `import jarvis` fonctionne sans l'extra installé.
- Le catalogue refuse un fichier au SHA-256 différent et n'installe rien (`wake_model_mismatch`).
- `third_party/README.md` contient la section avec paquet, licences (code et modèle), politique « non vendored », remplacement ; la licence du modèle est confirmée à la source ou marquée « à confirmer » explicitement.
- Le coût médian/p95/p99 par trame est consigné et la décision D7 écrite (boucle asyncio si p99 largement sous 80 ms, sinon exécuteur dédié à spécifier dans la Slice 04).
- Aucun fichier modèle, aucun `.onnx`/`.tflite` versionné ; `git status` propre hors fichiers prévus.

## Tests to write (red then green)

- `tests/unit/test_wakeword_model_catalog.py` : `test_a_model_with_a_different_sha256_installs_nothing`, `test_a_verified_model_is_installed_under_the_runtime_root`, `test_no_network_is_touched_at_import_or_by_the_tests`, `test_the_catalog_records_the_license_and_its_source`.
- `tests/unit/test_wakeword_dependency_declaration.py` : `test_the_wakeword_extra_is_declared_and_optional`, `test_importing_jarvis_does_not_import_openwakeword`, `test_no_model_artifact_is_tracked_by_git`.
- Test de balayage vie privée : aucun chemin personnel dans la notice ni les preuves (étendre le balayage existant s'il y en a un).

## Documentation Updates

`third_party/README.md` (section Wake word). La doc d'exploitation est faite en Slice 08.

## QA level

critical (qa-verification + code-review + runtime-validation sur l'installation réelle ; mutation : ≤10 mutants foreground sur la vérification SHA-256 et l'import paresseux, avec un témoin cosmétique qui doit survivre).

## Risks

- Pas de roue openwakeword pour Python 3.14 : bloquant, escalade.
- Modèle téléchargé à l'exécution : SHA-256 épinglé obligatoire, aucune confiance dans l'URL.
- Licence du modèle non vérifiable hors ligne : ne jamais l'affirmer sans source.
- Installer dans le venv vivant casserait le JARVIS du Human : interdit.

## Handoff Notes

Coding Slice : charger `/caveman` et `/coding-guideline` ; `/error-handling` si un chemin peut échouer. Un seul implémenteur dans le worktree `bww`. Tests en avant-plan, un fichier à la fois. Écrire d'abord les tests rouges, les committer (`test:`), puis l'implémentation (`feat:`/`fix:`).

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D3** — Licence : modèle `hey_jarvis` réservé aux tests privés (CC BY-NC-SA 4.0 d'après le handoff, à confirmer en Slice 01) ; artefact hors dépôt sous `runtime/`, SHA-256 épinglé dans le code, installation à la demande ; notice dans `third_party/README.md`.
- **D6** — Aucune migration SQLite (réglages JSON). Si une Slice en découvre le besoin : stop, suivre `CLAUDE.md`, prévenir le Human.
- **D7** — En SIMPLE l'inférence ne tourne jamais dans le rappel PortAudio (file vers un consommateur) ; en PRESENTATION `engine.process` s'exécute sur la boucle asyncio (`wakeword_shared_pcm.py:217`) : coût mesuré en Slice 01 avant de décider d'un exécuteur.

Interdits (toutes Slices) :

- Pas de migration SQLite, pas de modification de `jarvis.sqlite3` / `scene.sqlite3` ni de `_MIGRATIONS` (D6).
- Pas de second flux micro sans inscription dans `jarvis/audio/input_ownership.py` (constante `OWNER_*`, `register_input_stream`, libération y compris sur échec de fermeture) ET sans mise à jour de `EXPECTED_INPUT_OPENERS` (`tests/unit/test_presentation_audio_capture.py:1653`) et des comptes de propriétaires « SIMPLE = 2, PRESENTATION = 1 » (tests `:243` et `:329`) : on étend ces tests, on ne les contourne pas.
- Pas d'inférence (`engine.process`, onnxruntime) dans le rappel PortAudio : le rappel ne fait que copier/mettre en file (D7).
- Pas de nouvelle machine d'états : réutiliser `VoiceLifecycleState` (D5).
- Pas de modification de `ATTRIBUTE_KEYS` (`jarvis/domain/conversation_events.py:233`) ni de nouveau type d'événement de timeline (D4).
- Pas de PCM persisté : ni fichier, ni base, ni trace (le pré-roll reste une deque bornée en mémoire).
- Aucun chemin personnel ni nom d'utilisateur Windows dans les preuves, tests, docs ou traces committées.
- Aucune écriture dans `C:/Projects/jarvis/jarvis` (JARVIS vivant du Human) ni dans un autre worktree ; pas de `git stash`, de `push`, de `run_in_background`, de Monitor ; tests en avant-plan, un fichier à la fois.
- Pas de `pip install` dans `C:/Projects/jarvis/jarvis/.venv`.

Scope in (précisions contraignantes) :

- Aucune ligne de `jarvis/` hors `wakeword_model_catalog.py` n'est modifiée ; `wakeword_shared_pcm.py` n'est lu que pour la forme du contrat.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.
