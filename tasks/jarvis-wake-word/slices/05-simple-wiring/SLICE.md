# Slice 05 — Détecteur SIMPLE à flux propre avec moteur injecté

## Goal

Permettre au mode SIMPLE (repos, sans hub) d'écouter « Hey Jarvis » avec le moteur openWakeWord, par un détecteur à flux propre généralisé à un moteur injecté, inscrit comme propriétaire du micro, sans inférence dans le rappel PortAudio.

## Context

Audit §1/§3 : `PorcupineWakeWordBackend` ouvre son `sd.RawInputStream` (`wakeword_porcupine.py:71`), s'inscrit sous `OWNER_WAKEWORD_PORCUPINE` (`:72`) mais appelle `engine.process` dans le rappel PortAudio (`:53-69`, appel `:63`). En SIMPLE il n'y a pas de hub au repos : un détecteur à flux propre est nécessaire (préserve D14 : sans mot d'éveil activé, aucun flux). La composition SIMPLE est à `jarvis/app.py:959-971`.

## Canonical Concepts

Propriétaire du micro (`input_ownership`), détecteur à flux propre, file entre rappel et consommateur, `EXPECTED_INPUT_OPENERS`, suspension à l'entrée en session active.

## Scope

### In Scope

- Généraliser `jarvis/adapters/wakeword_porcupine.py` (ou nouvel adaptateur à flux propre `wakeword_own_stream.py`, choix tranché en Slice : privilégier la généralisation si elle ne change pas le comportement Porcupine) pour accepter un moteur injecté (`engine_factory`), le rappel PortAudio ne faisant que copier les octets dans une file bornée ; l'inférence tourne dans un consommateur hors rappel (D7).
- Si un nouvel ouvreur ou un nouveau propriétaire est créé : constante `OWNER_*` dans `jarvis/audio/input_ownership.py:49-56`, inscription, libération y compris si `stop`/`close` échoue, ajout à `EXPECTED_INPUT_OPENERS` (`tests/unit/test_presentation_audio_capture.py:1653`) et test `…second_microphone_owner`.
- Composition SIMPLE (`jarvis/app.py:959-971`) : si `wake_word.enabled` et fournisseur disponible, ajouter le détecteur openWakeWord au composite ; Porcupine inchangé quand sa clé existe ; aucune des deux voies ne s'active sans réglage/clé (D1).
- `suspend()`, `suspend_for_active_session()` et `resume()` : le flux se ferme pendant ACTIVE (comme Porcupine : un seul propriétaire à la fois, `docs/presentation-audio-capture.md:20`) et se rouvre à la mise en veille ; `close()` libère tout.
- Changement de périphérique d'entrée : le détecteur suit `audio_input_device` (`app.py:957-958`) au démarrage ; pas de hot-plug en v1, dit en doc.

### Out of Scope

- PRESENTATION (Slice 04) ; propagation de la source (06) ; UI (07).
- Fan-out du flux SIMPLE vers STT/Brain (aucune STT au repos : audit §3).
- Réécriture du détecteur Porcupine au-delà de la généralisation nécessaire.

## Dependencies

- `02-openwakeword-engine`
- `03-wake-word-settings`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/adapters/wakeword_porcupine.py:30` (constructeur), `:40-72` (`start`, rappel `:53`, appel `engine.process` `:63`, flux `:71`, inscription `:72`), `:75` (`_detected`), `:79-98` (`suspend`, `suspend_for_active_session`, `resume`), `:99` (`detections`), `:104` (`close`).
- `jarvis/audio/input_ownership.py:49-56` (`OWNER_*`), `:83` (`register_input_stream`), `:132` (`reset_for_test`).
- `jarvis/app.py:886-888` (imports), `:957-971` (clavier + Porcupine + Composite), `:849` et `:967` (`JARVIS_WAKE_KEYWORD`).
- `jarvis/adapters/wakeword_composite.py` (fan-in), `jarvis/adapters/wakeword_keyboard.py:58-62` (reste armé en ACTIVE).
- `jarvis/runtime/voice_v2.py:734` (`suspend_for_active_session`), `:1299` (`resume` en fin de `mute()`).
- `tests/unit/test_presentation_audio_capture.py:243` (un seul propriétaire en PRESENTATION), `:329` (SIMPLE garde ses deux propriétaires), `:1653-1704` (`EXPECTED_INPUT_OPENERS`, conformité), `:483`/`:1727` (`presentation_second_microphone_owner`) ; `tests/unit/test_v2_wake_backends.py`, `tests/unit/test_owner_input_gate.py`.
- Nouveau : `tests/unit/test_simple_wake_word_wiring.py`.

## Implementation Steps

1. Écrire les tests rouges : rappel sans inférence, file bornée, propriétaire inscrit/libéré, composition conditionnelle.
2. Généraliser le détecteur à flux propre pour un moteur injecté ; déplacer l'inférence hors du rappel.
3. Inscrire le propriétaire, étendre `EXPECTED_INPUT_OPENERS` si une nouvelle constante apparaît, adapter les comptes testés (étendre, ne pas contourner).
4. Câbler `app.py` sous condition de réglage ; vérifier le défaut `false` (aucun flux ouvert).
5. Vérifier les cycles `suspend`/`resume`/`close` et la libération sur échec.

## Architecture Constraints

Un seul ouvreur de flux de repos en SIMPLE par détecteur actif ; inscription dans `input_ownership` obligatoire ; le rappel PortAudio ne fait que `put_nowait` dans une file bornée (perte comptée et dite si pleine). Pas de nouvelle machine d'états : le détecteur suit `suspend`/`resume` pilotés par `VoiceLifecycleState` via `voice_v2`.

## Acceptance Criteria

- Avec `wake_word.enabled=false` (défaut) et sans clé Porcupine, `open_input_stream_count() == 0` au repos en SIMPLE.
- Avec openWakeWord activé, un seul flux est ouvert au repos, inscrit sous un propriétaire connu ; il est fermé pendant ACTIVE et rouvert après `mute()` ; zéro flux après `close()`.
- Le rappel PortAudio n'appelle jamais `engine.process` (test qui échoue si l'appel a lieu dans le thread du rappel).
- Une file pleine perd une trame de façon comptée et tracée, sans bloquer le rappel.
- Un échec de fermeture du flux libère quand même le propriétaire de `input_ownership`.
- `test_every_input_stream_opener_is_registered` (conformité `EXPECTED_INPUT_OPENERS`) reste vert avec la liste étendue.
- Porcupine se comporte exactement comme avant (tests existants verts).

## Tests to write (red then green)

- `tests/unit/test_simple_wake_word_wiring.py` : `test_disabled_by_default_opens_no_stream_in_simple`, `test_enabled_opens_exactly_one_registered_stream`, `test_the_portaudio_callback_never_runs_inference`, `test_a_full_queue_drops_counted_frames_without_blocking`, `test_stream_is_closed_during_active_and_reopened_after_mute`, `test_close_releases_the_owner_even_if_stream_close_fails`, `test_composition_adds_the_detector_only_when_enabled_and_available`, `test_porcupine_path_is_unchanged`, `test_detection_reaches_voice_as_a_wake_word_label`.
- Étendre `tests/unit/test_presentation_audio_capture.py` : `EXPECTED_INPUT_OPENERS` (si nouvel ouvreur) et comptes SIMPLE (`:329`).

## Documentation Updates

Docstrings ; doc canonique en Slice 08.

## QA level

critical (qa-verification + code-review + runtime-validation sur la composition SIMPLE avec flux factice ; mutation ≤10 mutants foreground sur l'appel d'inférence hors rappel, l'inscription/libération du propriétaire, la condition de composition, avec un témoin cosmétique).

## Risks

- Fuite de propriétaire du micro à l'arrêt ou sur échec de fermeture : test dédié.
- Contention micro entre le détecteur SIMPLE et la session Realtime : fermeture avant `stack.start()`/session active, déjà éprouvée pour Porcupine.
- Régression de D14 : le test « défaut = aucun flux » est obligatoire.
- Le même micro vu par Porcupine ET openWakeWord s'ils sont tous deux activés : un seul flux à la fois par politique à trancher et testée (ne jamais ouvrir deux flux de repos).

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

- Toute nouvelle `OWNER_*` ET `EXPECTED_INPUT_OPENERS` mis à jour dans le même commit.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.

## Résultat

Livrée par `bww`, puis reprise après QA critical (branche `fix/ww-s5-rework`, worktree `bqa`).

Contrat de panne, tel qu'il est maintenant écrit et testé :

- une panne de **construction** du moteur (`wake_engine_unavailable`) est dite avec son `cause_code` et n'ouvre aucun flux, mais elle n'est pas définitive : chaque `resume()` retente la construction, **au plus une tentative par `resume()`**, jamais de boucle interne. Un succès rétablit l'état normal (`engine_failed` faux, trace d'échec réarmée). L'ancien contrat « le moteur tombé ne se relance pas » est retiré ;
- une panne d'**inférence** (`wake_engine_failed`) reste terminale pour la séance en cours (flux fermé et libéré) et le prochain `resume()` reconstruit un moteur neuf ;
- une trace d'échec identique (même code, même `cause_code`) n'est écrite qu'une fois par minute ; la suivante porte `suppressed`. Rework QA 2 : la clé n'est réarmée que lorsque son cycle a réussi de bout en bout (flux ouvert pour `wake_input_unavailable`, une trame traitée sans échec pour `wake_engine_failed`, moteur construit pour `wake_engine_unavailable`), jamais à la seule construction du moteur (un micro refusé produisait une trace par tentative) ;
- `detections()` ne se termine plus sur une panne (seulement à `close()`) : sinon la tâche de relais du `CompositeWakeWordBackend` mourrait et un `resume()` réussi ne servirait à rien ;
- annulation ou fermeture pendant la construction (premier chargement, environ 1,6 s) : le moteur construit est supprimé une fois, quel que soit le côté qui arrive le dernier ;
- `detection_trace_data` ne perd jamais une détection pour une trace : lecture protégée attribut par attribut, `score` et `seuil` tracés seulement s'ils sont des flottants finis, sinon la clé est omise.

Limites connues, volontairement non corrigées (documentées seulement) :

- **I1** : si le thread d'inférence ne s'arrête pas dans le délai (`wake_consumer_stuck`), le moteur de ce thread n'est jamais supprimé explicitement (le thread peut encore s'en servir) et le tampon de reste de trame (`carry`) reste partagé avec lui. Le fil est démon : il disparaît avec le processus.
- **I2** : tant que l'inférence est bloquée, la file PCM se remplit et le rappel perd des blocs ; le compte `pcm_blocks_dropped` monte, mais `wake_pcm_dropped` n'est émis que par le thread consommateur, donc reste silencieux jusqu'à son retour (le total figure dans `wake.own_stream.stopped`).
- **Contrat un seul consommateur** : `last_detection` est un champ unique, écrit dans `detections()`. Voice OU le routeur de présentation consomme un détecteur à flux propre, jamais deux. Un second itérateur concurrent attendrait indéfiniment après `close()` (le jeton de fin n'est consommé qu'une fois). Code inchangé.
