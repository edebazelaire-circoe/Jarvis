# Slice 00 — READINESS

État : **READY**.

- Date : 2026-10-01. Agent 0 (orchestrateur), autonomie déléguée par le Human.
- Branche : `task/jarvis-session-context-recording-runtime`, créée depuis `main` = `11fcdc2`.
- Worktree de travail : `C:/Projects/jarvis/bsc`. Le checkout principal `C:/Projects/jarvis/jarvis` reste sur `main`, parce que le Jarvis habituel du Human en tourne et que cette tâche ajoute des migrations (v5+).
- Python : `.venv` du checkout principal, lancé depuis `bsc` (`PYTHONPATH=C:/Projects/jarvis/bsc`).

## 1. Écart entre le handoff et `main`

Le handoff a été planifié sur `96a9396` (= `origin/main`). Avant la création de la branche, `main` a été avancé à `11fcdc2`, sur instruction du Human. Ce fast-forward a apporté les 71 commits de `task/jarvis-generic-mcp-plugin-runtime`. Effets sur ce plan :

- `jarvis.sqlite3` est en **v4** (`mcp_plugins`, `mcp_credentials`), et plus en v3. Les migrations de cette tâche commencent donc à v5.
- Il existe un cinquième serveur natif, `jarvis-tools` (passerelle `list_tools`/`call_tool`), avec ses budgets. `FORWARDABLE_PREFIXES` contient maintenant `/v1/mcp/plugins` et `/v1/mcp/oauth/callback`.
- La phase B de la tâche MCP n'est pas terminée (HV-06-01, Q3). Elle ne recouvre pas ce plan.

## 2. Audit à l'aveugle (avant lecture des docs 01/02/03)

Trois audits Explore en lecture seule, menés sans lire ce dossier.

### 2.1 Session

- `JarvisSession` (`jarvis/domain/workspace_board.py:416`) porte `active_board_id`, `visited_board_ids` et `status` (open/closed). `SessionEndReason` (:152) vaut `new_session` ou `core_restart`.
- `SessionManager` (`jarvis/core/session_manager.py:108`) est le seul à écrire les Sessions. Au démarrage, `_open_at_start()` (:178) ferme la Session ouverte avec `CORE_RESTART` (:191-196), puis en ouvre une nouvelle sur le dernier Board, avec une nouvelle conversation Core. L'appel est fait par `v2_app.py:289-293` : `ensure_default`, puis `sessions.start`, puis `boards.start`.
- L'index unique partiel `idx_one_open_jarvis_session` (`sqlite_state.py:88`) n'autorise qu'une Session ouverte.
- Points d'entrée « nouvelle Session » existants :
  - `POST /v1/sessions/new` (`protocol/server.py:184`) ;
  - `POST /api/sessions/new` (`board_routes.py`) ;
  - le bouton `boardsNewSession` ;
  - `POST /api/agent/restart {"new_conversation":true}` ;
  - l'outil MCP `session_new` (`console_boards.py:310`).
- Les bindings `BoardConversationBinding` (:488) sont propres à un couple (Session, Board). Une Session qui se ferme ferme ses bindings : le binding de premier plan passe à `suspended`, les tâches de fond continuent.
- Tests qui figent le comportement actuel : `test_session_manager.py:210/235/257/313/338`, `test_board_switch_control_center.py`, `test_board_brains_*` et `tests/integration/test_board_session_e2e.py`. Côté doc : invariants 4 et 8 de `docs/boards.md:162-178`.
- Homonymes à ne pas confondre :
  - `"core_restart"` comme source de rejeu du mode d'interaction (`board_service.py:79`, `core/interaction_mode.py:136`) ;
  - `core_restarted` (jobs) ;
  - le `session_id` d'admission vocale dans les conversation events ;
  - la session Présentation du working set.
- Hors tâche : le worktree `sub-agents/jarvis-session-par-lancement` contient du travail **non commité** sur une base ancienne. Il définit une troisième notion, « session = lancement de Core » (`CoreLaunch`). Il n'est ni lu ni touché ici, et entre en conflit conceptuel avec D02.

### 2.2 Persistance et données

- `sqlite_state.py` : `_SCHEMA_VERSION = 4`. `_MIGRATIONS` est indexé par version produite, une transaction `BEGIN IMMEDIATE` par étape, avec sauvegarde `<base>.v<N>.bak`. `sqlite_scene.py` : v1, aucune migration.
- Racine de données : `jarvis/data_root.py:resolve_data_root()`. Elle contient `state/`, `history/` et `memory/`.
- Racine runtime séparée, dans le dépôt (`./runtime`) : `trace.jsonl`, `scene-captures/` (5 fichiers ou 24 h), etc.
- Il n'existe ni magasin générique d'artefacts ou de médias, ni dossier de travail par session. Les CLI cerveau tournent avec `cwd=project_root` (`control_center.py:1167`).

