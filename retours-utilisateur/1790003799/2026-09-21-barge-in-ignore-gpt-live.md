# GPT-Live : JARVIS ne se tait pas quand on lui parle par-dessus, et l'orbe reste bleu

- **Date** : 2026-09-21, vers 15h20-15h24 UTC
- **Mode vocal** : pile `openai_realtime`, modèle `gpt-live-1`, architecture `duplex`
  (garde d'écho + AEC actifs : `voice.duplex` `duplex_aec`), autorité de barge-in `acoustic`
- **Session** : conversation `fb1d4135-5e13-4a6f-bd34-95d18e1c2e12`, session `deffc006-4497-430a-afce-a433e54ede96`

## Comportement constaté

Mots de l'utilisateur, vers 15h22 : « ça fait deux fois que je parle et que tu t'interromps
pas, comment ça se fait ». Pendant que JARVIS parlait, l'utilisateur a pris la parole deux
fois, et JARVIS a continué de parler.

Symptôme lié, vers 15h24 : « là je suis en train de te parler et je sais que tu m'entends,
mais le state est bleu. [Il faut que tu sois] en state où l'utilisateur parle, c'est-à-dire
vert avec les waves ». Pendant qu'il parle, l'orbe reste bleu (veille) au lieu de passer au
vert animé (écoute).

## Comportement attendu

- Quand l'utilisateur parle par-dessus JARVIS, JARVIS se tait.
- Quand l'utilisateur parle, l'orbe passe au vert avec les ondes.

## Ce que montre la trace (`runtime/trace.jsonl`)

- Cinq candidats de barge-in locaux (`voice.barge_in_pending`, autorité `acoustic`) à
  15:20:38, 15:20:53, 15:20:56, 15:21:12 et 15:21:14, tous suivis d'un
  `voice.barge_in_rejected` avec le code `barge_in_not_confirmed`, 1,5 s plus tard. Le
  détecteur local avait bien entendu une voix : marges de +6,9, +19,7, +9,7, +6,2 dB, et
  le dernier rejet affiche un micro à −30,5 dBFS avec une marge de +27,5 dB.
- Aucun `voice.barge_in_confirming`, `voice.barge_in` ni `voice.speech_started`. Pourtant
  GPT-Live a bien entendu l'utilisateur : ses phrases ont été transcrites et envoyées au
  cerveau à 15:21:20 (« Est-ce que tu vois quel item je suis en train de sélectionner ») et
  à 15:21:52 (la plainte ci-dessus).
- Même chose sur tout le fichier : depuis le passage à `gpt-live-1` en duplex ce matin
  (sessions de 07h42 à 15h16 UTC), 10 candidats et **10 rejets `barge_in_not_confirmed`**.
  Zéro `voice.speech_started`. Le dernier barge-in réussi date du 2026-09-14, avec la pile
  Realtime classique.
- Les rejets n° 2 à 5 ont `learned: true` : la capture apprend donc la voix de
  l'utilisateur comme de l'écho, ce qui rend les candidats suivants plus difficiles à ouvrir.

## Cause probable

Avec l'autorité acoustique, le barge-in exige que le fournisseur confirme la parole par un
`realtime.speech_started` dans les `barge_in_confirm_s` (1,5 s) qui suivent le candidat
local (`RealtimeConversationBridge._on_near_end` → `_on_barge_timeout`,
`jarvis/runtime/realtime_audio.py`). **Le fil GPT-Live n'émet jamais ce signal.**
`OpenAILiveFrontend._handle` (`jarvis/adapters/openai_live_frontend.py`) ne connaît pas
d'évènement de VAD, et déclare `supports_native_interruptions=False`.
`LiveFrontendSession._legacy_events` (`jarvis/runtime/live_frontend_session.py`) ne
traduit la parole de l'utilisateur qu'en `realtime.transcript_delta`, que le bridge traite
comme une activité ambiante (`on_ambient`, ligne ~3963). Aucun chemin ne peut donc
confirmer le candidat : en duplex, le barge-in ne peut jamais aboutir. Ce n'est pas un
réglage de seuil.

L'orbe bleu vient probablement de la même absence. L'état « l'utilisateur parle »
(`_note_user_speech` → `on_user_speech`) et le retour à l'écoute sur début de parole ne
sont déclenchés que par `realtime.speech_started`. En GPT-Live, la parole de l'utilisateur
n'allume donc rien, et l'orbe reste sur la veille (bleu, `visual_idle`) posée auparavant.
Le correctif des couleurs `1e7d6d4` (« vert à l'écoute, violet quand JARVIS agit ») est
déjà fusionné dans `main` depuis 12:00 (+02:00), et le JARVIS lancé à 15:16 UTC l'avait.
Il ne couvre pas ce cas : il traite l'orange collé et le violet jamais relâché, pas la
détection du début de parole de l'utilisateur.

L'hypothèse initiale (garde d'écho ou AEC livekit trop agressifs) est **écartée comme
cause principale**. La garde était ouverte (`near_guard_open: true`), GPT-Live a bien reçu
et transcrit la voix, et le candidat local a bien été levé. C'est la confirmation qui ne
peut pas venir.

## Pistes (non implémentées, aucun code modifié)

- Donner au fil Live un équivalent de début de parole. Par exemple, traduire le premier
  `UserTranscriptDelta` d'un segment d'entrée en signal de parole utilisateur, ou tirer
  parti d'un évènement du fournisseur s'il en existe un. Il servirait à la fois à
  confirmer le barge-in et à allumer l'état « l'utilisateur parle ».
- Ou bien, en duplex, laisser la preuve locale seule (voix tenue et marge d'énergie,
  `_decide_sustained_barge_in`) décider sans attendre de `speech_started`, avec le même
  garde-fou anti-écho du 18/09.
- Ne pas faire apprendre le couplage sur un rejet `barge_in_not_confirmed` quand le fil ne
  peut structurellement pas confirmer.
- Test de non-régression à écrire : `LiveFrontendSession` et le bridge en duplex, un
  candidat `near_end` pendant que JARVIS joue, puis des deltas de transcription
  utilisateur. Attendu : `voice.barge_in` et arrêt de la lecture. Aujourd'hui, il
  échouerait sur `barge_in_not_confirmed`.

## Observation annexe

Chaque réponse du cerveau dite par GPT-Live finit en `voice.speech.output_stalled` puis
`interrupted`, avec `played_ms: 0`, 30 s après son début. Les sorties Live ne portent pas de
`speech_id`. Le cerveau reçoit alors « PAS ENCORE DIT » pour des réponses que l'utilisateur
a probablement déjà entendues. C'est à vérifier séparément.
