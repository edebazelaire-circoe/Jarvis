# Rendu et export d'une présentation gelée : MP4, images, PDF, liens d'origine exacts

Handoff `jarvis-remotion-presentation-integration`, Slice 16. **Statut : contrat (Level 2) et implémentation réelle (Level 3), vérifiés sur Windows 11 avec le vrai moteur Remotion épinglé, le vrai Chrome installé, un vrai Core et un vrai Control Center** ([preuves](#11-preuves)). Le rendu **exécute le code de la scène** dans un navigateur sans interface : il tourne donc sous le même modèle de menace que le Player ([remotion-isolation.md](remotion-isolation.md)) et son processus est isolé plus strictement encore ([§4](#4-isolation-du-processus-de-rendu)).

Pages voisines : [presentation-artifacts.md](presentation-artifacts.md) (source, snapshot, dérivé, `begin_render`), [remotion-runtime.md](remotion-runtime.md) (la capacité), [remotion-studio.md](remotion-studio.md) (le Studio n'est pas un moteur de rendu), [artifacts.md](artifacts.md).

## 1. Décisions

| Décision | Conséquence |
| --- | --- |
| **Un rendu part d'un snapshot figé, jamais d'une édition** (décisions 6 et 7 du handoff). | Les valeurs de contrôles, le rechargement à chaud, une édition de source ne rendent **jamais** un MP4. Seule une demande explicite d'export le fait, et elle rend **un snapshot `complete`** relu et vérifié (hash du paquet, empreinte de chaque membre) : la source vivante, la bibliothèque de prefabs vivante et les Boards ne sont pas consultés. |
| **Une scène par export.** | Cadence, taille et durée sont celles que le manifeste de la scène **déclare**. Un snapshot à plusieurs scènes demande `settings.scene_id` (jamais deviné) ; la concaténation d'une variante entière en un seul fichier n'est **pas** livrée ([§12](#12-limites-et-risques-résiduels)). |
| **Chaque export est un Artifact dérivé** (`presentation_video`, `presentation_still`, `presentation_pdf`), terminal, relié au snapshot par **une** relation `rendered_from`. | L'origine éditable se retrouve en deux sauts : dérivé → snapshot (relation) → source + variante + révisions (métadonnées typées du snapshot), puis « Ouvrir la source » ([presentation-artifacts.md](presentation-artifacts.md)). Les réglages résolus sont **figés avec le dérivé**. |
| **Un export est plat.** | `render_flat: true` sur chaque dérivé, dit dans la vue du Board : un MP4, une image ou un PDF n'est **jamais** présenté comme éditable ; l'origine éditable est la source. |
| **Remotion seul exporte** (`export` est `unsupported` pour Slidecar). | `begin_render` refuse un snapshot Slidecar ; il n'y a aucun repli (« Slidecar n'exporte pas » est dit à l'écran). |
| **Aucun téléchargement, aucune installation.** | Le rendu utilise la capacité Remotion **déjà installée** et le Chrome ou Edge **déjà installé** (`JARVIS_REMOTION_RENDER_BROWSER` pour en imposer un). Sans navigateur : `presentation_render_browser_unavailable`, jamais un téléchargement silencieux de « Chrome Headless Shell ». |
| **Concurrence 1, 8 travaux actifs au plus.** | Un rendu à la fois ; les autres attendent. Au plus 8 travaux non terminés **en tout** (celui qui tourne compris, créations en vol comprises) : la place est réservée avant le premier `await` de la demande, donc une rafale de 40 demandes en accepte 8 et refuse 32 (`queue_full`), sans aucun dérivé créé pour un refus. |
| **Le même rendu n'est pas refait.** | Un même (snapshot, réglages résolus) rend le travail en cours ou le rendu `complete` existant (`deduplicated: true`) ; deux demandes identiques simultanées font un seul travail. Un rendu échoué n'est jamais rendu comme doublon. |
| **Un seul Core vivant par racine de données.** | `render/core.lock` (référence `pid:heure`) : un second Core vivant ne lance, ne reprend et ne tue aucun rendu (`presentation_render_locked`) ; le verrou d'un Core disparu est repris. |
| **Le bac à sable du processus de Chrome reste actif.** | Remotion pose `--no-sandbox` ; le garde le retire (§4). `JARVIS_REMOTION_RENDER_NO_SANDBOX=1` est la seule sortie, un choix explicite de l'utilisateur ; un navigateur qui ne démarre pas avec le bac à sable le dit (`presentation_render_sandbox_unavailable`), jamais de relance silencieuse sans bac à sable. |
| **L'export est un geste de l'utilisateur ; le cerveau ne le fait que sur sa demande.** | Routes de Core + relais du Control Center pour la page ; depuis la Slice 21, `remotion_export` (serveur `jarvis-remotion`, [remotion-runtime.md](remotion-runtime.md) §13) appelle les MÊMES routes, seulement dans un tour adressé de l'utilisateur (attesté), `job_id` lu dans `remotion_status`, aucun `authorised_boards`, aucun réglage hors de la liste fermée `scene_id` / `frame_start` / `frame_end` / `frame` / `scale` / `crf`. Les budgets de `jarvis-presentation` et `jarvis-workspace` sont inchangés ; les agents lisent les dérivés par `artifact_search` / `artifact_get` comme avant. |

### PDF : évaluation et décision

Un PDF **de pages-images** est livré, parce qu'il est bon marché et honnête : une image JPEG rendue par page demandée (`settings.frames`, 1 à 24 images distinctes), assemblée par un écrivain PDF 1.4 d'une soixantaine de lignes (`jarvis/domain/presentation_render_output.py`, déterministe : aucune date, aucun identifiant, mêmes pages = mêmes octets). Page = taille de l'image à 96 ppp. Ce **n'est pas** un document : pas de texte sélectionnable, pas de calques, pas de lien ; le dictionnaire `Info` le dit (« Flat export ... not editable ») et le dérivé porte `render_flat`. Un PDF « vectoriel » ou textuel d'une scène demanderait que la scène soit écrite pour l'impression : hors périmètre.

## 2. Du paquet à l'Artifact : le chemin d'un export

1. **Demande** (`POST .../render/jobs`, [§8](#8-routes)) : `{snapshot_id, format, settings}` pour un snapshot déjà figé, ou `{presentation_id, variant_id, expected_*_revision, authorised_boards, format, settings}` : Core **fige d'abord** (`PresentationPackager.freeze` : révisions exactes sinon `presentation_studio_stale_revision`, liste blanche de Boards obligatoire, rejouable : les mêmes révisions retombent sur le même snapshot) puis rend **ce** snapshot.
2. **Validation avant de rien créer** : verrou des rendus, format et réglages (clés fermées), capacité `ready`, Node + `@remotion/bundler` + `@remotion/renderer` présents, navigateur trouvé, snapshot relu et vérifié, scène choisie, réglages résolus contre la composition déclarée, moteur installé = moteur du gel (`presentation_render_engine_mismatch` sinon), doublon (rendu en cours ou existant rendu tel quel), place réservée (`queue_full` sinon). Un refus ne crée **aucun** Artifact (testé). Pour un **export** (figer puis rendre), la file et le moteur (versions de Remotion des scènes de la variante) sont vérifiés **avant** de figer : un export refusé ne laisse aucun snapshot.
3. **Création** : `PresentationArtifacts.begin_render` crée le dérivé `pending` avec la relation `rendered_from` **dans sa transaction de création** et les réglages résolus en métadonnées ; il est lié au Board actif comme tout Artifact. Le Board le montre « En cours ».
4. **Rendu** (un travail à la fois) : paquet relu de nouveau, source **revalidée** par les gardes d'isolation d'aujourd'hui (`presentation_render_source_refused` si un paquet intact ne passe plus une garde plus récente), dossier de travail matérialisé, processus isolé ([§4](#4-isolation-du-processus-de-rendu)).
5. **Vérification** du fichier produit : MP4 par le `ffprobe` **épinglé** de la capacité (un seul flux H.264, dimensions, nombre d'images, durée), image par signature et dimensions du PNG, PDF par en-tête et nombre de pages ; trop gros (> 512 Mio) ou incohérent : `presentation_render_output_invalid` / `output_too_large`.
6. **Écriture** par le spool d'`ArtifactService` (`.partial`, `fsync`, renommage), métadonnées de fin, puis `finalize` (`complete`, taille mesurée, largeur, hauteur, durée). **Aucun octet final n'existe avant un fichier vérifié.**
7. **Nettoyage** : tout le dossier du travail est effacé sauf `job.json`, `render.log`, `result.json`, `egress.json` (traces de quelques Kio).

## 3. Réglages, résolution, bornes

Clés **fermées** (`settings`), types stricts ; une clé qui ne s'applique pas au format est refusée (`presentation_render_invalid`).

| Clé | Formats | Sens | Défaut |
| --- | --- | --- | --- |
| `scene_id` | tous | scène du snapshot (`pss_...`) ; obligatoire s'il y a plusieurs scènes Remotion | l'unique scène |
| `frame_start`, `frame_end` | mp4 | plage d'images **incluse** dans la durée déclarée | toute la scène |
| `frame` | still | image fixe | 0 |
| `frames` | pdf | 1 à 24 images distinctes, une page chacune | `[0]` |
| `scale` | tous | échelle de sortie : 0,25 · 0,5 · 1 · 1,5 · 2 | 1 |
| `crf` | mp4 | qualité H.264, 16 à 35 | 23 |
| `concurrency` | tous | onglets de rendu, 1 à 2 (**ne change pas les pixels** : hors de l'identité du rendu) ; chaque onglet pèse plusieurs centaines de Mo de Chrome, et pixels de sortie × onglets est borné à 3 840 × 2 160 (un onglet en 4K, ou deux en 1080p) | 1 |

Fixes, repris du manifeste : cadence (`fps`), largeur, hauteur, identifiant de composition. Fixes, de ce module : codec `h264`, format de pixel `yuv420p`, image PNG (image fixe) ou JPEG qualité 90 (pages de PDF). **Déterminisme** : `render_settings_sha256` est le SHA-256 du JSON canonique des réglages **résolus** + empreinte de la source du pin + version du moteur + empreinte du verrou ; les mêmes réglages sur le même snapshot donnent le même hash, et (mesuré) les mêmes octets pour une image fixe. Un MP4 est reproductible à l'image près, **pas** garanti octet pour octet entre deux encodeurs ou deux machines.

| Borne | Valeur | Où |
| --- | --- | --- |
| images d'un MP4 | 3 600 | `MAX_RENDER_FRAMES` ; au-delà : rendre par plages |
| pages d'un PDF | 24 | `MAX_PDF_PAGES` |
| taille de sortie | 3 840 × 2 160 au plus (dimensions d'un MP4 : paires) | `MAX_OUTPUT_WIDTH` / `HEIGHT` |
| fichier produit | 512 Mio | `MAX_OUTPUT_BYTES` |
| dossier d'un travail | 2 Gio (tué au-delà : `job_too_large`) | `MAX_JOB_DIR_BYTES`, mesuré toutes les 2 s |
| disque libre | 1,5 Gio avant de commencer (`disk_low`, HTTP 507) ; moins de 64 Mio pendant (`disk_full`, arbre tué) | `MIN_FREE_BYTES` |
| délai | 300 s + 1 s par image, plafonné à 3 600 s (`timeout`, arbre tué, la limite est dite) | `TIMEOUT_*` |
| travaux actifs | 1 en cours + 7 en attente = 8 non terminés, réservations en vol comprises | `CONCURRENCY_LIMIT`, `MAX_ACTIVE_JOBS` |
| rétention | par snapshot, les 20 rendus les plus récents gardent leurs fichiers ; au-delà, le payload d'un rendu `failed` ou `partial` est retiré du disque (l'enregistrement reste) ; un rendu `complete` n'est jamais retiré | `KEEP_RENDERS_PER_SNAPSHOT` |
| travaux gardés en mémoire | les 20 derniers terminés ; l'Artifact est la trace durable | `KEEP_FINISHED` |

## 4. Isolation du processus de rendu

Ce qui s'exécute : `node --require render-guard.cjs render-host.cjs spec.json` (cwd = le dossier `work/` du travail, `--max-old-space-size=2048`). Node ne lance **jamais** le code de la scène : il empaquette (`@remotion/bundler`, qui transforme du texte) puis pilote le navigateur ; **le code de la scène tourne dans le navigateur**, la frontière est donc celle du navigateur, que le garde configure.

| Couche | Ce qu'elle fait | Prouvé par |
| --- | --- | --- |
| **Environnement** | liste blanche (`process_tree.clean_env`) **sans** variable de proxy ; seules variables ajoutées : `JARVIS_RENDER_DIR`, `JARVIS_RENDER_RUNTIME`, `JARVIS_RENDER_BROWSER` ; `TEMP`/`TMP`/`TMPDIR` pointent le dossier du travail (le profil du navigateur y vit et y meurt). Aucun jeton, aucune clé, aucune route de Core, aucune base. | `test_the_process_gets_an_allow_listed_environment...` |
| **Dossier** | la source figée exacte (chemins `safe_relative`, aucun lien) + deux fichiers générés ; rien de la bibliothèque, d'un Board ni de la source vivante. | `test_prepare_*`, `test_the_plan_reads_nothing_but_the_package` |
| **Garde Node** (`render-guard.cjs`) | `listen` TCP forcé sur la boucle locale ; aucune connexion sortante hors boucle locale, aucun DNS hors `localhost`, aucun UDP ; **aucun processus enfant** sauf (a) les binaires sous `<runtime>/node_modules` (esbuild du bundler, compositeur Remotion/ffmpeg), comparés par **chemin réel**, et (b) le navigateur choisi (chemin exact), plus l'arrêt de ce navigateur par `taskkill /pid <son pid> /T /F` ; tout refus est compté. | `tests/unit/test_render_guard.py` (vrai Node) |
| **Bac à sable de Chrome conservé** | le garde **retire** `--no-sandbox` et `--disable-setuid-sandbox` (sauf `JARVIS_REMOTION_RENDER_NO_SANDBOX=1`). Mesuré avec `chrome://sandbox` dans le navigateur lancé exactement comme un rendu : processus Renderer `Lockdown` / intégrité `Untrusted`, GPU `Limited`, Storage `Lockdown` (le service réseau reste « Not Sandboxed » : défaut de Chrome sous Windows) ; avec l'opt-out : tous « Not Sandboxed ». Un rendu complet réussit avec le bac à sable actif sur ce poste. Si Chrome ne démarre pas avec le bac à sable : `presentation_render_sandbox_unavailable` avec la marche à suivre, jamais une relance sans bac à sable. | `sandbox-probe.json`, `test_the_process_sandbox_flags_are_stripped_by_default`, harnais `sandbox` |
| **Liste blanche des arguments finaux** | les arguments du navigateur, une fois réécrits, sont comparés à une liste blanche (ceux que Remotion 4.0.534 pose + ceux du garde). Un argument inconnu (une version future de Remotion, `--disable-web-security`, `--ignore-certificate-errors`, un autre proxy...) **refuse le lancement** : `presentation_render_guard_unexpected_args` (fail-closed). Après le rendu, un lancement du navigateur non enregistré par le garde (`browser_launches` < 1, pas de proxy) rend le travail `presentation_render_guard_not_applied` même si un fichier existe. | `test_an_argument_this_guard_does_not_know_refuses_the_launch_fail_closed` |
| **Un seul navigateur, des binaires épinglés** | seuls sont lançables le navigateur choisi (chemin exact), `@remotion/compositor-*` (ffmpeg compris) et `esbuild` / `@esbuild/*` ; un Chrome Headless Shell téléchargé par Remotion sous `node_modules/.remotion/` n'en fait pas partie. | `test_only_the_chosen_browser_may_be_launched...` |
| **Arguments du navigateur réécrits** | Remotion lance Chrome avec `--no-proxy-server`, `--proxy-server='direct://'`, `--proxy-bypass-list=*` (tout est direct) et ne permet pas d'ajouter d'argument : le garde les **remplace** au lancement par `--proxy-server=http://127.0.0.1:<proxy de refus>`, `--proxy-bypass-list=<-loopback>` (la boucle locale n'est plus exemptée : le navigateur ne joint ni Core, ni le Control Center, ni un autre service local), `--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1`, `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`. Le navigateur ne peut pas démarrer avant le proxy. | `test_the_browser_arguments_are_rewritten...` |
| **Proxy de refus** (dans le processus Node) | ne laisse passer que `localhost\|127.0.0.1:<port du serveur de rendu>` ; tout le reste (autre port local, Internet, `CONNECT`) reçoit 403 et est **compté** dans `egress.json` (jamais un échec silencieux) ; le compte est enregistré sur le dérivé (`render_egress_denied`, le navigateur lui-même tente des requêtes de fond, comptées aussi). | `test_the_denial_proxy_...`, harnais « hostile » |
| **Revalidation de la source** | gardes statiques de la Slice 06 relancées sur les octets du paquet à chaque rendu. | `test_the_frozen_source_is_revalidated_by_todays_guards` |
| **Limites** | délai, taille du dossier, disque, un seul rendu ; annulation = arbre tué après contrôle d'identité (`pid:heure`) ; un Node tué seul laisse un Chrome orphelin que le **balayage** (identifiant unique du travail dans la ligne de commande) achève. | harnais « cancel / kill » |

**Mesuré dans un vrai Chrome** (harnais, scènes hostiles du corpus de la Slice 06, version évasive : `fetch`, XHR, WebSocket, `sendBeacon`, `Image`, CSS `url()`, `<link rel=preconnect>`, WebRTC) : avec le garde, le puits HTTP local reçoit **0** requête, le puits TCP **0** connexion, le puits UDP **0** paquet, les scènes se rendent normalement ; **contrôle négatif** (mêmes scènes, arguments du navigateur laissés tels que Remotion les pose) : les trois puits reçoivent du trafic (16 requêtes, 2 connexions, 3 paquets sur la dernière exécution) : le harnais voit une fuite quand il y en a une. Le canal `dns-prefetch`/`preconnect`, **ouvert** dans le Player ([remotion-isolation.md](remotion-isolation.md) § 9), est **fermé** ici (résolution refusée, connexion par le proxy).

**Non couvert** : un code non JavaScript ou un module natif dans le processus Node (le garde est JavaScript) ; une faille du navigateur (le rendu n'est exactement aussi isolé que Chrome) ; **le processus tourne avec les droits de l'utilisateur sur ses fichiers** (pas d'utilisateur ni de Job Object dédié : un navigateur compromis pourrait lire ou écrire des fichiers de l'utilisateur ; il n'a aucun secret de Jarvis ni accès réseau) ; avec le bac à sable de Chrome actif (défaut), une faille du navigateur doit d'abord s'échapper de ce bac à sable ; avec `JARVIS_REMOTION_RENDER_NO_SANDBOX=1` il n'y en a plus (choix explicite, à ne faire que sur un poste où le bac à sable ne peut pas démarrer) ; une scène peut **lire** les fichiers qu'elle a reçus (`public/`, `public/live/`) et les props : ne jamais mettre dans une scène plus que ce qui peut sortir sur une diapositive.

## 5. Un travail : états, progression, annulation

États : `queued` → `running` → `finalizing` → `complete` ; ou `failed` / `cancelled` (terminaux). **Un état terminal n'apparaît qu'une fois le dérivé lui-même terminal** (qui lit `cancelled` lit un dérivé déjà `failed`). La vue (`GET .../jobs/{job_id}`) : `job_id`, `artifact_id`, `snapshot_id`, `state`, `phase`, `format`, `scene_id`, `frames_done`, `frames_total`, `percent`, `created_at`, `started_at`, `elapsed_s`, `timeout_s`, `queue_position`, `cancel_requested`, `can_cancel`, `error_code`, `error_detail`, `size_bytes`, `browser`, `settings`, `settings_sha256`, `egress_denied`, `verified_by`, `sandbox` (le bac à sable de Chrome était-il actif), `deduplicated` (vrai : la demande a rendu un travail en cours ou un rendu existant identique), `log_tail` (les 4 dernières lignes, seulement après un échec ; sans chemin de la machine). Phases : `queued`, `preparing`, `bundling`, `opening_browser`, `selecting_composition`, `rendering`, `encoding`, `verifying`, `storing`, `complete`, `failed`, `cancelled`.

- **Annuler** (`POST .../cancel`) : en file, le travail est retiré et son dérivé passe `failed` (`presentation_render_cancelled`) **avant** la réponse ; en cours, la réponse dit `cancel_requested` et l'arbre de processus est tué (mesuré : 1,0 à 1,3 s) ; en `finalizing` ou terminé : `presentation_render_not_cancellable`.
- **Un échec n'est pas une erreur HTTP** : c'est la vue du travail et le dérivé `failed` avec le même code. Aucun fichier final n'existe pour un dérivé `failed` ; un `.partial` éventuel reste sur disque comme preuve et n'est **jamais promu**.
- **Mémoire de Core** : les 20 derniers travaux terminés ; après un redémarrage, la trace durable est l'Artifact dérivé (état, code d'erreur, réglages, relation).

### Reprise après un arrêt (Core tué, poste éteint)

Au démarrage, **avant** tout rendu, le Core prend le verrou `render/core.lock` ; si un autre Core **vivant** le tient, celui-ci ne reprend, ne tue et n'efface rien (les rendus de l'autre Core ne sont pas des orphelins) et refuse les demandes (`presentation_render_locked`). Sinon (`PresentationRenderService.reconcile`, appelé par `v2_app` juste après `ArtifactService.recover_pending(owned=...)`, qui laisse ces dérivés à leur propriétaire) : pour chaque `job.json` non terminal, un processus de rendu resté vivant est tué (identité `pid:heure` contrôlée, jamais un autre programme), le balayage achève ce qui porte l'identifiant du travail, le dossier est effacé ; puis chaque dérivé `pending` d'une vie précédente devient `failed` (`presentation_render_interrupted`), ou `partial` (`artifact_recovered`) **seulement si** son fichier final existait déjà (renommage fait, base pas à jour : complet mais **non vérifié**, et dit tel). Un `.partial` n'est jamais promu à l'aveugle. À l'arrêt normal de Core : plus de demande, le rendu en cours est annulé (arbre tué), les travaux en file échouent `interrupted`.

## 6. L'Artifact dérivé

| Élément | Valeur |
| --- | --- |
| Kind, fichier, type MIME | `presentation_video` `render.mp4` `video/mp4` · `presentation_still` `still.png` `image/png` · `presentation_pdf` `render.pdf` `application/pdf` |
| Relation | `rendered_from` → le snapshot (une seule, posée dans la transaction de création, immuable, sans cycle) |
| Colonnes | `width`, `height`, `duration_ms` (MP4 : durée mesurée par ffprobe), `size_bytes` mesuré, `error_code` si `failed` |
| Métadonnées (scalaires plats, au plus 32 clés, figées à l'état terminal) | `render_format`, `render_job_id`, `render_scene_id`, `render_prefab_id`, `render_prefab_version`, `render_composition`, `render_source_digest`, `render_fps`, `render_width`, `render_height`, `render_scale`, `render_image_format`, `render_engine`, `render_engine_lock_sha256`, `render_engine_drift`, `render_settings_sha256`, `render_flat`, `render_sandbox`, MP4 : `render_codec`, `render_pixel_format`, `render_crf`, `render_frame_start`, `render_frame_end` ; image et PDF : `render_frames` ; PDF : `render_pages` ; à la fin : `render_output_sha256`, `render_verified_by` (`ffprobe` \| `header` \| `png` \| `pdf`), `render_browser`, `render_egress_denied`, `render_wall_ms` |

`render_engine_drift` : le verrou installé diffère de celui du gel, à version égale (consigné, pas refusé, comme la compilation). Une **version** de Remotion différente de celle du gel est refusée. `render_verified_by: header` : le `ffprobe` épinglé manquait, seul l'en-tête a été contrôlé (dit, jamais présenté comme une vérification complète). Les valeurs par défaut des propriétés sont **figées dans le paquet** (`prefabs[].props_defaults`, ajouté au gel par cette Slice) ; un snapshot plus ancien, sans cette clé, se rend avec les seules valeurs d'instance de la scène.

Données vivantes de Board : les copies figées au gel (`live/`) sont déposées sous `public/live/<nom><ext>` du dossier de travail (le préfixe statique de [presentation-live-refs.md](presentation-live-refs.md)). Le **message `props`** qui annonce ces données à la scène n'existe pas encore côté Player (Slice 10 : « non fait ») : un rendu ne l'invente pas.

## 7. Réglages d'environnement

| Variable | Rôle |
| --- | --- |
| `JARVIS_REMOTION_RENDER_NO_SANDBOX` | seule valeur qui compte : `1`. Laisse à Chrome les arguments `--no-sandbox` / `--disable-setuid-sandbox` que pose Remotion : le bac à sable du processus de Chrome n'existe plus pour ce rendu (`render_sandbox: false` sur le dérivé). À utiliser seulement si `presentation_render_sandbox_unavailable` est dit pour ce poste. |
| `JARVIS_REMOTION_RENDER_BROWSER` | chemin d'un Chrome ou Edge à utiliser. S'il est posé et n'existe pas : aucun navigateur (jamais un autre à la place). Sinon : Chrome sous `Program Files` / `Program Files (x86)` / `LocalAppData`, puis Edge ; macOS : Chrome ; Linux : `google-chrome`, `chromium`. La version est lue **sans lancer** le navigateur (dossier `<version>/` d'une installation Windows) : `--version` s'adresserait à la session ouverte de l'utilisateur. |

Données : les travaux vivent sous `<racine de données>/local_capabilities/remotion/runtime/render/jobs/<job_id>/` ([local-data.md](local-data.md)) ; rien dans le dépôt, aucune base, aucun schéma (`jarvis.sqlite3` reste v8).

## 8. Routes

Préfixe frère de la famille des capacités : `/v1/local-capabilities/remotion/render` (aucune route commune avec `/v1/local-capabilities/{capability_id}/{operation}` : les travaux sont sous `/jobs`, au moins quatre segments), jeton porteur de Core obligatoire. Code : `jarvis/protocol/presentation_render_routes.py`, `jarvis/core/presentation_render_service.py`.

| Méthode | Route | Corps | Réponse |
| --- | --- | --- | --- |
| GET | `/v1/local-capabilities/remotion/render` | — | `{render: {ready, reason, browser, concurrency, max_jobs, active_jobs}}` (lecture seule, ne lance rien) |
| GET | `/v1/local-capabilities/remotion/render/jobs` | — | `{jobs: [vue]}` |
| POST | `/v1/local-capabilities/remotion/render/jobs` | `{format, settings?, snapshot_id}` ou `{format, settings?, presentation_id, variant_id, expected_presentation_revision, expected_variant_revision, authorised_boards?}` | 202 `{job: vue}` |
| GET | `/v1/local-capabilities/remotion/render/jobs/{job_id}` | — | `{job: vue}` |
| POST | `/v1/local-capabilities/remotion/render/jobs/{job_id}/cancel` | `{}` | `{job: vue}` |

Pourquoi des routes d'abord : l'export est une **action de l'utilisateur** qui lance un processus et écrit un Artifact ; les budgets d'outils des serveurs MCP internes sont contractuels (le verbe du cerveau vit dans le serveur séparé `jarvis-remotion`, Slice 21). Le gel (`authorised_boards`) passe par la même route : sans liste, aucun Board n'est lu (refus par défaut). Corps de plus de 8 Kio, champ en trop, paramètre de requête : `presentation_render_invalid`.

| Code | HTTP | Cause |
| --- | --- | --- |
| `presentation_render_invalid` | 400 | corps, réglage, plage ou format invalide |
| `presentation_render_unknown_job` | 404 | identifiant inconnu de ce Core (au-delà des 20 derniers terminés, lire l'Artifact) |
| `presentation_render_unknown_scene` | 404 | scène absente du snapshot, ou plusieurs scènes sans `scene_id` |
| `presentation_render_unavailable` | 503 | Core sans service de rendu (aucun magasin de capacités) ou en arrêt |
| `presentation_render_runtime_unavailable` | 409 | capacité non `ready`, Node, `@remotion/bundler` ou `@remotion/renderer` manquants : installer ou réparer |
| `presentation_render_browser_unavailable` | 409 | aucun Chrome ni Edge (jamais téléchargé) |
| `presentation_render_snapshot_invalid` | 409 | snapshot inconnu, pas un snapshot, non `complete`, paquet falsifié ou illisible |
| `presentation_render_source_refused` | 409 | la source figée ne passe plus les gardes d'isolation d'aujourd'hui |
| `presentation_render_engine_mismatch` | 409 | version de Remotion installée ≠ version du gel |
| `presentation_render_not_cancellable` | 409 | travail terminé ou en `finalizing` |
| `presentation_render_queue_full` | 429 | 8 travaux déjà en cours ou en attente (réservations en vol comprises) |
| `presentation_render_locked` | 409 | un autre Core vivant tient le verrou des rendus de cette racine de données |
| `presentation_render_disk_low` | 507 | moins de 1,5 Gio libres avant de commencer |
| `presentation_render_store_failed`, `presentation_render_internal_error` | 500 | disque ou défaut inattendu (journalisé durablement, niveau `error`) |

Codes d'**échec d'un travail** (dans la vue et sur le dérivé, pas des erreurs HTTP) : `presentation_render_sandbox_unavailable` (Chrome n'a pas démarré avec son bac à sable : le détail dit l'opt-out), `presentation_render_guard_unexpected_args` (argument de lancement inconnu du garde : refusé), `presentation_render_guard_not_applied` (aucun lancement réécrit enregistré), `presentation_render_failed` (processus terminé en échec ; `error_detail` et `log_tail` disent pourquoi), `_crashed` (le processus s'est effondré), `_composition_mismatch` (la composition rendue n'est pas celle que le manifeste déclare), `_timeout`, `_disk_full`, `_job_too_large`, `_output_invalid`, `_output_too_large`, `_cancelled`, `_interrupted` (Core ou poste arrêté), ainsi que les codes de refus ci-dessus survenus après la demande (`_source_refused`, `_snapshot_invalid`, `_disk_low`). Les codes des registres traversés par un gel (`presentation_studio_stale_revision`, `live_ref_*`, `snapshot_package_*`, `artifact_*`) sont rendus tels quels.

## 9. Control Center

Cinq adresses relaient **telles quelles** vers Core (`jarvis/runtime/presentation_render_relay.py`), toutes gardées par Host et origine de boucle locale (préfixe `/api/local-capabilities`) : `GET /api/local-capabilities/remotion/render`, `GET` et `POST /api/local-capabilities/remotion/render/jobs`, `GET /api/local-capabilities/remotion/render/jobs/{job_id}`, `POST /api/local-capabilities/remotion/render/jobs/{job_id}/cancel` (cinq routes, un délai de 60 s pour la création, 40 s pour l'annulation, 10 s pour les lectures). Rien d'autre n'est relayé (aucune installation, aucun chemin libre).

Dans la vue **Artefacts** d'un Board (`control_center_workspace.js`), chaque copie figée **Remotion** `complete` propose « Exporter cette copie » (MP4, image, PDF). Ce qui attend se voit : « Export MP4 en cours — Rendu des images · 12/60 images (20 %) · 8 s écoulées · délai 6 min au plus », compteur vivant, **Annuler l'export**, numéro dans la file ; l'état est relu de Core chaque seconde tant que la vue est ouverte (la fermer arrête l'interrogation, la rouvrir la reprend) ; un échec dit son **code** et son détail ; trois lectures d'état ratées de suite sont dites (`export_lost`), jamais avalées ; à la fin la liste des rendus est **relue du serveur**. L'état d'un export vit dans Core, pas dans la page : à chaque lecture des présentations d'un Board, les travaux non terminés sont lus (`GET .../render/jobs`) et leur suivi reprend (page rechargée, panneau rouvert, export lancé depuis PowerShell), le compteur repartant des secondes écoulées de Core ; une demande identique à un rendu existant dit « rendu identique déjà existant, rien n'a été refait ». **Un rendu de plus de 8 Mio** (image 4K, PDF) s'ouvre aussi : une balise `<img>` ou un lien n'envoie pas de `Range` et Core refuse de rendre plus de 8 Mio d'un bloc ; le relais du Control Center lit alors le payload par plages de 8 Mio et l'écrit au navigateur au fur et à mesure (`Content-Length` annoncé, jamais plus d'un bloc en mémoire, borné à 1 Gio ; une panne en route ferme la connexion : fichier tronqué visible, jamais présenté comme complet). Les requêtes `Range` (vidéo, lecteur PDF) passent inchangées. Chaque rendu montre ses dimensions, sa durée, sa scène, l'empreinte de ses réglages en infobulle, la mention « export à plat : non éditable, l'origine éditable est la source ci-dessus », et un **aperçu** (image paresseuse, vidéo `preload="none"` : rien n'est lu avant le geste, lien « Ouvrir le PDF »). L'origine reste l'arbre **source → copie figée → rendus** de la Slice 08 avec « Ouvrir la source » / « Ouvrir la variante ».

## 10. Journal

Chaque étape normale est journalisée (`core.presentation_render.queued`, `.started`, `.complete`, `.cancel_requested`), chaque échec aussi (`.failed` niveau `error`, `.cancelled` niveau `warning`, `.internal_error`, `.fail_artifact_refused`, `.record_failed`, `.reconcile_failed`, `.orphan_unkillable`, `.reconciled`). Les routes journalisent un refus (`presentation_render.route_failed`) ; le relais, chaque écriture (`presentation_render.relayed`, jamais un corps).

## 11. Preuves

Harnais `scripts/remotion_render_harness.py` : vrai registre SQLite, vrai Studio de fichiers, vrai `PrefabService`, vrai `PresentationPackager`, vrai `RemotionRenderRunner`, vrai Node, Remotion 4.0.534, Chrome installé, racine de données privée (jamais le JARVIS vivant, aucune route de Core appelée), runtime privé (jonction `node_modules` vers l'installation de la Slice 06, **aucune installation de plus**). Sortie : `tasks/jarvis-remotion-presentation-integration/slices/16-render-export-and-derived-artifacts/evidence/real-render.json` (tête du dépôt, versions de Node et de Chrome, chaque vérification avec ses valeurs, durées, espace disque avant et après).

| Scénario | Ce qui est prouvé |
| --- | --- |
| `happy` | MP4 (60 images), image fixe, PDF de trois pages d'une scène gelée : ffprobe **indépendant** du runner (h264, 1280×720, 30 fps, 60 images, 2,0 s), PNG 1280×720, PDF à trois pages, empreinte du payload = celle enregistrée, relation `rendered_from`, réglages en métadonnées, même snapshot + mêmes réglages = même hash de réglages et mêmes octets d'image, une autre image = d'autres pixels, aucun dossier ni processus restant |
| `cancel_and_kill` | annulation en cours de rendu (arbre entier mort en ~1 s, dérivé `failed` `cancelled`, aucun fichier final) ; une référence `pid:heure` fausse ne tue pas le programme qui a réutilisé le pid ; processus tué de l'extérieur (arbre) ; Node seul tué (Chrome orphelin **balayé**) ; la file fonctionne ensuite |
| `core_death` | un processus « Core » séparé demande un rendu lent, est tué (`taskkill /F` sans `/T` : le rendu lui survit, orphelin) ; un nouveau service lit le registre : dérivé encore `pending`, `recover_pending` le laisse à son propriétaire, `reconcile` tue l'orphelin, dérivé `failed` `interrupted`, aucun fichier final ; un nouveau rendu réussit |
| `refusals` | snapshot inconnu, artefact qui n'est pas un snapshot, format, réglage inconnu, image hors de la scène, plage inversée, réglage hors format, `snapshot.zip` falsifié (un octet), moteur installé différent, capacité non installée, travail inconnu : chacun un code stable et **aucun dérivé créé** ; source modifiée après le gel : l'export de l'ancienne révision est `stale_revision` (rien de figé), le rendu de l'ancien snapshot reste valide et le Board dit `stale: true` avec son rendu |
| `bounds` | disque libre insuffisant avant (`disk_low`), disque qui se remplit pendant (arbre tué, `disk_full`), dossier trop gros (`job_too_large`), délai (`timeout`, limite dite) |
| `sandbox` | `chrome://sandbox` dans le navigateur lancé **exactement comme un rendu** : bac à sable actif par défaut (Renderer `Lockdown` / `Untrusted`), « Not Sandboxed » avec l'opt-out (la sonde voit la différence) ; un navigateur qui ne démarre pas : `sandbox_unavailable` (bac à sable actif) ou `browser_unavailable` (opt-out), jamais de relance sans bac à sable ; fichier `sandbox-probe.json` |
| `burst` | 40 demandes simultanées : 8 acceptées, 32 `queue_full`, aucun dérivé pour un refus ; une demande identique rend le travail existant (`deduplicated`) ; tout termine après les annulations |
| `two_cores` | un second Core, pendant que le premier rend : il ne tue, ne reprend ni n'efface rien (`locked: true`), refuse de rendre (`presentation_render_locked`) ; le premier mort, le verrou est repris et l'orphelin récupéré |
| `hostile` | scènes hostiles : 0 requête / 0 connexion / 0 paquet aux puits ; dénis comptés et enregistrés ; source refusée à la relecture si une garde plus récente existe ; contrôle négatif (voir [§4](#4-isolation-du-processus-de-rendu)) |

Mesures de la dernière exécution (Windows 11 10.0.26200, Node v24.18.0, Chrome 154.0.8037.99, Remotion 4.0.534, machine partagée donc **chargée par moments** : l'exécution précédente a mesuré 102,6 s pour le même MP4) : MP4 de 60 images 1280×720 13,8 s, image fixe 8,3 s, PDF de 3 pages 8,8 s, annulation en cours de rendu jusqu'à l'arbre mort 1,3 s ; disque libre 17 618 Mo avant, 17 577 Mo après.

Test de bout en bout opt-in `tests/unit/test_presentation_render_real.py` (un second test rend une image 4K de bruit de plus de 8 Mio et l'ouvre entière par le relais, sans `Range`, comme le fait un lien du Board) (`JARVIS_REMOTION_RUNTIME_DIR`) : vrai Core + vrai Control Center + vrai Chrome qui **clique « Exporter »** pour une image, un MP4 et un PDF, suit l'état à l'écran, vérifie l'aperçu (image 1280×720 chargée, vidéo 1280×720 de 3,0 s, PDF servi avec `application/pdf`), l'absence de débordement et de log d'erreur, puis le registre. Captures : `evidence/s16-board-*.png`.

Tests automatiques (aucun navigateur, aucun réseau) : `test_presentation_render_domain.py` (réglages, bornes, métadonnées, PDF, plan de la source), `test_presentation_render_service.py` (file, états, annulation, reprise, refus), `test_presentation_render_runner.py` (vrais processus enfants, disque réel), `test_render_guard.py` (le garde sous un vrai Node), `test_presentation_render_routes.py` (vrai Core, vrai registre), `test_presentation_render_relay.py`, `test_workspace_presentations_js.py` (interface, par node), `test_presentation_render_docs.py` (ce document contre le code).

Rejouer la preuve (hors profil vivant) : `python scripts/remotion_render_harness.py --work-dir <dossier court sous Temp> --runtime-dir <racine>/local_capabilities/remotion/runtime --evidence <fichier.json>` (≈ 6 minutes sur une machine chargée, ≈ 500 Mo de disque consommés au plus pendant les rendus, nettoyés ensuite). Verdict `PASSED` attendu.

## 12. Limites et risques résiduels

- **Une scène par export** : un snapshot de plusieurs scènes se rend scène par scène ; aucune concaténation en une vidéo (les cadences peuvent différer, les assets de `public/` de plusieurs scènes se heurteraient). À assembler hors de Jarvis ou par une Slice ultérieure.
- **Chrome installé, version non épinglée** : le navigateur est celui de l'utilisateur (testé : Chrome 154.0.8037.99 avec Remotion 4.0.534, mode `chrome-for-testing`) ; une autre version peut rendre des pixels légèrement différents. Edge n'a pas été exercé.
- **Windows seul éprouvé en réel** ; POSIX est couvert par la logique (groupe de processus, `pgrep`) et les tests unitaires, non exécuté.
- **Le processus de rendu a les droits de l'utilisateur sur ses fichiers** (§4) ; le bac à sable de Chrome est actif par défaut (sauf opt-out explicite) mais le service réseau de Chrome tourne hors bac à sable sous Windows ; un code natif échappe au garde Node.
- **Le proxy de refus compte aussi le bruit propre au navigateur** (mises à jour, services Google : 10 à 30 refus par rendu même pour une scène honnête) : `render_egress_denied` > 0 ne signifie pas qu'une scène a tenté de sortir ; le **contenu** des refus est dans `egress.json` (jusqu'à 20 cibles distinctes, tant que le travail n'est pas purgé).
- **Un MP4 n'est pas reproductible octet pour octet** entre deux machines ; les réglages le sont.
- **Mémoire** : le paquet est relu en mémoire (jusqu'à 64 Mio) à la demande **et** au rendu ; Chrome consomme plusieurs centaines de Mo par onglet (défaut 1, au plus 2, pixels × onglets bornés à une image 4K) ; un seul rendu à la fois.
- **Données vivantes de Board** : copiées sous `public/live/` mais non annoncées à la scène (aucun message `props` côté Player pour l'instant).
- **Licence Remotion** non examinée ici (contrat distinct, [local-capabilities.md](local-capabilities.md) §6) ; le rendu ne déclare aucune licence.
- **Les travaux terminés ne survivent pas en mémoire à un redémarrage** : l'Artifact dérivé, lui, oui ; l'interface relit l'état des travaux en cours seulement tant que la vue est ouverte.
- **Pas d'outil vocal ni de commande de présentation** pour exporter : voix et Tool Brain sont les Slices 20-21.
