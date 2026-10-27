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

## Produit installé : `%LOCALAPPDATA%\CIRCOE\Jarvis`

Ce qui précède décrit un **checkout de développement** (dépôt, worktree, bac à
sable). Un **produit installé** (Presentation Edition, décisions D04/D05) a une
maison stable par utilisateur Windows, indépendante du dossier du programme.

**Signal d'installation** (`jarvis/installation.py`, seule source) : le fichier
`jarvis-product.json`, posé par le paquet d'installation à côté du paquet
`jarvis/` (dans le dossier du programme). Contenu exact :
`jarvis.installation.marker_payload()`, soit
`{"schema": "jarvis.product-install", "schema_version": 1, "vendor": "CIRCOE", "product": "Jarvis"}`.
Présent = produit installé ; absent = checkout. Le chemin d'installation, le
nom du dossier ou un exécutable gelé ne comptent jamais. Un marqueur illisible
ou d'un autre schéma refuse le démarrage (`ConfigurationError`) au lieu de
retomber en mode développement. Le marqueur est ignoré par git
(`/jarvis-product.json`) : un checkout ne le porte jamais par accident. Couture
du paquet (Slice 06) : poser ce fichier, rien d'autre. Le paquet pose le code dans
`<installation>\app\` (marqueur compris) et ses runtimes privés (Python, Node)
dans `<installation>\runtime\` : disposition, résolution sans PATH et manifeste
dans [windows-packaging.md](windows-packaging.md). Le dossier du programme ne
contient aucun état et n'est jamais écrit à l'exécution (bytecode précompilé).

**Arborescence** (lue dans `LOCALAPPDATA`, jamais déduite du dossier du
programme ; `LOCALAPPDATA` absent ou relatif = refus de démarrer) :

```text
%LOCALAPPDATA%\CIRCOE\Jarvis\
  data\       racine de données : mêmes chemins internes que ci-dessus
              (state\, CONTEXT_GLOBAL\, memory\, history\, boards\, sessions\,
              artifacts\, presentations\, presentation_templates\, prefabs\,
              local_capabilities\, backups\, retours-utilisateur\)
  runtime\    core.token, control-center-settings.json (clés API du Control Center),
              trace.jsonl / errors.jsonl, *-mcp.json, modèles wake-word et
              locuteur, scene-captures\
  config\     .env du produit (lu à la place du .env du dossier du programme)
