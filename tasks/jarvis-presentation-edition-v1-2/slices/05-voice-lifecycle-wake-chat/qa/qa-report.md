# QA — Slice 05 `05-voice-lifecycle-wake-chat` (v1-2)

Relecture de `8e4e7141..33a97ac6` (4 commits `S5:`), worktree `pev12b`, 2026-10-27. Skills : `qa-verification`,
`code-review`, `runtime-validation`. Aucun code produit modifié ; aucun micro ni haut-parleur pris ; JARVIS vivant non
touché.

## Verdict : PASS avec réserves

Contrat tenu sur tout ce qui est vérifiable sans micro : une seule préférence, projection sans seconde machine
d'état, lanceur qui tient Voice au lieu de la boucle de plantages, Off qui survit au redémarrage, Quitter propre,
chat indépendant. La réserve majeure porte sur le périmètre HD-V12-01 (mot de réveil vocal non livrable en l'état),
pas sur la qualité du code.

## Findings

### Majeur

- **M1 — HD-V12-01 non réalisé, HV-V12-VOICE-01 impossible tel quel.** HD-V12-01 lève l'exclusion d'openWakeWord
  pour les builds internes et dit que la Slice 05 « peut armer le mot de réveil vocal en Sleep ». Rien n'est
  modifié sous `packaging/windows/*` (IMPLEMENTATION.md › « Travail de packaging à faire »), et le défaut
  `wake_word` reste `enabled: false` (`jarvis/runtime/wake_word_settings.py:86`). Sur un build interne, un profil
  vierge n'a donc que F9. Or le check `human-validation.json` HV-V12-VOICE-01 demande de « wake it by the configured
  wake word ». La page et la projection le disent honnêtement (« Moteur absent », « seul F9 »). Il faut une décision
  du PM : placer les étapes 1 à 4 de packaging dans une Slice (06 ou 09) avec son propre check, ou amender
  HV-V12-VOICE-01 (F9).

### Mineur

- **m1 — Bloc abîmé lu comme `sleep`, sans rien montrer à l'utilisateur.** `voice_lifecycle.py:104-121` : une
  préférence `"Off"` (écrite à la main) ou une version étrangère (après un retour à une version plus ancienne) se lit
  `sleep`. Avec une clé, le lanceur **démarre alors Voice**, et donc le micro, pour un utilisateur qui avait peut-être
  choisi Off. Constaté en bac : `{"preference": "Off"}` donne `preference: sleep, problem:
  voice_lifecycle_preference_invalid`. Le `problem` n'est ni affiché (la roue ne le lit pas) ni journalisé
  (`control_center.py:4261-4267` ne journalise qu'un changement d'état ou de code). Avis : `sleep` convient pour un
  bloc **absent** (profil vierge). Pour un bloc **présent mais illisible**, mieux vaudrait tenir Voice
  (`degraded`/`voice_lifecycle_block_unreadable`) jusqu'à ce que l'utilisateur appuie sur l'interrupteur : c'est
  plus sûr pour la vie privée, et le chat reste disponible. À défaut, il faut au moins journaliser et montrer
  `problem`. Le risque reste faible, car seule la route stricte écrit ce bloc, de façon atomique.
- **m2 — Une bascule Off→Sleep plus courte que la relecture compte comme un plantage.** `product_launcher.py:487-497`.
  Si Off ne dure pas assez pour que le lanceur le voie (relecture toutes les 1 s), Voice le voit quand même (elle
  relit toutes les 0,5 s), sort avec le code 0, et le lanceur consigne `child_exited` puis consomme un redémarrage
  (`may_restart`). Reproduit avec la vraie classe `Launcher` et une Voice factice qui reprend le chemin de `app.py` :
  avec des bascules de 0,25 s, 2 `child_exited code 0` sur 5. Au bout de 3 bascules de ce genre en 120 s, Voice est
  abandonnée (`voice_crash_loop`). On s'en remet par une bascule Off puis Sleep plus lente. Remède suggéré : ne pas
  compter une sortie 0 de Voice comme un plantage.
- **m3 — `sync_voice` bloque la boucle de veille pendant l'arrêt de Voice** (`stop_role`, jusqu'à 15 + 5 s). Pendant
  ce temps, ni Quitter ni la mort de Core ne sont traités. C'est sans effet en pratique, puisque Voice se libère en
  moins d'une seconde (0,5 s mesuré).
- **m4 — Édition `full` et développement.** La préférence s'y applique aussi (`app.py:1170-1179`, documenté dans
  `voice-lifecycle.md` › Who applies it). L'interrupteur apparaît dans la roue du JARVIS de développement. Off y
  arrête Voice ; Sleep ne la relance pas (`voice_not_running`, il faut relancer Voice). C'est un choix assumé et
  écrit dans IMPLEMENTATION.md. À signaler au Human avant la fusion, car son JARVIS quotidien a ce comportement.
