# Décisions à confirmer par le Human — jarvis-wake-word

Slice 08. Les décisions D1 à D7 ont été prises par l'agent 0 en Slice 00 (`slices/00-project-manager/READINESS.md`) en appliquant ses recommandations, faute de réponse du Human. Elles sont toutes **à confirmer**. Pour chacune : ce qui a été fait, ce que le Human doit confirmer, ce qu'il perd s'il refuse. Rien n'est marqué validé sur le poste ; les contrôles matériels sont dans `docs/HARDWARE_ACCEPTANCE.md` § 12 (statut **À FAIRE**).

## D1 — `wake_word.enabled` : désactivé par défaut

- **Fait** : `DEFAULT_ENABLED = False` (`jarvis/runtime/wake_word_settings.py`). Bloc absent, illisible ou de version étrangère : défauts complets, donc désactivé. Sans réglage ni clé Picovoice, aucun micro n'est ouvert au repos (comportement d'avant). L'onglet Réglages › Mot d'éveil dit que l'interrupteur ouvre un micro au repos.
- **À confirmer** : que le défaut reste `false`. Le handoff écrit `wakeWord.enabled = true` ; un défaut actif ouvrirait un micro permanent chez tout utilisateur et romprait la décision D14 de la tâche de présentation.
- **Si refusé** : changer `DEFAULT_ENABLED` et la sélection des fabriques ; les tests de défaut (`test_wake_word_settings.py`, `test_simple_wake_word_wiring.py::test_disabled_by_default_opens_no_stream_in_simple`) à réécrire.
- **Vérifié sur le poste par** : `HV-WAKEWORD-MIC-01-i` (preuve indirecte : le compte du registre de propriétaires n'est pas lisible au repos en SIMPLE, voir `Issues/003-owner-count-not-readable-at-rest.md`).

## D2 — Veille vocale : extension minimale de « Jarvis mute »

- **Fait** : `SLEEP_COMMANDS` / `is_sleep_command` (`jarvis/runtime/realtime_audio.py`) remplacent la comparaison inline : liste **fermée** de quatre formes, phrase entière, ponctuation ignorée : « Jarvis mute », « Jarvis stop listening », « Jarvis arrête d'écouter » (avec et sans accents). Même chemin `on_mute`, aucun détecteur, aucun état nouveau. **Pas** de « go to sleep », « va dormir », « stop » seul, « stop listening » sans « Jarvis », ni phrase au milieu d'une demande (testés non reconnus).
- **À confirmer** : le SLICE.md de la Slice 06 interdisait « stop listening » ; la consigne du PM l'a autorisé (même chemin que « Jarvis mute »). Le Human décide de garder « stop listening » et « arrête d'écouter » (deux lignes de `SLEEP_COMMANDS`) ou de revenir à « Jarvis mute » seul. Il décide aussi si « go to sleep » (cité par le handoff) doit un jour exister : ce serait un autre périmètre.
- **Limites connues, non corrigées** : « Jarvis, stop listening? » (ponctuation finale ignorée) coupe la séance ; les accents décomposés (NFD) ne sont pas reconnus (faux négatif sans danger) ; la source `manual_key` dépend de `manual_wake_key`.
- **Vérifié sur le poste par** : `HV-WAKEWORD-MIC-01-g`.

## D3 — Licence du modèle `hey_jarvis`

- **Fait** : code d'openWakeWord sous Apache-2.0, modèles préentraînés sous **CC BY-NC-SA 4.0** (confirmé à la source le 2026-10-07, README amont, section « License »). Usage **privé, tests privés, non commercial**. Aucune redistribution : les trois fichiers ONNX sont téléchargés sur une **commande explicite** dans `runtime/wake-word/models/` (ignoré par Git), taille et SHA-256 épinglés dans `jarvis/adapters/wakeword_model_catalog.py`, vérifiés avant installation. Notice : `third_party/README.md` ; exploitation : `docs/OPERATIONS.md` « Installer openWakeWord » ; sécurité : `docs/SECURITY.md` § 17 ; écran : la mention de licence n'apparaît qu'avec le fournisseur openWakeWord. Chemin de remplacement : modèle personnalisé sous licence libre, autre moteur local ou Porcupine, en changeant le catalogue et la fabrique.
- **À confirmer** : que l'usage prévu reste privé et non commercial ; que l'absence de redistribution (le Human installe lui-même) est acceptable ; la date de vérification de la licence (2026-10-07) est celle d'un instant : la relire avant toute distribution.
- **Si refusé** : retirer le fournisseur openWakeWord de la sélection (le bloc, l'écran et le détecteur SIMPLE sont isolés derrière lui) ou fournir un modèle sous licence compatible.
- **Écart d'installation à connaître** : il n'existe pas de commande dédiée dans le produit pour installer les modèles (voir `Issues/002-no-model-install-command.md`) ; la procédure documentée est une ligne Python.

## D4 — Vocabulaire des réglages et des traces

- **Fait** : réglages en snake_case dans un bloc `wake_word` (`schema_version`, `enabled`, `provider`, `keyword`, `sensitivity`, `cooldown_ms`) ; route `GET`/`POST /api/wake-word` ; traces `wake.shared_pcm.*`, `wake.own_stream.*`, `wake.openwakeword.slow_inference`, `voice.wake` (+ `provider`, `score`, `threshold` mesurés), `voice.connecting`, `voice.wake.outcome` dans `runtime/trace.jsonl`, **jamais** dans la timeline (`ATTRIBUTE_KEYS` inchangé) ; sources normalisées `manual_key` / `wake_word`, étiquette brute dans `keyword`.
- **À confirmer** : l'abandon des noms du handoff (`wakeWord.*`, `wake_word.detected`, `keyboard_f9`) au profit du vocabulaire existant. Voir aussi les écarts ci-dessous.

## D5 — Pas de seconde machine d'états

- **Fait** : `VoiceLifecycleState` (`BACKGROUND`, `CONNECTING`, `ACTIVE`, `ERROR`) reste la source de vérité ; « PASSIVE » du handoff est `BACKGROUND`. Le retour au repos (F9, phrase vocale, délai, `POST /api/live/stop`) converge sur `PersistentVoiceRuntime.mute()` qui réarme le détecteur.
- **À confirmer** : l'équivalence PASSIVE = BACKGROUND.

## D6 — Aucune migration SQLite

- **Fait** : réglages JSON (`runtime/control-center-settings.json`) ; aucune base, aucun `_MIGRATIONS`, `tests/unit/test_schema_migrations.py` vert à chaque Slice. Aucune base n'a été lue, modifiée ni copiée.
- **À confirmer** : rien de plus ; signaler si un besoin de persistance en base apparaît.

## D7 — Où s'exécute l'inférence

- **Fait** : mesure en Slice 01 (ONNX, CPU du poste de développement, à vide) : par trame de 80 ms, p50 2,7 à 3,2 ms, p99 3,8 à 6,2 ms, max 11,5 ms. **PRESENTATION** : `engine.process` reste sur la **boucle asyncio** (`jarvis/adapters/wakeword_shared_pcm.py`), sans exécuteur ; garde-fou : trace `wake.openwakeword.slow_inference` (code `wake_inference_slow`) si un appel dépasse 40 ms. **SIMPLE** : jamais dans le rappel PortAudio ; le rappel copie dans une file bornée de 16 blocs et un **thread dédié** exécute `engine.process` (`jarvis/adapters/wakeword_own_stream.py`), les détections reviennent à la boucle par `call_soon_threadsafe`.
- **À confirmer** : que l'inférence sur la boucle asyncio en PRESENTATION est acceptable (bascule vers un exécuteur dédié si `slow_inference` apparaît en usage réel, à voir en `HV-WAKEWORD-MIC-01-c`/`-j`) et que le thread dédié en SIMPLE convient. Coût sous charge de poste : p99 d'environ 8 ms, max d'environ 12 ms, soit 15 % du budget de trame.
- **Coût associé à connaître** : en SIMPLE, chaque `mute()` libère puis reconstruit le moteur (aucun état de modèle ne survit à la séance) : environ 155 ms mesurés dans un venv jetable, **jamais en conditions réelles** (`HV-WAKEWORD-MIC-01-k`). En PRESENTATION le moteur n'est pas rechargé.

## Écarts au HANDOFF, tous acceptés par l'agent 0, à confirmer

1. **La confiance n'est pas portée par le port.** `WakeWordBackend` ne transporte que des chaînes ; `score`, `threshold`, `provider` restent sur le moteur et passent au journal par duck-typing (`last_detection`, appariée à sa détection). Le handoff voulait un événement runtime avec confiance et source : il existe dans le journal, pas dans le port ni la timeline.
2. **PASSIVE = BACKGROUND** (D5) : pas de nouvel état.
3. **Vocabulaire snake_case** (D4) : `wake_word`, `manual_key`, `wake_word` ; pas de `wakeWord.*`, de `keyboard_f9` ni d'événements `wake_word.*`.
4. **Pas de timeline** : aucune détection n'entre dans la ligne de temps de la conversation (`ATTRIBUTE_KEYS` fermé, aucun nouveau type d'événement).
5. **Défaut désactivé** (D1) au lieu de `true`.
6. **Frontière = contrat `WakeWordEngine`**, pas l'interface `WakeWordProvider` du handoff : ni `setSensitivity` à chaud, ni `healthCheck` ; un changement de réglage exige un redémarrage de Voice.
7. **Pas de « go to sleep »** ; « stop listening » et « arrête d'écouter » seulement précédés de « Jarvis » (D2).
8. **Pas de hot-plug** ni de mise à chaud : le périphérique d'entrée est celui choisi au démarrage de Voice.
9. **Pas de commande d'installation dédiée** pour les modèles (Issue 002).

## Limites connues, documentées et non corrigées

- **Aucun garde de queue anti-écho** entre la fin de la voix de Jarvis et la reprise du détecteur ; en PRESENTATION le détecteur lit le PCM brut du hub (l'AEC ne sert que le chemin interactif). Mesuré en `HV-WAKEWORD-MIC-01-e` ; une Issue avec proposition de garde sera ouverte si le risque est avéré.
- **Un seul consommateur par détecteur** : `last_detection` est un champ unique écrit dans `detections()` ; Voice OU le routeur de présentation, jamais les deux.
- **Un F9 pressé pendant `CONNECTING` est perdu** (comportement hérité de `suspend_for_active_session` qui vide la file du `Composite`).
- **Modèle anglophone** : une voix française de synthèse plafonnait à 0,22 pour un seuil de 0,5 ; le seuil par défaut n'est pas calibré (`-d`, `-l`).
- Thread d'inférence bloqué (`wake_consumer_stuck`) : moteur non supprimé explicitement, fil démon ; `wake_pcm_dropped` silencieux tant que le consommateur est bloqué.
- `POST /api/wake-word` réécrit `self._settings()` comme `/api/interaction-mode` (issue transverse connue) ; deux onglets : le dernier enregistrement l'emporte.
- La suite de tests compte 6 échecs hérités et un test intermittent (`READINESS.md`, `Issues/001-flaky-evicted-source-test.md`), sans rapport avec le mot d'éveil.

## Résumé : ce que le Human doit trancher ou exécuter

| À faire | Où |
| --- | --- |
| Confirmer D1 (défaut `false`), D2 (« stop listening » / « arrête d'écouter »), D3 (licence, usage privé), D7 (boucle asyncio en PRESENTATION, thread en SIMPLE) | ce fichier |
| Confirmer D4, D5, D6 et les 9 écarts ci-dessus | ce fichier |
| Confirmer ou changer les seuils proposés des contrôles matériels avant la première mesure | `docs/HARDWARE_ACCEPTANCE.md` § 12.0 |
| Exécuter `HV-WAKEWORD-UI-01` | `slices/07-control-center-ui/human-validation.json` |
| Exécuter `HV-WAKEWORD-MIC-01-a` à `-l` | `docs/HARDWARE_ACCEPTANCE.md` § 12 ; `slices/09-human-microphone-validation/human-validation.json` |
