# Le lecteur du Presentation Studio est pauvre en commandes, se bloque et se met en pause quand l'utilisateur parle

- **Date** : 2026-10-11
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`
- **Contexte** : lecteur du Presentation Studio dans le Control Center, lecture en rôle « Jarvis présente ».

## Constaté

Ses mots (voix, transcription brute) : « Je trouve que l'UI du lecteur est très
naze. Déjà des fois ça se bloque au bout de quelques secondes. Je trouve que ça
manque de boutons pratiques. Par exemple quand j'appuie sur la flèche droite, ça
devrait passer à la slide suivante ; flèche gauche : retour au début de la
slide ; double gauche : la slide d'avant. Des petits trucs comme ça qui
manquent. Il manque aussi des boutons dans la barre : un pour mettre en plein
écran, un pour avancer un peu dans le temps, pour changer des trucs. Le bouton
lecture est vraiment très bizarre : pourquoi t'as pas fait une icône play /
pause ? Il y a encore pas mal de boulot à ce niveau-là. »

Faits relevés dans la session :

- La lecture se bloque parfois au bout de quelques secondes. En rôle « Jarvis
  présente », elle se met en pause dès que l'utilisateur parle (cause dans le
  code : `_absorb` / `_interrupt` de `presentation_studio_presenter`,
  interruption « allow »).
- En plein écran, la bande d'état du lecteur est cachée : la pause n'est donc
  pas expliquée.
- Le plein écran exige un clic et se ferme parfois.
- Aucun outil ne règle l'interruption d'un item après coup.
- Raccourcis clavier absents : flèche droite, flèche gauche.
- Barre de commandes : pas de bouton plein écran, pas de bouton « avancer un peu
  dans le temps ». Le bouton de lecture n'a pas d'icône play / pause.

## Attendu

- La lecture ne se bloque pas toute seule. Si elle se met en pause, la raison
  est visible, y compris en plein écran.
- Flèche droite : slide suivante. Flèche gauche : retour au début de la slide
  en cours. Double flèche gauche : slide précédente.
- La barre porte un bouton plein écran, un bouton pour avancer un peu dans le
  temps, et d'autres réglages pratiques.
- Un seul bouton lecture, avec une icône play / pause qui reflète l'état.
- Le plein écran ne se ferme pas de lui-même.
- À conserver : l'explorateur de variantes avec la liste des variantes à
  gauche, que l'utilisateur apprécie.

## Pistes

- Pas encore diagnostiqué : le blocage « au bout de quelques secondes » n'est
  pas expliqué par la seule pause à la voix ; à reproduire sans parler.
- Pause à la voix : l'interruption « allow » en rôle « Jarvis présente » est la
  cause connue ; décider si la parole de l'utilisateur doit mettre en pause, et
  l'afficher dans tous les cas.
- Prévoir un moyen de régler l'interruption d'un item après coup (outil
  `jarvis-presentation`).
- Aucun correctif écrit à ce stade.
