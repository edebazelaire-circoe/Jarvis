# Fermeture `core_restart` au démarrage de Core — compatibilité

**Introduit :** tâche `jarvis-session-context-recording-runtime`, Slice 01
(2026-10-01). Contrat : `jarvis/domain/workspace_board.py`
(`SessionEndReason`, `close_session`, `legacy_close_on_core_restart`) et
`docs/boards.md`, *Lifecycle*.

## Ce qui reste accepté

1. **Décoder `end_reason = "core_restart"`.** Les Sessions closes par un
   démarrage de Core avant D02 restent lisibles telles quelles
   (`JarvisSession.from_payload`, lignes `jarvis_sessions`). Elles ne sont
   jamais réécrites : un redémarrage passé a bien clos ces Sessions.
2. **Produire `core_restart`, par un seul chemin.** `close_session` et
   `close_session_with_bindings` refusent désormais toute raison autre que
   `new_session` (`invalid_session`). Seule la fonction
   `legacy_close_on_core_restart` la produit encore, et son seul appelant est
   `SessionManager._open_at_start`, pour que le démarrage actuel reste
   inchangé tant que la reprise n'est pas livrée. Test :
   `tests/unit/test_workspace_board_contract.py::test_only_the_legacy_start_path_still_produces_core_restart`.

## Pourquoi

D02 : une Session ne se ferme que sur une nouvelle Session explicite ; un
redémarrage la reprend. La Slice 01 fixe ce contrat dans le domaine, mais la
reprise au démarrage (D-SESS : mêmes `jarvis_session_id`, Board actif et
conversation, bindings réconciliés) est la Slice 03. Entre les deux, le
démarrage garde l'ancien comportement par ce chemin nommé, au lieu d'un
paramètre qui laisserait n'importe quel appelant produire `core_restart`.

## Condition de retrait

Slice 03 de `jarvis-session-context-recording-runtime` : `_open_at_start`
reprend la Session ouverte. Supprimer alors `legacy_close_on_core_restart`,
son test, cette fiche et l'appel dans `session_manager.py`. Garder
`SessionEndReason.CORE_RESTART` : il décode l'historique.
