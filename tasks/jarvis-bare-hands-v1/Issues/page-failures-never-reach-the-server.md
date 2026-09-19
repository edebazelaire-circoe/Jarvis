# Les pannes de la page ne quittent jamais la console du navigateur

**Découvert** : reprise de la Slice 12 (QA de `8267b40`, constat R12 ; repris du
constat F6 de la Slice 00).
**Portée** : hors Slice — le Control Center n'a **aucun** canal client → serveur
pour ses journaux, nulle part dans la page. La Slice 12 a suivi le motif du
dépôt ; le refermer est une décision d'architecture, pas un correctif local.

## Ce qui se passe

Le canal de commandes journalise correctement ses pannes… dans la console :
`barehands.command_poll_failed`, `barehands.receipt_failed`,
`barehands.command_loop_failed`, `barehands.command_invalid`,
`barehands.command_lifecycle_unreadable`,
`barehands.command_channel_not_installed`. Aucune de ces lignes n'atteint
`runtime/trace.jsonl`.

Conséquence concrète : une fenêtre dont le long-poll échoue en boucle (proxy
local, serveur redémarré, erreur de parsing) recule en backoff jusqu'à 30 s
pendant que le cerveau, lui, ne voit que `barehands_no_visible_page` ou
`barehands_command_expired`. L'opérateur qui lit la trace côté serveur voit la
conséquence et jamais la cause ; pour la voir, il faut avoir la console du
navigateur ouverte **au moment** où c'est arrivé.

Ce n'est pas propre à Bare Hands : la scène, la timeline et le Test Lab font
exactement pareil. C'est pour ça que ça reste une Issue et pas un défaut de
Slice.

## Ce qu'il faudrait

Une route `POST /api/client-log` bornée (débit limité, corps borné, origine
gardée comme les autres POST) et un petit `obsClientLog` côté page, qui
écrirait dans le même `RuntimeJournal` avec un `kind` préfixé. La décision qui
manque est le débit acceptable : une page en échec de long-poll boucle, et un
canal de journalisation qui suit la boucle d'échec est un amplificateur de
panne. Un plafond par minute et par `kind`, avec un compteur d'écrasés, est la
forme la plus probable.

## Pourquoi ne pas l'avoir fait dans la Slice 12

Parce que la partie utile est **commune à toute la page** et qu'une version
posée pour le seul canal de commandes serait la deuxième vérité que ce dépôt
interdit : la scène et le Test Lab auraient continué de se taire, et le premier
qui aurait cherché « les journaux du navigateur » en aurait trouvé un sur six.
