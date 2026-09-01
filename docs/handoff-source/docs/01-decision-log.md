# 01 - Decision log

## Locked decisions

### D01 - Ne pas forker fullstack-agent comme coeur

Le depot sert d'inspiration et d'installateur de reference. Le coeur Jarvis est un projet separe.

### D02 - Architecture par adapters

Les interfaces `TranscriptionBackend`, `AgentBackend`, `TTSBackend`, `MemoryBackend`, `StatePublisher` et `ActionBroker` sont des frontieres obligatoires.

### D03 - Barehands integre comme composant externe

Barehands est conserve pour le tracking des mains et le board. Son protocole local est encapsule par `GestureBridge`/`BoardClient`.

### D04 - Visualizer decouple

Le visualizer ne connait pas le LLM. Il consomme uniquement l'etat runtime Jarvis.

### D05 - OpenAI pour la transcription V1

La premiere implementation de `TranscriptionBackend` utilise l'API OpenAI. Le modele exact est une valeur de configuration, jamais une constante metier.

### D06 - Push-to-talk seulement en V1

Le microphone ouvert et le wake word sont reportes. Cela reduit le risque de declenchements involontaires et simplifie le test.

### D07 - Pas de shell general

Le modele ne dispose pas d'un outil `bash`/`powershell` generique. Les actions sont exposees comme commandes metier explicites.

### D08 - Confirmation des ecritures

Une action qui modifie les fichiers/memoire doit passer par `ActionBroker` et obtenir une confirmation utilisateur.

### D09 - Memoire humaine d'abord

Les fichiers Markdown sont la source de verite. Un index local accelere la recherche mais peut toujours etre reconstruit.

### D10 - Dependencies Barehands locales

MediaPipe, Three.js, WASM et modele de hand tracking doivent etre servis localement dans la version integree. Aucun CDN runtime.

### D11 - Localhost strict

Les services ecoutent sur `127.0.0.1`. Les endpoints de commande sont tokenises par session.

### D12 - Logs privacy-first

Les transcripts, prompts et reponses complets ne sont pas logges par defaut.

## Open decisions

### O01 - TTS V1

Choix du moteur a faire au debut de la task TTS : local ou API. Le contrat doit rendre ce choix reversible.

### O02 - Agent model

Le modele de raisonnement initial est configurable. La V1 doit fonctionner avec un backend OpenAI, mais ne doit pas supposer qu'OpenAI restera l'unique cerveau.

### O03 - Fallback STT local

Souhaitable mais pas bloquant pour le premier vertical slice. Peut etre ajoute apres le chemin OpenAI nominal si le temps V1 est contraint.
