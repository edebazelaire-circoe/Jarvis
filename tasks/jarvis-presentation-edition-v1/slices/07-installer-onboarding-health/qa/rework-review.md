# Slice 07 : contre-revue de la reprise QA

Relecteur : agent QA indépendant (`code-review` + `qa-verification`). Date : 2026-10-27.

Portée : `943570aa..a08c4583`, soit `728201eb` (code, tests, doc, I-009) et `a08c4583` (LOG), sur
`task/jarvis-presentation-edition-v1` (worktree `pev1`). Aucun code produit n'a été modifié. Aucun JARVIS, aucun
installeur réel et aucun build n'ont été lancés. Le Core `127.77.0.1:17653` n'a pas été touché. Sondes et mutations
tournent au scratchpad de la session `448345f0-…`, dans `scratchpad\s07rr\` :

- `probe_rework.py` : sondes R1 à R10 ;
- `mutate_rr.py` : mutations ;
- `mut\` : copie `git archive` de HEAD.

## Résumé

La reprise corrige ce qu'elle annonce.

- **B1** : le script différé attend la fin du processus, ne retire la clé qu'après la suppression effective, et laisse
  un reste reconnu si la suppression échoue.
- **M1** : le retour arrière dit vrai (`rollback_failed`), et l'installation suivante répare.
- **Garde du dossier étranger** : un manifeste forgé seul ne suffit pas.
- **Lanceur** : il refuse sans marqueur. « Quitter JARVIS » demande d'abord un arrêt propre, puis passe à `terminate`
  après l'échéance.

Les sondes P1 à P4 de la première revue ne reproduisent plus. Les mutations ciblées sont tuées, sauf une : l'ordre
« écarter avant d'effacer » du retour arrière n'est pas couvert. Il reste des mineurs, dont un enchaînement
démontrable mais très improbable : le script différé peut effacer une réinstallation toute fraîche si le PID qu'il
surveille est réutilisé.

**Recommandation (le PM décide) :** pas de bloquant ni de majeur. Les mineurs peuvent rejoindre I-009.

## Preuves

### Tests

Lancés en avant-plan depuis `pev1` avec `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider` :

| Lot | Résultat |
| --- | --- |
| `test_product_setup`, `test_windows_installer`, `test_product_launcher`, `test_brain_cli`, `test_product_readiness`, `test_product_readiness_js` | 95 passés |
| `test_product_readiness_browser`, `test_private_runtime`, `test_windows_packaging`, `test_control_center_shell_layers`, `test_product_connectors` | 166 passés |
| `test_control_center_relay_whitelist`, `test_app`, `test_product_edition`, `test_product_edition_ui_js`, `test_presentation_edition_ui_browser` | 115 passés, 1 échec connu (`test_app::…tools_gateway_target…`) |
| `test_control_center_presentation_rail_browser`, `test_control_center_presentation_rail_js`, `test_browser_harness_safety`, `test_status_centre_browser`, `test_global_launcher_browser` | 83 passés |
| `test_fullscreen_commands`, `test_capture_relay`, `test_prefab_relay`, `test_remotion_relay`, `test_testlab_http`, `test_memory_settings_endpoints` (utilisateurs de `READ_GUARDED_ROUTES`) | 198 passés |

### Sondes

`probe_rework.py`, exécuté contre le `jarvis` de `pev1`. Tous les chemins sont sous `s07rr\rr-uom6hd5_`, avec la
ruche JSON, et le script `cmd.exe` différé tourne pour de vrai.

| Sonde | Scénario | Résultat |
| --- | --- | --- |
| R1 (= P1) | Le processus désinstalleur vit 6 s et tient `pythonw.exe` | Pendant qu'il vit, le manifeste et la clé restent (`(True, True)`). Après sa fin : dossier supprimé, clé retirée, état retiré, réinstallation en mode `install`. Le journal montre `debut : attente…`, puis `processus termine…` 6 s plus tard, puis `dossier supprime, cle … retiree`. |
| R2 | PID « réutilisé » : le script surveille un autre `python.exe` vivant, qui ne tient aucun fichier, pendant qu'on réinstalle | La réinstallation réussit (`update`) et la clé est présente. Quand l'autre processus finit, **la nouvelle installation est effacée et la clé retirée** : `fresh install exists: False \| key: False`. Voir mn1. |
| R3 | Cible `r3 (été) l'a;b,c=d+é 日本\…\Jarvis` et dossier `tmp dir (x)` | Supprimée. Le voisin leurre `Jarvis keep` et le parent sont intacts. `A&B`, `R%D`, `x!y` et `c^d` sont refusés en `target_unsafe`. Cible par défaut sous un profil `Dupont & Fils` : `target_unsafe` (mn3). |
| R4 | `%TEMP%` = `t&m%p!d (x)` | La suppression aboutit et le script s'efface. **Le journal n'est écrit nulle part** : le `%` seul est mangé par `cmd`, voir mn3. |
| R5 | `%TEMP%` inutilisable (un fichier) | `FileExistsError` remonte en `setup_failed`. Le dossier reste `jarvis`, la clé reste, les raccourcis sont déjà retirés, et l'état vaut `uninstall`. Une nouvelle désinstallation réussit. |
| R6 | Jonction `runtime\link` vers un dossier étranger (script différé et suppression directe) ; cible = jonction vers un dossier étranger | Le dossier étranger est intact dans les deux cas : ni `rmdir /s` ni `rmtree` ne suivent la jonction. Cible-jonction : `not_a_jarvis_folder`, fichier intact. |
| R7 | Faux : état forgé ; manifeste forgé seul ; manifeste et marqueur forgés ; `C:\` | Résultats dans l'ordre : `leftover`, `foreign`, `jarvis`, `foreign`. Voir Flagged F1. |
| R8 (= P2) | Manifeste illisible | `not_a_jarvis_folder`, `thesis.docx` intact. |
| R9 (= P3) | Retour arrière bloqué par un fichier verrouillé | `rollback_failed`, `rolled_back: False`, dossier `leftover`. Le message dit « Redémarrez Windows, puis relancez l'installation ». L'installation suivante répare (`resumed: True`) et le parent ne contient plus que `Jarvis`. |
| R10 | `.failed-*` non effaçable après son renommage (antivirus) | Le refus nomme le reste. **L'installation suivante réussit mais laisse `Jarvis.failed-…` pour toujours** (mn2). |

P4 (barre oblique inverse finale) est couverte par
`test_the_stub_passes_a_target_with_a_trailing_backslash_intact_to_python`, qui compile l'amorce et lit l'argv réel de
Python ; ce test passe. `Quote` relu : il suit les règles de `CommandLineToArgvW`.

L'essai réel de la reprise (`s07rw\evidence`) a aussi été relu :

- `launch-quit.json` : `child_stopped_cleanly` pour `ui` puis `core`, arrêt en 2,3 s, aucun processus restant ;
- `dev-launch.json` : refus `not_installed_product` ;
- `logs\jarvis-uninstall.log` : attente de 10 s du `pythonw.exe` réel, puis suppression.

### Mutations

Faites sur la copie `s07rr\mut`, jamais dans le worktree.

| Mutation | Résultat |
| --- | --- |
| MA (B1) : pas d'attente du processus | tuée (`test_the_deferred_removal_waits_for_the_real_end…`) |
| MB (B1) : clé retirée même si le dossier reste | tuée (`test_a_deferred_removal_that_cannot_finish_keeps_the_key…`) |
| MC1 (retour arrière) : effacer la copie ratée au lieu de l'écarter | **SURVIVANTE** (mn4) |
| MC2 (retour arrière) : l'ancien programme n'est jamais restauré | tuée |
| MD (garde étrangère) : marqueur non exigé | tuée (`…never_deleted_nor_replaced[no_marker\|other_product]`) |
| ME : tout état fait un « reste » | tuée (`test_a_state_file_never_turns_a_foreign_folder_into_a_leftover`) |
| MF (lanceur) : pas de demande d'arrêt propre | tuée (deux tests de « Quitter ») |

### Fichiers

`git ls-files --eol` donne `i/lf` pour les 18 fichiers de `943570aa..a08c4583`. Leurs blobs ne contiennent aucun CR
ni aucun caractère de contrôle. Seule la copie de travail de `LOG.md` est `w/crlf` (`core.autocrlf`), ce qui est
cosmétique.

## Vérification point par point

1. **B1 : script `%TEMP%\jarvis-uninstall-<pid>-<UTC>.cmd`** (`jarvis/product_setup.py:712-769`, `:806-825`).
   - **Attente de la fin réelle.** Le script interroge `tasklist /fi "PID eq N" | find /i "<image>"` une fois par
     seconde, pendant 30 min au plus. Il surveille donc PID + nom d'image, sans l'heure de début. Sur une
     réutilisation du PID, le script attend un étranger puis efface quand même : R2, mn1. Comme l'interrogation a
     lieu chaque seconde, la fenêtre de réutilisation après la fin réelle est de 1 s au plus.
   - **Reprises bornées.** 40 essais espacés d'environ 3 s.
   - **Ordre.** `:removed` ne vient qu'après `if not exist "%TARGET%\"`, et ce n'est qu'à ce moment que la clé et
     l'état sont retirés. Sinon le journal écrit `ECHEC` et garde la clé (MB tuée, R1). Le résultat de `reg delete`
     n'est pas vérifié : le journal affirme « cle … retiree » dans tous les cas (mineur, mn5).
   - **Journal.** `%TEMP%\jarvis-uninstall.log`, perdu si `%TEMP%` contient `%` (R4).
   - **Nom du fichier.** Il est prévisible (PID + horodatage) et écrit par `write_text`, sans création exclusive.
     `%TEMP%` est propre à l'utilisateur (ACL du profil) : un autre utilisateur ne peut pas y préparer le fichier.
     Un processus du même utilisateur le pourrait, mais il a déjà tous les droits sur la cible. Observation F2.
   - **Injection.** `check_target` refuse `" % ! ^ & | < >`, et `DisableDelayedExpansion` est actif. Espaces,
     parenthèses, apostrophe, `; , = +` et Unicode passent pour de vrai (R3, script en `chcp 65001`). Revers : un
     profil Windows dont le nom porte `&`, `%`, `!` ou `^` ne peut pas installer dans le dossier par défaut (mn3).
   - **`%TEMP%` absent ou non inscriptible.** Refus visible et reprise possible (R5).
   - **État `<cible>.setup-state.json`.** Il ne vaut que pour SA cible (`target` exact), et chaque entrée du dossier
     doit figurer dans sa liste. Un état forgé fait bien effacer un dossier qu'il décrit (R7). Mais il vit dans le
     dossier parent de la cible, qui appartient à l'utilisateur : ce n'est donc pas une élévation. F1.
