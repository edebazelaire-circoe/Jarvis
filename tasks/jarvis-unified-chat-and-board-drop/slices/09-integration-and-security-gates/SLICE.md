# Slice 09 — Intégration isolée, scénarios de régression et preuves

## Goal
Établir une preuve end-to-end objective P0 + extra, sans toucher au Jarvis vivant.

## Context
Test sur worktree isolé, ports distincts et données sous `JARVIS_DATA_ROOT` propre. Utiliser des traces réelles pour vérifier le chemin Brain et travail.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Établir une preuve end-to-end objective P0 + extra, sans toucher au Jarvis vivant. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `02-chat-event-projection`
- `03-direct-brain-text-ingress`
- `04-voice-chat-channel-state`
- `05-chat-read-sync-relay`
- `06-chat-panel-and-composer`
- `07-chat-attachments`
- `08-board-drop-extra`

## Implementation Steps
1. Écrire/exécuter E2E : Voice -> sous-agents -> Chat lecture -> Passer au chat -> texte -> Brain réponse -> dépôt document ; re-Voice si applicable.
2. Exécuter tests cross-Board, pagination sans doublons, retry, déconnexion/reconnexion, réactivité, accessibilité, absence de TTS en text-only.
3. Tester fichiers malveillants/URL non fiables, origines/ACL, taille/erreur, résilience de payloads, migrations éventuelles.
4. Exécuter suite de non-régression Brain, Voice, timeline debug, Boards, Artifacts, Control Center, écran principal ; comparer baseline.
5. Obtenir `qa-verification` et QA contextuels de code/runtime/agent, conserver logs & captures datés avec HEAD ; ouvrir Issue uniquement pour découverte non induite hors-scope.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `tests/integration/test_board_session_e2e.py`
- `tests/integration/test_conversation_event_rollout_gate.py`
- `tests/unit/test_control_center_timeline_js.py`
- `tests/unit/test_schema_migrations.py`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.

## Automated Validation
- `qa-verification` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- `agent-trace-analysis` avec vraies traces si l'exécution, les outils ou le runtime agent changent.
- Tests ciblés et cas adverses : Tous les scénarios P0 et extra passent, preuve reproductible avec sha et environnement.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Tous les scénarios P0 et extra passent, preuve reproductible avec sha et environnement.
- Aucune régression nouvelle, aucun secret ou dump de log sensible exposé.
- Prêt pour Human validation seulement après QA machine maximale.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Aucun geste humain exigé pour cette Slice sauf blocage identifié par le PM.
