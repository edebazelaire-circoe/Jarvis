# Slice 06 — Source propagée jusqu'à activate(), parité F9/mot d'éveil, veille vocale minimale

## Goal

Garantir que F9 et le mot d'éveil traversent un seul chemin d'activation avec la source (`wake_word` / `manual_key`) propagée jusqu'à `activate()` et à la trace, et étendre minimalement la veille vocale existante (D2).

## Context

Audit §2 : le chemin unique existe de fait : toute détection (`'f9'` ou `'jarvis'`) mène à `await self.activate()` (`voice_v2.py:405-410`) ; la source ne sert qu'à la trace (`voice.wake`, `source=keyword`, `:409`) ; `rebind_board` appelle `activate()` sans source (`:549`). Mise en veille actuelle : F9 en ACTIVE, phrase exacte « Jarvis mute » (`realtime_audio.py:4954-4964`), timeout (90 s), `POST /api/live/stop`. Le vocabulaire existant est `ExplicitAddressSource` (`jarvis/domain/explicit_address.py:46-50`) : `WAKE_WORD`, `MANUAL_KEY` ; pas `keyboard_f9` (D4).

## Canonical Concepts

Chemin d'activation unique, `ExplicitAddressSource`, `VoiceLifecycleState`, « Jarvis mute ».

## Scope

### In Scope

- Faire porter la source de la détection à `activate()` par un paramètre optionnel (`activate(source=None)`), sans second chemin : le corps reste unique ; les appelants existants (`rebind_board` `:549`) restent valides.
- Traces : `voice.wake` porte `source` (étiquette existante) et, quand le détecteur la fournit, `score`/`threshold`/`provider` (Slice 04/05) ; états avant/après (`state_before`, `state_after`) tirés de `VoiceLifecycleState`.
- Test de parité : même entrée simulée par F9 et par un moteur factice → même suite d'appels et même état final, seules les étiquettes de trace diffèrent.
- Veille vocale (D2) : élargir MINIMALEMENT la détection de « Jarvis mute » (`realtime_audio.py:4954-4964`) si, et seulement si, une variante simple et sûre est justifiée (ex. « Jarvis, mute » déjà couvert par la normalisation) ; ne PAS ajouter « go to sleep » / « stop listening » ; consigner le choix.
- Documenter que le mot d'éveil est ignoré/suspendu pendant ACTIVE et que F9 reste armé (`wakeword_keyboard.py:58-62`).

### Out of Scope

- Nouveau détecteur de mot de veille ; nouvelle machine d'états ; routage d'intentions libre.
- Modification de la logique PRESENTATION d'adresse (`PresentationWakeRouter`).
- Modification de `ATTRIBUTE_KEYS` ou de la timeline.

## Dependencies

