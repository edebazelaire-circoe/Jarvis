# Contexte global : le prompt initial que JARVIS se compose

`<racine de données>/CONTEXT_GLOBAL/` est la mémoire de démarrage du cerveau
Claude. JARVIS l'organise lui-même : il y ajoute, modifie ou supprime des
fichiers, et choisit lesquels forment son prochain prompt initial.

## Où il vit et d'où il vient

- Sous la racine de données du PC ([local-data.md](local-data.md)), jamais dans
  le dépôt : l'agent y écrit librement, git ne doit pas le voir.
- Au premier lancement du cerveau, le dossier est créé depuis le modèle
  versionné `jarvis/context_global_seed/`. Ensuite il n'est plus jamais
  réinitialisé : un fichier que l'agent supprime reste supprimé. Pour repartir
  du modèle, déplacer le dossier ailleurs (le copier d'abord) ; il sera recréé.
- Le chemin est remis au CLI par `--add-dir` et dans la variable
  `JARVIS_GLOBAL_CONTEXT_DIR`, héritée par les sous-agents.

## `base_context.yaml`

La liste ordonnée des fichiers assemblés, chemins relatifs au dossier :

```yaml
- base_instruction.md
- personnality.md
- mission.md
- user_habits.md
- memory_summary.md
```

Seule cette forme est lue (une clé `files:` en tête est tolérée, commentaires
`#` permis) ; tout autre YAML est refusé et signalé, pas deviné. Une entrée
absente, hors du dossier (`..`, chemin absolu) ou qui n'est pas un fichier
texte (`.md`, `.txt`, `.yaml`) est ignorée et signalée.

## Assemblage

À chaque lancement du CLI du cerveau (`ClaudeLocalAgent.start`, profil
`conversation`), le manifeste est relu et chaque fichier ajouté sous un titre
`# <chemin>`. Le bloc est la couche `backend.claude.conversation.global_context`
de la consigne système, après les capacités (réglages, captures, écran, mains)
et avant l'ajout libre de l'utilisateur. Il commence par des règles fixes, dans
le code (`GLOBAL_CONTEXT_RULES`) : le chemin du dossier, le sens du manifeste,
et le fait qu'elles priment sur le contenu du dossier. Ainsi l'agent ne peut pas
effacer, en réécrivant ses fichiers, la façon de les retrouver.

- Le texte assemblé est plafonné à 12 000 caractères
  (`MAX_ASSEMBLED_CHARS`) : la consigne passe en argument du CLI, et la ligne
  de commande Windows plafonne à 32 767 caractères, dont ~16 000 déjà pris par
  le socle. Au-delà, le texte est coupé et l'agent en est averti.
- Les problèmes (entrée absente, manifeste illisible, plafond) sont écrits dans
  la consigne, pour que l'agent les corrige, et dans le journal
  (`agent.global_context`).
- Le CLI fige la consigne système d'une conversation : un changement du dossier
  s'applique au prochain démarrage de JARVIS, pas à la conversation reprise.

## Ce qui n'est pas chargé

Le reste du dossier se lit à la demande : `current_task/` (une tâche en cours
par fichier), `todo.md`, `pense_bete.md`, `captures/`, et tout ce que l'agent
juge utile d'y ranger.
