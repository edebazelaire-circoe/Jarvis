# Jarvis V1 - Implementation handoff

Ce dossier transforme l'audit du projet `jaredrhod/fullstack-agent` en plan d'implementation pour une **V1 experimentale d'assistant personnel Jarvis**.

La V1 n'est pas un fork aveugle de `fullstack-agent`. Elle conserve les parties utiles du projet amont, mais place un noyau Jarvis propre entre les interfaces et le modele d'IA.

## Objectif de la V1

Valider en conditions reelles qu'un assistant local peut :

1. recevoir une demande en push-to-talk ;
2. transcrire l'audio via un backend OpenAI configurable ;
3. envoyer le texte a un `AgentBackend` interchangeable ;
4. repondre oralement avec une latence acceptable ;
5. publier son etat a une interface visuelle ;
6. manipuler un petit board a la main via `barehands` ;
7. lire/ecrire une memoire locale simple et auditable ;
8. demander une confirmation avant toute action modifiant des donnees.

## Lecture recommandee

1. `tasks/TODO.md` - point d'entree d'implementation.
2. `docs/00-overview.md` - scope et mental model.
3. `docs/02-architecture-spec.md` - architecture cible V1.
4. `docs/05-security-threat-model.md` - contraintes de securite.
5. `docs/06-upstream-integration-map.md` - quoi reprendre des projets Jared Rhod.
6. `tasks/00-orchestrator/TASK.md` - premier task obligatoire.

## Regle centrale

**Ne pas construire Jarvis sur `fullstack-agent`.** Construire un noyau Jarvis modulaire et brancher les composants utiles autour de lui.

Les composants amont servent de reference et/ou de composants externes :

- https://github.com/jaredrhod/fullstack-agent
- https://github.com/jaredrhod/backtalk
- https://github.com/jaredrhod/barehands
- https://github.com/jaredrhod/ai-visualizer
- https://github.com/jaredrhod/ai-memory-vault

## Etat

Ce handoff decrit une V1 de test. Aucun choix de modele OpenAI precis n'est grave dans le code : les noms de modeles de transcription, de raisonnement et de TTS doivent etre configurables et verifies contre la documentation OpenAI au moment de l'implementation.
