# Import d'un modèle Remotion amont : origine vérifiée, licence, dépendances, provenance

Handoff `jarvis-remotion-presentation-integration`, Slice 18. **Statut : contrat (Level 2) et implémentation (Level 3) livrés ; éprouvé sur le réseau réel (GitHub), avec le vrai compilateur et dans un vrai Chrome** ([preuves](#10-preuves)). Ce que ce document ne fait pas : promouvoir un import vers la bibliothèque partagée (Slice 19), mettre une scène importée sur le plan d'une présentation (Studio, Slices 14-15), rendre en MP4 (Slice 16). Rien ici ne démarre, n'arrête ni ne relance Core, le Control Center, la voix ou ai-visualizer.

Termes : un **modèle amont** est le code source TSX d'un projet Remotion publié ailleurs (dépôt GitHub). L'**import** en fait **une version de prefab Remotion** ([remotion-source.md](remotion-source.md)) dont le manifeste v3 porte un bloc `catalog` ([prefabs.md](prefabs.md) › *Manifest v3*) : licence, dépendances, provenance. Le **code amont n'est jamais exécuté** par l'import : il est lu comme du texte.

## 1. Décision : un importeur de Core, une origine vérifiée, la source d'un prefab de la présentation

- **Seul Core parle au réseau**, par un port (`jarvis/ports/upstream_fetcher.py`) ; le code d'une scène n'y a aucun accès. Adaptateur réel : `HttpsUpstreamFetcher`. Faux de test : `FakeUpstreamFetcher` (garde la liste des adresses demandées : un refus d'origine n'ouvre **aucune** connexion).
- **Aucun importeur existant à réemployer** (audit R19) : `read_zip_source` (Slice 06) lit un ZIP local et reste disponible pour un futur import de fichier ; l'import amont lit une archive `tar.gz` de GitHub (`read_tar_source`), avec les mêmes refus (liens, chemins, doublons, bombes).
- **Le résultat est une version de prefab propre à UNE présentation** : `presentation-studio.p<12 hex de la présentation>.s<12 hex de la scène>` (`source_prefab_id`), jamais un prefab de la bibliothèque partagée. La requête n'a **aucun** champ de portée : un champ inconnu (`scope`, `library`, `publish`, `promote`...) est refusé, et le message dit pourquoi. La promotion vers la bibliothèque partagée reste une demande explicite et distincte : le chemin de promotion existant (`PresentationStudioTemplateService`, Slice 20 d'origine) est **HTML seulement** aujourd'hui, la promotion qui sait porter une source Remotion et sa provenance est la Slice 19. L'import ne pose pas la scène dans le document : il rend le pin `(prefab_id, version)`.
- **Aucun npm, aucun `package.json`, aucun script** : la source importée est limitée aux paquets du jeu verrouillé de la capacité Remotion ([§ 5](#5-dépendances--la-liste-auditée)).

## 2. Origines et téléchargement

Une requête dit `repo_url` (`https://github.com/<propriétaire>/<dépôt>`) et `commit` (SHA complet de 40 caractères hexadécimaux en minuscules : une branche ou une étiquette bouge, un SHA non). L'adresse de téléchargement est **construite** : `https://codeload.github.com/<propriétaire>/<dépôt>/tar.gz/<sha>`, jamais reprise de l'entrée.

| Règle | Détail |
| --- | --- |
| Hôte | `github.com` seulement en entrée ; téléchargement depuis `codeload.github.com`. Aucun autre hôte, aucune adresse `raw.githubusercontent.com` (une page, un aperçu MP4 ou un zip quelconque n'est jamais une source). Les hôtes ne se règlent pas. |
| Schéma | HTTPS seulement (certificat vérifié, contexte par défaut) ; pas d'identifiants, de port, de requête ni de fragment. |
| Propriétaires | Liste blanche réglable, défaut `remotion-dev` : `control-center-settings.json` du dossier d'exécution, clé `remotion_import.allowed_owners` (liste de noms GitHub), relue à **chaque** import (un changement s'applique sans redémarrage). Une entrée illisible est écartée, une liste vide ou absente retombe sur le défaut. |
| Redirections | Au plus 3, **jamais suivies automatiquement** ; chacune doit rester en HTTPS, sur `github.com` ou `codeload.github.com`, sans identifiants ni port, et sur le chemin du **même dépôt** (un dépôt transféré vers un autre propriétaire n'est pas suivi). Sinon `redirect_refused`, et aucune deuxième connexion n'est ouverte. |
| Bornes | Archive ≤ 12 Mio (annoncée puis comptée en lisant), délai global 30 s (chaque lecture est bornée par `min(10 s, temps restant)` : un seul morceau lent ne dépasse pas l'échéance), aucun proxy ni identifiant, un seul import à la fois (`import_busy`). |

Bornes de lecture (domaine, `jarvis/domain/remotion_upstream.py`) : 6000 membres au plus, 96 Mio décompressés au plus (la décompression est plafonnée pendant le flux : une bombe ne remplit pas la mémoire), 24 Mio de fichiers lus au plus.

## 3. Lecture de l'archive

`read_tar_source` lit le `tar.gz` **en mémoire, en flux**, sans rien écrire sur disque. L'archive **entière** est refusée pour :

- un lien symbolique ou physique, un périphérique ou tout membre autre qu'un fichier ou un dossier, même hors de ce qu'on aurait lu (`archive_link`) ;
- un chemin absolu, avec `..`, segment vide ou `.`, antislash, lecteur ou NUL (« zip-slip ») ; plusieurs dossiers racines (`archive_path`) ;
- deux membres de même nom, casse comprise (`archive_duplicate`) ;
- trop de membres ou une décompression au-delà de la borne (`archive_too_large`) ; un flux illisible ou tronqué (`archive_invalid`) ;
- un **commit non attesté** : GitHub écrit le SHA dans l'en-tête pax global (`comment`) ; absent ou différent du SHA demandé : `archive_commit_mismatch`. **Ce que cela prouve, et ce que cela ne prouve pas** : seulement que GitHub a répété le SHA demandé. Les objets d'un réseau de forks peuvent être servis sous le chemin d'un propriétaire autorisé (non testé ici) : **la liste blanche protège le propriétaire, pas le commit**. Une vérification d'accessibilité du commit depuis une branche du dépôt est une suite possible (Issue 04).
- une lecture trop longue : **échéance** de 20 s pour la lecture de l'archive (décompression comprise, tampon linéaire : 80 Mio de zéros dans 90 Kio se traversent en moins d'une seconde), `import_timeout`.

Seuls les fichiers dont l'importeur a besoin sont lus (`src/**`, `public/**` nommés par `staticFile`, licence, `package.json`). Le SHA-256 de l'archive est enregistré (`archive_sha256`).

## 4. Licence : celle du modèle, jamais celle de Remotion

Deux licences, deux champs :

- `catalog.license` : l'identifiant SPDX de la licence **du modèle**, lu dans le fichier `LICENSE*`/`COPYING*` de la racine (du sous-dossier du projet d'abord), sinon dans `package.json`. Le texte est recopié dans `src/upstream/license.json` pour que l'attribution voyage avec la source.
- `catalog.runtime_license` : la licence du **moteur** (`Remotion License (company licence may be required)`), écrite telle quelle. Jarvis n'évalue pas l'obligation d'une licence d'entreprise de l'utilisateur : il la **consigne**.

Licences redistribuables (`PERMITTED_LICENCES`) : `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `0BSD`, `Unlicense`, `CC0-1.0`. **Reconnaissance exacte** : le texte du fichier, une fois normalisé (minuscules, ponctuation retirée, titre, paragraphe de copyright et « all rights reserved » retirés), doit être **identique** au texte canonique de la licence (empreintes `CANONICAL_LICENCE_HASHES`, calculées sur les textes de l'API de licences de GitHub gardés dans `tests/fakes/licenses/`). Un paragraphe ajouté (clause « Commons », « usage personnel seulement », « aucune vidéo monétisée »...) fait que le texte n'est plus reconnu : `license_restricted` si un mot de restriction y figure, sinon `license_unknown`. **Tous** les fichiers de licence de la racine (`LICENSE*`, `LICENCE*`, `COPYING*`, `UNLICENSE*`) sont examinés et doivent dire la même chose (un `LICENSE` MIT ne cache pas un `LICENSE.md` GPL ; deux licences permises différentes, `LICENSE-MIT` et `LICENSE-APACHE`, sont un `license_conflict` : l'expression « MIT OR Apache-2.0 » n'est pas portée). Tout le reste est refusé, avec un code propre :

| Cas | Code |
| --- | --- |
| aucun fichier et aucune déclaration | `license_missing` |
| `UNLICENSED` ou « see license in LICENSE » sans fichier (tous droits réservés) | `license_unlicensed` |
| GPL, AGPL, LGPL, MPL, EUPL, SSPL, BUSL, EPL, CDDL, Creative Commons (hors CC0 exact), « non commercial », restriction d'usage ajoutée, ou la licence de Remotion elle-même | `license_restricted` |
| texte qui n'est pas exactement une licence examinée, ou déclaration hors liste | `license_unknown` |
| les fichiers se contredisent, ou le fichier dit une chose et `package.json` une autre | `license_conflict` |

Constat réel ([§ 10](#10-preuves)) : les modèles `template-empty` et `template-helloworld` de `remotion-dev` déclarent `UNLICENSED` et renvoient le lecteur à la licence de Remotion : ils sont **refusés**. `template-three` porte un fichier MIT et un `package.json` `UNLICENSED` : refusé en `license_conflict`.

## 5. Dépendances : la liste auditée

L'import ne regarde pas ce que `package.json` annonce mais ce que la source **atteint**. Le graphe d'imports est suivi depuis le composant (modules relatifs seulement) ; chaque import nu atteint est jugé :

| Paquet | Décision |
| --- | --- |
| `react`, `react/jsx-runtime`, `react/jsx-dev-runtime`, `remotion` | admis : la version est celle du **jeu verrouillé** de la capacité (`catalog.dependencies` porte `react` et `remotion` aux versions épinglées ; la plage déclarée par le modèle est dite dans `changes`) |
| tout autre paquet (`three`, `zod`, `roughjs`, `@remotion/*` autre que `remotion`, `react-dom`, modules Node) | **refusé** `dependency_refused`, avec le paquet, le fichier qui l'importe et la plage déclarée |

**Lecture prudente** : les imports sont cherchés dans le texte sans commentaires **et** dans le texte brut, sans exiger d'espaces (`import{a}from'zod'`, `export*from'zod'`, `require('zod')`, `import('zod')`), car un `/*` au milieu d'un texte JSX (`<p>/*</p>`) n'est pas un commentaire mais ferait taire la suite. Conséquence assumée : un `import` en commentaire d'un paquet hors liste refuse aussi ; un import relatif trouvé seulement dans le texte brut est suivi s'il existe (jamais de module silencieusement écarté). Un import de style ou de média (`./x.css`, `./a.png`) est refusé `import_unsupported_file` (le compilateur importe des modules ; les médias passent par `staticFile`), un import qui sort de `src/` `import_outside_source`, un import introuvable `import_unresolved`. Il n'y a **pas d'adaptateur** : la liste auditée est exactement `SCENE_ALLOWED_IMPORTS` ([remotion-source.md](remotion-source.md) §5) ; l'élargir exige d'exposer le module dans `host.js` et de le revoir ici. Une dépendance déclarée mais jamais atteinte (outils, `zod` d'un `Root` non repris, `@remotion/cli`) est **écartée et listée** dans `changes`. Un `remotion` déclaré d'une autre version majeure est refusé (`remotion_version_incompatible`) ; un `react` d'une autre majeure est un avertissement (`warnings`). Les scripts (`postinstall`...) ne sont jamais lus ni lancés.

## 6. Composition et entrée générée

Un projet Remotion déclare ses compositions dans un `Root` (`<Composition id component durationInFrames fps width height defaultProps />`), pas par un `export default`. Le plan :

1. cherche les balises `<Composition>` dans `src/` (commentaires retirés pour cette recherche) ; une seule : retenue, plusieurs : `composition_id` obligatoire (`composition_ambiguous`, ids listés), inconnue : `no_composition` ;
2. lit `width`, `height`, `fps`, `durationInFrames` : littéraux, constantes numériques uniques (`const FPS = 24`) ou arithmétique simple de ceux-là ; sinon `composition_unresolved` et l'appelant les donne dans `composition` (aucune valeur n'est devinée) ;
3. génère `src/Scene.tsx` (`src/JarvisEntry.tsx` si le dépôt a déjà un `Scene.tsx`) : il importe le composant (par le même import que le `Root`, ou depuis le fichier qui l'exporte) et rend `createElement(Composant, {...defaultProps, ...props})`. Les `defaultProps` du `Root` sont recopiés avec leurs imports ; une constante locale du `Root` ne peut pas l'être (`default_props_unresolved`) ; un composant venu d'un paquet ou non exporté est refusé (`component_unresolved`) ;
4. ne reprend que les modules **atteignables** (le `Root`, `index.ts`, `remotion.config.ts` restent dehors) et les fichiers de `public/` dont un `staticFile("nom")` littéral donne le nom. Un `staticFile` calculé ou un fichier manquant est un **avertissement** (la scène ne le trouvera pas), jamais un fichier deviné.

Puis le candidat passe par `parse_candidate`, donc par les **gardes de la Slice 06** (`SOURCE_GUARDS` : API navigateur, contenu actif des SVG, signature des assets) et les bornes de la Slice 05 (64 modules, 256 Kio chacun) : refus `source_guard_refused` (constats cités) ou `source_invalid`. Le même juge s'applique à la publication et à chaque relecture.

## 7. Provenance : écrite et vérifiée par Core

`catalog.upstream` (prefabs.md) gagne cinq clés **écrites seulement par l'importeur** (`VERIFIED_UPSTREAM_KEYS`), et `catalog.runtime_license` l'est aussi :

| Clé | Contenu |
| --- | --- |
| `commit` | le SHA demandé, **attesté par l'archive** (§ 3) |
| `archive_sha256` | SHA-256 de l'archive téléchargée |
| `imported_at` | date d'import UTC (`AAAA-MM-JJTHH:MM:SSZ`) |
| `changes` | ≤ 16 lignes : entrée générée, composition lue, modules et assets gardés ou écartés, dépendances (plage déclarée -> version du jeu verrouillé), licence |
| `source_sha256` | `source_digest` de l'ENSEMBLE EXACT de fichiers écrit dans la version (chemins triés + SHA-256 de chaque contenu) |

avec `name` (`propriétaire/dépôt`), `url`, `license` (SPDX du modèle), `author` (propriétaire), et `ref` (libellé libre optionnel de la requête). **Ce que Core écrit et ce que l'auteur déclare** : ces six champs (les cinq clés et `runtime_license`) sont écrits par Core ; le reste du catalogue (type, pile, `license` d'un prefab qui n'est pas un import) est déclaré par l'auteur. **Vérification** : un candidat qui porte l'un de ces champs et ne vient pas de l'importeur est refusé par `PrefabService.save` **et** par `edit_base` (« written by the upstream importer only »), sauf une révision qui reporte ceux de sa version précédente **à l'identique**.

**Intégrité (jamais de blanchiment)** : reporter la provenance n'est pas la garantir. La vue de catalogue (`GET /v1/prefabs/{id}[/{version}]?catalog=1`, lignes de liste comprises) compare l'empreinte des fichiers COURANTS de la version (calculée depuis son inventaire, sans relire d'octet) à `source_sha256` et ajoute à `upstream` : `verified_intact` (`true` : fichiers exactement ceux de l'import) et, sinon, `modified_files` (chemins ajoutés, retirés ou changés par rapport à la version d'origine, ≤ 32 ; `null` si cette version n'est plus lisible). Une version modifiée n'est jamais présentée comme « vérifiée » : la carte de la bibliothèque (Slice 17) écrit « Importé de cet amont : fichiers intacts, vérifié par Core » ou « Importé de cet amont : modifié depuis l'import » (origine, date, commit et fichiers modifiés restent visibles comme **historique**). Une révision qui rend les octets d'origine est de nouveau intacte : l'empreinte, pas l'histoire, décide. Les versions restent immuables ; `changes` n'est pas réécrit.

## 7 bis. Un modèle importé comme inspiration d'un brouillon d'agent (Slice 15)

Un modèle amont importé n'est **jamais appliqué de lui-même** : il ne sert d'inspiration à un brouillon (`prefabs[].remotion.inspiration {id, version}`, outils `presentation_draft_*`) que si l'agent le désigne et que Core
confirme sa provenance (`catalog.upstream.commit`, écrit par l'importeur seul). Sans cela le constat `tsx_inspiration_unconfirmed` refuse le brouillon. Accepté, le lien est enregistré (`derived_from`, origine `fork`, et
`provenance.inspirations` : `id`, `version`, `upstream`, `commit`, `license`, `verified_intact`) ; aucun octet n'est copié, la licence reste celle que l'importeur a enregistrée (§ 4). Détail :
[presentation-studio.md](presentation-studio.md#remotion-scenes-the-generator-slice-15).

## 8. Service, routes et codes

`RemotionImportService` (`jarvis/core/remotion_import_service.py`, câblé dans `JarvisCoreApplication` quand un `upstream_fetcher` est fourni — `jarvis/app.py` le fournit ; sans lui les routes répondent 503). Deux routes de Core (jeton porteur), **aucune** route du Control Center : un import est une demande explicite de l'utilisateur. Depuis la Slice 21, `remotion_import` (serveur `jarvis-remotion`, [remotion-runtime.md](remotion-runtime.md) §13) appelle ces deux routes sur la demande de l'utilisateur dans le tour en cours (attesté, ses mots en `user_request`, SHA complet donné par lui, `execute` seulement après un `plan` identique) ; jamais un geste spontané de l'agent, jamais la bibliothèque partagée, et la liste blanche des propriétaires reste un réglage que l'agent ne peut pas écrire.

| Méthode | Route | Corps | Réponse |
| --- | --- | --- | --- |
| POST | `/v1/remotion/imports/plan` | `{repo_url, commit, composition_id?, subdir?, composition?, title?, ref?}` | `{plan, guards_passed: true, compiled: false, publishes: false}` : télécharge, vérifie, analyse, passe les gardes ; n'écrit rien |
| POST | `/v1/remotion/imports` | idem + `presentation_id`, `scene_id?` | `{imported, scope: "presentation", presentation_id, scene_id, prefab: {prefab_id, version, fingerprint}, plan, published_to_library: false}` |

`subdir` désigne le projet dans un monorepo ; `composition` = `{width, height, fps, duration_in_frames}` donnés à la main quand le code ne les rend pas lisibles. `guards_passed` dit ce qui a été vérifié (manifeste, bornes, gardes de la Slice 06) ; `compiled: false` dit ce qui ne l'a PAS été : le plan ne compile pas, la compilation est le premier usage (une erreur `compile_*` y reste possible). Un import vers une présentation inconnue est refusé **avant** tout téléchargement. Le plan public (`ImportPlan.to_public()`) ne contient aucun octet de source, aucun chemin du poste.

Refus : `{"error": {"code", "message", "details"?}}`. Codes et statuts :

| Code | HTTP | Cause |
| --- | ---: | --- |
| `request_invalid` | 400 | corps illisible, champ inconnu (dont toute demande de portée « bibliothèque »), `presentation_id` manquant ou mal formé |
| `origin_invalid` | 400 | adresse mal formée, non HTTPS, avec identifiants, port, requête ou fragment |
| `commit_not_pinned` | 400 | le commit n'est pas un SHA complet |
| `origin_not_allowed` | 403 | hôte autre que `github.com`, ou propriétaire hors liste blanche |
| `redirect_refused` | 502 | redirection hors des hôtes ou du dépôt, ou plus de 3 |
| `fetch_failed` | 502 | HTTP non 200 (404 : commit inconnu de ce dépôt), erreur réseau ou TLS |
| `fetch_timeout` | 504 | délai global dépassé |
| `fetch_too_large` | 413 | archive au-delà de la borne |
| `import_timeout` | 504 | lecture de l'archive ou analyse du texte au-delà de l'échéance (20 s) |
| `presentation_not_found` | 404 | la présentation n'existe pas |
| `import_busy` | 409 | un autre import est en cours |
| `import_storage_failed` | 500 | la bibliothèque n'a pas pu écrire |
| `archive_invalid` | 422 | pas un `tar.gz` lisible, membre incohérent, aucun fichier |
| `archive_link` | 422 | lien ou membre spécial |
| `archive_path` | 422 | chemin hors de la racine, plusieurs racines |
| `archive_duplicate` | 422 | deux membres de même nom |
| `archive_too_large` | 422 | trop de membres ou de données décompressées |
| `archive_commit_mismatch` | 422 | commit non attesté par l'archive |
| `license_missing` | 422 | aucune licence |
| `license_unknown` | 422 | licence hors des licences examinées |
| `license_unlicensed` | 422 | `UNLICENSED` / tous droits réservés |
| `license_restricted` | 422 | copyleft, non commerciale ou licence de Remotion |
| `license_conflict` | 422 | fichier et `package.json` en désaccord |
| `no_project` | 422 | aucun module `src/` |
| `no_composition` | 422 | aucune `<Composition>` (ou id inconnu) |
| `composition_ambiguous` | 422 | plusieurs compositions, `composition_id` absent |
| `composition_unresolved` | 422 | réglages illisibles dans le code |
| `component_unresolved` | 422 | composant non importable |
| `default_props_unresolved` | 422 | `defaultProps` non transportables |
| `dependency_refused` | 422 | import hors liste auditée |
| `remotion_version_incompatible` | 422 | autre version majeure de Remotion |
| `import_unresolved` | 422 | import relatif introuvable |
| `import_unsupported_file` | 422 | import de style ou de média |
| `import_outside_source` | 422 | import hors de `src/` |
| `file_too_large` | 422 | asset nommé trop gros |
| `source_invalid` | 422 | la source ne tient pas dans la disposition d'une scène (bornes, UTF-8) |
| `source_guard_refused` | 422 | refus des gardes de la Slice 06 (constats cités dans `details`) |

Un défaut inattendu est un 500 `remotion_import_failed` sans détail interne, journalisé `core.remotion_import.route_failed` (niveau `error`).

## 9. Observabilité

Journal de Core, ids et comptes seulement (jamais un contenu de source) : `core.remotion_import.planned` (origine, commit, licence, nombre de modules et d'assets, taille, redirections, avertissements), `core.remotion_import.imported` (présentation, scène, prefab, version), `core.remotion_import.refused` (code et motif, niveau `warning`), `core.remotion_import.route_failed` (`error`). Le chemin normal est journalisé aussi : « rien dans le journal » ne veut pas dire « rien n'a été importé ».

## 10. Preuves

Épreuve opt-in `tests/unit/test_remotion_import_real.py`, lancée par `scripts/remotion_player_harness.py --slice 18 --report real-import.json` avec `JARVIS_REMOTION_IMPORT_NETWORK=1` : vrai réseau GitHub (`HttpsUpstreamFetcher`), vrai `PrefabService`, vrai compilateur Node + esbuild du verrou (runtime privé, jamais le profil vivant), vrai Chrome, Core isolé sur des ports libres. Sortie : `tasks/jarvis-remotion-presentation-integration/slices/18-upstream-template-import/evidence/` (`real-import.json`, `real_import_render.json`, `real_refusals.json`, capture). Cas réels, commits épinglés :

- **importé, compilé, joué** : `hongjiapeng/remotion-workflow-visualizer@730615b7` (MIT, `remotion` + `react` seulement) ;
- **refusés** : `remotion-dev/template-empty` et `template-helloworld` (`license_unlicensed`), `template-three` (`license_conflict`), `remotion-dev/highlighter` et `lifeprompt-team/remotion-scenes` (`dependency_refused`), propriétaire hors liste blanche (`origin_not_allowed`, aucune connexion).

Tests sans réseau : `tests/unit/test_remotion_upstream.py` (origine, archive hostile, licence, téléchargeur contre un faux `HTTPSConnection` : redirection hors hôte, `http`, autre dépôt, trop de sauts, 404, délai, taille), `test_remotion_import.py` (analyse : dépendances, composition, entrée, graphe, assets, gardes, catalogue v3), `test_remotion_import_service.py` (service, routes, provenance, câblage), `test_prefab_catalog.py` (nouvelles clés), `test_remotion_import_docs.py` (ce document contre le code).

## 11. Limites et risques résiduels

- **Lecture statique** : le graphe d'imports est trouvé par expressions régulières (texte sans commentaires et texte brut, quantificateurs bornés, échéance de 20 s pour toute l'analyse : `import_timeout`), pas par un analyseur TypeScript. Un `import` fabriqué pour échapper à la lecture est tout de même refusé par le compilateur (imports nus hors liste, `compile_import_refused`) et par les gardes de la Slice 06 : l'analyse est un diagnostic précoce, pas la frontière. La frontière d'exécution reste le bac à sable ([remotion-isolation.md](remotion-isolation.md)).
- **Licence** : reconnue par comparaison EXACTE avec les textes canoniques (un texte inhabituel est refusé `license_unknown`, jamais accepté « à peu près ») ; un fichier de licence légèrement reformaté (copyright sur deux paragraphes, mise en forme) peut être refusé à tort ; pas un identifiant SPDX signé. Aucune licence séparée n'est cherchée pour les fichiers de `public/` : un asset est couvert par la licence du dépôt, et le plan le dit dans `changes`. Les marques et les polices ne sont pas examinées. Pas un avis juridique.
- **Licence de Remotion** : consignée, non examinée (l'obligation d'une licence d'entreprise dépend de l'utilisateur).
- **GitHub seulement** ; pas de ZIP importé, pas d'URL libre. Un dépôt privé n'est pas accessible (aucun jeton n'est transmis).
- **Composition** : les `defaultProps` qui référencent une constante locale du `Root`, les `calculateMetadata`, les `lazyComponent` et les paramètres calculés ne sont pas transportés ; le plan le dit ou refuse. Le schéma de props de la scène importée est vide (`inputs.props` sans propriété) : les contrôles de la partition ne la pilotent pas encore.
- **Scène non épinglée** : l'import rend un pin ; tant qu'aucun document ne l'épingle, la rétention des prefabs `presentation-studio.*` peut l'archiver comme n'importe quelle source inutilisée.
- **Windows seul éprouvé**, Chrome 154 seul pour le rendu ; le réseau réel dépend de GitHub (les commits épinglés ne bougent pas, les dépôts peuvent disparaître).

## 11. Promotion vers la bibliothèque ou un modèle de présentation (Slice 19)

Un import reste **propre à sa présentation** (§ 3). La sortir de là est une demande explicite à part, par le service de modèles existant (`PresentationStudioTemplates`, [presentation-studio.md](presentation-studio.md#remotion-aware-promotion-remotion-slice-19)), et la provenance suit des règles écrites ici parce qu'elles découlent de celles de l'import :

- **Intact** (les fichiers recalculés rendent `catalog.upstream.source_sha256`) : la source promue garde `commit`, `archive_sha256`, `imported_at`, `changes`, `source_sha256` et `runtime_license` ; la publication passe par la porte de l'importeur (`verified_import`), le catalogue lit `verified_intact: true`. Pour un modèle de présentation, le recalcul est refait **à l'instanciation** : un enregistrement qui revendique un import vérifié que ses fichiers ne rendent pas est refusé avant toute création.
- **Ancré** (rework QA) : pour un modèle de présentation, « intact » ne suffit pas à l'instanciation : Core exige en plus de détenir encore une version saine dont la provenance écrite par l'importeur porte le même commit, la même archive et la même empreinte (`PrefabService.holds_verified_import`). Un enregistrement édité à la main mais cohérent (fichiers, empreinte, faux commit) est installé SANS les clés de l'importeur et rendu `declared_not_reverified` ; si la rétention a archivé l'import d'origine, un enregistrement authentique se lit pareil (honnête, pas alarmant).
- **Modifié** : ces clés ne sont **pas** portées (`upstream_verification_dropped`) ; `name`, `url`, `ref`, `license`, `author` restent comme déclaration, jamais comme vérification. Une source modifiée ne peut donc jamais être promue « vérifiée ».
- **Licence** : un amont dont la licence n'est pas dans `PERMITTED_LICENCES`, ou n'est pas déclarée (`not-declared`), n'est promu que si la demande nomme cette licence (`licence_ack`). Un import par l'importeur passe toujours (il refuse déjà les licences non permises) ; le cas visé est un amont **déclaré** à la main ou une licence modifiée.
- **Assets** (`public/**`) : gardés sans question pour un import intact (ceux de l'amont) ; sinon `keep_assets: true`, parce qu'une image peut être un média du projet.
