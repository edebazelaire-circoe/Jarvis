# Slice 11 — Preuves (E2E, reprise, régression, documentation)

Date : 2026-10-01. Branche `task/jarvis-session-context-recording-runtime`, worktree `bsc`,
base `2b52630`. Implémenteur.

`<s11>` = `scratchpad/s11/` de la session (non versionné) : rapports JSON `out/*.json`
(`migrate.json`, `matrix-final.json`, `mic.json`, `soak.json`), capture du rail
`out/matrix-rail.png`, traces `*/runtime/trace.jsonl`, relevés d'arrêt de boucle
`*/runtime/e2e-loop-stalls.jsonl` et `e2e-faulthandler-*.txt`.

## 1. Harnais

`scripts/e2e_session_capture.py` (versionné, hors pytest). Il lance de vrais processus
`python -m jarvis core|control-center`, isolés :

- `JARVIS_DATA_ROOT` et `JARVIS_RUNTIME_DIR` sous `<s11>` ;
- Core sur 127.77.0.1:18953, Control Center sur 18954 ;
- jamais les ports 17653/17654, jamais la base réelle.

Deux crochets dans le processus enfant :

- **sources de capture au choix** :
  - audio *paced* : motif de parole écrit en temps réel par le vrai sink, avec la vraie
    réparation WAV ;
  - ou vrai micro ;
  - écran réel (GDI + ffmpeg 7.1) ou factice ;
  - transcription scriptée (phrases numérotées, la sixième est une injection) ou réelle ;
  - tout le reste est le câblage de production, dont l'enrichissement `haiku` réel ;
- **chien de garde de boucle** :
  - un battement de 100 ms ;
  - la pile du fil de la boucle est relevée dès 1 s de retard ;
  - `faulthandler` relève tous les fils à 3 s ;
  - une sonde chronomètre une ouverture de fichier hors boucle.

Écart assumé : la matrice raccourcit la cadence d'enrichissement (`JARVIS_E2E_ENRICH_FAST` :
10 / 30 / 20 s au lieu de 45 / 120 / 90 s) pour tenir en dix minutes. Ce qui est prouvé, à savoir
quel Context un tour écrit, n'en dépend pas.

## 2. Matrice des scénarios

| # | Scénario (SLICE) | Résultat | Preuve |
| --- | --- | --- | --- |
| 1 | Migrer une racine du `main` actuel | ✅ | voir le détail sous le tableau |
| 2 | Reprise de la même Session après un redémarrage | ✅ | voir le détail sous le tableau |
| 3 | Nouvelle Session explicite = seule frontière | ✅ | M11 : `POST /v1/sessions/new` 201 ; exactement 2 Sessions en base après tous les redémarrages (`new_session` + ouverte) |
| 4 | Créer, basculer, réactiver des Contexts ; isolation des dormants | ✅ | voir le détail sous le tableau |
| 5 | Enregistrement audio + transcription + captures d'écran | ✅ | voir le détail sous le tableau |
| 6 | Enregistrement d'écran concurrent (vrai ffmpeg) | ✅ | M4 : audio et écran `active` ensemble ; écran arrêté seul `complete` (4,3 s, 82 583 o), l'audio continue |
| 7 | Redémarrage du cerveau en pleine capture | ✅ | voir le détail sous le tableau |
| 8 | Redémarrage plus large | ✅ (Voice : par construction) | voir le détail sous le tableau |
| 9 | Requêtes par heure, nature, Session, Context ; provenance | ✅ | voir le détail sous le tableau |
| 10 | Cerveau démarré en cours de Session : rattrapage borné | ✅ | voir le détail sous le tableau |
| 11 | Parité API / MCP / rail | ✅ | voir le détail sous le tableau |
| 12 | Régression Board / Voice / PRESENTATION / scène / MCP | ✅ | §5 |
| 13 | Documentation | ✅ | §6 |

### Détail des scénarios

**1 — Migration d'une racine du `main` actuel** (`migrate.json`)

- `main` (`bwt` = `11fcdc2`) fabrique une base v4 : un Board et deux tours.
- Ce code la migre en **v7** :
  - une seule copie, `jarvis.sqlite3.v4.bak` ;
  - même `jsess_a330…` et même conversation ;
  - un Context `active` / `adopted` ;
  - les 2 tours sont gardés.
