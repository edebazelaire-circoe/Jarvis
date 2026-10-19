# Fiche : JARVIS ne retombe pas en veille

Retour (voix, 2026-10-16 20:23) : « Encore une fois, ça n'a pas marché, tu ne t'es pas mis en mode veille » (confirmé : il reste à l'écoute au lieu d'attendre le mot de réveil).
Session : jsess_cb573e1f88b34a67ba02c180267c934b. Enquête en lecture seule, aucun code modifié, JARVIS non touché.

## Constat de départ (corrige la mémoire du projet)

La voix ne tourne pas en `continuous_brain` mais en **duplex / gpt-live-1** (`runtime/.voice_live_runtime` : architecture duplex, idle_timeout_s 60 ; `control-center-settings.json` : architecture duplex, idle_timeout_s 60). Le `.env` dit toujours `JARVIS_VOICE_ARCH=continuous_brain`, mais c'est le chemin duplex qui s'exécute.

En duplex, la veille ne vient que de `PersistentVoiceRuntime.check_timeout` (`jarvis/runtime/voice_v2.py` ~1688) : délai d'inactivité 60 s, puis `mute(IDLE)`, puis `voice.background` et mot de réveil réarmé.

## Preuves (runtime/trace.jsonl, 2026-10-16)

1. Zéro `voice.timeout` le 14 et le 16/10. Auparavant il en tombait chaque jour (10/10 : 9, 13/10 : 2, 03/10 : 4, etc.). La rupture date du 14/10.
2. Les 3 sessions du soir sont toutes fermées à la main, jamais par le délai :
   - 19:34:25 `core.voice_channel.disable_requested` (bascule chat) ;
   - 20:17:03 et 20:23:53 `voice.live_stop_requested` (« GPT-Live stop requested from Control Center ») ;
   - 19:55:47 idem.
3. Session 20:17:48 à 20:23:53 : l'orbe est restée 140 s d'affilée en `waiting`/`listening` (20:17:48 à 20:20:08) sans que l'utilisateur ait transcrit un seul tour adressé (le premier est à 20:20:08). Session 19:59 à 20:17 : plages de 126 s (20:10:18) et 106 s (20:08:04) dans le même cas. Le délai est de 60 s : il aurait dû expirer. L'orbe clignote `waiting` -> `listening` toutes les 3 à 10 s, soit « voix de l'utilisateur captée » déclenchée par du bruit/parole non adressée (barge-in à 20:18:15 sans tour derrière : `floor_released ... floor_taken_timeout`).
4. Historique des demandes : l'utilisateur demande la veille en langage naturel à répétition (07/10 13:42 et 21:25, 10/10 21:32, 14/10 22:21 « tu peux rester en mode sleep », 16/10 20:23). C'est donc un échec récurrent.

## Cause établie (la plus probable, chaîne vérifiée dans le code)

Commit `0c03ed8e` (2026-10-14, « délai d'inactivité réarmé tant que l'utilisateur parle »). Dans `check_timeout` :

- `if duplex and self.activity.enabled and self._live_user_active(): self.activity.reset(); return False` ;
- `_live_user_active()` lit `live_idle_evidence().user_speaking`, qui est vrai dès que `_user_speaking` (VAD du fournisseur, en salle ouverte), `_local_speech`, `_barge_pending` ou `_user_voice` (maintien 0,8 s) le sont ;
- ces drapeaux se lèvent sur **n'importe quel son que le VAD juge de la parole**, adressé ou non (`realtime_audio.py` ~4300-4345, `_note_user_voice`).

Effet : toute parole ambiante, écho ou conversation de fond remet le chronomètre à zéro. Cela viole la Décision 10, rappelée dans `ambient_activity()` : « du bruit, une conversation de fond ne prolongent jamais la session ». Dans une pièce où l'on parle ou avec du bruit, le délai de 60 s ne s'écoule jamais et JARVIS reste ouvert indéfiniment. Les clignotements d'orbe observés toutes les quelques secondes le confirment.

Facteurs aggravants, moins sûrs (hypothèses) :
- `if duplex and not self._live_idle_ready(): return False` : la veille exige en plus `sensor_known`, `device_known` et aucune sortie en attente. Le fil GPT-Live n'émet aucune fin de sortie (mémoire `gpt-live-wire-facts`), donc `_live_output_quiescent`/`_unfinished` peuvent rester faux et bloquer l'expiration. Non mesuré ici : la trace ne journalise pas `idle_waiting_for_safe_point` (seulement le fichier d'état écrasé).
- Aucune commande vocale de veille en langage naturel. `SLEEP_COMMANDS` (`realtime_audio.py` 209) est une liste fermée : seulement « Jarvis mute », « Jarvis stop listening », « Jarvis arrête d'écouter », phrase entière. « Passe en mode sleep / veille » n'en fait pas partie (documenté dans OPERATIONS.md : « va dormir » ne coupe pas). Le modèle GPT-Live n'a de plus aucun outil de mise en veille (`realtime_tools.py` : aucun tool sleep/mute) : il peut répondre « d'accord » sans rien faire. Je n'ai pas pu lire ses réponses du 16/10 (l'historique ne garde que les tours utilisateur).

## Correctif proposé (non appliqué)

1. Dans `check_timeout`, ne réarmer sur `_live_user_active()` que pour une parole **adressée** (propriétaire confirmé, ou tour adressé, ou barge-in confirmé), pas pour le VAD brut. Garder le maintien de 3 s pour les pauses en plein monologue, mais borné (par exemple plafond de 30 s de « voix » non adressée consécutive).
2. Ajouter un outil/commande de veille explicite côté duplex : un tool `go_to_sleep` (ou intention reconnue par le cerveau) qui appelle `mute(VoiceStopReason.IDLE)`, plus élargir `SLEEP_COMMANDS` aux formes naturelles (« mets-toi en veille », « passe en sleep », « mode veille »), en gardant la règle « phrase entière adressée ».
3. Journaliser à chaque tic d'expiration manquée la raison du report (`voice.timeout_deferred` avec `user_active`, `idle_ready`, `remaining_s`), pour que la prochaine panne soit lisible sans deviner.
4. Preuve à fournir avant de rendre : test avec VAD qui bascule en vrai toutes les 5 s sur du bruit non adressé, 60 s virtuelles, qui doit finir en `voice.background` (échoue sur le code actuel) ; puis essai réel avec le vrai fournisseur sur plusieurs tours, y compris « passe en veille ».

## Ce que je n'ai pas pu établir

- L'état réel de `live_idle_evidence` pendant les 140 s : seule la trace de l'orbe est indirecte. Un correctif devra d'abord ajouter la journalisation (point 3) ou rejouer le scénario.
- Si l'utilisateur parlait réellement ou si c'était l'écho/le bruit de la pièce : à confirmer, la conclusion tient dans les deux cas.
