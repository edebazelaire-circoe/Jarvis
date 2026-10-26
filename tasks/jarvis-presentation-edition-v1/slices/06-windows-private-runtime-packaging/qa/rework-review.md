# Slice 06 — contre-revue de la reprise QA

Relecteur : agent QA indépendant (code-review + qa-verification). Date : 2026-10-26.
Plage relue : `fa60429b..48972b1a` (`a60a2767` docs, `c89dd253` code/tests/doc, `48972b1a` LOG + I-007), worktree `pev1`.
Aucun code produit modifié. Aucun JARVIS lancé, aucun build lancé. Mutations faites sur une copie
(`git archive HEAD` → `<scratchpad 448345f0>\s06rr\base`), jamais dans le worktree (`git diff --quiet HEAD` vérifié).

## Verdict

**PASS. Aucun bloquant, aucun majeur.** Les deux majeurs de la QA (docs corrompues, bytecode non déterministe) sont
corrigés et chaque mineur déclaré corrigé l'est réellement. Il reste trois mineurs sur des trous de test (mutations
survivantes) et deux observations. Aucun ne justifie une nouvelle reprise. Ils peuvent aller dans `I-007`.

## 1. Docs et octets

- `git ls-files --eol` : `docs/local-data.md`, `docs/remotion-runtime.md`, `docs/windows-packaging.md` = `i/lf`, comme à
  `2d6ca879` et `f29d41cf^`. Aucun CR dans les blobs de `HEAD` (`git show HEAD:… | grep -c $'\r'` = 0). À `fa60429b`, il y
  avait du CRLF (`od -c` : `\r\n` dès la ligne 3).
