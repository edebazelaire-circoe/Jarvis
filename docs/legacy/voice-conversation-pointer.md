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
`current_session`, ou 404 `http_error` (route absente) / `session_not_found`
(`voice.session.unsupported`, avertissement) ; `binding_not_found` est levé.

**Pourquoi.** Voice et Core sont deux processus mis à jour séparément ; une
Voice neuve face à un Core ancien doit garder sa conversation.

**Condition de retrait.** Quand plus aucun Core sans `/v1/sessions/current`
ne peut tourner avec cette Voice (Slice 08, bascule complète) : supprimer le
repli dans `voice_v2.py`, puis l'écriture du pointeur et
`VoiceSwitchBus.conversation_id()` si le relais de switch n'en a plus besoin.

## Reste n° 2 — `agent_cli="pending"` et `/api/agent/restart` (réduit en Slice 04a)

**Ce qui reste.** Une liaison porte `agent_cli="pending"`
(`session_manager.PENDING_AGENT_CLI`) tant que le Control Center ne l'a pas
rapportée (`POST /v1/sessions/bindings/report`) : liaison jamais activée
(Board visité paresseusement), ou Control Center absent. Et le Control Center
garde le comportement historique de `POST /api/agent/restart
{"new_conversation": true}` (CLI unique redémarré sans reprise, aucune Session)
quand Core n'a pas de Sessions (404 texte) ou refuse `POST /v1/sessions/new`
(`agent.restart.session_unavailable`, warning ; info si Core est antérieur).

**Pourquoi.** Même raison que le reste n° 1 : Control Center et Core peuvent
tourner dans deux versions différentes.

**Condition de retrait.** Slice 08 (bascule complète) : supprimer le repli
de `ControlCenter.agent_restart` et `is_unsupported` dans
`jarvis/runtime/core_sessions.py` ; `pending` ne subsiste alors que pour une
liaison jamais activée.

## Reste n° 3 — préférence globale du mode d'interaction (Control Center) : **retiré**

**Retiré par la Slice 01b de `jarvis-board-ui-wheel-dossier-refactor`.** Le
mode suit le type du Board actif ; le rejeu (`startup`, `core_restart`,
`save_retry`), `_reconcile_interaction_mode` et le module
`interaction_mode_settings.py` sont supprimés, et `POST /api/interaction-mode`
refuse tout choix (`interaction_mode_derived`). La clé `interaction_mode` d'un
ancien `control-center-settings.json` reste dans le fichier (pas de nettoyage
destructif d'un fichier de l'utilisateur), ni lue ni écrite. Un Core sans
Boards garde son mode par défaut (assistant) : plus rien ne le lui rejoue.
