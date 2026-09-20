# Une commande vocale ne se voit pas à l'écran, et une commande vocale refusée ne se voit pas du tout

**Statut : FERMÉ** — implanté par la Slice 09. Résolution en fin de fichier.

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

---

## Résolution (Slice 09)

Ce qui manquait était bien **le rendu**, et il est posé par la Slice qui décide
ce que la surimpression montre — exactement là où l'Issue le prévoyait.

**Trois surfaces, parce qu'aucune seule ne suffit.** C'est le point qui n'était
pas dans l'Issue et qui a été trouvé en l'implantant : la coque de parcours est
à `z-index: 2147482000` et les toasts à `70`, donc **un toast posé pendant
qu'un parcours est ouvert est invisible**. Or « ferme la surimpression » et
« lance le tutoriel pendant une calibration » sont précisément les commandes
qu'on prononce à ce moment-là. Le rendu est donc :

| Quand | Où | Ce qu'on lit |
|---|---|---|
| un parcours est ouvert | la **coque** (`overlay.note`) | la commande, l'issue et le motif exact |
| panneau fermé, pas de parcours | un **toast** (`bad` 9 s pour un refus, `ok` 3 s sinon) | la commande et l'issue |
| toujours | la ligne `#barehandsVoice` de l'onglet Expérimental | heure, nom, issue, **code** du refus et cycle de vie relu |

**Ce qui a bougé côté canal, et ce qui n'a pas bougé.** Le canal n'a pas de
surface à lui et n'en a pas reçu : il **donne** son reçu à qui sait dessiner
(`deps.onReceipt`), et le republie (`channel.last()`, `null` tant que rien n'est
passé). `state().last` garde sa forme `"<commande>:<issue>"` — l'Issue suggérait
de s'en servir, mais elle ne porte ni le code ni l'horodatage, et changer la
forme d'un accesseur casse ses lecteurs. Un ajout suffisait ; il a suffi.

Un puits qui lève **ne mange pas le reçu** : le cerveau attend la vérité du
transport, pas celle de l'écran. La panne du puits est journalisée
(`barehands.receipt_sink_failed`) et la commande suit son cours — testé.

Couvert par `test_barehands_tutorial_js.py` :
`test_a_voice_command_leaves_a_trace_on_screen_even_when_it_is_refused` et
`test_the_channel_hands_its_receipt_to_the_screen_without_changing_what_it_reports`.

**Ce qui reste ouvert, et c'est nommé.** La ligne n'affiche que la **dernière**
commande : `stats()` porte les compteurs, mais un historique est un composant,
pas une ligne, et personne n'en a encore eu besoin. Et le rendu ne survit pas au
rechargement de la page — il vit dans `view`, pas sur le serveur, ce qui est la
conséquence directe de l'Issue `page-failures-never-reach-the-server`, toujours
ouverte.
