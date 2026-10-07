# Slice 09 — Outillage de mesure et validation micro réel par le Human

## Goal

Fournir l'outillage automatisable de mesure (latence détection→activation, comptage de faux positifs, journal de session de validation) puis faire exécuter par le Human la validation sur micro réel, dans les deux modes, avec écho, F9 et panne du fournisseur.

## Context

Audit §10 : aucune validation micro réel n'a jamais été faite pour le mot d'éveil existant ; `docs/OPERATIONS.md:4115` note le contrôle poste « non exécuté ». En PRESENTATION le détecteur lit le PCM brut du hub : l'AEC ne s'applique qu'au sink en ligne, et aucun garde de queue n'existe entre fin de lecture et `resume()`. L'écho TTS est le risque principal. Les traces `voice.wake` du journal `runtime/trace.jsonl` sont la source des preuves.

## Canonical Concepts

Journal `runtime/trace.jsonl`, `scripts/summarize_voice_trace.py`, fiche HV, critère mesurable de faux positif/négatif.

## Scope

### In Scope

- Partie logicielle (automatisable, testée) : `scripts/measure_wake_word_validation.py` (ou extension de `scripts/summarize_voice_trace.py`) qui lit un `trace.jsonl` et produit : nombre de détections par source (`wake_word`/`manual_key`), score/seuil, latence détection→activation (écart `voice.wake` → `voice.active`), détections hors fenêtre de test (faux positifs candidats), cooldowns ignorés ; sortie sans texte de parole, sans chemin personnel.
- Gabarit de feuille de résultat dans `docs/HARDWARE_ACCEPTANCE.md` (si non fait en 08) ou dans le dossier de la Slice ; preuves committées anonymisées.
- Lancement de la validation par le Human, sur son poste, avec le JARVIS vivant : le PM/agent ne touche pas au checkout vivant.
- Décision après mesure : réglage de sensibilité par défaut final ; si un risque d'écho est avéré, ouverture d'une Issue (`Issues/`) avec proposition de garde de queue, sans l'implémenter ici.

### Out of Scope

- Correction d'un défaut découvert en validation (Issue, puis Slice de rework).
- Entraînement d'un modèle personnalisé ; vérification du locuteur.
- Enregistrement continu du micro pour analyse (interdit : aucun PCM persisté).

## Dependencies

- `01-feasibility-dependencies`
- `02-openwakeword-engine`
- `03-wake-word-settings`
- `04-presentation-wiring`
- `05-simple-wiring`
- `06-activation-parity`
- `07-control-center-ui`
- `08-docs-acceptance`

## Files and symbols (references revérifiées au 2026-10-07 sur `efe6e75`)

- `jarvis/runtime/voice_v2.py:409` (`voice.wake`), `:410` (`activate`), `:734`, `:1299` ; événements `voice.active` / `voice.background` du journal ; `jarvis/runtime/journal.py:68` (`RuntimeJournal.emit`).
- `scripts/summarize_voice_trace.py`, `scripts/measure_speech_metrics.py` : outillage voisin à réutiliser.
- `jarvis/adapters/wakeword_shared_pcm.py:389` (`stats`), `:255` (`_fail`) : compteurs et codes de panne lus par la mesure.
- `docs/HARDWARE_ACCEPTANCE.md`, `docs/ACCEPTANCE_STATUS.md:335` (`HV-PRES-AUDIO-01`), `docs/OPERATIONS.md:4115` : fiches et statut.
- Nouveaux : `scripts/measure_wake_word_validation.py`, `tests/unit/test_wake_word_validation_measure.py`, `tasks/jarvis-wake-word/Issues/`, `human-validation.json`.

## Implementation Steps

1. Écrire les tests rouges de l'outil de mesure sur des traces synthétiques.
2. Implémenter l'outil (lecture seule du journal ; aucun accès micro).
3. Rejouer l'outil sur une trace synthétique de bout en bout ; vérifier l'absence de texte/chemin personnel.
4. Remettre au Human la procédure (HV-WAKEWORD-MIC-01) et l'outil ; il exécute les sous-contrôles sur son poste.
5. Consigner les résultats mesurés (anonymisés) ; ouvrir une Issue pour tout défaut non bloquant, escalader tout défaut bloquant.

## Architecture Constraints

L'outil est en lecture seule sur le journal : il n'ouvre pas le micro, ne persiste aucun audio. La validation Human n'accepte jamais une impression à la place d'un échec machine.

## Acceptance Criteria

- L'outil calcule correctement latence, comptes par source et faux positifs candidats sur des traces synthétiques (tests).
- Aucune sortie de l'outil ne contient de texte de parole ni de chemin personnel.
- Le Human a exécuté tous les sous-contrôles de HV-WAKEWORD-MIC-01 ; chacun a un résultat mesuré séparé de l'impression subjective.
- La latence détection→activation est mesurée sur le poste et consignée (valeur et méthode).
- Aucun micro n'est ouvert quand `enabled=false` (comptage du registre de propriétaires, vérifié sur le poste).
- Les défauts non bloquants sont des Issues ; aucun défaut bloquant ouvert.

## Tests to write (red then green)

- `tests/unit/test_wake_word_validation_measure.py` : `test_latency_is_the_gap_between_wake_and_active`, `test_counts_are_split_by_source`, `test_detections_outside_the_test_window_are_false_positive_candidates`, `test_cooldown_ignored_events_are_counted`, `test_the_output_contains_no_speech_text_and_no_personal_path`, `test_an_empty_or_truncated_trace_is_reported_not_crashed`, `test_the_tool_opens_no_audio_device`.

## Documentation Updates

Résultats consignés dans `LOG.md` ; fiche HV mise à jour dans `docs/HARDWARE_ACCEPTANCE.md` / `docs/ACCEPTANCE_STATUS.md` avec le statut réel après exécution.

## QA level

critical (qa-verification + code-review + runtime-validation ; agent-trace-analysis sur la trace réelle du poste ; mutation ≤10 mutants foreground sur le calcul de latence et la classification des faux positifs, avec un témoin cosmétique ; puis validation Human HV-WAKEWORD-MIC-01).

## Risks

- Écho de la voix de Jarvis déclenchant le mot d'éveil (PRESENTATION lit le PCM brut) : sous-contrôle dédié, Issue si avéré.
- Faux positifs en salle/TV et faux négatifs à distance : dépendent du seuil, mesurer, ne pas régler à l'oreille.
- Validation sur le JARVIS vivant : ne rien faire dans le checkout vivant côté agent.
- Preuves committées contenant des chemins ou noms d'utilisateur : balayage avant commit.

## Handoff Notes

Dernière Slice. Partie logicielle : charger `/caveman` et `/coding-guideline` ; puis passage au Human. Un seul implémenteur dans `bww`. Aucun `run_in_background`.

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

Scope in (précisions contraignantes) :

- Les sous-contrôles de `human-validation.json` sont tous obligatoires ; l'absence d'un résultat mesuré bloque l'acceptation.

Échecs hérités à NE PAS corriger (baseline `3bc7acf`, tests/unit : 6 échecs ; tests/integration : 0) :

1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent. Tout échec hors de cette liste est imputable à cette Slice.

Références fichier:ligne : fraîcheur à revérifier avant dispatch (plusieurs sessions fusionnent dans `main`) ; si une ligne a bougé, corriger la référence, pas le périmètre.
