# Studio Remotion optionnel : processus géré, copie de travail, garde réseau, carte

Handoff `jarvis-remotion-presentation-integration`, Slice 11. **Statut : contrat (Level 2) et implémentation réelle (Level 3), vérifiés sur Windows 11 avec le vrai `remotion studio`, un Core isolé et un vrai Chrome** ([preuves](#10-preuves)). Le Studio est un processus **supplémentaire** de la capacité locale Remotion ([remotion-runtime.md](remotion-runtime.md)) : il ne l'installe pas, ne la répare pas, et ne touche ni le worker `--serve` ni la compilation des scènes ([remotion-source.md](remotion-source.md) §5). L'aperçu intégré (Player, Slice 10) n'en dépend pas.

## 1. Décisions

| Décision | Conséquence |
| --- | --- |
| **Sur demande explicite seulement** (D5, D17). | Rien ne lance le Studio : ni le démarrage de Core, ni l'aperçu, ni la lecture de l'état (`GET`), ni la carte à son affichage. Seul `POST .../studio/open` (bouton « Ouvrir le Studio ») ou `restart` d'une scène déjà ouverte avant. |
| **Un seul Studio par profil d'exécution**, jamais un par présentation. | `open` sur une scène différente **change la scène en place** (rechargement à chaud), sans second processus ; `open` sur la même scène **réutilise** l'hôte vivant (`reused: true`). |
| **Le Studio ne sert que la source de la scène choisie**, matérialisée en copie de travail **en lecture seule**. | Jamais la racine de données, jamais un chemin libre : voir §2. L'écriture vers la bibliothèque ne passe jamais par le Studio (elle passe par `PrefabService`, Slices 14-15). |
| **Boucle locale uniquement**, port libre aléatoire ou imposé. | Le Studio stock lie `0.0.0.0` et `::` ; le garde (§3) le force sur `127.0.0.1`. Vérifié : l'adresse du réseau local refuse le port. |
| **Aucun secret dans l'environnement du Studio.** | Liste blanche (`process_tree.clean_env`) : ni `OPENAI_API_KEY`, ni jeton de Core ; seuls quatre identifiants de lancement non secrets sont ajoutés (§3). |
| **Une fenêtre à part, jamais intégrée ni forcée.** | La carte propose un lien `target=_blank rel=noopener` ; l'ouverture automatique après un clic peut être refusée par le navigateur (le lien reste). |

## 2. Dossier de travail : le seul dossier servi

```
<racine de données>/local_capabilities/remotion/runtime/studio/
    state.json                 état persistant (statut, scène épinglée, port, référence du processus)
    work/                      LE dossier servi (racine Remotion : son package.json est le plus proche du processus)
        package.json           généré : {"name": "jarvis-studio-scene", "private": true}
        studio-root.tsx        généré : registerRoot + <Composition> de la composition DÉCLARÉE par le manifeste
        src/**  public/**      les octets de la source, inchangés
    work.files.json            empreintes de la dernière synchronisation
    edits/<horodatage>/        copies des fichiers modifiés hors de Jarvis (au plus 5 dossiers)
    studio-guard.cjs           copie du garde livré, comparée à l'original à chaque lancement
    studio.log  listening.json  activity.json  exit.json
```

- **Construit par `plan_workspace` (pur)** à partir de la seule `RemotionSource` relue par `PrefabService.remotion_source` (gardes d'isolation de la Slice 06 comprises, empreintes SHA-256 vérifiées). La scène est repérée par un `StudioPin {prefab_id, version}` **exact** (jamais « la dernière »). Les `sample.props` du manifeste deviennent les `defaultProps` de la composition.
- **Résolution des paquets** : le dossier est sous `runtime/`, donc `remotion`, `react` et les loaders se résolvent dans l'unique `runtime/node_modules` (aucun `node_modules` par scène). Le cache de webpack du Studio vit dans `work/node_modules/.cache` : ni compté, ni lu, ni retiré par une synchronisation.
- **Copie en lecture seule** : chaque fichier est écrit via un fichier de préparation puis un renommage, avec l'attribut lecture seule. Une synchronisation ne touche **pas** un fichier identique (le rechargement à chaud ne voit que les fichiers changés), retire ce que la nouvelle version n'a plus, retire un lien ou une jonction posés dans `src/`, `public/` ou à la place de ces dossiers (jamais leur cible), et refuse un chemin qui sort de `work/`.
- **Fichiers modifiés hors de Jarvis** (depuis le Studio ou à la main : `src/**`, `public/**` ou un fichier de premier niveau, qui serait lu par le Studio, comme `remotion.config.ts`) : détectés par comparaison aux empreintes de la dernière synchronisation, **mis de côté** dans `edits/` (à la fermeture et avant chaque synchronisation), puis remplacés. La vue les compte (`work_copy.modified_files`, `edits_saved`). Rien n'est écrit dans la bibliothèque : une édition utile se refait par la route d'édition de source (Slice 14).
- **Les bornes** : 400 fichiers, 64 Mio de source ; au-delà, `remotion_studio_sync_failed`.

## 3. Processus et garde

Commande : `node --max-old-space-size=2048 --require studio/studio-guard.cjs <runtime>/node_modules/@remotion/cli/remotion-cli.js studio studio-root.tsx --port=<p> --no-open --ipv4 --disable-ask-ai --disable-git-source`, cwd = `work/`, sans fenêtre, sortie dans `studio.log` (1 Mio, une génération), environnement en liste blanche plus `JARVIS_STUDIO_DIR`, `JARVIS_STUDIO_LAUNCH` (identifiant aléatoire du lancement), `JARVIS_STUDIO_PARENT` (pid de Core) et `JARVIS_STUDIO_IDLE_S`. **Aucune route de Core, base, Board ou secret** n'est lisible depuis ce dossier.

Le Studio stock n'est pas sûr tel quel (il écoute sur tout le réseau local, son API sait lancer un gestionnaire de paquets, un éditeur ou un agent de code, et la scène tourne dans l'onglet du Studio, **même origine que cette API**). Le garde (`jarvis/capabilities/remotion/studio-guard.cjs`, chargé par `--require`, copié à chaque lancement) agit **dans le processus du Studio** :

1. **boucle locale** : tout `listen` TCP est forcé sur `127.0.0.1` / `::1` (toutes les formes d'appel) ;
2. **aucune connexion sortante** hors boucle locale (TCP : refus `EACCES` avant tout DNS, compté ; DNS : `lookup`/`resolve*` hors `localhost` refusés ; UDP : `dgram.createSocket` refusé) ;
3. **aucun processus enfant**, sauf le service **esbuild** épinglé (binaire sous `runtime/node_modules`, que le chargeur de TSX du Studio démarre) : installation de paquet, éditeur, terminal, agent, `powershell`, rendu sont refusés et comptés (`blocked_spawn`) ;
4. **Content-Security-Policy** sur chaque réponse : `default-src 'self'`, `connect-src 'self'` plus la boucle locale, `img-src`/`media-src` `'self' data: blob:`, `object-src 'none'`, `form-action 'self'`, scripts `'self' 'unsafe-inline' 'unsafe-eval' blob:` (le Studio en a besoin) ;
5. **identité** : `GET /__jarvis_studio__/health` rend `{ok, pid, launch}` ; Core exige l'identifiant de **ce** lancement (un autre programme sur le port ne passe pas) ;
6. **activité** : `activity.json` (dernière requête, WebSocket ouverts, refus) pour le délai d'inactivité ;
7. **plus d'orphelin** : le Studio se termine seul si Core a disparu depuis 60 s, ou après l'inactivité de Core plus 2 min.

La référence d'un processus est `pid:heure de création` ([remotion-runtime.md](remotion-runtime.md) §6) : un pid réutilisé n'est jamais tué pour un autre. L'arrêt tue **l'arbre** (`taskkill /T /F`, groupe de processus ailleurs) ; un arrêt incomplet est `remotion_studio_stop_failed`, jamais présenté comme réussi.

## 4. États, vue, codes

Statut : `stopped`, `starting`, `ready`, `stopping`, `failed`. Vue publique (`jarvis.domain.remotion_studio.public_view`) : `status`, `url` (`http://127.0.0.1:<port>/`, seulement `ready`), `port`, `port_mode` (`configured`/`random`), `pin`, `source_digest`, `composition`, `started_at`, `ready_at`, `synced_at`, `syncs` (par lancement), `restarts`, `idle_timeout_s`, `idle_in_s`, `viewers` (WebSocket ouverts), `stop_reason` (`user`, `idle_timeout`, `core_stopped`, `capability_change`, `restart`), `last_error_code`, `last_error_detail`, `diagnostics` (fin du journal, sans chemin ni secret), `work_copy`, `egress_blocked`. Aucun chemin du disque, aucun `process_ref`, aucun identifiant de lancement.

| Code (`remotion_studio_*`) | HTTP | Cause |
| --- | --- | --- |
| `invalid` | 400 | corps, pin ou paramètre invalide |
| `unavailable` | 503 | Core sans Studio (aucun magasin de capacités) |
| `source_unavailable` | 404 | version inconnue, HTML, altérée ou refusée par une garde |
| `busy` | 409 | une autre opération du Studio est en cours |
| `runtime_unavailable` | 409 | la capacité Remotion n'est pas `ready`/`running`, ou Node / `@remotion/cli` manquent : installer ou réparer d'abord |
| `not_running` | 409 | `sync` sans Studio ouvert ; `restart` sans scène précédente |
| `sync_failed` | 409 | la copie de travail n'a pas pu être écrite (le Studio reste ouvert sur l'ancienne version) |
| `port_unavailable`, `start_failed`, `start_timeout`, `health_failed`, `process_exited`, `stop_failed`, `store_failed`, `internal_error` | 200, vue `failed` | **échec d'opération = la vue** (comme les capacités), avec `last_error_code` et le journal |

## 5. Opérations

| Opération | Effet |
| --- | --- |
| `open {prefab_id, version}` | Studio arrêté ou en échec : exige la capacité prête, relit la source, matérialise, lance, attend `/health` de **ce** lancement puis la page (120 s au plus), `ready`. Déjà `ready` : même scène, réutilise ; autre scène, `sync` en place. Un Studio vivant qui ne répond plus est tué puis relancé. Une collision de port aléatoire est retentée **une fois** ; un port imposé n'est jamais remplacé (`port_unavailable`). |
| `sync {}` ou `{prefab_id, version}` | Rematérialise la scène courante (ou une autre version) : rechargement à chaud, **sans** nouveau processus. Mesuré : l'écran ouvert affiche la nouvelle version en moins de 2 s, sans rechargement de page. |
| `close` | Met de côté les fichiers modifiés, tue l'arbre, `stopped` (`stop_reason: user`). Idempotent. Ne perd aucun travail : la source vit dans la bibliothèque. |
| `restart` | `close` puis `open` sur la dernière scène (`restarts + 1`). Depuis `failed` aussi. |
| `status` (`GET`) | Lecture seule, relit vivacité, activité et fichiers modifiés ; constate une disparition (`failed`/`process_exited`). Ne lance rien. |
| surveillance (toutes les 15 s tant que `ready`) | disparition du processus : `failed`/`process_exited` ; aucune requête et aucun WebSocket pendant le délai (30 min par défaut, `JARVIS_REMOTION_STUDIO_IDLE_S`, 60 s à 24 h) : arrêt, `stop_reason: idle_timeout`. Un onglet du Studio ouvert (WebSocket) n'est jamais inactif. |
| `reconcile` (démarrage de Core) | Ne lance rien. Un Studio resté vivant (Core tué) et qui répond avec son identifiant est **adopté** ; sinon `failed`/`process_exited`. |
| arrêt de Core | ferme le Studio (`core_stopped`) : pas d'orphelin. Core tué brutalement : le garde l'achève au bout de 60 s. |
| `update`, `repair`, `uninstall`, `disable` de la capacité | le Studio est arrêté **avant** (crochet de `LocalCapabilityService`, `capability_change`) : il tient des fichiers de `runtime/`. |

## 6. Routes de Core

Préfixe frère de la famille des capacités : `/v1/local-capabilities/remotion/studio` (aucune route commune avec `/v1/local-capabilities/{id}/{operation}` : trois segments contre deux), jeton porteur obligatoire. Code : `jarvis/protocol/remotion_studio_routes.py`, `jarvis/core/remotion_studio_service.py`.

| Méthode | Route | Corps |
| --- | --- | --- |
| GET | `/v1/local-capabilities/remotion/studio` | — |
| POST | `/v1/local-capabilities/remotion/studio/open` | `{"prefab_id", "version"}` |
| POST | `/v1/local-capabilities/remotion/studio/sync` | `{}` ou `{"prefab_id", "version"}` |
| POST | `/v1/local-capabilities/remotion/studio/close` | `{}` |
| POST | `/v1/local-capabilities/remotion/studio/restart` | `{}` |

Réponse : `{studio: vue}`. Refus : `{error: {code, message}}`. Une requête avec paramètres de requête, un corps de plus de 1 Kio ou un champ en trop est refusée (`invalid`).

## 7. Réglages

| Variable | Rôle |
| --- | --- |
| `JARVIS_REMOTION_STUDIO_PORT` | port imposé (1024-65535) ; sinon un port libre de boucle locale à chaque lancement |
| `JARVIS_REMOTION_STUDIO_IDLE_S` | inactivité avant arrêt automatique, 60 à 86400 s (défaut 1800) ; une valeur illisible est ignorée (défaut), jamais un Core qui ne démarre pas |

## 8. Control Center : la carte « Remotion · Studio »

Six adresses relaient **telles quelles** vers Core (`jarvis/runtime/remotion_studio_relay.py`), toutes gardées par Host et origine de boucle locale :

| Control Center | Core | Délai |
| --- | --- | --- |
| GET `/api/local-capabilities/remotion` | GET `/v1/local-capabilities/remotion` | 10 s |
| GET `/api/local-capabilities/remotion/studio` | GET `.../studio` | 10 s |
| POST `/api/local-capabilities/remotion/studio/open` | POST `.../studio/open` | 150 s (démarrage ≤ 120 s) |
| POST `/api/local-capabilities/remotion/studio/restart` | POST `.../studio/restart` | 150 s |
| POST `/api/local-capabilities/remotion/studio/sync` | POST `.../studio/sync` | 40 s |
| POST `/api/local-capabilities/remotion/studio/close` | POST `.../studio/close` | 40 s |
 **Aucune installation ni désinstallation n'est relayée d'ici** : elles restent une action explicite sur Core ([remotion-runtime.md](remotion-runtime.md) §7). Le client de Core n'accepte que le préfixe `/v1/local-capabilities/remotion`.

La carte (`control_center_remotion_studio.js`) est en tête de l'onglet « Plugins externes » du dialogue MCP, au-dessus des cartes de plugins (la « carte unique » de [local-capabilities.md](local-capabilities.md) §1) : état de l'environnement Remotion, état du Studio, choix de la scène (scènes Remotion de la bibliothèque, `?engine=remotion`), boutons **Ouvrir le Studio**, **Actualiser la scène**, **Relancer**, **Fermer le Studio**.

- **Ce qui attend se voit** : pastille animée, durée écoulée (« Démarrage du Studio… 12 s écoulées, 2 min au plus. »), boutons désactivés pendant l'opération avec son libellé (« Ouverture du Studio… »), décompte de l'arrêt automatique (« arrêt automatique dans 28 min 12 s », absent tant qu'une fenêtre est ouverte), nombre de fenêtres ouvertes.
- **Un échec dit ce qui s'est passé** : phrase française du code, code stable affiché, journal du Studio replié ; l'état affiché est celui de Core, relu toutes les 2 s (démarrage, arrêt) ou 10 s.
- Étroit : la carte tient dans 390 px. Aucune écriture hors d'un clic ; aucun chemin du disque.

## 9. Ce que le Studio n'est pas

- Pas un moteur de rendu : le rendu et l'export sont la Slice 16 (le garde refuse les processus enfants, donc le bouton « Render » du Studio échoue visiblement).
- Pas un éditeur qui écrit dans la bibliothèque : ses modifications sont mises de côté, jamais publiées.
- Pas un lieu d'exécution isolé comme le Player : la scène y tourne dans l'onglet du Studio (§11).

## 10. Preuves

Harnais `scripts/remotion_studio_harness.py` : **Core isolé** (`python -m jarvis core`, racine de données privée, hôte `127.77.0.9` et port libres), **vraie installation npm** de la capacité, **vraie bibliothèque de prefabs**, **vrai `remotion studio`**, **vrai Control Center isolé**, **vrai Chrome** piloté par DevTools. Sortie : `tasks/jarvis-remotion-presentation-integration/slices/11-remotion-studio-process-ui/evidence/real-studio.json` et `evidence/screens/*.png`. Reproduction : `python scripts/remotion_studio_harness.py --work-dir <dossier court sous Temp> --evidence <fichier.json>` (≈ 8 minutes, ≈ 600 Mo, jamais le JARVIS vivant). Le verdict `PASSED` exige toutes les vérifications ; les valeurs de la dernière exécution sont dans le fichier (tête de dépôt, plate-forme, versions de Node et de Chrome) :

| Groupe | Ce qui est prouvé |
| --- | --- |
| 0-2 | le démarrage de Core ne lance aucun Studio ; installation réelle de la capacité ; une scène inconnue est refusée sans rien lancer |
| 3-4 | ouverture (démarrage à froid de webpack, 30 à 50 s) ; écoute **seulement** sur la boucle locale (netstat sur l'arbre) ; l'adresse du réseau local refuse le port ; CSP présente |
| 5 | Chrome affiche la scène ; une nouvelle version publiée puis `sync` s'affiche **sans recharger la page** (moins de 2 s) ; la CSP de la page bloque `fetch` vers un autre domaine et une image distante |
| 6-7 | `open` répété : même hôte ; autre scène : même processus ; copie en lecture seule ; une modification extérieure est signalée puis mise de côté avant la synchronisation ; la bibliothèque ne la reçoit jamais |
| 8-9 | `restart` remplace tout l'arbre ; un processus tué hors de Jarvis devient `failed`/`process_exited` ; `open` récupère ; `close` ne laisse ni processus node ni port |
| 10 | interface : carte arrêtée, jamais de lancement par la carte, progression avec durée écoulée et échéance, lien loopback, ouverture dans une fenêtre à part (geste de l'utilisateur), `sync`, échec expliqué, relance, fermeture, 390 px, aucune exception de script |
| 11-12 | inactivité réelle (60 s) : arrêt automatique ; Core tué brutalement : le Studio survit et le Core suivant l'**adopte** ; sans Core, le garde l'achève (≈ 60 s) ; arrêt propre de Core : `core_stopped`, aucun orphelin |
| 13-14 | port occupé : refus typé ; `uninstall` avec Studio ouvert : le Studio est arrêté d'abord |

Tests automatiques (aucun réseau, aucun navigateur) : `tests/unit/test_remotion_studio.py` (domaine et service, faux runner), `test_remotion_studio_runner.py` (disque réel : copie, lecture seule, modifications, liens ; HTTP de boucle locale réel ; faux spawn), `test_remotion_studio_guard.py` (le garde exécuté par un vrai Node, sans Remotion), `test_remotion_studio_routes.py` (vrai Core, vraie bibliothèque), `test_control_center_remotion_studio.py` (relais, chaîne réelle Control Center → Core, module JavaScript par node), `test_remotion_studio_docs.py` (ce document contre le code). Opt-in : `test_remotion_studio_real.py` (`JARVIS_REMOTION_RUNTIME_DIR`, vrai Studio, rechargement à chaud observé dans le paquet servi).

## 11. Limites et risques résiduels

- **La scène s'exécute dans l'onglet du Studio, sans le bac à sable du Player** (Slice 06) : même origine que l'API du Studio, hors iframe `sandbox`. Frontières réelles : (a) les gardes statiques (publication et relecture) ; (b) le garde du processus (aucune connexion sortante, aucun DNS, aucun UDP, aucun enfant sauf esbuild) ; (c) la CSP de la page (la preuve réelle bloque `fetch` et les images vers un autre domaine) ; (d) la copie en lecture seule, sans secret de Jarvis dans le processus ni dans le dossier. **Ce qui reste ouvert** : la CSP ne couvre pas WebRTC ni `<link rel=dns-prefetch|preconnect>` depuis le navigateur de l'utilisateur (même limite que [remotion-isolation.md](remotion-isolation.md) §9, sans le durcissement dans le royaume du bac à sable) ; la scène peut appeler l'API du Studio (lecture de la copie, écriture bloquée par l'attribut lecture seule sous Windows mais pas la suppression sous POSIX) ; un module natif ou un autre processus n'est pas couvert par un garde en JavaScript. N'ouvrir le Studio que sur une scène que l'on connaît.
- **Le garde n'est pas un bac à sable du système d'exploitation** : un code natif, un `worker_threads` rechargeant un module non patché, ou `process.binding` y échappent. Aucun accès aux secrets de Jarvis n'existe dans ce processus (environnement en liste blanche), mais il tourne avec les droits de l'utilisateur sur ses fichiers.
- **Licence Remotion non examinée ici** (contrat distinct, [local-capabilities.md](local-capabilities.md) §6). Le Studio affiche, selon la version et l'usage, des invites ou rappels de licence ; aucune clé n'est configurée, `--disable-ask-ai` coupe l'assistant en ligne, et les appels sortants du Studio (vérification de version, ressources distantes) échouent par construction, ce qui est visible dans `egress_blocked`.
- **Premier démarrage lent** : webpack construit tout le Studio à froid (30 à 50 s mesurés), 120 s au plus ; ensuite le rechargement à chaud est immédiat.
- **Un fichier de la copie modifié par le Studio** n'est détecté qu'à la lecture de l'état, à la fermeture et avant une synchronisation (comparaison d'empreintes), pas en continu.
- **Windows uniquement éprouvé en réel** ; POSIX est couvert par la logique (groupe de processus, `ps`/`/proc`) et les tests unitaires, non exécuté.
- **Une seule fenêtre d'édition** : un second onglet du même Studio est possible ; Jarvis ne les distingue pas (compte seulement).
- **Pas de reprise automatique après un plantage** : `failed` + `Relancer` (explicite) ; l'idée est qu'un Studio qui plante à répétition soit vu, pas masqué.
