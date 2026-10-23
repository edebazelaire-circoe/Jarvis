# Réglages : Personnalisation et ses destinations

**Statut :** contrat de surface (niveau 3 : métadonnées serveur + tests de conformité).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 03.
**S'appuie sur :** [`navigation-registry.md`](navigation-registry.md) (sections réservées), [`settings-shell.md`](settings-shell.md)
(montage d'une section), [`../voice-settings-schema.md`](../voice-settings-schema.md) (schéma Voix, inchangé).

- Destination de chaque option : `surface` de `voice.option_metadata`, décrite par le serveur
  (`jarvis/runtime/voice_settings_schema.py` : `SURFACE_SECTIONS`, `_SURFACE`, `_SURFACE_CONTEXT`). Une option
  persistable ou un diagnostic sans destination lève `RuntimeError` à la construction du schéma.
- Sections : `control_center.html` (`VOICE_SECTIONS`, `voiceSectionSpec`, section `diagnostics` et
  `registerSettingsDiagnostic`), `control_center_wake_word.js` (section `wake_word` et sa partie de diagnostic).
- Conformité : `tests/unit/test_voice_settings_surface.py` (une destination par option, servie par la page, table
  ci-dessous = serveur), `tests/unit/test_voice_settings_ui.py` (chaque option rendue une fois dans sa section),
  `tests/unit/test_wake_word_settings_browser.py` (section Mot d'éveil et diagnostic en vrai Chrome).

## 1. Ce que voit un utilisateur ordinaire

`voice_audio` (Personnalisation) n'a plus d'onglet `Voix` ni de sous-onglets techniques : cinq sections orientées tâche.

| Section | Contenu |
| --- | --- |
| `conversation` · Conversation | qui peut parler à JARVIS (mode, vérification du locuteur), accusé de réception réflexe, mise en veille, durée de session Duplex |
| `voice_output` · Voix & transcription | modèles de conversation (selon l'architecture), modèle et voix des piles, transcription, catalogue comparatif des modèles vocaux (replié) |
| `microphone_sound` · Micro & son | micro, haut-parleur, réduction de bruit, annulation d'écho, test sur les périphériques choisis, erreurs de détection avec « réessayer » |
| `turns_interruptions` · Tours & interruptions | fin de tour, type de détection de parole, qui coupe la voix de JARVIS ; touche `wake_toggle` en lecture seule + lien |
| `wake_word` · Mot d'éveil | activer, moteur, phrase, sensibilité, pause après un réveil ; avis de redémarrage de Voice |

- Les quatre premières sont `save: 'footer'` : elles écrivent dans le brouillon partagé (`SET.draft`) et le bouton
  « Enregistrer » envoie `/api/settings` exactement comme l'ancien onglet (charge utile inchangée, champs inconnus
  et pile inactive préservés). Le brouillon survit aux changements de section et de catégorie.
- Moment d'application : badge « Au prochain démarrage de Voice » (`applies: 'next_voice_start'`) ; après un
  enregistrement qui l'exige, ou quand Voice applique encore d'anciens réglages, la notice « Redémarrez Voice pour
  appliquer ».
- `wake_word` est `save: 'self'` : la route `/api/wake-word` est inchangée (cinq champs ensemble, dernier écrit
  gagne, refus traduits, saisie gardée). La saisie survit à un changement de section.
- La ligne « Réglages de la voix » de la roue Jarvis ouvre la catégorie `voice_audio` (Conversation à la première
  ouverture). Les anciens ID `voice` et `wakeword` ne sont plus des alias depuis la Slice 09 (aucun appelant).

## 2. Ce qui part dans Avancé & Diagnostics

| Section | Contenu |
| --- | --- |
| `architecture_compat` · Architecture & compatibilité | architecture vocale (`simple`, `front_brain`, `duplex`) et ses invariants (délégation client, orchestration cerveau, deltas spéculatifs, effort), retour au cerveau Claude, pile et mode historiques, réglage fin VAD et du vérificateur de locuteur. Même pied « Enregistrer » que Personnalisation. |
| `diagnostics` · Diagnostics | lecture seule, faite de parties (`registerSettingsDiagnostic`) : Voix (autorisation, vérificateur, worker, annulation d'écho, bascule de pile, catalogue/adaptateur, disponibilité, profil vocal) et Mot d'éveil (état du bloc lu, version illisible, clés ignorées, dernier événement du détecteur dans le journal, « Actualiser »). |

La Slice 08 affine ces deux sections ; elle range ses autres diagnostics comme des parties de `diagnostics`.

## 3. Un seul éditeur pour `wake_toggle`

Le raccourci réveiller / envoyer / interrompre est persisté par le registre des raccourcis : son éditeur est
la section Raccourcis (`interface_interactions` › `shortcuts`, Slice 06 :
[`interface-interactions.md`](interface-interactions.md)). Le lien pose le focus sur la touche `wake_toggle`. Personnalisation
en montre la touche effective en lecture seule et un lien « Modifier dans … » (`surface.context`).

## 4. Table de correspondance option → section

Générée depuis le serveur ; `test_the_documented_mapping_is_the_server_mapping` échoue si elle diverge.

| Option | Destination | Libellé |
| --- | --- | --- |
| `voice_stack` | `advanced_diagnostics` › `architecture_compat` | Pile vocale de compatibilité |
| `voice_arch` | `advanced_diagnostics` › `architecture_compat` | Mode vocal historique |
| `architecture` | `advanced_diagnostics` › `architecture_compat` | Architecture vocale |
| `conversation_model` | `voice_audio` › `voice_output` | Conversation |
| `reflex_model` | `voice_audio` › `voice_output` | Réflexe conversationnel |
| `analysis_model` | `voice_audio` › `voice_output` | Analyse |
| `speculative_deltas` | `advanced_diagnostics` › `architecture_compat` | Analyse des transcriptions provisoires |
| `reasoning_effort` | `advanced_diagnostics` › `architecture_compat` | Effort de raisonnement |
| `client_delegation` | `advanced_diagnostics` › `architecture_compat` | Délégation client active |
| `idle_timeout_s` | `voice_audio` › `conversation` | Fermeture après inactivité (secondes) |
| `brain_orchestration` | `advanced_diagnostics` › `architecture_compat` | Déléguer au cerveau (outils et sous-agents) |
| `barge_in_decider` | `voice_audio` › `turns_interruptions` | Quand je parle par-dessus JARVIS : qui le fait taire ? |
| `openai.model` | `voice_audio` › `voice_output` | Modèle Realtime |
| `openai.voice` | `voice_audio` › `voice_output` | Voix |
| `openai.turn_mode` | `voice_audio` › `turns_interruptions` | Fin de tour |
| `openai.transcription_model` | `voice_audio` › `voice_output` | Transcription de votre voix |
| `openai.transcription_language` | `voice_audio` › `voice_output` | Langue de transcription |
| `openai.noise_reduction` | `voice_audio` › `microphone_sound` | Réduction de bruit |
| `openai.echo_cancellation` | `voice_audio` › `microphone_sound` | Annulation d'écho (mode continu) |
| `openai.reflex_enabled` | `voice_audio` › `conversation` | Cerveau réflexe (mode continu) |
| `openai.ack_delay_ms` | `voice_audio` › `conversation` | Délai avant accusé de réception (ms) |
| `openai.vad_type` | `voice_audio` › `turns_interruptions` | Détection de fin de tour |
| `openai.vad_eagerness` | `advanced_diagnostics` › `architecture_compat` | Réactivité (semantic_vad) |
| `openai.vad_threshold` | `advanced_diagnostics` › `architecture_compat` | Seuil de détection de parole |
| `openai.vad_prefix_padding_ms` | `advanced_diagnostics` › `architecture_compat` | Audio conservé avant la parole (ms) |
| `openai.vad_silence_duration_ms` | `advanced_diagnostics` › `architecture_compat` | Silence qui clôt le tour (ms) |
| `gemini.model` | `voice_audio` › `voice_output` | Modèle Live |
| `gemini.voice` | `voice_audio` › `voice_output` | Voix |
| `gemini.turn_mode` | `voice_audio` › `turns_interruptions` | Fin de tour |
| `gemini.input_transcription` | `voice_audio` › `voice_output` | Transcrire votre voix |
| `gemini.output_transcription` | `voice_audio` › `voice_output` | Transcrire les réponses |
| `gemini.vad_start_sensitivity` | `advanced_diagnostics` › `architecture_compat` | Sensibilité au début de parole |
| `gemini.vad_end_sensitivity` | `advanced_diagnostics` › `architecture_compat` | Sensibilité à la fin de parole |
| `gemini.vad_prefix_padding_ms` | `advanced_diagnostics` › `architecture_compat` | Audio conservé avant la parole (ms) |
| `gemini.vad_silence_duration_ms` | `advanced_diagnostics` › `architecture_compat` | Silence qui clôt le tour (ms) |
| `conversation_mode` | `voice_audio` › `conversation` | Mode de conversation |
| `speaker_verification` | `voice_audio` › `conversation` | Vérification du locuteur |
| `owner_buffer_ms` | `advanced_diagnostics` › `architecture_compat` | Tampon de rejeu du propriétaire (ms) |
| `owner_threshold` | `advanced_diagnostics` › `architecture_compat` | Seuil de reconnaissance |
| `owner_evidence_ms` | `advanced_diagnostics` › `architecture_compat` | Fenêtre de preuve (ms) |
| `owner_short_evidence_ms` | `advanced_diagnostics` › `architecture_compat` | Réponse brève : parole minimale (ms) |
| `owner_short_margin` | `advanced_diagnostics` › `architecture_compat` | Réponse brève : marge du seuil |
| `owner_profile_path` | `advanced_diagnostics` › `diagnostics` | Profil vocal |
| `audio_input_device` | `voice_audio` › `microphone_sound` | Microphone |
| `audio_output_device` | `voice_audio` › `microphone_sound` | Haut-parleur |
| `active_timeout_s` | `voice_audio` › `conversation` | Mise en veille après inactivité |
| `wake_toggle` | `interface_interactions` › `shortcuts` | Réveiller / envoyer / interrompre — touche montrée en lecture seule dans `turns_interruptions` |
| `authorization.status` | `advanced_diagnostics` › `diagnostics` | État de l'autorisation |
| `authorization.runtime` | `advanced_diagnostics` › `diagnostics` | Autorisation appliquée par Voice |
| `authorization.verifier` | `advanced_diagnostics` › `diagnostics` | État du vérificateur vocal |
| `authorization.worker` | `advanced_diagnostics` › `diagnostics` | État du worker de vérification |
| `echo_cancellation.status` | `advanced_diagnostics` › `diagnostics` | État de l'annulation d'écho |
| `switch.status` | `advanced_diagnostics` › `diagnostics` | État du changement de pile |
| `catalog.source` | `advanced_diagnostics` › `diagnostics` | Source du catalogue modèles |
| `model.adapter_status` | `advanced_diagnostics` › `diagnostics` | État de l'adaptateur modèle |
| `model.availability` | `advanced_diagnostics` › `diagnostics` | Disponibilité du modèle |
