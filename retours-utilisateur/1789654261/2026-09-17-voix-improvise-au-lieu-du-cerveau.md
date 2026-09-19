# La voix dit autre chose que la réponse du cerveau

- **Date** : 2026-09-17
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`

## Comportement constaté

Relevé dans le registre vocal de Core, pas signalé à l'oral. Deux fois, le texte
réellement prononcé par OpenAI Realtime n'était pas celui du cerveau :

- cerveau : « Tu as raison, je devrais m'arrêter de parler dès que tu prends la
  parole… » ; voix : « Ah, je vois ce que tu veux dire. Si ça t'interrompt pas, ça peut
  être juste un petit souci de timing… » ;
- cerveau : « C'est noté : un dossier de retours utilisateur… » ; voix, en premier :
  « D'accord, on va rester concentré sur ce que tu veux consigner, laisse-moi réfléchir
  un instant. »

## Comportement attendu

En `continuous_brain`, la voix restitue mot pour mot le texte du cerveau (Décision 13).

## Contexte

Speeches `f33fb2f4` et `3411a919`, conversation `7e3b132c`. Des traces
`voice.state.diverged` (`voice_state_generated_divergence`) accompagnent ces paroles.

## Pistes
