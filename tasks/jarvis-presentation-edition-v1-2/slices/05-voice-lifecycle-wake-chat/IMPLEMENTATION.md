# Slice 05 — Notes d'implémentation (voix Off / Sleep / Active, mot de réveil, chat)

Branche `wt/v12-s05` (worktree `pev12b`), depuis `task/jarvis-presentation-edition-v1-2` @ `8e4e7141`.
Contrat produit : [`docs/voice-lifecycle.md`](../../../../docs/voice-lifecycle.md).

## Ce qui a changé

- **Une seule préférence persistée** : bloc `voice_lifecycle` (`{"schema_version": 1, "preference": "sleep"|"off"}`)
  dans `runtime/control-center-settings.json`. Défaut `sleep`. Un bloc abîmé n'est jamais lu comme `off`. Aucune table,
  aucune migration. Module `jarvis/runtime/voice_lifecycle.py` : lecture tolérante, écriture stricte, contrôle de la clé
  du fournisseur (même chemin que Voice), état du moteur du mot de réveil, projection Off / Sleep / Active, et
  `run_until_released` pour Voice.
- **Pas de seconde machine d'état** : l'état affiché est projeté de la préférence, de `launcher.json` (lanceur) et du
  battement de Voice (`.voice_heartbeat`, `.voice_runtime.runtime_state`).
- **Lanceur** (`product_launcher.py`) : Voice démarrée seulement si la préférence n'est pas `off` et si la clé existe ;
  sinon *tenue* avec son code (`voice_off`, `voice_provider_key_missing`, `voice_configuration_invalid`), publié dans
  `launcher.json` (`roles.voice.held`, `running`) : plus de boucle « 3 plantages puis abandon » sans clé. Préférence
  relue chaque seconde (clé relue seulement quand Voice ne tourne pas) : `off` arrête Voice à chaud par sa demande
  d'arrêt propre, `sleep` la redémarre et redonne sa chance à une Voix abandonnée. Voice fait désormais partie des
  rôles à arrêt propre (`GRACEFUL_ROLES`) : « Quitter JARVIS » ne la `terminate` plus d'emblée.
- **Voice** (`jarvis/app.py`) : `off` persisté → sortie 0 avant toute composition (aucun micro, aucun écouteur) ;
  en marche, rend la main sur la demande d'arrêt du lanceur ou sur `off` (aussi sans lanceur), le `finally` existant
  ferme séance et micro.
- **Control Center** : `GET/POST /api/voice/lifecycle` ; bloc `voice_lifecycle` dans `/api/status` ; `engine` dans
  `GET/POST /api/wake-word` ; faits coûteux (clé, empreintes des modèles) en cache 15 s ou jusqu'au changement de
  réglage ; trace `voice.lifecycle.state` à chaque changement d'état/code, `voice.lifecycle.preference_saved`,
  `voice.lifecycle.refused`.
- **Interface** (sobre, composants existants) : ligne **Voix activée** dans le sous-menu JARVIS de la roue
  (`menuitemcheckbox` de la roue, note = état serveur, détail = message et code, un POST par clic, délai 8 s, refus
  dit par notification et console). La ligne « Voix » dit « coupée » en Off. Page « Mot d'éveil » : activé mais moteur
  absent → pastille « Moteur absent », texte « seul F9 réveille JARVIS » et code (`data-ww-engine`), jamais « activé »
  tout court.
- **Préparation** : ligne `voice` (groupe poste, jamais requise) : clé présente ? état ? ; clé absente → « À faire »
  avec « Ouvrir Connexions ».
