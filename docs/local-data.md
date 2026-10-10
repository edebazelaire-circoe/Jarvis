# Données locales : une racine par PC, hors de git

Chaque PC qui fait tourner JARVIS est son propre serveur. Il garde ses propres
données, qui ne sont jamais partagées par git.

| Donnée | Chemin sous la racine |
| --- | --- |
| état opérationnel : conversations, jobs, événements, Boards, Sessions et leurs Contexts, registre d'Artifacts, activité | `state/jarvis.sqlite3` |
| scène constellation | `state/scene.sqlite3` |
| historique des tours | `history/*.jsonl` |
| mémoire d'exécution, racine mémoire unique ([ci-dessous](#mémoire--une-seule-racine)) | `memory/{short_term,long_term,…}_memory/` |
| dossier de travail de chaque Context de Session | `sessions/<jarvis_session_id>/contexts/<context_id>/` |
| fichiers des Artifacts (audio, vidéo, captures…) | `artifacts/<artifact_id>/` |
| bibliothèque de prefabs de fenêtre de cette installation ([prefabs.md](prefabs.md)) | `prefabs/<prefab_id>/<version>/` |
| Presentations du Studio : un dossier par Presentation, un fichier par variante, les variantes archivées dans `archive/` ([presentation-studio.md](presentation-studio.md)) | `presentations/<presentation_id>/{presentation.json, variants/<variant_id>.json, archive/<variant_id>.json}` |
| capacités locales installables : état (`state.json`) et dossier `runtime/` propre à chaque capacité, hors plugins MCP ([local-capabilities.md](local-capabilities.md)) | `local_capabilities/<capability_id>/{state.json, runtime/}` |
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
[artifacts.md](artifacts.md#board-links). Mesuré sur une base fabriquée par le
code v7 (`467232f`) : une seule sauvegarde `.v7.bak`, aucune ligne perdue, la
Session ouverte reprise ; le code v7 refuse ensuite la base v8 sans la toucher
(`state DB schema 8 is newer than supported 7`, code de sortie 2) et redémarre
sur `.v7.bak` restaurée, même Session
([boards.md](boards.md#accepted-v1-limits), limite 9). Une base v4 (le `main` d'avant ces versions) passe
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
- **aucune autre rétention automatique** ; une sauvegarde de la racine doit inclure
  `boards/` avec `state/`.

Détail : [boards.md](boards.md#board-memory).

## Bibliothèque de prefabs : `prefabs/`

`prefabs/<prefab_id>/<version>/` contient une version publiée d'un prefab de
fenêtre : `manifest.json`, `template.html`, `style.css`, `behavior.js` et
`publication.json` (empreinte, date, provenance, écrit par Core). Une
bibliothèque par installation, donc par racine de données : les worktrees et
`jarvis-dst` ont la leur. Les prefabs de base livrés restent dans le paquet
(`jarvis/prefabs/base/`), jamais ici, sauf leurs versions publiées par la
porte d'édition de base. Adaptateur : `jarvis/adapters/file_prefab_library.py`.

**Sources de scènes Remotion** (Slice 05, [remotion-source.md](remotion-source.md)) : même dossier, mêmes règles ; une version porte
  `manifest.json` (`schema_version` 2), `publication.json`, `src/**` et `public/**` à la place des trois fichiers HTML. Jamais de
  `node_modules` ni de `package.json` : l'unique arbre de dépendances est `local_capabilities/remotion/runtime/` ([remotion-runtime.md](remotion-runtime.md)). Le
  **cache de compilation** (`local_capabilities/remotion/compiled/<clé>/`) est dérivé et reconstructible : à ne pas sauvegarder, à supprimer sans risque. Les **dossiers de travail d'un rendu** (`local_capabilities/remotion/runtime/render/jobs/<job>/`, [remotion-render.md](remotion-render.md)) sont éphémères : effacés à la fin de chaque rendu, sauf quelques Kio de traces ; le résultat d'un export est un Artifact (`artifacts/<id>/render.mp4`), pas ce dossier.

- **une version publiée n'est jamais réécrite** : Core écrit dans
  `prefabs/.staging-<16 hex>/` puis renomme le dossier ; un arrêt brutal
  laisse au pire un `.staging-*`, retiré au démarrage suivant
  (`core.prefab.swept`), jamais une version incomplète ;
- ne pas éditer un fichier publié à la main : Core recalcule l'empreinte à la
  lecture et refuse la version (`tampered`, `core.prefab.tampered`) ;
- mêmes défenses de chemin que `sessions/` (lien, jonction, point d'analyse
  refusés) ;
- **rétention des sources du Studio** (Slice 01a, ids `presentation-studio.*`
  seulement) : une version que rien n'épingle peut être **archivée** en un seul
  renommage vers `prefabs/.archive/<prefab_id>/<version>/` (fichiers intacts,
  jamais détruits, jamais relus par le catalogue) ; son numéro reste pris et ne
  sera jamais réattribué. Pour restaurer une version, Core arrêté, remettre le
  dossier sous `prefabs/<prefab_id>/<version>/`. `.archive/` fait partie de la
  sauvegarde de `prefabs/`. Les prefabs de l'utilisateur et les bases ne sont
  jamais archivés ([prefabs.md](prefabs.md#retention-of-studio-scene-sources)) ;
- **aucune autre rétention automatique** ; une sauvegarde de la racine doit inclure
  `prefabs/` : une scène restaurée sans elle garde des fenêtres dont la
  définition manque.

## Presentations du Studio : `presentations/`

`presentations/<presentation_id>/presentation.json` (identité, index des variantes,
références de ressources) et `presentations/<presentation_id>/variants/<variant_id>.json`
(scènes logiques ordonnées, leurs variantes locales — clé `scene_variants` de la scène, schéma de variante 3, Slice 17 —, références vers la direction artistique et la partition),
`presentations/<presentation_id>/scores/<score_id>.json` (la partition, Slice 10),
`presentations/<presentation_id>/art_directions/<art_direction_id>.json` (la direction artistique, Slice 09 : données seulement,
jamais un fichier de police ou d'image copié, des références `{kind, locator, title}`) :
un fichier JSON par document, **pas une base SQLite** (aucune migration de
`jarvis.sqlite3`, décision (a) de la Slice 02, raisons dans
[presentation-studio.md](presentation-studio.md#storage-decision-a-file-store-recorded-by-slice-02)).
Une racine par installation, donc par racine de données : les worktrees et
`jarvis-dst` ont la leur. Adaptateur : `jarvis/adapters/file_presentation_studio_store.py`.

**Source éditable et copies figées (Remotion, Slice 07).** Ce dossier reste la
seule maison de la source éditable : elle n'est jamais déplacée ni copiée dans
`artifacts/`. Ses copies figées (snapshot) et leurs rendus (MP4, image, PDF) sont
des Artifacts : fichiers sous `artifacts/<artifact_id>/` (chemin relatif au
`payload_ref`, jamais absolu), lignes dans `jarvis.sqlite3` (schéma inchangé,
v8). Supprimer une Presentation ne supprime pas ses snapshots ; supprimer un
snapshot ne touche pas la source ([presentation-artifacts.md](presentation-artifacts.md)).
Le `snapshot.zip` (Slice 09) est autonome : source exacte de chaque pin, documents, et copie des éléments de Board
référencés ; aucun chemin de la machine, rien lu hors du paquet à la réouverture
([paquet](presentation-artifacts.md#snapshot-package-slice-09), [références vivantes](presentation-live-refs.md)).

- **jamais un fichier à moitié écrit** : chaque document s'écrit dans un
  temporaire de même dossier, `fsync`, puis remplacement atomique ; un arrêt
  brutal laisse l'ancien texte entier ou le nouveau entier. Une Presentation
  neuve se construit dans `presentations/.staging-<16 hex>/` puis le dossier est
  renommé : jamais un dossier sans `presentation.json`. Les restes
  (`.staging-*`, `*.<8 hex>.tmp`) sont retirés au démarrage de Core
  (`core.presentation_studio.swept`) ; rien d'autre n'est jamais supprimé ;
- chaque document porte `schema` et `schema_version` ; Core refuse un document
  d'une version plus récente que la sienne (`presentation_studio_unsupported_schema_version`)
  et ne le réécrit jamais ;
- ne pas éditer un fichier à la main : toute clé inconnue ou état d'exécution
  (identifiant de fenêtre, position de lecture...) est refusé à la lecture
  (`presentation_studio_corrupt_document`) ;
- mêmes défenses de chemin que `sessions/` (lien, jonction, point d'analyse
  refusés) ;
- **un commit acquitté est durable** (Slice 08) : fichier `fsync`é, remplacement
  atomique, puis vidage du dossier. Il n'existe ni tampon ni minuterie
  d'enregistrement : rien à vider à l'arrêt, au changement de variante ou à la
  mise en veille. Tuer Core (`kill -9`) ne peut pas ramener une Presentation en
  arrière de la dernière révision acquittée. Un temporaire `*.tmp` orphelin
  n'est jamais « promu » ;
- **Historique d'annulation** (Slice 08) : mémoire de Core seulement, jamais écrit
  dans `presentations/`. Borné (32 entrées par variante, 256 Kio par variante,
  1 Mio **sérialisé** au total, soit environ 9 Mio de mémoire au pire, 8 variantes) ; après un redémarrage, annuler répond
  `history_unavailable` (raison `not_recorded_since_start`), jamais un silence
  ni une annulation inventée ;
- **zone `archive/`** (Slice 16) : archiver une branche **déplace** son fichier de `variants/` vers
  `archive/` (un renommage par fichier, jamais une copie suivie d'une suppression) et déplace son entrée du
  manifeste de `variants` vers `archived`. Rien n'est détruit ni vidé automatiquement ; une variante archivée
  se restaure (`POST .../variants/{variant_id}/restore`), son numéro d'affichage ne sert plus jamais. Les
  documents liés (la partition) restent dans `scores/`. Le manifeste (`presentation.json`) est en schéma
  v2 : compteur de numéros, noeuds vivants, noeuds archivés ; la première réécriture d'un manifeste v1 en garde les octets exacts dans
  `presentation.json.v1.bak` (une seule fois, jamais remplacée ni supprimée, ni par le balayage). Après un arrêt brutal, Core remet au démarrage un
  fichier de variante dans le dossier que le manifeste lui donne et **rapporte** (sans les adopter ni les
  supprimer) les fichiers de variante ou les documents liés que le manifeste ne nomme pas
  (`core.presentation_studio.reconciled`, `reconcile_orphans`). Procédure à la main :
  [OPERATIONS.md](OPERATIONS.md#variantes-du-studio--archive-restauration-et-reprise) ;
- **aucune rétention automatique** ; l'état de lecture et les identifiants d'objets
  de la scène n'y sont jamais écrits (mémoire de Core seulement). Une seule exception, **hors** de
  `presentations/` : `state/presentation-studio-stage-ledger.json` (Slice 12), à côté de `scene.sqlite3`,
  qui ne liste que les identifiants des fenêtres de lecture du Studio sur la scène de ce poste, pour qu'un
  Core tué puisse les archiver au démarrage suivant ; sans titre ni contenu, effacé dès qu'ils sont repris,
  ne se sauvegarde ni ne se déplace avec les Presentations ; s'il est illisible, Core le garde à côté
  (`presentation-studio-stage-ledger.json.corrupt-<horodatage>`, les trois plus récents, jamais écrasé) et
  reprend les fenêtres du Studio par balayage de la scène ; une sauvegarde
  de la racine doit inclure `presentations/`.
  Les prefabs que les scènes référencent vivent dans `prefabs/` : sauvegarder
  les deux ensemble.
- **Rechargement à chaud (Slice 06)** : le document de variante est en `schema_version` 3 (chaque scène porte
  `source_revision` et `last_valid_pin`, lus en v2 par une étape de montée de version, jamais réécrits à la
  lecture). Une scène dont `last_valid_pin` n'est pas `null` a un pin **pas encore vu monter** : ne pas la
  « corriger » à la main, le premier rapport de montage de la page la confirme ou la ramène en arrière. Les
  sources de scène sont des prefabs `presentation-studio.p<12 hex>.s<12 hex>` dans `prefabs/` ; Core archive
  (déplace, ne supprime jamais) vers `prefabs/.archive/` celles que rien n'épingle, et seulement quand l'index
  des épinglages est complet ([prefabs.md](prefabs.md#retention-of-studio-scene-sources))

- **Modèles de présentation (Slice 20, Remotion Slice 19)** : `presentation_templates/ptp_<12 hex>.json`, un fichier JSON par modèle,
  créé une fois, jamais réécrit ni supprimé par Core. Un modèle de **présentation** (document v2) porte ses sources de scène
  **intégrées** (`embedded`, dans les 256 Kio d'un document du Studio) et le squelette de sa partition : ce n'est donc plus un simple index
  de versions de bibliothèque, il se sauvegarde avec la racine de données et jamais dans le dépôt. Rien n'est publié dans `prefabs/`
  par la promotion d'une présentation ; les prefabs `presentation-studio.p<...>.s<...>` n'apparaissent qu'à l'instanciation.

## Base de scène disparue sous son `-wal`

Si `scene.sqlite3` manque alors que `scene.sqlite3-wal` est là, Core renomme le
`-wal` et le `-shm` en `scene.sqlite3-wal.orphan-<horodatage>.bak`, les garde
intacts et crée une scène neuve et utilisable. Il note ensuite
`core.scene.orphan_wal_set_aside` avec les chemins. Pour récupérer l'ancienne
scène, il faut retrouver la base qui va avec ce `-wal`, puis rejouer les deux
ensemble dans un dossier à part. Ne jamais rejouer un `-wal` dans une autre
base.

## Mémoire : une seule racine

La mémoire canonique (notes Markdown, `docs/memory.md`) vit sous
`<racine>/memory/`, pour Core V2 comme pour le chemin V1
(`RuntimeConfig.memory_dir`). Le V1 pointait avant sur `./data/memory`, dans
l'arbre de travail git ; il suit maintenant la racine locale. Ordre de
résolution : `JARVIS_MEMORY_DIR`, puis `runtime.memory_dir` du fichier TOML,
puis `<racine>/memory`.

Quand la valeur par défaut est utilisée, l'ancien `./data/memory` est copié une
seule fois dans la nouvelle racine (`adopt_legacy_memory`, `jarvis/data_root.py`) :

- copie seulement : l'ancien dossier n'est ni modifié, ni supprimé, ni marqué ;
- un fichier déjà présent dans la nouvelle racine n'est jamais écrasé ;
- `Jarvis-V1.md` (contenu versionné) et l'index dérivé `.jarvis/` ne sont pas
  copiés ;
- un témoin `memory/.legacy-memory-adoption.json` évite de rejouer la copie : une
  note supprimée ensuite ne revient pas. Si Core a déjà repris l'ancien `./data`
  (`ADOPTED.json`), rien n'est recopié ;
- `data/memory/Jarvis-V1.md`, suivi par git, reste en place : le retirer du suivi
  est une décision humaine, pas celle de cette reprise.

Dans `<racine>/memory/`, `.jarvis/` est l'index dérivé (supprimable, il se
reconstruit), `.history/` garde les révisions précédentes de chaque note
(canonique, hors git) et `_candidates/` les propositions de consolidation
(Slice 04). Détail : [memory.md](memory.md#canonical-store-slice-02).
