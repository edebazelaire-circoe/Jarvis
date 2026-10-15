# 01 — Journal des décisions et points ouverts

## Décisions produit confirmées par l'utilisateur (13–14 octobre 2026)

- **D01. Deux interfaces, un seul circuit Brain.** Chat et voix rejoignent le Brain existant ; Brain, tâches, sous-agents et contexte persistent indépendamment du vocal.
- **D02. Chat = projection simple du transcript.** Uniquement les tours utilisateur acceptés et les messages Brain publiés ; ni réflexes, Mouth, outils, sous-agents, pensée, détails d'exécution. Le transcript/debug approfondi reste accessible séparément.
- **D03. Pas de double stockage d'historique.** L'information déjà conservée est réutilisée ; créer le moins possible de nouvelles tables. Le niveau source doit être vérifié dans le dépôt (événements canoniques versus traces diagnostiques).
- **D04. État vocal exclusif pour la saisie.** La fenêtre Chat peut être ouverte avec Voice actif, mais la saisie est grisée et un clic affiche pourquoi elle est indisponible. Voice désactivé -> chat opérationnel ; passer à l'écrit entraîne l'arrêt explicite de Voice, pas du Brain.
- **D05. Documents dans le chat.** Sélection et glisser-déposer, sans plafonds arbitraires proposés par l'utilisateur.
- **D06. Extra Board.** Drop de fichiers/images/URL dans la scène du Board pour en faire de la documentation/ressource, **dans le même dossier d'implémentation**, mais comme tranche séparée.
- **D07. Priorité.** Le chat est à réaliser dès que possible, l'extra Board ne doit pas masquer ni retarder le chemin critique.

## Constats de dépôt : vérifiés statiquement, non décisions utilisateur

- `docs/conversation-events.md` L3 : source canonique append-only `ConversationEventStore`, types publics `user.transcript.accepted`, `brain.message.published`. `RuntimeJournal` est diagnostic ; `trace_ref` relie les deux. Les projections, exports et timeline existent déjà.
- `docs/boards.md` L3 et `docs/session-context.md` L3 : la Session survit aux redémarrages ; le binding Session+Board possède la conversation Core et le CLI Brain ; aucun switch ne doit annuler le travail.
- `docs/artifacts.md` L3 : Artifact Registry, relations Board et payload sûr. `docs/local-data.md` et `CLAUDE.md` imposent le stockage hors git et les migrations versionnées.
- `docs/interaction-mode.md` : `InteractionMode` (SIMPLE/PRESENTATION/REUNION) est **autre chose** que le canal vocal/chat et que l'architecture Voice. Ne pas détourner cet enum.

## Inconnues à résoudre par Slice 00/01 sans bloquer l'écriture du dossier

- Quelle route Core accepte déjà un tour texte avec source dédiée et admission idempotente ; faut-il étendre `BrainTurnSource` ou réutiliser le format avec une source explicite ? **Ne pas réutiliser clandestinement une route dépendant d'un runtime vocal.**
- Quel est l'état vocal canonique accessible au Control Center (start/stop/active/transition) et son propriétaire ; garantir une bascule serveur cohérente sur course clic/désactivation.
- Quelles pièces jointes le Brain local lit déjà (fichiers, images, PDF, URL) et comment un Artifact est rendu accessible au contexte du binding sans le copier dans les prompts ni rompre les chemins sécurisés.
- Comment les événements Brain couvrent les messages édités/republifiés ou un événement perdu ; définir la politique d'affichage et de rattrapage sans inventer des réponses.
- Quel est le vocabulaire **Workspace Task Type** actuel. Non exposé dans cette session : `metadata.json` conserve `task_type:null`, Slice 00 doit résoudre avant distribution.
- Utilisation réelle des routes et fichiers à `main` frais, conflits avec les autres chantiers en cours (Studio/Boards/Wake Word) : audit de fraîcheur obligatoire.

## Choix d'implémentation proposés (non verrouillés tant que Slice 01 ne les valide pas)

- Rendre « Passer au chat » comme action explicite, plutôt qu'un envoi qui coupe Voice sans confirmation.
- Ordre d'affichage par séquence `ConversationEventStore` avec IDs de source ; UI rehydratée à chaque (re)connexion, progression par événements publiés ; si aucun token stream n'existe, afficher état d'attente puis message entier sans inventer de streaming.
- Conserver des bornes serveur configurables, adaptées aux capacités de stockage et à la sécurité, sans limites produit gratuites ; erreurs claires et pas d'upload invisible.
- URL drop comme **référence** vérifiée, jamais fetch réseau implicite. Si un Artifact kind est manquant, faire évoluer le contrat par migration/test au lieu de forcer un type mensonger.
