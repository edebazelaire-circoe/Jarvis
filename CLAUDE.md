# Règles du dépôt JARVIS

Ce fichier est lu par chaque agent qui travaille dans ce dépôt, y compris dans un
worktree. Il ne contient que des règles qui s'appliquent partout ; le détail
vit dans la documentation citée.

## Données locales : chaque PC a les siennes, hors de git

Les bases SQLite (`jarvis.sqlite3`, `scene.sqlite3`), l'historique et la
mémoire d'exécution appartiennent au PC qui fait tourner JARVIS. Chaque poste
est son propre serveur. Elles vivent hors du dépôt, sous
`~/.jarvis/instances/<dossier du dépôt>-<empreinte>/data` par défaut, une
racine par copie du dépôt pour que le bac à sable et les worktrees ne
partagent jamais les bases du JARVIS vivant (`JARVIS_DATA_ROOT` pour un autre
emplacement). Détail et reprise des anciennes données `./data` :
[docs/local-data.md](docs/local-data.md).

- Ne jamais versionner une base, son `-wal`, son `-shm` ni une sauvegarde
  `.bak`. Ne jamais faire dépendre un test ou un script d'une base du dépôt.
- Ne jamais supprimer, écraser ni « nettoyer » une base, un `-wal` ou un
  `-shm` sans en avoir fait une copie d'abord. Un `-wal` sans sa base se met
  de côté ; il ne se rejoue jamais dans une autre base.

## Tout changement de schéma passe par une migration versionnée

Une base existante n'est jamais recréée depuis le code : elle n'évolue que par
les migrations appliquées au démarrage de Core, après une sauvegarde
automatique `<base>.v<ancienne version>.bak`.

1. Ajouter l'étape dans `_MIGRATIONS` du fichier qui porte le schéma
   (`jarvis/adapters/sqlite_state.py` pour `jarvis.sqlite3`,
   `jarvis/adapters/sqlite_scene.py` pour `scene.sqlite3`), indexée par la
   version qu'elle produit, et incrémenter `_SCHEMA_VERSION`.
2. Ne jamais modifier le DDL d'une version publiée ni une migration déjà
   publiée : on ajoute, on ne réécrit pas. Migrations avant seulement, une
   transaction par étape.
3. Écrire le schéma figé de la nouvelle version :
   `JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest tests/unit/test_schema_migrations.py`,
   puis committer `tests/schema/<base>.v<N>.sql` avec la migration.

`tests/unit/test_schema_migrations.py` échoue dès qu'un schéma change sans
nouvelle version.

## Ne jamais lancer, relancer ni arrêter JARVIS sans accord

Aucun agent ne démarre, ne relance ni n'arrête Core, le Control Center, la voix
ou ai-visualizer de ce poste sans que l'utilisateur l'ait demandé dans la
conversation en cours. Cela vaut pour `project jarvis start|restart|refresh|stop`
(outil `project-cli`, qui ouvre des volets dans le Windows Terminal de
l'utilisateur), pour `python -m jarvis core|control-center|voice` lancé dans le
dépôt principal, et pour tout `Stop-Process` sur ces processus.

- Un Core déjà à l'écoute sur `127.77.0.1:17653` est celui de l'utilisateur : le
  réutiliser, ne pas en lancer un second (il échoue en « Errno 10048 » et laisse
  des volets orphelins).
- Pour éprouver un changement, utiliser un bac à sable ou un worktree avec ses
  propres ports et sa propre racine de données, jamais le JARVIS vivant.
- Si une migration ou un changement exige un redémarrage, le dire et laisser
  l'utilisateur le faire.
