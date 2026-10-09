# Capacités locales installables

Handoff `jarvis-remotion-presentation-integration`, Slice 03. **Statut : contrat (Level 2) et socle d'hôte (Level 3) livrés ; aucun runtime réel n'y est branché.** Remotion (Slice 04) sera la première capacité ; ce document ne l'installe pas.

Une **capacité locale** est un runtime que Jarvis installe **une seule fois par profil d'exécution** (racine de données du poste, [local-data.md](local-data.md)), épingle à des versions exactes, surveille et dont il gère le processus enfant. Ce n'est **pas** un plugin MCP.

## 1. Pourquoi un registre frère, pas un plugin MCP

| | Plugin MCP distant ([mcp/plugins.md](mcp/plugins.md)) | Capacité locale (ce document) |
| --- | --- | --- |
| Définition | URL `https://…`, `transport = streamable_http` seulement (`jarvis/domain/mcp_plugins.py`) | manifeste : composants épinglés, exigences du poste, point d'entrée **logique** |
| Transport | `streamable_http` | `local_process` (jamais `streamable_http`) |
| Secrets | coffre scellé DPAPI, OAuth | aucun : ni coffre, ni OAuth, ni endpoint, ni jeton |
| Stockage | `jarvis.sqlite3` v4 (`mcp_plugins`) | fichiers `local_capabilities/<id>/` sous la racine de données, **pas de schéma SQLite, donc pas de migration** |
| Codes d'erreur | `mcp_*` (`McpErrorCode`) | `local_capability_*` (`LocalCapabilityErrorCode`), aucun commun |
| Accès du modèle | passerelle `jarvis-tools` | aucun par défaut ; une capacité n'expose jamais ses outils par `jarvis-tools` |

Les deux familles ne partagent aucun code d'exécution : `tests/unit/test_local_capability_host.py` prouve que la pile locale n'importe rien de la pile des plugins distants, et que les espaces de codes sont disjoints. Le sens des plugins distants ne change pas ; un serveur stdio d'opérateur (`jarvis-drive`, [mcp/plugins.md](mcp/plugins.md) §11) reste hors de ce registre.

**Une seule carte pour l'utilisateur.** La vue publique (`public_view`) porte `family = "local_capability"` et un `status` unique ; la carte du Control Center (`jarvis/runtime/control_center_mcp_plugins.js`) pourra afficher les deux familles côte à côte en lisant `family`/`transport`, sans que l'une prenne les routes ou les champs de l'autre. La carte elle-même est un travail de Slice ultérieure (04 pour la première capacité) : ici, seul le contrat de données est figé.

## 2. Modèle

`CapabilityManifest` (`jarvis/domain/local_capabilities.py`, `new_manifest`) :

- `capability_id` : slug minuscule de 32 caractères au plus, jamais `jarvis-*` (espace des serveurs natifs) ;
- `components` : paquets **épinglés à une version exacte** (`1.2.3`, pré-version admise). `^`, `~`, `*`, plage et `latest` sont refusés ;
- `requirements` : exigences du poste, aujourd'hui `node` avec un minimum exact. Le runner les **vérifie**, il n'installe jamais Node ;
- `entrypoint` : nom logique résolu par le runner. Un manifeste ne porte ni chemin, ni ligne de commande.

`CapabilityState` (un par capacité) a quatre axes indépendants : `install_status`, `process_status`, `health`, `enabled`, plus `installed_components` (ce qui est réellement sur le disque), `process_ref` (pid opaque, pour reconnaître un orphelin), `last_error_code` (code stable) / `last_error_detail` (texte borné à 300 caractères, sur une ligne) et `install_attempts` (preuve du « une seule fois »).

`status` n'est qu'un résumé dérivé (`derive_status`), jamais stocké : `not_installed`, `installing`, `uninstalling`, `install_failed`, `disabled`, `repair_needed` (installée mais malsaine), `crashed`, `starting`, `running`, `stopping`, `ready` (installée, saine, arrêtée).

### Machine à états

Installation : `not_installed → installing → installed | failed` ; `installed|failed → installing` (mise à jour, réparation, reprise) ; `installed|failed → uninstalling → not_installed | failed`.
Processus : `stopped → starting → running | crashed | stopped | stopping` ; `running → stopping | crashed` ; `stopping → stopped | crashed` ; `crashed → starting | stopping | stopped`.
Invariants (`check_invariants`) : un processus n'existe que sur une capacité `installed` ; une capacité désactivée n'a pas de processus actif. Toute transition illégale lève `local_capability_internal_error` ; un état stocké qui viole un invariant est refusé, pas deviné.

## 3. Sémantique des opérations (`LocalCapabilityHost`, `jarvis/core/local_capability_host.py`)

