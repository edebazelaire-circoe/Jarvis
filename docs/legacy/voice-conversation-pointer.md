# Pointeur `.voice_conversation` — cache et repli face à un Core sans Sessions

**Introduit :** tâche `jarvis-board-session-context-runtime`, Slice 03.
**Contrat :** [boards.md › Sessions](../boards.md#sessions).

## Ce qui a changé

La conversation de Voice est celle de la liaison du Board actif dans la
Session Core ouverte (`GET /v1/sessions/current`, relue à chaque activation
par `PersistentVoiceRuntime._session_conversation_id`). Le pointeur
`runtime/.voice_conversation` (`VoiceSwitchBus.remember_conversation`) et
l'identifiant porté par le relais d'un switch de voix (`jarvis/app.py`,
`initial_conversation_id`) ne décident plus rien quand Core a des Sessions.

## Reste n° 1 — le pointeur est encore écrit et relu

**Ce que c'est.** Voice écrit toujours le pointeur après chaque activation ;
elle le relit, avec l'ancien chemin (conversation inconnue → 404 → conversation
neuve), seulement si Core ne prend pas les Sessions en charge : client sans
`current_session`, ou 404 (`voice.session.unsupported`, avertissement).

**Pourquoi.** Voice et Core sont deux processus mis à jour séparément ; une
Voice neuve face à un Core ancien doit garder sa conversation.

**Condition de retrait.** Quand plus aucun Core sans `/v1/sessions/current`
ne peut tourner avec cette Voice (Slice 08, bascule complète) : supprimer le
repli dans `voice_v2.py`, puis l'écriture du pointeur et
`VoiceSwitchBus.conversation_id()` si le relais de switch n'en a plus besoin.

## Reste n° 2 — `agent_cli="pending"` et `/api/agent/restart`

**Ce que c'est.** Core ne sait pas quel CLI le Control Center fait tourner : les
liaisons portent `agent_cli="pending"` (`session_manager.PENDING_AGENT_CLI`).
`POST /api/agent/restart {"new_conversation": true}` redémarre toujours le CLI
unique sans ouvrir de Session, et `POST /v1/sessions/new` ouvre une Session sans
redémarrer le CLI.

**Condition de retrait.** Slice 04a : le pool rapporte le CLI à l'activation
(la valeur `pending` disparaît des liaisons actives) et `new_conversation` est
réorienté vers `start_new_session`.
