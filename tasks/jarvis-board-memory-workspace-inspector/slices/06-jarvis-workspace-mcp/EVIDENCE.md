# Slice 06 — preuves (serveur MCP `jarvis-workspace`)

## Montage réel isolé

Core (`python -m jarvis core`, port 18991) et Control Center
(`python -m jarvis control-center`, port 18992) lancés depuis le worktree
`bbm`, racines `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` dans un dossier de
scratch, visualiseur coupé. Aucune donnée réelle : Boards de test
« Projet Atlas » (A, rendu actif) et « Ancien projet Borée » (B, nature
`meeting`, jamais ouvert, mémoire `summary.md` + `decisions.md` écrite par
l'API `/api/workspace/boards/B/memory/write`, origine `user`). Les tours
passent par Core `POST /v1/conversations/{id}/brain-turns`
(`addressing: "addressed"`, source `text`) — pas par `/api/agent/ask`, qui
contourne l'hydratation de Core. Cerveau : Claude CLI du Control Center,
profil `conversation`, modèle `claude-sonnet-5-5`. Les deux processus ont été
arrêtés avec leur arbre après le run.

Le CLI démarre avec `jarvis-console` **et** `jarvis-workspace` connectés
(`evidence/mcp-init.json`) : la console n'annonce que `settings_describe`,
`settings_get`, `settings_set` ; `jarvis-workspace` annonce ses vingt outils ;
`runtime/workspace-mcp.json` est écrit à côté des autres `--mcp-config`.

## Tour 1 — cerveau principal : lister, écrire, relire

Consigne : « Fais-le toi-même, sans sous-agent, avec tes outils
jarvis-workspace : liste mes Boards, puis note dans la mémoire du Board
actif, fichier notes/s6.md, la phrase « Décision S6 : serveur workspace
validé, code VEGA-17. », puis relis ce fichier et dis-moi ce qu'il contient. »

| # | Appel | Résultat |
|---|---|---|
| 1 | `ToolSearch select:mcp__jarvis-workspace__board_list,…board_memory_write,…board_memory_read` | trois schémas chargés en un appel |
| 2 | `mcp__jarvis-workspace__board_list {}` | 3 Boards, `board_kind` compris, A actif |
| 3 | `mcp__jarvis-workspace__board_memory_write {board_id: A, path: notes/s6.md, content}` | `created: true`, 55 o, `sha256 da0163…` ; ligne ledger `board.memory.written` seq 5, **`origin: brain`** |
| 4 | `mcp__jarvis-workspace__board_memory_read {board_id: A, path: notes/s6.md}` | le texte exact, `eof: true` |
| 5 | réponse | « Vous avez trois Boards … J'ai créé le fichier notes/s6.md … Il contient exactement : « Décision S6 : serveur workspace validé, code VEGA-17. » » |

Coût 0,168 $, 12,4 s. Aucun appel en trop, aucune erreur, aucun
sous-agent. Détail : `evidence/turn1-main-brain.json`.

## Tour 2 — sous-agent délégué sur l'ancien Board B, sans y aller

Consigne : « Envoie un sous-agent vérifier ce qui a été noté sur l'ancien
Board « Ancien projet Borée », sans y aller : qu'il lise sa mémoire avec les
outils jarvis-workspace et me résume les décisions, avec les codes. »

- Cerveau : un seul appel `Agent` (`[general] Lire mémoire Board Borée`,
  `run_in_background`), consigne avec le `board_id` de B, « Interdit :
  board_switch, et n'écris rien dans ce Board » ; réponse immédiate en une
  phrase.
- **Sous-agent** (même processus CLI, serveurs MCP hérités) :
  `ToolSearch` (4 schémas) → `mcp__jarvis-workspace__board_memory_tree {B,
  depth 4}` → `mcp__jarvis-workspace__board_inspect {B}` →
  `mcp__jarvis-workspace__board_memory_read {B, decisions.md}` →
  `mcp__jarvis-workspace__board_memory_read {B, summary.md}` ; compte rendu :
  NIMBUS / **ORION-42**, report au 15 octobre, lecture complète
  (`eof`, `truncated: false`). Journal du serveur : quatre `board.tool` sur B,
  `core.workspace.read` côté Core, aucun `board.tool_failed`.
- Tour de réveil (notification de fin du sous-agent) : relais oral en
  trois phrases avec le code ORION-42 (`agent.unsolicited_result`,
  `core.brain.notice_relayed`).

Coût du tour 2 avec sous-agent et réveil : 0,158 $ (cumul du processus
0,326 $). Détail : `evidence/turn2-delegated-subagent.json`.

## Premier plan inchangé

Instantanés pris par `/api/sessions/current` et
`/api/workspace/sessions/{id}` avant le tour 2 et après le réveil
(`evidence/state-1-before-delegation.json`,
`evidence/state-2-after-delegation.json`, comparaison
`evidence/foreground-before-after.json`) :

| Fait | Avant | Après |
|---|---|---|
| `active_board_id` | A | A (identique) |
| liaison de premier plan (`board_id`, `conversation_id`, `lifecycle`, `status`, Session) | A, `d331f299…`, `foreground`, `open` | identique |
| autorité de parole | A, `d331f299…` | identique |
| Boards de la Session | `default` (suspended), A (foreground) | identique : B n'est ni visité, ni lié |
| Board B | — | `last_opened_at: null`, `active: false`, aucune Session |

Ledger de la Session (lignes `board.*`) : les deux écritures de la mise en
place (`origin: user`, B) et celle du tour 1 (`origin: brain`, A). La lecture
de B par le sous-agent n'a rien écrit.

## Analyse de la trace (agent-trace-analysis)

- **Chemin conforme** : outils typés de `jarvis-workspace` uniquement, par
  leur nom complet (le prompt `BRAIN_WORKSPACE_PROMPT` les nomme ainsi) ; un
  `ToolSearch` groupé par agent, jamais un nom deviné ; aucun `board_switch`,
  aucun outil fichier, aucune lecture directe du dossier `boards/`.
- **Aucun appel redondant ni erreur** ; pas de reprise.
- **Optimisation possible (non bloquante)** : le sous-agent appelle
  `board_inspect` en plus de l'arbre (redondant pour une simple lecture,
  +1 aller-retour, quelques centaines d'octets) ; un réveil coûte, comme en
  S03, une partie notable du tour 2.
- **Preuve manquante** : les octets exacts des définitions d'outils envoyées à
  l'API ne sont pas capturés ici (mesurés hors ligne, `context_bytes`,
  contrat §10.12).

## Budget de contexte

| Surface | Avant (HEAD 5bc45e4) | Après |
|---|---:|---:|
| `jarvis-console` (outils) | 9 616 o / 12 outils | 2 973 o / 3 outils |
| `jarvis-workspace` (outils) | — | 13 883 o / 20 outils |
| Tous les serveurs natifs déclarés (outils) | 68 583 o | 75 823 o (**+7 240 o**) |
| Consignes serveur console + workspace | 1 326 o | 831 + 874 o (+379 o) |
| Prompt système composé | — | `BRAIN_WORKSPACE_PROMPT` 664 o (+665 o avec le séparateur) |

Gates : `tests/unit/test_mcp_catalog.py` (`WORKSPACE_CONTEXT_BUDGET_BYTES =
14 500`, `CONSOLE_CONTEXT_BUDGET_BYTES = 3 300`,
`DECLARED_CONTEXT_BUDGET_BYTES = 77 000`, consignes 950 / 900 o) et
`test_workspace_mcp.py` (prompt ≤ 700 o).
