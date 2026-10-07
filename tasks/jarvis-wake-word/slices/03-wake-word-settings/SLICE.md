# Slice 03 — Bloc de réglages wake_word, module, route, refus stricts

## Goal

Ajouter un bloc de réglages versionné `wake_word` (désactivé par défaut) dans `runtime/control-center-settings.json`, avec un module de lecture/validation/écriture, une route dédiée et des refus stricts.

## Context

Audit §4 : le fichier de réglages est lu tolérament par `_settings()` (`control_center.py:2739`) et écrit atomiquement par `_write_settings` (`:2770`) ; Voice ne le relit qu'au démarrage (`app.py:909`), donc tout changement exige un redémarrage de Voice. Le modèle à copier est `jarvis/runtime/interaction_mode_settings.py` (`SETTING_KEY` `:47`, `SCHEMA_VERSION` `:54`, `inspect` `:84`, `load` `:114`, `behaving` `:132`, `apply` `:144`, `describe` `:198`) avec ses routes `/api/interaction-mode` (`control_center.py:1215-1216`, `get_interaction_mode` `:3512`, `save_interaction_mode` `:3545`).

## Canonical Concepts

Bloc de réglages versionné, lecture tolérante / écriture stricte, défaut sûr (D1), redémarrage de Voice requis.

## Scope

### In Scope

- Nouveau `jarvis/runtime/wake_word_settings.py` : `SETTING_KEY = "wake_word"`, `SCHEMA_VERSION = 1`, champs `enabled` (défaut `false`), `provider` (`"openwakeword"` seul accepté en v1), `keyword` (`"hey_jarvis"`), `sensitivity` (0..1), `cooldown_ms` (borné), plus `inspect`, `load`, `apply`, `describe`.
- Lecture tolérante : bloc absent, mal formé, version inconnue ou valeur hors bornes → défauts sûrs (désactivé) et diagnostic dit ; jamais d'exception vers Voice.
- Écriture stricte : `apply` refuse (code dit) tout champ inconnu, tout type faux, toute valeur hors bornes, tout fournisseur inconnu ; le fichier n'est pas modifié sur refus.
- Routes `GET`/`POST /api/wake-word` (ou nom aligné sur `/api/interaction-mode`) dans `control_center.py`, qui réutilisent `_write_settings` (aucun second magasin).
- Variable d'environnement `JARVIS_WAKE_WORD_ENABLED` : NON ajoutée en v1 sauf si le PM le demande ; le fichier est la seule source.

### Out of Scope

- Interface graphique (Slice 07).
- Câblage dans Voice (04, 05) : cette Slice ne change aucun comportement runtime.
- Mise à chaud sans redémarrage ; clés `modelPath`, `inputDeviceId`, `debugMetrics` du handoff (optionnelles, non retenues).

## Dependencies

