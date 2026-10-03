# Slice 09 — Preuves (E2E, migration v8, sous-agent sur un Board archivé, déploiement)

Date : 2026-10-03. Branche `task/jarvis-board-memory-workspace-inspector`, worktree `bbm`,
base `184accc`. Implémenteur. Dossier des pièces : `evidence/` (à côté de ce fichier).

## 1. Matrice automatisée

Fichier : `tests/integration/test_board_workspace_e2e.py` (8 tests, ~37 s).

Banc : celui de `test_board_session_e2e.py`, sans aucun service factice.

- Core **réel** : `JarvisCoreApplication` + `LocalProtocolServer`, SQLite et racine de
  données sous `tmp_path`.
- Control Center **réel**, en HTTP, câblé comme dans `jarvis/app.py` :
  - `boards_dir` ;
  - `jarvis-workspace` ;
  - relais `/api/workspace/*`.
- Côté MCP : le **vrai** serveur FastMCP `jarvis-workspace` (`build_server`), avec un vrai
  client MCP en mémoire. Il parle HTTP au vrai Control Center.
- Seul l'exécutable `claude` est une doublure : un vrai processus stream-json qui note ses
  arguments et chaque message reçu.

| # | Scénario (contrat Slice 00) | Test | Résultat |
| --- | --- | --- | --- |
| a | Migration v7 → v8 d'une base réelle, `.v7.bak`, données intactes, usage normal | `test_a_v7_root_made_by_the_v7_code_migrates_once_keeps_everything_and_then_works` | ✅ |
| b | Mémoire de Board à travers un redémarrage de Core | `test_board_memory_and_its_ledger_survive_a_core_restart_and_the_session_resumes` | ✅ |
| c | Bascule + hydratation : la mémoire de A dans le tour de A, jamais dans celui de B | `test_each_board_turn_carries_its_own_memory_and_never_the_other_boards` | ✅ |
| d | Inspection historique non activante (chaque route de lecture, chaque outil MCP de lecture) | `test_inspecting_old_and_archived_boards_through_every_read_route_and_tool_activates_nothing` | ✅ |
| e | Parité écran / MCP : mêmes résultats, mêmes codes | `test_the_screen_routes_and_the_brain_tools_give_the_same_results_and_the_same_codes` | ✅ |
| f | Évasions de chemin de bout en bout (HTTP + MCP), vraie jonction NTFS | `test_path_escapes_are_refused_end_to_end_by_the_screen_and_the_brain_including_a_real_junction` | ✅ |
| g | Board archivé : lectures partout, écritures nulle part | `test_an_archived_board_is_readable_everywhere_and_writable_nowhere` | ✅ |
| — | La fixture v7 est du texte, fabriquée par le code v7 | `test_the_v7_fixture_is_text_made_by_the_v7_code` | ✅ |

**Stabilité** : 3 passages consécutifs, 8/8 verts à chaque fois (35,8 s, 36,1 s, 38,2 s).
Les passages de mise au point précédents sont exclus de ce compte.

**Mutation** : la garde d'archivage de `WorkspaceService._writable_board` a été neutralisée.
Les tests (e) et (g) échouent alors ; la garde a été restaurée.

### Détail

**(a) Migration v7 → v8.** La fixture `tests/fixtures/sqlite_state/state_v7_real_shaped.sql`
est le dump SQL d'une base fabriquée par le **code v7** :

- source : `origin/main` `467232f`, dans un worktree temporaire `b7e` (supprimé ensuite) ;
- générateur : `evidence/make_v7_fixture.py` ;
- contenu :
  - deux Sessions, dont une close par `new_session` ;
  - quatre Boards : `default` ; Atlas, actif, avec résumé, tâche et référence legacy ;
    Borée, visité ; Archive 2025, archivé ;
  - trois Contexts ;
  - trois Artifacts, dont une provenance `derived_from` ;
  - le ledger, deux tours.

Aucune base n'est versionnée : seul son dump texte l'est, comme `state_v1.sql`. Le test
recrée les dossiers de Context que le code v7 avait créés. Ce qui est vérifié :

- la base passe en v8 ;
- **une** sauvegarde `jarvis.sqlite3.v7.bak`, identique ligne pour ligne à la base v7
  (`iterdump`) ;
- aucune ligne perdue dans aucune table ;
- une seule table neuve, `board_artifact_links`, vide : pas de rattrapage ;
- la Session ouverte est reprise sur Atlas avec ses deux tours ;
- les Boards v7 sont lus avec la nature `empty` ; résumé, tâches et références legacy sont
  intacts ;
