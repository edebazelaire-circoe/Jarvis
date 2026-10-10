# Isolation du code d'une scène Remotion : gardes statiques, bac à sable d'exécution, bornes

Handoff `jarvis-remotion-presentation-integration`, Slice 06. **Statut : contrat (Level 2) et implémentation (Level 3) livrés ; éprouvés dans un vrai Chrome contre un corpus de scènes hostiles compilées par le vrai compilateur** ([preuve](#8-preuves)). Le montage du Player dans Jarvis et le service des fichiers par un second écouteur de Core sont livrés par la Slice 10 ([§ 10](#10-slice-10--monter-le-cadre-dans-jarvis)). Ce que ce document ne fait pas : édition à chaud (Slice 14, livrée : § 13 ci-dessous et `presentation-studio.md`) ; les variables typées et l'édition rapide (Slice 13) sont au [§ 12](#12-slice-13--variables-typées-et-inputprops-validées), import d'un gabarit amont (Slice 18). Rien ici ne démarre, n'arrête ni ne relance Core, le Control Center, la voix ou ai-visualizer.

Termes : la **source** d'une scène est un prefab Remotion v2 ([remotion-source.md](remotion-source.md)) ; le **bundle** est le `scene.js` compilé (Slice 05) ; le **cadre** est l'`<iframe>` qui l'exécute ; l'**hôte** est la page qui l'encadre (le Control Center) ; le **bac à sable** est le cadre plus l'origine, la CSP et le protocole décrits ici. Le précédent côté navigateur est le bac à sable des prefabs HTML ([SECURITY.md](SECURITY.md) § 16) : même idée (`sandbox="allow-scripts"` exactement, CSP fermée, `postMessage` versionné, source vérifiée), étendue à une origine dédiée parce qu'ici le code est du JavaScript complet (React, Remotion) et non un gabarit de quelques lignes.

## 1. Modèle de menace

Le code d'une scène (TSX/JS écrit par un agent, issu d'un modèle ou importé) est **hostile par défaut**. Ce qu'un attaquant veut, et la couche qui le lui refuse :

| Objectif de la scène | Refusé par |
| --- | --- |
| Lire les jetons, cookies, stockage, DOM du Control Center ; agir comme Jarvis (outils, Core) | origine dédiée + `sandbox` sans `allow-same-origin` (origine opaque) + aucun secret dans la page du cadre |
| Exfiltrer par le réseau : `fetch`, XHR, WebSocket, balise, `<img>`, CSS `url()`, `prefetch`, `preload` | CSP `connect-src 'none'`, `img-src 'self' data:`, `default-src 'none'` ; garde statique `network_api` |
| Exfiltrer par WebRTC (`RTCPeerConnection` vers un `stun:`/`turn:` hostile) | **la CSP n'a pas de directive WebRTC** : l'amorce retire les constructeurs avant la scène (au mieux, dans le domaine du cadre) ; garde statique |
| Exfiltrer par un indice de lien (`<link rel=dns-prefetch\|preconnect>` créé par le DOM) | **aucune couche ne le ferme** (mesuré) : risque résiduel nommé, § 9 |
| Exécuter du code construit (`eval`, `Function`, minuterie à chaîne, `import()`, Worker, handler en ligne) | CSP sans `unsafe-eval` ni `unsafe-inline` (scripts par nonce), `worker-src 'none'` ; garde statique |
| Ouvrir une fenêtre, naviguer le cadre, l'hôte ou le sommet | `sandbox` sans `allow-popups`/`allow-top-navigation` ; `frame-src` de l'hôte ; détection par le chien de garde |
| Se faire passer pour l'hôte (messages forgés) ou être piloté par un tiers | protocole `rs:1` : source + origine + champs exacts, bornes, plafond d'infractions |
| Figer ou ruiner le poste (boucle, mémoire, DOM énorme) | processus séparé (iframe d'origine distincte) + chien de garde ping/pong + plafond de tas déclaré |
| Contenu actif dans un asset (SVG avec script, faux PNG) | garde statique des assets ; `nosniff`, type fixé par l'extension, CSP `sandbox` sur chaque fichier servi |
| Faire exécuter du code au serveur (Node, npm) lors de la compilation | la compilation **n'exécute jamais** le code de la scène (esbuild transforme du texte) ; environnement sans secret, tas plafonné, délai, arbre tué |

**Ce que le bac à sable ne promet pas : « aucune fuite réseau ».** Il promet qu'une scène **ne détient aucun secret de Jarvis** (jeton, cookie, stockage, outils, Core) et ne peut ni agir comme Jarvis ni lire l'hôte. Tout ce que l'hôte lui donne (`inputProps`, assets) est lisible par son code et peut sortir par les canaux résiduels du § 9 (noms DNS, connexion TCP nue) : ne jamais passer à une scène une donnée plus sensible que le contenu de la diapositive.

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

**Forme d'un constat** : `chemin:ligne: code - explication` (`parse_finding` le décompose pour une UI ou un agent). Au plus 5 par fichier. **Bornes de coût** (la garde tourne dans la boucle d'événements de Core, à la publication **et** à chaque relecture) : toute répétition d'un motif est **bornée** (`\s{0,64}`, `[^}]{0,200}`... ; `test_no_rule_has_an_unbounded_repeat` parcourt l'arbre de chaque motif et refuse tout `*`/`+` restant, après la reprise QA B1 : des motifs non bornés mettaient 8 à 29 s sur 256 Kio de lignes courtes) ; chaque règle est mesurée à moins de 1 s sur 256 Kio d'entrées adverses (70 fragments, avec et sans saut de ligne) ; un budget de temps par module (`MODULE_SCAN_BUDGET_S` = 1 s) et par source (`SOURCE_SCAN_BUDGET_S` = 4 s) **refuse** la source (`scan_budget`) au lieu de la laisser tourner ou de l'accepter.

Les modules sont lus **en texte brut, sans lexeur** (un lexeur approximatif est lui-même contournable) : une règle ne vise que des formes de code (`nom.`, `nom[`, `nom(`, valeur passée), pas le mot isolé, pour qu'une diapositive qui dit « le document parent » ne soit pas refusée.

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

