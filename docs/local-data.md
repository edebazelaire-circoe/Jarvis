# Données locales : une racine par PC, hors de git

Chaque PC qui fait tourner JARVIS est son propre serveur. Il garde ses propres
données, qui ne sont jamais partagées par git.

| Donnée | Chemin sous la racine |
| --- | --- |
| état opérationnel : conversations, jobs, événements, Boards, Sessions et leurs Contexts, registre d'Artifacts, activité | `state/jarvis.sqlite3` |
| scène constellation | `state/scene.sqlite3` |
| historique des tours | `history/*.jsonl` |
| mémoire d'exécution | `memory/{short_term,long_term,…}_memory/` |
| dossier de travail de chaque Context de Session | `sessions/<jarvis_session_id>/contexts/<context_id>/` |
| fichiers des Artifacts (audio, vidéo, captures…) | `artifacts/<artifact_id>/` |
| contexte global du cerveau, géré par l'agent ([context-global.md](context-global.md)) | `CONTEXT_GLOBAL/` |

La racine par défaut est
`~/.jarvis/instances/<dossier du dépôt>-<empreinte du chemin>/data`, par exemple
`C:\Users\<vous>\.jarvis\instances\Jarvis-1a2b3c4d\data`. Le chemin exact est
noté au démarrage de Core dans `core.data_root.adopted`. Il y a une racine par
copie du dépôt, et non une seule par PC : le bac à sable `jarvis-dst` et les
worktrees des agents tournent sur le même PC que le JARVIS vivant, et deux Core
ne doivent jamais partager une base. Pour placer la racine ailleurs, définir
`JARVIS_DATA_ROOT`, dans l'environnement ou dans `.env`. Le dossier courant
n'y change rien. Cette résolution est faite en un seul endroit,
`jarvis/data_root.py`. Core, le Control Center (Test Lab) et
`measure_speech_metrics` la partagent.

## Pourquoi hors du dépôt

Jusqu'au 2026-09-30, ces données vivaient sous `./data`, dans l'arbre de
travail git. Les bases y ont d'abord été versionnées, puis retirées du suivi
(`34bb291`). Le refresh suivant (`pull --rebase`) est alors parti d'un commit
de sauvegarde qui suivait encore les bases, pour aller vers un commit qui ne
les suivait plus : git a retiré `scene.sqlite3` et `jarvis.sqlite3` du disque.
Les `-wal` sont restés, et la scène est devenue indisponible. Tant que les
bases restent dans l'arbre de travail, un `checkout` d'un commit ancien ou
d'une branche qui les suit encore peut les écraser ou les retirer sans rien
signaler, puisqu'elles sont ignorées. Hors du dépôt, git ne peut plus les
toucher.

## Reprise des anciennes données `./data`

Au premier démarrage de Core sans `JARVIS_DATA_ROOT`, Core reprend le contenu
de l'ancien `./data` du dépôt dans la nouvelle racine, avant d'ouvrir quoi que
ce soit :

- chaque base est copiée par l'API de sauvegarde SQLite, en lecture seule. Le
  WAL est lu avec elle, rien de validé n'est perdu. `integrity_check` est
  vérifié et le nombre de lignes de chaque table est comparé. La copie n'est
  mise en place qu'ensuite, par renommage ;
- `history/` et `memory/` sont copiés fichier par fichier. `memory/Jarvis-V1.md`
  (contenu versionné) et l'index `memory/.jarvis/` sont exclus ;
- rien de ce qui existe déjà dans la nouvelle racine n'est écrasé : la reprise
  ne se fait qu'une fois ;
- l'ancien `./data` n'est ni modifié ni supprimé. Il reste une sauvegarde.
  Seul le `-shm`, simple index que tout lecteur SQLite met à jour, peut changer.
  Un témoin `data/ADOPTED.json`, ignoré par git, y note la racine de
  destination. Il empêche toute seconde reprise. Si le dépôt est déplacé, sa
  racine par défaut change, mais Core lit le témoin et suit la racine déjà
  reprise (`core.data_root.followed`) au lieu de repartir d'une copie périmée ;
- un `-wal` sans sa base dans l'ancien dossier n'est pas repris. Il est
  signalé et laissé en place ;
- le journal (`runtime/trace.jsonl`) note `core.data_root.adopted` avec le
  détail. `legacy-adoption.json`, à la racine, garde la trace de la reprise ;
- si une base ancienne ne se copie pas proprement, Core note
  `core.data_root.adoption_failed` et tourne encore sur l'ancien `./data` pour
  ce démarrage. Les données restent intactes et utilisables.

