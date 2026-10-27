# Slice 08 — notes d'implémentation

Branche `wt/v12-s08` (worktree `pev12e`), partie de `58c6b177`. Commit d'implémentation `a4a220b9`.
Contrat écrit : `docs/macos-portability.md`. Checks Human : `HUMAN-CHECKS.md` (HV-V12-MAC-01).

**macOS n'est pas supporté. Rien n'a été exécuté sur un Mac.** Tout ce qui est macOS est testé sous Windows en
plateforme simulée ; le job CI macOS est écrit et lint, jamais exécuté (push réservé au Human).

## Changements

| Sujet | Fichiers | Effet |
|---|---|---|
| Racines par plateforme (adaptateur unique, au-dessus de l'existant) | `jarvis/installation.py`, `jarvis/data_root.py`, `jarvis/runtime/feedback_sessions.py` | `HostPlatform`, `host_platform()`, `product_home(platform=…)` : macOS `~/Library/Application Support/CIRCOE/Jarvis`, caches/journaux réservés sous `~/Library/Caches|Logs/CIRCOE/Jarvis`, `HOME` absolu exigé ; `ProductHome.label`/`sub_label` remplacent le libellé Windows codé en dur. Windows et `OTHER` : inchangés |
| Runtimes privés POSIX | `jarvis/private_runtime.py`, `jarvis/adapters/node_capability_runner.py` | `PackageLayout(install_root, platform)` : `bin/python3`, `bin/node`, `node/bin` en tête du PATH, `lib/python3.X/site-packages`, pas de `.exe` ; `channel_problems(platform=…)` ; `npm-cli.js` sous `lib/node_modules` (POSIX seulement) |
| Arbre de processus POSIX | `jarvis/runtime/owned_process_tree.py`, `product_launcher.py`, `claude_local.py`, `codex_local.py` | `PosixProcessGroupAPI` (session propre, `killpg`, refus d'un enfant hors de son groupe), `default_api()`, `spawn_kwargs(tree)` (Windows : exactement l'ancien `creationflags`) ; le lanceur crée un arbre par enfant aussi sur macOS et passe `start_new_session` seulement si l'arbre le demande |
| Verrou d'instance | `product_launcher.InstanceLock` | branche `fcntl.flock` inchangée, désormais testée (simulée + réelle dans la CI macOS) |
| Secrets | `jarvis/adapters/dpapi_sealer.py` | macOS : `UnavailableSealer(MACOS_KEYCHAIN_PENDING)` ; refus `credential_vault_unavailable`, jamais de clair (pas de `keyring` dans les dépendances) |
| Navigateur Remotion | `jarvis/adapters/remotion_render_runner.py` | macOS : Chrome, Edge, Chromium dans `/Applications` puis `~/Applications` |
| CLI Claude | `jarvis/runtime/brain_cli.py` | macOS : `~/.local/bin/claude`, `/opt/homebrew/bin/claude`, `/usr/local/bin/claude` (PATH minimal du Finder) |
| Paquet macOS (plan) | `packaging/macos/{runtimes.json,platform_policy.json,Info.plist,jarvis.entitlements,macos_package.py}` | épingles arm64/x64, politique de plateforme, modèles de bundle ; `check-pins`, `plan`, `verify` ; pas de `build` |
| CI | `.github/workflows/ci.yml` | job `macos` (`macos-latest` arm64, `macos-26-intel` x64), `contents: read`, aucun secret, 35 min calculées ; porte dure + découverte `continue-on-error` |
| Smoke | `scripts/core_smoke.py` | Core + Control Center d'un checkout en bac à sable, arrêt par référence `pid:début` |
| Porte de release | `scripts/release_test_gate.py` | `test_macos_portability*.py` ajouté à la suite `release` |
| Docs | `docs/macos-portability.md` (nouveau), `docs/release.md` (A13, HV-V12-MAC-01), `docs/windows-packaging.md`, `docs/local-data.md` | inventaire classé, table des chemins, processus, secrets, boucle locale, paquet, permissions, signature, CI, porte |
| Tests | `tests/unit/test_macos_portability.py` (49 tests, dont 2 `posix_only`) | correspondance des chemins des deux plateformes, Windows figé à l'octet, disposition et vérification d'un paquet macOS simulé, npm POSIX, navigateurs, refus des secrets, groupe de processus (noyau simulé), arguments de lancement, lanceur, `flock` simulé, épingles, plan, plist, politique, CLI Claude, smoke |

## Exécuté (Windows 11, ce poste)

- Résolution des chemins Windows avant/après (`win_paths_probe.py` : maison, racines, diagnostics, disposition du
  paquet, PATH des enfants, Documents, navigateurs) : **identique** (`win_paths_before.json` = `win_paths_after.json`).
- `tests/unit/test_macos_portability.py` : 47 passés, 2 sautés (`posix_only`).
- Balayage voisin : 313 + 413 passés (data_root, installation, known_folders/export, private_runtime, process_tree,
  owned_process_tree, product_launcher, local_secrets, dpapi, feedback, brain_cli, node runner, back brain, codex,
  claude console/gateway, render runner, screen capture, product_setup, product_readiness, windows packaging/installer,
  release tooling) ; aucun échec, rien de nouveau dans `tests/known_failures.json`.
- Porte `release` : 30 fichiers, 771 passés, 0 échec, 2 sautés (liens symboliques sans privilège). `verify_release.py` vert.
- `actionlint` 1.7.12 (binaire Windows officiel, SHA-256 contrôlé contre le fichier de sommes) : vert. La 1.7.7 de la
  V1 ne connaît pas le label `macos-26-intel`.
- Épingles macOS : les 4 archives (Python arm64/x64, Node arm64/x64) téléchargées, SHA-256 et taille recalculés =
  fichiers de sommes publiés ; dispositions `python/bin`, `node-v…/bin` vues ; archives supprimées.
- `scripts/core_smoke.py` en bac à sable (`%TEMP%\v12s08`, ports 63653-63654, `127.0.0.1`) : Core `/v1/health` OK
  (3,1 s), Control Center 200 (9,2 s), arrêt de nos deux processus, aucun restant.
- Build Windows de production depuis le commit propre `a4a220b9` : sonde OK (Python 3.14.6, Node 24.21.0, aucun outil
  du PATH), `package_sha256 175e7641…`, `verify` : paquet intact. `macos_package.py verify` sur ce paquet Windows le
  refuse (177 fichiers Windows nommés), comme attendu.
- Nettoyage : paquet (448 Mo) et bac supprimés après copie des bases du bac (`smoke-sandbox-copy/`, 7 fichiers
  `sqlite3`/`-wal`/`-shm`) ; aucun processus de la Slice restant (vérifié par ligne de commande).

Preuves : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s08\`.

## Écrit seulement (jamais exécuté)

- Tout le comportement macOS réel : carte des chemins sur un vrai `HOME`, `killpg` d'un vrai groupe, `flock` réel,
  import de `ctypes.wintypes` sur macOS par `owned_process_tree`, Chrome du Mac, npm du Node POSIX.
- Le job CI `macos` entier (porte dure, sonde de boucle locale, suite voisine, smoke Core sur macOS).
- Les modèles `Info.plist` / `jarvis.entitlements`, la disposition du bundle, la signature et la notarisation.

## Non vérifié, risques et suites

1. **Boucle locale** (probable bloquant) : Core écoute sur `127.77.0.1`, le bac à sable Remotion sur `127.77.0.2` ;
   macOS ne répond qu'à `127.0.0.1` sans alias `lo0`. Décision d'architecture à prendre (piste : `localhost` pour le
   bac à sable). Non corrigé : cela touche le modèle d'isolement Remotion.
2. **Secrets** : refus sur Mac ; un produit installé ne peut pas y enregistrer de clé. Trousseau à écrire sur un Mac.
3. **Paquet macOS** : aucun packager, aucun verrou de roues macOS (`pyobjc-*` attendus), fichier de licence de
   python-build-standalone à confirmer, minimum macOS 13.5 (Node 24) à confirmer.
4. **À adapter** listés dans l'inventaire : boîte d'erreur du lanceur (`osascript`), fenêtre de `claude auth login`,
   `_final_path` du Studio (`F_GETPATH`), notifications de fichiers (FSEvents), F9 et permissions TCC.
5. Groupe de processus plus faible qu'un Job Object (pas de démarrage suspendu, `setsid` d'un descendant, pas
   d'arrêt à la mort du propriétaire) : documenté, non compensé.
6. `test_brain_cli.test_known_locations_follow_the_official_installers` suppose Windows (il n'est pas dans la liste CI
   macOS).

## Checks Human

- Pousser la branche, lire les rapports du job `macos` (arm64, x64).
- Trancher la boucle locale sur Mac ; fournir les identifiants Apple Developer quand un paquet existera.
- `HV-V12-MAC-01` sur le Mac d'un collègue (`HUMAN-CHECKS.md`), après les prérequis.
