# Portabilité macOS

Statut au 2026-10-27 (Slice 08 de `jarvis-presentation-edition-v1-2`, décision Human HD-V12-03) :

> **macOS n'est PAS une plateforme supportée.** Une CI macOS verte ne veut pas dire « macOS supporté ». Aucun paquet
> macOS n'est construit, signé ni notarisé. Le support ne sera affirmé qu'après l'acceptation sur un vrai Mac
> (`HV-V12-MAC-01`, faite par le Human sur le Mac d'un collègue).

Règle : un seul code, des adaptateurs de plateforme ; jamais de branche Mac. Windows ne change pas : chaque adaptateur
garde à l'octet le comportement Windows d'avant (tests `tests/unit/test_macos_portability.py`, et comparaison
avant/après de la résolution des chemins Windows, identique).

Ce qui a été **exécuté** : tout sous Windows 11, avec une plateforme simulée (paramètre `platform`, module `sys`/`os`
remplacé, fonctions du noyau injectées). Ce qui ne l'a **jamais** été : quoi que ce soit sur macOS. Les tests
`posix_only` (verrou `flock` réel, arrêt d'un vrai groupe de processus) et le job CI `macos` sont écrits pour le
premier passage sur un runner GitHub, qui n'a pas encore eu lieu (le push est réservé au Human).

## Racines logiques (adaptateur unique : `jarvis/installation.py` › `product_home`)

| Racine | Windows (inchangé) | macOS (prévu) | Créée par |
|---|---|---|---|
| Maison du produit | `%LOCALAPPDATA%\CIRCOE\Jarvis` | `~/Library/Application Support/CIRCOE/Jarvis` | le lanceur (`ensure_home`) |
| Données (`state/`, `CONTEXT_GLOBAL/`, `boards/`…) | `<maison>\data` | `<maison>/data` | Core |
| Runtime (jeton, journaux, réglages du Control Center) | `<maison>\runtime` | `<maison>/runtime` | Core, lanceur |
| Configuration (`.env` du produit) | `<maison>\config` | `<maison>/config` | lanceur |
| Caches (réservé, aucun consommateur) | `<maison>\cache` | `~/Library/Caches/CIRCOE/Jarvis` | personne encore |
| Journaux (réservé, aucun consommateur) | `<maison>\logs` | `~/Library/Logs/CIRCOE/Jarvis` | personne encore |
| Exports (seulement) | `<Documents>\Jarvis` (API des dossiers connus) | `~/Documents/Jarvis` (`known_folders`, hors Windows) | premier export |
| Libellé de diagnostic | `%LOCALAPPDATA%\CIRCOE\Jarvis` | `~/Library/Application Support/CIRCOE/Jarvis` | `ProductHome.label` |

- Signal du produit installé : le même marqueur `jarvis-product.json` à côté du code, sur les deux plateformes.
- macOS : `HOME` absent ou relatif en mode installé = refus de démarrer (`ConfigurationError`), comme `LOCALAPPDATA`
  sous Windows. `JARVIS_DATA_ROOT` / `JARVIS_RUNTIME_DIR` gardent la priorité.
- Caches et journaux sous `~/Library/Caches|Logs` : réservés parce que macOS exclut `Caches` des sauvegardes Time
  Machine et que la Console lit `Logs`. Aucun code ne les crée : en V1 les journaux vivent dans `runtime/logs`.
- Un dossier `~/Documents/Jarvis` ne contient jamais d'état interne : la maison n'est jamais sous Documents, et
  `ExportDestination` refuse une racine d'export qui chevauche la maison.

## Inventaire des hypothèses Windows

Relevé sur `jarvis/`, `scripts/`, `packaging/` le 2026-10-27. Classement : **gardé** (déjà conditionné à la
plateforme, rien à faire), **adapté** (fait dans cette Slice, testé en plateforme simulée), **à adapter** (nécessaire
au produit sur Mac, pas encore fait), **Windows par nature** (n'a pas d'équivalent à porter ; macOS aura son propre
mécanisme), **outillage** (développement et essais seulement, hors produit).

| Sujet | Où | Classement | Détail |
|---|---|---|---|
| Maison du produit | `installation.py` | adapté | `product_home(platform=…)` ; libellés `ProductHome.label`, `sub_label` (`data_root.py`, `feedback_sessions.py`) |
| Dossier Documents | `adapters/known_folders.py` | gardé | `SHGetKnownFolderPath` sous Windows ; ailleurs `$XDG_DOCUMENTS_DIR` puis `~/Documents` |
| Forme de la racine d'export | `adapters/export_destination.py` | gardé | `:` après le lecteur et UNC vérifiés seulement sous `nt` ; liens refusés partout |
| Runtimes privés `.exe` | `private_runtime.py` | adapté | `PackageLayout(platform)` : `bin/python3`, `bin/node`, `lib/python3.X/site-packages`, PATH des enfants sur `node/bin` |
| `npm-cli.js` | `adapters/node_capability_runner.py` | adapté | `lib/node_modules/npm` à côté de `bin/node` (archives officielles POSIX) |
| Plateformes Remotion | `domain/remotion_capability.py` | gardé | `darwin-x64`, `darwin-arm64` déjà admis |
| Chrome / Edge pour Remotion | `adapters/remotion_render_runner.py` | adapté | Chrome, Edge, Chromium dans `/Applications` puis `~/Applications` |
| Balayage des restes d'un rendu | `remotion_render_runner.sweep` | gardé | PowerShell sous Windows, `pgrep -f` ailleurs |
| Arbre de processus borné | `adapters/process_tree.py` | gardé | Toolhelp + heure de création sous Windows ; `killpg` + `start_new_session` ailleurs ; jamais `taskkill /T` |
| Confinement des enfants (Job Object) | `runtime/owned_process_tree.py` | adapté | `PosixProcessGroupAPI` : session propre + `killpg` ; plus faible qu'un Job (voir *Processus*) |
| Enfants du lanceur, CLI Claude/Codex | `product_launcher.py`, `claude_local.py`, `codex_local.py` | adapté | `spawn_kwargs(tree)` : `creationflags` identique sous Windows, `start_new_session` ailleurs |
| Verrou d'instance unique | `product_launcher.InstanceLock` | adapté (tests) | `msvcrt.locking` / `fcntl.flock` : la branche POSIX existait sans test ; testée en simulé, et en réel dans le job macOS |
| Boîte de dialogue d'erreur du lanceur | `product_launcher.default_notify` | à adapter | `MessageBoxW` sous Windows ; ailleurs stderr, invisible pour une app lancée du Finder (`osascript` à prévoir) |
| Adresse de Core `127.77.0.1`, bac à sable `127.77.0.2` | `v2_config.py`, `remotion_sandbox_server.py`, `display_mcp.py` | à adapter | voir *Boucle locale* : bloquant probable sur Mac |
| Secrets (DPAPI) | `adapters/dpapi_sealer.py`, `runtime/local_secrets.py` | adapté (refus) | Trousseau non écrit : refus explicite, jamais de clair (voir *Secrets*) |
| CLI Claude introuvable hors PATH | `runtime/brain_cli.py` | adapté | `~/.local/bin/claude`, `/opt/homebrew/bin/claude`, `/usr/local/bin/claude` |
| Connexion `claude auth login` dans sa fenêtre | `runtime/brain_cli.start_sign_in` | à adapter | `CREATE_NEW_CONSOLE` sous Windows ; sur Mac, aucune fenêtre (Terminal via `open -a Terminal` à prévoir) |
| Console de débogage `wt.exe` | `runtime/claude_local.py`, `codex_local.py` | outillage | `CREATE_NEW_CONSOLE` ; surface développeur |
| Chemin réel d'un fichier ouvert | `adapters/remotion_studio_runner._final_path` | à adapter | `GetFinalPathNameByHandleW` / `/proc/self/fd` ; macOS retombe sur le nom résolu (prévoir `fcntl F_GETPATH`) |
| Longueur de chemin Windows | `safe_folders.py`, `board_memory_store.py`, `node_capability_runner.py` (`winreg` LongPathsEnabled) | gardé | conditionné à `nt` |
| `fsync` d'un dossier | `file_presentation_studio_store.py` | gardé | branches `nt` et POSIX |
| Notifications du système de fichiers | `adapters/file_change_notifier.py` | à adapter | `ReadDirectoryChangesW` seulement ; ailleurs `available` faux (FSEvents à écrire si un usage produit en dépend) |
| Capture d'écran (`gdigrab`, GDI) | `adapters/screen_capture.py`, `windows_display.py` | Windows par nature | refus nommé `UNSUPPORTED_PLATFORM` hors Windows ; une capture Mac serait `avfoundation` + permission « Enregistrement de l'écran » |
| Notifications Windows | `app.py` (`WindowsNotificationDelivery`) | Windows par nature | désactivées par défaut ; ailleurs `NullNotificationDelivery` |
| Installeur, registre `HKCU`, raccourcis | `product_setup.py`, `packaging/windows/setup_stub.cs` (`csc`) | Windows par nature | macOS : glisser `Jarvis.app` dans Applications ; mise à jour et réparation à concevoir (voir *Paquet*) |
| Paquet Windows (roues `win_amd64`, `pywin32`) | `packaging/windows/*` | Windows par nature | macOS : `packaging/macos/*` (plan) |
| Démarrage automatique | `scripts/windows_autostart.ps1` | Windows par nature | macOS : `LaunchAgent` à concevoir |
| Mot de réveil (openWakeWord, onnxruntime) | `requirements-internal.*` | à adapter | roues macOS à verrouiller par architecture ; build interne seulement (HD-V12-01) |
| Raccourci global F9 (`pynput`) | voix | à adapter | sur Mac, `pynput` exige Accessibilité / Surveillance de l'entrée ; dépendances `pyobjc-*` (`platform_policy.json`) |
| Micro (`sounddevice`/PortAudio) | voix | gardé (non éprouvé) | CoreAudio par la roue ; permission micro + entitlement `audio-input` |
| Harnais Remotion, `e2e_session_capture`, `testlab`, `worktrees.py` | `scripts/`, `jarvis/testlab/` | outillage | `taskkill`, `windll`, PowerShell : hors produit |

## Processus

`OwnedProcessTree` choisit son moteur par plateforme (`default_api`) : Job Object `KILL_ON_JOB_CLOSE` sous Windows
(inchangé), groupe de processus ailleurs (`PosixProcessGroupAPI`). Le lanceur, les CLI Claude/Codex en profil restreint
passent `spawn_kwargs(tree)` à leur `Popen` : sous Windows exactement l'ancien `creationflags`, ailleurs
`start_new_session=True` (l'enfant devient chef de session et de groupe ; `assign` refuse un enfant qui ne l'est pas).

Ce que le groupe POSIX ne garantit PAS, à la différence d'un Job :

- l'enfant tourne dès sa première instruction (POSIX ne sait pas démarrer un processus suspendu) ;
- un descendant qui appelle `setsid()` quitte le groupe et survit à `killpg` ;
- si le propriétaire meurt, rien ne tue le groupe (pas d'équivalent de `KILL_ON_JOB_CLOSE`).

Le verrou d'instance unique utilise `fcntl.flock(LOCK_EX | LOCK_NB)`, libéré par le noyau à la mort du processus.

## Secrets

Aucune liaison au Trousseau n'est dans les dépendances (`keyring` absent ; `cryptography` n'est qu'une dépendance
transitive) et aucun Mac ne permet d'éprouver les invites d'accès du Trousseau. `default_sealer` rend donc sur macOS un
`UnavailableSealer` qui le dit (`MACOS_KEYCHAIN_PENDING`) : `seal_settings` refuse avec `credential_vault_unavailable`
et ne touche à rien. **Jamais de clair.** Conséquence : un produit installé sur Mac ne peut pas encore enregistrer une
clé de fournisseur. C'est un bloquant de `HV-V12-MAC-01`.

Conception prévue (à écrire et éprouver sur un Mac) : une clé maîtresse aléatoire par usage (même séparation que les
entropies DPAPI) rangée dans le Trousseau de session (`security` en mode `-i`, jamais la valeur sur la ligne de
commande), et un scellement AES-GCM avec l'usage comme donnée associée, sous un schéma distinct de `dpapi-user-v1`.

## Boucle locale

Core écoute par défaut sur `127.77.0.1` et le bac à sable Remotion sur `127.77.0.2`. Windows répond à toute adresse
`127.0.0.0/8` ; macOS ne configure que `127.0.0.1` sur `lo0` : lier `127.77.0.1` y échoue (« Can't assign requested
address ») sans `sudo ifconfig lo0 alias`. Ce n'est pas vérifié sur un Mac ; le job CI le sonde (étape de découverte).
Les deux adresses sont réglables (`JARVIS_CORE_HOST`, `JARVIS_REMOTION_SANDBOX_HOST`) et le smoke macOS force
`127.0.0.1`. Changer le défaut sur Mac est une **décision d'architecture** : le bac à sable Remotion exige un autre
HÔTE que le Control Center (`docs/remotion-isolation.md` › *Origine* : les cookies se partagent entre ports d'un même
hôte ; `assert_distinct_origins` refuse un hôte partagé). Piste à évaluer : `localhost` pour le bac à sable, admis
comme hôte canonique et distinct de `127.0.0.1`. À trancher avant tout essai produit sur Mac.

## Paquet macOS (plan et squelette : `packaging/macos/`)

- `runtimes.json` : Python 3.14.6 et Node 24.21.0 (mêmes versions que Windows) pour **arm64** et **x64**. Node :
  archives officielles `nodejs.org` (`SHASUMS256.txt`). Python : python.org ne publie pas de Python relocalisable pour
  macOS ; la source est python-build-standalone (Astral, `install_only`, `SHA256SUMS` de la release `20260804`).
  Les quatre empreintes ont été relevées dans les fichiers de sommes ET recalculées sur les archives téléchargées le
  2026-10-27 (archives supprimées ensuite). Fichier de licence de Python : à vérifier au premier build.
- `platform_policy.json` : `pywin32` jamais dans un paquet Mac ; `pyobjc-*` (MIT) attendus pour `pynput` ; verrous
  `requirements-macos-{arm64,x64}.lock` à générer sur un runner macOS ; macOS 13.5 minimum (Node 24).
- `Info.plist` (modèle) : `com.circoe.jarvis`, `NSMicrophoneUsageDescription`, `NSAppleEventsUsageDescription`,
  `LSMinimumSystemVersion` 13.5.
- `jarvis.entitlements` : Hardened Runtime avec `device.audio-input`, `cs.allow-jit` (V8),
  `cs.allow-unsigned-executable-memory` (ctypes/libffi), `cs.disable-library-validation` (extensions des roues) ;
  pas d'App Sandbox (Jarvis lance Node, Chrome et la CLI Claude). À valider sur un Mac.
- `macos_package.py` : `check-pins`, `plan --arch`, `verify <paquet>` (= `private_runtime.verify_package` en
  disposition POSIX + aucun fichier `.exe/.dll/.cmd/.bat/.ps1/.pyd`, aucun module réservé à Windows). **Pas de
  commande `build`** : aucun paquet macOS n'existe.

Disposition prévue : `Jarvis.app/Contents/MacOS/jarvis-launcher` lance
`../Resources/package/runtime/python/bin/python3 -B -m jarvis launch` ; `Contents/Resources/package/` porte le même
arbre que le paquet Windows (`app/`, `runtime/python`, `runtime/node`, `licenses/`, manifestes). L'état de
l'utilisateur ne vit jamais dans le bundle (signé, en lecture seule) mais dans `~/Library/Application Support`.
Distribution : `Jarvis-<version>-macos-<arch>.dmg`.

### Permissions (TCC)

| Permission | Pourquoi | Déclaration |
|---|---|---|
| Micro | voix, mot de réveil | `NSMicrophoneUsageDescription` + entitlement `audio-input` |
| Accessibilité / Surveillance de l'entrée | raccourci global F9 (`pynput`) | aucune clé : invite TCC au premier usage, à guider dans l'UI |
| Enregistrement de l'écran | seulement si une capture Mac est écrite un jour | aucune clé : invite TCC |
| Automatisation (Apple Events) | ouvrir le Control Center dans le navigateur, si `open` ne suffit pas | `NSAppleEventsUsageDescription` |

### Signature et notarisation (documentées, non exécutées)

Prérequis Human : compte Apple Developer (Developer ID Application), identifiants App Store Connect (clé API) ou
mot de passe d'application, dans les secrets GitHub d'un environnement protégé. Étapes :

1. signer de l'intérieur vers l'extérieur chaque binaire et `.dylib`/`.so` (`codesign --force --timestamp --options
   runtime --entitlements packaging/macos/jarvis.entitlements --sign "Developer ID Application: …"`), puis le bundle ;
2. `codesign --verify --deep --strict` et `spctl --assess --type execute` ;
3. créer le `.dmg`, le signer, `xcrun notarytool submit --wait`, puis `xcrun stapler staple` ;
4. vérifier sur un Mac propre que Gatekeeper ouvre l'application sans avertissement.

Aucune de ces étapes n'est dans la CI : il n'existe ni identifiants ni paquet.

## CI (`.github/workflows/ci.yml`, job `macos`)

Runners GitHub au 2026-10-27 : `macos-latest` (macOS 26, arm64) et `macos-26-intel` (x64) ; `macos-13` n'existe plus.
Permissions `contents: read`, aucun secret. Étapes :

- **porte dure** : `check-pins`, `plan --arch`, `tests/unit/test_macos_portability.py` sur un vrai noyau macOS
  (y compris les tests `posix_only`) ;
- **découverte** (`continue-on-error`, rapports téléversés) : sonde de `127.77.0.1`, suite voisine (chemins,
  installation, processus, lanceur, export, Board, recherche, compilation Presentation), smoke Core + Control Center
  (`scripts/core_smoke.py`, bac à sable, `127.0.0.1`).
- **absente** : construction, installation et smoke d'un paquet macOS (le packager n'existe pas).

Vérifiée par `actionlint` 1.7.12 (binaire Windows officiel, SHA-256 contrôlé) ; jamais exécutée sur GitHub.

## Porte de support : `HV-V12-MAC-01`

La CI ne remplace pas un Mac : permissions, micro, écho, raccourci global, Trousseau, Gatekeeper et la boucle locale
ne se vérifient que sur une vraie machine. Liste de contrôle : `tasks/jarvis-presentation-edition-v1-2/slices/
08-macos-portability-build-validation/HUMAN-CHECKS.md`. Prérequis avant de la commencer : les « à adapter » marqués
bloquants ci-dessus (Secrets, Boucle locale, paquet construit et notarisé).