**Routes** (`SandboxResponder.respond`, servies sur l'origine dédiée par `RemotionSandboxServer`, § 10) :

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

**Hôtes canoniques** : `origin_of` n'accepte qu'un IPv4 pointé strict de boucle locale (`ipaddress` : ni `127.1`, ni forme décimale ou hexadécimale, ni zéros initiaux) ou `localhost`, et `assert_distinct_origins` compare les formes canoniques.

**Indices de lien** : chaque réponse porte `X-DNS-Prefetch-Control: off` et la page la méta équivalente. Mesuré dans Chrome 154 : cela **n'arrête pas** un `<link rel=dns-prefetch>` ou `preconnect` explicite créé par la scène ; seul le préchargement implicite des ancres est concerné. `prefetch` et `preload` sont bloqués par la CSP (`default-src`, `img-src`).

**Côté hôte** (repris par la Slice 10, § 10, avec ses propres tests) : créer le cadre avec `IFRAME_ATTRIBUTES` ; la page qui monte le cadre porte `Content-Security-Policy: frame-src <origine du bac à sable>` **et rien d'autre** (`embedder_frame_src`, qui n'accepte plus qu'une origine) : surtout pas l'origine du visualiseur ou de Core, sinon une scène navigue son cadre vers une page de Jarvis. Le Control Center héberge aujourd'hui un cadre de visualiseur (`frame_src_policy`) : la Slice 10 doit soit monter le cadre Remotion dans un document qui n'a pas ce `frame-src`, soit trancher et tester l'union en connaissance de cause. Un cadre qui tente `location.href = ...` est alors bloqué avant toute requête (prouvé : requêtes reçues = 0) ; écouter `message` **en vérifiant la source** (`event.source === iframe.contentWindow`) ; charger `remotion_sandbox_protocol.js` ; ne jamais mettre dans `init` autre chose que les `inputProps` de la scène.

## 5. Protocole `rs: 1`

Mêmes principes que `jv: 1` des prefabs ([prefabs.md](prefabs.md)), un fichier pur, utilisé **par les deux pages** (hôte et cadre) : `jarvis/runtime/remotion_sandbox_protocol.js`, exposé en `window.RemotionSandboxProtocol` et `module.exports`.

| Sens | Types (champs exacts, une clé de plus est un refus) |
| --- | --- |
| hôte -> cadre | `init {composition{id,width,height,fps,durationInFrames}, props}`, `props {props}`, `control {action: play\|pause\|seek, frame?, until?}`, `cue {name, frame}`, `ping {n}`, `teardown {}` |
| cadre -> hôte | `ready {}`, `pong {n, frame, dropped, heap?, muted?}`, `clock {frame, playing}`, `violation {directive, blocked}`, `error {message}` |

- **Contrôle de l'expéditeur** : côté hôte, `event.source === iframe.contentWindow` ; l'origine d'un cadre `sandbox` sans `allow-same-origin` est toujours la chaîne `"null"` et ne distingue personne, elle n'est qu'un second contrôle. Côté cadre : `event.source === window.parent` **et** `event.origin ===` l'origine de l'hôte (baked dans la page) ; le cadre n'envoie qu'à cette origine (`targetOrigin` explicite). Un cadre frère ne peut donc pas piloter la scène (prouvé).
- **Bornes avant travail** : `jsonBudget` s'arrête dès que la borne est dépassée (cadre -> hôte 2 Kio, props 64 Kio, profondeur 8, 2 000 nœuds, JSON simple seulement, jamais une clé `__proto__`) ; une chaîne géante n'est pas parcourue. Les valeurs acceptées sont des **copies** fraîches et bornées. Composition : 16 à 7 680 px, 1 à 120 images/s, 1 à 108 000 images ; cue : nom `[a-z][a-z0-9_]{0,39}`.
- **Chien de garde** (`createSupervisor`) : `ping {n}` toutes les secondes avec un jeton neuf, `pong` correspondant exigé ; aucune réponse en `silentMs` = 3 s : le cadre est retiré (`unresponsive`) ; pas de `ready` en 10 s (`no_ready`). Une autre fenêtre qui écrit à l'hôte n'est pas la faute du cadre (comptée à part). Les refus de protocole s'additionnent : `maxViolations` = 20 retire le cadre (`protocol_abuse`) ; au-delà de 200 messages par seconde les messages sont jetés **avant** analyse ; une rafale d'une seconde coûte une infraction, une rafale **soutenue** (`maxFloodSeconds` = 3 secondes de suite au-dessus du plafond) retire le cadre en 3 s (`protocol_abuse`) — et non en 20 s comme avec le seul compteur d'infractions ; une rafale de messages **invalides** le retire en ~0,14 s. `violation`/`error` limités à 20 par seconde. Le `pong` rapporte le tas JS du cadre en Mo (`performance.memory`, -1 si absent) : au-delà de `maxHeapMb` = 768 le cadre est retiré (`memory`). **Le chien de garde et le rapport de tas ne protègent que contre l'abus naïf ou accidentel** : la scène partage le domaine JavaScript du cadre, peut répondre elle-même à un `ping` qu'elle voit passer, forger un `pong` et redéfinir `performance.memory` ; ce qu'elle ne peut pas faire sans rester réactive, c'est geler le cadre.
- **Jeton de ping** : `strongToken()` (128 bits de `crypto.getRandomValues`, 32 hexadécimaux), jamais `Math.random`. **Message énorme** : le clonage structuré d'un `postMessage` de 64 Mo se fait **avant** tout gestionnaire ; mesuré : l'hôte reste figé 240 à 340 ms puis refuse le message sans le parcourir (`too_large`). Le coût croît avec la taille (centaines de Mo = secondes de gel et deux fois la mémoire dans l'hôte) et **l'hôte ne peut pas l'empêcher** (le navigateur clone avant d'appeler le code de l'hôte) : seul le plafond du navigateur le borne. Résiduel nommé au § 9.
- **Ce que le cadre reçoit** : les `inputProps`, la composition, des ordres de lecture. Il ne reçoit ni jeton, ni outil, ni adresse de Core ; il n'a d'ailleurs aucun moyen de joindre Core (`connect-src 'none'`).
- **Rapport de CSP** : l'amorce remonte chaque violation de CSP à l'hôte (`violation`), que la Slice 10 doit tracer (« la scène X a tenté une connexion bloquée »).

## 6. Côté serveur : le processus de compilation

La compilation **ne lance jamais le code de la scène** : esbuild transforme du texte dans un système de fichiers virtuel (Slice 05) ; un import hors liste, `import("...")` à littéral, `fs`, `node:*`, une URL sont refusés par le compilateur lui-même (`compile_import_refused`, troisième couche constatée par la preuve). Le processus `node runtime-host.mjs --compile` : environnement en **liste blanche** (`process_tree.ENV_ALLOWLIST`, aucun `*_KEY`, `*_TOKEN`, `*_SECRET` ; testé), répertoire de travail = dossier `runtime/` de la capacité, **tas V8 plafonné à 1 Go** (`--max-old-space-size=1024`, `SCRIPT_NODE_FLAGS`, Slice 06), délai de 60 s / 120 s avec arbre de processus tué, sortie bornée (4 Mio / 8 Mio), suivi par `cancel_all` à l'arrêt de Core. Un plantage ou un dépassement de ce processus est un échec typé (`compile_compiler_failed`, `compile_timeout`) ; Core et le Control Center ne sont pas touchés (testé : `test_remotion_compiler_real.py::test_pathological_but_in_bounds_sources_end_quickly_and_typed`, imbrications de 120 000 niveaux et table de 9 000 entrées). Pas d'utilisateur ou de répertoire dédié : le processus tourne sous le compte de l'utilisateur, comme tous les processus enfants de la capacité (§ 9).

## 7. Contrat pour les Slices suivantes

- **10 (Player), livrée : voir § 10** : servir `SandboxResponder` sur un second écouteur de boucle locale (`load_bootstrap()` pour l'amorce, `compiler.resolve_output_file` pour les fichiers) ; créer le cadre avec `IFRAME_ATTRIBUTES` ; fusionner `embedder_frame_src(...)` dans `frame_src_policy` ; vérifier la source de chaque message avec `createSupervisor` (pas de logique de confiance à côté) ; appeler `tick()` toutes les 250 ms (sans `tick()`, aucun ping ni aucun retrait : le chien de garde n'existe pas) ; utiliser `strongToken()` (le défaut) et ne pas passer un `token()` faible ;  sur `kill`, retirer le cadre, afficher la raison en clair (« la scène ne répond plus depuis 3 s », « trop de mémoire », « messages invalides ») avec un bouton de rechargement, journaliser `remotion.sandbox.killed` ; ne jamais ajouter `allow-same-origin`, `unsafe-eval` ni `unsafe-inline` à un script ; ne jamais monter `scene.js` dans une page qui n'est pas ce bac à sable ; **`frame-src` de la page qui monte le cadre : l'origine du bac à sable seule, avec son propre test** (voir § 4) ; documenter le résiduel `Access-Control-Allow-Origin: *` des scripts et polices (clés de 128 bits de contenu, mais lisibles par toute page qui les connaît) ; ne passer aux `props` que ce qui peut sortir (§ 9).
- **13 (contrôles), livrée : voir § 12** : les contrôles et les cues passent par `props` / `control` / `cue` ; un nouveau type de message s'ajoute à `FIELDS`, aux deux listes de types et à ses bornes, avec un test, jamais en contournant `validate`.
- **14 (édition à chaud)** : une édition est une nouvelle version, donc repasse par les gardes ; ne jamais servir un fichier non publié.
- **18 (import)** : `read_zip_source` d'abord, puis `build_candidate` (gardes de la source) ; aucune exécution de script du gabarit, aucun `npm install`.
- **Toute extension de la liste d'imports** (`SCENE_ALLOWED_IMPORTS`) donne à une scène une API de plus : la revoir ici.

## 8. Preuves

Harnais `scripts/remotion_isolation_harness.py` (pilote DevTools `scripts/remotion_isolation_cdp.mjs`, Node >= 22, aucune dépendance). **Réel** : le compilateur (Node + esbuild du verrou), le `PrefabService` et ses gardes, les en-têtes, la page et la route livrés, le protocole et le chien de garde JavaScript livrés, Chrome. **Simulé** : l'hôte (une page minimale qui plante un cookie, un `localStorage`, une variable globale et un jeton) et trois origines de boucle locale (hôte `127.0.0.1`, bac à sable `127.0.0.2`, puits d'exfiltration `127.0.0.3` qui journalise tout). Racine de données et profil Chrome jetables ; les « bombes » sont bornées (240 à 400 Mio) même si un plafond échoue. Sortie : `tasks/jarvis-remotion-presentation-integration/slices/06-remotion-source-isolation/evidence/real-isolation.json` (SHA du dépôt, versions de Chrome et de Node, les vérifications avec leurs constats, console du navigateur, requêtes reçues).

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
| `webrtc_exfil` (`RTCPeerConnection` vers un puits UDP) | sans l'amorce durcie : **10 paquets UDP reçus malgré sandbox, origine et CSP** (aussi dans le contrôle négatif) ; avec : `TypeError`, 0 paquet |
| `link_hints` (`dns-prefetch`, `preconnect`, `prefetch`, `preload`) | `prefetch` et `preload` bloqués par la CSP ; **`dns-prefetch` (noms résolus, relevés dans le journal réseau de Chrome) et `preconnect` (1 connexion TCP reçue) restent ouverts**, y compris avec `X-DNS-Prefetch-Control: off` : résiduel nommé |
| `huge_message` (64 Mo) | l'hôte se fige 240 à 340 ms (clonage), refuse `too_large`, le cadre reste vivant (une seule infraction) |
| `postmessage_spoof` (messages forgés, 1 Mo, `__proto__`, 3 000 de rafale) | cadre retiré en ~140 ms pour `protocol_abuse` ; 1 seul message accepté ; aucune pollution de prototype |
| frère qui écrit au cadre (`props`, `ping`, `teardown` forgés) | ignoré par le cadre (compteur `dropped` > 0), titre inchangé |
| scène honnête | s'affiche, `props` met le titre à jour, `seek` et `cue` avancent l'image, l'image `staticFile` se charge, `pong` régulier, 0 violation |

**Contrôles négatifs** : les mêmes octets servis depuis l'origine de l'hôte, sans `sandbox` ni CSP, **fuient** : `localStorage`, `sessionStorage`, cookie, `parent.document`, `top.JARVIS_TOKEN` rendent les secrets ; `fetch`, XHR, balise, image atteignent le puits. Le harnais voit donc une évasion quand elle existe. **Ablations** : sans l'amorce durcie (sandbox, origine, CSP conservés) WebRTC fuit ; sans CSP (cadre `sandbox` et origine dédiée conservés) le réseau s'ouvre (6 requêtes reçues) mais aucun secret de l'hôte n'est lu ; sans `sandbox` (origine dédiée et CSP conservées) aucun secret de l'hôte n'est lu non plus, le réseau reste fermé, et l'hôte refuse tous les messages du cadre (`bad_origin`) : chaque couche porte du poids et aucune ne dépend d'une autre pour les secrets de l'hôte.

Tests automatiques (aucun réseau, aucun navigateur) : `tests/unit/test_remotion_isolation.py` (gardes sur le corpus et sur le code honnête, faux positifs, assets, branchement et relecture, CSP, en-têtes, chemins, page, route, archives, processus de compilation), `tests/unit/test_remotion_sandbox_protocol_js.py` (protocole et chien de garde, par node), `tests/unit/test_remotion_isolation_docs.py` (ce document contre le code). Opt-in : `tests/unit/test_remotion_isolation_real.py` et `test_remotion_compiler_real.py` (`JARVIS_REMOTION_RUNTIME_DIR`).

Relancer la preuve (hors profil vivant, Core non touché) : `python scripts/remotion_isolation_harness.py --work-dir <court> --runtime-dir <racine>/local_capabilities/remotion/runtime --evidence <fichier.json>`.

## 9. Limites et risques résiduels

- **Canaux hors CSP, ouverts** (reprise QA B2) : (1) `<link rel=dns-prefetch>` créé par la scène fait résoudre un nom choisi par elle (environ 190 octets de données par nom, autant de noms que voulu), et `<link rel=preconnect>` ouvre une connexion TCP vers un hôte:port choisi (aussi un balayage aveugle des ports du poste ou du réseau local, sans lire de réponse) ; ni la CSP, ni `X-DNS-Prefetch-Control`, ni la méta, ni `allow=""` ne les ferment. Contre-mesure impossible dans le domaine du cadre (les chemins d'insertion d'un `<link>` sont trop nombreux : `innerHTML`, `insertAdjacentHTML`, `createContextualFragment`...). Ce que ces canaux peuvent faire sortir est borné par ce que la scène détient : ses `props` et ses assets, jamais un secret de Jarvis. (2) WebRTC : l'amorce retire `RTCPeerConnection` et consorts avant la scène, ce qui ferme le canal **tant que la scène ne retrouve pas un constructeur autrement** (au mieux, dans le domaine du cadre) ; la protection forte serait un réglage du navigateur de l'utilisateur (`--force-webrtc-ip-handling-policy`, une politique d'entreprise), que Jarvis ne peut pas imposer. (3) Un `postMessage` énorme fige l'hôte le temps du clonage (§ 5).
- **Chien de garde et tas = abus naïf ou accidentel seulement** : la scène partage le domaine du cadre et peut forger un `pong` ou redéfinir `performance.memory` ; seul le gel du fil est observé par l'hôte.
- **Navigateur** : Chrome 154 seul exercé (Windows 11). Firefox, Safari, WebView2 non. La preuve suppose l'isolation de sites par défaut de Chrome (iframe d'origine distincte = processus distinct) : sur un navigateur qui ne la fournit pas (certains mobiles), une scène qui boucle gèlerait aussi l'hôte et le chien de garde ne pourrait pas agir.
- **CPU** : une scène qui reste réactive tout en brûlant le CPU n'est pas retirée (le chien de garde mesure la réponse, pas la charge) ; le navigateur ralentit les onglets cachés. La Slice 10 peut ajouter une mesure d'avancement d'image (`pong.frame`) si le besoin apparaît.
- **Mémoire** : Jarvis ne peut pas poser de plafond de tas au navigateur de l'utilisateur ; le rapport `pong.heap` dépend de `performance.memory` (propre à Chrome, valeurs arrondies) et d'une scène qui ne le falsifie pas avant l'amorce (l'amorce passe avant `scene.js`, mais `Performance.prototype` n'est pas gelé). Une scène qui alloue très vite (plusieurs Go entre deux `ping`) peut épuiser la mémoire avant d'être retirée ; le navigateur finit par tuer le processus, pas Jarvis. Le plafond de la preuve (128 Mo) est un paramètre de test.
- **Couche 1** : contournable par construction (le corpus l'établit) ; ne jamais s'y fier seule. Des faux positifs sont possibles (`parent.` ou `document.` utilisés comme variables locales) : le message dit quoi renommer.
- **Tromperie visuelle** dans le cadre : une scène peut peindre un faux formulaire ; elle ne peut ni le soumettre (`form-action 'none'`) ni quitter son cadre. L'interface de l'hôte ne doit jamais afficher une demande de secret dans la surface du cadre.
- **Serveur** : pas d'utilisateur ni de Job Object dédié (la mémoire native d'esbuild n'est pas plafonnée, seul le tas V8 l'est) ; le délai tue l'arbre. Le listener du bac à sable est joignable par tout processus local ; il ne sert que du contenu non secret, adressé par un hachage de contenu de 128 bits, avec `Host` vérifié ; `Access-Control-Allow-Origin: *` sur les scripts et polices les rend lisibles par une page web qui connaîtrait la clé.
- **Licence Remotion** : le Player affiche « Some companies are required to obtain a license » (console) ; l'accuser (`acknowledgeRemotionLicense`) est une déclaration juridique de l'utilisateur, non faite ici.
- **Versions publiées avant la garde** : refusées à la relecture (§ 3), pas migrées automatiquement.
- **Conservation de `style-src 'unsafe-inline'`** et du `style` en ligne : voir § 4.

## 10. Slice 10 : monter le cadre dans Jarvis

Handoff `jarvis-remotion-presentation-integration`, Slice 10. **Statut : contrat (Level 2) et implémentation (Level 3) livrés ; éprouvés dans un vrai Chrome contre un Core isolé** (`tests/unit/test_remotion_player_realpage_browser.py`, preuve `tasks/jarvis-remotion-presentation-integration/slices/10-remotion-player-host/evidence/real-player.json`). Une scène Remotion se joue dans Jarvis depuis une Presentation, au même titre qu'une scène HTML : même objet fenêtre de stage, même propriétaire (Core), mêmes règles de pin et de plein écran. Elle ne passe jamais par un `srcdoc` HTML.

### 10.1 Les trois documents, deux origines, un seul `frame-src` utile

```
page du Control Center        http://127.0.0.1:17654/            frame-src <visualiseur> http://127.0.0.1:17654/remotion-stage
  +- fenêtre de stage (prefab host)
       +- page de la scène    http://127.0.0.1:17654/remotion-stage?id=..&v=..   frame-src http://127.77.0.2:17655   (rien d'autre)
            +- bac à sable    http://127.77.0.2:17655/page/<scène>/<hôte>        sandbox="allow-scripts", CSP du § 4
```

**Décision (l'addendum PM la demandait)** : la page principale du Control Center encadre déjà un visualiseur (`frame_src_policy`) ; y ajouter l'origine du bac à sable aurait fait de l'union « visualiseur + bac à sable » le `frame-src` de la page qui monte le cadre Remotion : une scène qui navigue (`location.href`) vers l'origine du visualiseur y chargerait une page de Jarvis. Le cadre Remotion est donc monté par **un document de plus**, `GET /remotion-stage` (`jarvis/runtime/remotion_relay.py`, `control_center_remotion_stage.{html,js}`), de l'origine du Control Center, dont l'en-tête est exactement `Content-Security-Policy: frame-src <origine du bac à sable>` (`embedder_frame_src`) et **rien d'autre** ; `frame-src 'none'` quand Core ne configure aucun bac à sable. La page principale n'encadre ce document que par son **adresse exacte** (`frame-src <visualiseur> http://127.0.0.1:17654/remotion-stage`, une source à chemin et non `'self'` : un cadre de prefab HTML ne peut pas naviguer vers une autre page du Control Center) ; elle ne nomme jamais l'origine du bac à sable.

Mesuré (`test_a_scene_that_navigates_to_an_origin_of_jarvis_sends_no_request` et son contrôle positif) : le « visualiseur » est ici l'écouteur d'un attaquant, encadré par la page principale comme l'est le vrai ; la scène hostile qui assigne `window.location.href` vers lui **n'envoie aucune requête** (l'écouteur ne voit que l'iframe du visualiseur de la page principale) ; avec la même scène et une politique de la page de scène qui nommerait ce visualiseur (l'union que le contrat interdit), la requête **arrive**.

### 10.2 Ce que Core construit et sert

- `JarvisCoreApplication(remotion=<RemotionFactory>)` (port `jarvis/ports/remotion.py` ; `jarvis/app.py` la construit par `_remotion_factory` -> `jarvis/runtime/remotion_composition.py`, `_remotion_sandbox_settings`, réglages `JARVIS_REMOTION_SANDBOX_HOST` défaut `127.77.0.2` et `JARVIS_REMOTION_SANDBOX_PORT` défaut `17655` ; l'origine qui encadre est celle du Control Center, `JARVIS_UI_PORT`) construit : le `RemotionCompiler` (`build_remotion_compiler`, prêt seulement si la capacité locale est `ready`/`running`), le `RemotionSandboxServer` (`jarvis/runtime/remotion_sandbox_server.py`), le `RemotionPlayerService` (`jarvis/core/remotion_player.py`) et la porte du moteur (`StudioEngineGate`, § 10.5). `assert_distinct_origins` refuse un bac à sable qui partage l'hôte du Control Center.
- **L'écouteur n'est ouvert qu'à la première scène Remotion jouée** (`ensure_started`), jamais au démarrage de Core ; un port occupé est un échec typé (`engine_unavailable`, « cannot bind ... »), jamais un cadre vide. Fermé avec Core. Il ne sert que `SandboxResponder.respond` : aucun jeton, aucun cookie, aucune route de Core.
- Routes de Core (jeton porteur ; relayées par le Control Center sous `/api/remotion/...`, mêmes gardes que `/api/prefabs`) : `GET /v1/remotion/sandbox` (état du moteur et origine) ; `GET /v1/remotion/player/{prefab_id}/{version}` : relit la source (gardes de la Slice 06), compile `host.js` et `scene.js` (`asyncio.to_thread`, cache), ouvre l'écouteur et rend le descripteur `{kind: "remotion", page_url, sandbox_origin, composition{id,width,height,fps,durationInFrames}, defaults, engine_drift, compiled}` : aucun chemin disque. `GET /v1/prefabs/{id}/{version}/bundle` d'une source Remotion rend `{kind: "remotion", id, version, title}` seulement (rien d'exécutable, `PrefabService.bundle` la refuse toujours).
- `POST /api/remotion/report` : la page de scène rend compte (`ready`, `failed`, `killed`, `violation`, `scene_error`) ; le Control Center journalise `remotion.stage.*` et `remotion.sandbox.killed` (champs d'une liste fermée, valeurs bornées). Exige l'`Origin` du Control Center lui-même (403 sinon), `Content-Type: application/json` (415) et plafonne à 60 comptes rendus par minute (429).

### 10.3 Ce que fait la page de scène (hôte du cadre)

`control_center_remotion_stage.js` reprend à la lettre le § 7 : cadre créé avec exactement `IFRAME_ATTRIBUTES` (`src` posé **avant** l'insertion, sinon le `load` de l'`about:blank` passerait pour une navigation) ; source de chaque message vérifiée par `createSupervisor(...).accept(event, iframe.contentWindow)` ; **`tick()` toutes les 250 ms tant qu'un cadre est monté** (arrêté au retrait) ; **`strongToken()` par défaut**, jamais un `token()` plus faible (test : 32 hexadécimaux) ; sur `kill`, cadre retiré, raison en clair (« La scène ne répond plus depuis 3 s », « trop de mémoire », « messages invalides », « ne s'est pas lancée dans les 10 s »), bouton « Recharger la scène », `remotion.sandbox.killed` journalisé ; un second `load` du cadre est une navigation (retrait). Ne passe au cadre que les `inputProps` (valeurs par défaut du manifeste sous les valeurs de la scène ; le bloc `data` du manifeste, sous la clé réservée `data`, depuis la Slice 13 : § 12) : **discipline des props**, voir § 10.8.

Le protocole entre la fenêtre de stage et la page de scène (`rsh: 1`, même origine, source = `contentWindow`, champs exacts, `control_center_remotion_frame.js`) : fenêtre -> page `props`, `control {play|pause|seek}` (`frame?`, `until?`, Slice 12), `cue`, `teardown` ; page -> fenêtre `clock {frame, playing, duration, fps}` (Slice 12, § 11) et `status {phase: shell|preparing|mounting|ready|failed|killed|scene_error}`. Les valeurs changent par message (coalescé : au plus un `props` par 16 ms, la dernière gagne), jamais par un nouveau rendu ni un remontage : une édition de couleur, de titre ou de durée est visible en une image et la scène reste éditable. Le prefab host reste propriétaire du cycle de vie (génération, `onOutcome` du rechargement à chaud, pause LRU, démontage, échange « préparé à côté » des sources du Studio : le cadre de la scène suivante est préparé hors écran et ne remplace l'ancien qu'une fois prêt).

Le protocole entre la fenêtre de stage et la page de scène (`rsh: 1`, même origine, source = `contentWindow`, champs exacts, `control_center_remotion_frame.js`) : fenêtre -> page `props`, `control {play|pause|seek}`, `cue`, `teardown` ; page -> fenêtre `status {phase: shell|preparing|mounting|ready|failed|killed|scene_error|notice}`. Les valeurs changent par message (coalescé : au plus un `props` par 16 ms, la dernière gagne), jamais par un nouveau rendu ni un remontage : une édition de couleur, de titre ou de durée est visible en une image et la scène reste éditable. Le prefab host reste propriétaire du cycle de vie (génération, `onOutcome` du rechargement à chaud, pause LRU, démontage, échange « préparé à côté » des sources du Studio : le cadre de la scène suivante est préparé hors écran et ne remplace l'ancien qu'une fois prêt).

### 10.4 États visibles (jamais un repli, jamais un cadre vide)

| État | Ce que l'utilisateur voit | Sortie |
| --- | --- | --- |
| préparation (compilation, jusqu'à 120 s) | « Préparation de la scène Remotion… N s » (compteur vivant), échéance de 150 s | à l'échéance : « La préparation est trop longue » + Réessayer |
| moteur indisponible (capacité absente, à réparer, port pris, Core sans adaptateur) | « Remotion n'est pas disponible » + la raison réelle et la réparation de l'adaptateur | Réessayer ; aucune scène jouée, jamais de HTML |
| erreur de compilation | « La scène ne compile pas » + `fichier:ligne:colonne  texte` (au plus 20) | Réessayer (après une nouvelle version) |
| source refusée par les gardes | « La source de la scène est refusée » + les constats | nouvelle version |
| cadre retiré par le chien de garde | « Scène retirée par le chien de garde » + la raison | Recharger la scène (recompile, remonte, génération suivante) |
| erreur d'exécution d'une scène vivante | bande « Recharger » de la fenêtre | Recharger |

La bande d'erreur de la fenêtre n'est **pas** doublée quand la page de scène dit déjà tout (échec, retrait) : le rapport (`onOutcome`) et les compteurs restent. Dans une petite fenêtre le bouton passe avant les détails. Les panneaux d'échec et de retrait sont annoncés (`role="alert"`), l'attente est un `status` ; le texte est en français (une phrase d'introduction, puis `Détail :` avec les mots réels de Core, puis `Code :`). Une page ouverte par une autre adresse que celle que le bac à sable autorise (`localhost` au lieu de `127.0.0.1`) le dit (« Ouvrez le Control Center via http://127.0.0.1:... ») au lieu d'accuser la scène ; l'adresse du cadre doit être celle de `sandbox_origin` avant tout montage ; un démontage pendant la préparation abandonne la requête et arrête le compteur.

### 10.5 La porte du moteur (`resolve_engine`)

`StudioEngineGate` (`jarvis/core/presentation_studio_engine_gate.py`) appelle `resolve_engine` avec l'état que rapportent les adaptateurs (`RemotionPlayerService.availability()` : seule lecture de la disponibilité de Remotion dans Core). `PresentationStudioService.require_engine(presentation_id, action)` est appelé **avant lire** (`PresentationStudioPlaybackService._start`, avant toute compilation ou mise en scène), **éditer** (`PresentationStudioEditService.edit`, `render_overlay`) et **prévisualiser** (`show_preview`). Un document `remotion` sans adaptateur prêt échoue en `presentation_studio_engine_unavailable` (409) avec la raison et la réparation ; **rien ne joue à sa place** (test : `test_without_the_runtime_nothing_plays_and_nothing_falls_back_to_html` : 409 typé, aucun objet `studio-*` sur la scène, état `idle`, journal `engine_refused`). Le contrôle scène/moteur est `require_native` : seule une source **`native`** pour le moteur de la Presentation est utilisable ; `adapter` est déclaré, pas utilisable (aucune étape d'adaptation visible n'existe) et `unsupported` est refusé de même, en `engine_unsupported`. Il s'applique à l'ajout et à la modification d'une scène (`_check_scenes`), au démarrage pour **toutes** les scènes stockées (et variantes locales), et à chaque chemin qui met un bloc sur l'étage (scène montrée, bloc de détour, aperçu de variante ; le rechargement à chaud passe par `check_scenes`) : voir `presentation-engine.md`.

**La porte est fermée par défaut** : un Core construit sans la composition Remotion a quand même la porte et rapporte « aucun adaptateur Remotion » ; le contourner est un choix explicite (`engine_gate=False`, fait par `tests/conftest.py` pour les mondes de test historiques). Un réglage `JARVIS_REMOTION_SANDBOX_*` invalide n'arrête pas Core : le moteur est indisponible, avec la raison, de façon typée et visible.

### 10.6 Son, autoplay, plein écran

- **Autoplay** : le navigateur ne reprend un `AudioContext` que sur un geste de l'utilisateur DANS le cadre ; le cadre n'a pas `allow="autoplay"` (`IFRAME_ATTRIBUTES` inchangé). Le Player démarre donc **muet** (`initiallyMuted`) : les images avancent toujours (sans cela la lecture reste à l'image 0 en attendant un contexte audio qui ne vient pas : défaut mesuré dans Chrome 154). Un vrai clic ou une vraie touche (`isTrusted`) dans la scène active le son ; un message de l'hôte ne le peut pas (un `postMessage` n'est pas un geste). `pong.muted` (champ optionnel, booléen) le dit à la page, qui affiche « Son coupé · cliquez la scène pour l'activer » puis « Son actif ». Une scène sans audio n'est pas concernée.
- **Plein écran** : inchangé (`control_center_fullscreen.js`) : l'élément hôte de la fenêtre de stage entre en plein écran sur un geste ; la page de scène et le bac à sable le remplissent (mesuré : 1280x720 = écran) ; la barre de lecture se masque au repos. Échap physique : vérification humaine (OPERATIONS.md). Aucun plein écran n'est annoncé par la voix seule.
- **Commandes** : `play` est envoyé à l'ouverture ; `play`/`pause`/`seek` et la durée sont lisibles dans la barre de la page de scène (position interpolée entre deux `pong`) ; `JarvisPrefabHost.control(objectId, action, frame)` et `.cue(objectId, name, frame)` les offrent à la partition (Slices 12 et 13).

### 10.7 Tests et preuves

`tests/unit/test_remotion_player.py` (disponibilité, descripteur, porte, compatibilité), `test_remotion_sandbox_server.py` (écouteur réel sur `127.77.0.2` : paresseux, en-têtes, Host, port occupé), `test_remotion_player_routes.py`, `test_remotion_relay.py` (en-tête exact `frame-src`, gardes, journal), `test_remotion_stage_js.py` (node : `tick()`, jeton, cadre figé retiré, délai, échecs typés, délégation de l'hôte), `test_remotion_app_wiring.py` (composition de production), `test_remotion_player_docs.py` (ce chapitre contre le code) ; opt-in avec une installation existante (`JARVIS_REMOTION_RUNTIME_DIR`) : `test_remotion_player_realpage_browser.py` (Chrome réel, Core isolé). Preuve : `scripts/remotion_player_harness.py` -> `tasks/jarvis-remotion-presentation-integration/slices/10-remotion-player-host/evidence/real-player.json` et captures.

### 10.8 Risques résiduels de la Slice 10

- **`Access-Control-Allow-Origin: *`** des scripts et polices de l'origine dédiée (requis par `integrity` et `@font-face` depuis un document d'origine opaque) : inchangé, clés de 128 bits de contenu, fichiers non secrets ; toute page web qui connaîtrait une clé peut les lire.
- **Discipline des props** : tout ce que la page de scène donne au cadre (`inputProps`, assets) est lisible par le code de la scène et peut sortir par les canaux ouverts du § 9 (`dns-prefetch`, `preconnect`, WebRTC au mieux). Seul le contenu de la diapositive y passe ; jetons et secrets n'y passent jamais. Depuis la Slice 13, le bloc `data` du manifeste y passe aussi, sous la clé réservée `data`, après la même validation que `props` ([§ 12](#12-slice-13--variables-typées-et-inputprops-validées)) : c'est du contenu de diapositive, pas un état de Jarvis.
- **Origine du Control Center exacte** : `frame-ancestors` et le `targetOrigin` du cadre sont `http://127.0.0.1:<JARVIS_UI_PORT>` ; une page ouverte par `localhost` ne peut pas encadrer le bac à sable (échec visible : « ne s'est pas lancée dans les 10 s »).
- **Fenêtre de stage petite par défaut** (comme toute fenêtre) : la scène s'y affiche avec bandes noires ; le plein écran est la vue de présentation.
- **Chrome 154 seul exercé** (Windows 11) ; audio réel (haut-parleurs, scène avec piste sonore) jamais écouté ici ; Échap physique et plusieurs écrans : humain.
- **Charge** : un cadre Remotion vivant est un processus de rendu ; le plafond de 24 cadres vivants du prefab host s'applique (les plus anciens passent en pause).

## 11. Slice 12 : la ligne de temps de la partition (seek, lecture, pause, position)

Handoff `jarvis-remotion-presentation-integration`, Slice 12. Le contrat côté partition (ancres, segments, ce que Core décrit) est dans [presentation-studio.md](presentation-studio.md) › *Remotion timeline bridge* ; ce chapitre est le côté bac à sable et navigateur. Ajouts **seulement additifs** au protocole `rs: 1` et `rsh: 1` ; tout ce qui existait garde sa forme.

### 11.1 Messages ajoutés

| Sens | Message | Règle |
| --- | --- | --- |
| hôte -> cadre | `control {action, frame?, until?}` | `seek` exige `frame` (inchangé) ; `play` et `pause` peuvent porter `frame` (aller à cette image, puis jouer ou tenir) ; `play` peut porter `until` : le lecteur s'arrête **de lui-même sur cette image** (>= `frame`), `pause` et `seek` n'en portent pas (refus `bad_until`). Entiers 0..108 000. |
| cadre -> hôte | `clock {frame, playing}` | position du lecteur : `frame` entier 0..108 000, `playing` booléen, rien d'autre (`extra_field`). Envoyé au plus toutes les 250 ms pendant la lecture et à chaque `play` / `pause` / `seeked` / `ended` (au plus un par 100 ms si rien n'a changé). Plafond côté hôte : `maxClocksPerSecond` = 12 ; au-delà le rapport est jeté et compté (`clockDropped`), **sans infraction** (un lecteur bavard n'est pas un cadre hostile) ; un rapport malformé est une infraction (`bad_clock`, comptée par `maxViolations`). |
| page de la scène -> fenêtre | `clock {frame, playing, duration, fps}` (`rsh: 1`) | la position bornée à `0..durée-1` par la page, au plus 4 par seconde, sauf changement d'état (lecture <-> pause, toujours dit). Même contrôle de source (`contentWindow` du cadre) et d'origine que `status`, champs exacts (`parseClock`). |
| fenêtre -> page | `control {action, frame?, until?}` | même forme ; la page borne `frame` et `until` à la composition et n'envoie `until` que pour `play`. |

### 11.2 Ce que fait le cadre (`remotion_sandbox_child.js`)

`seek` oublie toute image d'arrêt ; `pause` aussi. `play` avec `until` pose l'image d'arrêt : sur l'événement `frameupdate` du Player, dès que l'image atteint `until`, le cadre fait `pause()` puis `seekTo(until)` (le lecteur tient exactement sur `until`, jamais une image au-delà) et rapporte la position. Un `play` dont l'image d'arrêt est déjà atteinte ne lit pas : il se place sur `until` et reste en pause. Un ordre reçu avant que le Player existe est gardé avec son image d'arrêt (comme `seek` / `play` l'étaient). Le lecteur rapporte sa position par `clock` ; `pong` garde `frame` (le chien de garde).

### 11.3 Ce que fait la page de la scène et la fenêtre

La page de la scène (`control_center_remotion_stage.js`) borne la position du `clock` à la composition, la garde (la barre de lecture l'affiche) et la relaie à la fenêtre (4 par seconde). L'hôte des cadres (`control_center_prefab_host.js`) garde la dernière position par fenêtre (`clock(objectId)` : `{frame, playing, duration, fps, at}`) et efface la position à chaque ordre (l'ancienne ne décrit plus le lecteur). `control(objectId, action, frame, until)` valide les entiers avant d'écrire. Le suiveur de la ligne de temps (`JarvisRemotionFrame.createTimelineFollower`, un par page de scène, `control_center_scene_page.js`) applique la vue de Core ; il est pur et testé sous node.

### 11.4 Autorité et menace

La position est un **conseil d'un code non fiable** : elle n'arrive jamais à Core, ne sert qu'à décider d'un rattrapage borné DANS le segment de la scène (une par seconde, cinq par segment, puis abandon dit une fois), et un rapport faux (image hors composition, type faux, clé en plus, expéditeur étranger, origine étrangère) est refusé et compté sans effet. Mesuré dans Chrome : une scène qui poste `clock {frame: 99999999}` ou `{frame: -3}` à son hôte est refusée par le chien de garde (`refused.bad_clock`), le lecteur ne bouge pas, le cadre n'est pas retiré (deux infractions sur vingt). La scène ne déclenche aucune cue, aucune parole, aucun outil : seule la partition de Core décide (`presentation-studio.md`).

### 11.5 Tests et preuves

`test_remotion_sandbox_protocol_js.py` (formes, plafond de `clock`), `test_remotion_sandbox_child_js.py` (le vrai script du cadre contre un faux Player), `test_remotion_timeline_js.py` (suiveur, dérive, rapports falsifiés ou périmés, relais de la page), `test_remotion_timeline_realpage_browser.py` (Chrome réel, Core isolé : segment d'entrée, ancre révélée, cue, pause, reprise, retour, faux rapport ; preuve `tasks/jarvis-remotion-presentation-integration/slices/12-score-to-remotion-runtime/evidence/real-timeline.json`).

### 11.6 Risques résiduels de la Slice 12

- **La position est une déclaration du cadre** : une scène hostile peut mentir (elle ne gagne que de provoquer, au plus cinq fois par segment, un `seek` de SON lecteur à une image de SON segment).
- **Latence** : la vue de Core est lue toutes les 500 ms pendant une ligne de temps ; le début d'un segment peut paraître jusqu'à ~0,5 s après la révélation. Pas de synchronisation à l'image près avec l'audio.
- **`frameupdate` du Player** est la source de l'arrêt : un navigateur qui étrangle l'onglet (arrière-plan) peut dépasser `until` d'une ou deux images avant que `seekTo(until)` ne remette le lecteur sur l'image d'arrêt.
- Chrome 154 seul exercé (Windows 11) ; audio réel jamais écouté.

## 12. Slice 13 : variables typées et `inputProps` validées

**Statut : contrat (Level 2) et implémentation (Level 3) livrés ; éprouvé dans un vrai Chrome sur un Core isolé** ([preuve](#126-tests-et-preuves)). Contrat produit : [presentation-studio.md](presentation-studio.md) > *Typed variables and fast edits*. Rien ici n'ajoute d'éditeur, de route ni de type de contrôle : la modification durable reste `control.set` / `control.reset` (CAS), le Player ne reçoit que des valeurs.

### 12.1 Ce qui traverse, et seulement après validation

`inputProps` = `props` du manifeste (défauts complétés) + `data` du manifeste sous la clé réservée `data` (seulement si le manifeste déclare des `data`). Elles sont **construites et validées avant d'être postées** au bac à sable, deux fois : par Core au moment de décrire la scène (`defaults` et `input_contract` du descripteur de lecture, `jarvis/domain/remotion_controls.py::build_input_props`) et par la **page de scène** (`jarvis/runtime/control_center_remotion_props.js`, chargé avec le protocole) à chaque `init` et à chaque message `props`. Le bac à sable garde en plus ses propres bornes (§ 5) : trois portes, la plus proche du code non fiable en dernier.

Ce que la validation refuse (jamais « réparé » en silence) : type du manifeste (chaîne, texte, couleur `#rrggbb`, énumération, entier, nombre, booléen, liste, objet), bornes (`min`, `max`, `max_length`, `max_items`, motif), clé inconnue, champ requis absent sans défaut, **fonction, symbole, `undefined`, `BigInt`, nombre non fini, objet qui n'est pas simple** (prototype autre que `Object.prototype` ou `null`, accesseur, trou de tableau, `Date`, `Map`, classe), nom `__proto__` / `constructor` / `prototype` à toute profondeur, un entier hors ±(2^53 − 1) (JavaScript ne le lit pas exactement ; `2.0` vaut `2`), une chaîne ou une clé avec un demi-substitut Unicode isolé, un nombre qui dépasse le flottant. Puis **le même calcul de budget que le bac à sable** (`jsonBudget`, § 5 : null 4, booléen 5, nombre 8, chaîne en unités UTF-16 + 2, clé + 3 ; 8 niveaux, 2 000 valeurs, 64 Kio) sur l'objet **fusionné** `props` + `data` que le bac à sable recevra (la page appelle la fonction du protocole, Core en porte un calque `sandbox_budget`, testé contre elle) : ce que la page accepte, le bac à sable l'accepte. Un refus **n'envoie rien** : la scène garde ses dernières valeurs valides, la page compte le refus (`state().propsRefused`, `lastProblems`), le dit à la fenêtre par un **avis transitoire** (`status {phase: 'notice'}`, jamais `scene_error` ni `failed` : pas de bande rouge, pas de rapport d'échec à Core ; la fenêtre l'affiche en ambre et l'efface à l'avis vide que la page envoie dès que des valeurs sont acceptées), le journalise (`remotion.stage.props_rejected`, nombre de défauts, **jamais une valeur** : les messages disent le chemin et la règle) et la scène continue. Le `data` que le contrat ne porte pas (`carries_data` faux) est **ignoré et dit** (`dropped`), jamais validé. Sans `input_contract` dans le descripteur, la page ne monte pas la scène (fermé par défaut : échec visible `props_refused`).

### 12.2 Le contrat d'`inputProps` et ce qu'un moteur ne porte pas

`input_contract = {engine, props, data, withheld, carries_data}` : les schémas du manifeste **moins** les paramètres que le moteur ne porte pas, et la liste explicite `withheld [{path, reason}]`. Règles fermées (`unsupported_reason`), toutes dites, aucune cachée :

| Moteur | Paramètre | Pourquoi |
| --- | --- | --- |
| Remotion | type `url` | le bac à sable n'a aucun réseau (`connect-src 'none'`) ; une image se livre dans la source et se lit par `staticFile` |
| Remotion | propriété nommée `data` dans `inputs.props` | la clé `data` des `inputProps` est réservée au bloc `data` du manifeste ; `carries_data` devient faux |
| Remotion | liste dont les éléments contiennent un tel paramètre | on ne porte pas la moitié d'une liste : la liste entière est retirée |
| Slidecar | (aucun) | |

Un objet ou une liste qui **contient** un paramètre non porté n'est pas porté non plus (`props.card` dont `image` est une `url` ; `props.cards`) : son contrôle est étiqueté non pris en charge avec le chemin fautif, et `control.set` est refusé, au lieu de stocker une valeur dont une partie serait perdue. Un paramètre retiré reste **déclaré** : son contrôle existe, l'inspecteur le montre grisé et inerte avec la raison de Core, `describe_control` rend `support: {status: "unsupported", reason}`, `control.set` sur lui est refusé (`presentation_studio_value_refused`, « not supported by the remotion engine: ... ») au lieu de réussir sans effet visible ; `control.reset` reste possible (retirer une valeur ignorée est inoffensif). Une valeur déjà stockée pour un chemin retiré est ignorée à la construction et dite (`dropped`). Déclarer des étiquettes par paramètre dans le manifeste exigerait une version 4 du manifeste : non fait (§ 12.7) ; ces règles sont dérivées du type, jamais devinées.

### 12.3 Messages ajoutés (additifs)

- fenêtre de scène vers page de scène : `props {props, data?}` (`data` est un champ **optionnel** de plus ; `control_center_prefab_host.js` l'envoie, `control_center_remotion_frame.js` l'autorise, la page le valide). Aucun autre type de message n'est ajouté ; vers le bac à sable, `init` et `props` portent toujours des `inputProps`, rien d'autre.
- page de scène vers fenêtre : `status {phase: 'notice', message}` (message vide = avis effacé) ; `control_center_prefab_host.js` l'affiche (`.sc-prefab-warning`) sans `fail()` ni `onOutcome`.
- `POST /api/remotion/report` : l'événement `props_rejected` (champ `diagnostics` = nombre de défauts), niveau `warning`, dans **son propre seau** (10 par minute) : une rafale de refus ne prend pas la place d'un rapport `killed` ou `failed` (60 par minute).
- descripteur de lecture (la route `/v1/remotion/player/...` existante) : `input_contract` ; `defaults` = les `inputProps` sans valeur de scène.

### 12.4 Aperçu contre état canonique, sans rendu

Trois états, un seul chemin d'écriture :

1. **Aperçu** : l'inspecteur montre la valeur dans un cadre de prefab en mode `preview` de l'hôte (mêmes validations de la page de scène) ; `mode: preview` côté Core calcule le résultat **sans rien écrire** (`edit`, `render_overlay`). Une valeur d'aperçu n'est jamais enregistrée tant qu'un `commit` ne la valide pas.
2. **Enregistrement** : `control.set` / `control.reset` en `mode: commit` avec la révision de base (`basis.variant_revision`) et la valeur attendue (`if_current`) : base périmée, `stale` ; valeur périmée, refus « no longer what the edit expected » ; rien n'est appliqué. L'écriture met à jour le **modèle source** (la variante) ; le Player suit par `props` (au plus un message par 16 ms, la dernière valeur gagne).
3. **Réinitialisation** (↺ de l'inspecteur) : `control.reset` ; le défaut curé du contrôle s'écrit explicitement, sinon la clé est retirée et le défaut du manifeste s'applique. L'inverse est enregistré (annulable).

La voix (acteur `brain`, outils MCP) et l'interface (acteur `user`) envoient la **même opération** ; il n'existe aucun chemin d'export, de rendu MP4 ni de recompilation sur une édition simple : le même document du bac à sable reste monté (mesuré, § 12.6).

### 12.5 Genre d'un contrôle

`describe_control` rend `kind` : `color`, `text`, `spacing`, `timing`, `motion`, `data` ou `value`, lu du type du manifeste, de la racine (`data.*` donne `data`), du groupe curé et du nom (`duration`, `delay`, `stagger`, `fade`... donnent `timing` ; `margin`, `gap`, `padding`, `radius`... ou le groupe `layout` donnent `spacing` ; le groupe `motion` donne `motion`). C'est une lecture : rien n'est stocké, les contrôles existants ne changent pas. La liste des contrôles d'une scène Remotion et celle d'une scène Slidecar ont la même forme (parité testée) ; seuls `engine` et `support` diffèrent.

### 12.6 Tests et preuves

`tests/unit/test_remotion_input_props.py` (tableau de cas commun `tests/fixtures/remotion_input_props_cases.json` joué par Python et par JavaScript, plus les valeurs que seul JavaScript peut porter), `test_remotion_controls.py` (genre, contrat, parité Slidecar/Remotion, vrai `PrefabService` : couleur, espacement, stagger, données, aperçu qui n'écrit rien, hors bornes, prototype piégé, paramètre non porté, CAS de base et de valeur, réinitialisation), `test_remotion_stage_js.py` (mise à jour couleur/espacement/stagger/données, valeurs piégées jamais envoyées, `data` jamais sans contrat, pas de contrat = rien), inspecteur (`test_presentation_studio_inspector_behaviour_js.py` : contrôle non porté grisé et inerte), `test_remotion_relay.py`, `test_remotion_controls_docs.py`, et l'épreuve réelle opt-in `test_remotion_controls_realpage_browser.py`. Preuve réelle : `tasks/jarvis-remotion-presentation-integration/slices/13-remotion-controls-bridge/evidence/` (`real-slice-13.json`, `typed_controls.json`, captures), produite par `scripts/remotion_player_harness.py --slice 13 --test tests/unit/test_remotion_controls_realpage_browser.py`.

### 12.7 Risques résiduels de la Slice 13

- **Étiquettes par paramètre** : les règles « non pris en charge » sont dérivées (type `url`, clé `data`) ; un auteur ne peut pas marquer un paramètre « Slidecar seulement » dans le manifeste (une version 4 est à écrire si le besoin se confirme).
- **La page de scène recopie le validateur de Core** en JavaScript (même contrat, même tableau de cas testé des deux côtés) : une divergence future est attrapée par le test de parité, pas par le type.
- **Messages d'erreur** : la page ne rend pas les mêmes phrases que Core (seules les décisions sont comparées) ; elle ne journalise ni n'affiche jamais une valeur (chemin et règle seulement).
- **Ce que le cerveau voit** : `kind`, `engine` et `support` sont dans les lignes d'introspection des contrôles (`describe_control`), pas dans ce que les outils MCP de voix rendent aujourd'hui ; le cerveau n'apprend qu'un paramètre n'est pas porté par le refus de `control.set` (« not supported by the remotion engine »).
- **`data` sort désormais vers la scène** (clé `data`) : c'est du contenu de diapositive, borné par le même schéma ; les canaux résiduels du § 9 s'appliquent comme aux `props`.
- **Édition pendant une lecture** : `playback/edit` met la lecture en pause avant de valider (comportement existant de la Slice 12) ; une édition de contrôle par `variants/{id}/edits` ne la touche pas.
- Les événements d'état et de notification d'une scène Remotion (`events`) restent refusés par le manifeste v2 : le pont est **entrant** (valeurs vers le Player), jamais sortant.

## 13. Slice 14 : édition de source, compilation avant publication, erreur de rendu

Contrat de l'édition : [presentation-studio.md](presentation-studio.md) > *Hot reload contract* > *Remotion sources*. Ce qui touche l'isolation :

- **Rien de nouveau n'exécute le code d'une scène hors du bac à sable.** Le garde de compilation (`RemotionBuildGate`) ne fait que **compiler** (esbuild
  dans le processus géré de la capacité, fichiers virtuels, imports « nus » limités à `SCENE_ALLOWED_IMPORTS`, § 5 de `remotion-source.md`) une source
  que `validate_candidate` a déjà passée aux `SOURCE_GUARDS` (§ 3) ; il ne l'exécute pas. Une édition d'agent ne gagne donc aucun privilège : mêmes
  gardes que la publication, mêmes bornes, même cache. Testé de bout en bout avec le vrai compilateur : syntaxe, `import "fs"` utilisé (refusé par le
  compilateur, `compile_import_refused`), export par défaut manquant, `window.fetch` (refusé par la garde `realm_access` avant toute compilation).
- **Les diagnostics ne sortent que ce que le compilateur sait de la source** : `file` est un chemin de la source, jamais du poste (test : ni `:\` ni
  `node_modules` dans le message) ; le journal `reload_build_refused` porte le code et un compte, jamais un texte de source.
- **Frontière d'erreur autour du composant de la scène** (`guarded` dans `remotion_sandbox_child.js`) : le `Player` de Remotion n'a pas de propriété
  `onError`, l'erreur d'un composant passe par l'émetteur du lecteur avant que la référence existe. L'amorce enveloppe donc le composant dans une classe
  `Boundary` (identité stable : un changement de propriétés ne remonte pas la scène) dont `componentDidCatch` dit `error` à l'hôte par le canal déjà
  borné (`report`, au plus `maxReportsPerSecond`), et rend `null`. Aucun nouveau type de message.
- **Prouvé de montage** (`control_center_prefab_host.js`) : pour une scène Remotion, `ready` de la page de scène veut dire « bac à sable chargé », plus
  « monté ». L'hôte attend le premier `clock` du lecteur (posé après le premier rendu validé ; l'erreur de rendu, elle, arrive avant) puis `SETTLE_MS` ;
  sans premier `clock` dans `RENDER_PROOF_MS` (10 s) la scène échoue (`timeout`, « did not render a first frame »). Pour un cadre « staged » (échange à
  chaud), l'échec laisse l'ancien cadre à l'écran et Core ramène le pin (`presentation_studio_mount_failed`). Défaut trouvé par l'épreuve réelle : avant
  cela, une scène qui compilait mais levait au rendu était rapportée « montée » et remplaçait la bonne.
- **Risques résiduels** : une erreur après la première image reste une erreur de la scène vivante (bande « Recharger la scène »), pas un retour arrière ; pas
  de contrôle de types ; une scène qui boucle sans lever est rattrapée par le chien de garde du § 10, pas par l'édition.
