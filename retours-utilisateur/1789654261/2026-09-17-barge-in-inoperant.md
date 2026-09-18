# Barge-in inopérant : la voix de JARVIS ne se coupe pas

- **Date** : 2026-09-17
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`

## Comportement constaté

En session vocale réelle, l'utilisateur a parlé pendant que JARVIS répondait à voix haute,
et la synthèse vocale ne s'est pas arrêtée.

## Comportement attendu

Dès que l'utilisateur prend la parole, la voix de l'agent se coupe et l'agent écoute.

## Contexte

Un diagnostic est en cours dans une autre tâche ; ne pas le dupliquer.

## Pistes

- Trace de la session (16:14:25 à 16:14:37) : cinq candidats locaux rejetés faute de
  confirmation d'OpenAI dans les 0,8 s ; le `speech_started` du cinquième est arrivé
  140 ms trop tard et a été ignoré, garde d'écho fermée. Chaque rejet apprenait en plus
  la voix de l'utilisateur comme de l'écho.
- Mesure contre le vrai OpenAI Realtime (`gpt-realtime-2.1-mini`, motif de la garde :
  silence, pré-roll 400 ms, direct) : confirmation entre 225 et 818 ms.
- Correctif (2026-09-17, non commité) : fenêtre portée à 1,5 s, confirmation tardive
  acceptée 0,6 s après la fenêtre, premier rejet sans apprentissage du couplage
  (`jarvis/runtime/realtime_audio.py`, `jarvis/audio/duplex.py`). Reste à valider au micro.
