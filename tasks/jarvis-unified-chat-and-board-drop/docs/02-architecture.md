# 02 — Architecture cible et frontières

## Flux

```text
Voice Runtime -- audio/transcription commit --> Core BrainTurn admission --+
                                                                       | (Session + Board binding)
Chat UI -- text + optional authorized artifact refs --> Chat relay --+--> Core BrainOrchestrator
                                                                        --> BoardBrainPool/CLI agent
                                                                        --> BrainOutcomeService
                                                                        --> ConversationEventStore
                                                                              |       |
                                                                  filtered chat projection    debug timeline (unfiltered)
                                                                              |
                                                                        Chat UI (read only)
```

**Une seule source de données :** `ConversationEventStore` avec les types autorisés `USER_TRANSCRIPT_ACCEPTED` et `BRAIN_MESSAGE_PUBLISHED`. `RuntimeJournal` ne sert que de drill-down ; ne pas reconstruire l'histoire sur trace.jsonl. Les entrées doivent pointer vers `event_id`, `conversation_id`, `correlation_id` / `turn_id` / `outcome_id` si disponibles ; séquence du store = ordre canonique. Conserver la sémantique de `collapse_published_messages` ; ne pas masquer des reformulations non identiques.

**Portée :** `Session` ouverte -> Board actif -> `BoardConversationBinding.conversation_id`. Lors du changement de Board, re-scope immédiatement la vue et les envois ; jamais fuite d'une autre conversation. Une Session pouvant visiter plusieurs Boards, « historique de Session » signifie **fil courant du binding** par défaut, pas fusion automatique de tous les Boards. Si le produit exige une vue globale plus tard, elle mérite une décision séparée.

**Écriture :** navigateur -> Control Center proxy authentifié -> Core admission/Brain (`BrainTurnInput` et contrats existants) -> Brain backend présent dans le binding ; **jamais navigateur -> provider**, et jamais navigateur -> Voice `bridge` en contournant le Brain. Tout tour doit être durablement accepté une seule fois, puis projeté via `user.transcript.accepted`; ne pas fabriquer un message optimiste persistant séparé. `client_request_id` stable/idempotent sur retry ; statut `pending`, erreur corrélée et déduplication.

**Réponses :** `brain.message.published` provenant de `BrainOutcomeService`; le message texte est indépendant de `mouth.speech.*` et des réflexes ; chat seul -> aucune demande de restitution TTS liée à ce tour. Le Brain peut traiter, déléguer, clarifier, échouer ; afficher un état borné sans fabriquer une réponse. Si une publication Brain est non attribuable, la politique d'affichage doit être explicite dans Slice 01, jamais un filtrage par heuristique d'horloge.

**Voix/chat :** verrouillage est un état de **canal d'entrée** distinct des trois `InteractionMode`. Voice actif -> chat read-only, même événementiel. `Passer au chat` commande au propriétaire du Voice Runtime un arrêt/disable du canal audio, attend son ACK + preuve d'état, puis déverrouille l'envoi. L'arrêt du canal ne doit pas fermer Session/Board, annuler `BrainOrchestrator` ni détruire `BoardBrainPool`. Les échecs d'arrêt gardent le chat verrouillé avec message d'erreur. Sur réactivation Voice, bloquer toute nouvelle saisie et traiter explicitement les envois en vol sans les perdre/doubler.

**Uploads chat :** Browser sélection/drop -> ingress sûr serveur, validation/noms/MIME/longueurs/anti-traversal/quota techniques -> payload durable sous `JARVIS_DATA_ROOT` par service approprié -> Artifact lié au Context/Session (et éventuellement Board uniquement sur action explicite) -> référence structurée transmise au Brain selon capacités vérifiées. Aucun binaire brut ni données sensibles en trace/event attributes ; ne pas exposer path absolu au navigateur. État `pending/complete/failed` idempotent ; nettoyage sûr des uploads refusés/incomplets.

**Drop Board extra :** overlay ciblé sur le Board/scene ; `File` (images comprises) -> Artifact ; URL drag -> référence metadata/lien (URL inert par défaut, pas fetch SSRF). Création d'un lien `BoardArtifactLink` / ressource Board canonique, visible dans inspecteur et, si compatible avec les contracts scène, sous forme d'objet scène ; absence de lien scène ne doit pas empêcher l'ajout au Board. Une resource Board n'est pas un message de conversation.

## Points d'entrée code à vérifier à HEAD frais

- Domaine événements : `jarvis/domain/conversation_events.py`, `conversation_transcript.py`, `conversation_event_query.py`.
- Query et stockage : `jarvis/core/conversation_event_query.py`, `jarvis/adapters/sqlite_conversation_events.py`, `jarvis/runtime/conversation_event_view.py`, `control_center_timeline.js`.
- Core Brain : `jarvis/core/brain_service.py`, `brain_outcomes.py`, `voice_admission.py`, `jarvis/adapters/control_center_brain.py`, `jarvis/domain/v2.py`.
- Runtime/HTML : `jarvis/runtime/control_center.py`, `control_center.html`, `control_center_live.js`, `control_center_boards.js`, `control_center_workspace.js`, `voice_switch.py`.
- Board/Artifact : `jarvis/core/artifact_service.py`, `jarvis/domain/artifacts.py`, `board_artifact_links.py`, `jarvis/runtime/workspace_relay.py`.

Tout ajout API doit recevoir contrat d'authentification, erreur stable, tests et documentation. Ne pas faire fuiter des routes diagnostiques à un nouveau client non autorisé.
