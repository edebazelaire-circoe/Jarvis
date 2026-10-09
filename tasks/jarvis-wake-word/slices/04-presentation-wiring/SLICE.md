# Slice 04 — Fabrique de moteur configurable côté PRESENTATION, traces score/seuil

## Goal

Brancher le moteur openWakeWord sur le détecteur à PCM partagé de PRESENTATION par échange de fabrique, selon les réglages, avec traces de score et de seuil dans le journal, sans second flux micro.

## Context

Audit §1/§3 : en PRESENTATION le hub est l'unique propriétaire du micro ; la fabrique Porcupine est câblée en dur (`presentation_runtime.py:1717-1720`, gardée par `self.wake_access_key`). `SharedPcmWakeWordBackend` lit le PCM du hub et appelle `engine.process` synchrone sur la boucle asyncio (`wakeword_shared_pcm.py:217`). La décision D7 (exécuteur ou non) est tranchée par la mesure de la Slice 01.

## Canonical Concepts

`SharedPcmWakeWordBackend`, fabrique de moteur, `PresentationAudioSession`, `ExplicitAddressSource.WAKE_WORD`, journal `voice.wake`.

## Scope

### In Scope

- Sélection de la fabrique dans `PresentationStackBuilder.build` (`presentation_runtime.py:1717-1720`) : openWakeWord si `wake_word.enabled` et fournisseur disponible ; sinon comportement actuel (Porcupine si clé) ; la touche manuelle reste toujours présente.
- Passage des réglages (`wake_word_settings.load`) jusqu'au constructeur de la pile, par le mécanisme déjà utilisé pour `wake_access_key`/`keyword` ; pas de lecture de fichier dans l'adaptateur.
- Mise en œuvre de D7 selon la mesure de 01 : si `engine.process` doit quitter la boucle, un exécuteur borné unique, sans perte silencieuse de trames (compteur dit).
- Traces dans le journal : `wake.shared_pcm.*` existantes enrichies d'un score, d'un seuil et d'un fournisseur ; `voice.wake` reste émis par Voice (`voice_v2.py:409`). Aucun PCM, aucun texte dans les traces.
- Pannes d'init/de moteur : codes existants (`wake_engine_unavailable`, `wake_engine_failed`, `wake_subscription_refused`, `wake_consume_failed`) ; F9 reste utilisable.

### Out of Scope

- SIMPLE (Slice 05) ; propagation de la source jusqu'à `activate()` (Slice 06).
- Nouveau type de détection dans le port ; modification de `ATTRIBUTE_KEYS`.
- Changement de l'AEC ou de la garde d'écho (voir Slice 09 pour la mesure).

## Dependencies