- Le diff contre `f29d41cf^` est minimal : `local-data.md` 5+/1- et `remotion-runtime.md` 1+/1-. Le texte est juste :
  `` `<installation>\app\` ``, `` `<installation>\runtime\` ``, `` `<installation>\runtime\node` ``, la barre oblique
  inverse est littérale et il n'y a plus de BEL.
- J'ai balayé les 233 fichiers ajoutés ou modifiés de `2d6ca879..HEAD` (texte, hors binaires) : **0** caractère de
  contrôle et **0** CR isolé. Le VT du LOG (S04) a disparu. Aucun blob n'est en `i/crlf` ni `i/mixed` (197 `i/lf`, 36
  `-text` = PNG).

## 2. Déterminisme

- `compileall_argv` impose `-j 1` et `unchecked-hash`. La mutation **A2** (`-j 1` → `-j 0` dans `compileall_argv`) est
  **tuée** par `test_bytecode_is_compiled_in_a_single_process`.
- Preuve des deux builds (`<scratchpad>\s06rw\evidence`) : `runtime-manifest-A.json` et `runtime-manifest-B.json` sont
  identiques octet pour octet (`cmp`). `package_sha256 ecdf881d…`, `source_revision c89dd253`, sonde verte.
- Autres sources possibles de non-déterminisme, jugées sans effet :
  - Horodatages : `tree_sha256` hache `chemin relatif\0sha256(contenu)` trié, sans mtime. Le paquet est un dossier, pas
    un zip.
  - Ordre des fichiers : `iter_tree` est trié.
  - Mode d'invalidation : `unchecked-hash` stocke un hachage de la source, sans mtime. `-s out` retire le préfixe du
    dossier de build de `co_filename`. `PYTHONHASHSEED=0` est appliqué.
  - Métadonnées pip : `--require-hashes --no-deps` avec `--find-links`, donc pas de `direct_url.json`. Les lanceurs
    (`bin/`, `Scripts/`) et leurs lignes `RECORD` sont retirés. `INSTALLER` est constant.
- Résidu non prouvé :
  - Les deux builds ont tourné sur le même poste, avec le même cache et le même pip du `.venv`. La reproductibilité
    d'un poste à l'autre, notamment avec une autre version de pip et son format de `RECORD`, n'est pas démontrée.
  - Voir aussi m1 ci-dessous.

## 3. Mineurs déclarés corrigés

| Point | Constat | Preuve |
| --- | --- | --- |
| Manifeste mal formé typé | Corrigé. `_check_manifest_shape` lève `ValueError`, d'où `runtime_manifest_invalid`, au lieu d'une `AttributeError`. Les `root`/`executable` absolus, avec lecteur, `..` ou vides sont refusés. Le manifeste réel (`runtime/python`, `runtime/python/python.exe`) passe. | 10 cas paramétrés. Mutation **S** (`product` non contrôlé) tuée. |
| Build ≠ `--rev` | Corrigé, sans refus intempestif. Le contrôle passe avant toute lecture des entrées. | Essai réel en lecture seule dans `pev1` : `ensure_inputs_match(HEAD)` passe. `48972b1a~1` passe aussi : seuls le LOG et l'Issue diffèrent. `fa60429b` est refusé en nommant `jarvis/app.py`, etc. Une révision inconnue donne `git rev-parse --verify … a échoué (code 128) : fatal: …` avec les prérequis. |
| `/v1/health` `degraded` | Corrigé. Voir le détail plus bas. | Mutation **R** (la réserve écrase aussi `fail`) tuée. |
| Zip Slip | Corrigé. `/x`, `\x`, `C:x`, `C:\x`, `..` sont refusés, et la destination résolue doit rester sous la cible (zip et tar). | 7 cas paramétrés. Voir m3 pour la garde `resolve`. |
| `wake-word install` | Corrigé, et refusé seulement dans le produit installé `presentation`. `status` reste permis. | `install_refusal(installed=False, presentation)` donne `None`, de même que `(True, full)`. Un test de bout en bout vérifie qu'aucun réseau n'est appelé et qu'aucun dossier de modèles n'est créé. Mutation **W** (ignorer `installed`) tuée. |
| `verify` (fichiers en trop, manifeste illisible) | Corrigé. Il signale les fichiers en trop à la racine et sous `runtime\`. Un BOM, un JSON invalide ou une forme invalide donnent `ÉCHEC : paquet altéré`, sans traceback. Les arbres `app`/`licenses`, le manifeste tiers et `package_sha256` sont désormais testés : les mutations M5 de la QA sont couvertes. | Mutation **U** (`unexpected_entries` retiré) tuée. |
| `jarvis-barehands` | Il n'est pas déclaré en `presentation`, et l'avertissement `barehands.mcp_unconfigured` disparaît dans cette seule édition. En `full`, la déclaration est **identique** : même expression `BarehandsMcpTarget("127.0.0.1", ui_port, runtime_root)` (`jarvis/app.py:1841-1842`). Le JARVIS quotidien est en `full` : le `.env` du dépôt principal ne contient pas `JARVIS_PRODUCT_EDITION`, et la variable est vide dans l'environnement. | Le test `full` vérifie que l'avertissement reste émis. Voir m2 pour le câblage d'`app.py`. |
| Sonde (`probe_problems`) | Factorisée et testée champ par champ : 9 cas. Cela couvre la mutation M10 de la QA. | — |
| FFmpeg imageio (M4 de la QA) | Couvert. Un faux module injecté renvoie un chemin en développement et `None` en produit installé. | — |
| Docs | `windows-packaging.md` décrit les prérequis, la règle « entrées de la révision », `verify`, `-B` pour le lanceur S07, l'essai avec `JARVIS_OPEN_BROWSER=0`, et l'exception des fichiers tiers non compilables. Le texte correspond au code. | — |

### Détail : `/v1/health` `degraded`

- `runtime_reserve` ne renvoie quelque chose que si `status` vaut `degraded` ou `invalid`.
- En développement, `diagnostics()` renvoie `{"mode": "development", "source": "path"}`, sans `status`, donc pas de
  réserve. Le JARVIS de développement n'est donc **jamais** `degraded` à cause de ce changement (test :
  `_health({"mode": "development", …})["status"] == "ok"`).
- Une cause propre à Core, comme `fail`, n'est pas masquée par la réserve.
- J'ai relu les consommateurs de `/v1/health`. **Aucun ne lit `status`, tous lisent `ready`**, qui reste `true` :
  - `jarvis/app.py:1203-1205` : démarrage de la voix, `if not health.get("ready")`.
  - `jarvis/runtime/deployment.py:416-418` : `_await_health`, `last.get("ready")`.
  - `jarvis/runtime/declaration_relay.py:333` : ne lit que `store_id`.
  - Le volet d'attente de la voix dans `project-cli` (`C:/DevTools/project-cli/config/projects/jarvis.json:109`) :
    `(Invoke-RestMethod …/v1/health).ready`.
  - Le `healthUrl` du launcher vise `/api/status` du Control Center, pas `/v1/health`.
  - `/v1/health` n'est pas dans `FORWARDABLE_PREFIXES`, donc l'interface du Control Center ne le relaie pas.
  - Aucun JS ne le lit.
- Conclusion : `degraded` n'est traité nulle part comme une panne fatale.
- La preuve runtime de l'implémenteur (`v1-health-no-node.json`) montre `ready: true`, `status: degraded` et un
  `detail` qui nomme `node: private_runtime_missing`.

## 4. Mutations (copie au scratchpad)

Script : `<scratchpad 448345f0>\s06rr\tools\mutate.py`. Lots : `test_windows_packaging`, `test_private_runtime`,
`test_agent_capabilities`, `test_wake_word_install_command`. Le test dé-sélectionné
`test_the_human_decisions_named_by_the_policy_exist_in_the_slice` échoue seulement parce que la copie n'a pas `tasks/`.

| # | Mutation | Résultat |
| --- | --- | --- |
| A1 | `precompile` appelle `compileall` en ligne avec `-j 0` (sans `compileall_argv`) | **survit** (m1) |
| A2 | `compileall_argv` en `-j 0` | tuée |
| C | `BUILD_INPUTS` sans `pyproject.toml` | **survit** (m3) |
| D | `safe_destination` sans la garde `resolve().is_relative_to` | **survit** (m3, défense en profondeur déjà couverte par les contrôles lexicaux) |
| H | `app.py` déclare `BarehandsMcpTarget` même en `presentation` | **survit**, y compris avec `test_app`, `test_barehands_command_channel`, `test_product_edition`, `test_installed_product_root` (m2) |
| R | la réserve écrase aussi un `status` ≠ `ok` | tuée |
| W | le refus de `wake-word install` ignore `installed` | tuée |
| U | `verify` sans `unexpected_entries` | tuée |
| S | forme de `product` non contrôlée | tuée |

Résultat : 5 mutations tuées sur 9.

## Findings

### BLOQUANT
Aucun.

### MAJEUR
Aucun.

### MINEUR

**m1 — Le déterminisme est imposé sur l'assistant, pas sur son usage**

Emplacement : `packaging/windows/build_package.py:367` (`precompile`), testé seulement via `compileall_argv`
(`tests/unit/test_windows_packaging.py`, `test_bytecode_is_compiled_in_a_single_process`).

La mutation A1 survit : `precompile` pourrait reconstruire sa ligne de commande sans `compileall_argv` sans que rien ne
le voie.

Recommandation : tester `precompile` avec un `subprocess.run` simulé et vérifier `-j 1` sur l'argv reçu.

**m2 — Le câblage « pas de `jarvis-barehands` en `presentation` » n'est pas testé**

Emplacement : `jarvis/app.py:1841-1842`.

Le test `test_bare_hands_absent_from_presentation_is_intended_not_a_warning` construit `ControlCenter(barehands_mcp=None)`
directement. La mutation H survit à tous les lots voisins. Le seul test qui exerce ce site d'`app.py`,
`test_app::test_the_control_center_receives_a_tools_gateway_target…`, est déjà en échec sur `main`.

Le comportement réel a été observé par l'implémenteur dans le paquet installé (pas de `barehands-mcp.json`), mais aucune
régression future ne serait détectée.

Recommandation : extraire la décision dans une fonction pure (`barehands_target(edition, …)`) et la tester pour
`presentation` et pour `full`.

**m3 — Deux gardes du build sans test qui les distingue**

- Mutation C : `test_the_build_refuses_a_working_tree_that_differs_from_the_revision` compare l'appel à
  `B.BUILD_INPUTS` lui-même. Retirer `pyproject.toml` de la liste passe donc inaperçu, alors que la doc le promet.
  Recommandation : comparer à la liste littérale attendue.
- Mutation D : la garde `resolve().is_relative_to` de `build_package.py:200` n'est jamais atteinte par les cas testés,
  puisque les contrôles lexicaux refusent avant. Le risque est faible.

### OBSERVATIONS

- `wake_word_install._process_install_refusal` suit `process_edition()`. Dans un produit installé, un
  `JARVIS_PRODUCT_EDITION=full` posé à la main rend donc `install` possible. C'est cohérent avec la règle
  d'édition existante (la variable prime). À trancher avec HV-PACKAGE-04 si l'on veut un refus lié à
  l'installation seule.
- Le refus de Bare Hands suit l'édition, pas l'installation. Un checkout lancé avec `JARVIS_PRODUCT_EDITION=presentation`
  (bac à sable) n'a donc plus `jarvis-barehands`. C'est le comportement demandé, et il ne touche pas le JARVIS quotidien
  (`full`).

## Tests exécutés (`.venv` du dépôt principal, depuis `pev1`, avant-plan)

| Lot | Résultat |
| --- | --- |
| `test_private_runtime`, `test_windows_packaging`, `test_wake_word_install_command`, `test_agent_capabilities` | 154 passés |
| `test_control_center_mvp`, `test_data_root`, `test_installed_product_root`, `test_product_edition`, `test_node_capability_runner`, `test_process_tree`, `test_screen_capture`, `test_wake_word_docs`, `test_presentation_wake_word_wiring` | 290 passés, 3 ignorés (ffmpeg absent) |
| `test_barehands_command_channel`, `test_barehands_calibration_agent`, `test_mcp_catalog`, `test_claude_tools_gateway_args`, `test_barehands_migration_sweep`, `test_app` | 300 passés, 1 échec connu (`test_app::…tools_gateway_target…`, `AttributeError data_root`, déjà sur `main`) |

## Non vérifié

- Aucun build ni lancement. La reproductibilité repose sur les manifestes A/B de l'implémenteur, relus et comparés
  ici, pas sur un build refait.
- Le comportement de `verify` sur un vrai paquet n'a pas été vu ici : seulement sur un faux paquet construit par le
  test, plus le journal de l'implémenteur.
- Pas de second poste : la reproductibilité d'une machine à l'autre n'est pas prouvée.
