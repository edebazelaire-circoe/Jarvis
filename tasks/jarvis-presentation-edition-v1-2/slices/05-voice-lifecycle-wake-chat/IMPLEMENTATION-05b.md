# Slice 05b — Notes d'implémentation (mot de réveil vocal dans les builds internes, HD-V12-01)

Branche `wt/v12-s05b` (worktree `pev12d`), depuis `76ed387e` (Slice 05 + branche de tâche V1.2 avec la V1 fusionnée).
Suite de la QA M1 de la Slice 05 (« Travail de packaging à faire » de `IMPLEMENTATION.md`).
Commits : `40fd44d2` (canaux, build interne, défaut armé, docs, tests), `9b90236e` (texte de licence de `flatbuffers`),
puis ces notes.

## Ce qui a changé

- **Canal de build explicite** : `build_package.py build|lock --channel production|internal`. **Défaut : `production`**,
  sans openWakeWord. Le build interne s'obtient seulement par `--channel internal`. Le canal est écrit dans
  `runtime-manifest.json` (`product.channel`, `product.channel_warning`, bloc `models`), dans
  `third-party-manifest.json` (`channel`, `warning`, `channels` des composants réservés, lignes `kind: model`) et dans
  `release-info.json` (`product.channel` ; build interne : nom d'artefact `jarvis-<v>-internal-<rev>-<sha>`,
  `production_blockers`, `channel_warning`). Un manifeste sans canal (paquets V1) vaut `production`.
- **Politique de licences par canal** (`third_party_policy.json`) : section `channels` (verrous, avertissement,
  décision), entrées `channels: ["internal"]` pour les 12 roues de l'extra `wakeword` (openwakeword Apache-2.0,
  onnxruntime MIT, scipy, scikit-learn, tqdm MPL-2.0 AND MIT, joblib, narwhals, threadpoolctl, cloudpickle, colorama,
  flatbuffers, packaging), section `models` (`openwakeword-models`, CC-BY-NC-SA-4.0), et les exclusions
  `openwakeword`, `onnxruntime`, `openwakeword-models` limitées à `channels: ["production"]` (décision HV-PACKAGE-04
  gardée, `channel_decision: HD-V12-01`). `channel_policy` filtre la politique du canal construit : une roue réservée
  installée dans un build de production n'a pas d'entrée et est un exclu présent → build refusé.
- **Verrou interne** : `requirements-internal.in` → `requirements-internal.lock` (12 roues EN PLUS, SHA-256), résolu
  sous la contrainte de `requirements.lock` ; `lock --channel internal` refuse une résolution qui changerait une roue
  de la production ; `read_locks` refuse une roue verrouillée deux fois.
- **Modèles** : le build interne télécharge `melspectrogram.onnx`, `embedding_model.onnx`, `hey_jarvis_v0.1.onnx` par
  `wakeword_model_catalog.download_spec` (taille et SHA-256 du catalogue, inchangés) dans le cache du build, et les
  copie dans `<paquet>\models\wake-word` (arbre suivi par `verify`). Le produit installé les lit là :
  `catalog.default_model_dir()` → `bundled_model_dir()` en priorité (même si `JARVIS_RUNTIME_DIR` est posé). Aucun
  téléchargement au premier lancement ; `wake-word install` y dit « livrés avec ce programme, rien à installer ».
- **Avis de licence** : `licenses\openwakeword-models\NOTICE.txt` (attribution, licence par URI, « Usage interne non
  commercial ; à remplacer avant production ») ; `license_files` de la politique copie `onnxruntime/LICENSE` et
  `ThirdPartyNotices.txt` (rangés hors de `dist-info`) ; `license_text_from` reprend le texte Apache-2.0 de `requests`
  pour `flatbuffers`, dont la roue n'a aucun fichier de licence, avec un `NOTICE.txt` qui le dit. Le build refuse une
  roue réservée au canal interne sans texte de licence.
