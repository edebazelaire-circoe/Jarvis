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

## Contrat Slice 00 (agent 0, 2026-10-14)

**Ordre révisé :** cette Slice passe **avant** 03 (03 lit son état). **Dépendances :** 01. **Palier QA : critique** — `qa-verification`, `code-review`, `runtime-validation` sur Core + Voice simulé isolés, `agent-trace-analysis` non requis (pas de prompt). Mutation autorisée (≤ 10 mutants) sur : fraîcheur du rapport, rejet d'un `seq` ancien, période `unknown` au démarrage, expiration de la demande, `chat_writable` par état.

Source : `../../docs/06-resolved-architecture.md`, D-VOICE (routes, charges utiles, machine d'état). Pas de backend UI ici : l'UI est en 06.

**Fichiers :**
- N `jarvis/domain/voice_channel.py` : états (`absent`, `unknown`, `background`, `connecting`, `active`, `error`, `switching`), `VoiceChannelReport` (validation stricte), `DisableRequest`, fonction pure `channel_view(reports, request, now, started_at) -> (state, chat_writable, locked_reason)`. Constantes `VOICE_CHANNEL_FRESH_S = 5.0`, `VOICE_DISABLE_TIMEOUT_S = 10.0`.
- N `jarvis/core/voice_channel.py` : `VoiceChannelService` en mémoire (epoch tiré à la construction, revision, dernier rapport par incarnation, demande courante) ; méthode **synchrone** `write_gate() -> str | None` (raison de refus) pour 03 ; diagnostics `core.voice_channel.report_rejected`, `core.voice_channel.disable_requested`, `core.voice_channel.disable_settled` (ids et codes seulement).
- M `jarvis/protocol/server.py` : `POST /v1/voice/channel/report`, `POST /v1/voice/channel/disable`, `GET /v1/chat/state` (binding courant + bloc `voice`). M `jarvis/protocol/client.py` : méthodes typées. M `jarvis/core/v2_app.py` : câblage `core.voice_channel`.
- M `jarvis/app.py` : dans `_voice_timeout_loop` (`:1767`), une étape `_report_voice_channel` sur le modèle de `_handle_live_ui_supervision` (`:1835-1878`) : rapport chaque seconde, demande lue dans la réponse, `await voice.mute(VoiceStopReason.USER)`, rapport d'acquittement immédiat ; une panne de rapport est journalisée une fois par épisode, jamais levée.
- M `jarvis/runtime/voice_v2.py` : `voice_incarnation_id` et `seq` ; rapport `connecting` immédiat (attente ≤ 0,5 s) avant l'ouverture du micro. Ne modifier ni `mute()` ni la logique de session.
- N `jarvis/runtime/chat_relay.py` (créé ici, enrichi par 03 et 07) : relais `GET /api/chat/state` et `POST /api/chat/voice/disable` sur la mécanique de `capture_relay.py` (codes CC standard). M `jarvis/runtime/control_center.py` : préfixe `/api/chat` dans `READ_GUARDED_ROUTES` (`:300-304`) et montage des routes.

**Tests :** `tests/unit/test_voice_channel_domain.py` (table de la machine d'état complète, frontières à 4,9 s / 5,1 s, `seq` égal refusé, nouvelle incarnation acceptée, grâce de démarrage), `tests/unit/test_voice_channel_service.py` (demande idempotente par `client_request_id`, expiration à 10 s, acquittement `failed`, réveil pendant `switching`), `tests/unit/test_voice_channel_protocol.py` (routes, auth, 400 strict), `tests/unit/test_voice_channel_reporter.py` (boucle Voice avec un faux Core : la demande appelle `mute` une seule fois, l'acquittement suit, `mute` qui lève → `failed` + `voice_disable_failed`, Core injoignable → pas d'exception). Régressions : `test_interaction_mode_follower.py`, tests Live stop existants, `test_control_center_origin_ports.py`.

**Acceptation :** voix `active` → `chat_writable=false` ; demande → `background` acquitté ≤ 2 s en test → `chat_writable=true` ; Brain, Session, Board, `InteractionMode` inchangés (asserté) ; voix absente → écriture permise ; Core redémarré → `unknown` 5 s.

**Ne pas toucher :** `jarvis/domain/interaction_mode.py`, `jarvis/runtime/interaction_mode_observer.py`, le cycle de vie Live (`live_lifecycle.py`, `live_primary_owner.py`), `brain_service.py`, `control_center.html`, le JARVIS vivant.