- **Chat** : aucun changement de code nécessaire (Off = `absent`, Sleep = `background`, déjà inscriptibles ; un tour
  écrit n'est jamais parlé). Prouvé par test.
- **Docs** : `docs/voice-lifecycle.md` (nouveau), liens depuis `chat.md`, `settings/voice-audio.md`,
  `product-install.md` (lanceur, ligne `voice`), `release.md` (HD-V12-01, bloquant de production),
  `control-center-shell.md` et `OPERATIONS.md` (la roue n'affirmait plus « aucun interrupteur »).
- **Quitter JARVIS, trou comblé** (trouvé en bac à sable, présent aussi sur la base `8e4e7141`) : le Control Center
  dépassait les 15 s de grâce du lanceur quand une requête restait ouverte (aiohttp attend 60 s par défaut) et
  finissait en arrêt forcé. `AppRunner(shutdown_timeout=HTTP_SHUTDOWN_TIMEOUT_S=3 s)` : arrêt propre. Remotion, MCP et
  CLI restent arrêtés par la fermeture du Job Object de chaque rôle (inchangé).

## Preuves

Commits `4a2de8ba`, puis `S5: tenue de la voix publiée…` (voir `git log`). Python du venv du checkout principal,
lancé depuis `pev12b`, Windows 11, 2026-10-27.

- `tests/unit/test_voice_lifecycle.py` (45) : préférence (défaut, bloc abîmé ≠ off, écriture stricte, version
  étrangère) ; matrice de démarrage du lanceur (profil vierge avec clé → Voice ; `off` persisté → jamais démarrée, sur
  deux lancements ; clé absente → tenue `voice_provider_key_missing`, aucun `child_exited`/`child_abandoned`) ; bascule
  à chaud off → arrêt propre (pas de `terminate`) → sleep → seconde incarnation ; Voix abandonnée relancée après
  off/on ; changement de tenue publié ; « Quitter » : ui, voice, core arrêtés proprement, chaque Job fermé ; Voice avec
  `off` → sortie 0 sans composer sa pile ; `run_until_released` (off, demande d'arrêt, fin normale) ; matrice de
  projection (12 cas) ; réveil armé seulement en veille ; moteur absent (paquet, modèles, clé Porcupine) ; routes du
  Control Center, bloc de `/api/status`, `engine` de `/api/wake-word` ; ligne `voice` de la préparation ; arrêt du
  Control Center non bloqué par une requête ouverte (le test échoue avec un délai de 30 s).
- `test_chat_text_ingress.py::test_chat_in_off_or_sleep_reaches_the_brain_without_touching_voice[off|sleep]` : le tour
  atteint le cerveau, état et révision du canal vocal inchangés, aucune demande, aucun `brain.speech.requested`.
- Navigateur (Chrome réel) : `test_jarvis_wheel_browser.py` (interrupteur : `menuitemcheckbox` coché en veille, clic →
  POST `off`, notification, relu « coupée · OFF » ; reclic → « démarrage… », la projection et non l'espoir ; refus 400 →
  rien ne change, `jarvis_wheel.voice_power_failed` avec le code) ; `test_wake_word_settings_browser.py` (activé sans
  moteur → « Moteur absent », `wake_package_missing`, « seul F9 »). Fichiers entiers verts : wheel 6/6, mot d'éveil
  21/21, `test_status_centre_browser.py`, `test_product_readiness_browser.py`.
- Balayage voisin non navigateur (voix, chat, lanceur, réglages, préparation, mot de réveil, Control Center, docs :
  152 fichiers) : 3 463 passés, seuls échecs = 6 de `test_control_center_mcp_api.py` et
  `test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`, tous dans
  `tests/known_failures.json`. Relance des 37 fichiers `test_control_center*` après le correctif d'arrêt : mêmes 6 connus.
- **Essai réel en bac à sable avec le lanceur produit** (archive du commit sous `%TEMP%\v12s05`, marqueur
  `jarvis-product.json` posé, `LOCALAPPDATA` et racines de données/runtime/export dans le bac, ports 48653/48654,
  visualiseur coupé, navigateur non ouvert, aucune clé vocale) :
  1. profil vierge : Core et Control Center démarrés, Voice **tenue** `voice_provider_key_missing` (`launcher.json`),
     `/api/voice/lifecycle` `degraded`/`voice_provider_key_missing`/`managed: true`, préparation « À faire » avec la
     phrase du produit, `/api/wake-word` `engine.configured: false` ;
  2. POST `off` → `off`/`voice_off`, `launcher.json` passe à `held: voice_off` (après correctif) ; POST invalide → 400 ;
  3. « Quitter » → lanceur code 0, `child_stopped_cleanly` pour ui et core, ports 48653/48654 libres ;
  4. second lancement : `off` survit, Voice tenue `voice_off` d'emblée, quitter propre ;
  5. `python -m jarvis voice` seul avec `off` : code 0, « Voice ne démarre pas », trace
     `voice.lifecycle.start_refused_off`.
  Base `8e4e7141` dans le même bac : `child_stop_timeout ui` à chaque « Quitter » (le trou corrigé). Preuves copiées
  au scratchpad de la session 448345f0 : `scratchpad\v12s05\evidence\` (résultat, `launcher.log`, trace filtrée,
  journal de la base) et `scratchpad\v12s05\sandbox-dbs\` (copies des bases jetables avant suppression du bac).
  Aucun processus du bac ne reste.

## Checks Human proposés

- **HV-V12-VOICE-01** (déjà au paquet de la Slice) : sur un poste avec micro réel, profil vierge, clé du fournisseur
  saisie : JARVIS ouvert → roue JARVIS « Voix activée · veille · SLEEP » ; F9 → conversation, puis retour en veille ;
  « Voix activée » décochée → « coupée · OFF », vérifier dans la barre des tâches Windows que le micro n'est plus
  utilisé ; quitter et relancer → toujours coupée ; envoyer un message au chat → réponse écrite, aucun son, micro
  toujours fermé ; recocher → « démarrage… » puis « veille ».
- **HV-V12-VOICE-02** (proposé) : mot de réveil réel « Hey Jarvis » (openWakeWord installé dans un build interne) :
  page « Mot d'éveil » sans « Moteur absent », réveil par la voix depuis la veille ; puis désinstaller l'extra →
  la page dit « Moteur absent » et la préparation le rappelle.
- **HV-V12-VOICE-03** (proposé) : poste sans clé du fournisseur : la préparation dit « Clé du fournisseur vocal
  absente » (À faire), la roue « indisponible », aucun plantage répété dans `runtime\logs\launcher.log`.

## Travail de packaging à faire (HD-V12-01, hors de cette Slice)

Rien n'a été touché sous `packaging/windows/*` ni `build_package.py`. Pour que la veille arme le mot de réveil vocal
dans un build interne :

1. `packaging/windows/requirements.in` : ajouter l'extra `wakeword` (`openwakeword>=0.6,<0.7`, `onnxruntime>=1.30,<2`,
   `numpy`, et leurs dépendances `scipy`, `scikit-learn`) pour les builds internes seulement (marqueur de build).
2. `packaging/windows/third_party_policy.json` : entrées `openwakeword` et `openwakeword-models` passées d'exclues à
   « autorisées build interne, CC BY-NC-SA, bloquant de production » ; notice dans `third_party/README.md`.
3. Modèles : soit les livrer dans le paquet et faire lire ce dossier par `wakeword_model_catalog.default_model_dir()`
   (aujourd'hui `<maison du produit>\runtime\wake-word\models`), soit lever le refus
   `wake_word_install_unavailable_in_edition` de `wake_word_install.py` pour les builds internes et faire installer les
   modèles au premier lancement ; dans les deux cas, empreintes SHA-256 du catalogue inchangées.
4. Défaut produit à décider : le bloc `wake_word` est `enabled: false, provider: porcupine` par défaut ; un build interne
   qui veut « Hey Jarvis » en veille dès le premier lancement doit écrire `{"enabled": true, "provider":
   "openwakeword"}` (graine du profil) — sinon seul F9 réveille, ce que la page et la projection disent.
5. Le contrôle de la clé (`voice_lifecycle.provider_key`) et le moteur (`wake_engine`) s'exécutent dans le Python privé
   du paquet : rien à ajouter.

## Ce qui n'a pas été vérifié

- **Aucun micro ni haut-parleur réel** n'a été pris (règle de la Slice : le JARVIS vivant pouvait les utiliser).
  Voice n'a jamais tourné avec une clé dans le bac : la bascule à chaud d'une Voice **réelle** (arrêt propre par
  `run_until_released`, micro libéré, puis redémarrage en veille) et le retour Sleep après une conversation ne sont
  prouvés que par tests (doubles de processus) → HV-V12-VOICE-01.
- Le mot de réveil vocal réel (« Hey Jarvis ») n'a pas été exercé : moteur non installé ici et paquet inchangé
  (HD-V12-01, travail de packaging ci-dessus) → HV-V12-VOICE-02.
- L'arrêt de Remotion/aides par « Quitter » n'a pas été observé avec un rendu en cours : il repose sur la fermeture du
  Job Object de chaque rôle, inchangée et couverte par les tests V1.
- Le chat n'a pas été essayé de bout en bout dans le bac (pas de CLI de cerveau connectée) : prouvé contre un vrai Core
  avec un cerveau factice.
- `agent-trace-analysis` (QA exigée) : aucun prompt ni outil d'agent n'est modifié ; les traces nouvelles sont des
  événements d'état, listées dans `docs/voice-lifecycle.md` › Surfaces.
- En développement (sans lanceur), repasser de `off` à `sleep` ne relance pas Voice : la projection dit
  `voice_not_running` ; il faut relancer Voice (`project jarvis restart` côté Human). Choix assumé : seul le lanceur
  supervise des processus.

## Reprise QA (rapport `qa/qa-report.md`, `7d43e87f` ; décisions du PM du 2026-10-27)

- **M1 (mot de réveil vocal non livré)** : reporté par le PM à une Slice de suivi, après la fusion de la branche
  parente V1 (le packaging y est en cours de modification). Elle couvrira le packaging openWakeWord des builds
  internes et le mot d'éveil activé par défaut quand le moteur est présent. Rien de plus ici ; la section « Travail de
  packaging à faire » reste la liste de départ. HV-V12-VOICE-01 ne peut réveiller par la voix qu'après cette Slice
  (F9 d'ici là).
- **m1 (bloc illisible)** :
  - bloc absent : veille, comme avant ;
  - bloc présent mais illisible (`"Off"`, autre version, pas un objet) : préférence `unreadable`. Le lanceur tient
    Voice (`voice_preference_unreadable`, avertissement). Voice refuse de démarrer, ou se libère si elle tournait. La
    projection est `degraded` avec un message lisible, journalisée en avertissement avec `problem` ;
  - l'interrupteur est décoché ; un clic écrit `sleep`. L'écriture remplace désormais un bloc illisible :
    `voice_lifecycle_foreign_version` est retiré, le bloc ne porte qu'un choix ;
  - trouvé en bac : juste après la réécriture, la projection montrait encore la tenue périmée du lanceur. Une tenue due
    à la préférence est maintenant ignorée dès que la préférence lue dit « veille ».
- **m2 (bascules rapides)** :
  - une sortie de Voice avec le code 0 n'est plus un plantage (`voice_exited_clean`), même quand le Off qui l'a causée
    a été trop bref pour le lanceur. Aucun redémarrage de plantage n'est consommé ; la relance suit la préférence
    courante ;
  - garde-fou : plus de `VOICE_CLEAN_EXITS_MAX` (10) sorties propres en 120 s abandonnent quand même Voice.
- **m3** (boucle de veille bloquée pendant l'arrêt de Voice, au plus 15 + 5 s, mesuré 0,5 s) : accepté, noté dans
  `docs/voice-lifecycle.md`.
- **m4 (sans lanceur)** :
  - nouvel état produit `not_running` (code `voice_not_running`) : la roue affiche « à relancer », ton neutre et non
    erreur, avec le message « La voix est rallumée mais ne tourne pas : relancez Voice (ou JARVIS) pour l'utiliser. Le
    chat reste disponible. » ;
  - `docs/voice-lifecycle.md` › Who applies it le dit ;
  - `project jarvis` et les scripts de l'utilisateur ne sont pas modifiés. À signaler au Human avant la fusion : son
    JARVIS quotidien (édition `full`) a l'interrupteur, Off y arrête Voice, Sleep demande une relance à la main.

### Preuves de la reprise

- Tests ajoutés dans `test_voice_lifecycle.py` (54 au total, tous verts) :
  - bloc illisible (3 formes) : jamais de Voice ; avec une clé, lanceur tenu au départ ; arrêt à chaud quand le bloc
    devient illisible ;
  - Voice seule : sortie 0 avec `voice_preference_unreadable` et `problem` ;
  - route : état, journal en avertissement, réécriture par l'interrupteur ;
  - projection : `not_running`, `unreadable`, tenues périmées ignorées ;
  - **cinq bascules Off→Sleep plus brèves que la relecture** : 5 `voice_exited_clean`, aucun `child_exited` ni
    abandon, 6 incarnations, aucun redémarrage de plantage consommé ;
  - une Voice qui sort 0 en boucle est abandonnée après 10 sorties ;
  - mutation : sans le correctif m2, les deux derniers tests échouent.
- JS (`test_jarvis_wheel_js.py`, 9/9) : « à relancer » et choix illisible.
- Navigateur (`test_jarvis_wheel_browser.py`, 7/7) : un choix illisible s'affiche « indisponible », décoché, avec son
  code ; un clic envoie `{"preference": "sleep"}`, puis la case est cochée.
- Balayage voisin (152 fichiers + chat) : 3 492 passés. Seuls échecs : les 6 de `test_control_center_mcp_api.py`
  connus (`known_failures.json`).
- **Harnais de course du QA** (`scratchpad\v12s05qa\harness\race.py`, vraie classe `Launcher`, Voice factice qui
  reprend `run_until_released`, Job Object réel), sur ce code, cinq bascules de 0,25 s : `voice_exited_clean` ×2,
  `voice_exited_held` ×1, Off vu ×1. Bilan : `abandoned False`, `restarts 0`, Voice en marche, puis arrêt propre
  (`child_stopped_cleanly`). Avant la reprise, le QA mesurait 2 `child_exited` sur 5.
- **Bac à sable avec le lanceur produit** (`%TEMP%\v12s05`, marqueur produit, ports 48653/48654, aucune clé), bloc
  `{"preference": "Off"}` posé avant le lancement :
  - `launcher.json` `held: voice_preference_unreadable` ;
  - `/api/voice/lifecycle` `unreadable/degraded/voice_preference_unreadable`, `problem:
    voice_lifecycle_preference_invalid`, message lisible ; préparation `optional` ;
  - trace `voice.lifecycle.state` en avertissement avec `problem` ;
  - POST `sleep` : bloc réécrit `{"schema_version": 1, "preference": "sleep"}`, réponse
    `degraded/voice_provider_key_missing` (la vraie raison suivante, sans clé), `launcher.json` à
    `voice_provider_key_missing` ;
  - Quitter : code 0, ui et core arrêtés proprement, ports libres ;
  - `python -m jarvis voice` avec un bloc de version 3 : code 0, « Choix de voix illisible », trace
    `start_refused_off` en avertissement.

  Preuves dans `scratchpad\v12s05\evidence-qa\`, bases du bac copiées dans `scratchpad\v12s05\sandbox-dbs-qa\` avant
  la suppression du bac (`%TEMP%\v12s05` et `%TEMP%\v12s05r` supprimés, aucun processus restant).
- Non exercé réellement : la bascule rapide avec une **vraie** Voice (clé + micro) → HV-V12-VOICE-01.