### 2.3 Événements, journal, contexte du cerveau

- Conversation events : table `conversation_events` (v2), écrite seulement par Core. Le contrat est dans `docs/conversation-events.md`. La timeline CNV les indexe par `conversation_id` et ignore `jarvis_session_id`.
- `RuntimeJournal` (`runtime/journal.py`) : un fichier `trace.jsonl` diagnostique, partagé par trois processus, sans identifiant ni rétention. Aucune notion d'« activité » ou de ledger produit n'existe.
- Contexte du cerveau, côté Core : `BrainContext` + `BrainBoardContext` (≤ 2048 caractères). Côté CC : `build_agent_brief` (`control_center.py:760`) + `render_board_brief`. Aucun résumé de Session (`Conversation.summary` n'a aucun écrivain).

### 2.4 Audio et capture

- **Micro** : seul le processus Voice l'ouvre (`sounddevice`). LiveKit ne sert qu'à l'AEC. `input_ownership.py` est un compteur en mémoire, propre au processus Voice. `AudioCaptureHub` n'existe qu'en PRESENTATION (24 kHz mono int16, blocs de 50 ms) et sa politique est fixe : `drop_oldest` (`capture_hub.py:99`). En SIMPLE, deux flux coexistent (Porcupine + tour).
- **Ambiant** : mémoire seulement, jamais de PCM sur disque, `authorizes_actions = False`, segments de 30 s maximum, une seule transcription en cours, aucune relance.
- **Transcription** : port `TranscriptionBackend.transcribe(AudioClip)`, en lot. Seul adaptateur : OpenAI (`gpt-4o-mini-transcribe` pour l'ambiant), sans relance HTTP. Si le fournisseur de la pile vocale n'est pas OpenAI, le blocage `presentation_transcription_unavailable` s'applique.
- **Écran** : aucune capture de bureau, aucun enregistrement d'écran. Ni ffmpeg sur l'hôte, ni Pillow, mss, opencv ou av dans le venv (numpy et sounddevice sont présents).
- **Capture de scène** : PNG du calque de scène rendu par l'onglet CC, ≤ 1280×720, ≤ 2 Mio. Stockage dans `runtime/scene-captures/`, rétention 5 fichiers ou 24 h.
- **Topologie** : le superviseur lance Core, puis UI, puis Voice.
  - La mort de Core termine tout l'arbre (`supervisor_v2.py:286-313`).
  - Voice redémarre seul (crash ou changement de pile vocale), de même que le CC.
  - Le cerveau est un sous-processus du CC.

### 2.5 MCP, routes et palette

- Cinq serveurs natifs : display, console, barehands, drive, tools. Les règles d'ajout d'un outil sont dans `tool-contract` §10.2, avec la parité vérifiée par `test_mcp_catalog.py`.
- `jarvis-console` : 9 616 o sur un budget de 10 000 o (marge d'environ 384 o).
- Routes Core : table unique `server.py:131-220`. Relais CC par `forward_json`, limité à la liste blanche `FORWARDABLE_PREFIXES` (`protocol/client.py:34`).
- Palette gauche (`control_center_barehands_hud.js:1768`) :
  - construite depuis `BH.describeTools()`, avec `role="toolbar"` ;
  - l'exclusion mutuelle vient du réglage `tool` ;
  - `test_barehands_palette_js.py:152` exige que les outils dessinés soient exactement les outils installés (`pointer`, `pan`, `select`).
- `CONTROL_SELECTOR` (`control_center_scene_page.js:2190`) inclut `#barehandsPalette`. Le précédent d'un hôte séparé est `control_center_interaction_mode.js`.

### 2.6 Task Types et routage

- Aucun vocabulaire Workspace Task Type n'existe : ni dans le dépôt, ni dans `C:\DevTools\skills-lib`, ni dans `~/.claude`.
- Aucune règle de routage « Claude Work Agent » n'est exposée.
- Les skills `/caveman`, `/coding-guideline`, `/impeccable`, `qa-verification`, `code-review`, `runtime-validation` et `agent-trace-analysis` existent toutes.

## 3. Décisions (agent 0, autonomie déléguée)

**D-TT — Task Types.** Le gate est levé, comme pour les six tâches précédentes : le vocabulaire n'existe pas. `task_type` reste `null`, et chaque `metadata.json` reçoit `task_type_resolution`. Pour « Claude Work Agent », la Slice 10 est confiée à un sous-agent Claude qui charge `/impeccable`. La limite est consignée (précédent : `jarvis-mcp-semantic-batch-inspector`).

**D-SESS — Sémantique de redémarrage et Boards (D02, résout « Board compatibility »).**

- Au démarrage, `SessionManager` **reprend** la Session ouverte : mêmes `jarvis_session_id`, `active_board_id` et `conversation_id` du binding actif.
- Il ne produit plus jamais `core_restart`. La valeur reste décodable pour l'historique, et les lignes historiques ne sont pas réécrites.
- Les bindings de la Session reprise sont réconciliés : `foreground` passe à `suspended` (leur CLI est mort avec l'ancien processus), puis `align_host` relance ou reprend la CLI par `agent_session_id`, comme pour un retour A/B/A.
- La première Session d'une base garde la règle d'adoption existante.
- `start_new_session()` reste la seule frontière.
- Les invariants 4 et 8 de `boards.md` et les tests listés en 2.1 changent **délibérément** (Slice 03), avec une justification dans le commit.
- Le nouveau modèle Context n'a aucune clé `board_id`.

**D-CTX — Owner Context.**

- `SessionContext` vit dans un nouveau module `jarvis/domain/session_context.py`, et non dans `workspace_board.py` qui est déjà gros.
- La persistance passe par `sqlite_state.py`, en **v5** (Slice 02).
- Le service appartient à Core et est exposé par `SessionManager` ou un `ContextService` voisin ; la Slice 01 tranche.
- Le dossier de travail est `<data_root>/sessions/<jarvis_session_id>/contexts/<context_id>/`.
- Une Session ouverte héritée reçoit **un** Context actif par défaut, avec l'origine `adopted`, sans historique fabriqué.
- Le dossier est hors du `cwd` de la CLI. La Slice 03 doit vérifier, par une trace réelle, que la CLI Claude peut y écrire (`--add-dir`) et que Codex le peut aussi, sinon l'écrire comme limite.

**D-ART — Registre et activité.**

- Tables génériques `artifacts`, `artifact_relations` et `session_activity` dans `jarvis.sqlite3`, en **v6** (Slice 04).
- Les payloads vont dans `<data_root>/artifacts/<artifact_id>/` (et non dans `./runtime`), sous des chemins relatifs à la racine de données.
- Le ledger d'activité est distinct des conversation events (aucun texte ambiant n'y entre comme tour adressé) et de `RuntimeJournal` (simple miroir diagnostique, avec des identifiants seulement).

**D-CAP — Owner de capture et garantie de continuité (D13).**

- **Core porte le `CaptureService`**. Il est la seule vérité d'état : machine d'état, intention durable, finalisation et réconciliation. L'état durable des captures est en **v7** (Slice 05, ou fusionné dans v6 si la Slice 04 le porte proprement).
- Core ouvre lui-même les sources. Le flux micro de l'enregistrement explicite est un flux `sounddevice` **distinct** de ceux de Voice : WASAPI partagé, déjà multi-flux en SIMPLE. Il n'y a donc aucun couplage avec `AudioCaptureHub` ni avec son `drop_oldest`, et la sémantique ambiante reste intacte (D12). Pour l'écran, l'encodeur éventuel est un sous-processus supervisé par Core.
- **Garantie V1, à documenter et tester** :

  | Mort de | Effet sur la capture |
  |---|---|
  | cerveau | ininterrompue |
  | Control Center | ininterrompue |
  | Voice (crash, changement de pile vocale) | ininterrompue |
  | Core (= tout l'arbre du superviseur) | partiel récupérable |

  Partiel récupérable signifie : au démarrage suivant, chaque capture non finalisée est réconciliée en artefact `partial`, avec en-tête WAV réparé et conteneur vidéo réparé ou marqué. Un `capture.gap` est écrit, et rien n'est relancé automatiquement.
- La Slice 05 peut contester ce choix avec des preuves (par exemple, PortAudio instable dans Core). La solution de repli est un processus enfant `jarvis capture`, client de Core, avec la même garantie.

**D-AUDIO — Format et transcription.**

- Le spool est en WAV PCM16, écrit par un thread d'écriture. La file entre le callback et l'écrivain est bornée **sans perte silencieuse** : si elle déborde, la perte est datée et enregistrée comme `gap`.
- La transcription se fait depuis le spool durable, avec `AmbientSegmenter` pour les frontières et `TranscriptionBackend` pour le texte. Elle gère relance et rattrapage.
- Sans fournisseur OpenAI, l'enregistrement fonctionne quand même et la transcription prend l'état `unavailable`, relançable.

**D-SCREEN — Dépendances écran (Slice 07).**

- Aucune dépendance système n'est supposée. Toute bibliothèque doit s'installer par pip, être épinglée, déclarée dans un extra `capture`, et sa licence consignée.
- Candidats à valider :
  - capture d'écran par `mss` (PNG natif, sans Pillow) ;
  - enregistrement par le binaire ffmpeg fourni par `imageio-ffmpeg` (`gdigrab`).
- La Slice 07 tranche avec une mesure réelle sur l'hôte : processeur, taille, perte d'affichage.

**D-MCP — Surface outil (Slice 09).**

- Un **nouveau serveur natif** (nom de travail `jarvis-capture`), et pas `jarvis-console` dont la marge est d'environ 384 o.
- Il suit la recette complète : `ServerMeta`, sous-commande `app.py`, `_capture_mcp_args`, `AGENT_SNAPSHOT_FLAGS`, variante de consigne, entrées `mcp_tool_meta`, parité catalogue.
- Les outils appellent le CC (`/api/...`), comme les outils Board. Le CC relaie vers Core par un préfixe ajouté **délibérément** à `FORWARDABLE_PREFIXES` (par exemple `/v1/contexts`, `/v1/captures`, `/v1/artifacts`).

**D-UI — Palette (Slice 10).**

- Un hôte frère `#captureRail`, posé sous la palette dans le même langage visuel. Il a son propre module (`control_center_capture_rail.js`), sans `data-bh-tool` et hors de `#barehandsPaletteStrip`.
- `test_barehands_palette_js.py:152` reste vert sans modification.
- `#captureRail` est ajouté à `CONTROL_SELECTOR`, avec des tests de non-chevauchement dans le style de `test_interaction_mode_hud_browser.py`.

**D-ISSUE.**

- `docs/presentation-audio-capture.md:120` mentionne `DROP_NEWEST`, alors que le code n'a qu'une politique. C'est consigné dans `Issues/presentation-capture-doc-drop-newest.md`, sans correction dans cette tâche.

## 4. Ligne de base des tests unitaires (`11fcdc2`)

Mesure faite dans le worktree détaché `C:/Projects/jarvis/bwt` : 349 fichiers `tests/unit/test_*.py`, 8 tranches au premier plan, avec `JARVIS_DATA_ROOT` isolé. Résultat : **10 492 passed, 9 failed, 6 skipped, 0 error**. Les 9 échecs se reproduisent aussi en isolement.

Ces 9 échecs sont **« not yours »** pour chaque implémenteur :

- `test_scene_group_drag_js.py` (5) :
  - 4 viennent de `ReferenceError: orbitTurns is not defined` dans `control_center_scene_interact.js:1414`. La fonction n'existe que de façon privée dans `control_center_scene_layout.js` (fusion `fd76479`).
  - 1 test lit le texte source et ne trouve plus son ancre dans `onPointerUp`.
  - Tests concernés : `test_a_group_move_keeps_recorded_offsets_and_leaves_unplaced_members_behind`, `test_dragging_n_objects_posts_one_translate_selection_and_confirms_every_layer`, `test_a_refused_group_move_rolls_every_layer_back_and_nothing_moving_sends_nothing`, `test_a_group_pushed_into_a_corner_keeps_every_orbiting_member_on_screen`, `test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`.
- `test_barehands_interaction_js.py` (2) :
  - `test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine` et `test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`.
  - Cause : le rebasage de la décision 19 n'est pas respecté (frame d'armement comptée deux fois).
- `test_brain_delegation.py` (1) :
  - `test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`.
  - Le test est périmé : il ne tient pas compte de `BRAIN_SETTINGS_PROMPT`. Déjà « not yours » dans la tâche MCP.
- `test_interaction_mode_hud_browser.py` (1) :
  - `test_le_mouvement_reduit_arrete_vraiment_le_halo`.
  - Le halo est déjà à `animation: none` sans réduction de mouvement. Cause probable : réglage Windows « effets d'animation » sur l'hôte. Non vérifié.

## 5. Validation du plan

- Graphe des dépendances (`slices/TODO.md`) : acyclique. Chaque dépendance pointe vers une Slice antérieure.
- Identifiants HV uniques : `HV-REC-AUDIO-001` (06), `HV-REC-SCREEN-001` (07), `HV-REC-UI-001` et `HV-REC-UI-002` (10), `HV-REC-E2E-001` (11).
- Les fichiers SLICE.md sont propres à chaque Slice (aucun gabarit). Les décisions ci-dessus les précisent sans les réécrire.
- Ordre d'exécution : 01, 02, 03, 04, 05, puis 06 et 07 en série (un seul implémenteur par worktree), puis 08, 09, 10, 11.
- Avant chaque Slice, un contrôle de fraîcheur ciblé est fait contre `main`.
