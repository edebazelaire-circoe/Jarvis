# Slice 02 — OpenWakeWordEngine conforme à WakeWordEngine

## Goal

Fournir `OpenWakeWordEngine`, un moteur local conforme au contrat existant `WakeWordEngine`, avec seuil de sensibilité, cooldown, et dernier score exposé, sans changer le contrat du port.

## Context

Audit §1 et §11 : le contrat de moteur existe (`wakeword_shared_pcm.py:80-90`, forme `pvporcupine` : `frame_length`, `sample_rate`, `process(pcm_tuple_int16) -> int`, `delete()`). Le port `WakeWordBackend` (`jarvis/ports/v2.py:229-234`) ne transporte que des chaînes : la confiance se perd au moteur. Le moteur garde donc le score en attribut observable ; la propagation en trace est faite en Slice 04/05.

## Canonical Concepts

`WakeWordEngine`, `process() >= 0` = détecté, seuil/sensibilité, cooldown (trames comptées, pas horloge murale), fabrique paresseuse.

## Scope

### In Scope

- Nouveau `jarvis/adapters/wakeword_openwakeword.py` : classe `OpenWakeWordEngine` (`frame_length = 1280`, `sample_rate = 16000`), `process` renvoie `0` sur détection (indice du mot-clé), `-1` sinon ; `delete()` libère le modèle ; attributs `last_score`, `threshold`, `provider = "openwakeword"`, `keyword`.
- Seuil dérivé de `sensitivity` (0..1) par une fonction pure documentée et testée ; valeur par défaut raisonnable justifiée par la mesure de la Slice 01.
- Cooldown en nombre de trames (ou durée convertie en trames) : un énoncé ne déclenche qu'une détection ; compteur `cooldown_ignored`, `below_threshold` observables.
- Fabrique `openwakeword_engine_factory(*, keyword, sensitivity, cooldown_ms, model_dir)` calquée sur `porcupine_engine_factory` (`:93-101`) : import paresseux, erreurs dites (`wake_engine_unavailable` si paquet ou modèle absent, via les codes existants du backend).
- Moteur de test déterministe sans onnxruntime (rejouer des scores injectés) pour les tests unitaires ; un seul test marqué `live` charge le vrai modèle (ignoré sans l'extra).

### Out of Scope

- Câblage dans PRESENTATION (04) et SIMPLE (05).
- Lecture des réglages (03).
- Toute modification de `WakeWordBackend` ou de `WakeWordEngine` ; propagation du score hors du moteur.

## Dependencies

- `01-feasibility-dependencies`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/adapters/wakeword_shared_pcm.py:80-90` (`WakeWordEngine`), `:93-101` (`porcupine_engine_factory`), `:198-227` (`_consume`, `engine.process` `:217`), `:255` (`_fail`) : contrat et usage consommateur.
- `jarvis/adapters/wakeword_porcupine.py:53-69` (rappel PortAudio appelant `engine.process` `:63`) : lu uniquement ; ce chemin est traité en Slice 05.
- `tests/unit/test_presentation_audio_capture.py:161` (`FakeWakeEngine`), `tests/unit/test_v2_wake_backends.py` : harnais et style de test.
- Nouveaux : `jarvis/adapters/wakeword_openwakeword.py`, `tests/unit/test_openwakeword_engine.py`.
- Dépend de `jarvis/adapters/wakeword_model_catalog.py` (Slice 01) pour localiser les modèles.

## Implementation Steps

1. Écrire les tests rouges du moteur (scores injectés).
2. Implémenter la fonction pure sensibilité → seuil et le cooldown en trames.
3. Implémenter le moteur et sa fabrique paresseuse ; mapper les pannes d'initialisation sur des erreurs dites.
4. Test `live` optionnel avec le modèle réel et la phrase de référence.
5. Vérifier la conformité structurelle au contrat (`frame_length`, `sample_rate`, `process`, `delete`) par un test partagé avec le moteur Porcupine factice.

## Architecture Constraints

Le moteur est pur calcul : il n'ouvre aucun flux et n'écrit aucun fichier. Il accepte un `journal` **facultatif** (même `DiagnosticSink` que le backend), uniquement pour la trace de lenteur `wake.openwakeword.slow_inference` (D7, code `wake_inference_slow`, durée et seuil, jamais d'audio) ; sans journal il reste muet, et c'est le backend qui trace le reste. *(Aligné en Slice 08 : cette ligne disait « ne journalise pas lui-même ».)* Le contrat `WakeWordEngine` n'est pas modifié ; l'état du score est un attribut lu par l'appelant. Import d'`openwakeword` dans la fabrique seulement.

`OpenWakeWordEngine.process` n'accepte qu'**un tuple (ou une liste) d'entiers** de 1280 échantillons int16 : un `numpy.array` ou des `bytes` sont refusés (`wake_frame_invalid`). Les deux détecteurs (partagé et à flux propre) dépaquettent donc eux-mêmes le PCM en tuple d'entiers avant l'appel *(précision ajoutée en Slice 08, polish de la QA de la Slice 02)*.

## Acceptance Criteria

- `process` renvoie `-1` pour un score sous le seuil et `0` au-dessus ; `last_score` reflète la dernière trame.
- Deux trames consécutives au-dessus du seuil dans la fenêtre de cooldown produisent UNE détection ; une détection après la fin du cooldown est acceptée.
- La sensibilité change le seuil de façon monotone ; valeurs hors 0..1 refusées ou bornées de façon dite et testée.
- Une trame de mauvaise longueur ou de mauvais type lève une erreur explicite (pas de silence).
- `delete()` est idempotent et libère le modèle.
- Sans l'extra installé, la fabrique lève l'erreur de disponibilité attendue et `SharedPcmWakeWordBackend` la rend en `wake_engine_unavailable` sans planter Voice.
- Aucun fichier, aucun flux ouvert par le moteur.

## Tests to write (red then green)

- `tests/unit/test_openwakeword_engine.py` : `test_a_score_below_the_threshold_is_not_a_detection`, `test_a_score_above_the_threshold_is_a_detection`, `test_one_utterance_yields_one_detection_during_the_cooldown`, `test_a_detection_after_the_cooldown_is_accepted`, `test_sensitivity_maps_monotonically_to_the_threshold`, `test_out_of_range_sensitivity_is_refused_or_clamped_loudly`, `test_a_wrong_sized_frame_raises`, `test_delete_is_idempotent`, `test_last_score_is_exposed`, `test_the_engine_opens_no_stream_and_writes_no_file`, `test_the_engine_satisfies_the_wakeword_engine_contract`.
- `tests/unit/test_openwakeword_engine.py` (suite backend) : `test_shared_pcm_backend_reports_wake_engine_unavailable_when_the_package_is_missing` (réutilise `SharedPcmWakeWordBackend` avec la fabrique).
- `@pytest.mark.live` : `test_the_real_model_detects_the_reference_phrase` (ignoré sans l'extra ni le modèle).

## Documentation Updates

Docstring de module en français (pourquoi un score en attribut et pas dans le port) ; la doc canonique est mise à jour en Slice 08.

## QA level

critical (qa-verification + code-review + runtime-validation ; mutation ≤10 mutants foreground sur le seuil, le cooldown, la monotonie sensibilité→seuil, avec un témoin cosmétique qui doit survivre).

## Risks

- Cooldown mesuré à l'horloge murale rendrait les tests flaky : compter des trames.
- Trame de 1280 échantillons contre blocs de 50 ms du hub : le backend gère le report (`_carry`) ; ne pas dupliquer cette logique ici.
- Seuil par défaut mal calibré : la calibration réelle est une validation Human (Slice 09).
- Les modèles openWakeWord sont sensibles au rééchantillonnage : écart mesuré en Slice 01.

## Handoff Notes

Coding Slice : charger `/caveman` et `/coding-guideline` ; `/error-handling` si un chemin peut échouer. Un seul implémenteur dans le worktree `bww`. Tests en avant-plan, un fichier à la fois. Écrire d'abord les tests rouges, les committer (`test:`), puis l'implémentation (`feat:`/`fix:`).

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D3** — Licence : modèle `hey_jarvis` réservé aux tests privés (CC BY-NC-SA 4.0 d'après le handoff, à confirmer en Slice 01) ; artefact hors dépôt sous `runtime/`, SHA-256 épinglé dans le code, installation à la demande ; notice dans `third_party/README.md`.
- **D4** — Vocabulaire : réglages snake_case, bloc `wake_word` ; traces `voice.wake` enrichies (score, seuil, fournisseur) dans le journal `runtime/trace.jsonl`, pas dans la timeline ; sources existantes `wake_word` / `manual_key` (pas `keyboard_f9`).
- **D5** — Aucune seconde machine d'états : `VoiceLifecycleState` (`jarvis/domain/v2.py:81`) reste la source de vérité ; « PASSIVE » du handoff = `BACKGROUND`.
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
- Pas de thread, pas de tâche asyncio, pas de file dans le moteur : l'ordonnancement appartient aux backends.

Scope in (précisions contraignantes) :

- `WakeWordBackend` (`jarvis/ports/v2.py:229`) reste inchangé : le score ne voyage pas par le port.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.
