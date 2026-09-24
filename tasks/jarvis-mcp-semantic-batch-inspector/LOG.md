# Execution log


Reserved for implementation agents. Record durable verified execution notes only.
## 2026-09-24 — Slice 00 (agent 0)

- Branch `task/jarvis-mcp-semantic-batch-inspector` from `origin/main` @ `ddcdb71` (= handoff snapshot). Handoff mirrored from Drive (39 files) in `ff525d0`.
- Blind audit done without reading `tasks/`; handoff conclusions confirmed, six precisions added (READINESS §3).
- Baseline at `ddcdb71`: unit 6991 passed / 25 failed / 6 skipped (248 files); integration 566 / 6 / 22 (67 files). 23 of 31 failures sit in the scene/MCP domain this task touches — stale tests after main widened brain scene authority.
- State: HUMAN_DECISION_REQUIRED on H1 (Task Type waiver) and H2 (stale-test realignment ownership). Human answered "oui et oui" and delegated all further decisions to agent 0 → READY. Out-of-domain red tests filed in `Issues/01-*`.

## 2026-09-25 — Slice 01 (contrats canoniques, docs seulement)

- Fichiers : `docs/scene-selection-batch.md` (nouveau), `docs/mcp/tool-contract.md` (nouveau), `docs/scene-model.md` (renvoi + dérive `:715` marquée « jusqu'à Slice 05 » ; ligne `scene_update_many` sur l'épingle corrigée : le code n'écarte pas les objets épinglés), `docs/mcp/plan-outils-interface.md` (encadré « contrat livré »). Aucun code, aucun test.
- Décisions clés :
  - `SceneSelection` : mode explicite (`ids`, 1–512) XOR mode filtres ; ET entre champs, OU dans `kinds` / `exec_states` ; `connected` renommé `constellation` sans alias ; ajouts `kinds`, `exec_states`, `group`, `exclude` (≤ 32, filtres seulement).
  - Borne unique 512 (= `MAX_SCENE_OBJECTS` = `MAX_ARCHIVE_MANY_IDS`), remplace 32/128 ; patch ≤ `MAX_PATCH_OPS` par construction ; jamais de découpage d'un lot atomique (64 Kio de corps → filtre).
  - Constellation : non orientée + arêtes virtuelles `signal_owners` ; archivés exclus ; **masqués inclus** (le filtre aux nœuds rendus de la page est une projection UI) ; profondeur 1–6 ou composante entière ; ordre racine puis BFS (= algorithme JS) ; fixtures partagées Python/JS.
  - Id explicite inconnu / archivé / inéligible → refus de tout le lot (sauf archivé dans `archive_selection` = inchangé) ; membre de filtre inéligible (`unplaced`) → écarté et rapporté. `pinned_by_user` n'est jamais un refus (l'épingle ne résiste qu'au résolveur, `scene.py:1430`).
  - Ops domaine : `patch_selection`, `translate_selection` (delta commun, borne zone sûre élargie à la bbox — jamais pire —, clamp par axe, quantum 0,1 vers zéro, `pin: true` pour le glisser de la page), `pin_selection`, `unpin_selection`, `archive_selection` ; `archive_many` inchangé. Rapport `batch` sur la réponse de commande.
  - MCP : surface scène 13 → 13 (`scene_set_visibility` retiré, `scene_move` ajouté) ; `inspect/query/get` restent JSON texte compact, schéma du texte côté catalogue (non annoncé), colonnes définies une fois en code ; mutations typées ; annotations MCP dérivées d'un module de métadonnées unique ; `jarvis-drive` en catégorie « Externe », disponibilité jamais prouvée ; `barehands_tutorial` déprécié (condition existante du doc legacy).
- Points ouverts : transmission d'`outputSchema`/annotations au modèle par le CLI (mesure Slice 08, repli Slice 04) ; import de `drive_mcp` sans dépendances Google (Slice 04) ; ajout de `barehands_tools`/`console_tools` à l'instantané agent (Slice 06) ; relais `patch_omitted` du proxy étendu aux commandes de sélection (Slice 03) ; clé d'idempotence `drive_update` (candidat `Issues/`).

## 2026-09-25 — Slice 02 (SceneSelection et constellation canonique)

- Réalignement baseline (H2), commit séparé : `test_menu_entries_depend_on_kind_origin_and_state` attend l'entrée `select-constellation` (ajoutée par `00f1eb5`, visible seulement si la constellation a > 1 objet).
- Nouveau module `jarvis/domain/scene_selection.py` : `SceneSelection` stricte (modes exclusifs, pluriels, borne unique 512, `exclude` ≤ 32), `constellation_of` (non orientée + arêtes virtuelles `signal_owners`, masqués inclus, profondeur 1–6 ou composante, racine puis BFS), `resolve_selection` indépendante de l'opération (`refused` en ordre canonique références puis ids, `archived_ids` à part, `skipped` si `require_placed`, `hidden_count`).
- Décisions de l'agent 0 appliquées (post-QA Slice 01) : référence `near` non placée → `unplaced` ; `group` qui n'est pas un groupe → nouveau `SceneRefusal.INVALID_SELECTION` ; tous les fautifs listés, motif = premier ; ids explicites archivés rangés à part (l'op tranche via `refusals(archived_ok=)`) ; `hidden_count`.
- `display_mcp.py` importe `text_matches` / `work_matches` / `box_distance` du domaine (définition unique) ; comportement inchangé, `_connected_ids` intact (Slice 05).
- Parité : `tests/fixtures/scene_constellation_cases.json` joué contre Python et contre `constellationOf` (node) — premier test de `constellationOf`, conforme sans modification ; commentaires ajoutés (copie locale côté interact, projection UI côté page).
- Tests : `test_scene_selection.py` 82 passés, `test_scene_constellation.py` 20 passés. Fichiers de garde : interaction+contrats+liens+vue+rendu 475/475 ; display_mcp+query_tools 96 passés / 2 échecs hérités (identiques avant/après).
- 2026-09-25 — S1 reprise QA (docs) : disponibilité en faits séparés (`condition`, `next_launch`, `advertised`) + état affiché par précédence ; glisser multi-objet = delta pointeur sans « unturn » d'orbite par membre (orbitants se réinstallent, mono-objet inchangé) ; `refused[]` complet en ordre canonique (références puis membres), `reason` = première entrée (= Slice 02) ; `structured_output=False` pour inspect/query/get et mesure CLI dès Slice 04 ; inventaire §7 en fichiers ; `idempotent` par outil ; `hidden_count`, bbox avec masqués, groupe plus large que la zone sûre immobile sur l'axe, membres non placés qui reviennent ; renvoi « jusqu'à Slice 05 » dans ARCHITECTURE.md.

## 2026-09-25 — Slice 03 (lots de scène atomiques)

- Réalignement baseline (H2), commit séparé `f67cf62` : `test_scene_artifacts.py` (6), `test_scene_service.py` (2), `test_scene_transport_client.py` (4), `integration/test_scene_transport.py` (2) alignés sur main `f05ed24` (cerveau : archive, épingle, déplace l'épinglé, `archive_many` ; consigne d'affichage et messages d'artefact changés ; la conversation porte la consigne des réglages). Le générateur de parité garde des refus d'autorité réels (runtime hors matrice) ; le refus HTTP du cerveau passe par `execution_node`.
- Domaine `2760604` : `SceneOp.*_SELECTION` (5), `jarvis/domain/scene_batch.py` (`apply_selection_command`, `SelectionChanges`, `SceneDelta`, `SceneBatchReport`, `BatchDelta`, `group_delta`), `SceneUpdate.batch`, `SELECTION_OPS`, import de `scene_batch` à l'appel (cycle avec `scene_selection`). Réutilise `_plan_object_write` / `_with_cascade` / `_archive_ops`. Docstring `scene.py` réalignée (autorité cerveau, épingle). `parse_enum` nomme `SceneOp` (18 valeurs) au lieu de les lister : message < 300 caractères.
- Fil / Core / relais : `scene_wire.command_body` ajoute `batch` ; `decode_command_response` le relaie ; `CoreSceneView.command` omet le patch des commandes de sélection (`patch_omitted`) et journalise les comptes (jamais les ids). Corps > 64 Kio → 413 avant lecture (512 ids longs, testé). `SceneService` inchangé (le réducteur fait tout sous son verrou).
- Page `675254f` : glisser de groupe = une `translate_selection` (`pin: true`), écart pointeur borné par `groupDelta` (parité `group_delta` sur 300 cas), pas de dé-tour d'orbite par membre, non placés non envoyés (`scene.user_drag_unplaced_skipped`), couches optimistes posées avant le lâcher. Glisser d'un objet inchangé.
- Tests : `test_scene_batch.py` 40, `test_scene_group_drag_js.py` 5, parité JS étendue (commande de sélection toutes les 8 étapes, rng séparé), 3 tests d'intégration. Suites requises vertes (voir rapport de slice).