- `04-presentation-wiring`
- `05-simple-wiring`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/runtime/voice_v2.py:383` (`wakeword.detections()`), `:403-410` (boucle de détection, trace `:409`, `activate()` `:410`), `:509`/`:549` (`rebind_board`), `:600` (`activate`), `:734` (`suspend_for_active_session`), `:1236` (`mute`), `:1299` (`wakeword.resume()`).
- `jarvis/runtime/realtime_audio.py:4954-4964` (« Jarvis mute » : `mute_words == ["jarvis", "mute"]`) et l'appel `on_mute` qui suit.
- `jarvis/domain/explicit_address.py:46-54` (`ExplicitAddressSource`).
- `jarvis/runtime/shortcuts.py:71-80` (`wake_toggle`, `manual_wake_key`), `jarvis/adapters/wakeword_keyboard.py:58-62`.
- `jarvis/domain/v2.py:81` (`VoiceLifecycleState`).
- Tests de référence : `tests/unit/test_v2_voice_toggle.py`, `tests/unit/test_v2_continuous_live.py`, `tests/unit/test_v2_wake_backends.py`.
- Nouveau : `tests/unit/test_wake_activation_parity.py`.

## Implementation Steps

1. Écrire les tests rouges de parité et de propagation de source.
2. Ajouter le paramètre de source à `activate()` ; une seule implémentation.
3. Enrichir `voice.wake` ; vérifier `state_before`/`state_after`.
4. Trancher et tester la veille vocale (D2) ; consigner la décision dans le LOG.

## Architecture Constraints

Un seul chemin `detections() -> activate()`. La source est de la métadonnée de trace, jamais une branche de comportement (sauf si le produit la différencie déjà). `VoiceLifecycleState` reste l'unique état (D5).

## Acceptance Criteria

- F9 simulé et mot d'éveil simulé en BACKGROUND aboutissent à `ACTIVE` par le même code (`activate`), mêmes effets de bord, étiquettes de trace distinctes `manual_key`/`wake_word` (ou labels existants `f9`/`jarvis` mappés sans second vocabulaire).
- Une détection pendant ACTIVE n'en démarre pas une seconde (le comportement actuel est préservé, test).
- « Jarvis mute » remet `BACKGROUND` et réarme le détecteur (`resume`, `:1299`) ; test inchangé ou étendu.
- Aucun changement de comportement SIMPLE/PRESENTATION hors étiquettes de trace.
- Aucune nouvelle phrase de veille libre n'est ajoutée (D2).

## Tests to write (red then green)

- `tests/unit/test_wake_activation_parity.py` : `test_f9_and_the_wake_word_reach_active_through_the_same_path`, `test_the_source_label_is_traced_and_does_not_change_behaviour`, `test_a_detection_while_active_does_not_activate_twice`, `test_rebind_board_still_activates_without_a_source`, `test_mute_returns_to_background_and_rearms_the_detector`, `test_no_free_form_sleep_phrase_is_recognised`, `test_state_before_and_after_are_traced`.
- Rejouer `test_v2_voice_toggle.py`, `test_v2_continuous_live.py`, `test_v2_wake_backends.py`.

## Documentation Updates

Mise à jour du contrat dans la Slice 08.

## QA level

glue (qa-verification + code-review ; pas de mutation).

## Risks

- Introduire une branche par source qui fait diverger F9 et voix : interdit, test de parité.
- Casser les appelants d'`activate()` : paramètre optionnel.
- Élargir « mute » au point de couper sur une mention : conserver la règle « deux mots exacts » (`:4953-4954`).

## Handoff Notes

Coding Slice : charger `/caveman` et `/coding-guideline` ; `/error-handling` si un chemin peut échouer. Un seul implémenteur dans le worktree `bww`. Tests en avant-plan, un fichier à la fois. Écrire d'abord les tests rouges, les committer (`test:`), puis l'implémentation (`feat:`/`fix:`).

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D2** — Veille vocale : extension minimale de « Jarvis mute » (`realtime_audio.py:4954-4964`), pas de nouveau détecteur ; « go to sleep » / « stop listening » hors périmètre.
- **D4** — Vocabulaire : réglages snake_case, bloc `wake_word` ; traces `voice.wake` enrichies (score, seuil, fournisseur) dans le journal `runtime/trace.jsonl`, pas dans la timeline ; sources existantes `wake_word` / `manual_key` (pas `keyboard_f9`).
- **D5** — Aucune seconde machine d'états : `VoiceLifecycleState` (`jarvis/domain/v2.py:81`) reste la source de vérité ; « PASSIVE » du handoff = `BACKGROUND`.

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

- Le renvoi à `ExplicitAddressSource` est un vocabulaire à réutiliser, pas à dupliquer.

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

### Limite de contrat (non corrigée) : un seul consommateur par détecteur

`last_detection` est un champ unique écrit dans `detections()` (détecteurs `SharedPcm` et à flux propre, relayé par `Composite`). Le contrat est un seul consommateur par détecteur : Voice OU le routeur de présentation, jamais deux. Un second itérateur concurrent sur le flux propre attendrait indéfiniment après `close()` (jeton de fin consommé une fois). Code inchangé.

### Limite héritée (non corrigée)

Un F9 pressé pendant `CONNECTING` est perdu en silence : `suspend_for_active_session` vide la file de `CompositeWakeWordBackend` (`_clear_pending`), et `activate()` ne fait rien hors BACKGROUND. Le comportement existait avant la Slice 06 (constat QA) ; il n'est ni corrigé ni aggravé ici. Piste : ne vider que les mots d'éveil, pas la touche manuelle, ou rejouer l'appui à l'entrée en ACTIVE.
