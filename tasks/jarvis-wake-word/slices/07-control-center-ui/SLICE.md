# Slice 07 — Interface du Control Center : activation, sensibilité, état de santé

## Goal

Exposer dans les réglages du Control Center l'activation du mot d'éveil, la sensibilité et l'état de santé du fournisseur, en s'appuyant sur la route de la Slice 03.

## Context

Audit §4 : les réglages vivent dans `control_center.py` / `control_center.html` ; la carte du mode d'interaction est un modèle (`control_center_interaction_mode.js`, routes `/api/interaction-mode` `control_center.py:1215-1216`). Voice ne relit les réglages qu'au démarrage : l'interface dit « redémarrage de Voice requis ».

## Canonical Concepts

Fenêtre de réglages, état de santé du détecteur (`stats()` `wakeword_shared_pcm.py:389`, `failure_code`), redémarrage de Voice.

## Scope

### In Scope

- Une carte/section « Mot d'éveil » dans les réglages : interrupteur `enabled` (défaut désactivé), curseur `sensibilité`, champ `cooldown` éventuel, pastille d'état (désactivé / en écoute / en panne avec le code dit / indisponible faute d'extra ou de modèle).
- Mention explicite : « Redémarrez Voice pour appliquer » ; mention de licence « modèle pour tests privés, non commercial » (D3).
- Lecture de l'état de santé depuis une route existante ou étendue du Control Center (pas de nouvelle source de vérité) ; aucune affirmation de santé non mesurée.
- Refus de la route affichés tels quels (codes dits), jamais avalés (`/error-handling`).

### Out of Scope

- Mise à chaud sans redémarrage.
- Calibration assistée ou enregistrement audio pour régler le seuil.
- Mode d'interaction ou autres réglages vocaux.

## Dependencies

- `03-wake-word-settings`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/runtime/control_center.html` et `jarvis/runtime/control_center_interaction_mode.js` : modèle de carte et d'appel de route.
- `jarvis/runtime/control_center.py:1215-1216` (routes du modèle), `:3406` (`_settings_payload`), `:3504` (`get_settings`), `:4615` (`save_settings`).
- `jarvis/adapters/wakeword_shared_pcm.py:389` (`stats`), `:255` (`_fail`, `failure_code`) : source de l'état de santé côté Voice (le transport vers le Control Center est à définir ici, minimal).
- Tests de référence : `tests/unit/test_voice_settings_ui.py`, `tests/unit/test_settings_ia_contract.py`, `tests/unit/test_scene_settings_ui.py`, `tests/unit/test_interaction_mode_hud_browser.py` (échec hérité `test_le_mouvement_reduit_arrete_vraiment_le_halo` : ne pas corriger).
- Nouveaux : `tests/unit/test_wake_word_settings_ui.py` ; éventuellement `jarvis/runtime/control_center_wake_word.js`.

## Implementation Steps

1. Écrire les tests rouges de la page (rendu, refus affichés, valeurs par défaut).
2. Ajouter la section et son script en réutilisant les conventions de la carte du mode d'interaction.
3. Brancher la pastille d'état sur la route de santé retenue.
4. Vérifier thème, accessibilité (libellés, focus) et phrase de licence.
5. Préparer la fiche de validation Human (`human-validation.json`).

## Architecture Constraints

La page ne stocke rien : elle lit/écrit par la route de la Slice 03. Pas de second magasin. L'état de santé vient du runtime, jamais déduit côté page.

## Acceptance Criteria

- Interrupteur désactivé par défaut ; l'enregistrer écrit `wake_word.enabled` par la route ; le rechargement le relit.
- Une valeur refusée (sensibilité hors bornes) affiche le code du refus et ne change rien.
- La pastille distingue désactivé, en écoute, panne (code dit) et indisponible.
- Le message « redémarrage de Voice requis » et la mention de licence sont visibles.
- Aucun échec ajouté à la liste héritée ; les tests `test_*_ui.py` voisins restent verts.

## Tests to write (red then green)

- `tests/unit/test_wake_word_settings_ui.py` : `test_the_section_is_rendered_and_disabled_by_default`, `test_saving_writes_the_setting_through_the_route`, `test_a_refusal_is_shown_with_its_code`, `test_health_states_are_distinguished`, `test_the_restart_notice_and_the_license_notice_are_visible`, `test_the_page_stores_nothing_locally`.
- Rejouer `tests/unit/test_settings_ia_contract.py` et `test_voice_settings_ui.py`.

## Documentation Updates

Capture/description de l'écran en Slice 08.

## QA level

ui (qa-verification + code-review ; contrôle visuel navigateur ; validation Human HV-WAKEWORD-UI-01 ; pas de mutation).

## Risks

- Afficher « en écoute » sans preuve : l'état vient du runtime.
- Fichier de réglages réécrit avec perte de clés : couvert en Slice 03, retesté ici de bout en bout.
- Tests de navigateur lents/instables (échecs hérités du même domaine) : ne pas les corriger.

## Handoff Notes

UI Slice : charger `/caveman`, `/coding-guideline` et `/impeccable` (cohérence visuelle avec les cartes existantes). Un seul implémenteur dans `bww`. Tests en avant-plan, un fichier à la fois. Tests rouges d'abord, puis implémentation.

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D1** — `wake_word.enabled` : défaut `false`. Aucun micro ouvert au repos tant que le Human n'a pas activé le mot d'éveil.
- **D3** — Licence : modèle `hey_jarvis` réservé aux tests privés (CC BY-NC-SA 4.0 d'après le handoff, à confirmer en Slice 01) ; artefact hors dépôt sous `runtime/`, SHA-256 épinglé dans le code, installation à la demande ; notice dans `third_party/README.md`.
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

- La page ne contourne pas la route de la Slice 03 ; aucune écriture directe du fichier de réglages.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.
