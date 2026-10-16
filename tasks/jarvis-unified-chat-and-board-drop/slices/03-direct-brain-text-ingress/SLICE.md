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

## Contrat Slice 00 (agent 0, 2026-10-14)

**Dépendances révisées :** 01, **04** (la garde lit `VoiceChannelService.write_gate()`). **Palier QA : critique** — `qa-verification`, `code-review`, `runtime-validation` (Core + Control Center isolés, sans processus Voice), `agent-trace-analysis` sur de vraies traces (le brief change). Mutation autorisée (≤ 10 mutants) sur : ordre des gardes (rejeu avant verrou), égalité au binding, lecture synchrone du verrou, borne 8192, `_text_only` (cache et repli durable).

Source : `../../docs/06-resolved-architecture.md`, D-INGRESS et D-NOTTS.

**Fichiers :**
- M `jarvis/protocol/server.py` `submit_brain_turn` (`:585-667`) : pour `source=text` seulement, les étapes 1 à 4 et 6 de D-INGRESS (l'étape 5, pièces jointes, est ajoutée par 07 ; ici `attachments` non vide → 400 `invalid_request` « attachments not supported yet »). `ValueError` de conflit d'identité → 409 `chat_request_conflict`.
- M `jarvis/domain/v2.py` : `BrainTurnInput.attachments: tuple[str, ...] = ()` (validé : ids d'Artifact, distincts, bornés) — utilisé par 07.
- M `jarvis/core/voice_admission.py` `persist_turn` : `metadata["attachments"]` seulement si non vide ; ajouté aux clés comparées.
- M `jarvis/core/brain_service.py` : `_text_only(conversation_id, correlation_id)` (cache rempli par `submit` + repli `repository.get_turn`) ; dans `_emit_speech`, après la rétention (`:2638-2645`) et avant `_speech_gate`, retenue `SPEECH_WITHHELD_TEXT_CHANNEL = "text_channel"` + diagnostic `core.brain.speech_withheld_text_channel`.
- M `jarvis/adapters/control_center_brain.py` `_turn_context` : `"channel": "text"` pour `source=text`, absent sinon (contexte octet pour octet inchangé pour les autres tours).
- M `jarvis/runtime/control_center.py` `build_agent_brief` (`:1019`) : ligne « Canal : écrit (chat)… 6000 caractères au plus… » ; montage du relais.
- M `jarvis/runtime/chat_relay.py` (créé par 04) : `POST /api/chat/turns` (garde `/api/chat` posée par 04, JSON obligatoire, corps ≤ 64 Kio, délai 15 s, `core_timeout` 504, journal `chat.turn.relayed` sans texte).

**Tests :** `tests/unit/test_chat_text_ingress.py` — `test_text_turn_reaches_foreground_binding_brain`, `test_not_foreground_409`, `test_locked_by_voice_409_each_reason`, `test_voice_absent_allows`, `test_replay_after_lock_returns_duplicate_200`, `test_same_request_other_text_409_conflict`, `test_text_too_long_400`, `test_single_user_event_per_turn`, `test_delegation_available` (le backend factice reçoit le même contexte qu'un tour vocal, `channel` en plus) ; `tests/unit/test_speech_text_channel.py` — `test_text_turn_result_published_not_spoken`, `test_late_work_result_after_core_restart_not_spoken` (repli durable), `test_voice_turn_still_spoken`, `test_notice_policy_unchanged` ; `tests/unit/test_chat_relay.py` — garde (Origin étranger, Host non bouclage, `cross-site`, `same-site` en POST), 415, 413, relais des codes Core, 504. Régressions : `test_v2_brain_orchestrator.py`, `test_board_speech_authority.py`, `test_conversation_event_producers.py`, `test_voice_admission_protocol.py`, `test_control_center_prompts.py`.

**Acceptation :** un tour texte sans processus Voice atteint le cerveau du binding, produit un seul `user.transcript.accepted` (`attributes.source = "text"`) puis `brain.message.published`, **zéro** `brain.speech.requested` pour sa corrélation (asserté sur le store) ; un sous-agent lancé par ce tour fonctionne (trace réelle) ; les tours vocaux sont inchangés.

**Ne pas toucher :** les relais d'état et de bascule de 04 hors besoin ; la route `/api/agent/ask` et `/api/agent/send` (le navigateur ne les appelle pas) ; `InteractionMode`/`OutputDisposition` ; `control_center.html` ; migrations.
