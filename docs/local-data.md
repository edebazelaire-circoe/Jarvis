# Données locales : une racine par PC, hors de git

Chaque PC qui fait tourner JARVIS est son propre serveur. Il garde ses propres
données, qui ne sont jamais partagées par git.

| Donnée | Chemin sous la racine |
| --- | --- |
| état opérationnel : conversations, jobs, événements, Boards | `state/jarvis.sqlite3` |
| scène constellation | `state/scene.sqlite3` |
| historique des tours | `history/*.jsonl` |
| mémoire d'exécution | `memory/{short_term,long_term,…}_memory/` |

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

Le schéma de chaque version est figé dans `tests/schema/<base>.v<N>.sql`.
`tests/unit/test_schema_migrations.py` échoue dès qu'un DDL change sans
nouvelle version. Pour écrire le fichier figé d'une nouvelle version :

```bash
JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest tests/unit/test_schema_migrations.py
```

## Base de scène disparue sous son `-wal`

Si `scene.sqlite3` manque alors que `scene.sqlite3-wal` est là, Core renomme le
`-wal` et le `-shm` en `scene.sqlite3-wal.orphan-<horodatage>.bak`, les garde
intacts et crée une scène neuve et utilisable. Il note ensuite
`core.scene.orphan_wal_set_aside` avec les chemins. Pour récupérer l'ancienne
scène, il faut retrouver la base qui va avec ce `-wal`, puis rejouer les deux
ensemble dans un dossier à part. Ne jamais rejouer un `-wal` dans une autre
base.
