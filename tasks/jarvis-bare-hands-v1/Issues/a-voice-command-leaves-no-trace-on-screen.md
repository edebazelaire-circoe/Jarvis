# Une commande vocale ne se voit pas à l'écran, et une commande vocale refusée ne se voit pas du tout

**Découvert** : reprise de la Slice 12 (QA de `8267b40`, constat R13).
**Portée** : à traiter **dans la Slice 09**, qui est celle qui touche à ce que
Bare Hands montre pendant un parcours. Ce n'est pas un défaut de transport : la
Slice 12 n'a pas de surface à elle.

## Ce qui se passe

Une commande vocale appliquée redessine bien le panneau Expérimental — c'est
l'effet de bord, voulu et testé, de passer par `setAwake`, qui finit par
`refreshPanel()`. Mais **rien ne dit que ça vient de la voix** : l'écran est
exactement celui qu'aurait produit un clic sur le bouton de réveil. Un opérateur
qui regarde la fenêtre ne peut pas distinguer les deux.

Et une commande vocale **refusée** ne produit rien du tout à l'écran : le canal
écrit un `console.warn` et poste son reçu, puis se tait. `barehands_flow_absent`
sur `barehands_tutorial`, par exemple, ne laisse aucune trace visible dans la
fenêtre.

La RÈGLE ZÉRO n'est pas violée — l'utilisateur **entend** JARVIS le dire, c'est
ce que la Slice 12 garantit de bout en bout, et le cerveau reçoit la phrase
exacte du refus. Le manque est pour l'œil, pas pour l'oreille : on ne peut pas
regarder l'écran pour savoir ce que la voix vient de faire.

## Ce qu'il faudrait

Dans le panneau Expérimental, une ligne « dernière commande vocale » :
horodatage, nom de la commande, issue (`applied` / `duplicate` / `refused`) et
le code du refus le cas échéant. Le canal a déjà toute la matière —
`channel.state().last` porte `"<commande>:<issue>"` et `channel.stats()` les
compteurs — et `JarvisBarehandsCommandChannel` les expose déjà. Il manque le
rendu et son rafraîchissement.

C'est à la Slice 09 de le poser, parce que c'est elle qui décide de ce que la
surimpression de tutoriel montre, et qu'une deuxième zone d'état posée avant
cette décision serait à refaire.
