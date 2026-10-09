# Environnement Remotion : installation unique et cycle de vie

Handoff `jarvis-remotion-presentation-integration`, Slice 04. **Statut : contrat (Level 2) et implémentation réelle (Level 3), vérifiés sur Windows 11 avec le vrai réseau npm** ([preuve](#9-preuves)). Première capacité locale au sens de [local-capabilities.md](local-capabilities.md) ; elle n'écrit, ne lance et n'arrête rien au démarrage de Core : l'installation est une **action explicite**.

Ce document ne dit rien de l'usage de Remotion (source des présentations, Player, Studio : Slices 05, 10, 11). Il garantit seulement qu'il y a, par poste, **un seul** environnement Remotion installé, épinglé, vérifiable et réparable.

## 1. Ce qui est installé, et où

Un seul arbre `node_modules` par racine de données (`JARVIS_DATA_ROOT`, [local-data.md](local-data.md)), jamais dans le dépôt, jamais par `npm -g`, jamais par présentation :

```
<racine de données>/local_capabilities/remotion/
    state.json                 état de la capacité (hôte, docs/local-capabilities.md §5)
    runtime/
        package.json, package-lock.json, runtime-host.mjs   copiés depuis jarvis/capabilities/remotion/
        node_modules/          l'arbre complet (≈ 270 Mo, 297 paquets dans le verrou)
        install-record.json    ce qui a été installé : versions, empreinte du verrou, empreinte des fichiers, plate-forme
        .npm-cache/ .npmrc .npmrc-global     cache et configuration npm PROPRES à cette capacité
        worker.json worker.log               présents seulement quand le processus tourne ou a tourné
        .install.lock                        présent seulement pendant une installation
```

`runtime/` est le seul dossier où le runner écrit. Le runner refuse tout autre dossier (le nom doit être `<id>/runtime`).

## 2. Jeu de paquets épinglé

Source unique : `jarvis/domain/remotion_capability.py`. `jarvis/capabilities/remotion/package.json` et `package-lock.json` le répètent pour npm ; `tests/unit/test_node_capability_runner.py` échoue si l'un des trois diverge.

| Paquet | Version | Rôle |
| --- | --- | --- |
| `remotion` | 4.0.534 | cœur (compositions, `useCurrentFrame`...) |
| `@remotion/player` | 4.0.534 | aperçu embarqué (Slice 10) |
| `@remotion/cli` | 4.0.534 | Studio et rendu (Slices 11, 16) |
| `@remotion/bundler` | 4.0.534 | **compile le TSX pour le navigateur** (source du bundle du Player ; embarque rspack et esbuild) |
| `react`, `react-dom` | 19.3.0 | pairs requis par le Player et le bundler |

Versions vérifiées sur le registre npm le 2026-10-09 (`npm view`, dernière version publiée de chacun) et exercées par l'installation réelle (§9). Les 291 autres paquets sont **verrouillés** par `package-lock.json` (version, `resolved` sur `registry.npmjs.org`, `integrity` sha512 pour chacun : un test le vérifie).

**Poste requis** (vérifié, jamais installé par Jarvis) : Node.js ≥ 20.0.0 (le plus haut `engines.node` du verrou est 18.12 ; Node 18 est en fin de vie), npm ≥ 9.0.0, plate-forme `win32-x64`, `darwin-x64`, `darwin-arm64`, `linux-x64` ou `linux-arm64` (celles pour lesquelles le verrou porte les binaires natifs de Remotion et de rspack). Windows ARM64 n'est pas pris en charge. npm est celui livré **avec** le Node trouvé sur le `PATH` (`node_modules/npm/bin/npm-cli.js`), sans passer par `npm.cmd` ni un shell.

## 3. Statuts et échecs typés

Statut affiché (`status`, dérivé, [local-capabilities.md](local-capabilities.md) §2) : `not_installed` → `installing` → `ready` (ou `install_failed`), `running`, `crashed`, `repair_needed` (installée mais malsaine), `disabled`, `uninstalling`. « Réparation en cours » est `installing` pendant `repair`.

Chaque échec d'installation garde un **code stable** (`last_error_code`) et une phrase `jeton: explication` bornée, sans chemin absolu ni secret (`last_error_detail`) :

| Code | Jeton(s) du détail | Cause | Que faire |
| --- | --- | --- | --- |
| `local_capability_requirement_missing` | `node_missing`, `node_unusable`, `node_too_old` (trouvé / requis), `npm_missing`, `npm_unusable`, `npm_too_old`, `platform_unsupported` | le poste ne satisfait pas §2 (plusieurs lignes possibles, séparées par `;`) | installer / mettre à jour Node.js soi-même, puis `install` de nouveau |
| `local_capability_install_offline` | `offline` | npm n'atteint pas le registre (DNS, proxy, pare-feu, certificat) | rétablir le réseau, puis `repair` |
| `local_capability_install_permission_denied` | `permission_denied`, `file_locked` | dossier non inscriptible, fichier verrouillé (antivirus, indexeur) | corriger les droits ou exclure le dossier de l'antivirus, puis `repair` |
| `local_capability_install_disk_full` | `disk_full` | moins de 1,5 Go libres avant téléchargement, ou `ENOSPC` | libérer de la place, puis `repair` |
| `local_capability_install_timeout` | (message avec la limite) | `npm ci` > 15 min ; l'arbre de processus a été tué | `repair` ; vérifier le débit |
| `local_capability_install_integrity_failed` | `integrity_failed` | npm a refusé un tarball dont le sha512 ne correspond pas au verrou | ne pas contourner ; `repair` ; si cela se répète, le registre ou un proxy altère les paquets |
| `local_capability_install_failed` | `npm_failed`, `registry_refused`, `npm_unlaunchable`, `path_too_long`, `manifest_mismatch`, `shipped_files_unreadable`, `cancelled` | autre échec de npm (fin de sortie bornée dans le détail) ; chemin Windows de plus de 130 caractères sans « chemins longs » ; Core arrêté pendant l'installation | selon le jeton |
| `local_capability_install_interrupted` | — | Core (ou le poste) s'est arrêté pendant l'installation ; constaté au démarrage suivant par `reconcile` | `repair` |
| `local_capability_health_failed` | `tree_corrupt` (paquet nommé), `shipped_files_changed`, `record_missing`, `version_mismatch`, `node_missing`, `probe_failed`, `probe_timeout` | la sonde §5 a échoué : `repair_needed` | `repair` (réinstalle depuis le verrou) |
| `local_capability_start_failed` | `worker_not_ready`, `worker_unhealthy`, `node_missing` | le processus n'a pas répondu en 45 s | lire `worker.log`, puis `start` |

Les échecs sont journalisés par l'hôte (`local_capability.<op>.failed`, niveau `error`) ; les opérations normales aussi (niveau `info`).

## 4. Installation

`install` copie `package.json`, `package-lock.json` et `runtime-host.mjs` dans `runtime/`, vérifie que le `package.json` livré égale le manifeste, puis lance **`npm ci --ignore-scripts --no-audit --no-fund`** dans `runtime/` :

- `npm ci` installe exactement le verrou et **vérifie le sha512 de chaque tarball** (`EINTEGRITY` sinon) ; aucune résolution de version n'a lieu chez l'utilisateur ;
- `--ignore-scripts` : aucun script d'installation de paquet tiers ne s'exécute (esbuild et rspack trouvent leurs binaires dans leurs paquets de plate-forme) ;
- cache, `.npmrc` utilisateur et `.npmrc` global remplacés par des fichiers de `runtime/` (ni jeton de registre privé, ni cache global écrit) ; registre forcé à `https://registry.npmjs.org/` ; environnement de l'enfant en **liste blanche** (aucune variable `JARVIS_*`, clé d'API ni jeton) ;
- délai 15 min ; au dépassement (ou à l'arrêt de Core) **l'arbre entier** est tué (`taskkill /T /F` sous Windows, groupe de processus ailleurs), pas seulement `npm` ;
- verrou `.install.lock` (pid + heure de création du processus + date) : un verrou dont le processus a disparu, trop vieux (> 30 min) ou illisible est repris ; un verrou vivant donne `local_capability_busy`. L'hôte refuse déjà une seconde opération dans le même Core (`busy`) ;
- après `npm ci`, l'arbre sur disque est comparé au verrou (chaque paquet applicable à la plate-forme, à la version du verrou) et `install-record.json` est écrit.

**Une fois** : `install` sur une capacité déjà installée aux versions épinglées ne lance rien (`install.noop`) ; installée à d'autres versions, elle refuse (`update_required`) : `update` est explicite. Un `node_modules` partiel laissé par une installation interrompue est effacé au début de l'installation suivante.

## 5. Santé

`health` (et la fin de chaque `install`/`repair`) lance la sonde du runner :

1. `install-record.json` lisible, versions installées = versions épinglées ;
2. empreinte SHA-256 des **trois** fichiers livrés (`package.json`, `package-lock.json`, `runtime-host.mjs`) : la copie de `runtime/` = celle du record = celle du fichier livré avec Jarvis (`shipped_files_changed` nomme le fichier ; après une mise à jour de Jarvis, `repair` recopie et réinstalle) ;
3. chaque paquet du verrou applicable à cette plate-forme présent à la bonne version (les aides optionnelles sans contrainte de plate-forme, comme les aides wasm, peuvent manquer) ;
4. empreinte (chemin, taille) de **tous les fichiers** des six paquets épinglés : un fichier supprimé, ajouté ou tronqué la change (`tree_corrupt`) ;
5. `node runtime-host.mjs --probe` (délai 90 s) : charge réellement `remotion`, `@remotion/bundler` (donc rspack natif), `@remotion/player` et `esbuild` (compilateur des scènes, Slice 05) et compare les versions.

Limite connue : une altération de contenu qui **conserve la taille** d'un fichier d'un paquet transitif n'est pas détectée par la sonde (le sha512 n'est vérifié que par npm à l'installation). `repair` ne la voit pas non plus ; `uninstall` puis `install` la corrige.

`repair` : saine et processus non planté → rien ; sinon `npm ci` complet depuis le verrou (≈ 19 s mesurés ; le cache npm de `runtime/` est conservé). Un processus seulement planté se relance par `start`.

## 6. Processus

`start` lance `node runtime-host.mjs --serve` (cwd `runtime/`, environnement en liste blanche, sortie dans `worker.log`) : un petit processus qui recharge les paquets, écoute **uniquement sur `127.0.0.1`** (port éphémère, aucun jeton) et sert `GET /health`. Core attend `worker.json` puis interroge `/health` (45 s au plus) **sans passer par un proxy d'environnement** et exige que la réponse porte le pid du processus lancé (un autre programme sur ce port ne passe pas) ; `worker.log` est plafonné à 1 Mo (une génération `worker.log.1`) ; si l'heure de création du processus est illisible (POSIX sans `/proc` ni `ps`), il est tué et le démarrage refusé (`process_identity_unavailable`) plutôt que suivi à l'aveugle ; sinon l'arbre est tué et l'état est `crashed` + `start_failed` avec la fin du journal. C'est le point d'ancrage que les Slices 10-11 étendront (Player, Studio) ; il n'exécute **aucune** source de présentation.

La référence d'un processus est `pid:heure de création` : un pid réutilisé par un autre programme n'est jamais pris pour le nôtre. `stop` tue l'arbre ; `restart` = `stop` puis `start` (deux routes). Après un redémarrage de Core, `reconcile` retrouve l'enfant vivant (inchangé) ou le marque `crashed` (`process_exited`) s'il a disparu.

## 7. Routes de Core

Jeton porteur de Core obligatoire, comme toutes les routes `/v1`. Famille distincte de `/v1/mcp/plugins` (aucun chemin, code ni champ commun).

| Méthode | Route | Réponse |
| --- | --- | --- |
| GET | `/v1/local-capabilities` | `{capabilities: [vue]}` |
| GET | `/v1/local-capabilities/{capability_id}` | `{capability: vue}` |
| POST | `/v1/local-capabilities/{capability_id}/{operation}` | `operation` ∈ `install`, `update`, `repair`, `uninstall`, `start`, `stop`, `health`, `enable`, `disable`. Corps vide ou `{}`. |

Les quatre opérations longues répondent **200** si elles finissent en 2 s, sinon **202** avec la vue courante (`status: installing`...) : l'appelant relit par `GET` jusqu'à `ready` ou `install_failed`. Une seconde demande pendant ce temps reçoit **409** `local_capability_busy`. Refus : 404 inconnue, 400 invalide, 409 précondition, 503 `local_capability_runner_unavailable` (Core sans runner ni magasin), 500 défaut local. Un **échec d'opération** n'est pas une erreur HTTP : c'est la vue (`status: install_failed`, `last_error_code`, `last_error_detail`). Le thread d'installation est un thread démon : l'arrêt de Core ne l'attend pas, mais tue l'arbre npm (`cancel_all`) et l'état reste vrai.

Au démarrage de Core, **seul** `reconcile()` s'exécute (une installation « en cours » devient `install_failed` / `install_interrupted`, un enfant disparu devient `crashed`) : rien n'est installé, lancé ni arrêté. Contrat testé : `tests/unit/test_local_capability_routes.py`.

## 8. Désinstaller, désactiver : ce qui est protégé

`uninstall` arrête le processus puis vide `runtime/` (sans suivre aucun lien symbolique ni jonction, avec reprise des fichiers verrouillés) et garde `state.json` (`not_installed`). `disable` arrête le processus et marque la capacité désactivée ; `enable` ne relance rien. Aucune de ces opérations ne lit ni n'écrit hors de `local_capabilities/remotion/` : les sources et les assets des présentations (`<racine>/presentation/...`, stockage du Studio) sont intacts, ce que le harnais et les tests vérifient octet par octet. Réinstaller restitue un environnement identique sans toucher aux présentations.

## 9. Preuves

Harnais `scripts/remotion_install_harness.py` : vrai `LocalCapabilityHost` + vrai `NodeCapabilityRunner`, vrai npm, vrai réseau, racine de données privée dans le dossier temporaire (jamais le profil vivant), sans toucher à Core. Sortie : `tasks/jarvis-remotion-presentation-integration/slices/04-remotion-one-time-provisioning/evidence/real-install.json` (branche à `208aeaea`, Windows 11 10.0.26200, Node v24.18.0, npm 11.16.0 livré avec ce Node). Résultats de la dernière exécution :

| Scénario | Résultat |
| --- | --- |
| installation fraîche | 21,8 s (17 à 43 s sur les exécutions successives, selon le réseau), 270,3 Mo, 150 entrées de premier niveau, `ready`, sonde 0,5 s ; versions installées = versions épinglées |
| seconde `install` | 0 s, aucun appel npm, `install_attempts` inchangé (1) |
| trois `install` quasi simultanées | une seule s'exécute, deux `local_capability_busy`, un seul `node_modules` |
| `start` / redémarrage de Core / `stop` / `start` | 0,5 s ; l'hôte neuf retrouve le même enfant vivant ; arrêt 0,3 s, enfant disparu ; relance sous un nouveau pid ; enfant tué hors Jarvis → `crashed` (`process_exited`) → `start` → `running` ; 0 orphelin |
| fichier tronqué | `repair_needed` (`tree_corrupt`) → `repair` → `ready` |
| fichier supprimé + fichier tronqué + paquet transitif retiré | `repair_needed` nommant `scheduler@0.28.0` → `repair` (19 s) → `ready` |
| arrêt de Core pendant `npm ci` (arbre tué à mi-chemin) | état affiché `installing` avant `reconcile` ; après `reconcile` : `install_failed` / `install_interrupted` ; `repair` (18,8 s) → `ready` ; aucun verrou résiduel, aucun orphelin |
| hors ligne (proxy mort) | 13,9 s → `local_capability_install_offline` ; réseau rétabli → `repair` → `ready` |
| dossier non inscriptible (ACL de refus) | `local_capability_install_permission_denied` sans lancer npm ; droits rétablis → `repair` → `ready` |
| délai de 6 s | 6,6 s → `local_capability_install_timeout`, 0 processus node restant |
| tarball altéré (sha512 faux dans une copie du verrou) | `local_capability_install_integrity_failed` (`EINTEGRITY` de npm) ; avec le vrai verrou, `repair` → `ready` |
| `uninstall` avec sources et asset de présentation | sources et asset identiques (octets), `runtime/` vide, réinstallation 17,3 s |

Tests unitaires (faux npm/node) : `tests/unit/test_node_capability_runner.py`, `test_process_tree.py`, `test_remotion_lifecycle.py`, `test_local_capability_routes.py`, en plus de `test_local_capability_host.py`.

## 10. Changer de version

1. Modifier `jarvis/domain/remotion_capability.py` et `jarvis/capabilities/remotion/package.json` (versions **exactes**).
2. Dans un dossier vide contenant ce `package.json` : `npm install --package-lock-only --ignore-scripts`, puis copier le `package-lock.json` obtenu dans `jarvis/capabilities/remotion/`. Vérifier `engines.node` maximal du verrou ≤ `NODE_MINIMUM` (un test le fait).
3. Les postes installés passent en `update_required` / `lock_changed` : `update` ou `repair` explicite.

## 11. Limites et risques résiduels

- **Réseau et npm réels** : le premier `install` télécharge ≈ 270 Mo depuis `registry.npmjs.org` ; hors ligne il échoue proprement mais ne peut pas réussir. Aucun miroir interne n'est configuré.
- **Chemins longs Windows** : au-delà de 130 caractères pour `runtime/` sans « chemins longs » activés, l'installation est refusée (`path_too_long`) avant tout téléchargement ; une racine `~/.jarvis/instances/<dossier>-<empreinte>/data` standard reste en dessous.
- **Antivirus / indexeur** peuvent verrouiller `node_modules` (`file_locked`) ; la suppression réessaie cinq fois.
- **Licence Remotion** non examinée ici (contrat distinct, [local-capabilities.md](local-capabilities.md) §6).
- **Pas d'interface** : la carte du Control Center est différée ([Issue 02](../tasks/jarvis-remotion-presentation-integration/Issues/02-local-capability-deferred-wiring.md) point a). L'action explicite passe par les routes §7 (recette dans [OPERATIONS.md](OPERATIONS.md), « Capacité locale Remotion »).
- **Windows uniquement éprouvé en réel** : macOS et Linux sont pris en charge par le verrou et la logique (tests unitaires), mais n'ont pas été exécutés.
- **Altération à taille constante** d'un paquet transitif non détectée après installation (§5).
- Le plus haut `engines.node` provient de `@rspack/core` ; une montée de version peut relever `NODE_MINIMUM`.

## 12. Compilation des scènes (Slice 05)

Le même `runtime-host.mjs` sert aussi `node runtime-host.mjs --compile <requête.json>` : un processus **à la demande** (pas le worker `--serve`) qui compile une scène ou le « host » du Player avec l'esbuild du verrou, dans cet unique arbre. Lancé par `NodeCapabilityRunner.run_script` (mêmes environnement en liste blanche, délai et arrêt de l'arbre). Contrat complet, cache, clés et échecs typés : [remotion-source.md](remotion-source.md) §5. Conséquences pour cette capacité : le fichier livré a changé (un environnement installé avant la Slice 05 affiche `shipped_files_changed` ; `repair` le met à niveau), la sonde (§5) charge aussi `esbuild`, et `uninstall` supprime désormais le cache de npm même quand un chemin dépasse 260 caractères sous Windows (chemins étendus ; avant, « répertoire non vide »). Le cache de compilation (`local_capabilities/remotion/compiled/`) est hors de `runtime/` : `uninstall` ne le vide pas. Slice 06 : le processus de compilation a un tas V8 plafonné (`--max-old-space-size=1024`) et le code des scènes est isolé à l'exécution ([remotion-isolation.md](remotion-isolation.md)).
