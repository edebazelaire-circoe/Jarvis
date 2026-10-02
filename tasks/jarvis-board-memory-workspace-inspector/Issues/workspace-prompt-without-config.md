# Le bloc de prompt « Boards et mémoire » est annoncé même sans son `--mcp-config`

Découvert pendant la QA de la Slice 06 (2026-10-03), hors périmètre : motif antérieur à la tâche.

## Constat

- `jarvis/runtime/prompt_catalog.py:~273-277` compose toujours les blocs
  `backend.claude.conversation.settings`, `.capture` et `.workspace` dans le
  prompt système du cerveau (`--append-system-prompt`), sans condition.
- L'écriture de leur `--mcp-config` peut échouer (`OSError`) :
  `claude_local._workspace_mcp_args` (`jarvis/runtime/claude_local.py:~1181-1203`)
  journalise alors `agent.workspace_mcp_failed` (erreur, code
  `workspace_mcp_config_write_failed`) et démarre le cerveau **sans** le serveur
  `jarvis-workspace`. Même chose pour la console (`console_mcp_config_write_failed`)
  et la capture.
- Résultat : le prompt parle au cerveau d'outils (`board_inspect`,
  `board_memory_*`…) qu'il n'a pas. Il peut les chercher (`ToolSearch`) en vain,
  ou dire à l'utilisateur qu'il va les utiliser.
- Seule la passerelle `jarvis-tools` fait déjà bien : son bloc
  (`backend.conversation.tools`) n'est ajouté que si son `--mcp-config` a été écrit.

## Correctif proposé

Composer les blocs de prompt à partir des configurations **effectivement
écrites** : `_workspace_mcp_args` (et ses jumeaux console / capture) renvoie si
le fichier existe, et `prompt_catalog` n'ajoute le bloc correspondant que dans
ce cas, comme pour `tools`. Test : une écriture de config qui échoue → ni
`--mcp-config` ni bloc de prompt pour ce serveur, ligne `agent.*_mcp_failed`
présente.

## Note annexe (QA live)

Dans les runs isolés de la QA (Core 18995 / Control Center 18996, données
scratch), le CLI Claude du cerveau charge aussi les serveurs MCP **de
l'utilisateur** (`jarvis-drive`, `claude-in-chrome`) depuis sa configuration
personnelle : un run « isolé » n'est donc pas isolé côté outils annoncés au
modèle (contexte, tentation d'appels). À garder en tête pour mesurer un budget
de contexte ou un chemin d'outils ; piste : `--strict-mcp-config` pour les runs
de QA.
