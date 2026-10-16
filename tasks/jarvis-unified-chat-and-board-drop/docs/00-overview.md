# 00 — Objectifs et frontières

## Produit

Jarvis dispose aujourd'hui d'une conversation vocale avec Brain persistant, Board/Session, timeline/debug, et sous-agents. Ajouter **Chat** comme canal de saisie/lecture autonome, pas un assistant concurrent. Le chat projette une conversation existante, y envoie ses propres tours, et affiche exclusivement la réponse du Brain, sans exposer l'orchestration interne.

### Inclus, priorité P0

- Onglet fixe en bas à droite ; panneau latéral réutilisant langage visuel et comportement des menus ; ouverture/fermeture sans effet sur le moteur.
- Historique reconstruit de `user.transcript.accepted` + `brain.message.published`, depuis la **conversation active du binding Session/Board**, avec rechargement et mises à jour temps réel raisonnables ; lien optionnel vers l'outil transcript/debug existant.
- Saisie multiligne ; envoi explicitement au Brain via Core, avec mêmes permissions, tâches, délégations, mémoire/contextes que les tours vocaux ; affichage d'erreur et état d'attente sans exiger TTS.
- Mode vocal actif : historique lisible et actualisé ; formulaire verrouillé, aide « Désactivez le vocal pour écrire », bascule **Passer au chat** ; bascule atomique/verrouillée avec confirmation effective de l'arrêt vocal avant autorisation d'écrire. Aucun arrêt Brain/sous-agents/Session.
- Envoi de pièces jointes multiples par bouton et drop ; validation réelle et messages d'état ; mise à disposition autorisée pour le Brain via mécanismes d'Artifact/Context existants si adaptés.

### Extra dans cette tâche

- Déposer un fichier, une image ou une URL **sur le Board/zone de scène** pour y ajouter une ressource réutilisable, affichée et liée au Board courant. C'est une entrée documentaire, **pas** un tour de chat et **pas** une instruction automatique au Brain.

### Non-objectifs

- Remplacer la timeline détaillée, résumer les sous-agents dans le chat, exposer prompts/traces/tool calls ou réflexes, inventer un stockage conversationnel bis.
- Modifier architecture vocale, implémenter wake word, refondre la scène/Studio/Remotion ou reconstruire l'éditeur de mémoire.
- Récupérer/fetcher automatiquement les URL distantes, gérer une bibliothèque de fichiers cloud, inventer un multimodal Brain sans support attesté.
- Fixer arbitrairement des quotas/champs MIME ; les contraintes de sécurité existantes restent obligatoires.

## Premier parcours d'acceptation

Une demande vocale lance plusieurs sous-agents. Le chat ouvert montre demande acceptée et messages Brain sans activités internes. « Passer au chat » coupe Voice mais préserve binding/Session/travaux. Un texte envoyé au Brain demande l'avancement ; la réponse s'affiche dans le chat, sans synthèse audio. L'utilisateur glisse un document, continue la discussion, revient demain dans la même Session. Extra : il dépose un PDF, une image et une URL sur le Board, qui y deviennent des ressources visibles et liées au Board.
