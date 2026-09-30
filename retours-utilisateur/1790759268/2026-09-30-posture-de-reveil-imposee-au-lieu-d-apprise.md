# La posture de réveil est imposée au lieu d'être apprise sur la main

- **Date** : 2026-09-30
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`
- **Contexte** : calibration Bare Hands, étape « Posture de réveil » (`c_pose`).

## Constaté

L'exercice échoue avec « index pas assez déplié » et « trois autres doigts trop
dépliés ». Mesures : écart pouce-index 0,511 paume (jugé bon), repli des trois
autres doigts 1,817 paume. Ce repli dépasse la borne maximale réglable (1,8).

Deux sorties ont été proposées, et l'utilisateur les a refusées :

- replier ses doigts pour faire le C imposé ;
- élargir les seuils de repli.

Ses mots : « C'est pas moi de me conformer à quoi ressemble la posture de
réveil. C'est à la posture de réveil de se conformer à ma main. » Puis : « tu
dois prendre une photo de ma main, de ma posture de réveil, et c'est ça qui doit
faire source de validité […] c'est ça qu'il faut retrouver. »

## Attendu

L'étape « Posture de réveil » enregistre la posture que fait l'utilisateur, et
c'est cette posture qui sert ensuite de référence pour le réveil. Sa posture
naturelle réveille le curseur sans qu'il change de geste. Une main ouverte ou
au repos ne réveille rien.

## Pistes

- Corrigé le 2026-09-30 : décision 72 de `docs/barehands-contracts.md`.
  - L'étape relève six distances de la main, mesurées en paumes, plus une
    tolérance.
  - Cette signature devient la posture de réveil : elle est appliquée au
    moteur tout de suite, puis rangée dans le profil (`wake_posture`).
  - La preuve est dans `tests/unit/test_barehands_learned_wake_posture.py`.
- La « photo » est remplacée par cette signature, parce que la décision 32
  interdit de conserver une image ou des points de main. Aucune image n'est
  gardée.
- L'étape ne refuse plus que trois cas, et dit chaque fois pourquoi :
  - la posture est en fait un pincement ;
  - elle ressemble trop à la main au repos de l'étape 1 ;
  - la main a bougé pendant la tenue.
- Pas encore vérifié avec la vraie main de l'utilisateur devant la caméra.
  Pour le faire :
  - recharger la page, puis relancer la calibration ;
  - vérifier que l'exercice « bouger sans cliquer » compte zéro réveil non
    voulu ;
  - vérifier que la posture réveille bien Bare Hands depuis la veille.