- `00-project-manager`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/runtime/interaction_mode_settings.py:47,54,84,114,132,144,198` : modèle de module.
- `jarvis/runtime/control_center.py:1023` (`settings_path`), `:1215-1216` (routes du modèle), `:2739` (`_settings`), `:2770` (`_write_settings`), `:3504` (`get_settings`), `:3512`/`:3545` (handlers du modèle), `:4615` (`save_settings`).
- `jarvis/app.py:909` (`overrides = _control_settings(...)`), `:511` (`_control_settings`) : consommateur côté Voice, non modifié ici.
- `jarvis/runtime/scene_settings.py` : second exemple de bloc.
- Nouveaux : `jarvis/runtime/wake_word_settings.py`, `tests/unit/test_wake_word_settings.py`, `tests/unit/test_wake_word_settings_api.py`.

## Implementation Steps

1. Écrire les tests rouges du module (défauts, bornes, refus, tolérance) puis de la route.
2. Implémenter `wake_word_settings.py` sur le modèle d'`interaction_mode_settings.py`.
3. Ajouter les routes et les handlers ; `apply` écrit par `_write_settings`.
4. Vérifier qu'un fichier de réglages existant sans bloc `wake_word` se lit et se réécrit sans perte des autres clés.

## Architecture Constraints

Convention snake_case ; un seul fichier de réglages ; `SCHEMA_VERSION` du bloc, pas de la base ; aucune migration SQLite (D6). `enabled=false` par défaut (D1) : sans réglage explicite, le comportement actuel est strictement inchangé.

## Acceptance Criteria

- Sans bloc, `load()` renvoie `enabled=false` et le reste des défauts ; `describe()` le dit.
- Un bloc invalide en lecture donne les défauts sûrs et un diagnostic, sans exception.
- `apply` refuse champ inconnu, type faux, `sensitivity` hors 0..1, `cooldown_ms` hors bornes, `provider` inconnu, avec un code distinct par cause ; le fichier reste identique octet pour octet.
- Un `POST` valide écrit atomiquement, préserve les autres clés (dont les secrets) et le `GET` suivant le relit.
- La réponse indique « redémarrage de Voice requis ».
- Aucun changement de comportement de Voice avec ou sans le bloc (test).

## Tests to write (red then green)

- `tests/unit/test_wake_word_settings.py` : `test_absent_block_means_disabled_with_safe_defaults`, `test_malformed_block_falls_back_without_raising`, `test_unknown_schema_version_falls_back_and_says_so`, `test_apply_refuses_unknown_field`, `test_apply_refuses_wrong_types`, `test_apply_refuses_out_of_range_sensitivity`, `test_apply_refuses_out_of_range_cooldown`, `test_apply_refuses_unknown_provider`, `test_a_refusal_leaves_the_file_untouched`, `test_apply_preserves_other_keys`.
- `tests/unit/test_wake_word_settings_api.py` : `test_get_returns_the_described_block`, `test_post_valid_block_is_written_atomically`, `test_post_invalid_block_is_refused_with_a_code`, `test_the_response_says_voice_must_restart`.
- `tests/unit/test_wake_word_settings_api.py` : `test_no_sqlite_file_is_created_or_modified`.

## Documentation Updates

Docstring de module ; la référence de configuration est écrite en Slice 08.

## QA level

glue (qa-verification + code-review ; pas de mutation).

## Risks

- Écraser des secrets ou des clés voisines en réécrivant le fichier : tests de préservation.
- Un défaut actif romprait D14 (micro permanent) : test du défaut.
- Nom de route divergent de `/api/interaction-mode` : s'aligner, ne pas inventer.

## Handoff Notes

Coding Slice : charger `/caveman` et `/coding-guideline` ; `/error-handling` si un chemin peut échouer. Un seul implémenteur dans le worktree `bww`. Tests en avant-plan, un fichier à la fois. Écrire d'abord les tests rouges, les committer (`test:`), puis l'implémentation (`feat:`/`fix:`).

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D1** — `wake_word.enabled` : défaut `false`. Aucun micro ouvert au repos tant que le Human n'a pas activé le mot d'éveil.
- **D4** — Vocabulaire : réglages snake_case, bloc `wake_word` ; traces `voice.wake` enrichies (score, seuil, fournisseur) dans le journal `runtime/trace.jsonl`, pas dans la timeline ; sources existantes `wake_word` / `manual_key` (pas `keyboard_f9`).
- **D6** — Aucune migration SQLite (réglages JSON). Si une Slice en découvre le besoin : stop, suivre `CLAUDE.md`, prévenir le Human.

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

- Aucune lecture du bloc par Voice dans cette Slice (câblage en 04/05).

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.

## Rework QA (2026-10-07, `fix/ww-s3-rework`)

- Entiers JSON démesurés : `*_out_of_range` en lecture et en écriture (jamais d'exception). `keyword` Porcupine validé par `fullmatch`.
- Code stable ajouté : `wake_word_foreign_version` (POST refusé quand le bloc enregistré porte une autre version de schéma). Avertissement `wake_word.settings.unreadable` une fois par processus.
- `state` et `restart_message` disent que le réglage n'est pas encore consommé par Voice (« Réglage enregistré ; il ne s'applique qu'au prochain démarrage de Voice et seulement là où le mot d'éveil configurable est câblé »). Cette mention sera retirée ou ajustée aux Slices 05-07, quand le câblage existera (formule retirée en Slice 07).
