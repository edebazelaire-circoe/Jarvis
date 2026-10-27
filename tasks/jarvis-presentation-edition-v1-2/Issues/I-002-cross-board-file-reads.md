# I-002 — Lectures de fichiers entre Boards en édition confinée (reprise QA de la Slice 02)

Statut : **ouvert** ; correction 1 faite par la Slice 03 (voir fin), en attente de QA ; correction 2 non retenue. Pas une régression de la V1.2 :
l'accès existe depuis board-memory-workspace-inspector S03 et la Slice 01 de la V1 Presentation.

## Constat (trace réelle S02, `scratchpad\v12s02\evidence\trace.jsonl`)
Un sous-agent `[general] [research]` du Board A fait `Grep` sur `<data_root>`, puis sur `<data_root>\boards` et
`<data_root>\sessions`. Le premier est refusé par le CLI (« is outside … agent-workdir, …\data\sessions, … ») ; les deux
autres passent : `data\boards` a rendu `boards\<A>\memory\missions\…\mission.md`. Avec un second Board peuplé, il aurait
rendu ses fichiers aussi.

## Cause
1. **`--add-dir` à l'échelle de toutes les données.** Le Control Center accorde au CLI de conversation, pour toute sa
   vie et quel que soit le Board de l'agent du pool :
   - `<data_root>/boards` (`ControlCenter.boards_dir` → `ClaudeLocalAgent.boards_dir` → `_add_dir_args`,
     `jarvis/runtime/control_center.py` `_wire_agent`, `jarvis/runtime/claude_local.py` `_add_dir_args`) : la mémoire de
     **tous** les Boards ;
   - `<data_root>/sessions` et le dossier des Artifacts (`ControlCenter._granted_dirs`) : les Contexts de toutes les
     Sessions, donc de tous les Boards ;
   - `<data_root>/CONTEXT_GLOBAL` ; en édition confinée en plus `<data_root>/local_capabilities` et
     `<runtime>/scene-captures` (`_confined_read_dirs`).
   Les sous-agents lancés par la CLI (outil `Task`/`Agent`) héritent de ces dossiers. `docs/boards.md` › *Folder grant*
   le dit : « une autorisation, pas une frontière de sécurité ».
2. **Le contrat d'inspection permet de lire tout Board.** `docs/boards.md` › *Non-activating inspection* : lire
   n'importe quel Board, Session ou mémoire (courant, autre, archivé) est permis et sans effet ; les outils MCP
   `board_memory_tree|read|search`, `board_inspect`, `dossier_*` prennent un `board_id` explicite et ne refusent pas un
   autre Board. Restreindre seulement les `--add-dir` ne ferait donc **pas** qu'« un sous-agent ne peut plus lire la
   mémoire d'un autre Board » : il le ferait par `board_memory_read(board_id=B)`.

## Pourquoi ce n'est pas corrigé dans la Slice 02
- La preuve demandée (« un sous-agent ne peut plus lire la mémoire d'un autre Board ») exige de changer le contrat
  d'inspection pour l'édition confinée (refus des outils MCP hors Board actif), pas seulement les dossiers accordés : c'est
  une décision produit, et la Slice 03 (« Board boundaries remain strict », recherche dans le Board courant) en dépend.
- Le grant par Board touche le cycle de vie du pool : le foreground démarre sans liaison puis adopte une liaison sans
  relancer la CLI ; un changement de `--add-dir` relance la CLI (`requested_add_dirs`, comparaison du Control Center) ;
  la mémoire d'un Board peut ne pas exister encore (le CLI ignore un `--add-dir` absent) ; `sessions/` est par Session,
  pas par Board. Le faire à la volée dans cette Slice risquait de casser l'hydratation, `presentation_source` (aperçus
  lus par `Read`) et l'Intervieweur.

## Correction proposée (une Slice ou une reprise dédiée, avant ou avec la Slice 03)
1. **Grant par Board en édition confinée** : `ClaudeLocalAgent` reçoit l'id du Board de son entrée de pool (le
   `TrackerWorkObserver` l'a déjà : `lambda: entry.board_id`) ; en `presentation`, `--add-dir` donne
   `<data_root>/boards/<board_id>/memory` (créé avant le lancement par `safe_folders.ensure_folder_tree`) au lieu de
   `<data_root>/boards`, et le dossier de la Session ouverte au lieu de `<data_root>/sessions`. Un agent sans liaison ne
   reçoit aucun dossier de Board ; l'adoption d'une liaison relance la CLI (`--resume`), comme un changement de grant
   aujourd'hui. `full` inchangé.
2. **Refus MCP hors Board actif en édition confinée** : les outils `board_memory_*`, `board_inspect`, `dossier_*`
   refusent un `board_id` autre que celui de l'appelant (code stable, par exemple `board_out_of_scope`), sauf
   `board_list` (titres). Le contrat *Non-activating inspection* garde l'inspection inter-Boards pour `full` et l'UI.
