# Isolation du code d'une scène Remotion : gardes statiques, bac à sable d'exécution, bornes

Handoff `jarvis-remotion-presentation-integration`, Slice 06. **Statut : contrat (Level 2) et implémentation (Level 3) livrés ; éprouvés dans un vrai Chrome contre un corpus de scènes hostiles compilées par le vrai compilateur** ([preuve](#8-preuves)). Ce que ce document ne fait pas : monter le Player ni servir les fichiers par une route de Core (Slice 10), pont de contrôles (Slice 13), édition à chaud (Slice 14), import d'un gabarit amont (Slice 18). Rien ici ne démarre, n'arrête ni ne relance Core, le Control Center, la voix ou ai-visualizer.

Termes : la **source** d'une scène est un prefab Remotion v2 ([remotion-source.md](remotion-source.md)) ; le **bundle** est le `scene.js` compilé (Slice 05) ; le **cadre** est l'`<iframe>` qui l'exécute ; l'**hôte** est la page qui l'encadre (le Control Center) ; le **bac à sable** est le cadre plus l'origine, la CSP et le protocole décrits ici. Le précédent côté navigateur est le bac à sable des prefabs HTML ([SECURITY.md](SECURITY.md) § 16) : même idée (`sandbox="allow-scripts"` exactement, CSP fermée, `postMessage` versionné, source vérifiée), étendue à une origine dédiée parce qu'ici le code est du JavaScript complet (React, Remotion) et non un gabarit de quelques lignes.

## 1. Modèle de menace

Le code d'une scène (TSX/JS écrit par un agent, issu d'un modèle ou importé) est **hostile par défaut**. Ce qu'un attaquant veut, et la couche qui le lui refuse :

| Objectif de la scène | Refusé par |
| --- | --- |
| Lire les jetons, cookies, stockage, DOM du Control Center ; agir comme Jarvis (outils, Core) | origine dédiée + `sandbox` sans `allow-same-origin` (origine opaque) + aucun secret dans la page du cadre |
| Exfiltrer par le réseau (`fetch`, XHR, WebSocket, balise, `<img>`, CSS `url()`) | CSP `connect-src 'none'`, `img-src 'self' data:`, `default-src 'none'` ; garde statique `network_api` |
| Exécuter du code construit (`eval`, `Function`, minuterie à chaîne, `import()`, Worker, handler en ligne) | CSP sans `unsafe-eval` ni `unsafe-inline` (scripts par nonce), `worker-src 'none'` ; garde statique |
| Ouvrir une fenêtre, naviguer le cadre, l'hôte ou le sommet | `sandbox` sans `allow-popups`/`allow-top-navigation` ; `frame-src` de l'hôte ; détection par le chien de garde |
| Se faire passer pour l'hôte (messages forgés) ou être piloté par un tiers | protocole `rs:1` : source + origine + champs exacts, bornes, plafond d'infractions |
| Figer ou ruiner le poste (boucle, mémoire, DOM énorme) | processus séparé (iframe d'origine distincte) + chien de garde ping/pong + plafond de tas déclaré |
| Contenu actif dans un asset (SVG avec script, faux PNG) | garde statique des assets ; `nosniff`, type fixé par l'extension, CSP `sandbox` sur chaque fichier servi |
| Faire exécuter du code au serveur (Node, npm) lors de la compilation | la compilation **n'exécute jamais** le code de la scène (esbuild transforme du texte) ; environnement sans secret, tas plafonné, délai, arbre tué |

Hors périmètre, dit sans fard : un compte local déjà compromis, un navigateur dont l'isolation de sites est désactivée, une faille du navigateur ou de V8 (le bac à sable est exactement aussi fort que Chrome), la tromperie visuelle **à l'intérieur** du cadre (une scène peut dessiner un faux formulaire ; elle ne peut ni le soumettre ni quitter son cadre), l'usure de CPU d'une scène qui reste réactive (§ 9).

## 2. Les couches, de la plus proche de l'agent à la plus proche du navigateur

| # | Couche | Où | Nature |
| --- | --- | --- | --- |
| 1 | Gardes statiques (`SOURCE_GUARDS`) | `jarvis/domain/remotion_isolation.py` | filtre : refuse tôt, avec fichier et ligne |
| 2 | Origine dédiée, `Host` vérifié | `jarvis/domain/remotion_sandbox.py`, `jarvis/runtime/remotion_sandbox.py` | **frontière** |
| 3 | `<iframe sandbox="allow-scripts">` + directive CSP `sandbox` | idem | **frontière** |
| 4 | CSP à nonce, fichiers à `integrity` | idem | **frontière** |
| 5 | Protocole `rs:1` et chien de garde | `jarvis/runtime/remotion_sandbox_protocol.js`, `remotion_sandbox_child.js` | contrôle de l'hôte sur un cadre hostile |
| 6 | Compilation sans exécution, environnement nu | `jarvis/adapters/remotion_compiler.py`, `node_capability_runner.py` | côté serveur |

La couche 1 n'est **pas** une frontière : une expression régulière sur du JavaScript est contournable, et le corpus de preuve contient, pour chaque attaque, une version écrite pour passer la couche 1 (§ 8). Les couches 2 à 4 sont la frontière, et chacune tient seule (ablations, § 8).

## 3. Gardes statiques

`SOURCE_GUARDS = (isolation_guard,)` (`jarvis/domain/remotion_source.py`) : appelé à la **publication** (`PrefabService.save`) **et** à chaque relecture des octets d'une version (`PrefabService.remotion_source`, donc avant toute compilation). Aucun octet n'est réécrit ni « nettoyé » : l'agent corrige et publie une nouvelle version.

**Version déjà publiée qu'une garde refuse** (décision demandée par le contrat de la Slice 05, § 7) : elle n'est **pas** `tampered` (ses octets sont ceux publiés) mais `invalid_definition` à la relecture, avec les constats ; le catalogue la liste toujours, son dossier reste intact pour le diagnostic, rien n'est réécrit (testé : `test_a_version_published_before_a_guard_is_refused_on_reread_and_its_bytes_are_left_alone`). Elle ne se compile ni ne se joue tant qu'une nouvelle version n'est pas publiée.

**Forme d'un constat** : `chemin:ligne: code - explication` (`parse_finding` le décompose pour une UI ou un agent). Au plus 5 par fichier. Les modules sont lus **en texte brut, sans lexeur** (un lexeur approximatif est lui-même contournable) : une règle ne vise que des formes de code (`nom.`, `nom[`, `nom(`, valeur passée), pas le mot isolé, pour qu'une diapositive qui dit « le document parent » ne soit pas refusée.

| Code | Refuse |
| --- | --- |
| `network_api` | `fetch`, `XMLHttpRequest`, `WebSocket`, `WebTransport`, `EventSource`, `RTCPeerConnection`, `sendBeacon` |
| `code_execution` | `eval`, `Function`, `execScript` |
| `constructor_chain` | `.constructor.constructor`, `.constructor(`, `["constructor"]` |
| `dynamic_import` | `import()`, `require()`, `import.meta` |
| `string_timer` | `setTimeout("...")`, `setInterval("...")`, `setImmediate("...")` |
| `worker_or_channel` | `Worker`, `SharedWorker`, `ServiceWorker`, `Worklet`, `importScripts`, `MessageChannel`, `BroadcastChannel`, `postMessage`, sélecteurs de fichiers |
| `realm_access` | `window`, `globalThis`, `self`, `document`, `parent`, `top`, `opener`, `navigator`, `location`, `history`, `localStorage`, `sessionStorage`, `indexedDB`, `caches`, `cookieStore` suivis de `.` ou `[` |
| `realm_value` | ces noms (sauf `top`, `parent`, `location`, `history`, que l'on peut nommer variable) passés comme valeur |
| `realm_property` | `.cookie`, `.opener`, `.contentWindow`, `.contentDocument`, `.defaultView`, `.ownerDocument` |
| `popup_or_dialog` | `open()`, `alert()`, `confirm()`, `prompt()` |
| `markup_tag` | éléments `script`, `iframe`, `frame`, `embed`, `object`, `applet`, `link`, `meta`, `base` (JSX ou `createElement`) |
| `srcdoc` | `srcDoc` / `srcdoc` |
| `inline_handler_string` | `onclick="..."`, `onerror="..."` et semblables en chaîne (une fonction JSX reste permise) |
| `active_url_scheme` | `javascript:`, `vbscript:`, `data:text/html`, `data:image/svg+xml` |
| `external_resource` | `src=`/`href=`/`poster=`/`action=` vers `http(s)://` ou `//`, `url(http...)`, `@import` : les fichiers vivent dans `public/` et se lisent par `staticFile()` |
| `obfuscated_name` | `["fe" + "tch"]` (deux littéraux concaténés dans un crochet), `atob()` |
| `unbounded_loop` | `while (true)`, `for (;;)`, `do {} while (true)` : une animation se calcule à partir du numéro d'image |

Une ligne de plus de `MAX_LINE_CHARS` = 50 000 caractères est refusée avant toute expression régulière (code minifié ou généré). Les `.json` ne s'exécutent pas et ne sont pas analysés.

**Assets** (`scan_asset`) : la **signature binaire** doit correspondre à l'extension (`.png`, `.jpg`, `.gif`, `.webp`, polices, `.mp3`, `.wav`, `.ogg`, `.mp4`, `.webm` ; un faux PNG qui est du HTML est refusé, `asset_signature`) ; un **SVG** est refusé s'il contient `<script>`, `foreignObject`/`iframe`/`embed`/`object`, un attribut `on*=`, `javascript:`, une déclaration `<!ENTITY>`, une référence autre que `#fragment` ou raster `data:`, un `url()` externe ou `@import`, ou une animation de `href`/`on*` (codes `svg_*`).

**Bornes** (inchangées de la Slice 05, rappelées parce qu'elles font partie de l'isolation) : 64 modules de 256 Kio (1 Mio au total), 64 assets de 4 Mio (16 Mio au total), chemins lexicaux, `scene.js` ≤ 4 Mio, délai de compilation 60 s, hôte 120 s ; plus, ici : 50 000 caractères par ligne, 5 constats par fichier.

**Archives** (import de gabarits, appelé par la Slice 18 ; rien ne l'appelle encore) : `archive_problems(entrées)` et `read_zip_source(octets)` lisent un ZIP **en mémoire** (jamais sur disque) : seuls `src/**` et `public/**` aux mêmes chemins et extensions qu'une source ; `package.json`, `node_modules`, scripts d'installation, archives imbriquées (`.zip .tar .tgz .gz .7z .rar .jar`), liens symboliques, membres chiffrés, plus de 160 entrées, plus de 24 Mio extraits, taux de compression > 100:1, ou membre dont la taille réelle diffère du répertoire sont refusés (`archive_path`, `archive_nested`, `archive_symlink`, `archive_encrypted`, `archive_ratio`, `archive_size`). **Aucune installation npm implicite** : les dépendances d'une scène sont les paquets verrouillés de la capacité (`SCENE_ALLOWED_IMPORTS`), un `package.json` est refusé, le compilateur n'appelle jamais npm (testé).

## 4. Contrat d'exécution isolée

Rien n'est câblé ici (Slice 10) ; ces fonctions sont pures et testées (`tests/unit/test_remotion_isolation.py`), et la preuve navigateur les consomme telles quelles.

**Origine** : un second écouteur de boucle locale, **autre adresse et autre port** que Core (`127.77.0.1:17653`) : par exemple `127.77.0.2:17654`. Un autre port seul ne suffit pas (les cookies se partagent entre ports d'un même hôte) : `assert_distinct_origins` et le constructeur de `SandboxResponder` le refusent. Ce serveur ne sert que le contenu non secret de la compilation, ne pose jamais de cookie ni de jeton (`assert_no_ambient_authority` sur chaque réponse) et ne reçoit jamais de requête de Core avec un jeton.

**Cadre** (`IFRAME_ATTRIBUTES`) : `sandbox="allow-scripts"` — exactement cette valeur, jamais `allow-same-origin`, `allow-popups`, `allow-forms`, `allow-top-navigation`, `allow-modals`, `allow-downloads`, `allow-pointer-lock` (`FORBIDDEN_SANDBOX_TOKENS`) —, `allow=""` (aucune fonction de navigateur), `referrerpolicy="no-referrer"`, `loading="eager"`.

**Routes** (`SandboxResponder.respond`, servies par ce que le Player de la Slice 10 montera sur l'origine dédiée) :

| Route | Rend |
| --- | --- |
| `GET /page/<scene-clé>/<host-clé>` | le document du cadre : `host.js`, l'amorce en ligne, puis `scene.js`, chacun avec le nonce de la réponse ; `host.js` et `scene.js` portent `integrity="sha384-..."` calculé sur les octets servis et `crossorigin="anonymous"` |
| `GET /f/<clé>/scene.js \| host.js \| public/<asset>` | un fichier **déclaré** par `compile.json`, par `RemotionCompiler.resolve_output_file` (SHA-256 vérifié) ; jamais `compile.json`, jamais `src/` |

Chemin lexical : aucun `%`, `\`, `..`, NUL, non-ASCII, plus de 240 caractères ; clés du compilateur (`scene-<32 hex>`, `host-<32 hex>`) ; assets selon `source_path_problem`. `GET`/`HEAD` seulement (405), `Host` dans la liste (421, ré-association DNS), un seul intervalle `Range` pris en charge pour la lecture média, erreurs uniformes sans chemin disque (404 / 500 + journal `remotion.sandbox.unknown_file` / `unavailable`).

**CSP du document** (`page_csp`, en-tête et non `<meta>` : `frame-ancestors` et `sandbox` n'existent qu'en en-tête) :

```
default-src 'none'; script-src 'nonce-<24 car. neufs par réponse>'; style-src 'unsafe-inline'; img-src 'self' data:;
media-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none';
object-src 'none'; manifest-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors <origine de l'hôte>; sandbox allow-scripts
```

`style-src 'unsafe-inline'` est le même compromis que SECURITY.md § 16 (React pose des styles en ligne) : sans chemin de sortie (`img-src`, `font-src`, `connect-src` fermés) une feuille de style ne peut rien exfiltrer. `media-src data:` : le Player de Remotion débloque l'audio par un clip `data:` (relevé par la preuve réelle) ; un `data:` porte ses propres octets. L'ordre des scripts est un contrat : `host.js` (de confiance), l'amorce (qui prend ses références `parent`, `postMessage` et ses écouteurs **avant** que la scène puisse les remplacer), puis `scene.js` (hostile).

**En-têtes de chaque réponse** : `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (caméra, micro, géolocalisation, USB, HID, paiement... vides), `Cross-Origin-Resource-Policy: cross-origin`, `Cross-Origin-Opener-Policy: same-origin`. **Fichiers** : type fixé par l'extension (table `CONTENT_TYPES`, extension inconnue = refus, jamais deviné), `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; sandbox` (un SVG ouvert comme document n'exécute rien), `Cache-Control: private, max-age=31536000, immutable` (la clé est le contenu), `Accept-Ranges: bytes` ; `Access-Control-Allow-Origin: *` pour les **scripts et les polices seulement** (le document est d'origine opaque : `integrity` et `@font-face` exigent CORS ; ce sont des fichiers non secrets, lus sans cookie). **Page** : `Cache-Control: no-store`. Aucune réponse ne porte `Set-Cookie`, `Authorization` ni `WWW-Authenticate`.

**Côté hôte** (à reprendre par la Slice 10) : créer le cadre avec `IFRAME_ATTRIBUTES` ; la page de l'hôte porte `Content-Security-Policy: frame-src <origine du bac à sable>` (`embedder_frame_src`, à fusionner avec la directive existante du visualiseur, `frame_src_policy` de `control_center.py`) : un cadre qui tente `location.href = ...` est bloqué avant toute requête (prouvé : requêtes reçues = 0) ; écouter `message` **en vérifiant la source** (`event.source === iframe.contentWindow`) ; charger `remotion_sandbox_protocol.js` ; ne jamais mettre dans `init` autre chose que les `inputProps` de la scène.

## 5. Protocole `rs: 1`

Mêmes principes que `jv: 1` des prefabs ([prefabs.md](prefabs.md)), un fichier pur, utilisé **par les deux pages** (hôte et cadre) : `jarvis/runtime/remotion_sandbox_protocol.js`, exposé en `window.RemotionSandboxProtocol` et `module.exports`.

| Sens | Types (champs exacts, une clé de plus est un refus) |
| --- | --- |
| hôte -> cadre | `init {composition{id,width,height,fps,durationInFrames}, props}`, `props {props}`, `control {action: play\|pause\|seek, frame?}`, `cue {name, frame}`, `ping {n}`, `teardown {}` |
| cadre -> hôte | `ready {}`, `pong {n, frame, dropped, heap?}`, `violation {directive, blocked}`, `error {message}` |

- **Contrôle de l'expéditeur** : côté hôte, `event.source === iframe.contentWindow` ; l'origine d'un cadre `sandbox` sans `allow-same-origin` est toujours la chaîne `"null"` et ne distingue personne, elle n'est qu'un second contrôle. Côté cadre : `event.source === window.parent` **et** `event.origin ===` l'origine de l'hôte (baked dans la page) ; le cadre n'envoie qu'à cette origine (`targetOrigin` explicite). Un cadre frère ne peut donc pas piloter la scène (prouvé).
- **Bornes avant travail** : `jsonBudget` s'arrête dès que la borne est dépassée (cadre -> hôte 2 Kio, props 64 Kio, profondeur 8, 2 000 nœuds, JSON simple seulement, jamais une clé `__proto__`) ; une chaîne géante n'est pas parcourue. Les valeurs acceptées sont des **copies** fraîches et bornées. Composition : 16 à 7 680 px, 1 à 120 images/s, 1 à 108 000 images ; cue : nom `[a-z][a-z0-9_]{0,39}`.
- **Chien de garde** (`createSupervisor`) : `ping {n}` toutes les secondes avec un jeton neuf, `pong` correspondant exigé ; aucune réponse en `silentMs` = 3 s : le cadre est retiré (`unresponsive`) ; pas de `ready` en 10 s (`no_ready`). Une autre fenêtre qui écrit à l'hôte n'est pas la faute du cadre (comptée à part). Les refus de protocole s'additionnent : `maxViolations` = 20 retire le cadre (`protocol_abuse`) ; au-delà de 200 messages par seconde les messages sont jetés **avant** analyse. `violation`/`error` limités à 20 par seconde. Le `pong` rapporte le tas JS du cadre en Mo (`performance.memory`, -1 si absent) : au-delà de `maxHeapMb` = 768 le cadre est retiré (`memory`).
- **Ce que le cadre reçoit** : les `inputProps`, la composition, des ordres de lecture. Il ne reçoit ni jeton, ni outil, ni adresse de Core ; il n'a d'ailleurs aucun moyen de joindre Core (`connect-src 'none'`).
- **Rapport de CSP** : l'amorce remonte chaque violation de CSP à l'hôte (`violation`), que la Slice 10 doit tracer (« la scène X a tenté une connexion bloquée »).

## 6. Côté serveur : le processus de compilation

La compilation **ne lance jamais le code de la scène** : esbuild transforme du texte dans un système de fichiers virtuel (Slice 05) ; un import hors liste, `import("...")` à littéral, `fs`, `node:*`, une URL sont refusés par le compilateur lui-même (`compile_import_refused`, troisième couche constatée par la preuve). Le processus `node runtime-host.mjs --compile` : environnement en **liste blanche** (`process_tree.ENV_ALLOWLIST`, aucun `*_KEY`, `*_TOKEN`, `*_SECRET` ; testé), répertoire de travail = dossier `runtime/` de la capacité, **tas V8 plafonné à 1 Go** (`--max-old-space-size=1024`, `SCRIPT_NODE_FLAGS`, Slice 06), délai de 60 s / 120 s avec arbre de processus tué, sortie bornée (4 Mio / 8 Mio), suivi par `cancel_all` à l'arrêt de Core. Un plantage ou un dépassement de ce processus est un échec typé (`compile_compiler_failed`, `compile_timeout`) ; Core et le Control Center ne sont pas touchés (testé : `test_remotion_compiler_real.py::test_pathological_but_in_bounds_sources_end_quickly_and_typed`, imbrications de 120 000 niveaux et table de 9 000 entrées). Pas d'utilisateur ou de répertoire dédié : le processus tourne sous le compte de l'utilisateur, comme tous les processus enfants de la capacité (§ 9).

## 7. Contrat pour les Slices suivantes

- **10 (Player)** : servir `SandboxResponder` sur un second écouteur de boucle locale (`load_bootstrap()` pour l'amorce, `compiler.resolve_output_file` pour les fichiers) ; créer le cadre avec `IFRAME_ATTRIBUTES` ; fusionner `embedder_frame_src(...)` dans `frame_src_policy` ; vérifier la source de chaque message avec `createSupervisor` (pas de logique de confiance à côté) ; appeler `tick()` toutes les 250 ms ; sur `kill`, retirer le cadre, afficher la raison en clair (« la scène ne répond plus depuis 3 s », « trop de mémoire », « messages invalides ») avec un bouton de rechargement, journaliser `remotion.sandbox.killed` ; ne jamais ajouter `allow-same-origin`, `unsafe-eval` ni `unsafe-inline` à un script ; ne jamais monter `scene.js` dans une page qui n'est pas ce bac à sable.
- **13 (contrôles)** : les contrôles et les cues passent par `props` / `control` / `cue` ; un nouveau type de message s'ajoute à `FIELDS`, aux deux listes de types et à ses bornes, avec un test, jamais en contournant `validate`.
- **14 (édition à chaud)** : une édition est une nouvelle version, donc repasse par les gardes ; ne jamais servir un fichier non publié.
- **18 (import)** : `read_zip_source` d'abord, puis `build_candidate` (gardes de la source) ; aucune exécution de script du gabarit, aucun `npm install`.
- **Toute extension de la liste d'imports** (`SCENE_ALLOWED_IMPORTS`) donne à une scène une API de plus : la revoir ici.

## 8. Preuves

Harnais `scripts/remotion_isolation_harness.py` (pilote DevTools `scripts/remotion_isolation_cdp.mjs`, Node >= 22, aucune dépendance). **Réel** : le compilateur (Node + esbuild du verrou), le `PrefabService` et ses gardes, les en-têtes, la page et la route livrés, le protocole et le chien de garde JavaScript livrés, Chrome. **Simulé** : l'hôte (une page minimale qui plante un cookie, un `localStorage`, une variable globale et un jeton) et trois origines de boucle locale (hôte `127.0.0.1`, bac à sable `127.0.0.2`, puits d'exfiltration `127.0.0.3` qui journalise tout). Racine de données et profil Chrome jetables ; les « bombes » sont bornées (240 à 400 Mio) même si un plafond échoue. Sortie : `tasks/jarvis-remotion-presentation-integration/slices/06-remotion-source-isolation/evidence/real-isolation.json` (SHA du dépôt, versions de Chrome et de Node, 34 vérifications avec leurs constats, console du navigateur, requêtes reçues).

Corpus : `tests/fakes/remotion_hostile.py`, chaque échantillon en version `direct` (refusée par la couche 1) et `evasive` (écrite pour passer la couche 1, publiée avec les gardes réelles, compilée, chargée).

| Échantillon | Constat dans Chrome |
| --- | --- |
| `net_exfil` (fetch, XHR, WebSocket, sendBeacon, Image, CSS `url()`) | 0 requête reçue par le puits ; violations `connect-src` et `img-src` remontées à l'hôte |
| `storage_read` (localStorage, sessionStorage, cookie, indexedDB) | 4/4 `SecurityError`, aucun secret |
| `parent_access` (`parent.document`, `top.JARVIS_TOKEN`, `parent.location`...) | 4/4 `SecurityError`, `opener` nul |
| `window_nav` (`window.open`, navigation du sommet, du parent, du cadre) | `open` rend `null` (« allow-popups » absent), navigations bloquées, 0 requête ; le cadre dont la navigation est refusée par `frame-src` meurt et est retiré par le chien de garde |
| `code_exec` (eval, Function, minuterie à chaîne, import(), Worker) | `EvalError` ×3 ; minuterie et Worker refusés par le navigateur (violations `script-src`, `worker-src`) |
| `infinite_loop`, `memory_bomb`, `dom_bomb` | cadre retiré par le chien de garde ~4 s après le début (3 s de silence), **l'hôte garde un écart de minuterie maximal de 10 à 16 ms** : le cadre est bien un autre processus |
| `memory_creep` (réactif, +8 Mio / 50 ms) | seul le rapport de tas l'arrête : retiré à 174 à 201 Mo (seuil de la preuve 128, défaut livré 768) |
| `svg_script` (script, `onload`, image externe, iframe) | refusé à la publication ; publié sans la couche 1 : aucun script ni requête ; ouvert comme document : « Blocked script execution », titre inchangé |
| `inline_injection` (`dangerouslySetInnerHTML` avec `onerror`, `onload`, `<script>`) | 0 requête, violation de CSP remontée |
| `postmessage_spoof` (messages forgés, 1 Mo, `__proto__`, 3 000 de rafale) | cadre retiré en ~140 ms pour `protocol_abuse` ; 1 seul message accepté ; aucune pollution de prototype |
| frère qui écrit au cadre (`props`, `ping`, `teardown` forgés) | ignoré par le cadre (compteur `dropped` > 0), titre inchangé |
| scène honnête | s'affiche, `props` met le titre à jour, `seek` et `cue` avancent l'image, l'image `staticFile` se charge, `pong` régulier, 0 violation |

**Contrôles négatifs** : les mêmes octets servis depuis l'origine de l'hôte, sans `sandbox` ni CSP, **fuient** : `localStorage`, `sessionStorage`, cookie, `parent.document`, `top.JARVIS_TOKEN` rendent les secrets ; `fetch`, XHR, balise, image atteignent le puits. Le harnais voit donc une évasion quand elle existe. **Ablations** : sans CSP (cadre `sandbox` et origine dédiée conservés) le réseau s'ouvre (6 requêtes reçues) mais aucun secret de l'hôte n'est lu ; sans `sandbox` (origine dédiée et CSP conservées) aucun secret de l'hôte n'est lu non plus, le réseau reste fermé, et l'hôte refuse tous les messages du cadre (`bad_origin`) : chaque couche porte du poids et aucune ne dépend d'une autre pour les secrets de l'hôte.

Tests automatiques (aucun réseau, aucun navigateur) : `tests/unit/test_remotion_isolation.py` (gardes sur le corpus et sur le code honnête, faux positifs, assets, branchement et relecture, CSP, en-têtes, chemins, page, route, archives, processus de compilation), `tests/unit/test_remotion_sandbox_protocol_js.py` (protocole et chien de garde, par node), `tests/unit/test_remotion_isolation_docs.py` (ce document contre le code). Opt-in : `tests/unit/test_remotion_isolation_real.py` et `test_remotion_compiler_real.py` (`JARVIS_REMOTION_RUNTIME_DIR`).

Relancer la preuve (hors profil vivant, Core non touché) : `python scripts/remotion_isolation_harness.py --work-dir <court> --runtime-dir <racine>/local_capabilities/remotion/runtime --evidence <fichier.json>`.

## 9. Limites et risques résiduels

- **Navigateur** : Chrome 154 seul exercé (Windows 11). Firefox, Safari, WebView2 non. La preuve suppose l'isolation de sites par défaut de Chrome (iframe d'origine distincte = processus distinct) : sur un navigateur qui ne la fournit pas (certains mobiles), une scène qui boucle gèlerait aussi l'hôte et le chien de garde ne pourrait pas agir.
- **CPU** : une scène qui reste réactive tout en brûlant le CPU n'est pas retirée (le chien de garde mesure la réponse, pas la charge) ; le navigateur ralentit les onglets cachés. La Slice 10 peut ajouter une mesure d'avancement d'image (`pong.frame`) si le besoin apparaît.
- **Mémoire** : Jarvis ne peut pas poser de plafond de tas au navigateur de l'utilisateur ; le rapport `pong.heap` dépend de `performance.memory` (propre à Chrome, valeurs arrondies) et d'une scène qui ne le falsifie pas avant l'amorce (l'amorce passe avant `scene.js`, mais `Performance.prototype` n'est pas gelé). Une scène qui alloue très vite (plusieurs Go entre deux `ping`) peut épuiser la mémoire avant d'être retirée ; le navigateur finit par tuer le processus, pas Jarvis. Le plafond de la preuve (128 Mo) est un paramètre de test.
- **Couche 1** : contournable par construction (le corpus l'établit) ; ne jamais s'y fier seule. Des faux positifs sont possibles (`parent.` ou `document.` utilisés comme variables locales) : le message dit quoi renommer.
- **Tromperie visuelle** dans le cadre : une scène peut peindre un faux formulaire ; elle ne peut ni le soumettre (`form-action 'none'`) ni quitter son cadre. L'interface de l'hôte ne doit jamais afficher une demande de secret dans la surface du cadre.
- **Serveur** : pas d'utilisateur ni de Job Object dédié (la mémoire native d'esbuild n'est pas plafonnée, seul le tas V8 l'est) ; le délai tue l'arbre. Le listener du bac à sable est joignable par tout processus local ; il ne sert que du contenu non secret, adressé par un hachage de contenu de 128 bits, avec `Host` vérifié ; `Access-Control-Allow-Origin: *` sur les scripts et polices les rend lisibles par une page web qui connaîtrait la clé.
- **Licence Remotion** : le Player affiche « Some companies are required to obtain a license » (console) ; l'accuser (`acknowledgeRemotionLicense`) est une déclaration juridique de l'utilisateur, non faite ici.
- **Versions publiées avant la garde** : refusées à la relecture (§ 3), pas migrées automatiquement.
- **Conservation de `style-src 'unsafe-inline'`** et du `style` en ligne : voir § 4.
