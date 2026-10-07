# Audit à l'aveugle (Slice 00) — jarvis-wake-word

Base : `3bc7acf` (main), branche `task/jarvis-wake-word`. Audit en lecture seule, HANDOFF.md lu en dernier. Chemins relatifs à la racine du dépôt. Aucun test lancé par l'audit.

## 1. Ce qui existe déjà

- **Port détecteur** `WakeWordBackend` (`jarvis/ports/v2.py:229-234`) : `detections() -> AsyncIterator[str]`, `suspend()`, `suspend_for_active_session()`, `resume()`, `close()`. Ne transporte que des chaînes : ni confiance, ni seuil.
- **Contrat moteur** `WakeWordEngine` (`jarvis/adapters/wakeword_shared_pcm.py:80-90`), forme `pvporcupine` : `frame_length`, `sample_rate`, `process(pcm_tuple_int16) -> int` (`>= 0` = détecté), `delete()`. Fabrique unique `porcupine_engine_factory` (`:93-101`), seule à importer `pvporcupine`.
- `jarvis/adapters/wakeword_porcupine.py` : détecteur autonome, ouvre son propre `sd.RawInputStream` (`:71`), s'inscrit dans `input_ownership` (`OWNER_WAKEWORD_PORCUPINE`), appelle `engine.process` dans le thread de rappel PortAudio (`:53-69`). Mot-clé `"jarvis"`, sensibilité non passée.
- `wakeword_shared_pcm.py` : `SharedPcmWakeWordBackend`, lit le PCM du hub, n'ouvre aucun flux ; pannes dites (`wake_engine_unavailable`, `wake_engine_failed`, `wake_subscription_refused`, `wake_consume_failed`) ; `engine.process` appelé synchrone sur la boucle (`:217`).
- `wakeword_composite.py` (fan-in), `wakeword_keyboard.py` (F9 via pynput ; reste armé en ACTIVE).
- `jarvis/audio/capture_hub.py` (hub 24 kHz, blocs 50 ms, pré-roll 1,5 s en mémoire), `input_ownership.py` (registre de comptage, 7 ouvreurs), `resampling.py` (linéaire SANS anti-repliement, limite assumée).
- `jarvis/runtime/explicit_address_lane.py` + `jarvis/domain/explicit_address.py` : `ExplicitAddressSource` fermé (`WAKE_WORD`, `MANUAL_KEY`).
- `jarvis/runtime/presentation_audio.py` / `presentation_runtime.py` : en PRESENTATION le hub est l'unique propriétaire du micro ; fabrique Porcupine câblée en dur (`presentation_runtime.py:1717-1720`) ; `app.py:956-971` compose Keyboard + Porcupine (si clé) dans un Composite.
- `jarvis/runtime/voice_v2.py` : `run()` consomme `wakeword.detections()` (`:383`), trace `voice.wake` (`source=label`, `:409`), appelle `activate()` (`:410`) ; `suspend_for_active_session()` (`:734`) ; `resume()` en fin de `mute()` (`:1299`).
- Raccourci F9 : `jarvis/runtime/shortcuts.py:71-80` (`wake_toggle`, `manual_wake_key`).

## 2. État PASSIVE / ACTIVE

- Source de vérité : `VoiceLifecycleState` (`jarvis/domain/v2.py:81`) : `BACKGROUND` (= « PASSIVE » du handoff), `ACTIVE`, `CONNECTING`, `ERROR`. Ne PAS créer de seconde machine d'états.
- Axe orthogonal : `InteractionMode` (`jarvis/domain/interaction_mode.py`) : `assistant`, `presentation`, `meeting` ; « SIMPLE » n'est qu'une étiquette d'affichage (`InteractionMode.SIMPLE` lève volontairement).
- Chemin d'activation unique de fait : toute détection (`'f9'` ou `'jarvis'`) → `await self.activate()` (`voice_v2.py:405-410`). La source ne sert qu'à la trace. `rebind_board` appelle aussi `activate()` sans source (`:549`).
- Mise en veille aujourd'hui : F9 pendant ACTIVE ; phrase exacte « Jarvis mute » (deux mots, `jarvis/runtime/realtime_audio.py:4954-4964`) ; `JARVIS_ACTIVE_TIMEOUT_S` (90) ; `POST /api/live/stop`. « Va dormir » / « arrête d'écouter » n'existent pas.

## 3. STT / Brain au repos