- **`verify` refuse un paquet de production** portant un composant interne (`private_runtime.channel_problems`, partagé
  avec l'installeur et `release_info`) : arbre `models\`, dossier ou `dist-info` `openwakeword`/`onnxruntime` dans
  `site-packages`, composant tiers réservé à un autre canal, canal inconnu. `scripts/verify_release.py` refuse une roue
  du verrou interne qui ne serait pas réservée au canal interne ou qui doublerait la production.
- **Sonde du build par canal** : production → `wake_word_settings.load({})` désactivé ; interne → armé
  (`openwakeword`), modèles lus dans le paquet et vérifiés, **vrai détecteur openWakeWord construit** depuis ces modèles
  et nourri de 5 trames de zéros (aucun périphérique audio), aucune détection.
- **Défaut du mot de réveil** : `wake_word_settings.baseline()` = réglage d'un profil vierge (bloc **absent**). Armé
  (`enabled: true`, `openwakeword`, `hey_jarvis`) seulement si `wake_word_install.installed_engine_ready()` (lu une fois
  par processus) ; sinon les défauts sûrs. Un bloc illisible donne toujours les défauts sûrs. L'état des Réglages dit
  « Mot d'éveil actif par défaut … Désactivez-le ici pour garder le clavier seul ».
- **Docs** : `docs/release.md` (canaux, bloquant de production **P1**, ligne P1 du tableau des portes, vérificateur),
  `docs/windows-packaging.md` (section *Channels*, manifeste, sonde, `verify`), `docs/voice-lifecycle.md` (tableau du
  défaut par poste), `third_party/README.md`, `docs/SECURITY.md` §17, `docs/OPERATIONS.md`.

### Comment les cas sont distingués (après la reprise QA)

`installed_build_ships_engine()` (anciennement `installed_engine_ready`, voir *Reprise QA*) est vrai si et seulement
si : **produit installé** (`private_runtime.package_layout()` non nul, c'est-à-dire marqueur `jarvis-product.json` à
côté du code) **et** manifeste du paquet avec un bloc `models.wake_word` (écrit seulement par le build interne).
La présence des fichiers du moteur n'entre plus dans la décision : elle est dite par l'état du moteur.

| Poste | Résultat | Profil vierge |
| --- | --- | --- |
| build interne installé | vrai | « Hey Jarvis » armé en Sleep + F9 ; moteur en panne → réglage activé, code et message dits |
| build de production installé | faux (manifeste sans `models`) | F9 seul, « Moteur absent » si l'utilisateur l'active |
| checkout de développement (édition `full` du poste) | **toujours faux** (pas de marqueur) | `DEFAULT_ENABLED = False` inchangé |

Le critère n'est jamais le réglage d'édition : un checkout avec l'extra `wakeword` et des modèles vérifiés reste en
F9 seul par défaut (prouvé par test, voir *Reprise QA*).

## Preuves

- **Build interne réel** depuis le commit propre `9b90236e`, `%TEMP%\v12s05b\pkg-internal` : sonde OK
  (`default_enabled: true`, `openwakeword`, `model_dir_in_package: true`, 3 modèles vérifiés, `OpenWakeWordEngine`,
  silence `[-1, -1, -1, -1, -1]`) ; `verify` vert (`0fa1d0b7…`, canal internal, avertissement répété) ; modèles
  présents aux SHA-256 du catalogue ; `licenses\openwakeword-models\NOTICE.txt`, `python-packages\onnxruntime\…`
  (LICENSE + ThirdPartyNotices), `openwakeword\LICENSE`, `flatbuffers\{LICENSE,NOTICE.txt}`. Premier essai refusé par
  le build lui-même (« flatbuffers: aucun texte de licence livré ») → `9b90236e`.
- **Build de production réel**, même commit, `pkg-production` : sonde OK (réveil désactivé), `verify` vert
  (`11f1e090…`, canal production), aucun `openwakeword`/`onnxruntime`/`models`, aucun composant à `channels`.
  Après y avoir planté `openwakeword\` et `models\` copiés du build interne : `verify` code 1, « production: modèles
  livrés … », « production: openwakeword présent, réservé au build interne (HD-V12-01) ».
- **Tailles** : production 442,5 Mo, 11 384 fichiers ; interne 681,3 Mo, 17 083 fichiers (+238,8 Mo : scipy 116 Mo,
  onnxruntime 46 Mo, sklearn 45 Mo, scipy.libs 20 Mo, openwakeword 0,4 Mo, modèles 3,6 Mo). Installeurs non construits.
- **Essai « produit installé » dans un bac** (dossier du paquet lancé tel quel, PATH réduit à Windows, `LOCALAPPDATA`
  et `TEMP` du bac, ports 56653-56656, visage et navigateur coupés, `JARVIS_LAUNCH_VOICE=0`, Voice jamais lancée,
  aucun micro) :
  - interne : `wake-word status --json` → `ready: true`, `package_installed: true`, 3 modèles `verified`,
    destination « dossier du programme : models/wake-word » ; `wake-word install --yes` → code 1 « rien à installer » ;
    Control Center : `GET /api/wake-word` profil vierge → `enabled: true`, `openwakeword`, `hey_jarvis`,
    `present: false`, `engine.available: true` ; `/api/voice/lifecycle` → `voice_word` configuré et disponible
    (`degraded` = clé du fournisseur absente dans le bac, attendu) ; `POST {"enabled": false}` → bloc écrit
    `enabled: false`, relu désactivé, « F9 réveille JARVIS » ; `verify` toujours vert ensuite (dossier du programme non
    écrit) ;
  - production : `status` → `package_installed: false`, modèles `wake_model_missing` ; `install` → refus d'édition ;
    profil vierge → `enabled: false`, « Aucun mot de réveil vocal n'est activé : F9 réveille JARVIS ».
- **Tests** : `test_wake_word_installed_default.py` (nouveau, 14), `test_windows_packaging.py` (87, dont canaux,
  politique, manifestes, `verify` par canal, sonde, licences), `test_release_tooling.py` (canal dans `release-info`,
  verrou interne). Balayage voisin : 26 fichiers (wake word, voice lifecycle, packaging, installeur, product setup,
  readiness, launcher, release tooling, private runtime) **988 passés, 2 ignorés** (essais live openWakeWord sans
  modèle ni clip) ; 10 fichiers de plus (app, voice composition, control center quality, release gates…) 263 passés,
  2 échecs **connus** (`tests/known_failures.json` : `test_app::…tools_gateway…`, `test_surface_reflex_policy::…`) ;
  `test_wake_word_settings_browser.py` (Chrome réel) 21/21 en deux lots (le fichier entier dépasse 10 min) ;
  `scripts/verify_release.py` vert.
- Copies : `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s05b\evidence\`
  (journaux des deux builds, manifestes des deux paquets, `NOTICE.txt`, rapports des deux essais, `verify` du paquet
  altéré, tailles). Sorties de build et bac supprimés ; aucun processus laissé.

## Check Human

- **HV-V12-VOICE-02** (proposé) : sur un poste, installer le **build interne** (`build --channel internal` puis
  `installer`), profil vierge, clé du fournisseur vocal renseignée ; la roue en veille ; dire « Hey Jarvis » → JARVIS
  passe en Active (orbe vert à la voix) ; F9 marche toujours. Puis Réglages › Voix & audio › Mot d'éveil : désactiver,
  redémarrer Voice, « Hey Jarvis » ne réveille plus, F9 oui. Vérifier dans `licenses\openwakeword-models\NOTICE.txt`
  l'avertissement non commercial.

## Non vérifié

- **Aucun vrai micro** : le réveil par la voix réelle (« Hey Jarvis » entendu, seuil, faux réveils, écho des
  haut-parleurs) n'est prouvé que par le détecteur réel nourri de silence → HV-V12-VOICE-02.
- **Pas d'installeur ni de `package_smoke.py`** sur le build interne : le paquet a été lancé depuis son dossier de build
  (même marqueur, même runtime privé, PATH réduit), pas depuis une installation par `JARVIS-Setup.exe`. La taille de
  l'installeur interne n'est pas mesurée.
- Voice n'a pas tourné dans le bac (pas de clé) : l'armement effectif du détecteur par Voice en Sleep repose sur les
  tests (`simple_wake_backends` reçoit le bloc armé et construit le détecteur openWakeWord) et sur la sonde.
- Reproductibilité du build interne (deux builds → même `package_sha256`) non mesurée.
- Observation : au démarrage, le Control Center du bac a créé un cache `claude-cli-nodejs` sous le `LOCALAPPDATA` du
  bac (sonde de la CLI externe) ; aucun processus n'est resté.
- Le cache partagé du build (`%LOCALAPPDATA%\Temp\jarvis-build-cache`) garde désormais les 12 roues internes et les
  trois modèles (~77 Mo).
- Le paquet interne contient un fichier vide `scipy-1.18.1-cp314-cp314-win_amd64.whl` à la racine de `site-packages` :
  il vient de la roue amont de scipy elle-même (suivi par l'empreinte, sans effet).

## Reprise QA (`qa/qa-report-05b.md`, HEAD `36c5fea1`)

Commit `2512f7c2`. Aucun changement de packaging : pas de rebuild.

- **MA1 corrigé** : la condition d'armement d'un profil vierge devient `wake_word_install.installed_build_ships_engine()`
  : produit installé (marqueur) **et** manifeste du paquet déclarant `models.wake_word`. Elle ne lit plus les fichiers
  du moteur. Un modèle manquant ou altéré, ou un paquet Python absent, à n'importe quel démarrage suivant : le réglage
  reste activé (`openwakeword`) ; `voice_lifecycle.wake_engine` rend `configured: true, available: false` et le code
  stable (`wake_model_missing`, `wake_model_mismatch`, `wake_package_missing`) avec son message (« … seul F9 réveille
  JARVIS ») ; la page Mot d'éveil affiche « Moteur absent » (rendu inchangé, `test_an_enabled_word_without_its_engine_says_it_does_not_listen`
  rejoué dans Chrome) ; la ligne « Voix » de la préparation ajoute ce message et ce code ; le mot vocal n'est pas armé,
  F9 l'est. Plus jamais « Aucun mot de réveil vocal n'est activé » dans ce cas. `engine_modules_present` (devenu
  inutile) est retiré. `docs/voice-lifecycle.md` › *Wake word engine* réécrit en conséquence.
  Test : `test_a_broken_engine_stays_enabled_and_says_why_it_does_not_listen[missing|altered|package]` (vrai
  `read_states` sur un paquet simulé, puis `project` et `product_readiness._voice_item`), avec un appel non mis en
  cache, c'est-à-dire un « nouveau processus ».
- **m2 corrigé** : `test_the_command_line_builds_production_unless_internal_is_asked[build|lock]` (appel de `main`
  sans `--channel` → `production`) ; `test_without_the_product_marker_engine_and_verified_models_never_arm_the_default`
  (paquet sans marqueur, paquet Python « présent », trois modèles vérifiés → jamais armé, profil vierge désactivé) et
  son pendant `test_the_same_package_with_its_marker_arms_the_default`.
  **Mutations rejouées** (fichiers restaurés par `git checkout` après chacune) sur les trois fichiers de tests de la
  Slice : M4 (`build --channel` par défaut `internal`) → 1 échec, **tuée** ; M7a (retrait de `if layout is None:
  return False`) → 2 échecs, **tuée** ; M7b (armement par les fichiers du moteur au lieu du marqueur) → 4 échecs,
  **tuée** ; retour de MA1 (armement conditionné à `package_installed()`) → 1 échec, **tuée**.
- **Restes acceptés (non corrigés, consignés)** :
  - **m1** : le contrôle sur disque de `channel_problems` ne voit que `site-packages/openwakeword|onnxruntime`
    (+ `dist-info`) et `models/` ; un composant renommé avec des manifestes réécrits de façon cohérente passe `verify`.
    Non exploitable par accident (le build exige une entrée de politique par roue, `*.onnx` ignoré par Git). Piste :
    rechercher les `*.onnx`/`*.tflite` hors `onnxruntime/datasets`.
  - **m3** : `release_info.py` identifie un build interne (nom `-internal-`, `production_blockers`,
    `channel_warning`) sans refuser de le publier ; aucune étape de publication n'existe et la CI construit le canal
    par défaut (production). Une future étape de publication devra lire `product.channel`.
  - **m4** : une variante `onnxruntime_directml-*.dist-info` seule n'est pas attrapée par le motif ; sans effet réel
    (ces roues installent `onnxruntime/`, attrapé).
- Tests : `test_wake_word_installed_default.py` (15), `test_windows_packaging.py`, `test_release_tooling.py` et
  16 fichiers voisins (wake word, voice lifecycle, readiness, private runtime, product setup, openwakeword engine) :
  849 passés, 2 ignorés (essais live sans modèle ni clip).
