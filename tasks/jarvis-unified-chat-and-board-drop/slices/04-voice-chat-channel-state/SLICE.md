# Slice 04 — Verrouillage et bascule Voice vers Chat

## Goal
Permettre la lecture du chat pendant Voice actif, mais refuser les envois jusqu'à arrêt effectif du canal vocal.

## Context
Ne pas utiliser `InteractionMode` ou les architectures Voice pour représenter `chat_active`. Le propriétaire Voice doit attester son propre statut.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Permettre la lecture du chat pendant Voice actif, mais refuser les envois jusqu'à arrêt effectif du canal vocal. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`
- `03-direct-brain-text-ingress`

## Implementation Steps
1. Exposer état fiable de Voice et le publier au Control Center/Chat avec transitions asynchrones.
2. Action explicite « Passer au chat » demandant au runtime propriétaire la désactivation Voice, puis attendre ACK effectif ; ne pas tuer Core/Brain/BoardBrains ni annuler travaux en cours.
3. Le serveur refuse les écritures texte si état actif/transition/indéterminé ; UI grisée et message d'aide sur tentative.
4. Sur échec de désactivation ou réactivation Voice, rester/verrouiller sans perdre le fil visible ; protéger la course entre submit et activation.
5. Tests avec doubles/instance isolée de Voice, Brain work long et subagents, erreurs, racine de données inchangée.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/runtime/voice_switch.py`
- `jarvis/runtime/control_center_live.js`
- `jarvis/runtime/control_center.py`
- `jarvis/core/brain_service.py`

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
- Tests ciblés et cas adverses : Bascule réussie -> Voice arrêté, Brain et sous-agents encore fonctionnels.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Bascule réussie -> Voice arrêté, Brain et sous-agents encore fonctionnels.
- Voix active ou inconnue -> envoi texte interdit avec raison ; lecture continue.
- Aucun changement forcé de Session, Board ou mode Interaction.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Sur instance utilisateur autorisée, confirmer que Passer au chat coupe seulement Voice, pas les travaux en cours.
