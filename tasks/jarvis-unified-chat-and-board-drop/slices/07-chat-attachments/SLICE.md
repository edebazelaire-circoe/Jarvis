# Slice 07 — Pièces jointes et drag-and-drop dans le chat

## Goal
Joindre des fichiers multiples au message Brain sans imposer des bornes produit arbitraires.

## Context
Le registre Artifacts et les Contexts existent; le Brain peut ou non supporter des modalités selon CLI, à mesurer avant implémentation.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Joindre des fichiers multiples au message Brain sans imposer des bornes produit arbitraires. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`
- `03-direct-brain-text-ingress`
- `06-chat-panel-and-composer`

## Implementation Steps
1. Construire endpoint authentifié de stage/upload selon sécurité Artifact (`JARVIS_DATA_ROOT`, payloads atomiques, types déclarés, ACL Session/Board, nom défensif, pas de symlinks/traversal).
2. Associer les références de fichiers au tour Brain par représentation structurée canonique et uniquement après upload réussi ; adapter au support réel des agents, annoncer les formats non supportés et ne pas prétendre analyser un fichier non lu.
3. Ajouter bouton attacher et dropzone dans le panneau avec liste, états progress/ready/failed, retry sûr, plusieurs fichiers, suppression avant envoi, taille/format erreurs humaines claires.
4. Établir bornes techniques configurables, vérifications MIME/ext/quotas/auth et observabilité sans enregistrer les octets dans les événements conversationnels.
5. Tester race abandon, double drop, gros fichier, image, PDF, caractères Unicode, environnement sans Voice, changement Board/Session avant envoi.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/core/artifact_service.py`
- `jarvis/domain/artifacts.py`
- `jarvis/adapters/artifact_payloads.py`
- `jarvis/runtime/control_center.html`
- `jarvis/runtime/workspace_relay.py`

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
- `agent-trace-analysis` avec vraies traces si l'exécution, les outils ou le runtime agent changent.
- Tests ciblés et cas adverses : Fichier(s) réellement accessibles au Brain autorisé et liés au bon contexte.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Fichier(s) réellement accessibles au Brain autorisé et liés au bon contexte.
- Aucun fichier non pris en charge annoncé comme traité ; aucune perte silencieuse ni double Artifact.
- Sûreté chemins/récupération et absence de fuites dans logs/événements.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Tester sélection et dépôt de deux fichiers de types différents dans un tour de Chat et vérifier la prise en compte par Brain.

## Note de compatibilité

Si le Brain actif ne sait pas consommer un format (ex. image vs document), ne pas prétendre qu'un chemin local passé en texte suffit. Définir explicitement support par agent, conversion/import sécurisé si existant, ou feedback « non pris en charge ». Toute extension de capacité doit être testée séparément.


## Contrat Slice 00 (agent 0, 2026-10-14)

**Découpage :** cette Slice devient le **backend** des pièces jointes (ingestion, sécurité, référence au cerveau, accès du CLI). Le bouton, la zone de dépôt et les états du panneau partent en **`07b-chat-attachments-ui`** ; le contrôle humain HV-JCHAT-07-01 y est déplacé. **Dépendances révisées :** 01, 03. **Palier QA : critique** — `qa-verification`, `code-review`, `runtime-validation` (Core + Control Center isolés, `curl` multipart réel), `agent-trace-analysis` sur de vraies traces (le brief change ; preuve que le CLI lit un PDF et une image joints). Mutation autorisée (≤ 10 mutants) sur : borne de taille en flux, `Content-Length` court, conflit de rejeu, reniflage, `brain_readable`, refus `attachment_not_allowed`.

Source : `../../docs/06-resolved-architecture.md`, D-ATT (route, identité, reniflage, table de lisibilité, bloc du brief, `artifacts_root`).