- `main` refuse la base v7, sur une copie : code de sortie 2, `Jarvis: state DB schema 7 is newer than supported 4`. La base reste en v7.
- Retour arrière, sur une copie :
  - base, `-wal` et `-shm` mis de côté, puis `.v4.bak` copié à la place ;
  - `main` redémarre en v4 ;
  - il applique ses propres règles : la Session est close `core_restart`, une neuve est ouverte.

**2 — Reprise de la même Session après un redémarrage**

- M1 : Core seul tué (`taskkill /F`), puis relancé.
- M2 : Core et Control Center tués, puis relancés.
- Dans les deux cas, même `jsess`, même conversation et même Context.
- `core.session.resumed` ×2, `core.session.opened` ×1.
- M8 : arrêt brutal pendant la capture, même `jsess` après relance.

**4 — Contexts et isolation des dormants**

- M3 :
  - B est créé avec un relais (`handoff_written`) ;
  - une capture d'écran est prise dans B (`context_id` = B) ;
  - A est réactivé : A `active`, B `dormant`.
- M7 :
  - un tour d'enrichissement écrit `summary.md` de A pendant que A est actif ;
  - après la bascule vers B, le tour suivant écrit B ;
  - l'empreinte de `summary.md` de A ne change pas (`108dc271…` avant et après) ;
  - `capture.association_changed` est écrit dans B.
- Brief (T1, T2) : le dormant B n'y figure que par son id et son titre.

**5 — Enregistrement audio, transcription et captures d'écran**

- Matrice (audio *paced*, transcription scriptée, M4 et M8) :
  - segments minutés, 35 segments, 2 760 caractères ;
  - lecture depuis `from_ms` ;
  - `addressed: false`.
- Micro réel, 3 s (`mic.json`) :
  - `complete`, 0 trou, 16 kHz, 96 044 o, soit 3,0 s ;
  - sans fournisseur, la transcription passe `unavailable` avec la vraie cause ;
  - `abandon` répond 200.
- Capture d'écran réelle : PNG 1920×1080, 186 678 o.
- Les médias réels sont supprimés par l'API (200/200) ; aucun fichier ne reste.

**7 — Redémarrage du cerveau en pleine capture**

- M5 : `POST /api/agent/restart` répond 200.
- La capture continue :
  - même `jcap_8c03…` ;
  - les octets passent de 387 244 à 582 444 ;
  - 0 trou, aucun `capture.gap`.
- T1, vrai tour après le redémarrage :
  - le cerveau appelle `capture_status` via MCP ;
  - il dit l'état exact et ce qui s'est dit ;
  - il cite l'injection de la salle comme parole ambiante et ne la suit pas.

**8 — Redémarrage plus large**

- M6, Control Center tué puis relancé :
  - octets 1 190 444 → 1 436 844 (pendant que le Control Center est mort) → 1 760 044 ;
  - 0 trou.