- SIMPLE `BACKGROUND` : tournent le flux Porcupine (si clé), pynput, `follow_core_mode`. Aucune STT, aucun Brain, aucune session fournisseur.
- PRESENTATION : hub ouvert en continu + voie ambiante (`ambient_lane.py`) qui transcrit : ce n'est pas un « repos » au sens du handoff.
- Double propriétaire du micro : déjà géré et compté (`_suspend_simple()` avant `stack.start()`, `presentation_runtime.py:1237-1240` ; test de conformité `EXPECTED_INPUT_OPENERS`, `tests/unit/test_presentation_audio_capture.py:1653-1661`). Tout nouvel ouvreur s'inscrit ET s'ajoute à ce test.

## 4. Configuration

- Fichier `runtime/control-center-settings.json` (`control_center.py:1023`) ; lecture tolérante `_settings()` (`:2739`), écriture atomique `_write_settings` (`:2770`). Voice le relit au démarrage seulement (`app.py:909`) : un réglage de mot d'éveil exige un redémarrage de Voice.
- Modèles : `jarvis/runtime/interaction_mode_settings.py` (SETTING_KEY, SCHEMA_VERSION, inspect/load/apply/describe, route dédiée `/api/interaction-mode`), `scene_settings.py`.
- Clés existantes : `manual_wake_key`, `shortcuts.wake_toggle`, `PORCUPINE_ACCESS_KEY` (`credentials.py:57-62`), env `JARVIS_WAKE_KEYWORD` (`app.py:849,967`). Aucune clé de sensibilité, seuil, cooldown, fournisseur, activation.
- Convention : snake_case ; `wakeWord.*` du handoff devient un bloc `wake_word` (`schema_version`, `enabled`, `provider`, `keyword`, `sensitivity`, `cooldown_ms`). Module visé : `jarvis/runtime/wake_word_settings.py`.
- Migration SQLite : NON (réglages JSON ; CLAUDE.md n'impose une migration que pour un schéma SQLite).

## 5. Observabilité

- Journal `runtime/trace.jsonl` via `RuntimeJournal.emit` (`jarvis/runtime/journal.py:68`), sans liste blanche. Événements existants : `voice.wake` (`data.source`), `wake.shared_pcm.*`, `explicit_address.*`, `presentation.audio.*`, `voice.background` / `voice.active`.
- Pas de famille `wake_word.*` ; les noms du handoff entrent en collision de convention avec `wake.shared_pcm.*`.
- Timeline : `ATTRIBUTE_KEYS` (`jarvis/domain/conversation_events.py:232-241`) est fermé (pas de `confidence`/`threshold`/`keyword`) ; pas de type d'événement « wake ». Décision : tracer dans le journal uniquement pour la v1.
- Vie privée : aucun PCM persisté (pré-roll en deque bornée ; test `test_a_long_presentation_capture_writes_no_file_anywhere`).

## 6. Tests et harnais

- Références : `tests/unit/test_presentation_audio_capture.py`, `test_v2_wake_backends.py`, `test_v2_voice_toggle.py`, `test_v2_continuous_live.py`, `test_owner_input_gate.py`, `test_presentation_integration.py`, `test_interaction_mode_follower.py`, `tests/integration/test_presentation_scenarios.py`.
- Faux : `FakeCaptureDevice`, `sine_block`, `FakeWakeEngine` (détecte au n-ième appel ou lève), `FakeWakeBackend`, `input_ownership.reset_for_test()`, `FakeWakeWord` (`jarvis/testlab/virtual/harness.py:212`). Marqueur pytest `live`.
- `tests/fixtures/bonjour-jarvis.wav` (test live seulement). Aucun modèle `.onnx`/`.tflite`/`.ppn` versionné.

## 7. Dépendances et licences

- `pvporcupine>=3,<4` (extra `voice`, installé 3.0.5), clé Picovoice requise ; sans clé, seul F9 reste (`docs/OPERATIONS.md:3906`). Licence Picovoice non documentée dans le dépôt.
- `openwakeword` absent (pyproject et environnement). `onnxruntime 1.30.0` présent mais non déclaré. Pas de `.venv` dans les worktrees : l'environnement est celui du checkout principal (`C:/Projects/jarvis/jarvis/.venv`, Python 3.14). Compatibilité openwakeword / Python 3.14 : NON vérifiée.
- Notices : `third_party/README.md`, section « Speaker verification (Solo Owner) » = modèle pour une section « Wake word (openWakeWord) » (paquet, licence, modèles, non vendored, artefacts dans `runtime/`, SHA-256 épinglé dans le code comme `jarvis/adapters/sherpa_model_catalog.py`).
- Échantillonnage : hub 24 kHz → abonné « wake » rééchantillonné à `engine.sample_rate` (16 kHz) ; openWakeWord : 16 kHz, trame 1280 échantillons (80 ms). Rééchantillonnage linéaire non validé pour openWakeWord (mel).

## 8. Documentation du mot d'éveil

`docs/presentation-audio-capture.md` (contrat canonique), `docs/interaction-mode.md` (`:220`, `:479-494`), `docs/ARCHITECTURE.md` (`:326-331`, `:377`, `:426-437`), `docs/OPERATIONS.md` (F9 `:117-136`, variables `:1187,1196`, entrée PRESENTATION `:3895-3925`, écho `:4115`), `docs/ACCEPTANCE_STATUS.md` (`:271`, `:285`, `HV-PRES-AUDIO-01` `:335`), `docs/HARDWARE_ACCEPTANCE.md`, `docs/presentation-addressed-turn.md:560`, `docs/SECURITY.md`, `README.md:133`. Doublons sous `sw2/` et `sw3/`.

## 9. Écarts entre HANDOFF.md et le code

Déjà réalisé : un chemin unique BACKGROUND→ACTIVE (`voice_v2.py:405-410`) ; pas de second flux en PRESENTATION ; panne du détecteur laisse F9 utilisable ; pas d'audio persisté ; micros comptés.

Démenti / à corriger : (1) « PASSIVE/ACTIVE à créer » : existe (`VoiceLifecycleState`) ; (2) `confidence` perdue au moteur et au déclencheur (le port ne transporte que des chaînes) ; (3) `keyboard_f9` → vocabulaire existant `manual_key` / `wake_word` ; (4) clés camelCase / événements `wake_word.*` → snake_case, bloc `wake_word`, traces `voice.wake` enrichies ; (5) `wakeWord.enabled = true` par défaut ouvrirait un micro permanent chez tout le monde (régression de D14 : sans clé Porcupine, aucun flux au repos) → défaut `false` recommandé ; (6) « ne pas toucher à la propriété du micro » : nécessaire en SIMPLE car le hub n'existe pas au repos ; (7) phrases de veille « go to sleep » / « stop listening » : seul « Jarvis mute » existe (optionnel dans le handoff) ; (8) confiance dans la timeline : inatteignable sans changer `ATTRIBUTE_KEYS`.

## 10. Risques

Écho TTS qui déclenche « Hey Jarvis » (en PRESENTATION le détecteur lit le PCM brut du hub, l'AEC ne s'applique qu'au sink en ligne ; aucun garde de queue entre fin de lecture et `resume()` ; `docs/OPERATIONS.md:4115` : contrôle poste non exécuté) ; fuite de propriétaire du micro (inscription + libération y compris sur échec de fermeture, ajout à `EXPECTED_INPUT_OPENERS`, test `…second_microphone_owner`) ; comptes de propriétaires « SIMPLE = 2, PRESENTATION = 1 » testés (`test_presentation_audio_capture.py:243,329`) : étendre, pas contourner ; inférence ONNX synchrone sur la boucle asyncio (`wakeword_shared_pcm.py:217`) et, côté SIMPLE, jamais dans le rappel PortAudio (passer par une file) ; rééchantillonnage 24→16 kHz sans anti-repliement ; compatibilité Python 3.14 des roues openwakeword ; téléchargement des modèles à l'exécution (épingler SHA-256, installation à la demande) ; licence CC BY-NC-SA du modèle `hey_jarvis` (à confirmer, non vérifiable hors ligne) ; aucune validation micro réel jamais faite pour le mot d'éveil existant.

## 11. Recommandation de l'audit

Étendre le contrat existant, ne pas ajouter une couche : un `OpenWakeWordEngine` conforme à `WakeWordEngine` (seuil, cooldown, dernier score) ; PRESENTATION = échange de fabrique ; SIMPLE = généraliser le backend à flux propre pour un moteur injecté (préserve D14) ; aucune nouvelle machine d'états ; traces dans le journal ; bloc de réglages `wake_word` versionné, défaut désactivé ; sommeil vocal reporté ou limité à une extension minimale de « Jarvis mute ».
