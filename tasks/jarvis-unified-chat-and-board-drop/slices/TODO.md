# Slices — Plan d’implémentation, ordre de dépendances

- [ ] `00-project-manager` — Readiness, audit aveugle et orchestration (gate initial)
- [ ] `01-canonical-contracts` — Contrats produit, événements, canal et attachments (dépend de : 00-project-manager)
- [ ] `02-chat-event-projection` — Projection utilisateur/Brain sans stockage parallèle (dépend de : 01-canonical-contracts)
- [ ] `03-direct-brain-text-ingress` — Ingress texte Brain, sans dépendance Voice (dépend de : 01-canonical-contracts)
- [ ] `04-voice-chat-channel-state` — Verrouillage et bascule Voice vers Chat (dépend de : 01-canonical-contracts, 03-direct-brain-text-ingress)
- [ ] `05-chat-read-sync-relay` — Lecture live et rattrapage via événements existants (dépend de : 02-chat-event-projection, 03-direct-brain-text-ingress)
- [ ] `06-chat-panel-and-composer` — Onglet bas droit, panneau et dialogue texte (dépend de : 04-voice-chat-channel-state, 05-chat-read-sync-relay)
- [ ] `07-chat-attachments` — Pièces jointes et drag-and-drop dans le chat (dépend de : 01-canonical-contracts, 03-direct-brain-text-ingress, 06-chat-panel-and-composer)
- [ ] `08-board-drop-extra` — Extra : dépôt de fichiers, images et URL sur le Board (dépend de : 01-canonical-contracts, 07-chat-attachments)
- [ ] `09-integration-and-security-gates` — Intégration isolée, scénarios de régression et preuves (dépend de : 02-chat-event-projection, 03-direct-brain-text-ingress, 04-voice-chat-channel-state, 05-chat-read-sync-relay, 06-chat-panel-and-composer, 07-chat-attachments, 08-board-drop-extra)
- [ ] `10-release-and-human-acceptance` — Documentation finale, livraison et validation utilisateur (dépend de : 09-integration-and-security-gates)

**Démarrage impératif :** Slice 00, exécutée par le Project Manager sans délégation. Aucune Slice de code ne peut démarrer avant `READY` et résolution du vocabulaire réel Workspace Task Type. Toutes les Slices sont en attente à la création ; aucune preuve d'implémentation n'est supposée. Les Slices 02–07 constituent le chemin P0, Slice 08 est l'extra Board inclus, Slices 09–10 valident l'ensemble.