| Opération | Effet |
| --- | --- |
| `install` | **Une fois.** Déjà `installed` aux versions épinglées : aucun appel au runner (`install.noop`). Installée à d'autres versions : refus `update_required`, jamais de mise à jour implicite. Reprend après un `failed`. |
| `update` | Aligne sur les versions épinglées du manifeste (`register` d'un nouveau manifeste, puis `update`). Arrête d'abord le processus. |
| `repair` | Sonde ; saine : rien. Sinon réinstalle aux versions épinglées. |
| `check_health` | Sonde (`verify`) ; détecte un processus disparu (`process_exited`, état `crashed`). |
| `start` / `stop` | Idempotents. `start` refuse : non installée, désactivée, versions à mettre à jour. Un échec de lancement donne `crashed` + `start_failed` ; un échec d'arrêt donne `crashed` + `stop_failed` (orphelin possible, **dit**, jamais présenté comme arrêté). |
| `disable` / `enable` | `disable` arrête puis désactive ; `enable` réactive **sans lancer**. |
| `uninstall` | Arrête, retire ce que le runner a posé, garde l'enregistrement (`not_installed`). |
| `reconcile` | Au démarrage de Core : une installation « en cours » devient `failed` / `install_interrupted` ; un processus noté vivant mais disparu devient `crashed`. N'installe, ne lance, n'arrête rien. Un `state.json` illisible est rapporté, jamais réécrit. |

Une opération à la fois par capacité : la seconde reçoit `local_capability_busy` (pas de file). Chaque étape est écrite **avant** l'effet suivant, donc un arrêt de Core laisse un état vrai.

**Échecs.** Un échec du runner (exigence manquante, installateur, versions différentes de l'épinglage, santé, lancement, arrêt, désinstallation) est écrit comme **état typé** et **renvoyé** dans la vue (`status`, `last_error_code`, `last_error_detail`) et journalisé (`local_capability.<op>.failed`, niveau `error`). Un refus de précondition (inconnue, occupée, non installée, désactivée, mise à jour requise) lève `LocalCapabilityError`. Une exception inattendue du runner est journalisée avec son type et devient le code de l'opération, jamais « inconnu ».

Codes : `unknown`, `invalid`, `busy`, `not_installed`, `disabled`, `update_required`, `requirement_missing`, `install_failed`, `install_interrupted`, `uninstall_failed`, `health_failed`, `start_failed`, `stop_failed`, `process_exited`, `runner_unavailable`, `store_failed`, `internal_error` (préfixe `local_capability_`).

## 4. Qui lance le processus enfant

**Core**, via un `CapabilityRunner` injecté (`jarvis/ports/local_capabilities.py`) : un seul propriétaire, qui connaît la racine de données du poste et peut réconcilier au démarrage. Pas d'assistant du Control Center : le Control Center ne fait que lire la vue et demander des opérations par des routes de Core (Slice ultérieure). Cela respecte la règle du dépôt (`CLAUDE.md`) : ni le socle ni ses tests ne démarrent, ne relancent ou n'arrêtent Core, le Control Center ou la voix.

- Le socle ne câble **aucun runner** : `UnavailableRunner` répond `runner_unavailable`. Aucun réseau, npm ni processus n'est exécuté par défaut. Les tests injectent un faux.
- Le runner n'écrit que dans `runtime_dir`, `<data_root>/local_capabilities/<id>/runtime/`, et ne retire que ce qu'il y a posé. Il n'a aucune permission sur les dossiers de projets, de Boards ou d'Artifacts, ni sur la mémoire de Jarvis.
- Le code source d'une présentation (TSX/JS non fiable) ne gagne **aucun** privilège Jarvis : il ne tourne que dans le processus enfant, sans variables d'environnement secrètes, ce que la Slice 06 (isolation) doit prouver pour Remotion.
- Tester sur un bac à sable ou un worktree avec sa racine (`JARVIS_DATA_ROOT`), jamais sur le profil vivant.

## 5. Stockage

`<data_root>/local_capabilities/<capability_id>/state.json` (écriture atomique : fichier temporaire unique, `fsync`, remplacement) et `runtime/`. Hors du dépôt, une racine par copie du dépôt ([local-data.md](local-data.md)). Aucune table : aucune migration (`CLAUDE.md`). `state.json` n'est jamais versionné.

## 6. Ce qui reste à faire (hors Slice 03)

- Slice 04 : manifeste Remotion (versions épinglées réelles), runner réel (npm), exigences de poste, sonde de santé réelle.
- Routes Core, câblage de `reconcile` au démarrage de Core, et carte du Control Center (`family`/`transport`).
- Contrôle de licence Remotion (autre contrat).

Tests : `tests/unit/test_local_capability_host.py`.
