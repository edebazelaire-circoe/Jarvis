# Slice 02 — Projection utilisateur/Brain sans stockage parallèle

## Goal
Dériver le fil de chat depuis le ledger existant, sans jamais copier l'historique.

## Context
`ConversationEventStore` est L3 ; `user.transcript.accepted` et `brain.message.published` sont publics; `conversation_transcript.py` et la timeline incluent davantage de voies.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Dériver le fil de chat depuis le ledger existant, sans jamais copier l'historique. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`

## Implementation Steps
1. Introduire un projecteur pur ou réutiliser un projecteur existant, filtrage exact sur types autorisés ; spécifier statut sur absence de texte/événement.
2. Séquence du store, IDs immuables, déduplication des republications identiques selon le contrat; conserver deux messages différents même corrélation.
3. Implémenter chargement paginé, scoping par conversation du binding actif, cursor stable et adaptateur optionnel pour liens « voir transcript complet ».
4. Tester ordre arbitraire horloges, pages filtrées vides, reconnexion, anciennes Sessions, A/B/A et protection de données sur changement de Board.
5. Ne pas écrire de nouvelle table/JSONL de messages ni exposer `RuntimeJournal` comme source.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/domain/conversation_events.py`
- `jarvis/domain/conversation_transcript.py`
- `jarvis/domain/conversation_event_query.py`
- `jarvis/core/conversation_event_query.py`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.
- Avant code, exécuter `/caveman` et `/coding-guideline`.

## Automated Validation
- `qa-verification` systématique.
- `code-review` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- Tests ciblés et cas adverses : Seuls deux types sont visibles, dans le bon ordre, avec identité stable.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Seuls deux types sont visibles, dans le bon ordre, avec identité stable.
- Un rafraîchissement n'ajoute ni trou ni doublon dans le fil.
- Les autres Boards et les traces diagnostiques ne sont jamais inclus.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Aucun geste humain exigé pour cette Slice sauf blocage identifié par le PM.

## Contrat Slice 00 (agent 0, 2026-10-14)

**Portée resserrée :** projection **pure**, sans route ni I/O. Le filtre côté Core et le relais sont en 05. Source : `../../docs/06-resolved-architecture.md`, D-PROJ.

**Dépendances :** 01. Peut tourner en parallèle de 04 (fichiers disjoints). **Palier QA :** standard (`qa-verification`, `code-review`).

**Fichiers :**
- N `jarvis/domain/chat_projection.py` : `CHAT_PROJECTION = "chat"`, `CHAT_EVENT_TYPES`, `is_chat_event(event)` (prédicat sans état : `user.transcript.accepted` dont `addressing` est absent, `addressed` ou `uncertain` ; `brain.message.published` ; `brain.turn.failed`), et `project_chat(stored_events) -> tuple[ChatItem, ...]`, implémentation de référence des règles avec état (promotion `uncertain` par `brain.message.published` de même `correlation_id`, affichée à sa propre séquence ; repli par réutilisation de la règle de `collapse_published_messages`, `jarvis/domain/conversation_transcript.py:150-161`, sans la recopier si un import suffit ; statut d'échec attaché à la bulle utilisateur ; clé `event_id`). Aucune horloge, aucune heuristique de temps.
- N `jarvis/runtime/control_center_chat_model.js` : mêmes règles en JS pur, sans DOM, exporté comme les autres modèles (`module.exports` sous node, global dans la page). Fonctions : `createChatModel()`, `applyPage(model, page)` (rejouable, idempotente par `event_id`), `items(model)`, `markPending(model, correlationId)`, `reset(model, conversationId)`.
- N `tests/unit/test_chat_projection.py`, `tests/unit/test_control_center_chat_model_js.py` (node, comme `test_control_center_timeline_js.py`).

**Tests :** `test_fixture_cases_python` et `test_fixture_cases_js` sur `tests/fixtures/chat_projection/cases.json` (parité exacte) ; `test_is_chat_event_allowlist_exhaustive` (parcourt tout `ConversationEventType` : seuls trois passent) ; `test_uncertain_hidden_until_promoted` ; `test_refused_uncertain_never_shown` ; `test_page_replay_idempotent` ; `test_cursor_split_promotion` (tour incertain et message Brain dans deux pages successives) ; `test_failed_on_system_turn_ignored`.

**Acceptation :** les deux implémentations donnent la même sortie sur tout le fixture ; aucune lecture de `RuntimeJournal` ; aucun nouveau stockage.

**Ne pas toucher :** `control_center_timeline.js` (lecture seule pour la parité), `jarvis/core/*`, `jarvis/protocol/*`, `control_center.html`.
