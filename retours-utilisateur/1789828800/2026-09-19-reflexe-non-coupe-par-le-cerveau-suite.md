# La réponse du cerveau est produite puis jetée sans jamais être dite (2e signalement)

- **Date** : 2026-09-19
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain` (`.env`)
- **Session** : `retours-utilisateur/1789828800`, Control Center lancé à 16:40:00
  (14:40:00 UTC).
- **Suite de** : `retours-utilisateur/1789824166/2026-09-19-reflexe-non-coupe-par-le-cerveau.md`
  (même sujet, session précédente de 15:22:46). Le diagnostic complet, la chronologie
  de la trace et la sonde qui échoue sont là-bas ; cette fiche-ci ne consigne que le
  deuxième signalement et ce qu'il précise de l'attente de l'utilisateur.

## Comportement constaté

L'utilisateur revient sur le même défaut, à l'oral, sans avoir lu le code. Ses mots
exacts :

> « OK donc à noter dans les feedback user euh et c'est lié à l'échange qu'on vient
> d'avoir ici donc le [problème] à cette session là c'est que le cerveau le brain
> n'arrive pas à interrompre la voix pourtant c'est lui qui a la priorité sur euh la
> sur la commande vocale en fait il est censé pouvoir interrompre en tout cas pas
> interrompre mais il faut vraiment qu'il y a un flux qui se fasse là parce que c'est
> pas possible que le brain envoie des données qui ne sont pas interprétées par Jarvis
> derrière quoi »

Ce qu'il constate, dans ses termes : **le cerveau envoie des données qui ne sont pas
interprétées par la voix derrière**. La réponse existe, elle est produite, et elle
n'est jamais dite — pendant que le réflexe, lui, continue de parler.

Il se corrige lui-même en cours de phrase (« il est censé pouvoir interrompre, en tout
cas pas interrompre, mais il faut vraiment qu'il y a un flux qui se fasse »). Cette
correction est le cœur du retour : ce qu'il demande n'est pas d'abord une coupure
brutale du réflexe, c'est que **la sortie du cerveau ne puisse pas être ignorée par la
couche vocale**. Qu'un chemin existe, toujours, entre ce que le cerveau produit et ce
qui est prononcé.

## Comportement attendu

Ce que l'utilisateur doit pouvoir constater quand ce sera réparé : **aucune réponse du
cerveau n'est silencieusement perdue.** Si le cerveau rend un texte, ce texte est
entendu — au besoin en interrompant la phrase d'attente en cours, ou en passant juste
après elle, mais jamais jeté sans trace audible pour l'utilisateur.

Le corollaire, dans ses mots : le réflexe ne doit pas pouvoir occuper la bouche assez
longtemps pour faire périmer ce que le cerveau vient de produire.

## Contexte

Rappel de ce qui avait été établi au premier signalement (détails et preuves dans la
fiche source) :

- Dans la trace d'incident, le réflexe a parlé **16 s** (18,0 s au total, dont 9,9 s
  après que la réponse du cerveau était prête) ; la réponse du cerveau a été écartée
  **3 ms** après sa naissance (`presentation_decided` / `deferred` / `stale_source`,
  `age_ms: 3`) et n'est jamais entrée dans la file de parole.
- **La règle que l'utilisateur énonce — le cerveau prioritaire sur le réflexe —
  n'existe pas dans le code.** Le champ de priorité ne sert qu'au tri ; l'arbitrage
  réel est temporel : le cerveau gagne s'il est prêt avant le premier son du réflexe,
  et perd toujours après.
- Un chemin d'arrêt qui fonctionne existe déjà : celui qu'emprunte le barge-in quand
  l'utilisateur coupe la voix à la main. La piste évoquée était que le cerveau emprunte
  ce même chemin.

Ce que le second signalement ajoute : l'utilisateur ne décrit plus l'incident d'un tour,
il décrit une **propriété manquante du système** (« il faut vraiment qu'il y a un flux
qui se fasse »). Le défaut n'est donc pas perçu comme un accident de timing mais comme
un lien absent entre le cerveau et la voix.

## Pistes

Les pistes techniques établies sont dans la fiche source et ne sont pas redites ici.
Ce que ce tour-ci déplace dans leur lecture :

1. Le correctif ne peut pas se limiter à « couper le réflexe plus tôt ». Même réflexe
   coupé, une réponse périmée (`stale_source`) resterait jetée : l'utilisateur
   entendrait toujours le cerveau produire du vide. Le point 4 de la fiche source (une
   réponse complète jetée mérite mieux qu'un `info`) remonte donc au même rang que les
   points 1 et 2.
2. Ce que l'utilisateur appelle « flux » recouvre les deux moitiés du trajet : la
   coupure du réflexe **et** la garantie de livraison de la sortie du cerveau. Traiter
   l'une sans l'autre laisserait le constat intact de son côté.

## Ce dont je doute

La question ouverte de la fiche source n'est pas tranchée et le reste : **deux questions
posées dans le même souffle sont-elles une intention ou deux ?** Le code répond
« deux », et c'est cette réponse qui fait périmer la première réponse du cerveau.
Le mot « flux » de l'utilisateur suggère qu'il attend « une seule conversation, rien ne
se perd » — mais il n'a pas été interrogé là-dessus et ce n'est pas à deviner.

Aucun code n'a été modifié : fiche seulement.
