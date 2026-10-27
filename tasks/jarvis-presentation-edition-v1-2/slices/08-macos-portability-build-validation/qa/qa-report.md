# QA — Slice 08 (portabilité macOS, validation de build)

Branche `wt/v12-s08` (worktree `pev12e`), diff `58c6b177..ecb6a81c` (`a4a220b9`, `ecb6a81c`). QA du 2026-10-27,
lecture seule du code produit. Skills : `qa-verification`, `code-review`.
Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s08qa\`.

## Verdict : PASS avec réserves

Aucune régression Windows trouvée : arguments de création de processus, arrêts, chemins, recherche de la CLI Claude
et des navigateurs sont identiques avant et après, à l'octet (sonde comparée sur les deux commits, essai réel avec Job
Object). Les réserves portent sur le job CI macOS, qui ne peut pas passer tel qu'il est écrit (MA1), et sur le critère
d'acceptation de la Slice, qui n'est que partiellement atteint (MA2).

## Findings

### Bloquant
Aucun.

### Majeur

**MA1 — La porte dure du job `macos` échouera à son premier passage, pour une raison sans lien avec macOS.**
`.github/workflows/ci.yml:205` installe seulement `.[dev]` (pytest, pytest-asyncio). Or `tests/conftest.py:29-36`
(fixture `autouse`) importe `jarvis.core.v2_app`, qui tire `jarvis/audio/duplex.py:56` `import numpy as np`.
numpy n'est que dans les extras `voice`/`speaker`/`wakeword`.
Preuve : sous WSL Ubuntu (Python 3.14.4, venv propre avec les seules dépendances de `.[dev]`),
`pytest tests/unit/test_macos_portability.py` donne **49 erreurs** (`ModuleNotFoundError: No module named 'numpy'`,
`tests/conftest.py:36`). Après l'ajout de numpy seul, on obtient **47 passés et 2 sautés**, y compris les deux tests
`posix_only` (verrou `flock` réel, `killpg` réel des petits-enfants) sur un vrai noyau POSIX.
Les jobs Windows `tests`/`browser` de la V1 installent de la même façon (`ci.yml:76`, `:110`) : le défaut leur est
antérieur, mais la porte macOS en hérite. Correctif suggéré : installer numpy (ou un extra de test) dans les jobs,
ou rendre l'import de `v2_app` dans `conftest.py` indépendant de numpy.

**MA2 — Le critère d'acceptation de SLICE.md n'est que partiellement atteint (écart déclaré honnêtement).**
Le critère est : « produce and smoke-test a macOS package from CI ». Or aucun paquet n'est construit, et il n'y a ni
smoke en environnement propre sans Python/Node système ni smoke de rendu Remotion. Un artefact non signé ne demande
pourtant aucun identifiant. La documentation (`docs/macos-portability.md` › CI, « absente ») et IMPLEMENTATION.md le
disent clairement. La décision revient au PM : accepter le plan comme livrable de la Slice ou ouvrir une suite.

### Mineur

- **m1** `jarvis/runtime/owned_process_tree.py:7` et `:187` citent `OwnedProcessTree.popen_kwargs()`, qui n'existe
  pas. La fonction s'appelle `spawn_kwargs(tree)`.
- **m2** `docs/macos-portability.md:58` et `:84` disent que le lanceur passe `spawn_kwargs(tree)`. En réalité,
  `product_launcher.py:398-401` lit `tree.start_new_session` lui-même. Le comportement est équivalent, mais la
  description est inexacte.
- **m3** `packaging/macos/platform_policy.json:21` prévoit de générer le verrou x64 « sur macos-13 », alors que
  `ci.yml` et la documentation disent que `macos-13` n'existe plus (`macos-26-intel`).
- **m4** `ci.yml:206` : le nom d'étape « shape, SHA-256 » est flatteur, car `check-pins` vérifie la forme
  hexadécimale sans recalculer d'empreinte. `ci.yml:179` annonce « 46 tests » alors qu'il y en a 49.
- **m5** Suite de découverte macOS : `tests/unit/test_owned_process_tree.py:47` exige les drapeaux Windows sans
  condition. Il échoue désormais sur POSIX (vu sous WSL), comme 7 autres tests aux hypothèses Windows ou sans les
  extras Google (WSL : 8 échecs sur 141). Ce n'est pas bloquant (étape `continue-on-error`), mais le rapport sera
  bruyant.
- **m6** `jarvis/adapters/screen_capture.py:204-210` : sur macOS, `OwnedProcessTree()` réussit désormais (groupe
  POSIX), mais ffmpeg est lancé avec `creationflags=OwnedProcessTree.creationflags` sans `start_new_session`.
  `assign` refuse alors l'enfant, qui est tué. Le résultat reste un refus (`SOURCE_UNAVAILABLE`), avec un autre
  message, et ce cas n'est atteignable que si le refus `UNSUPPORTED_PLATFORM` en amont ne s'applique pas. À noter
  pour une future capture Mac.
- **m7** `jarvis/private_runtime.py:154` : `sorted(...)[-1]` est lexicographique (`python3.9` > `python3.14`).
  C'est sans effet avec un seul runtime livré.
- **Info** : les ports du cadre (64653-64656) font partie d'une plage exclue par Windows sur ce poste
  (`netsh … excludedportrange` : 64587-64686, WinError 10013). Le smoke a été refait sur 63753-63756.

## Vérifié OK

- **Windows, sites de processus** (ligne à ligne et à l'exécution) :
  - `spawn_kwargs` renvoie `{"creationflags": tree.creationflags}` quand `IS_WINDOWS` (= `os.name == "nt"`) ;
  - `OwnedProcessTree.creationflags` vaut `0x08000004` (inchangé) ;
  - le lanceur ne passe jamais `start_new_session` (`tree.start_new_session` est faux) ;
  - `flags |= CREATE_NO_WINDOW` est inchangé ;
  - `default_api()` renvoie `WindowsJobAPI` ;
  - `terminate`, `close_if_empty` et la voie taskkill/Job ne sont pas touchés. `close_fds` et `start_new_session`
    ne sont pas passés sous Windows, ni dans Claude, ni dans Codex, ni dans le lanceur.
- **Sonde avant/après** (`qa_win_probe.py`, exécutée sur les arbres exportés de `58c6b177` et `ecb6a81c`) :
  `product_home` (cas standard, UNC, espaces et accents), refus quand `LOCALAPPDATA` est absent ou relatif, et
  `HOME` ignoré sous Windows ; `detect_installation`, racines, libellés de diagnostic ; `PackageLayout`,
  `child_path`, `channel_problems` ; `npm-cli.js` ; Documents ; navigateurs Chrome/Edge ; `known_locations` de la
  CLI Claude ; `DpapiSealer` ; kwargs réels du lanceur avec un vrai Job.
  `diff` : **identique**, à la seule exception de l'attribut nouveau `start_new_session=False`.
- **Essai réel Windows** :
  - `scripts/core_smoke.py` en bac à sable (`%TEMP%\v12s08qa\sbx2`, ports 63753-63756) : Core `/v1/health` OK
    (3,1 s), Control Center 200 (2,8 s), arrêt propre, aucun processus restant.
  - Vraie CLI Claude au repos (`ClaudeLocalAgent`, profil `job_result`, le site modifié ; le cerveau
    `conversation` lancé par le Control Center n'a pas d'arbre et n'est donc pas concerné). Aucun message envoyé.
    Job réel (`in_job` vrai, 5 membres dont les MCP Python), puis `close_owned()` vrai. Les 5 PID sont morts,
    aucun orphelin.
- **POSIX** :
  - Simulé sous Windows, et réel sous WSL : groupe, `killpg`, refus d'un enfant hors de son groupe, `flock`.
  - Chemins macOS sous `~/Library`, avec `HOME` absolu exigé.
  - Runtimes `bin/`.
  - Chrome, Edge et Chromium sous `/Applications` puis `~/Applications`.
  - Secrets : `UnavailableSealer(MACOS_KEYCHAIN_PENDING)`, jamais en clair.
- **Épingles** : les 4 empreintes correspondent aux fichiers de sommes publiés, téléchargés à nouveau
  (`SHASUMS256.txt` de Node et `SHA256SUMS` de python-build-standalone). L'archive Python arm64 a été téléchargée
  à nouveau : SHA-256 `a39d12dc…` et taille 26170048 identiques, `python/bin/python3` présent. La licence se trouve
  à `python/lib/python3.14/LICENSE.txt`, ce qui renseigne le « to-verify ». `plan` et `verify` sont cohérents, et
  il n'existe pas de commande `build`.
- **CI** :
  - `actionlint` 1.7.12 est vert (le zip correspond au fichier de sommes publié) ;
  - matrice `macos-latest`/`macos-26-intel`, `contents: read`, aucun secret, 35 min ;
  - porte dure séparée des étapes `continue-on-error` ;
  - jobs Windows inchangés (le diff ne fait qu'ajouter).
- **Documentation** : « CI verte ≠ macOS supporté » est répété (doc, ci.yml, release.md A13, HUMAN-CHECKS). La
  boucle locale est décrite avec précision (`127.77.0.1` pour Core, `127.77.0.2` pour le bac à sable, `lo0`,
  variables d'environnement, contrainte `assert_distinct_origins`).
- **Tests Windows** :
  - nouveaux tests et premier lot voisin : 272 passés, 3 sautés ;
  - deuxième lot (back brain, codex, claude, export, render runner, setup, readiness, release tooling, screen
    capture, windows packaging) : 401 passés, 5 sautés ;
  - troisième lot : 201 passés et 1 échec connu (`test_brain_capability_parity`, `known_failures.json`) ;
  - porte `release` : 31 fichiers, 818 passés, 0 échec, **VERT**.
- **Mutations** (sur une copie exportée, 9 au total, **toutes tuées**) :

  | Mutation | Test qui la tue |
  |---|---|
  | `spawn_kwargs` Windows | `test_spawn_arguments_per_platform` |
  | drapeaux du Job | `test_windows_tree_class_flags_are_unchanged` |
  | libellé de `product_home` | `test_windows_home_is_byte_identical_to_v1` |
  | répartition `win32` | `test_sys_platform_maps_to_one_platform_family` |
  | raison du refus des secrets macOS | `test_macos_secret_sealer_refuses_and_says_why` |
  | session toujours passée par le lanceur | `test_the_launcher_never_passes_a_session_argument_for_a_windows_job` |
  | kwargs retirés de la CLI Claude | `test_back_brain_speculative` (pas les tests de la Slice) |
  | kwargs retirés de Codex | `test_back_brain_worker[codex]` |
  | `assign` POSIX permissif | test du refus hors groupe |

## Non vérifié

- Tout ce qui demande un vrai macOS : Python 3.14 sur Darwin, `killpg`/`flock` du noyau XNU, Chrome du Mac,
  Trousseau, TCC, bundle, signature et notarisation, le job CI lui-même (jamais exécuté sur GitHub).
- Le Linux de WSL ne fait que représenter un noyau POSIX.
- Le lancement de la CLI par l'interface du Control Center (exercé directement sur le site modifié, voir plus haut).

## Nettoyage

Bacs `%TEMP%\v12s08qa` supprimés après copie des bases (`sandbox-db-copy/`, 10 fichiers `sqlite3`/`-wal`/`-shm`).
Venv et sources WSL supprimés. Le worktree est resté propre (seul ce rapport a été ajouté). Aucun processus de la QA
ne reste. Le JARVIS vivant n'a pas été touché.