2. **Retour arrière** (`:631-688`).
   - La copie ratée est renommée `.failed-*` avec des reprises, l'ancien programme est remis, puis seulement la copie
     est effacée.
   - `rollback_failed` dit vrai et garde l'état. La reprise suivante nettoie l'ancien `.previous-*`, mais seulement
     s'il est JARVIS, porte le bon préfixe et a le même parent (`:614-617`). Rien n'est supprimé hors de
     l'installation (R9).
   - Deux restes : un `.failed-*` non effacé n'est jamais repris (mn2), et l'ordre « écarter d'abord » n'est pas
     testé (mn4).
3. **Garde du dossier étranger** (`is_jarvis_program`, `folder_kind`, `:385-487`).
   - Deux preuves sont exigées. Un manifeste forgé seul donne `foreign` (R7, et le test `[no_marker]`).
   - Une jonction comme cible est résolue puis jugée sur le dossier réel (R6). Une jonction intérieure n'est pas
     suivie.
   - Tests présents : unreadable/no_marker/other_product, état d'une autre cible, ancêtre de la maison.
   - Manifeste et marqueur forgés ensemble donnent `jarvis` : sans signature, on ne peut pas faire mieux (F1).
4. **Lanceur** (`jarvis/runtime/product_launcher.py:450-501`, `:555-561`).
   - Il refuse sans marqueur (`not_installed_product`, essai réel `dev-launch.json`).
   - « Quitter JARVIS » écrit `stop-<rôle>.request`, attend `STOP_GRACE_S` = 15 s, puis seulement `terminate`, puis
     `kill` après 5 s. Les demandes périmées sont effacées avant chaque lancement.
   - Le grep de `taskkill`, `os.kill`, `TerminateProcess` et `Stop-Process` sur les fichiers modifiés trouve un seul
     `os.kill(pid, 0)` : c'est la sonde POSIX de `pid_alive`, qui ne tue rien. Aucun arrêt par PID mémorisé.
   - La Voix reste en `terminate` : écart déclaré dans I-009 §7.
