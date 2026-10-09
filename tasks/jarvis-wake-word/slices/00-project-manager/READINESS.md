# Slice 00 — READINESS — jarvis-wake-word

Date : 2026-10-07. Agent 0 (orchestrateur). Branche `task/jarvis-wake-word`, base `3bc7acf` (main), worktree `C:/Projects/jarvis/bww`.

## État déclaré du handoff

- Origine : Drive `to-do`, dossier `jarvis-wake-word` (id `1rP_UusTc9-ahyeS4xMHib8hC4bYv1r3f`), miroir octet pour octet au commit S0 `efe6e75` (SHA-256 vérifiés).
- Contenu reçu : `HANDOFF.md`, `README.md`, `grill-session.md`, `LOG.md`. **Les dossiers `slices/`, `docs/`, `Issues/` (et leurs doublons Drive) étaient vides** : aucun `slices/TODO.md`, aucun `SLICE.md`, aucune `human-validation.json`, alors que le README en cite un. Le découpage est donc écrit par la Slice 00 (cette Slice) à partir de l'ordre d'implémentation du HANDOFF et de l'audit. Le README dit lui-même que les noms de fichiers et Task Types sont à résoudre par la Slice 00.
- Fallback de cycle de vie : `docs/workflows/AGENT_TASK_LIFECYCLE.md` n'existe pas dans ce dépôt ; files Drive `to-do` `1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm`, `current` `1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`, `done` `16yBLZRVOEbfDAN_CRh5722bkN46IUmo7`, branche de base `main` (pas de `dev`). Le connecteur Drive ne déplace pas de dossier : le Human déplace `to-do` → `current`.
- Task Types : vocabulaire inexistant, gate waivé (A11).

## Audit à l'aveugle

Voir `docs/01-blind-audit.md`. Conclusion : le contrat de détecteur et le chemin d'activation unique existent déjà ; le travail est une extension (`OpenWakeWordEngine` derrière `WakeWordEngine`), pas une nouvelle couche.

## Baseline de tests (point de branche `3bc7acf`)

Mesurée dans un worktree détaché `bsw`, en avant-plan, HEAD vérifié avant/après chaque tranche.

| Suite | Fichiers | Tests | Réussis | Échecs | Ignorés |
|---|---|---|---|---|---|
| tests/unit | 421 | 12 539 | 12 516 | 6 | 17 |
| tests/integration | 73 | 669 | 646 | 0 | 23 |

**Échecs hérités (« not yours, do not fix »)** :
1. `tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`
2. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
3. `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
4. `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
5. `tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo`
6. `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`

`tests/integration/test_scene_transport.py::test_stopping_the_server_releases_a_pending_long_poll` est intermittent (0 échec sur ce passage). Tout échec hors de cette liste est imputable à la Slice courante. Règle : un balayage large (unit + integration) après chaque lot de reworks intégrés, pas seulement ici.

## Décisions de l'agent 0 (recommandations appliquées, à confirmer par le Human)

- **D1** `wake_word.enabled` : **défaut `false`**. Un défaut actif ouvrirait un micro permanent chez tous les utilisateurs et romprait le comportement actuel (sans clé Porcupine, aucun flux au repos). Le Human l'active dans les réglages.
- **D2** Mise en veille vocale : extension **minimale** de l'existant (« Jarvis mute »), pas de nouveau détecteur ; hors périmètre : phrases libres « go to sleep ».
- **D3** Licence : le modèle `hey_jarvis` (CC BY-NC-SA 4.0 d'après le handoff, à confirmer en Slice 01) est réservé aux tests privés ; notice dans `third_party/README.md` sur le modèle de « Speaker verification » ; artefact hors dépôt (`runtime/`), SHA-256 épinglé, installation à la demande.
- **D4** Vocabulaire : réglages snake_case, bloc `wake_word` ; traces `voice.wake` enrichies (score, seuil, fournisseur) dans le **journal**, pas dans la timeline (`ATTRIBUTE_KEYS` reste fermé). Sources existantes `wake_word` / `manual_key` (pas `keyboard_f9`).
- **D5** Pas de seconde machine d'états : `VoiceLifecycleState` reste la source de vérité ; `PASSIVE` du handoff = `BACKGROUND`.
- **D6** Aucune migration SQLite attendue (réglages JSON). Si une Slice en découvre le besoin : stop, suivre CLAUDE.md, prévenir le Human.
- **D7** En SIMPLE l'inférence ne tourne jamais dans le rappel PortAudio (file) ; en PRESENTATION `engine.process` s'exécute sur la boucle asyncio : coût à mesurer en Slice 01 avant de décider d'un exécuteur.

## Réparations de planification

1. Découpage créé de toutes pièces (aucun SLICE.md reçu), voir `slices/TODO.md`.
2. Hypothèses du handoff démenties ou déjà réalisées : `docs/01-blind-audit.md` §9, intégrées aux contrats des Slices.
3. Le handoff exige des tests « PASSIVE/ACTIVE » : ils s'écrivent sur `VoiceLifecycleState` (`BACKGROUND`/`ACTIVE`) et les harnais existants.

## Vigilances d'exécution (mémoire du dépôt)

- Un implémenteur par worktree ; QA dans des worktrees séparés (`bqa`, `bsw` pour balayages). Reworks sur `fix/ww-sN-rework` (préfixe de tâche obligatoire), cherry-pickés quand l'implémenteur est libre.
- Tests en avant-plan, un fichier à la fois (RAM libre ~1-2 Go) ; pas de `run_in_background` ni de Monitor pour QA/implémenteurs.
- Le checkout `C:/Projects/jarvis/jarvis` est le JARVIS vivant du Human (et une autre session y fusionne) : ne rien y faire en tâche.
- Preuves committées : aucun chemin personnel, aucun nom d'utilisateur Windows (un test de balayage de vie privée existe pour les tâches précédentes : l'étendre si utile).
- La dernière Slice inclut la validation micro réel, faite par le Human.
- Avant tout close-out : `git fetch` puis `git rev-list --left-right --count origin/main...HEAD` ; fusionner `origin/main` DANS la branche de tâche.
