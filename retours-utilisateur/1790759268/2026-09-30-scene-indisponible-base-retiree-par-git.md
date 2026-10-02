# Scène indisponible : git a retiré scene.sqlite3 du disque pendant le refresh

- **Date** : 2026-09-30
- **Session** : `retours-utilisateur/1790759268`
- **Symptôme** : plus d'étoiles de sous-agents ; le Control Center affiche « scène
  indisponible » ; `scene_inspect` renvoie `scene_unavailable` avec « scene store … is
  missing but its -wal file exists: the database was moved without it ».
- **L'utilisateur** : « Ouais c'est un vrai problème ça. » Puis : « la database doit être
  sortie de l'historique git mais c'est pas censé impacter la création d'une nouvelle
  scène […] Le projet doit toujours avoir une base de données active et utilisable. »

## Cause

Le fichier a bien été **supprimé du disque**. La désindexation seule n'y est pour rien.

1. 08:51 : `34bb291` (`git rm --cached`) sort `data/state/*.sqlite3` du suivi. Le
   fichier reste sur le disque, et `origin/main` ne suit plus la base.
2. 09:46:10 : le refresh crée le commit local `8be78de` « sauvegarde avant refresh ». Ce
   commit suivait encore `scene.sqlite3` et `jarvis.sqlite3`, parce que le `main` local
   datait d'avant `34bb291`.
3. 09:46:16 : `pull --rebase --autostash` fait `checkout 34bb291`. Passer d'un commit qui
   suit un fichier à un commit qui l'a supprimé, c'est pour git un fichier à retirer de
   l'arbre de travail. `scene.sqlite3` et `jarvis.sqlite3` ont disparu du disque. Leurs
   `-wal`/`-shm` sont restés, puisqu'ils étaient ignorés. Le commit de sauvegarde a
   ensuite été sauté (`rebase --skip`), ce qui n'a rien restauré.
4. Au démarrage de Core, la garde de `SQLiteSceneRepository` a vu un `-wal` sans sa base.
   Elle a refusé la scène, à raison, pour ne pas rejouer ce WAL dans une base neuve. Mais
   elle n'avait pas de solution de repli : la scène est restée indisponible.

`jarvis.sqlite3` avait subi le même sort ; il a été restauré à part vers 09:54
(`jarvis.sqlite3.v2.bak`).

## Réparation de l'état

- Sauvegarde d'abord : `data/state/scene-recovery-20260930.bak/` (`-wal` et `-shm`
  d'origine, base extraite du blob git `d584169`).
- La base du dernier commit (rev 1215, 2026-09-21) + le `-wal` orphelin (écrit jusqu'au
  28/09 18:28) forment bien une paire. Rejoués dans un dossier à part, ils donnent la rev
  1513 (28/09 18:28), `integrity_check` ok, 6 objets, 2 liens, 200 entrées d'historique.
  Le dépôt réel de la scène (`SQLiteSceneRepository`) l'ouvre et la valide.
- Cette base, WAL intégré, est maintenant `data/state/scene.sqlite3`. Le `-wal`/`-shm`
  d'origine est rangé dans le dossier de sauvegarde (`*.original`).
- **Rien de perdu** : la scène n'avait rien écrit entre le 28/09 18:28 et la disparition.

## Correctif (commit `9c6f7c1`, poussé sur main)

Si la base de scène manque et qu'un `-wal` est resté, Core ne se bloque plus :

- il renomme le `-wal`/`-shm` en `scene.sqlite3-wal.orphan-<horodatage>.bak`. Ces fichiers
  sont gardés octet pour octet, ignorés par git, jamais effacés ni rejoués ;
- il crée une scène neuve et utilisable, et journalise `core.scene.orphan_wal_set_aside`
  avec les chemins ;
- si le renommage échoue, la scène reste refusée et rien n'est créé.

Preuve, sur un vrai Core lancé à part avec le `-wal` réel de l'incident :

- **avant** : `GET /v1/scene/snapshot` renvoie 503 `scene_unavailable`, avec le message
  exact de l'utilisateur ;
- **après** : il renvoie 200, scène rev 0, et le `-wal` est gardé à côté.

Les tests unitaires ont été écrits en premier et ont échoué avant le correctif.

## Reste à faire

- **Redémarrer Core** pour qu'il recharge la scène restaurée et le correctif.
  La scène n'est chargée qu'au démarrage.
- Risque restant : la base vit dans l'arbre git. Un `checkout` d'un commit antérieur à
  `34bb291` (ou une branche de worktree qui suit encore les bases) écrase ou retire les
  bases sans prévenir, puisqu'elles sont ignorées. Piste : sortir `JARVIS_DATA_ROOT` du
  dépôt (par exemple `~/.jarvis/data`).

## Suite : données hors du dépôt et migrations obligatoires (même jour)

Demande de l'utilisateur : « la database doit être sortie de l'historique git
mais c'est pas censé impacter la création d'une nouvelle scène […] faut des
scripts de migration quand on fait des changements dans la base de données […]
chaque PC a ses propres données SQL. Chaque PC fait son propre serveur ».

Ce qui a été fait (commit `feat(data)` sur main) :

- **Données hors du dépôt.** Racine par défaut :
  `~/.jarvis/instances/<dossier>-<empreinte>/data`, soit sur ce poste
  `C:\Users\Etienne\.jarvis\instances\Jarvis-2d57e264\data`.
  `JARVIS_DATA_ROOT` reste possible. C'est une racine par copie du dépôt, et
  non une seule par PC : `jarvis-dst` et les worktrees des agents tournent sur
  ce même PC, et une racine unique leur ferait partager les bases du JARVIS
  vivant.
- **Reprise au premier démarrage de Core.** Copie de l'ancien `./data` par
  l'API de sauvegarde SQLite, WAL compris. Chaque copie est vérifiée
  (`integrity_check` et nombre de lignes par table) avant d'être mise en
  place. L'ancien dossier reste intact, avec un témoin `data/ADOPTED.json`.
  Rien n'est écrasé. Si une copie échoue, Core reste sur l'ancien dossier.
- **Migrations versionnées.** `scene.sqlite3` a maintenant le même mécanisme
  que `jarvis.sqlite3` : sauvegarde `.v<N>.bak`, une transaction par étape.
  Le schéma de chaque version est figé dans `tests/schema/`, et
  `tests/unit/test_schema_migrations.py` échoue dès qu'un DDL change sans
  migration.
- **Règle écrite** dans `CLAUDE.md`, à la racine, que chaque agent lit
  automatiquement, worktrees compris. Le détail est dans `docs/local-data.md`.

Preuve, sur un vrai Core, avec des copies des bases réelles et un aller-retour
`git checkout 8be78de` puis retour, soit le geste de l'incident :

- **avant** : la scène passe de la révision 1513 et 6 objets à la révision 0
  et 0 objet, puisque les bases sont retirées du disque ;
- **après** : la scène reste à la révision 1513 avec 6 objets.
