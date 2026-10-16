# Jarvis — Mode Chat unifié et dépôt rapide sur Board

**Projet :** Jarvis · **Priorité produit :** P0 (chat) ; extra embarqué (drop sur Board) · **Statut initial :** planifié, rien n'est implémenté par ce dossier.

**Entrée d'exécution :** `slices/TODO.md`, puis `slices/00-project-manager/SLICE.md`.

**Source :** échange utilisateur des 13–14 octobre 2026, reconstitution fidèle dans `grill-session.md`, et inspection statique du dépôt https://github.com/edebazelaire-circoe/Jarvis à `main` / `664d767bf33e9690b67b2c12e0fd9b8cb894923a` le 14-10-2026. Les chemins de code sont des points de départ à revalider, jamais des ordres aveugles.

## Résultat attendu

Un onglet **Chat** en bas à droite ouvre un panneau latéral déployé horizontalement. Il montre la même conversation que la voix, mais **uniquement les demandes utilisateur effectivement acceptées et les messages publiés par le Brain**. Il ne duplique ni l'historique ni les logs : c'est une projection filtrée de la source canonique des événements. Le chat reste utilisable **sans aucun runtime vocal**. L'écriture y est désactivée quand le vocal est actif, avec une explication accessible et une action explicite **Passer au chat** qui désactive le canal vocal sans fermer la Session, le Brain ni ses travaux. Les réponses textuelles reviennent par la voie Brain, pas par TTS.

Le chat accepte plusieurs fichiers par sélection ou glisser-déposer pour les transmettre au Brain. En extra distinct mais inclus dans cette tâche, le **Board** accepte fichiers, images et URL déposés pour les associer à son espace documentaire/Artifacts sans les confondre avec un message de chat.

## Règles de réalisation

- Pas de deuxième Brain, deuxième agent, transcript, stockage de conversation ou pipeline de sous-agents.
- La vérité de conversation est `docs/conversation-events.md` : notamment `user.transcript.accepted` et `brain.message.published`, avec ordre par séquence, identité et filtres d'autorisation. Les journaux de débogage sont des preuves corrélées, **pas** une source alternative pour le chat.
- Les bindings réels sont `(jarvis_session_id, board_id) -> conversation_id + agent_session_id` (voir `docs/boards.md`), pas un Brain global unique. Changer de canal ne change pas de binding.
- Respecter les migrations/versionnements de `CLAUDE.md` et les données hors dépôt de `docs/local-data.md`. Ne jamais démarrer, redémarrer, arrêter ou toucher au Jarvis vivant sans accord explicite ; tests en instance isolée.
- Un clic d'envoi pendant une transition de mode doit être refusé côté serveur si la voix est toujours active. La grisure du champ seule ne protège pas la règle.
- Une pièce jointe du chat n'est pas automatiquement un dépôt sur Board ; l'action Board est distincte.

## Orchestration et vérification

Le Project Manager **exécute lui-même** Slice 00 (audit aveugle avant de lire nos conclusions ; réconciliation ; état `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT` ou `HUMAN_DECISION_REQUIRED`). Aucune délégation d'implémentation tant que l'état n'est pas `READY`. Avant chaque envoi de Slice, refaire une vérification de fraîcheur de HEAD/contrats, conflits de branches, tâches voisines et vocabulaire Workspace Task Type. Il peut réviser et subdiviser la planification, jamais éditer lui-même le code produit.

**QA obligatoire :** toute Slice implémentée reçoit `qa-verification` ; tout code reçoit `code-review` ; tout comportement runtime/UI reçoit `runtime-validation` ; toute modification de prompts, outils, routage, modules ou runtime d'agent reçoit `agent-trace-analysis` sur de vraies traces. Les agents QA fournissent preuves et findings, le PM arbitre. Une régression introduite par la Slice bloque son approbation et ne peut être garée dans `Issues/`. Les tests machines sont menés au maximum avant toute validation humaine. Chaque Slice de code requiert `/caveman` et `/coding-guideline`; toute Slice frontend requiert en plus `/impeccable` et un agent Claude si le host prend en charge cette règle.

**Décisions et inconnues :** `docs/01-decision-log.md`. **Architecture :** `docs/02-architecture.md`. **Risques/validation :** `docs/04-testing-and-quality.md`. **Dépendances :** `slices/TODO.md`.
