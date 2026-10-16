# Slices — Plan d'implémentation, ordre de dépendances

Révisé par la Slice 00 (agent 0, 2026-10-14). Contrat contraignant : `../docs/06-resolved-architecture.md`. Chaque `SLICE.md` porte une section « Contrat Slice 00 » qui prime sur ses étapes d'origine.

- [x] `00-project-manager` — Readiness, audit aveugle et orchestration (gate initial)
- [x] `01-canonical-contracts` — Contrats produit, événements, canal et attachments, docs seulement (dépend de : 00-project-manager)
- [x] `02-chat-event-projection` — Projection pure utilisateur/Brain, Python + JS en parité (dépend de : 01-canonical-contracts)
- [x] `04-voice-chat-channel-state` — État du canal vocal possédé par Core, rapports Voice, bascule (dépend de : 01-canonical-contracts) — **critique**
- [x] `03-direct-brain-text-ingress` — Ingress texte Brain, gardes serveur, aucun TTS (dépend de : 01-canonical-contracts, 04-voice-chat-channel-state) — **critique**
- [x] `05-chat-read-sync-relay` — Paramètre `projection=chat` sur la lecture existante (dépend de : 02-chat-event-projection)
- [x] `06-chat-panel-and-composer` — Onglet bas droit, panneau et dialogue texte (dépend de : 03-direct-brain-text-ingress, 04-voice-chat-channel-state, 05-chat-read-sync-relay)
- [x] `07-chat-attachments` — Backend des pièces jointes et référence au Brain (dépend de : 01-canonical-contracts, 03-direct-brain-text-ingress) — **critique**
- [x] `07b-chat-attachments-ui` — Pièces jointes dans le panneau Chat (dépend de : 06-chat-panel-and-composer, 07-chat-attachments)
- [x] `08-board-drop-extra` — Extra : dépôt de fichiers, images et URL sur le Board (dépend de : 01-canonical-contracts, 07-chat-attachments ; après 06 pour la page)
- [x] `09-integration-and-security-gates` — Intégration isolée, scénarios de régression et preuves (dépend de : 02, 03, 04, 05, 06, 07, 07b, 08)
- [ ] `10-release-and-human-acceptance` — Documentation finale, livraison et validation utilisateur (dépend de : 09-integration-and-security-gates)

**Séquencement imposé (fichiers partagés) :** serveur 04 → 03 → 05 → 07 (`jarvis/protocol/server.py`, `jarvis/runtime/control_center.py`) ; page 06 → 07b → 08 (`control_center.html`). Seule 02 peut tourner en parallèle de 04. Un seul Work Agent par worktree ; jamais `git stash`.

**Paliers QA :** critiques 03, 04, 07 (mutation autorisée, au plus 10 mutants, sur les gardes listées) ; les autres standard.

**Task Type :** levé (`waived-by-agent-0`), précédent `tasks/jarvis-bare-hands-ui-calibration-refinement/slices/00-project-manager/READINESS.md`.

**Démarrage impératif :** Slice 00 par l'agent 0, sans délégation ; aucune Slice de code avant `READY`. Les Slices 02 à 07b forment le chemin P0 (jalon utilisable sans pièce jointe après 06, P0 complet après 07b) ; 08 est l'extra Board ; 09 et 10 valident l'ensemble.