3. **Preuves** : tests du grant (`launched_add_dirs` par Board, A/B/A, adoption), test MCP (refus `board_id` étranger),
   essai réel : un `[research]` du Board A ne trouve rien de B par `Grep` ni par `board_memory_read`.

## Autres constats consignés ici (hors Slice)
- **Origine des écritures des sous-agents** : `core.workspace.mutated` porte `origin: "brain"` aussi pour les écritures
  d'un sous-agent (trace S02, 10:09:41 et 10:10:21 : dossier de mission écrit par l'Intervieweur). Le serveur
  `jarvis-workspace` est partagé par le cerveau et ses sous-agents et pose toujours `origin: brain`. Proposition : un
  vocabulaire `agent` (ou l'id d'agent du hook) pour distinguer l'auteur dans le ledger.
- **Lignes invalides dans `trace.jsonl` après un arrêt forcé** : 1 ligne tronquée dans la trace S02 (ligne 347, journal
  d'un serveur MCP tué en pleine écriture), 3 dans celle de la QA. Les lecteurs (`read_jsonl_tail`, outils de QA)
  doivent ignorer une ligne invalide ; à vérifier pour chaque lecteur, et envisager une écriture par ligne entière
  (`O_APPEND` + une seule écriture) côté journal.

## Décision de l'agent 0 (2026-10-27)
- **Correction 1 (dossiers `--add-dir`) : confiée à la Slice 03.** En édition confinée, les lectures directes de fichiers (Read/Grep/Glob) sont limitées à la mémoire du Board de l'agent et au dossier de la Session ouverte (plus les connaissances globales nécessaires), avec relance ou reconfiguration de la CLI au rattachement à un autre Board. La Slice 03 possède la découverte des sources existantes et doit poser ces frontières.
- **Correction 2 (outils MCP par identifiant) : non retenue.** L'inspection non activante d'un autre Board par son identifiant (`board_memory_*`, `board_inspect`, `dossier_*`) est un geste explicite, tracé et documenté (`docs/boards.md`), utile pour réutiliser la recherche d'un autre projet de l'utilisateur à sa demande. Ce qui est refusé, c'est le balayage implicite de tous les Boards par le système de fichiers. La Slice 03 précise dans la consigne de recherche que la découverte porte sur le Board courant et les connaissances globales, et qu'un autre Board n'est lu que sur demande ou référence explicite.
- `origin: "brain"` des écritures de sous-agents et lignes invalides de `trace.jsonl` : restent ouverts ici, non bloquants.

## Correction 1 faite (Slice 03, agent d'implémentation, 2026-10-27, code `79cf6813`)
- **Grant par Board** en édition confinée : `ClaudeLocalAgent._board_scoped_dirs` remplace `<data_root>/boards`
  par `<data_root>/boards/<board_id>/memory` et `<data_root>/sessions` par `<data_root>/sessions/<jarvis_session_id>`,
  pour le Board et la Session de l'entrée du pool (`board_scope`, posé par `ControlCenter._wire_agent` ;
  `sessions_root` par `_wire_agent` et `_grant_dirs`). Dossiers créés au besoin (`ensure_folder_tree`, ids
  vérifiés) ; refus dit une fois (`agent_board_memory_dir_unavailable`, `agent_session_dir_unavailable`). Un agent
  sans liaison ne reçoit ni Board ni Session. `agent.start` porte `board_scope`. `full` inchangé.
- **Relance au rattachement** : `board_scope_stale()` (CLI lancé pour une autre liaison) compte comme un grant
  manquant (`_lacks_workspace_grant`) : relance `--resume` à l'adoption (`session_resume`) et avant un tour
  (`board_scope`), jamais pendant un tour ni un travail. Trace réelle : démarrage sans liaison (`board_scope
  [null, null]`, aucun dossier de Board), adoption, relance avec `boards\default\memory` et
  `sessions\jsess_55af…` seulement.
- **Preuve réelle** (bac S03) : un `[general] [research]` du Board A fait `Grep`/`Glob` sur `<data>\boards` et
  `<data>\sessions` : refusés « is outside … boards\default\memory, sessions\<Session ouverte> … » ; rien de B.
- **Consignes** : la découverte porte sur le Board courant et les connaissances globales ; un autre Board se lit
  par les outils `board_*` avec son identifiant, sur demande ou référence explicite (prompt confiné, note des
  sous-agents, bloc des rôles de recherche, section `RECHERCHE : EXISTANT D'ABORD`).
- **Reste lisible par chemin** (non partitionné par Board) : `<data>/artifacts` (pièces jointes) et
  `<data>/local_capabilities` (aperçus Remotion). Documenté dans `docs/product-capabilities.md` › *Reading scope*.
- Statut : correction 1 **faite**, en attente de QA ; correction 2 non retenue (décision ci-dessus) ; autres
  constats inchangés.
