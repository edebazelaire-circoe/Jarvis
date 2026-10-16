# 04 — Tests, sécurité, QA et validation humaine

## Machine gates sans exception

- Chaque Slice implémentée : `qa-verification` indépendant avec preuve, incluant cas négatifs.
- Slice code : `code-review`. Slice modifiant interface, état ou transport : `runtime-validation` sur Core/Control Center isolés, capture d'écran si frontend. Changement de prompts, agent backend, routage, outils ou runtime d'agent : `agent-trace-analysis` sur traces **réelles** et non exemples imaginés.
- QA apporte résultats ; PM choisit acceptation, rework, nouvelle Slice, Issue pour découverte hors scope ou escalade. Régression causée par la Slice = **bloquant**, pas Issue reportée.
- Validation humaine après maximum de tests automatisés, jamais à la place. Aucun agent ne démarre, redémarre ni arrête le Jarvis vivant sans accord explicite (`CLAUDE.md`).

## Matrice de tests

| Famille | Prouver |
| --- | --- |
| Projection | En l'absence de contenu, vide ; user+Brain uniquement ; aucune mouth/reflex/tool/subagent ; séquences exactes ; duplicates/republication ; paginations vides mais curseur avancé ; reconnexion ; événement manquant, old sessions honnêtement vides. |
| Scoping | Session et Board actifs ; switch Board A/B/A restitue A ; aucune fuite B dans A ; rechargement/restart ; permission et filtrage cross-user si multi-user apparait. |
| Brain textuel | Envoi sans process Voice ; même Brain/binding/Context/Work ; idempotence retry ; failure/timeouts ; clarification ; pas de TTS ; pas de réponse inventée ; retour Brain affiché. |
| Transition de canal | Voice actif -> lecture seulement ; clic disabled => explication ; arrêt Voice ACK -> input actif ; arrêt refusé -> input toujours lock ; activation Voice en parallèle d'un submit ; tâches/subagents toujours actifs. |
| UI | Bas droite, z-index et dock existants, clavier/Tab/Enter/Shift+Enter, focus, indicateur chargement, contraste/accessible tooltip, long texte, scroll, fenêtres étroites, scène/Studio ouverts. |
| Fichiers | Sélection et drop multiple, PDF/image/autre type réellement supporté, document vide, fichiers volumineux, erreur explicite, drag d'URL, noms Unicode, path traversal, extension/MIME trompeurs, duplication/retry, fichiers partiels, ACL Board, logs sans contenu. |
| Board extra | Drop fichier/image/URL dans la scène sans activer chat ni créer un turn, ressources persistées et liées au Board actif, inspecteur cohérent, Board switch, absence de fetch réseau d'URL. |
| Recovery | Core coupé/revenu en instance sandbox, événement tardif, long-poll 25s, UI refresh, pas de double envoi ni de travail annulé ; données existantes préservées. |

## Régressions existantes à respecter

`tests/unit/test_conversation_events.py`, `test_conversation_transcript.py`, `test_conversation_event_query_contract.py`, `test_control_center_timeline_js.py`, `test_boards_hud_browser.py`, `test_workspace_manager_browser.py`, `test_board_brains*.py`, `test_board_session_e2e.py`, `test_schema_migrations.py`, suites artifacts/board links et tests HTTP relatifs (à revalider au HEAD). Lancer les commandes précises sur un environnement de test, conserver sha et sorties ; ne pas affirmer avoir exécuté ici.

## Validation humaine demandée

- Vérifier le Chat visuellement avec les menus, la scène et la bannière Live ; fermeture/ouverture et interactions tactiles/souris.
- Tester avec une vraie Session vocale : lancer des sous-agents, ouvrir chat, voir le transcript filtré, passer au texte, relancer une question sans perdre les tâches, revenir en vocal si souhaité.
- Déposer un PDF/image/URL sur Board et confirmer que la ressource est bien visible au bon endroit. 

Ces vérifications sont référencées par des IDs uniques dans `human-validation.json`, et ne sont demandées qu'après machine QA.