**Fichiers :**
- N `jarvis/domain/uploads.py` : bornes (`JARVIS_UPLOAD_MAX_BYTES` 64 Mio, `JARVIS_CHAT_MAX_ATTACHMENTS` 10, lues par une fonction pure partagée Core/CC), identité `jart_up_<sha256[:40]>`, nom de payload `upload.<ext>`, `sniff_mime(head) -> str`, table `BRAIN_READABLE` par agent (`claude` : texte, PNG/JPEG/GIF/WebP, PDF ; `codex` : vide), validation du nom d'origine.
- N `jarvis/core/upload_service.py` : façade sur `ArtifactService.create` / `open_spool` / `finalize` (`jarvis/core/artifact_service.py:95-210`) ; refus en flux au-delà de la borne (spool fermé, Artifact `failed` codé) ; métadonnées `original_name`, `declared_mime`, `sha256`, `provenance`, `client_upload_id`, `brain_readable`.
- N `jarvis/protocol/upload_routes.py` : `PUT /v1/uploads/{client_upload_id}?purpose=chat` (le `purpose=board` est ajouté par 08 ; ici `board` → 400).
- M `jarvis/domain/artifacts.py` : `ArtifactKind.UPLOAD = "upload"` (`:136`). M `docs/artifacts.md` (table des natures). M `jarvis/runtime/capture_mcp.py:606` (filtre `artifact_search`). M `jarvis/runtime/control_center_workspace.js:69` (libellé « Pièce jointe du chat » / « Fichier déposé » selon la provenance).
- M `jarvis/protocol/server.py` `submit_brain_turn` : étape 5 de D-INGRESS (validation des pièces) ; M `jarvis/domain/conversation_events.py` : clé `attachment_count` dans `ATTRIBUTE_KEYS` (`:296`) ; M `jarvis/core/voice_admission.py` `record_user_turn_accepted` (`:69-70`) : `attachment_count` tiré des métadonnées (le rejeu et le backfill restent identiques octet pour octet) ; M `docs/conversation-events.md`.
- M `jarvis/domain/brain_context.py` (`BrainAttachmentsContext`, bornes), `jarvis/core/brain_service.py` (`:1845`, construction depuis le registre au moment du tour), `jarvis/adapters/control_center_brain.py` `_turn_context` (bloc `attachments`, absent sinon), `jarvis/runtime/control_center.py` `build_agent_brief` (bloc de **données**, mention « non lisible » pour `brain_readable=false`).
- M `jarvis/core/session_manager.py` (`:836`) : `artifacts_root` à côté de `sessions_root` ; M `jarvis/runtime/control_center.py` : `_learn_sessions_root` accorde aussi `artifacts_root` par `--add-dir`, même politique de relance (jamais pendant un tour ni un travail, `:1834-1840`).
- M `jarvis/runtime/chat_relay.py` : `POST /api/chat/uploads` multipart en flux (`request.multipart()`, corps Core streamé, rien sur disque côté CC), ajoute `brain_readable` selon l'agent du foreground.

**Tests :** `tests/unit/test_uploads_domain.py` (noms Unicode, `..`, NUL, extensions trompeuses, reniflage par type, table de lisibilité) ; `tests/unit/test_upload_service.py` (borne dépassée en flux → `failed` sans fichier final, `Content-Length` court, vide, rejeu identique 200, rejeu différent 409, concurrent 409 `upload_in_progress`, `.partial` jamais écrasé, chemin `MAX_PATH`) ; `tests/unit/test_upload_protocol.py` (Core + relais CC : garde, deux fichiers successifs, fichier > 6 Mio passé en flux, codes relayés, aucun octet ni nom d'origine dans `trace.jsonl`) ; `tests/unit/test_chat_attachments_brain_context.py` (bloc rendu, chemin absolu présent au brief et absent de toute réponse HTTP vers le navigateur et de tout événement, pièce d'une autre Session refusée, pièce `pending` refusée, `attachment_count` sur l'événement, `add_dirs` contient `artifacts_root`). Régressions : `test_artifact_store.py`, `test_artifact_payloads.py`, `test_artifacts_domain.py`, `test_board_artifact_links.py`, `test_capture_mcp.py`, `test_control_center_prompts.py`, `test_conversation_event_backfill.py`, `test_schema_migrations.py` (vert sans nouvelle version).

**Acceptation :** un PDF et une PNG joints sont lus par le CLI Claude réel dans une instance isolée (trace) ; un `.zip` est annoncé non lisible et le cerveau ne prétend pas l'avoir analysé (trace) ; aucune migration ; aucun double Artifact sur reprise.

**Ne pas toucher :** `link_to_active_board` (règle globale), `ClaudeLocalAgent.send(images=…)`, `control_center.html`, `control_center_chat.js` (07b).