```

`logs\` et `cache\` ne sont pas créés en V1 : aucun consommateur ne les
utilise (les journaux sont dans `runtime\`, le cache de compilation Remotion
dans `data\local_capabilities\remotion\compiled\`). Rien de canonique ni de
secret ne vit sous le dossier du programme ni sous le dossier courant.

Les trois dossiers sont créés au premier lancement par le lanceur du produit
(`python -B -m jarvis launch`, Slice 07), qui écrit aussi ses journaux dans
`runtime\logs\` (`launcher.log`, `core.log`, `ui.log`, `voice.log`) ; la
préparation les recrée sur demande (action `prepare_data`). L'installeur, la
mise à jour et la désinstallation ne touchent jamais cette maison :
[product-install.md](product-install.md).

**Précédence**, identique dans les deux modes :

| Racine | 1. variable | 2. produit installé | 3. développement |
| --- | --- | --- | --- |
| données | `JARVIS_DATA_ROOT` | `…\Jarvis\data` | `~/.jarvis/instances/<dépôt>-<empreinte>/data` |
| runtime | `JARVIS_RUNTIME_DIR` (relatif : au dossier courant) | `…\Jarvis\runtime` | `./runtime` (dossier courant) ; `<dépôt>/runtime` pour le hook de routage, les modèles wake-word et le banc locuteur |
| `.env` | — | `…\Jarvis\config\.env` | `<dépôt>/.env` |
| édition | `JARVIS_PRODUCT_EDITION` | `presentation` | `full` ([product-edition.md](product-edition.md#selection)) |

Une variable vide compte comme absente. Les variables restent la porte des
tests et de l'administration ; le produit n'en pose aucune. Déplacer ou mettre
à jour le programme ne crée donc pas de second profil, et un worktree (sans
marqueur) reste isolé du profil installé.

Chemin V1 (`AppConfig`, `python -m jarvis run|text|health|reindex`) : même
résolveur, avec l'environnement réel. Ordre : `JARVIS_RUNTIME_DIR`, puis
`runtime.runtime_dir` du TOML, puis le défaut. En produit installé, une valeur
TOML **relative** (le `./runtime` de `config/jarvis.example.toml`) est
**ignorée** (avertissement au journal) : elle placerait le runtime sous le
dossier courant ; une valeur absolue est respectée. L'ancien
`./data/memory` n'est pas repris en produit installé (`adopt_legacy_memory`
coupé, comme la reprise de `./data` par Core).

**Consommateurs** (tous par `resolve_data_root` / `resolve_runtime_root` /
`default_runtime_root` de `jarvis/data_root.py`) : Core et le Control Center
(`V2Settings.load`), la voix, le chemin V1 (`AppConfig`), le Test Lab
(`testlab/composition.py`), le serveur MCP Écran (jeton par défaut), le hook de
routage, le catalogue wake-word, le banc locuteur, les retours utilisateur
(`runtime/feedback_sessions.py`). Les serveurs MCP enfants reçoivent
`JARVIS_RUNTIME_DIR` explicite du Control Center, et les magasins (Boards,
Sessions, Artifacts, Presentations, prefabs, capacités locales, mémoire,
`CONTEXT_GLOBAL`) reçoivent la racine de Core : aucun ne résout seul.

**Reprise** : le produit installé ne reprend **jamais** l'ancien `./data`
(il serait dans le dossier du programme) et n'adopte **jamais
automatiquement** un profil de développement. Voir [Reprise d'un
profil](#reprise-dun-profil-vers-une-racine-vide).

**Diagnostics** : Core journalise `core.installation` au démarrage et
`GET /v1/health` porte un bloc `installation` : `mode` (`installed` |
`development`), `product_home`, et pour `data_root` / `runtime_root` une
`source` (`product_home`, `override`, `development_default`, `followed`) et un
`label` sans chemin d'utilisateur (`%LOCALAPPDATA%\CIRCOE\Jarvis\data`, le seul
nom `<dépôt>-<empreinte>`, ou `null`). Le paquet de support
(`python -B -m jarvis support-bundle`, Slice 10) ne lit de cette maison que des
compteurs, les versions de schéma (lecture seule) et la fin masquée des journaux
de `runtime\` ; jamais une base, l'historique, la mémoire, `CONTEXT_GLOBAL` ni
une présentation : [release.md](release.md#support-bundle). Mise à jour sur un
profil existant et frontière du retour arrière : [release.md](release.md#update-over-an-existing-profile).

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

`CONTEXT_GLOBAL/` d'un ancien `./data`, s'il existe, est repris **en bloc**,
seulement si la nouvelle racine n'en a pas (sinon : signalé dans `skipped`,
jamais complété fichier par fichier, pour qu'un fichier supprimé par l'agent
reste supprimé). Si sa copie échoue (jonction, lien, fichier verrouillé), le
reste de la reprise tient : l'échec est noté dans `skipped` (journal
`core.data_root.adopted`, niveau warning), la source reste intacte et se copie à
la main ; Core ne retombe pas sur `./data`. Mode développement seulement : le
produit installé ne fait jamais cette reprise.

## Reprise d'un profil vers une racine vide

`adopt_data_root(source, cible)` (`jarvis/data_root.py`) copie une racine de
données complète vers une autre. Elle n'est **jamais appelée automatiquement**
(décision Slice 02 : un profil de développement n'est pas adopté par le
produit ; aucune version installée antérieure n'existe). C'est la couture
d'une reprise explicite, demandée par l'utilisateur ou un administrateur
(intégration d'onboarding prévue par une Slice ultérieure).

- **jamais de fusion** : la cible doit être absente ou vide
  (`target_not_empty` sinon) ; source et cible ne se chevauchent pas
  (`roots_overlap`) ;
- **copie d'abord** dans un dossier voisin `.<cible>.adopting-<hex>`, mise en
  place par un seul renommage après toutes les vérifications ; en cas d'échec,
  rien n'est en place et ce dossier de copie est retiré ;
- chaque `*.sqlite3` par l'API de sauvegarde en lecture seule (WAL compris),
  `integrity_check` et comptes de lignes comparés (`database_copy_failed`
  sinon) ; chaque autre fichier vérifié par SHA-256 (`copy_mismatch`) ;
- un lien, une jonction ou un point d'analyse dans la source refuse tout
  (`source_unsafe`) ;
- **non repris** : `-wal`/`-shm` (leur contenu validé passe par la sauvegarde ;
  un `-wal` sans sa base est signalé et laissé dans la source), `.staging-*`,
  `.purging-*`, `.adopting-*`, `*.partial`, `*.tmp`, `memory/**/.jarvis/`
  (index dérivé), `local_capabilities/<id>/runtime/` et `compiled/` (moteurs et
  cache à réinstaller : la capacité se répare depuis Réglages) ;
- `CONTEXT_GLOBAL/` est toujours repris, vérifié présent dans la copie
  (`global_context_missing` sinon) ;
- la source n'est ni modifiée ni marquée ; la cible reçoit
  `profile-adoption.json` (rapport).

## Schéma : migrations versionnées seulement

Une base existante n'est jamais recréée depuis le code. Elle n'évolue que par
les migrations que Core applique au démarrage :

- `jarvis.sqlite3` : `_MIGRATIONS` et `_SCHEMA_VERSION` dans
  `jarvis/adapters/sqlite_state.py`. Sauvegarde `jarvis.sqlite3.v<N>.bak` avant
  la première étape (voir `docs/state-model.md`, procédure de retour arrière),
  écrite en `journal_mode=DELETE` (une lecture n'ajoute ni `-wal` ni `-shm`) ;
  Core journalise une ligne `core.state.migrated` par étape appliquée (de, vers,
  lignes changées) ;
- `scene.sqlite3` : même mécanisme dans `jarvis/adapters/sqlite_scene.py`.
  Sauvegarde `scene.sqlite3.v<N>.bak` ; Core journalise une ligne
  `core.scene.migrated` par étape (de, vers, sauvegarde). v2
  (organic-agent-orchestration, Slice 08) ne réécrit aucune ligne : elle monte
  la version du fichier (rôles et liens d'agent dans les colonnes `data`).
  Retour arrière vers un Core antérieur : JARVIS arrêté, mettre de côté
  `scene.sqlite3` (avec son `-wal` et son `-shm`, sans les effacer), puis
  remettre `scene.sqlite3.v1.bak` à sa place. Tout ce qui a été écrit dans la
  scène après la migration est perdu (étoiles, rôles, liens, placements,
  archivages). Ne jamais redescendre `schema_version` à la main dans le fichier
  v2 : un Core plus ancien lirait des charges inconnues et refuserait la base
  comme `corrupted`.

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
v9 (2026-10-17) : type de Board fixé, **données seules** (aucun DDL, première
migration qui réécrit des payloads) : chaque Board reçoit son `board_kind`
définitif (`assistant`, `presentation` ou `meeting`) et perd ses clés de mode
`interaction_mode` / `interaction_mode_origin` ; sauvegarde
`jarvis.sqlite3.v8.bak`. Le code v8 refuse ensuite la base
(`state DB schema 9 is newer than supported 8`). Règles et retour arrière :
[boards.md](boards.md#persistence).
v10 (2026-10-20) : historique durable des missions, **DDL seul** (sept tables
neuves, aucune ligne produit, aucune colonne de statut d'exécution) ;
sauvegarde `jarvis.sqlite3.v9.bak`. Le code v9 refuse ensuite la base
(`state DB schema 10 is newer than supported 9`) ; retour arrière : restaurer
`.v9.bak`. Contrat : [mission-history.md](mission-history.md).
v11 (2026-10-20) : versions de Work Method promues par une personne, **DDL seul**
(une table neuve en ajout seul `work_method_versions`, aucune ligne produit). Le code
v10 refuse ensuite la base (`state DB schema 11 is newer than supported 10`). Contrat :
[work-methods.md](work-methods.md#promotion).

**Mise en service de v10 et v11 ensemble.** Une base v9 (cas du JARVIS vivant tant que
la branche de l'orchestration organique n'est pas fusionnée) passe v9 → v10 → v11 en
**un seul** démarrage de Core, après **une seule** sauvegarde, `jarvis.sqlite3.v9.bak`
(la sauvegarde est faite une fois, sous le nom de la version de départ) ; il n'y a donc
pas de `.v10.bak`. Retour arrière : arrêter Core, mettre de côté `jarvis.sqlite3` et ses
`-wal` / `-shm` (jamais les supprimer), restaurer `jarvis.sqlite3.v9.bak` et relancer le
code v9. Tout ce qui a été écrit depuis la migration est alors absent de la base
restaurée : historique des missions (v10) et versions promues (v11) ; l'instantané
`<runtime>/work-methods.json` est réécrit vide par le Control Center à son prochain
démarrage, et le hook revient aux versions livrées. Une base déjà en v10 ne passe que
v10 → v11, après la sauvegarde `jarvis.sqlite3.v10.bak`.

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
- une sauvegarde de la racine doit les inclure avec `state/` ;
- **pièces jointes du Chat et dépôts sur le Board** (handoff
  jarvis-unified-chat-and-board-drop) : Artifacts `upload` dont le fichier est
  `artifacts/<artifact_id>/upload.<ext>` (le nom d'origine n'est jamais un nom
  de fichier ; règle de l'extension : [chat.md](chat.md) › *Attachments*) ; une URL déposée est un Artifact `link` **sans**
  fichier (l'URL est dans la base). Un téléversement en échec garde sa ligne et
  son dossier est retiré (aucun `.partial` laissé) ; un téléversement `pending`
  d'un Core mort passe `failed` (`upload_interrupted`) au démarrage suivant,
  jamais `partial`. Ces Artifacts sont liés au Board actif comme les autres.
  **Aucune nouvelle base ni migration** : tout passe par les colonnes JSON
  existantes (`artifacts.data`, `turns.data.metadata`) et la liste fermée des
  natures d'Artifact, sans `CHECK` SQL (`_SCHEMA_VERSION` reste 8 et 1). L'état
  du canal vocal du Chat vit dans la mémoire de Core, rien sous `runtime/`.
  Bornes, chemins et refus : [chat.md](chat.md) › *Attachments*, *Data
  locations*.

Détail : [artifacts.md](artifacts.md).

## Interne et export : `Documents\Jarvis` n'est jamais un espace de travail

Tout ce qui est écrit sous la racine de données (sources, variantes, prefabs,
assets, brouillons, mémoire des Boards, Sessions, `CONTEXT_GLOBAL`, snapshots,
payloads des Artifacts) et sous le runtime (dossiers de rendu, aperçus) est
**interne** et canonique. `Documents\Jarvis` (dossier Documents résolu par
l'API des dossiers connus de Windows) ne reçoit qu'une **copie** d'un fichier
final (MP4, image, PDF), sur un geste explicite de l'utilisateur ; Jarvis ne la
relit jamais, l'effacer ou la déplacer ne change rien. Aucun démarrage, rendu ni
brouillon n'y écrit. Contrat : [export.md](export.md).

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
  sauvegarde de `prefabs/`. Seule exception à « jamais détruits » : la purge définitive d'une Presentation archivée
  efface ses propres sources `presentation-studio.p<12 hex>.*` (catalogue et `.archive/`), après les avoir copiées dans
  `backups/purge-presentations-<horodatage>/prefabs/` ; les sources `presentation-studio.rm-*` (partageables) ne sont jamais purgées. Les prefabs de l'utilisateur et les bases ne sont
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
v8). Supprimer un snapshot ne touche pas la source ([presentation-artifacts.md](presentation-artifacts.md)).
La seule suppression d'une Presentation est la **purge définitive des archivées** (ci-dessous) : elle emporte ses
snapshots et leurs rendus, après les avoir sauvegardés.
Le `snapshot.zip` (Slice 09) est autonome : source exacte de chaque pin, documents, et copie des éléments de Board
référencés ; aucun chemin de la machine, rien lu hors du paquet à la réouverture
([paquet](presentation-artifacts.md#snapshot-package-slice-09), [références vivantes](presentation-live-refs.md)).

- **jamais un fichier à moitié écrit** : chaque document s'écrit dans un
  temporaire de même dossier, `fsync`, puis remplacement atomique ; un arrêt
  brutal laisse l'ancien texte entier ou le nouveau entier. Une Presentation
  neuve se construit dans `presentations/.staging-<16 hex>/` puis le dossier est
  renommé : jamais un dossier sans `presentation.json`. Les restes
  (`.staging-*`, `*.<8 hex>.tmp`, et le `.purging-<16 hex>` d'une purge interrompue, déjà sauvegardé) sont retirés au
  démarrage de Core (`core.presentation_studio.swept`) ; rien d'autre n'est supprimé, hors la purge définitive ;
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
- **purge définitive des archivées** (demande explicite de l'utilisateur, jamais automatique) : un plan d'abord (rien
  n'est écrit), puis, avec le jeton du plan et le oui de l'utilisateur, Core **sauvegarde** dans
  `backups/purge-presentations-<horodatage UTC>/` les dossiers des Presentations archivées, leurs sources de scène
  `presentation-studio.p<12 hex>.*` (`prefabs/` et `prefabs/.archive/`), les dossiers de leurs Artifacts dérivés et une copie
  cohérente de `jarvis.sqlite3` (API sqlite3 backup, jamais une copie de fichier : la base est en WAL), puis efface tout cela ;
  si la sauvegarde échoue, rien n'est effacé. Une Presentation non archivée n'est jamais purgée. `backups/` n'est jamais vidé
  par JARVIS : retirer une sauvegarde est une décision humaine. Restaurer :
  [OPERATIONS.md](OPERATIONS.md#purge-définitive-des-présentations-archivées) ;
  contrat : [presentation-studio.md](presentation-studio.md#purge-definitive-des-archivees) ;
- **aucune rétention automatique** ; l'état de lecture et les identifiants d'objets
  de la scène n'y sont jamais écrits (mémoire de Core seulement). Depuis native-studio-playback-fix Slice 09, une lecture
  se montre dans Variantes sur une surface **en mémoire** et n'écrit plus aucun objet de la scène ni aucun registre.
  L'ancien registre `state/presentation-studio-stage-ledger.json` (Slice 12, à côté de `scene.sqlite3`, **hors** de
  `presentations/`) n'existe plus que sur un poste qui a fait tourner une version précédente : il ne liste que des
  identifiants de fenêtres de lecture du Studio ; au démarrage, Core archive ces fenêtres (et toute fenêtre
  `studio-stage-*` / `studio-aux-*` restée sur la scène), puis **met le fichier de côté**
  (`presentation-studio-stage-ledger.json.retired-<horodatage>`, jamais supprimé, jamais réécrit) ; illisible, il est gardé
  en `.corrupt-<horodatage>` (les trois plus récents) et la scène est balayée quand même. Ces fichiers ne se sauvegardent ni
  ne se déplacent avec les Presentations ; une sauvegarde de la racine doit inclure `presentations/`.
  Les prefabs que les scènes référencent vivent dans `prefabs/` : sauvegarder
  les deux ensemble.
- **Rechargement à chaud (Slice 06)** : le document de variante est en `schema_version` 3 (chaque scène porte
  `source_revision` et `last_valid_pin`, lus en v2 par une étape de montée de version, jamais réécrits à la
  lecture). Une scène dont `last_valid_pin` n'est pas `null` a un pin **pas encore vu monter** : ne pas la
  « corriger » à la main, le premier rapport de montage de la page la confirme ou la ramène en arrière. Les
  sources de scène sont des prefabs `presentation-studio.p<12 hex>.s<12 hex>` dans `prefabs/` ; Core archive
  (déplace, ne supprime jamais, hors purge définitive de leur Presentation archivée) vers `prefabs/.archive/` celles que rien n'épingle, et seulement quand l'index
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

Quand la valeur par défaut est utilisée (checkout de développement seulement :
jamais en produit installé), l'ancien `./data/memory` est copié une
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
