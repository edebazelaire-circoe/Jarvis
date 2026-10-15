# Slice 07b — Pièces jointes dans le panneau Chat (UI)

## Goal
Joindre un ou plusieurs fichiers à un message du Chat par bouton ou glisser-déposer, avec des états clairs, sur le backend de la Slice 07.

## Context
Créée par la Slice 00 (agent 0, 2026-10-14) en scindant l'ancienne Slice 07 : le backend critique (ingestion, sécurité, référence au cerveau) reste en 07 ; l'interface est ici. Contrat contraignant : `../../docs/06-resolved-architecture.md` (D-ATT, D-UI).

## Canonical Concepts
- `../../docs/06-resolved-architecture.md`, `docs/chat.md` (écrit par la Slice 01), `docs/artifacts.md`.

## Scope
### In Scope
Bouton « Joindre », zone de dépôt sur le panneau Chat, liste des pièces avant envoi, progression, retrait, reprise, messages d'erreur humains, envoi du message avec les ids d'Artifact.

### Out of Scope
- Tout changement serveur (07), le dépôt sur Board (08), la chronologie, le JARVIS vivant.

## Dependencies
- `06-chat-panel-and-composer`
- `07-chat-attachments`

## Implementation Steps
1. `/impeccable` puis `/caveman` et `/coding-guideline`.
2. Ajouter au panneau un bouton accessible qui déclenche un `input type=file multiple` caché, et une zone de dépôt limitée au panneau (un dépôt ailleurs ne fait rien ; le navigateur n'ouvre jamais le fichier).
3. Un fichier = une requête `POST /api/chat/uploads` (multipart : `client_upload_id` puis `file`), `client_upload_id` UUID v4 gardé pour la reprise ; progression par `XMLHttpRequest.upload.onprogress`.
4. États par pièce : `en cours`, `prête`, `prête, non lisible par le Brain` (`brain_readable=false`), `échec` (message selon le code ; `upload_too_large` donne la borne), `retirée`. Envoi bloqué tant qu'une pièce est `en cours` ; texte obligatoire (« Ajoutez un message pour accompagner les fichiers »).
5. Envoi : `attachments` = ids des pièces prêtes. La bulle utilisateur affiche « N pièce(s) jointe(s) » à partir de `attributes.attachment_count` ; les noms ne vivent que dans l'état local du message envoyé ; après rechargement, le nombre et un lien vers l'inspecteur Workspace.
6. Changement de Board ou de Session pendant la préparation : pièces non envoyées marquées « à renvoyer » (liées à l'ancien contexte) ; jamais envoyées en silence vers la nouvelle conversation.

## Files Likely Touched
- `jarvis/runtime/control_center_chat.js`, `jarvis/runtime/control_center_chat_model.js`, `jarvis/runtime/control_center.html` (styles)

## Architecture Constraints
- Aucun chemin absolu, aucun octet ni nom de fichier dans les événements ou journaux.
- Le verrou vocal s'applique à l'envoi : pièces préparables, envoi refusé tant que `chat_writable` est faux.

## Automated Validation
- `qa-verification`, `code-review`, `runtime-validation` (captures).
- Tests navigateur Chrome headless CDP.

## Acceptance Criteria
- Deux fichiers de types différents, l'un sélectionné, l'autre déposé, partent dans un même message, chacun avec un état exact.
- Un format non lisible est dit avant l'envoi ; aucune perte silencieuse ; reprise sans doublon.

## Documentation Updates
- Section UI de `docs/chat.md`.

## Handoff Notes
- Human check : HV-JCHAT-07-01 (déplacé depuis 07).

## Contrat Slice 00 (agent 0, 2026-10-14)

**Dépendances :** 06, 07. **Palier QA :** standard (`qa-verification`, `code-review`, `runtime-validation` ; `/impeccable`). Work Agent Claude.

**Fichiers :** M `jarvis/runtime/control_center_chat.js`, `jarvis/runtime/control_center_chat_model.js` (état des pièces, pur), `jarvis/runtime/control_center.html` (styles du panneau seulement) ; N `tests/unit/_chat_attachments_browser.mjs`, `tests/unit/test_control_center_chat_attachments_browser.py` ; cas ajoutés à `tests/unit/test_control_center_chat_model_js.py`.

**Tests :** `select_two_files_then_send`, `drop_two_files_on_panel`, `drop_outside_panel_ignored`, `unreadable_format_announced`, `too_large_shows_limit`, `retry_reuses_client_upload_id`, `remove_before_send`, `send_blocked_while_uploading`, `text_required_with_files`, `board_switch_marks_pending_attachments`, `voice_lock_blocks_send_not_preparation`, `keyboard_accessible_attach_button`.

**Acceptation :** les douze cas passent ; captures jointes au LOG ; aucune modification serveur.

**Ne pas toucher :** fichiers Python, `control_center_timeline.js`, logique de lecture (05/06) hors besoin d'affichage.
