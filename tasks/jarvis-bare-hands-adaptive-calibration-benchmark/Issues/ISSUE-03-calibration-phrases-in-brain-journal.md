# ISSUE-03 — Les phrases et résultats de calibration restent dans le journal général du cerveau

Découvert à la QA réelle de la Slice 06 (2026-09-26), hors périmètre de la Slice (décision d'agent 0 : ne pas toucher au journal général dans cette Slice).

**Constat.** La séance de calibration (décision 41 : la preuve ne quitte pas la page) et son module serveur (`jarvis/runtime/barehands_calibration.py`) ne journalisent ni les phrases de l'utilisateur ni les résultats de calibration. Mais le **journal général du cerveau** (`runtime/trace.jsonl`), comme pour **chaque** tour, écrit :

- `agent.input` — la phrase de l'utilisateur telle qu'elle part au cerveau (« le relâchement colle, je dois ouvrir grand pour lâcher ») ;
- `agent.event` / `agent.ask` — les événements du flux du CLI, dont les appels d'outils `calibration_*` et leurs résultats (mesures scalaires, textes de retour, hypothèses, essais).

Ces lignes vivent aussi longtemps que la trace (rotation du journal), donc au-delà de la fin de la séance.

**Ce qui est vrai aujourd'hui** (et écrit ainsi dans `docs/barehands-contracts.md` décisions 41/50/53 et `docs/OPERATIONS.md`) : rien de la calibration n'est rangé ni journalisé **par la calibration** ; le journal général du cerveau, lui, porte les tours de calibration comme tous les autres tours.

**Question pour l'Humain.** Faut-il une rétention particulière pour les tours du cerveau pendant une séance de calibration (masquer `agent.input` et les résultats `calibration_*` dans la trace, ou les effacer à la fin de la séance), ou la règle générale du journal (tout tour y est) suffit-elle ? Le contenu est scalaire (aucune image, aucun point de main), mais les phrases de ressenti sont des paroles de l'utilisateur.

**Pas de correction dans la Slice 06** : le journal général appartient au cerveau et à ses tests ; le changer ici toucherait toutes les conversations.
