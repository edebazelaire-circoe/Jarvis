# Grill session - reconstructed

> This is a reconstructed grill session based on available conversation context.

## 1. Intention utilisateur

L'objectif est de creer un assistant personnel de type **Jarvis**, utilisable :

- en vocal ;
- visuellement avec une camera ;
- avec les mains comme modalite d'interaction ;
- avec une architecture suffisamment serieuse pour ne pas etre seulement une demo de dix minutes.

Le projet `jaredrhod/fullstack-agent` a ete identifie comme reference potentielle. La question etait de savoir s'il apportait de vraies briques techniques, s'il etait securise, portable vers d'autres projets d'IA, et s'il valait mieux l'adopter que repartir de zero.

## 2. Conclusions de l'audit

### fullstack-agent

Decision : **ne pas en faire le socle du produit**.

Raison : le depot principal est surtout un wizard/orchestrateur Claude Code qui installe et relie quatre depots. Il apporte une tres bonne experience d'installation, mais peu de logique technique propre.

### backtalk

Decision : **garder les idees et certains patterns, mais ne pas adopter son `brain.py` comme coeur de Jarvis**.

Points juges pertinents :

- capture audio ;
- push-to-talk ;
- VAD ;
- gestion de peripheriques audio ;
- interruption/barge-in ;
- streaming phrase par phrase ;
- publication d'etats voix ;
- mecanisme d'approbation vocale.

Limite : le coeur est fortement couple au Claude Agent SDK et a Claude Code.

### barehands

Decision : **brique amont la plus interessante a integrer comme composant externe**.

Valeur : MediaPipe + interactions gestuelles + board pilotable par commandes locales. L'interface avec le cerveau est simple et portable.

Important : Barehands ne donne pas de vraie vision au LLM. Il reconnait essentiellement les mains/gestes. La comprehension de scene par modele multimodal est hors V1.

### ai-visualizer

Decision : **reutiliser l'idee et si possible le composant quasiment tel quel**.

Le bus de signaux par petits fichiers locaux est simple et suffisant pour une V1. Il pourra etre remplace par WebSocket/event bus plus tard.

### ai-memory-vault

Decision : **s'inspirer de l'approche Markdown/Obsidian, sans le considerer comme un moteur de memoire complet**.

La V1 doit garder une source de verite lisible et locale, avec un index simple pour retrouver les bonnes informations.

## 3. Securite

Decisions verrouillees :

- tous les services V1 ecoutent sur `127.0.0.1` uniquement ;
- aucun JavaScript tiers n'est charge dynamiquement depuis un CDN dans la version retenue ;
- la cle OpenAI reste exclusivement cote backend ;
- la V1 ne donne pas un Bash general au modele ;
- toute action modifiant des donnees passe par un `ActionBroker` ;
- le push-to-talk est le seul mode vocal active dans la V1 ;
- le contenu des transcriptions ne doit pas etre logge par defaut ;
- les commandes Barehands localhost doivent etre protegees par un token de session ;
- les sources amont doivent etre pincees a un commit avant integration ;
- les implications AGPL doivent etre preservees et documentees.

## 4. Architecture souhaitee

Un noyau Jarvis est introduit avec des interfaces explicites :

- `TranscriptionBackend`
- `AgentBackend`
- `TTSBackend`
- `MemoryBackend`
- `ActionBroker`
- `StatePublisher`
- `GestureBridge`

La V1 doit pouvoir changer de fournisseur IA sans reecrire l'audio, l'interface, la memoire ou les gestes.

## 5. OpenAI transcription

Decision : utiliser un backend de transcription OpenAI en premiere implementation, mais rendre le modele configurable.

Le flux attendu :

`micro -> capture PCM/WAV -> OpenAITranscriptionBackend -> texte -> AgentBackend`

Un backend local type Whisper peut etre garde comme fallback ulterieur ou optionnel.

## 6. Scope V1

A prouver :

- conversation push-to-talk ;
- sortie vocale ;
- etats idle/listening/thinking/speaking ;
- board Barehands ;
- memoire locale simple ;
- actions locales restreintes et confirmees ;
- lancement en une commande ;
- tests de bout en bout.

Hors V1 :

- microphone toujours ouvert ;
- wake word ;
- speaker recognition ;
- vision generale de la scene ;
- email/calendar/browser automation ;
- execution shell generale ;
- controle domotique ;
- application mobile ;
- multi-utilisateur ;
- cloud deployment.

## 7. Question non resolue

Le moteur de synthese vocale final n'est pas verrouille. La V1 doit donc definir `TTSBackend` et permettre au premier implementateur de choisir le chemin le plus rapide et stable (local ou API), sans coupler le reste du systeme a ce choix.
