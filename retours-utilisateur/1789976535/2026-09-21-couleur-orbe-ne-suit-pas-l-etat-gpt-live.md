# La couleur de l'orbe ne suit pas l'état de JARVIS (GPT-Live)

- **Date** : 2026-09-21
- **Mode vocal** : duplex GPT-Live (`gpt-live-1`), d'après `runtime/.voice_runtime`
  (`"architecture": "duplex"`), session ouverte à 07:44:22 UTC.
- **Session** : `retours-utilisateur/1789976535`.
- **Périmètre** : l'orbe du Control Center (thème Cosmos) et tout ce qui lit
  `runtime/.voice_state` (la même source alimente le visualiseur du thème circuit).
- **Retour récurrent** : l'utilisateur précise qu'il l'a déjà signalé et que ce
  n'est toujours pas corrigé.

## Comportement constaté

Ses mots, dictés à 07:46:03 UTC pendant qu'il parlait à JARVIS (« écrite » est une
erreur de transcription pour « écoute ») :

> « Je note toujours qu'il y a le problème de couleur d'état. Là, t'es en mode,
> par exemple, écoute, donc tu devrais être en vert, enfin, des waves. Tu fais
> l'action, tu aurais dû être en violet, mode actif... Ce genre de souci... Je
> l'ai déjà signalé. Comme ça, je ne l'ai pas été corrigé »

Relevé sur le poste, pendant la même session, en échantillonnant `.voice_state`
toutes les 50 ms : l'état affiché est resté sur **`speaking` (orange)** de 07:47:31
à 07:48:50, alors que JARVIS écoutait, puis travaillait (délégation au cerveau à
07:47:58, action Bare Hands à 07:48:04), puis écoutait de nouveau. Seul un passage
de 100 ms en violet à 07:47:58.

## Comportement attendu

Ce que l'utilisateur doit voir, dans ses termes :

- JARVIS l'écoute : l'orbe est **verte**, avec l'onde du micro.
- JARVIS agit (le cerveau travaille, appelle des outils) : l'orbe est **violette**.
- JARVIS parle : l'orbe est **orange**, le temps de la phrase seulement.
- L'action finie et la réponse dite (ou finie sans rien dire) : l'orbe **repasse
  au vert**.

## Cause

Deux défauts, tous deux propres au fil GPT-Live :

1. **GPT-Live envoie de l'audio en continu, même quand il se tait.** Mesuré sur le
   vrai fournisseur (session séparée) : un bloc de 100 ms toutes les 100 ms, du
   début à la fin de la session ; quand JARVIS se tait, ce sont des zéros exacts.
   Chaque bloc, silence compris, rallumait « JARVIS parle » : orange permanent, et
   la détection de fin de parole ajoutée le matin même (quiescence locale) ne
   pouvait jamais se déclencher, la file de lecture ne se vidant jamais.
2. **Le violet ne se relâchait jamais.** « Le cerveau réfléchit » n'était levé qu'à
   l'ouverture d'une sortie portant un `speech_id` ; aucune sortie GPT-Live n'en
   porte. Une fois le premier défaut réglé, l'orbe serait restée violette à vie
   après la première action, au lieu de revenir au vert.

## Ce qui a été fait

Branche `fix/orb-live-state-colors`, commit `1e7d6d4` (non poussée, non
fusionnée ; worktree `.claude/worktrees/orb-live-colors`).

- Le silence de GPT-Live (blocs de crête ≤ 16) n'est plus joué ni annoncé comme
  une parole.
- La fin du travail du cerveau (`brain.work.*` de Core) rend l'écoute, même sans
  parole.

Mesure au pixel (orbe Cosmos d'un vrai Control Center, fil cadencé comme GPT-Live) :
avant, orange aux six étapes ; après, vert → violet → orange → violet → orange → vert.

Effet de bord attendu : le délai d'inactivité GPT-Live (60 s dans les réglages)
va maintenant s'appliquer pour de bon. Avant, le silence diffusé le réarmait
toutes les 100 ms et la session ne se mettait jamais en veille.

## Ce qui reste à vérifier par l'utilisateur

Après redémarrage de la voix sur cette branche : parler à JARVIS en GPT-Live et
regarder l'orbe pendant un tour complet (écoute, action, réponse, retour à
l'écoute).