5. **Mineurs déclarés corrigés.**
   - `/S` sans boîte : test `test_an_unknown_argument_in_silent_mode_never_opens_a_dialog`.
   - Cible de l'amorce : `DefaultTarget` lit d'abord `LOCALAPPDATA`.
   - `--launch` : `try`/`catch`, code de sortie 3.
   - Messages : m9 retiré ; phrases de produit plus « Détails » (m3).
   - `win.open` au clic : `preOpen` réserve une fenêtre au clic, sinon un lien « Ouvrir la page »
     (`test_a_page_blocked_by_the_browser_is_offered_as_a_link`).
   - `/api/product` dans `READ_GUARDED_ROUTES`, avec correspondance par préfixe (`control_center.py:2374`).
   - Double clic sur `connect_circoe` : `SERIALIZED_ACTIONS`, marque posée sans `await` intermédiaire, test dédié.
   - Mutation M1 de la première revue : test ajouté.
   - Docstring `--move` mise à jour.
   - Le JARVIS de développement (`full`, sans marqueur) n'est pas touché : `test_full_edition_never_reads_nor_opens_the_preparation`
     passe. Sans `JARVIS_STOP_REQUEST_FILE`, Core et le Control Center attendent comme avant (`stop_request.py`).

## Findings

### BLOCKER

