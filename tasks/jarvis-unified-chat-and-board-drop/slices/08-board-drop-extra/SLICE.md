# Slice 08 — Extra : dépôt de fichiers, images et URL sur le Board

## Goal
Permettre à l'utilisateur d'enrichir un Board par drop direct dans la scène, sans composer de message.

## Context
Les Boards, Artifacts et liens Board existent déjà; la scène constellation possède ses propres interactions. Réutiliser leurs contrats plutôt que dessiner un stockage de fichiers bis.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Permettre à l'utilisateur d'enrichir un Board par drop direct dans la scène, sans composer de message. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`
- `07-chat-attachments`

## Implementation Steps
1. Définir zones de drop acceptées (Board actif, scène/canevas) et feedback sans interférer avec les mouvements/clicks des objets existants.
2. Pour un fichier/image, réutiliser ingestion Artifact et lier ressource au Board actif avec provenance; pour une URL, enregistrer référence inerte/metadata validées et ne pas fetcher implicitement.
3. Afficher une ressource trouvable sur le Board et dans l'inspecteur Workspace; si l'objet scène requiert un contrat, valider cette projection séparément et sans remodéliser le graphe.
4. Supporter erreurs, annulation, duplicats, multi-drop et switch Board durant le transfert ; garantir aucune création de message chat, pas de déclenchement Brain auto.
5. Tests Board A vs B, image, document, URL, persistence après refresh, scoping, compatibilité avec inspecteur et scene.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/runtime/control_center_scene_interact.js`
- `jarvis/runtime/control_center_workspace.js`
- `jarvis/domain/board_artifact_links.py`
- `jarvis/core/artifact_service.py`
- `docs/scene-model.md`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.
- Avant code, exécuter `/caveman` et `/coding-guideline`.
- Frontend : exécuter `/impeccable`, affecter un agent Claude si cette règle est supportée par le host.

## Automated Validation
- `qa-verification` systématique.
- `code-review` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- Tests ciblés et cas adverses : Les dépôts sont reliés au **Board ciblé** et consultables après reconnexion.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Les dépôts sont reliés au **Board ciblé** et consultables après reconnexion.
- Pas de nouvelle conversation créée et aucune URL distante automatiquement lue.
- Fonction extra isolée, ne bloque pas l'usage chat P0.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Déposer fichier, image et URL dans un Board puis constater les trois ressources visibles et réutilisables après changement/reprise du Board.


## Contrat Slice 00 (agent 0, 2026-10-14)

**Dépendances révisées :** 01, **07** (ingestion), plus 06 seulement pour ne pas éditer `control_center.html` en même temps (séquencement, pas dépendance fonctionnelle). **Palier QA :** standard (`qa-verification`, `code-review`, `runtime-validation` avec captures ; `/impeccable`). Work Agent Claude.

Source : `../../docs/06-resolved-architecture.md`, D-BOARD.

**Décisions :** fichiers et images par `PUT /v1/uploads/{client_upload_id}?purpose=board&board_id=…` (provenance `board_drop`, cible = Board actif sinon 409 `board_drop_target_inactive`, contrôle après création et lien explicite de rattrapage `relinked: true`) ; URL par `POST /v1/uploads/links` → Artifact `kind = link`, `complete`, `text = url`, **jamais récupérée** (`http`/`https`, ≤ 2048, sans identifiants, sinon 400 `link_invalid`) ; visible dans l'inspecteur Workspace ; **pas d'objet de scène** (contrat de scène incompatible, `docs/scene-model.md:484-490` : à proposer en Issue) ; jamais un tour de chat ni un message au cerveau.

**Fichiers :**
- M `jarvis/domain/artifacts.py` : `ArtifactKind.LINK = "link"` ; M `jarvis/domain/uploads.py` (validation d'URL, `purpose=board`) ; M `jarvis/core/upload_service.py` (cible active, rattrapage par `WorkspaceService.artifact_link(origin=user)`) ; M `jarvis/protocol/upload_routes.py` (`purpose=board`, `POST /v1/uploads/links`) ; M `jarvis/runtime/chat_relay.py` ou N `jarvis/runtime/board_drop_relay.py` (`POST /api/boards/drop` multipart et `POST /api/boards/drop-link`, sous un préfixe ajouté à `READ_GUARDED_ROUTES`).
- N `jarvis/runtime/control_center_board_drop.js` (calque de dépôt au-dessus de la scène du Board actif, injecté par marqueur ; n'intercepte que `dragenter/dragover/drop` portant des fichiers ou `text/uri-list`, jamais les gestes de la scène) ; M `jarvis/runtime/control_center.html` (marqueur, styles) ; M `jarvis/runtime/control_center.py` (injection) ; M `jarvis/runtime/control_center_workspace.js:69` (libellé `link`) ; M `jarvis/runtime/capture_mcp.py:606` ; M `docs/artifacts.md`, `docs/boards.md`.

**Tests :** `tests/unit/test_board_drop.py` — `test_file_drop_links_active_board`, `test_image_drop_sniffed`, `test_drop_on_inactive_board_409`, `test_switch_race_relinks_target`, `test_url_inert_no_network` (aucune connexion sortante : transport réseau factice qui échoue le test s'il est appelé), `test_url_refused_schemes_and_credentials`, `test_no_conversation_event_no_brain_turn` (store d'événements et orchestrateur inchangés), `test_duplicate_drop_idempotent` ; `tests/unit/_board_drop_browser.mjs` + test Python associé — calque visible au survol avec fichier, dépôt multiple, URL déposée, scène toujours manipulable (clic et déplacement d'un objet après dépôt), Board A/B/A. Régressions : `test_scene_artifacts.py`, `test_workspace_manager_browser.py`, `test_boards_hud_browser.py`, `test_board_artifact_links.py`.

**Acceptation :** un PDF, une image et une URL déposés sur le Board A apparaissent dans ses Artifacts (inspecteur) après rechargement et après A → B → A, absents de B ; aucune conversation, aucun tour, aucune requête réseau vers l'URL.

**Ne pas toucher :** le modèle de scène (`jarvis/domain/scene*.py`, `sqlite_scene.py`), `link_to_active_board`, le panneau Chat, `control_center_timeline.js`.