- aucun dossier de mémoire n'est inventé ;
- l'historique v7 reste lisible : Session close, ses Boards, ses Artifacts, la provenance ;
- l'usage normal marche : écriture de mémoire, Artifact neuf lié `active_board`, lien
  `explicit` d'un ancien Artifact ;
- au redémarrage : ni seconde migration ni seconde sauvegarde, même Session, mémoire relue.

**Même chose avec de vrais processus** (`evidence/migrate_real.py`, `evidence/migrate.json`) :

- `python -m jarvis core` du worktree `bbm` sur une copie de la racine v7 :
  - v8 ;
  - `jarvis.sqlite3.v7.bak` (en v7) ;
  - même Session ;
  - `lost_rows: {}` ;
  - écriture de mémoire en 201.
- Second démarrage : même Session, mémoire relue, toujours une seule `.bak`.
- Le code v7 (`b7e`), sur une copie de la base v8 :
  - code de sortie 2 ;
  - message `Jarvis: state DB schema 8 is newer than supported 7` ;
  - la base reste en v8.
- Retour arrière, sur une copie :
  - base, `-wal` et `-shm` mis de côté ;
  - `.v7.bak` copiée à la place ;
  - le code v7 redémarre en v7 sur la **même Session**.

**(b) Redémarrage.**

- Avant l'arrêt, sur A et B : écriture, `mkdir`, remplacement avec `expected_sha256`, ajout,
  déplacement, suppression.
- Ledger : 9 lignes `board.*`, attribuées au bon Board.
- Après l'arrêt et la relance de Core (le Control Center reste en vie) :
  - même `jarvis_session_id`, même Board actif, même Context ;
  - toujours une seule Session ;
  - lignes du ledger identiques ;
  - arbre identique ; contenus relus.
- `last_opened_at` de A est **avancé** par la reprise. Celui de B reste `null`.
- Une écriture faite après la reprise est rattachée à la même Session.

**(c) Hydratation.** La preuve est le message que le CLI reçoit : stdin de la doublure.

- Tour sur A : le résumé, un fichier et le localisateur de A.
- Ce même tour ne contient ni le résumé, ni les fichiers, ni l'identifiant de B.
- Après la bascule vers B : l'inverse, avec la nature `meeting`.
- Une écriture sur A pendant que B est actif n'atteint pas le tour de B. Elle est là au
  retour sur A.
- Le Context ne change pas au fil des bascules, et rien n'est copié dans `sessions/`.
- Chaque lancement du CLI reçoit `--add-dir <data_root>/boards` et le `--mcp-config` de
  `workspace-mcp.json`.

**(d) Non-activation.**

- Données : un historique réel construit par les routes de l'écran, avec une Session close
  qui a visité Borée (mémoire, Artifact lié) et un Board archivé.
- Lectures :
  - 39 lectures HTTP : toutes les routes `/api/workspace/*` de lecture, plus `/api/boards*`,
    `/api/sessions*` et `/api/artifacts/{id}` ;
  - 18 appels d'outils MCP de lecture.
