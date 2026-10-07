# Slice 08 — Documentation canonique, copies sw2/sw3, fiche d'acceptation matérielle

## Goal

Mettre à jour la documentation canonique du mot d'éveil (contrat, exploitation, configuration, licence), les copies suivies `sw2`/`sw3` si elles contiennent des passages concernés, et la fiche d'acceptation matérielle.

## Context

Audit §8 : la documentation du mot d'éveil est répartie (`docs/presentation-audio-capture.md`, `docs/interaction-mode.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/ACCEPTANCE_STATUS.md`, `docs/HARDWARE_ACCEPTANCE.md`, `docs/presentation-addressed-turn.md`, `docs/SECURITY.md`, `README.md`). `sw2/` et `sw3/` sont suivis par git (`OPERATIONS.md`, `README.md`, `REPORT.md` chacun) : vérifier s'ils contiennent des passages sur le mot d'éveil avant d'y toucher.

## Canonical Concepts

Documentation canonique (maturité Level 3), notice de licence, fiche de validation matérielle.

## Scope

### In Scope

- `docs/presentation-audio-capture.md` : propriétaires du micro (SIMPLE avec détecteur openWakeWord, PRESENTATION inchangé à 1), tables `:62`, `:80-81`, `:94`, rééchantillonnage `:265`, entrée PRESENTATION `:302`.
- `docs/OPERATIONS.md` : section de configuration du bloc `wake_word` (défaut désactivé, bornes, redémarrage de Voice), installation de l'extra `wakeword` et du modèle, diagnostic des pannes (codes `wake_*`), entrée PRESENTATION `:3895-3925` (tableau `:3906` : le mot d'éveil existe aussi sans clé Porcupine si openWakeWord est activé), contrôle écho `:4115`.
- `docs/ARCHITECTURE.md` (`:326-331`, `:377`, `:426-437`, `:1080`), `docs/interaction-mode.md` (`:220`, `:479-494`), `docs/presentation-addressed-turn.md:560`, `docs/SECURITY.md` (aucun audio persisté, micro permanent seulement si activé), `README.md:133`.
- `docs/ACCEPTANCE_STATUS.md` (`:271`, `:285`, `HV-PRES-AUDIO-01` `:335`) et `docs/HARDWARE_ACCEPTANCE.md` : ajouter HV-WAKEWORD-UI-01 et HV-WAKEWORD-MIC-01 avec leurs procédures et leur statut « non exécuté ».
- Notice de licence : vérifier la cohérence avec `third_party/README.md` (Slice 01).
- `sw2/` et `sw3/` : mettre à jour uniquement les passages réellement concernés ; sinon consigner « sans objet ».

### Out of Scope

- Tout changement de code ou de test (sauf test de cohérence documentaire s'il en existe un).
- Exécution de la validation matérielle (Slice 09).
- Documentation d'un comportement non implémenté (« go to sleep », hot-plug, mise à chaud).

## Dependencies

- `04-presentation-wiring`
- `05-simple-wiring`
- `06-activation-parity`
- `07-control-center-ui`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `docs/presentation-audio-capture.md:17,20,62,80-81,94,164,265,302`.
- `docs/OPERATIONS.md:117-136` (F9), `:1187`, `:1196` (variables), `:3895-3925` (entrée PRESENTATION), `:3906` (tableau « Sans quoi »), `:4115` (poste non exécuté).
- `docs/ARCHITECTURE.md:326-331,377,426-437,1080`, `docs/interaction-mode.md:220,479-494`, `docs/presentation-addressed-turn.md:560`.
- `docs/ACCEPTANCE_STATUS.md:271,285,335`, `docs/HARDWARE_ACCEPTANCE.md` (sections 0-11 : nouvelle section dédiée), `docs/SECURITY.md`, `README.md:133`.
- `third_party/README.md:13` (section modèle), `sw2/OPERATIONS.md`, `sw2/README.md`, `sw3/OPERATIONS.md`, `sw3/README.md` (vérification).

## Implementation Steps

1. Relire le code livré (Slices 01-07), relever les écarts avec la doc actuelle.
2. Mettre à jour la doc canonique en français/anglais selon la langue de chaque fichier.
3. Ajouter les deux fiches HV et le statut « non exécuté ».
4. Traiter `sw2`/`sw3` ou consigner « sans objet ».
5. Passer un contrôle de liens/références (les lignes citées existent).

## Architecture Constraints

Documenter ce qui existe, pas ce qui est prévu. Une seule doc canonique par sujet ; les autres renvoient. Aucun chemin personnel, aucun nom d'utilisateur.

## Acceptance Criteria

- Chaque fichier cité décrit le comportement livré ; aucune mention de `keyboard_f9`, de `wakeWord.*` camelCase ni de phrases de veille libres.
- La licence du modèle est identique dans `third_party/README.md` et les docs d'exploitation, avec la mention « tests privés, non commercial ».
- `docs/HARDWARE_ACCEPTANCE.md` / `docs/ACCEPTANCE_STATUS.md` listent HV-WAKEWORD-UI-01 et HV-WAKEWORD-MIC-01 avec statut « non exécuté ».
- Les valeurs par défaut documentées (désactivé, sensibilité, cooldown) correspondent au code (vérifié par lecture).
- `sw2`/`sw3` traités ou « sans objet » consigné.
- Aucun test ne régresse.

## Tests to write (red then green)

- Aucun test produit. Contrôle : balayage de vie privée existant étendu aux nouveaux fichiers de doc si le mécanisme existe ; sinon `grep` ciblé consigné.
- Si un test de cohérence documentaire existe pour `docs/`, le rejouer ; sinon aucun.

## Documentation Updates

Cette Slice est la documentation.

## QA level

glue (qa-verification + code-review documentaire ; pas de mutation).

## Risks

- Documenter un comportement non livré : relire le code.
- Divergence entre `docs/` et `sw2`/`sw3` : vérifier, ne pas copier aveuglément.
- Numéros de ligne périmés dans les docs : vérifier avant d'écrire.

## Handoff Notes

Slice documentaire : charger `/caveman`. Pas de code produit ni de test (sauf contrôle documentaire existant). Un seul implémenteur dans `bww`.

## Slice 00 contract (binding)

Décisions de `00-project-manager/READINESS.md` applicables à cette Slice (à confirmer par le Human ; en cas de désaccord, stop et rapport au PM) :

- **D1** — `wake_word.enabled` : défaut `false`. Aucun micro ouvert au repos tant que le Human n'a pas activé le mot d'éveil.
- **D2** — Veille vocale : extension minimale de « Jarvis mute » (`realtime_audio.py:4954-4964`), pas de nouveau détecteur ; « go to sleep » / « stop listening » hors périmètre.
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

Scope out (précisions contraignantes) :

- Aucune modification de `jarvis/` ni de `tests/`.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.
