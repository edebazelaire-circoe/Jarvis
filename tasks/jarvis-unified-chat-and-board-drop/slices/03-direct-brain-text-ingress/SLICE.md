# Slice 03 — Ingress texte Brain, sans dépendance Voice

## Goal
Acheminer un tour texte au Brain actif par Core en gardant Session, Board et capacité de délégation.

## Context
`BrainOrchestrator` et `BoardBrainPool` existent ; rechercher et réutiliser admission, correlation et outcome. L'UI n'appelle jamais directement un agent CLI.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Acheminer un tour texte au Brain actif par Core en gardant Session, Board et capacité de délégation. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`

## Implementation Steps
1. Définir Core route/adapter et relay Control Center sécurisés pour le canal texte (source reconnue par domaine), cible Binding Session+Board **actif**.
2. Admettre et persister le tour une fois (`user.transcript.accepted`), idempotence par client_request_id sur retry/latence ; garder le contexte/mémoire/travaux identiques à Voice.
3. Éviter toute création de speech/TTS pour le tour « texte » et toute annulation de CLI en cas de désactivation Voice ; faire confiance à la publication canonique Brain pour afficher la réponse.
4. Répondre avec accusé de réception corrélé, codes d'erreur stables sur Core indisponible, binding absent, Voice actif, doublon, échec backend et auth.
5. Tester sans process voix, deux envois concurrents, replay, Board switch/race, appel aux sous-agents, confirmation/sécurité existantes.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/core/brain_service.py`
- `jarvis/core/voice_admission.py`
- `jarvis/adapters/control_center_brain.py`
- `jarvis/domain/v2.py`
- `jarvis/runtime/control_center.py`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.
- Avant code, exécuter `/caveman` et `/coding-guideline`.

## Automated Validation
- `qa-verification` systématique.
- `code-review` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- `agent-trace-analysis` avec vraies traces si l'exécution, les outils ou le runtime agent changent.
- Tests ciblés et cas adverses : Un tour texte atteint le même Brain du binding que Voice et peut déléguer.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Un tour texte atteint le même Brain du binding que Voice et peut déléguer.
- Les tours textuels créent un seul événement utilisateur, puis le vrai message Brain ; aucun TTS.
- Les gardes de sécurité/permissions existants restent en place.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Aucun geste humain exigé pour cette Slice sauf blocage identifié par le PM.
