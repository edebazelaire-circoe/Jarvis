# JARVIS se coupe lui-même sans arrêt : l'annulation d'écho et l'enceinte Bluetooth — 2026-09-19

Session `runtime/trace.jsonl`, 15:19 → 16:45 UTC. Symptôme rapporté : « le AEC ne
fonctionne pas du tout, JARVIS n'arrête pas de s'interrompre ».

## Le poste

| | |
|---|---|
| Sortie | **Bose Flex SoundLink**, liaison **Bluetooth**, hôte MME, latence déclarée 180 ms |
| Entrée | **Microphone (UGREEN Camera)**, hôte MME, latence déclarée 180 ms |
| Annulation d'écho | active (`voice.duplex`, `duplex_aec`), `livekit.rtc` se charge |

Ni casque, ni micro proche : une enceinte sans fil et un micro de webcam, les
deux conditions les plus hostiles qu'une annulation d'écho puisse rencontrer.

## Ce que la trace dit

`voice.barge_in_pending` et `voice.barge_in_confirming` portent les niveaux
depuis le 18/09. Sur les 66 événements du 19/09 :

| grandeur | valeur |
|---|---|
| `near_coupling_db` médian | **−59,5 dB** (minimum de l'apprentissage : −60) |
| `near_excess_db` au moment d'un candidat | **−6 à −23 dB** |
| `near_floor_db` | −70,0 partout (plancher de l'apprentissage) |
| candidats avec `near_ref_env_db` ≤ −100 | 9 sur 66 (13 %) |

Deux mécanismes distincts, et ils suffisent à tout expliquer.

**1. Le couplage appris décrit le calme, pas la bouffée.** L'annuleur retire
cinquante décibels la plupart du temps ; le couplage, une moyenne glissante,
apprend donc −59,5 dB. Mais il lâche par bouffées, et pendant ces bouffées
l'écho remonte à −6 dB de ce qui est joué. La bouffée franchit la marge de
trente décibels, devient « l'utilisateur parle », et JARVIS se coupe. Le
couplage rattrapait bien le niveau entendu à chaque récusation du bridge
(18/09, `release(learn=True)`), mais la moyenne le ramenait sous la bouffée en
deux secondes : la suivante rouvrait la garde. Sans jamais converger — c'est
exactement la boucle rapportée.

**2. La référence se tait pendant que la pièce résonne encore.** La référence
remise à l'annuleur est le bloc REMIS AU PÉRIPHÉRIQUE. Entre ce moment et le son
dans la pièce il y a le tampon du pilote (180 ms) **et la liaison Bluetooth**
(150 à 300 ms de plus, invisibles de PortAudio). À la fin de chaque phrase la
référence s'arrête une demi-seconde avant l'enceinte. Le détecteur voit alors
`ref_env` à −120 dB, juge le micro contre le seul plancher de bruit (−70 dB), et
l'écho à −29 dB le franchit de quarante décibels. Neuf des candidats du 19/09
sont de cette forme, dont deux `voice.barge_in` avec `speech_id: null` : JARVIS
a été coupé alors que, de son point de vue, il ne jouait plus rien.

## La mesure qui manquait

L'avance de la référence sur l'écho est le paramètre dont dépend toute
l'annulation, et elle n'était ni réglée, ni mesurée, ni visible. Mesurée ici sur
AEC3 lui-même (`WebRtcEchoCanceller`, chemin de production, 16 s de voix
synthétique, écho à −12 dB avec deux réflexions et la saturation d'un
haut-parleur) :

| avance de la référence | ERLE | résidu médian | résidu p95 |
|---|---|---|---|
| −250 ms | 4,1 dB | −27,6 dB | **+6,3 dB** |
| −100 ms | 5,2 dB | −25,0 dB | **+5,2 dB** |
| −50 ms | 6,9 dB | −30,9 dB | **−7,1 dB** |
| 0 ms | 10,5 dB | −51,6 dB | **−6,9 dB** |
| **+25 ms** | **24,3 dB** | −65,5 dB | **−46,2 dB** |
| +50 ms | 25,7 dB | −65,7 dB | −45,8 dB |
| +200 ms | 20,9 dB | −65,1 dB | −45,3 dB |
| +300 ms | 36,2 dB | −65,1 dB | −45,7 dB |

La falaise est à +25 ms. En dessous, le résidu médian reste bas — l'annuleur a
l'air de marcher — mais le p95 monte à −7 dB : le profil exact que la trace du
poste montre. Au-dessus, le p95 est à −45 dB et aucune marge n'est franchie.

## Les correctifs

- **`NearEndDetector._learn_coupling`** : le couplage suit un **percentile haut**
  (90 par défaut) des résidus des six dernières secondes de parole de JARVIS, au
  lieu d'une moyenne glissante. Il décrit la bouffée, pas le calme entre deux
  bouffées. Il ne bouge pas avant `COUPLING_MIN_FRAMES` résidus : une syllabe ne
  décrit pas une pièce, et sans ce seuil la première de l'utilisateur
  apprendrait au détecteur que la pièce lui renvoie une voix.
- **Une trame « proche » est apprise comme les autres** tant que rien n'est
  verrouillé. Écarter les bouffées de l'apprentissage sous prétexte qu'elles
  ressemblent à de la parole était circulaire : c'est précisément ce qui
  empêchait de les apprendre.
- **`_released_db`** : le niveau qu'une récusation a prouvé n'est plus soumis au
  percentile et ne s'efface qu'à 0,2 dB par seconde de parole de JARVIS. Il
  tient le temps que le percentile décrive la pièce à son tour ; l'ancienne
  moyenne l'effaçait en deux secondes.
- **`EchoDelayEstimator`** : l'avance de la référence sur l'écho est mesurée en
  continu, par corrélation des enveloppes en dB du micro BRUT et de la référence
  (500 trames, une mesure par seconde, jamais d'audio gardé). Elle sert à deux
  choses, et seulement deux : le détecteur compare le micro à la référence
  **telle qu'elle est audible** — donc retardée de cette avance, ce qui referme
  le trou de la fin de phrase — et elle part dans la trace
  (`voice.echo_alignment`, `near_echo_lead_ms`), à côté de la latence que le
  pilote déclare. L'annuleur, lui, garde la référence en avance : c'est ce dont
  il a besoin.
- Une avance **négative** — l'écho qui précède sa propre référence, hors de
  portée de tout annuleur — est reportée telle quelle : c'est un défaut de la
  chaîne, et il doit se voir.

## Ce que cela change, mesuré

Même scénario (référence continue, résidu à −55 dB, bouffées de 150 ms à −8 dB
toutes les 1,2 s, chaque candidat récusé par le bridge comme en production) :

| règle d'apprentissage | faux barge-in | couplage final |
|---|---|---|
| moyenne glissante (avant) | **11**, un par bouffée, sans fin | −54,6 dB |
| percentile + preuve (après) | **1**, la première | −8,6 dB |

Et sur la chaîne complète (AEC3 réel, 22 s, écho à −12 dB avec réflexions et
saturation, l'utilisateur parle de 16 à 18,5 s, chaque candidat récusé) :

| avance de la référence | règle | faux barge-in | l'utilisateur est entendu |
|---|---|---|---|
| +400 ms (annuleur en état) | avant | 0 | oui |
| +400 ms | après | 0 | oui |
| 0 ms (annuleur hors d'état) | avant | **2** | oui |
| 0 ms | après | **0** | oui |

L'estimateur, sur ce même scénario, mesure l'avance à 400 ms exactement
(corrélation 0,73).

`tests/unit/test_voice_duplex.py` :
`test_a_bursty_residual_stops_cutting_jarvis_after_one_rejection`,
`test_the_trailing_echo_of_a_distant_speaker_never_opens_the_guard`,
`test_the_estimator_reports_an_echo_that_precedes_its_own_reference`.

## Réglages

| variable | défaut | ce qu'elle fait |
|---|---|---|
| `JARVIS_ECHO_ALIGN` | actif | `0` coupe l'estimateur et l'alignement du détecteur |
| `JARVIS_NEAR_END_COUPLING_PERCENTILE` | 90 | plus haut = plus prudent sur l'écho |
| `JARVIS_NEAR_END_RELEASE_DECAY_DB_S` | 0,2 | vitesse d'oubli d'une preuve, par seconde de parole |
| `JARVIS_NEAR_END_ECHO_MARGIN_DB` | 10 | marge au-dessus de l'écho attendu |
| `JARVIS_NEAR_END_FLOOR_MARGIN_DB` | 12 | marge au-dessus du plancher de bruit |

## Limites

La première bouffée d'un niveau jamais entendu coupe encore JARVIS : aucune
fenêtre ne peut décrire un écho avant de l'avoir entendu. Ce qui change est
qu'elle est apprise pour de bon au lieu d'être oubliée en deux secondes.

Le sens de l'échec est maintenant le bon : quand l'annulation ne fait pas son
travail, JARVIS devient **dur à interrompre** au lieu de s'interrompre tout
seul. Sur une enceinte Bluetooth, couper JARVIS peut donc demander de parler
plus près du micro. La vraie sortie est ailleurs — un casque, ou une sortie
filaire, ramène l'avance de la référence dans la zone où AEC3 retire cinquante
décibels — et `voice.echo_alignment` est là pour dire laquelle des deux
situations est en cours.