- La photographie prise avant (l'état une fois retombé) et après est identique :
  - le nombre de lignes de **chaque** table ;
  - les lignes Sessions, liaisons et Boards ;
  - le listing de `boards/` (taille et `mtime`) ;
  - l'autorité de parole et le mode ;
  - le premier plan du pool ;
  - le nombre de CLI lancés.

**(e) Parité.**

- Succès identiques entre écran et outil : texte, `sha256`, taille et `eof` d'une lecture ;
  arbre ; recherche ; inspection ; liste des liens ; empreinte et taille d'une même écriture.
- Ledger : seule l'origine diffère (`user` côté écran, `brain` côté outil).
- Un lien posé par l'écran est vu `changed: false` par l'outil : c'est la même table.
- 14 refus donnent le même code par HTTP et par MCP : `memory_exists`, `memory_conflict`,
  `memory_too_large`, `memory_not_found` ×2, `memory_not_text`, `memory_path_invalid`,
  `board_archived` ×2, `board_not_found` ×2, `session_not_found`, `artifact_not_found`,
  `board_is_active`.
- Écart connu et voulu : au-delà de 262 144 **caractères**, le schéma MCP refuse avant
  d'envoyer (« Argument invalide »). Le test utilise donc 140 000 « é », soit 280 000 octets,
  pour atteindre `memory_too_large` des deux côtés.

**(f) Évasions.**

- 10 chemins, chacun essayé sur 5 opérations (lecture, arbre, écriture, déplacement vers,
  déplacement depuis), par HTTP et par MCP. Les codes sont identiques des deux côtés, et ce
  sont toujours `memory_path_escape` ou `memory_path_invalid` selon la forme du chemin ;
  `memory_path_escape` pour tout `..`, `notes/door` et ce qui passe par la jonction.
- Les chemins : `../`, `notes/../../`, `..\`, `C:/…`, `C:x`, `/etc/…`, UNC, la **vraie
  jonction NTFS** `notes/door`, un fichier derrière elle, le Board voisin par `../`.
- `board_id` n'est pas un chemin : `board_voisin` donne `board_not_found` des deux côtés.
- La jonction est listée comme lien et n'est jamais parcourue. Une recherche n'y trouve rien.
- Ce qui reste intact : le dossier extérieur (octets), le Board voisin, le premier plan.
- Une suppression récursive retire la jonction sans toucher sa cible.

**(g) Board archivé.**

- 10 écritures écran refusées `board_archived` : écriture, ajout, `mkdir`, déplacement,
  suppression, lier, délier, renommer, changer de nature, basculer.
- Les 9 équivalents MCP sont refusés de même.
- Les lectures marchent par les deux chemins.
- Après ces refus : fichiers identiques, aucune ligne de ledger, premier plan inchangé.

### Fichiers voisins, lancés une fois chacun

| Fichier | Résultat |
| --- | --- |
| `tests/integration/test_board_session_e2e.py` | 7 passed |
| `tests/unit/test_schema_migrations.py` | 8 passed |
| `tests/unit/test_workspace_mcp.py` | 66 passed |
| `tests/unit/test_workspace_inspection_api.py` | 51 passed |
| `tests/unit/test_workspace_memory_mutations.py` | 65 passed |
| `tests/unit/test_board_memory_hydration.py` | 31 passed |
| `tests/unit/test_board_memory_contract.py` | 124 passed |
| `tests/unit/test_workspace_board_contract.py` | 72 passed |
| `tests/unit/test_board_alerts.py` | 31 passed |
| `tests/unit/test_data_root.py` | 7 passed |
| `tests/unit/test_documented_routes.py` | 3 passed (était **rouge** à `184accc`, voir §4) |

Le balayage large de la suite revient à un autre agent ; il n'est pas lancé ici.

## 2. Trace réelle : sous-agent délégué sur un Board **archivé**

Ce cas manquait : S06 a couvert un sous-agent sur un Board actif ancien, et la QA S06 un
Board archivé sans délégation.

**Montage** (`evidence/trace_s9.py`, `evidence/run_cc_strict.py`) :

- vrais processus `python -m jarvis core` (port 18971) et Control Center (18972), lancés
  depuis `bbm` ;
- données et runtime en scratch ; visualiseur coupé ; processus tués avec leur arbre à la
  fin.

**Isolation des outils** : la piste de `Issues/workspace-prompt-without-config.md` est
appliquée.

- `run_cc_strict.py` lance le Control Center normal, mais ajoute `--strict-mcp-config` au
  CLI `claude` et en retire `--chrome`. Ce sont deux lignes de harnais ; le code produit
  n'est pas modifié.
- Effet : l'`init` du CLI ne monte que `jarvis-display`, `jarvis-console`,
  `jarvis-workspace`, `jarvis-capture` et `jarvis-tools`. Ni `jarvis-drive` ni
  `claude-in-chrome` (`evidence/trace-key-rows.json`).
- Le prompt et les outils de Jarvis sont ceux de la production.

**Mise en place**, par les routes de l'écran :

1. « Projet Kepler » est créé en nature `meeting`. On y bascule dans la Session 1.
2. Sa mémoire est écrite : `summary.md` et `decisions.md` (LYRA, **KEPLER-31**, 12 novembre).
3. On revient sur `default`, puis on ouvre une **Session neuve**.
4. Kepler est **archivé**.
5. « Projet Atlas » est créé et devient le Board actif.

**Tour unique** : Core `POST /v1/conversations/{id}/brain-turns`, avec
`addressing: "addressed"` et `source: "text"`. La consigne :

> « Envoie un sous-agent inspecter l'ancien Board archivé « Projet Kepler » sans l'ouvrir :
> qu'il lise sa mémoire et l'historique de ses Sessions, puis me dise ce qui avait été décidé
> et dans quelle Session. »

**Chemin** (`evidence/turn-delegated-archived.json`, extrait des transcriptions du CLI et du
sous-agent) :

| Qui | Appel | Résultat |
| --- | --- | --- |
| cerveau | `Agent` `[general] Inspecter Board archivé Kepler` (arrière-plan) ; la consigne nomme les outils de lecture et interdit d'ouvrir ou d'écrire | réponse immédiate en une phrase : « Un sous-agent inspecte Kepler en lecture seule, sans ouvrir le Board… » |
| sous-agent | `ToolSearch select:` 7 outils `mcp__jarvis-workspace__*` en un appel | schémas chargés |
| sous-agent | `board_list {include_archived: true}` | 3 Boards, Kepler `archived` |
| sous-agent | `board_inspect {Kepler}` | `archived`, `active: false`, 1 Session |
| sous-agent | `board_memory_tree {Kepler, depth 4}` | 2 fichiers |
| sous-agent | `session_list` | 2 Sessions |
| sous-agent | `board_memory_read decisions.md`, puis `summary.md` | texte complet, `eof` |
| sous-agent | `session_get {Session close}` | la Session de Kepler, close |
| réveil | relais oral (`agent.unsolicited_result`, `core.brain.notice_relayed`, `spoken: true`) | « … le fournisseur retenu est LYRA (code KEPLER-31), et le lancement est reporté au 12 novembre. Le Board n'a eu qu'une seule Session, celle du 2 octobre vers 23h16, aujourd'hui close… Rien n'a été ouvert ni modifié. » |

Ce que montre la trace (journal du serveur : six `board.tool`, six `core.workspace.read`) :

- **Outils de lecture seulement.** Aucun `board_switch`, aucune écriture, aucun outil
  fichier, aucun refus. Le sous-agent dit honnêtement ce qu'il ne peut pas affirmer : qui a
  décidé, et le rattachement exact à la Session, qui est déduit.
- **Premier plan inchangé.** Le diff de `evidence/state-0-before.json` et
  `evidence/state-1-after.json` est **vide** :
  - `active_board_id` (Atlas) et la liaison de premier plan ;
  - l'autorité de parole ;
  - les Boards de la Session ;
  - Kepler : `status: archived` ; `last_opened_at` et `updated_at` inchangés ;
  - les fichiers de Kepler (taille et `mtime`) ;
  - les lignes `board.*` du ledger : aucune ;
  - le nombre de Sessions : 2.
- **Optimisation possible** (non bloquante) : `board_list` et `session_list` sont redondants
  quand le nom suffit, mais justifiés ici, puisque l'identifiant n'était pas donné.

**Coût** : 0,119 $ pour le tour du cerveau (6,7 s). **0,251 $** cumulés pour le processus :
tour, sous-agent (12 s) et réveil. Le budget était de 2 tours à ~0,3 $ ; un seul a servi.

## 3. Documentation (passe finale)

- `docs/boards.md` :
  - *Board kind* : le panneau Boards montre et règle la nature (la phrase « not yet » était
    périmée) ;
  - limite 8 précisée : un autre Board se lit par `board_id` sans charger sa conversation ;
  - **limite 9** neuve : v8 à sens unique, retour arrière ;
  - *End-to-end proof* : le nouveau fichier et cette preuve.
- `docs/local-data.md` : la migration v8 et le retour arrière, mesurés.
- `docs/state-model.md` : ce que perd une restauration (liens, `board_kind`) ; `boards/`
  reste sur le disque.
- `docs/OPERATIONS.md` : « Mise à jour vers cette version (schéma v8) » pour l'opérateur.
- `docs/ARCHITECTURE.md` :
  - nouvelle ligne pour `WorkspaceService`, le magasin, `board_artifact_links`, les routes
    et le relais ;
  - routes citées corrigées (§4).
- Termes périmés vérifiés absents : « Slices 07-08 à venir », outils Board sur
  `jarvis-console` (la seule mention restante est l'historique « Moved » de §10.9),
  « Core start = new Session » (déjà corrigé en S01), kinds d'activité à soulignés.

## 4. Écart trouvé et corrigé

`tests/unit/test_documented_routes.py` était **rouge** à `184accc`. Causes, dans
`docs/ARCHITECTURE.md` :

- `/api/workspace/*` (ligne Board/Session, S06) et la section du gestionnaire (S07) : la
  regex lit `/api/workspace/`, qui n'est pas un préfixe ;
- `/api/artifacts/{id}` alors que la route enregistrée est `{artifact_id}`.

C'était une régression de cette tâche, corrigée ici (`/api/workspace*`,
`/api/artifacts/{artifact_id}`).

## 5. Restes

- Les vérifications humaines HV-WS-UI-001 et HV-WS-UI-002 : script dans `HUMAN-CHECKS.md`,
  à faire après la fusion.
- `Issues/workspace-prompt-without-config.md` reste ouvert. Le harnais de trace applique
  `--strict-mcp-config` de son côté ; le produit ne le fait pas.
