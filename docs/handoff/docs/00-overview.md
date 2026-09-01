# 00 - Overview

## Goal

Construire une **V1 de Jarvis testable sur un poste local**, assez petite pour etre implementee rapidement mais structuree comme un produit evolutif.

## Mental model

Jarvis n'est pas un modele. Jarvis est une couche d'orchestration locale qui relie :

- les sens : micro et gestes ;
- le cerveau : un `AgentBackend` ;
- la voix : un `TTSBackend` ;
- la memoire : un `MemoryBackend` ;
- les actions : un `ActionBroker` ;
- l'expression visuelle : visualizer + Barehands.

Chaque couche doit pouvoir etre remplacee sans reecrire les autres.

## V1 success criteria

La V1 est consideree comme valide si un utilisateur peut lancer Jarvis, maintenir une touche, poser une question, recevoir une reponse orale, voir l'etat visuel evoluer, puis demander a Jarvis d'afficher une carte sur le board ou d'enregistrer une note, avec confirmation pour l'ecriture.

## In scope

- Python 3.11+ pour le noyau.
- Execution locale desktop.
- Push-to-talk.
- Transcription OpenAI via API backend configurable.
- Un premier `AgentBackend` fonctionnel.
- Un `TTSBackend` fonctionnel.
- Barehands comme board gestuel.
- ai-visualizer ou adaptation directe comme face.
- Memoire locale Markdown + index simple.
- Action broker sans shell general.
- Diagnostics et tests E2E.

## Non-goals

- assistant toujours a l'ecoute ;
- reconnaissance de la personne qui parle ;
- vision multimodale de la camera ;
- automatisation Gmail/Calendar ;
- navigateur autonome ;
- commandes systeme arbitraires ;
- orchestration multi-agent ;
- distribution SaaS.

## UX V1

Etats visibles : `idle`, `listening`, `thinking`, `speaking`, `awaiting_confirmation`, `error`.

Interaction principale :

1. hold key ;
2. parler ;
3. release ;
4. transcription ;
5. reponse ;
6. possibilite d'interrompre la parole en appuyant a nouveau.

Le board Barehands reste une seconde modalite : l'utilisateur peut deplacer et ouvrir les elements avec ses mains, tandis que Jarvis peut y `present` une carte.
