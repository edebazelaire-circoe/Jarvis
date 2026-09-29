# Créer une nouvelle session de conversation à la voix

- Date : 2026-09-28
- Chantier : [tasks/jarvis-board-session-context-runtime/](../tasks/jarvis-board-session-context-runtime/) (Board + Session runtime, V1 livrée le 2026-09-29)
- Statut : réalisé (2026-09-29) par l'outil MCP `session_new` du serveur `jarvis-console` (handoff `jarvis-board-session-context-runtime`, Slice 05, `docs/boards.md` › *MCP tools*) : une nouvelle Session, fil neuf sur le même Board, Boards et tâches intacts ; appliquée à la fin du tour du cerveau. Réponses aux questions ouvertes : « nouvelle session » = une nouvelle Session Jarvis (fil du brain neuf sur le même Board ; la session vocale se relie seule à la nouvelle conversation, `board.voice_binding.changed`) ; l'utilisateur entend une phrase courte (« Nouvelle session à la fin de ta réponse. ») et voit la même action dans le panneau Boards du Control Center (« Nouvelle session »).

## L'idée

Pouvoir demander à JARVIS, à la voix, de créer une nouvelle session de
conversation : repartir d'un fil neuf sans passer par le Control Center.

## Ce qui existe aujourd'hui

- Le cerveau vocal n'a aucun outil ni réglage pour ouvrir une nouvelle session.
- Seul réglage proche : `idle_timeout_s` (« Fermeture après inactivité »,
  `jarvis/runtime/voice_capabilities.py`), qui ferme la session vocale après un
  temps d'inactivité, sans que l'utilisateur puisse le demander.
- Côté Control Center, `POST /api/agent/restart` avec le corps
  `{"new_conversation": true}` redémarre le brain sur une conversation neuve
  (`jarvis/runtime/control_center.py`, `agent_restart`). Il est appelé par
  l'écran de la scène (`jarvis/runtime/control_center_scene_settings.js`), pas
  par la voix.

## Pistes

- Exposer ce redémarrage « conversation neuve » comme un outil du cerveau vocal
  (ou du serveur MCP `jarvis-console`), pour qu'une demande orale y mène.
- À préciser : ce que « nouvelle session » veut dire pour l'utilisateur (fil du
  brain neuf, session vocale neuve, ou les deux), et ce qu'il doit entendre ou
  voir pour savoir que c'est fait.
