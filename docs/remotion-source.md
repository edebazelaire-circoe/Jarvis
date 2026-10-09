# Source d'une scène Remotion : stockage, disposition des modules, compilation

Handoff `jarvis-remotion-presentation-integration`, Slice 05. **Statut : décision (§1), contrat (Level 2) et implémentation (Level 3) vérifiés, compilation réelle prouvée sur Windows 11 avec Node et esbuild du verrou, Player rendu dans Chrome** ([preuve](#9-preuves)). Ce que ce document ne fait pas : isoler le code d'une scène à l'exécution (Slice 06), servir le Player (Slice 10), éditer à chaud (Slice 14), cataloguer (Slice 17).

Termes : une **scène Remotion** est une scène du Studio ([presentation-studio.md](presentation-studio.md)) dont le pin `(prefab_id, version)` désigne une **source Remotion** ; le moteur est un attribut du document ([presentation-engine.md](presentation-engine.md)). L'environnement Node/Remotion est celui de la capacité locale ([remotion-runtime.md](remotion-runtime.md)).

## 1. Décision : un nouveau genre de version dans la bibliothèque de prefabs versionnée

**Retenu : la source d'une scène Remotion est une version de la bibliothèque de prefabs existante** (`<racine de données>/prefabs/<id>/<version>/`), pas un arbre séparé `<racine>/remotion/`. Recommandation du PM reprise après vérification dans le code, pas dans la documentation :

| Besoin | Ce qui existe déjà, sans rien savoir de l'HTML | Preuve |
| --- | --- | --- |
| Scène = pin exact `(id, version)` | `StudioScene.prefab: PrefabRef` ; `held_pins()` | `jarvis/domain/presentation_studio_scene.py` (`StudioScene`, `held_pins`) |
| Versions immuables, numéro attribué par Core, publication atomique | `PrefabService.save/_publish` + `FilePrefabLibrary.publish` (dossier de préparation puis un renommage) | `jarvis/core/prefab_service.py` (`save`, `_publish`), `jarvis/adapters/file_prefab_library.py` |
| Ce qu'un document épingle ne disparaît jamais ; ce que rien n'épingle est archivé, jamais détruit | `StudioPinRegistry` (variantes, `last_valid_pin`, scène vivante, retenues en vol, pile d'annulation) + rétention `presentation-studio.*` | `jarvis/core/presentation_studio_pins.py`, `jarvis/core/prefab_retention.py`, `RETENTION_NAMESPACE` dans `jarvis/domain/prefab.py` |
| Retour arrière après un rechargement à chaud raté, reprise après arrêt brutal | `last_valid_pin`, `PresentationStudioReloadService.recover`, `plan_carry_over` (valeurs, contrôles et ancres reportés **par nom**) | `jarvis/core/presentation_studio_reload.py`, `jarvis/domain/presentation_studio_reload.py` |
| Variantes de scène, variantes locales, modèles | pins d'un même `(id, version)` | `SceneVariantSet`, `StudioScene.scene_variants` |
| Paramètres éditables déclarés, valeurs validées par Core | `inputs.props` / `inputs.data`, `validate_instance`, `StudioControl`, `ScoreAnchor` | `jarvis/domain/prefab.py`, `PrefabService.validate_instance` |
| Détection d'altération | empreinte recalculée à chaque lecture, version `tampered` refusée | `PrefabService._load` |

Un arbre séparé aurait obligé à refaire chacune de ces six lignes (et à les garder synchrones avec le premier arbre, car une présentation mêle encore des scènes HTML hérités). Le coût du réemploi est **fermé et local** : la forme d'une version (quatre fichiers fixes, clé `files`) ; rien d'autre ne dépend de l'HTML. Ce coût est payé ici : manifeste v2 (§4), fichiers `src/**` et `public/**` (§3).

Conséquences non négociables :

- **Aucune table SQLite n'est touchée** : les migrations de `CLAUDE.md` (`_MIGRATIONS`, instantané `tests/schema/*.sql`) ne s'appliquent pas. Le seul « schéma » qui change est celui du manifeste de prefab, versionné (§4).
- **Un seul arbre de dépendances** : celui de la capacité Remotion (`runtime/node_modules`). Une source n'a ni `package.json` ni `node_modules` ; elle est refusée si elle en porte un (§2).
- Les sources `Remotion` d'un Studio portent l'id `presentation-studio.p<12 hex>.s<12 hex>` (`source_prefab_id`) : elles entrent donc dans la **rétention** existante. La route `POST /v1/prefabs` refuse déjà cet espace de noms aux autres portes (`jarvis/protocol/prefab_routes.py`) : seul le Studio publie ces ids, directement par `PrefabService.save`.

## 2. Disposition d'une source

```
src/Scene.tsx            point d'entrée : export default <composant React> (propriétés = inputs.props)
src/**/*.{ts,tsx,js,jsx,json}   modules de CETTE scène (imports relatifs seulement)
public/**/*.{png,jpg,jpeg,webp,gif,svg,woff2,woff,ttf,otf,mp3,wav,ogg,mp4,webm}   assets de cette scène, lus par staticFile("nom")
```

Jamais : `node_modules`, `package.json`, `package-lock.json`, `tsconfig.json`, `remotion.config.*`, fichier caché, CSS importé (le style se fait en ligne ou en objets JS). Les dépendances sont celles de l'arbre partagé, **limitées** aux imports « nus » `react`, `react/jsx-runtime`, `react/jsx-dev-runtime`, `remotion` (`SCENE_ALLOWED_IMPORTS`, §5) ; l'accès aux assets passe par `staticFile`.

**Chemins** (`source_path_problem`, lexical, identique sur tous les postes, sans lire le disque) : relatif, POSIX (`/`), ASCII `[A-Za-z0-9._-]`, ≤ 120 caractères, segments ≤ 64, profondeur ≤ 8 ; pas de `..`, `.`, segment vide, antislash, `:` (lettre de lecteur), `/` initial, octet NUL, segment commençant ou finissant par un point, nom d'appareil Windows (`CON`, `NUL`, `COM1`...), extension hors liste (en minuscules). Deux chemins qui ne diffèrent que par la casse, ou un fichier qui est aussi un dossier, sont refusés. **L'identité d'un fichier est son chemin dans SA scène** : `src/lib/Title.tsx` de deux scènes sont deux fichiers distincts (deux versions de prefab, deux dossiers).

**Bornes** : 64 modules (256 Kio chacun, 1 Mio au total), 64 assets (4 Mio chacun, 16 Mio au total), UTF-8 sans NUL pour un module. Les routes `POST /v1/prefabs` et `POST /v1/prefabs/validate` plafonnent le corps à 512 Kio (`MAX_DEFINITION_BODY_BYTES`) : les assets volumineux ne passent pas par une route de candidat, mais par la publication interne du Studio.

**Empreintes** : SHA-256 de chaque fichier ; `source_digest` = SHA-256 du JSON canonique `{chemin: sha256}` : indépendant de l'ordre, de l'id et du numéro de version du prefab. C'est la clé de contenu de la compilation (§5). L'empreinte de **version** (celle de `publication.json`) couvre en plus le manifeste.

**Mémoire du catalogue** : `PrefabService` ne garde, pour une version Remotion, **aucun octet de contenu** : le manifeste analysé et un inventaire `{chemin: (taille, sha256)}` (`PrefabBundle.inventory`, `sources` vide). Les octets sont relus **à la demande** (`PrefabService.remotion_source`, donc la compilation) et comparés aux SHA-256 de l'inventaire : une version modifiée depuis le balayage est `tampered`. Les gardes de `SOURCE_GUARDS` s'exécutent à la publication et à cette relecture (pas au balayage du catalogue).

**Fichiers inattendus** : une version dont `src/` ou `public/` contient un fichier non déclaré par le manifeste, ou dont un fichier déclaré manque, est `tampered`. Un lien, une jonction ou un sous-dossier remplaçant un fichier est refusé (mêmes défenses que le reste de la bibliothèque).

**Crochet de la Slice 06** : `jarvis.domain.remotion_source.SOURCE_GUARDS` (tuple de fonctions `(RemotionSource) -> messages`), appelé à la publication **et** chaque fois que les octets d'une version sont relus (`PrefabService.remotion_source`, donc avant toute compilation). Vide ici ; la Slice 06 y met ses gardes (imports interdits, API navigateur interdites...), qui s'appliquent alors à toute source, déjà publiée comprise : une garde nouvelle refuse une version ancienne en `invalid_definition` à la relecture, sans la réécrire.

## 3. Stockage, versions, épinglage, retour arrière

```
<racine de données>/prefabs/presentation-studio.p0000000000a1.s0000000000b1/1/
    manifest.json        schema_version 2, bloc "source" (§4)
    publication.json     empreinte, date, provenance (écrit par Core, inchangé)
    src/Scene.tsx  src/lib/Title.tsx  src/theme.json
    public/dot.png
```

- **Une version publiée n'est jamais réécrite.** Un changement est une **nouvelle version** (`revision`, numéro attribué par Core) ; les anciennes restent octet pour octet (testé : `test_versions_are_immutable_and_a_revision_is_a_new_version`).
- **Publication atomique** : tous les fichiers (sous-dossiers compris) sont écrits dans `prefabs/.staging-<16 hex>/`, puis un seul renommage. Un arrêt brutal laisse un `.staging-*` retiré au démarrage (`core.prefab.swept`), jamais une version partielle, et ne consomme aucun numéro.
- **Redémarrage de Core** : un `PrefabService` neuf relit le catalogue, recalcule les empreintes ; la source revient identique (testé : octets, `source_digest`, empreinte). Aucun `node_modules` n'est copié : `forbidden_names_in_library == []` dans la preuve réelle.
- **Racine de données changée** : une autre racine est une autre bibliothèque (testé). Les worktrees et le bac à sable n'ont jamais la source du Jarvis vivant.
- **Épinglage et rétention** : inchangés. `StudioScene.held_pins()` donne le pin de la scène et de ses variantes locales ; `StudioPinRegistry` les protège ; la rétention archive un dossier **entier** (`src/**` et `public/**` compris) vers `prefabs/.archive/<id>/<version>/` en un renommage, son numéro n'est jamais réattribué (testé avec 33 versions et un pin).
- **Retour arrière** : le mécanisme à chaud existant (`last_valid_pin`, `recover`) ne manipule que des `PrefabRef` et le manifeste (`plan_carry_over`) ; il s'applique à une source Remotion sans changement. Ce qui reste HTML dans `PresentationStudioReloadService` (les fichiers `template/style/behavior` de `SourceEditRequest`, `compose_candidate`) est la matière de la Slice 14.
- **Identité de scène et partition inchangées** : `StudioScene.scene_id` (`pss_…`) et `ScoreAnchor.anchor_id` ne dépendent pas du moteur ; un contrôle désigne `props.<clé>` ou `data.<clé>` du manifeste, une ancre désigne un contrôle (testé sur un pin Remotion et sur une révision qui retire une clé).
- **Rien d'absolu dans un contexte de Board** : le résultat public de compilation n'a ni chemin disque ni port (§5) ; un chemin de fichier d'une source est toujours relatif à sa scène.

## 4. Manifeste de prefab : version 2

`jarvis.prefab` reste **une famille à clés fermées par version**. Règle (nouvelle, `MANIFEST_VERSIONS = (1, 2)`) : *un manifeste s'écrit à la plus basse version qui l'exprime ; une version ne retire jamais une clé de la précédente ; une version publiée n'est jamais réécrite.* Conséquences :

- Les prefabs HTML restent en **v1**, byte pour byte : leurs empreintes, `publication.json` et `catalog.lock.json` ne bougent pas (`test_html_bundles_keep_their_fingerprint_and_their_shape`, `test_prefab_base_lock`).
- Un lecteur d'avant la Slice 05 lit toujours tout l'HTML et **refuse** une v2 (`schema must be … version 1` : la version est `tampered`, tracée `core.prefab.tampered`, le catalogue continue). Ce comportement est figé dans `test_an_old_reader_refuses_a_remotion_version_and_still_reads_every_html_one`. Le balayage de bibliothèque d'un lecteur ancien ne plante donc pas sur un dossier v2.
- Un lecteur actuel lit v1 et v2.

Clés du manifeste v2 = clés v1 **moins `files`, plus `source`** (les autres, `inputs`, `sample`, `scene`, `family`, `tags`, `aliases`, restent identiques et servent donc les paramètres éditables, la recherche et l'aperçu). `events` doit être vide (les événements d'état/notification sont ceux des cadres HTML ; le pont de contrôles Remotion est la Slice 13).

```json
"source": {
  "format": "remotion",
  "engine": {"name": "remotion", "version": "4.0.534", "react_version": "19.3.0", "lock_sha256": "<sha256 du package-lock.json livré>"},
  "entry": "src/Scene.tsx",
  "composition": {"id": "Scene", "width": 1280, "height": 720, "fps": 30, "duration_in_frames": 90},
  "modules": ["src/Scene.tsx", "src/lib/Title.tsx", "src/theme.json"],
  "assets": ["public/dot.png"]
}
```

`modules` et `assets` sont **triés et sans doublon** (forme canonique, donc empreinte stable) ; `composition` est **déclarée**, jamais lue dans le code (le Player en a besoin avant d'exécuter quoi que ce soit) ; `engine` dit pour quel jeu de paquets la source a été écrite (§5, dérive). Candidat accepté par `parse_candidate`/`PrefabService.save` : `{manifest, sources: {chemin: texte}, assets: {chemin: base64}}` ; `jarvis.domain.remotion_source.build_candidate` le construit en forme canonique et `jarvis.adapters.remotion_compiler.shipped_engine_pin()` donne le bloc `engine` du jeu livré.

**Pas de migration** : aucune base SQLite, aucun document de présentation ne change (`Presentation.engine` existe depuis la Slice 02 ; une scène épingle un `PrefabRef` comme avant).

## 5. Contrat de compilation (TSX -> bundle navigateur pour le Player)

Le Player n'exécute pas du TSX. **Rien d'autre dans le plan ne compile** ; ce chapitre est ce que la Slice 10 consomme.

**Qui** : `jarvis.adapters.remotion_compiler.RemotionCompiler`. **Processus géré de la capacité Remotion** : un `node runtime-host.mjs --compile <requête.json>` par compilation, lancé par `NodeCapabilityRunner.run_script` (environnement en liste blanche, délai, arbre tué au dépassement, suivi par `cancel_all` à l'arrêt de Core). Le worker `--serve` de la Slice 04 n'est **pas** requis (il ne fait que `/health`) : la compilation exige la capacité **`ready` ou `running`**, sinon `compile_runtime_unavailable` avec la raison et la réparation (`POST /v1/local-capabilities/remotion/install|repair`).

**Quoi** : esbuild 0.28.1 (du verrou de la capacité, présent via `@remotion/bundler`), dans l'arbre partagé. Une scène est compilée dans un **système de fichiers virtuel** : les modules viennent de la requête (mémoire), les imports relatifs sont résolus parmi eux (extensions et `index.*` essayés ; `..` qui sort de la source est refusé), les imports « nus » sont limités à `SCENE_ALLOWED_IMPORTS` et résolus vers l'hôte, tout le reste est refusé (`fs`, `node:*`, URL, `/chemin`, paquet non installé, `@remotion/cli`...). La scène ne lit ni disque ni `node_modules`.

**Deux cibles, un seul React** :

| Cible | Fichier | Contenu | Clé de cache |
| --- | --- | --- | --- |
| `host` | `host.js` (≈ 570 Kio minifié) | IIFE qui pose `globalThis.__JARVIS_HOST__ = {react, react/jsx-runtime, react/jsx-dev-runtime, react-dom, react-dom/client, remotion, @remotion/player}` | arbre installé (versions + empreinte du verrou) + identité du compilateur |
| `scene` | `scene.js` (quelques Kio) | IIFE `var JarvisScene = {component}` ; les imports autorisés sont des lectures de `__JARVIS_HOST__` (jamais embarqués) | contenu de la source + point d'entrée + arbre installé + **identité du compilateur** + liste d'imports + minification |

Côté page du Player (Slice 10) : charger `host.js`, puis `scene.js`, fixer `window.remotion_staticBase` à un **chemin absolu de l'origine qui sert la page** (préfixe de `public/` : `staticFile("x")` rend `"/" + base + "/x"`, une URL complète y est cassée, vérifié sur 4.0.534), et monter `<Player component={JarvisScene.component} durationInFrames fps compositionWidth compositionHeight inputProps />` avec la composition du manifeste. Preuve réelle dans Chrome : §9.

**Où, quelle clé** : `<racine de données>/local_capabilities/remotion/compiled/<clé>/{scene.js | host.js, public/**, compile.json}`, clé = `scene-<32 hex>` ou `host-<32 hex>` (`scene_cache_key`, `host_cache_key`). « Arbre installé » = `InstalledEngine` : versions de Remotion et de React, SHA-256 du `package-lock.json` **et** SHA-256 du `runtime-host.mjs` installé (la logique de compilation : une mise à niveau du compilateur sur le même arbre npm ne réutilise jamais un bundle de l'ancien). Un test lie la liste `HOST_MODULES` du script à `HOST_EXPOSED_MODULES` côté Python. La clé est le **contenu** : deux versions de prefab au même contenu partagent une sortie ; un arbre réparé ou mis à jour (empreinte du verrou) ne réutilise jamais un ancien bundle ; une liste d'imports resserrée (Slice 06) change la clé. C'est un cache **dérivé** : le supprimer ne perd rien (la source fait foi), `uninstall` de la capacité ne le supprime pas (il est hors de `runtime/`) mais il n'est jamais utilisé tant que la capacité n'est pas prête.

**Écriture et relecture** : dossier temporaire `.tmp-<hex>` puis un renommage ; une seule compilation à la fois par clé (les autres attendent et relisent) ; une entrée relue est **vérifiée** (taille et SHA-256 de chaque fichier selon `compile.json`) sinon reconstruite ; élagage au plus récemment utilisé (`CACHE_KEEP_ENTRIES` = 64, `CACHE_MAX_BYTES` = 1 Gio, jamais l'entrée qui vient d'être écrite ; dossiers `.tmp-*` abandonnés depuis plus d'une heure retirés). `resolve_output_file(clé, chemin)` ne rend qu'un fichier déclaré par `compile.json` (clé bien formée, pas de `..`, pas de lien) : c'est la seule porte par laquelle Core servira ces fichiers. Le SHA-256 est vérifié au **premier service** d'un fichier, puis seulement quand sa taille ou sa date change (un `lstat` par service ensuite) : une édition à taille constante est vue (`compile_cache_io`, journal `remotion.compile.cache_error`) ; seule une édition qui restitue aussi la date y échappe (le SHA-256 de tout fichier est de toute façon revérifié à chaque relecture complète du cache), ce qui suppose un attaquant maître de la racine de données. Le cache est manipulé par chemins étendus sous Windows (un asset au nom de 120 caractères sur une racine longue dépasse 260), et un lien ou une jonction posé à `compiled/<clé>` est **retiré** (jamais sa cible) puis remplacé (`remotion.compile.cache_link_removed`).

**Délais** : scène 60 s (`SCENE_TIMEOUT_S`), host 120 s ; au dépassement l'arbre de processus est tué. Mesuré : host 0,8 s, scène 0,2 s, relecture du cache 0,01 s. **Tailles** : `scene.js` ≤ 4 Mio, `host.js` ≤ 8 Mio, sinon `compile_output_too_large`.

**Échecs typés** (`RemotionCompileError`, `code`, `message` d'une phrase sans chemin du poste, `diagnostics` ≤ 20 `{file, line, column, text}` où `file` est un chemin **de la source**) :

| Code | HTTP conseillé | Cause | Journal |
| --- | ---: | --- | --- |
| `compile_runtime_unavailable` | 409 | capacité non prête, enregistrement d'installation absent, Node introuvable | `error` |
| `compile_invalid_source` | 400 | source refusée avant tout processus (chemin d'asset non sûr) | `warning` |
| `compile_source_error` | 422 | erreur de syntaxe ou de type de l'utilisateur (fichier, ligne, colonne) | `warning` |
| `compile_import_refused` | 422 | import hors liste, hors de la source ou introuvable | `warning` |
| `compile_entry_invalid` | 422 | pas d'export par défaut | `warning` |
| `compile_timeout` | 504 | délai, arbre tué | `warning` |
| `compile_output_too_large` | 422 | bundle au-delà de la borne | `warning` |
| `compile_compiler_failed` | 500 | Node ou esbuild a échoué sans résultat exploitable (fin de sortie nettoyée : racines connues, puis tout chemin absolu restant, lecteur, UNC, chemin étendu ou POSIX, devient `<path>`) | `error` |
| `compile_cache_io` | 500 | cache illisible, non inscriptible, fichier non déclaré demandé ou contenu différent de `compile.json` (l'exception d'origine est chaînée ; le journal porte la clé, `errno` et un détail nettoyé) | `error` |

Le chemin normal est journalisé aussi (`remotion.compile.done`, `remotion.compile.reused`, `remotion.compile.pruned`), l'échec avec son code (`remotion.compile.failed`). Une erreur de l'utilisateur n'est jamais un `error` système. Ces codes sont **distincts** de `presentation_studio_engine_unavailable` (état du moteur) : la Slice 10 mappe `compile_runtime_unavailable` vers `engine_unavailable` à la frontière.

**Dérive d'arbre** : `CompiledArtifact.engine_pinned` (ce que la source déclare) et `engine_installed` (`install-record.json`) ; `engine_drift` vrai s'ils diffèrent. Le plan impose **un seul arbre** par poste : on compile avec l'arbre installé et on **signale**, on ne corrige jamais en silence. Mettre à jour un prefab pour le jeu courant est la Slice 19 (essai dans une nouvelle variante).

**Résultat public** (`CompiledArtifact.to_public()`) : `{contract, target, cache_key, entry_file, files[{path, bytes, sha256}], source_digest, engine_installed, engine_pinned, engine_drift, reused, duration_ms, warnings}`. Aucun chemin absolu, aucun port, testé : c'est la seule forme à mettre dans un contexte de Board ou une réponse HTTP.

**Modification de la capacité (Slice 04)** : `runtime-host.mjs` gagne `--compile` et la sonde charge aussi `esbuild`. Le fichier livré change donc : un environnement installé avant cette Slice affiche `shipped_files_changed` et se met à niveau par `repair` (≈ 19 s, réseau non requis grâce au cache npm du `runtime/`). Deux défauts de la Slice 04 relevés par l'épreuve réelle sont corrigés : `uninstall` échouait sur Windows (« répertoire non vide ») quand la racine de données dépasse ~85 caractères, parce que le cache de npm range des fichiers à nom de 124 caractères au-delà de 260 caractères de chemin : `_remove_tree` utilise maintenant les chemins étendus et réessaie un dossier « en attente de suppression ».

## 6. Ce qui n'est pas ici

- Exécuter le code d'une scène dans un contexte sans privilège (iframe isolée, pas de réseau, quotas) : **Slice 06**. Un `scene.js` s'exécute dans la page qui le charge ; tant que la Slice 06 n'a pas livré le bac à sable, ne le charger que dans une page à origine dédiée sans jeton.
- Servir `host.js`/`scene.js`/`public/**` par une route de Core, `engine_unavailable` à la lecture : **Slice 10**.
- Rechargement à chaud et édition par fichiers : **Slice 14**. Rendu MP4/still/PDF (qui a besoin d'un `serveUrl` du bundler de Remotion, pas du bundle du Player) : **Slice 16**.

## 7. Contract for Slice 06 (isolation)

1. Poser vos gardes dans `SOURCE_GUARDS` (publication et relecture) ; elles reçoivent `RemotionSource` (`block`, `files` en octets, `module_texts()`, `digest`). Une garde nouvelle fait refuser des versions déjà publiées au rechargement du catalogue : décider si c'est `tampered` (refus dur) ou une classe « à migrer » ; ne **pas** réécrire une version publiée.
2. La liste d'imports du compilateur est `SCENE_ALLOWED_IMPORTS` / paramètre `allowed_imports` ; la resserrer change les clés de cache. L'élargir exige d'ajouter le module à `HOST_EXPOSED_MODULES` (donc à `host.js`).
3. La compilation ne lit aucun fichier de la scène : tout ce qui touche au disque d'une scène passe par `PrefabService.remotion_source` (octets déjà validés).
4. `scene.js` n'est qu'une fonction de la source et de l'hôte ; l'exécuter (page, origine, CSP, quotas, durée) est à vous. `window.remotion_staticBase` est la seule variable globale que la page doit poser.

## 8. Contract for Slice 08 / 10 / 14 / 17 / 19

- **08 (Board)** : une source reste le parent logique (Slice 07) ; rien dans le contexte d'un Board ne doit être un chemin disque. Utiliser `CompiledArtifact.to_public()` et `(prefab_id, version)`, jamais `compiled/…`.
- **10 (Player)** : appeler `PrefabService.remotion_source(id, version)` puis `RemotionCompiler.compile_host()` / `compile_scene(source)` dans `asyncio.to_thread` ; servir via `resolve_output_file` ; poser `remotion_staticBase`, monter le Player avec `source.block.composition`. Mapper les codes de §5 (`compile_runtime_unavailable` -> `engine_unavailable`). `PrefabService.bundle()` refuse un prefab Remotion (`invalid_definition`) : une fenêtre HTML ne doit jamais recevoir une source Remotion. Câbler `build_remotion_compiler(host, store, runner, diagnostics=…)` dans `v2_app`/`app.py` (rien n'est instancié par Core aujourd'hui : Issue 02).
- **14 (HMR, agents)** : une édition est une **nouvelle version** de la source (candidat `build_candidate`/`parse_candidate`, mêmes champs que `SourceEditRequest` étendu à `{chemin: texte}`) ; `compose_candidate` est à généraliser. La compilation d'une version déjà vue est gratuite (même contenu = même clé).
- **17 (catalogue)** : le manifeste v2 est la base. Ajouter les champs (type sémantique, compatibilité par moteur, pile technique, dépendances, licence, amont) **dans une version 3** qui peut s'appliquer aux deux genres (règle de §4 : écrire à la plus basse version qui exprime le manifeste, jamais de retrait de clé), avec un test de balayage de bibliothèque qui lit v1, v2 et v3 et une garde « un lecteur v2 refuse v3 sans planter ». Les prefabs HTML restent en v1 tant qu'ils ne portent rien de la v3. `source.engine` est déjà la déclaration « compatible `remotion` » d'une source v2.
- **19 (promotion, mises à jour)** : `engine_drift` signale qu'une version a été écrite pour un autre arbre ; l'essai de mise à jour se fait dans une nouvelle variante (nouveau pin), jamais en place.

## 9. Preuves

Harnais `scripts/remotion_compile_harness.py` : vrai `LocalCapabilityHost` + vrai `NodeCapabilityRunner` (vrai npm, vrai réseau pour l'installation), vrai `PrefabService`/`FilePrefabLibrary`, vrai compilateur, vrai Chrome (headless, page servie par un serveur HTTP de boucle locale), racine de données privée dans le dossier temporaire (jamais `~/.jarvis`), Core non démarré. Sortie : `tasks/jarvis-remotion-presentation-integration/slices/05-remotion-project-source-contract/evidence/real-compile.json` (SHA du dépôt, plateforme, Node, durées, listes de fichiers, codes d'échec, texte rendu par le Player).

Scénarios : installation fraîche ; publication d'une source puis d'une révision ; **redémarrage** (service et compilateur neufs : même source octet pour octet, même `source_digest`, compilation relue du cache) ; compilation `host` puis `scene` ; absence de `node_modules`/`package.json` dans la bibliothèque et dans le cache ; erreur de syntaxe (fichier, ligne, colonne), import `fs`, import qui sort de la source, export par défaut manquant, délai ; Player dans Chrome (titre rendu à partir de `inputProps`, couleur appliquée, image servie par `staticFile`) ; `uninstall` de la capacité : sources identiques à l'octet, compilation ensuite refusée par `compile_runtime_unavailable`.

Tests (aucun réseau) : `tests/unit/test_remotion_source.py` (domaine : chemins, bloc, fichiers, empreintes, manifeste, compatibilité v1), `test_remotion_source_store.py` (bibliothèque réelle sur dossiers temporaires : disposition, immutabilité, redémarrage, altération, rétention, épinglage, scène/ancres), `test_remotion_compiler.py` (faux Node : cache, clés, échecs typés, concurrence, élagage, forme publique), `test_remotion_compiler_real.py` (Node + esbuild réels, ignoré sans `JARVIS_REMOTION_RUNTIME_DIR`), `test_remotion_source_docs.py` (ce document contre le code).

## 10. Limites et risques résiduels

- **Mémoire** : le catalogue ne garde que le manifeste et l'inventaire (environ 150 octets par fichier, 128 fichiers au plus par version), jamais le contenu ; un test mesure qu'un chargement de catalogue avec un asset de 3 Mio retient moins de 400 Kio et ne dépasse pas 1 Mio de pointe (lecture en flux de 256 Kio). Le pire cas ne dépend donc plus de la taille des assets : (manifeste <= 32 Kio + inventaire <= 20 Kio) par version, la même échelle que les versions HTML. Les octets d'une source ne sont en mémoire que le temps d'une relecture (`remotion_source`, au plus 20 Mio) ou d'une compilation. Un dossier gonflé à la main est refusé **avant lecture** (nombre de fichiers borné avant tri, taille de chacun et du total relevée par `lstat`).
- **Taille sur disque** : les assets d'une source sont dupliqués dans chaque version (immuabilité) ; avec la rétention (≥ 16 versions vivantes + épinglées + archives) une scène à 16 Mio d'assets peut peser plusieurs centaines de Mio. Les assets volumineux ou partagés relèvent des références vivantes de la Slice 09 ; une déduplication par contenu serait une suite.
- **Pas d'isolation à l'exécution** (§6), ni de vérification de types TypeScript (esbuild enlève les types, il ne les contrôle pas ; une erreur de type ne bloque pas la compilation).
- **Un import inutilisé n'est pas vu** : esbuild retire un import jamais utilisé d'un fichier TypeScript avant de le résoudre ; il ne s'exécute pas, donc inoffensif, mais n'est pas « refusé ». Un `import "fs"` (effet de bord) l'est.
- **Windows seul éprouvé en réel** ; Node 24.18 ; macOS/Linux jamais exécutés. Chrome a été exercé en headless ; un Player en fenêtre réelle reste à la Slice 10.
- **Dépendance à `window.remotion_staticBase` de Remotion 4.0.534** (comportement vérifié dans `static-file.js`) ; une montée de version de Remotion se vérifie avec le harnais.
- **Coût d'un lecteur ancien** : sur un poste où une ancienne version de Jarvis lirait la même racine de données, les sources v2 y sont `tampered` (refusées, tracées).
- **Altération du cache de compilation** : une édition qui restitue la taille **et** la date d'un fichier de sortie n'est pas vue au service (elle l'est à la relecture complète du cache) ; c'est un attaquant maître de la racine de données, hors périmètre.