- `02-openwakeword-engine`
- `03-wake-word-settings`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/runtime/presentation_runtime.py:1704` (import de `porcupine_engine_factory`), `:1717-1720` (fabrique en dur), `:1237-1240` (`_suspend_simple` avant `stack.start()`), `:709` (`PresentationWakeRouter`), `:854` (`_label`, armement `turns.arm`).
- `jarvis/adapters/wakeword_shared_pcm.py:104-142` (constructeur), `:156-197` (`start`), `:198-227` (`_consume`, `:217`), `:243` (`_detected`), `:255` (`_fail`), `:389` (`stats`).
- `jarvis/runtime/presentation_audio.py` (`PresentationAudioSession.build`, paramètre `wake_engine_factory`).
- `jarvis/app.py:909` (lecture des réglages à `main`), `:959-971` (composition SIMPLE, lue pour comparaison, modifiée en Slice 05).
- `jarvis/audio/capture_hub.py:592` (`subscribe`) : le détecteur reste un abonné, aucun nouvel ouvreur.
- Tests : `tests/unit/test_presentation_audio_capture.py` (`FakeCaptureDevice` `:98`, `FakeWakeEngine` `:161`, `sine_block` `:232`, `EXPECTED_INPUT_OPENERS` `:1653`), `tests/unit/test_presentation_integration.py`, `tests/integration/test_presentation_scenarios.py`.
- Nouveau : `tests/unit/test_presentation_wake_word_wiring.py`.

## Implementation Steps

1. Écrire les tests rouges de sélection de fabrique, d'absence de second flux et de traces.
2. Étendre la construction de pile pour recevoir les réglages et choisir la fabrique.
3. Appliquer la décision D7 (exécuteur ou boucle) avec compteur de trames perdues.
4. Enrichir les traces du backend (score, seuil, fournisseur) sans texte ni audio.
5. Vérifier que `EXPECTED_INPUT_OPENERS` et les comptes de propriétaires de PRESENTATION restent à 1.
6. Rejouer `test_presentation_*` et le scénario d'intégration.

## Architecture Constraints

Échange de fabrique, pas de nouvelle couche. Le détecteur PRESENTATION reste un abonné du hub ; aucun second flux. Si l'inférence quitte la boucle, c'est par un exécuteur borné, jamais le rappel PortAudio (D7). Une panne du fournisseur est dite et n'empêche ni la séance ni F9.

## Acceptance Criteria

- Avec `wake_word.enabled=true` et openWakeWord disponible, la pile PRESENTATION construit le moteur openWakeWord ; avec `false` ou indisponible, le comportement est celui d'avant (test d'équivalence).
- `physical_input_owners() == 1` en PRESENTATION ; `input_ownership.open_input_stream_count()` inchangé ; `EXPECTED_INPUT_OPENERS` inchangé ou étendu explicitement.
- Une détection du moteur injecté produit une trace avec `score`, `threshold`, `provider` ; aucune trace ne contient d'octets PCM ni de texte de parole.
- Une panne du moteur laisse la touche manuelle fonctionnelle et la séance vivante.
- Le coût d'inférence ne bloque pas la boucle au-delà du budget fixé en Slice 01 (test avec moteur lent factice si exécuteur).
- Les tests `test_presentation_*` existants et `tests/integration/test_presentation_scenarios.py` restent verts.

## Tests to write (red then green)

- `tests/unit/test_presentation_wake_word_wiring.py` : `test_enabled_setting_selects_the_openwakeword_factory`, `test_disabled_setting_keeps_the_previous_factory`, `test_missing_provider_degrades_to_manual_key_only`, `test_presentation_still_holds_exactly_one_physical_input_owner`, `test_detection_trace_carries_score_threshold_provider`, `test_no_pcm_or_speech_text_reaches_the_journal`, `test_engine_failure_keeps_the_manual_key_usable`, `test_a_slow_engine_does_not_stall_the_event_loop` (si exécuteur), `test_dropped_frames_are_counted_not_silent`.
- Étendre `tests/unit/test_presentation_audio_capture.py` si nécessaire : le nombre de propriétaires reste `1`.

## Documentation Updates

Mise à jour de `docs/presentation-audio-capture.md` faite en Slice 08 ; ici, docstrings seulement.

## QA level

critical (qa-verification + code-review + runtime-validation avec capture factice composée ; agent-trace-analysis sur une trace réelle du journal ; mutation ≤10 mutants foreground sur la sélection de fabrique, la préservation du compte de propriétaires et le contenu des traces, avec un témoin cosmétique).

## Risks

- Bloquer la boucle asyncio avec l'inférence (D7) : mesure et test de lenteur.
- Régression du comportement Porcupine : test d'équivalence.
- Fuite de contenu dans les traces : test dédié.
- Rééchantillonnage 24→16 kHz sans anti-repliement : écart mesuré en 01, validation réelle en 09.

## Handoff Notes

Coding Slice : charger `/caveman` et `/coding-guideline` ; `/error-handling` si un chemin peut échouer. Un seul implémenteur dans le worktree `bww`. Tests en avant-plan, un fichier à la fois. Écrire d'abord les tests rouges, les committer (`test:`), puis l'implémentation (`feat:`/`fix:`).

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D1** — `wake_word.enabled` : défaut `false`. Aucun micro ouvert au repos tant que le Human n'a pas activé le mot d'éveil.
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

Scope in (précisions contraignantes) :

- Le détecteur PRESENTATION lit le PCM du hub : aucun flux supplémentaire, jamais.

Scope out (précisions contraignantes) :

- `PresentationWakeRouter` ne change pas de sémantique ; l'armement `turns.arm` reste tel quel.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.