- **m5 — Test instable, sans lien avec la Slice.**
  `test_product_setup.py::test_the_deferred_removal_waits_for_the_real_end_of_the_process_then_removes_key_and_state`
  a échoué une fois dans le grand lot, puis est passé 3 fois sur 3 seul ou par fichier. `product_setup` n'est pas
  touché par cette Slice.

## Vérifié OK

- **Préférence unique** : bloc `voice_lifecycle` dans `control-center-settings.json`, écriture stricte par
  `_write_settings` (atomique). En bac : 400 avec code pour `OFF`, une clé en trop, une liste ou `None`.
- **Route POST** : même `_origin_guard` que les autres routes mutantes. En bac, une origine étrangère, un autre port
  local ou `Sec-Fetch-Site: cross-site` donnent 403, et la préférence reste inchangée.
- **Projection** : aucun état optimiste. La réponse au POST est relue sur le serveur ; la roue remplace ses faits par
  cette réponse, puis par le battement suivant.
- **Arrêt de Voice** : `run_until_released` annule la tâche puis passe par le `finally` de `voice.close()`, et Voice
  sort par la demande d'arrêt (rôle gracieux). Coût de la relecture : 0,15 ms par appel quand Voice est tenue,
  0,09 ms quand elle tourne.
- **Délai de 3 s du Control Center** : aucun flux SSE ni WebSocket ; seuls les long-polls et les exports en cours au
  moment de Quitter sont coupés. Aucune requête n'est coupée en marche normale.
- **Essai réel** avec le lanceur produit en bac (marqueur, sans clé, ports 53653/53654), 3 lancements :
  - Voice tenue `voice_provider_key_missing` ;
  - 12 bascules en 0,19 s, ensuite `launcher.json` reste cohérent ;
  - POST off donne `held: voice_off` ;
  - Quitter : code 0 en 8,4 s, puis 2,4 s et 2,5 s ; `child_stopped_cleanly` pour ui et core ; ports libres ;
    aucun processus du bac restant (vérifié par WMI) ;
  - Off conservé aux lancements 2 et 3 ;
  - Quitter pendant 20 bascules : arrêt propre, dernière valeur persistée.
- **Harnais** (vraie classe `Launcher`, Voice factice qui reprend `run_until_released`, Job Object réel) : bascule à
  chaud Off (arrêt propre en 0,5 s), retour en Sleep (relance), Quitter juste après Off→Sleep (Voice non relancée,
  rien ne reste).
- **Événements de trace** présents : `voice.lifecycle.state|preference_saved|refused`, `launcher.voice_held`,
  `stop_requested`.
- **Docs** cohérentes : `voice-lifecycle.md`, `chat.md`, `settings/voice-audio.md`, `release.md`.
- **Tests** :
  - `test_voice_lifecycle.py`, chat Off/Sleep, `test_jarvis_wheel_js.py`, `test_wake_word_settings_ui.py`,
    `test_product_launcher.py` : 133 réussis ;
  - navigateur, roue et mot d'éveil : 27/27 ;
  - `test_status_centre_browser.py` et `test_product_readiness_browser.py` : 38/38 ;
  - balayage voisin (voix, chat, lanceur, réglages, préparation, product_setup, mot de réveil, `test_app.py`) : 2 455
    réussis, 2 échecs : celui de `test_app` est connu (`known_failures.json`), l'autre est m5.
- **Mutations** : 7 sur 7 tuées, sur une copie du bac :
  - Off ignoré au lancement ;
  - clé absente non tenue ;
  - pas d'arrêt à chaud ;
  - `connecting` non projeté Active ;
  - bloc abîmé lu `off` ;
  - `app.py` ignorant Off ;
  - Voice abandonnée non relancée.

## Non vérifié

- Une Voice réelle avec une clé : micro libéré à la bascule, retour en Sleep après une conversation, F9. Aucune fausse
  clé n'a été tentée (elle aurait pris un vrai périphérique). Renvoyé à HV-V12-VOICE-01.
- Le mot de réveil vocal réel (voir M1).
- Le chat de bout en bout dans le bac (pas de cerveau connecté). Il est couvert par le test contre un vrai Core.

Preuves (résultat du bac, `launcher.log`, trace filtrée, harnais, copies des bases du bac) :
`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\v12s05qa\`.
Le bac `%TEMP%\v12s05qa` est supprimé ; aucun processus ne reste.
