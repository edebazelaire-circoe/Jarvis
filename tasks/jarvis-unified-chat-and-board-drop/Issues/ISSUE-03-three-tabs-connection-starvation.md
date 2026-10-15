# ISSUE-03 — Trois onglets Control Center saturent les connexions du navigateur (préexistant)

- **Constat (reprise S6, 2026-10-15, `ab88ab9c`) :** chaque page du Control Center tient deux longues attentes de 25 s (`/api/fullscreen/commands`, `/api/presentation-studio/explorer/commands`). Chrome partage 6 connexions HTTP/1.1 par origine entre tous les onglets : trois pages suffisent à les occuper. `/api/status` ≈ 8,3 s Chat ouvert, 8,6 s Chat fermé (2 onglets Chat + chronologie) ; > 9 s avec 3 onglets, Chat ouvert ou fermé.
- **Pas causé par cette tâche :** le Chat ne tient plus aucune connexion en attente (décision S6) ; la saturation existe Chat fermé. À 2 onglets, tout répond en < 25 ms.
- **Piste :** une seule longue attente par page multiplexant les commandes (ou un SSE / WebSocket unique), ou des lectures courtes comme le Chat ; HTTP/2 sur le loopback lèverait la limite des 6 connexions.
- **Disposition :** hors périmètre (non bloquant pour cette tâche, non régressif). Signalé à l'Humain à la clôture.