Aucun.

### MAJOR

Aucun.

### MINOR

- **mn1. Le script différé ne vérifie pas qu'il possède encore la cible.** `jarvis/product_setup.py:737` (attente par
  PID + image, sans heure de début) et `:750-758` (`rmdir` puis retrait de la clé sans contrôle).
  - Preuve, sonde R2 : pendant que le script attend un processus homonyme, une réinstallation aboutit. Le script
    efface ensuite la nouvelle installation et retire sa clé, sans rien dire à l'utilisateur. La maison n'est pas
    touchée.
  - En pratique, il faut un PID réutilisé par un exécutable du même nom dans la seconde qui suit la fin. Une course
    voisine existe pendant les 2 min de reprises (fichier verrouillé, puis réinstallation qui s'intercale). Les deux
    sont très improbables.
  - Correctif peu coûteux :
    - noter un jeton aléatoire dans l'état `uninstall`, et que le script vérifie (`findstr`) avant chaque `rmdir` et
      avant de retirer la clé ;
    - faire refuser par `install` un état `uninstall` dont le processus vit encore ;
    - en complément, passer l'heure de début du processus (I-009 §2 traite déjà le même défaut pour `launcher.json`).
- **mn2. Un `.failed-*` non effacé n'est jamais repris.** `jarvis/product_setup.py:612-623` ne nettoie que `previous`
  et l'ancien `.previous-*`. Preuve, R10 : `Jarvis.failed-…` reste après une installation réussie. Il pèse le poids
  d'un paquet complet (Python et Node privés). Il n'est nommé que dans le `detail` du refus précédent. Suggestion :
  le noter dans l'état et l'effacer après un succès, avec les mêmes gardes de nom et de parent que `.previous-*`.
- **mn3. Certains caractères dans le chemin du profil Windows.** `jarvis/product_setup.py:82`, `:276`,
  `:731-733`.
  - Un nom de profil qui contient `&`, `%`, `!` ou `^` (permis par Windows) rend la cible par défaut
    `target_unsafe` : l'installation est impossible sans `--target` (R3).
  - Un `%TEMP%` qui contient `%` fait perdre le journal de la désinstallation différée (R4) ; la suppression, elle,
    aboutit.
  - Cas rare. Suggestion : passer chemins et cible au script par l'environnement du processus
    (`set` hérité, ou `%~1` avec des arguments), plutôt que les écrire dans le texte du script.
- **mn4. Lacune de test sur le retour arrière.** La mutation MC1 survit : aucun test ne distingue « écarter
  `.failed-*` puis restaurer » de « effacer puis restaurer ». C'est pourtant la propriété annoncée par la doc
  (`docs/product-install.md` › Rollback). Il faudrait un verrou qui empêche l'effacement d'un fichier mais pas le
  renommage de son dossier, comme un antivirus qui ouvre avec `FILE_SHARE_DELETE`.
- **mn5. Le journal affirme « cle de desinstallation retiree » sans vérifier.** `jarvis/product_setup.py:757-759` :
  le code de sortie de `reg delete` (ou de `del` pour la ruche simulée) n'est pas vérifié. Si `reg` échoue, le
  journal dit faux et Windows liste encore JARVIS. Une nouvelle désinstallation donne alors `absent` et retire la clé
  proprement, donc l'effet est mineur.
- **mn6. Mode `/S` : seule `ArgumentException` est rattrapée.** Constaté par lecture, non exécuté.
  `packaging/windows/setup_stub.cs:97-99` (`Full` → `Path.GetFullPath`) et `:396-397`. `GetFullPath` lève aussi
  `NotSupportedException` (par exemple `C:\a:b`) et `PathTooLongException`. En `/S`, ces exceptions ne sont pas
  rattrapées : plantage, voire boîte WER, alors que le mode silencieux promet de n'ouvrir aucune boîte. Suggestion :
  rattraper `Exception` dans `Parse`, ou dans `Full`.

## Flagged

- **F1.** L'état d'opération, le manifeste et le marqueur sont des preuves de bonne foi, pas d'authenticité. Le même
  utilisateur peut les forger (R7) et faire effacer un dossier. Il n'y a pas de franchissement de privilège : la cible,
  son parent et `HKCU` lui appartiennent déjà. Seule la signature (HV-INSTALL-04) change la donne.
- **F2.** Le nom du script différé est prévisible et le fichier n'est pas créé de façon exclusive. C'est sans
  conséquence entre utilisateurs, puisque `%TEMP%` est propre au profil. `tempfile.mkstemp(suffix=".cmd")` coûterait
  une ligne.
- **F3.** R5 : si le script ne peut pas être écrit, les raccourcis sont déjà retirés avant le refus. C'est voulu
  (« raccourcis d'abord »), mais JARVIS reste installé sans raccourci jusqu'à une nouvelle désinstallation ou
  installation.
- **F4.** `test_a_folder_without_both_proofs…` couvre `unreadable_manifest` avec un marqueur présent, mais pas un
  manifeste au nom d'un autre produit avec le bon marqueur. La branche `product.name != "Jarvis"` (`:394`) n'est donc
  pas éprouvée seule (non muté).

## Non vérifié

- Désinstallation lancée par Windows depuis « Applications installées », vrai registre, vraie boîte de message :
  simulation et ruche JSON seulement. L'essai réel de la reprise a lancé `pythonw.exe` à la main.
- Comportement de l'amorce avec un chemin `NotSupportedException` (mn6) : relu, non exécuté, pour ne pas ouvrir de
  boîte WER sur le poste.
- Arrêt propre de Core quand des rendus, des sessions cerveau ou des écritures sont réellement en cours : seule
  l'issue de l'essai réel (2,3 s, `child_stopped_cleanly`) a été relue.
- `preOpen` dans un vrai navigateur avec bloqueur de fenêtres : couvert uniquement par le test navigateur (simulation
  `window.open`).
- Lots `test_control_center_*` hors de la liste ci-dessus, et les échecs connus.

## Risques résiduels

- La suppression différée reste un script `cmd.exe` sans lien fort avec le processus ni avec l'opération (mn1).
- Installeur non signé : les preuves d'identité du dossier sont forgeables par l'utilisateur lui-même (F1).