Une fois la reprise vérifiée, l'ancien `./data/state`, `./data/history` et les
dossiers de mémoire peuvent être archivés à la main. Rien ne les supprime
automatiquement.

## Schéma : migrations versionnées seulement

Une base existante n'est jamais recréée depuis le code. Elle n'évolue que par
les migrations que Core applique au démarrage :

- `jarvis.sqlite3` : `_MIGRATIONS` et `_SCHEMA_VERSION` dans
  `jarvis/adapters/sqlite_state.py`. Sauvegarde `jarvis.sqlite3.v<N>.bak` avant
  la première étape (voir `docs/state-model.md`, procédure de retour arrière) ;
- `scene.sqlite3` : même mécanisme dans `jarvis/adapters/sqlite_scene.py`.
  Sauvegarde `scene.sqlite3.v<N>.bak`.

Règles :

- une migration s'ajoute, elle ne se réécrit jamais ;
- une transaction par étape, migrations avant seulement ;
- une base neuve suit le même chemin qu'une base migrée.

Versions de `jarvis.sqlite3` : v2 journal d'événements, v3 Boards et
Sessions, v4 plugins MCP, v5 (2026-10-01) table `session_contexts` : un
Context par ligne, clé `context_id`, liée à `jarvis_sessions`, au plus un
Context actif et un Context `adopted` par Session (index uniques partiels).
La v5 ne crée aucune ligne : le Context `adopted` d'une Session ouverte
d'avant la v5 est créé par Core (`ensure_context`), une seule fois. Détail :
[session-context.md](session-context.md#persistence). v6 (2026-10-01) :
registre d'Artifacts (`artifacts`, `artifact_relations`) et ledger d'activité
de Session (`session_activity`), sans ligne migrée ; sauvegarde
`jarvis.sqlite3.v5.bak`. Détail : [artifacts.md](artifacts.md). v7
(2026-10-01) : intention et état durables des captures (`captures`, une ligne
par capture, au plus une capture continue ouverte par canal/appareil), sans
ligne migrée ; sauvegarde `jarvis.sqlite3.v6.bak`. Détail :
[capture.md](capture.md). v8 (2026-10-02) : liens Board-artifact
(`board_artifact_links`, un lien par couple Board/Artifact, origine
`active_board` ou `explicit`), sans ligne migrée : un Artifact d'avant la v8
n'a pas de Board ; sauvegarde `jarvis.sqlite3.v7.bak`. Détail :
[artifacts.md](artifacts.md#board-links). Une base v4 (le `main` d'avant ces versions) passe
d'un coup en v7 et ne reçoit qu'**une** sauvegarde, `jarvis.sqlite3.v4.bak` ;
ce `main` refuse ensuite la base v7 sans la toucher. Retour arrière mesuré :
[session-context-capture.md](session-context-capture.md#schema-migration-and-rollback).

Le schéma de chaque version est figé dans `tests/schema/<base>.v<N>.sql`.
`tests/unit/test_schema_migrations.py` échoue dès qu'un DDL change sans
nouvelle version. Pour écrire le fichier figé d'une nouvelle version :

```bash
JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest tests/unit/test_schema_migrations.py
```

## Dossiers des Contexts : `sessions/`

`sessions/<jarvis_session_id>/contexts/<context_id>/` contient les documents
qu'un agent range dans le Context d'une Session. La base ne garde que l'index
et le cycle de vie ; le contenu est dans ces dossiers et appartient à l'agent.

- le chemin est dérivé des identifiants, jamais reçu en entrée : `..`, un
  séparateur, une lettre de lecteur ou un caractère non ASCII sont refusés ;
- un lien symbolique, une jonction ou tout point d'analyse Windows sur
  `sessions`, la Session, `contexts` ou le Context est refusé
  (`context_workspace_unsafe`), et rien n'est écrit à travers ;
- Core ne supprime ni ne vide jamais ces dossiers. Une création interrompue
  est complétée au passage suivant ;
- le CLI du cerveau reçoit **tout** l'arbre `sessions/` (`--add-dir` pour
  Claude, `writable_roots` pour Codex), pas un seul Context : sous
  `bypassPermissions` (réglage par défaut), cet accord n'est **pas** une
  frontière d'autorisation. Seule la règle du brief tient les Contexts
  dormants et les autres Sessions à l'écart ;
- de même, il reçoit `boards/` (`--add-dir`, Claude seulement) : la règle du
  prompt système, pas l'accord, tient la mémoire des autres Boards à l'écart
  ([boards.md](boards.md) › *Board memory hydration*) ;
- une sauvegarde de la racine doit les inclure avec `state/` : une base
  restaurée sans eux garde des Contexts dont le dossier est vide.

## Fichiers des Artifacts : `artifacts/`

`artifacts/<artifact_id>/` contient le fichier (payload) d'un Artifact :
enregistrement audio, vidéo d'écran, capture d'écran... La base n'en garde que
la référence relative `artifacts/<artifact_id>/<nom>` : déplacer la racine ne
casse aucun enregistrement.

- mêmes défenses de chemin que `sessions/` (lien, jonction, point d'analyse
  refusés, `artifact_payload_unsafe`) ;
- un fichier en cours d'écriture s'appelle `<nom>.partial` ; un fichier au nom
  final est complet. Après un arrêt brutal, Core reprend au démarrage les
  Artifacts restés `pending` (`partial` ou `failed`, jamais `complete`) ;
- **aucune rétention automatique** : ce ne sont pas des captures de
  diagnostic (`runtime/scene-captures/`). Seule une suppression explicite
  retire un dossier, après la base ;
- une sauvegarde de la racine doit les inclure avec `state/`.

Détail : [artifacts.md](artifacts.md).

## Mémoire des Boards : `boards/`

`boards/<board_id>/memory/` contient la mémoire libre d'un Board : notes,
décisions, plans que ses agents rangent eux-mêmes. Aucun fichier imposé ;
`summary.md`, s'il existe, est le condensé lu à l'hydratation. La base ne
garde que l'identité du Board (`work_boards`) ; le contenu est dans ce
dossier et appartient aux agents. Adaptateur :
`jarvis/adapters/board_memory_store.py`.

- l'emplacement est dérivé du seul `board_id` validé ; un client ne passe
  qu'un chemin relatif POSIX **dans** `memory/` (`BoardMemoryPath` : `..`,
  chemin absolu, lecteur, nom réservé Windows refusés) ;
- mêmes défenses que `sessions/` sur la racine (`board_memory_unsafe`), et à
  **chaque** opération chaque composant sous `memory/` est inspecté : un lien,
  une jonction ou un point d'analyse n'est jamais suivi
  (`memory_path_escape`) ; une suppression récursive retire le lien lui-même,
  jamais sa cible ;
- course avec un autre processus : avant **et** après chaque acte (écriture,
  création de dossier, déplacement, suppression), l'identité (`lstat`) de
  chaque dossier de `boards/<id>/memory/...` et de l'entrée visée est
  revérifiée ; une suppression récursive revérifie le parent et l'entrée avant
  chaque retrait. Un dossier remplacé (jonction, lien) est refusé
  (`board_memory_unsafe`, trace `board.memory.chain_changed`) ; vu après coup,
  l'acte a pu atterrir ailleurs et n'est pas défait. Garanti : aucune
  opération ne suit un lien qu'elle a vu. Risque résiduel : un processus local
  hostile qui peut écrire dans la racine de données peut encore gagner la
  course dans l'instant entre la dernière vérification et l'appel système ; il
  est alors signalé, pas empêché ;
- dossier créé à la première opération (lecture comprise), pour un Board
  actif comme archivé : archiver un Board garde sa mémoire ;
- écriture atomique : temporaire neuf `.~bm<hex>.tmp` dans le même dossier
  (un nom déjà pris n'est jamais touché ; ces noms sont refusés aux clients),
  `fsync`, puis remplacement. Un temporaire laissé par un arrêt brutal n'est
  ni listé ni cherché ; il peut être retiré à la main ;
- au plus 256 Kio lus ou écrits par appel ; texte UTF-8 seulement pour lire,
  écrire et chercher (un binaire est listé avec sa taille, jamais lu) ;
- **aucune rétention automatique** ; une sauvegarde de la racine doit inclure
  `boards/` avec `state/`.

Détail : [boards.md](boards.md#board-memory).

## Base de scène disparue sous son `-wal`

Si `scene.sqlite3` manque alors que `scene.sqlite3-wal` est là, Core renomme le
`-wal` et le `-shm` en `scene.sqlite3-wal.orphan-<horodatage>.bak`, les garde
intacts et crée une scène neuve et utilisable. Il note ensuite
`core.scene.orphan_wal_set_aside` avec les chemins. Pour récupérer l'ancienne
scène, il faut retrouver la base qui va avec ce `-wal`, puis rejouer les deux
ensemble dans un dossier à part. Ne jamais rejouer un `-wal` dans une autre
base.
