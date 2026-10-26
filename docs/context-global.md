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

## Permanence

`CONTEXT_GLOBAL` est de l'**état canonique permanent** (décision D05 de
Presentation Edition) : ni un cache, ni du runtime. Il vit sous la racine de
données, donc pour un produit installé sous
`%LOCALAPPDATA%\CIRCOE\Jarvis\data\CONTEXT_GLOBAL\`
([local-data.md](local-data.md#produit-installé--localappdatacircoejarvis)),
jamais dans le dossier du programme : une mise à jour, un déplacement ou une
réinstallation du programme le retrouvent tel quel.

- **chargé à chaque démarrage** du cerveau depuis la racine résolue
  (`global_context_root(settings.data_root)`, Control Center), jamais
  ré-ensemencé une fois créé ;
- **jamais effacé** par un nettoyage, une réparation, une purge de cache ou une
  désinstallation. Garde réutilisable : `ensure_not_global_context(chemin)`
  (`jarvis/adapters/global_context.py`, `GlobalContextProtected`, casse
  ignorée). Branchée sur les effaceurs récursifs : `safe_tree.remove_tree`
  (purge des Presentations archivées, prefabs ; refus avant le premier fichier
  effacé), `node_capability_runner._remove_tree` (nettoyage, réparation et
  retrait des capacités locales, rendus et Studio Remotion ; refus en
  descendant) et la purge du cache de compilation Remotion. Tout nouvel
  effaceur récursif d'un dossier de la racine doit l'appeler. Le
  désinstalleur (Slice 06/07) ne retire jamais `data\` ;
- **copié par toute reprise** : en bloc par la reprise de l'ancien `./data`
  (seulement si la cible n'en a pas) et par `adopt_data_root` (vérifié présent
  dans la copie) ; jamais fusionné fichier par fichier
  ([local-data.md](local-data.md#reprise-dun-profil-vers-une-racine-vide)).

Tests : `tests/unit/test_installed_product_root.py` (chargement depuis la
maison du produit et après déplacement du programme, garde, reprises).

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
