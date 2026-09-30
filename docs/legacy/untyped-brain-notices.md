# Relais spontanés sans genre — compatibilité

**Introduit :** tâche `jarvis-voice-stale-speech-presentation`, Slice 03
(2026-09-28). Contrat : `jarvis/domain/brain_notice.py` et
`docs/conversation-events.md`, « Spontaneous notices ».

## Ce qui reste accepté

1. **Une notice sans `kind`** servie par `/api/agent/notices` (Control Center
   d'avant la Slice 03, qui sert `{seq, text, ts_ms, origin}`) : `next_notices`
   la transmet sans genre, `announce_notice` en fait un `result`, et elle est
   dite comme avant. Test : `tests/unit/test_brain_notice_contract.py::test_an_old_format_notice_from_the_control_center_is_still_spoken_as_a_result`,
   `tests/unit/test_brain_delegation.py::test_the_brain_backend_follows_the_notice_cursor`.
2. **Un backend dont `next_notices()` rend de simples textes** : la boucle
   `JarvisCoreApplication._brain_notice_loop` les dit en `result`. Test :
   `tests/unit/test_brain_delegation.py::test_core_speaks_the_relay_as_soon_as_the_backend_hands_it_over`.

Seule l'**absence** de genre est tolérée : un genre présent mais hors contrat
est refusé et tracé (`agent.notice_refused`, `core.brain.notice_dropped`
`reason=invalid_notice`).

## Pourquoi

Core et le Control Center sont deux processus redémarrés séparément : pendant
une mise à jour, un Core neuf peut lire un Control Center ancien. Refuser ses
notices rendrait muets les relais de fin de sous-agent.

## Condition de retrait

Quand aucun Control Center ne sert plus de notice sans `kind` (tous les
déploiements ont la Slice 03) et qu'aucun backend ne rend de textes nus (seul
`ControlCenterBrainBackend` implémente `next_notices` aujourd'hui ; les doubles
de test à textes nus sont à convertir) : rendre `kind` obligatoire dans
`NoticeTyping.from_payload` et supprimer la branche `str` de la boucle.
