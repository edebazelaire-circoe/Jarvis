# Fin de phrase atténuée : JARVIS semble s'être auto-coupé

- **Date** : 2026-09-18
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`

## Comportement constaté

Quand JARVIS termine une phrase à l'oral, le volume de la fin de phrase est atténué de
façon assez forte, et cette atténuation commence trop tôt, avant la vraie fin de la
phrase. La phrase semble donc coupée, et l'utilisateur a l'impression d'avoir interrompu
JARVIS (« tu t'es encore auto-coupé ») alors qu'aucune interruption n'a eu lieu.

Ce n'est **pas** un défaut d'interruption (barge-in) : la lecture va bien jusqu'au bout,
c'est le gain audio de fin d'énoncé qui décroît trop fort et trop tôt.

## Comportement attendu

La fin de phrase reste au même niveau sonore que le reste de l'énoncé, ou bien avec un
fondu de sortie beaucoup plus court et beaucoup moins marqué.

## Contexte

Session vocale continue, constatée le 2026-09-18 en usage réel. Aucune prise de parole
de l'utilisateur au moment de l'atténuation.

## Pistes

- Un seul mécanisme touche le gain de lecture dans tout le pipeline de sortie : le
  « duck » de barge-in. Il n'existe aucun fondu de fin d'énoncé volontaire, aucune rampe
  de fin de phrase, aucune enveloppe en sortie. L'atténuation entendue est donc très
  probablement ce duck, déclenché par l'écho de JARVIS lui-même en fin de phrase, puis
  jamais relevé avant la fin de la réponse.

## Pistes techniques

- `jarvis/runtime/realtime_audio.py:493` `set_output_gain()` et
  `jarvis/runtime/realtime_audio.py:498` `_apply_gain()` : seul point d'application d'un
  gain sur le PCM joué. La rampe s'étale sur **un seul bloc de sortie**
  (`OUTPUT_CHUNK_FRAMES = 2400`, soit 100 ms à 24 kHz, `realtime_audio.py:217`), appliqué
  bloc par bloc dans la boucle d'écriture `realtime_audio.py:815`. La baisse est donc
  quasi instantanée et perçue comme une coupure, pas comme un fondu.
- Constantes du duck (`realtime_audio.py:1232-1236`, valeurs par défaut, non surchargées
  ailleurs dans le dépôt) :
  - `barge_in_duck_gain = 0.3` → environ **−10,5 dB**, c'est l'atténuation entendue ;
  - `barge_in_sustain_s = 0.6` → durée pendant laquelle la voix reste baissée avant de
    décider coupure ou reprise ;
  - `barge_in_confirm_s = 1.5` (fenêtre de confirmation) et
    `BARGE_IN_LATE_CONFIRM_S = 0.6` (`realtime_audio.py:2789`).
- Déclenchement : `_confirm_sustained_barge_in()` (`realtime_audio.py:2818-2843`) pose
  `set_output_gain(0.3)` dès que le fournisseur confirme une parole, **avant** de savoir
  si elle dure. En fin de phrase, l'écho résiduel de JARVIS ouvre facilement un candidat
  (garde `far_recent` / `tail_frames = 25` dans `jarvis/audio/duplex.py:270` et `:333`) :
  la fin d'énoncé est donc jouée à 30 % du volume.
- Retour au plein volume : seulement en trois endroits, tous tardifs par rapport à la fin
  de phrase :
  - `_reject_barge_confirmation()` `realtime_audio.py:2851-2861`, au plus tôt
    `barge_in_sustain_s` (0,6 s) après la baisse ;
  - `realtime.response_done` `realtime_audio.py:3530`, c'est-à-dire **après** la fin de la
    phrase : si la réponse se termine pendant le duck, toute la queue de phrase a été
    jouée atténuée et la remise à 1.0 n'est plus audible ;
  - coupure effective `realtime_audio.py:1568-1572` et remise à zéro `:1025`, `:3351`.
- Vérification suggérée dans le journal de la session : rechercher `voice.barge_in_confirming`
  (« volume baissé, coupure si ça dure ») suivi de `voice.barge_in_rejected` ou d'un
  `response_done` sans coupure. Si ces deux traces encadrent chaque fin de phrase
  atténuée, le diagnostic est confirmé.
- Pistes de correction possibles (non appliquées) : ne pas ducker tant que la sortie est à
  moins de N ms de sa fin, rendre `barge_in_duck_gain` moins agressif, étaler la rampe sur
  plusieurs blocs, et/ou resserrer la garde d'écho de fin d'énoncé (`tail_frames`).

Aucun code n'a été modifié : diagnostic uniquement.

## Résolution (2026-09-18)

Le diagnostic ci-dessus était incomplet : ce n'était **pas** seulement une
atténuation. La trace de la session `7e3b132c` montre treize `voice.barge_in`
réellement exécutés dans la journée, dont sept entre 16:27 et 16:31 à 0,7 –
1,5 s du début de la phrase (`played_ms` : 718, 818, 1018, 1318, 1318, 1318,
1418, 1518). Le tour était donc bel et bien marqué interrompu.

### Cause réelle

La chaîne complète, lue dans la trace :

1. l'écho résiduel de la voix de JARVIS franchit le `NearEndDetector` — le
   plancher est collé à `FLOOR_MIN_DB` (−70 dB), la barre effective est donc
   d'environ −58 dBFS, et les trames relevées à l'ouverture des candidats
   montent à −24 à −36 dBFS ;
2. la garde d'écho s'ouvre et déverse son pré-roll (400 ms, surtout de l'écho)
   vers OpenAI ;
3. le VAD du fournisseur émet `speech_started` ; le bridge baisse le volume ;
4. `barge_in_sustain_s` plus tard, la « preuve de durée » ne relisait que
   `_user_speaking`, **c'est-à-dire le verrou du VAD du fournisseur**, que ce
   même écho tient ouvert bien plus longtemps que la fenêtre. La condition
   était donc toujours vraie : la coupure était acquise dès la première
   bouffée d'écho.

La preuve : des coupures confirmées avec un micro à −79,1, −93,0 et
−103,3 dBFS au moment de la décision, c'est-à-dire du silence
(`voice.barge_in_confirming` de 13:34:19, 16:29:59, 16:32:40).

Le gain n'était que le symptôme : `set_output_gain(0.3)` posé à la
confirmation, puis rendu au mieux 0,6 s plus tard — ou jamais, quand la
réponse se terminait pendant la fenêtre.

### Correctif

La preuve exigée est désormais **locale et mesurée pendant la fenêtre**, tous
les 50 ms, à partir des compteurs de la capture
(`CaptureProcessor.processed_frames` / `voiced_frames`, nouveaux) :

- il faut `barge_in_min_voiced_ms` de trames réellement « proches » ;
- la plus forte doit dépasser ses bornes d'au moins `barge_in_min_margin_db` ;
- un trou de silence de plus de `barge_in_silence_grace_ms` referme le
  candidat **immédiatement** et rend le volume, sans attendre la fin de la
  fenêtre ;
- toute fin de sortie pendant la fenêtre rend le volume tout de suite : une
  fin de phrase ne peut plus rester atténuée jusqu'à son terme ;
- une voix tenue rejetée pour une autre raison n'est plus apprise comme de
  l'écho (le détecteur deviendrait sourd au locuteur).

Compteurs figés (capture arrêtée, rejeu hors ligne) ou absence de capture
duplex : aucune preuve locale n'est exigeable, la décision reste celle d'avant.
Le barge-in reste donc possible partout ; il est seulement plus exigeant.

### Seuils réglables

| Variable | Défaut | Avant | Effet |
| --- | --- | --- | --- |
| `JARVIS_BARGE_IN_CONFIRM_S` | `1.5` | 1.5 | attente d'un `speech_started` après un candidat acoustique |
| `JARVIS_BARGE_IN_SUSTAIN_S` | `0.9` | 0.6 | durée que la parole doit tenir avant de couper |
| `JARVIS_BARGE_IN_DUCK_GAIN` | `0.6` | 0.3 | gain pendant la preuve (0,6 ≈ −4,4 dB au lieu de −10,5 dB) |
| `JARVIS_BARGE_IN_MIN_VOICED_MS` | `350` | — | voix locale cumulée exigée dans la fenêtre |
| `JARVIS_BARGE_IN_SILENCE_GRACE_MS` | `300` | — | silence toléré avant rejet immédiat et retour du volume |
| `JARVIS_BARGE_IN_MIN_MARGIN_DB` | `6.0` | — | dépassement le plus fort exigé sur la fenêtre |
| `JARVIS_BARGE_IN_POLL_MS` | `50` | — | pas d'échantillonnage de la preuve |
| `JARVIS_NEAR_END_FLOOR_MARGIN_DB` | `12.0` | 12.0 | marge au plancher de bruit du détecteur |
| `JARVIS_NEAR_END_ECHO_MARGIN_DB` | `10.0` | 10.0 | marge au-dessus de l'écho attendu |
| `JARVIS_NEAR_END_MIN_RUN_MS` | `60` | 60 | durée d'affilée exigée pour verrouiller un candidat |

Si l'écho continue d'ouvrir des candidats sur ce poste, monter
`JARVIS_NEAR_END_ECHO_MARGIN_DB` de 3 à 6 dB agit à la source ; si le
barge-in devient trop dur, baisser `JARVIS_BARGE_IN_MIN_VOICED_MS` et
`JARVIS_BARGE_IN_SUSTAIN_S`.

### Nouveaux codes de trace

`voice.barge_in_rejected` porte maintenant `ducked_ms`, `voiced_ms`,
`peak_margin_db` et l'un des codes `barge_in_local_voice_gone`,
`barge_in_local_voice_too_short`, `barge_in_local_voice_too_weak`, en plus des
codes existants. `voice.barge_in_confirming` porte `local_evidence` : faux
signifie qu'aucune preuve locale n'était disponible.

### Vérification

`tests/unit/test_barge_in_sustain.py` : bouffée courte qui ne coupe pas et rend
le volume avant la fin de la fenêtre, parole soutenue qui coupe, voix trop
faible qui ne coupe pas, pile sans preuve locale qui garde l'ancienne décision,
et les seuils lus depuis l'environnement. Suite unitaire complète passée.

**Non vérifié** : un tour réel contre le vrai service OpenAI sur ce poste.
Le correctif ne prend effet qu'au prochain démarrage du serveur vocal.