- M8, Core tué pendant un enregistrement audio et un enregistrement d'écran (4 s, vrai ffmpeg) :
  - audio et écran `partial` / `recoverable_partial`, `stop_reason: recovered` ;
  - `capture.gap` (`core_restart`) pour les deux ;
  - `status.recovery.partial` liste les deux ;
  - ffmpeg est mort avec Core (aucun orphelin) ;
  - WAV réparé : 104,5 s ; MP4 réparé : 4,0 s ;
  - octets rapportés avant la mort : 3 312 044, récupérés : 3 344 044 (rien de ce qui a été annoncé n'est perdu) ;
  - la transcription est rattrapée et finalisée `partial`.
- T2 (après la mort de Core) dit : « marqués partiels… un trou signalé ».
- Voice : non lancé. Aucun run n'avait de processus Voice, et la capture a tourné. Core ouvre son propre flux (D-CAP). Voice ne peut donc pas l'interrompre.

**9 — Requêtes par heure, nature, Session, Context ; provenance**

M9 :

- `kind=screenshot&jarvis_session_id=current` ;
- `context_id=<B>` ;
- `context_id=active&kind=audio_recording` ;
- `jarvis_session_id=<id>`, au moins 2 Contexts ;
- `since=<début de l'audio>&kind=transcript_segment` ;
- `relations?direction=dependents`, qui rend `transcribed_from` ;
- `transcript?from_ms=9000` : premier segment 6,8 à 9,7 s ;
- `/v1/activity`.

Toutes passent, via l'API.

**10 — Cerveau démarré en cours de Session : rattrapage borné**

- M10b : un nouveau Board donne un nouveau fil CLI, sans historique, même Session.
- L'enregistrement tourne : 27 segments, 2 094 caractères.
- Bloc du tour réellement reçu (journal de session du CLI) :
  - 5 340 o au total ;
  - queue de transcription de **1 495 caractères**, des points 8 à 26 : les plus anciens ne sont pas rejoués ;
  - `summary.md` 627 o, activité 599 o.
- Réponse T3 : « le plus ancien point numéroté est le point 8 et le plus récent est le point 26 ».

**11 — Parité API / MCP / rail**

- Au même instant, avec un audio actif :
  - `GET /v1/captures/status` : `audio active jcap_8c03…` ;
  - outil MCP `capture_status` dans T1 : même id, `active`, transcription `running` ;
  - rail dans Chrome sans tête (CDP) : audio `data-capture-state=active`, `aria-pressed=true` ; écran `idle` / `false` ; légende `REC 1`, emplacement `below`.

### Tours réels du cerveau (sonnet, run final)

| Tour | Demande | Outils | Réponse (extrait) | Coût |
| --- | --- | --- | --- | --- |
| T0 | « Réponds seulement : prêt. » | — | « Prêt. » | 0,0685 $ |
| T1 | état via `capture_status` + ce qui s'est dit | `ToolSearch`, `capture_status` | « Un seul enregistrement tourne : le micro… sans trou… la transcription suit avec une demi-seconde de retard » | 0,0996 $ |
| T2 | (Control Center relancé après la mort de Core) ce qui s'est passé, est-ce complet | aucun | « Les deux ont un trou signalé et sont marqués partiels… La transcription est finalisée, mais elle est partielle elle aussi. » | 0,0193 $ |
| T3 | (fil neuf) plus ancien / plus récent point vu | aucun | « le point 8 … le point 26 » | 0,0762 $ |

## 3. Coûts

- Run final : 0,2845 $. Détail :
  - 4 tours cerveau : 0,264 $ ;
  - 5 tours d'enrichissement, à 0,0032–0,0037 $ chacun ;
  - 3 descriptions, à 0,0014–0,0015 $ chacune.
- Runs de mise au point :
  - matrice sans cerveau : environ 0,015 $ d'enrichissement ;
  - matrice avec cerveau : 0,211 $ de tours + environ 0,015 $ ;
  - trois soaks : environ 0,06 $ d'enrichissement, dont 0,0287 $ mesuré sur le dernier.
- Total : **environ 0,59 $**, pour un plafond de 1,50 $.
- La transcription réelle n'a rien coûté : il n'y a pas de clé dans l'instance isolée.

## 4. Enquête : arrêt d'environ 12 s de la boucle

- **Reproduit.** Soak 1, 300 s, avec Core, Control Center, audio, écran et sondage à 1 Hz :
  - **11,2 s** de boucle figée dans le **Control Center**, au démarrage de son CLI ;
  - la pile est figée dans `claude_local.wait_ready` → `RuntimeJournal.emit("agent.ready")` → `journal._append` → `path.open("a")` ;
  - le fil du chien de garde, qui écrit dans le même dossier, est resté muet 10 s.
- **Ailleurs :**
  - matrice finale : 6,7 s figées dans un import paresseux (`importlib get_data`) sur la boucle du Control Center ;
  - une sonde hors boucle a mesuré une ouverture de fichier de 2,09 s ;
  - Core, sur tous les runs : pire lecture du statut 0,78 s, p99 0,04 s, aucun arrêt de plus de 3 s ;
  - 410 lectures sur 420 s avec 9 relances du Control Center : seuls les imports de démarrage dépassent 1 s (1,3–2,5 s).
- **Cause.** L'hôte a des pics de latence du système de fichiers de plusieurs secondes (antivirus, 1 à 2 Go de mémoire libre). Une E/S disque synchrone sur une boucle devient alors un arrêt complet du processus. L'arrêt observé pendant la QA de la Slice 10 est le même : `/board` et le relais sont sur le Control Center.
- **Corrigé dans le code de la tâche.** Core touchait le disque sur sa boucle. Ces appels passent dans un fil :
  - `SessionManager` : `ensure` du dossier, `handoff.md`, lecture de `summary.md`, écritures `summary.md` et curseur (temporaire + `fsync` + remplacement) ;
  - le worker d'enrichissement : lectures de `summary.md` et du curseur ;
  - `ArtifactService` : `store_payload` (capture d'écran) et suppression des dossiers.
- **Test de régression.** `tests/unit/test_core_disk_off_loop.py` :
  - chaque appel disque dort 0,4 s ;
  - la boucle ne doit pas rester bloquée plus de 0,2 s ;
  - le mutant qui remet la lecture de `summary.md` sur la boucle échoue.
- **Hors tâche.** `RuntimeJournal` écrit de façon synchrone dans tous les processus, et des imports paresseux tournent dans les gestionnaires du Control Center : `Issues/runtime-journal-sync-append.md`.

## 5. Tests (après correctif)

| Lot | Résultat |
| --- | --- |
| `test_core_disk_off_loop` (nouveau) | 2 verts ; mutant tué |
| Sessions, Contexts, enrichissement, rattrapage, hydratation, stockage, `test_session_manager` (8 fichiers) | 213 verts, 1 ignoré (lien symbolique sans privilège) |
| Artifacts, capture (service, store, domaine, API, relais, MCP), transcription, enrichissement rework, schéma, architecture (13 fichiers) | 359 verts |
| `test_screen_capture` (ffmpeg réel), `test_board_*`, `test_boards_*`, `test_session_protocol`, voix/Session, `tests/integration/test_board_session_e2e.py` | 339 verts |
| Fichiers qui scannent `scripts/` + `test_audio_recording_source`, PRESENTATION, voix du propriétaire (10 fichiers) | 510 verts, 1 ignoré (modèle absent) |
| Tests qui lisent la doc (`test_documented_routes`, `test_data_root`, `test_board_alerts`, `test_workspace_board_contract`, `test_barehands_clean_room`, `test_board_service`) | 148 verts |

Le balayage large à `2b52630` (11 217 verts ; seuls les échecs connus et une instabilité de charge) n'est pas rejoué. Le correctif ne touche que `session_manager`, `context_enrichment` et `artifact_service`. Les suites qui les exercent sont ci-dessus.

## 6. Documentation

- **Nouveau** `docs/session-context-capture.md`, page d'entrée de la fonctionnalité :
  - garanties, avec la preuve de chaque ligne ;
  - bornes de perte mesurées et rattrapage borné ;
  - installation, variables, coûts, confidentialité ;
  - dépannage ;
  - migration et retour arrière.
- `README.md`, `docs/OPERATIONS.md` : liens vers cette page.
- `docs/ARCHITECTURE.md` : table des processus.
- `docs/state-model.md` : `-wal`/`-shm` mis de côté au lieu d'être supprimés (règle `CLAUDE.md`) ; captures et dossiers `sessions/` dans le retour arrière ; règles de l'ancien binaire.
- `docs/local-data.md` : une base v4 → v7 n'a que `.v4.bak` ; refus de `main`.
- `docs/session-context.md`, `docs/artifacts.md` : disque hors de la boucle.
- `docs/capture.md` : lien vers la page d'entrée.
- `docs/boards.md` : définition périmée de la Session (« Starts when Core starts ») corrigée.

## 7. Processus

Chaque processus est lancé puis arrêté par le harnais (`taskkill /T /F`) :

| Run | PID |
| --- | --- |
| migrate | Core 41544, 41160 ; Core `main` 29516, 11208 |
| matrice finale | Core 26564, 27928, 33156, 40980 ; Control Center 28752, 21408, 35324, 31824 ; Chrome 38852 |
| mic | Core 21856 |
| dernier soak | Core 40552 ; Control Center 43412, 24908, 32972, 42796, 16872, 3360, 34488, 11400, 43424, 17904 |

- Les PID sont ceux des lanceurs du venv. Leurs enfants, CLI `claude` et ffmpeg, sont tués avec l'arbre.
- Après coup, aucun processus ne porte `scratchpad\s11`, 18953 ou 18954 (`Get-CimInstance Win32_Process`).
- Médias réels :
  - 2 enregistrements d'écran et 1 capture par run de matrice, supprimés par l'API ou à la main ;
  - micro et capture du run `mic`, supprimés par l'API.
- Il ne reste que des PNG synthétiques et un MP4 factice (octets nuls) du soak.
