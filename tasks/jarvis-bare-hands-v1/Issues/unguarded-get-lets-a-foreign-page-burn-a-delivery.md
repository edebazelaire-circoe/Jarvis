# Un long-poll GET non gardé laisse une page tierce consommer une remise

**Découvert** : reprise de la Slice 12 (QA de `8267b40`, constat R11).
**Portée** : hors Slice — **motif préexistant du dépôt**. `GET /api/scene/patches`
a exactement la même forme, et la Slice 12 l'a reproduit fidèlement. Le
refermer vaut pour les deux à la fois, et demande de décider ce qu'on fait des
GET longs du Control Center en général.

## Ce qui se passe

Le garde d'origine du Control Center n'inspecte l'`Origin` que sur les méthodes
autres que `GET`/`HEAD`/`OPTIONS`, sauf pour les routes de
`READ_GUARDED_ROUTES` (historique de conversation, preuves du Test Lab), qui
sont gardées sur **toutes** les méthodes.

`GET /api/barehands/commands` n'est pas dans cette liste. Donc une page tierce
visitée pendant que Bare Hands est allumé peut ouvrir le long-poll, et la
remise étant désormais **exclusive** (reprise de la Slice 12, constat R3), elle
peut faire **disparaître** une commande : la page légitime ne la verra jamais,
et le cerveau apprendra `barehands_command_expired` avec `deliveries: 1`.

Ce qu'elle ne peut **pas** faire, et c'est ce qui borne le constat :

- lire la réponse — pas de CORS, la requête part mais le corps lui est refusé ;
- forger un reçu — le POST, lui, est gardé, et l'identifiant est imprévisible ;
- allumer ou éteindre Bare Hands — `POST /api/barehands` est gardé aussi.

C'est donc un déni de service local, pas une prise de contrôle. La docstring de
`jarvis/runtime/barehands_mcp.py` affirmait que ce canal n'ajoutait aucune
autorité ; c'est vrai des deux POST et faux du GET. **Elle est corrigée**, et
dit maintenant précisément ça.

## Ce qu'il faudrait

Ajouter les longs GET du Control Center à `READ_GUARDED_ROUTES` — au minimum
`/api/barehands/commands` et `/api/scene/patches` — et vérifier que la page
légitime les envoie bien avec une `Origin` de boucle locale (elle est servie
par ce même serveur, donc oui, mais `Sec-Fetch-Site` et l'absence d'`Origin`
sur un GET de même origine demandent d'être regardés avant de serrer le garde).

## Pourquoi ne pas l'avoir fait dans la Slice 12

Serrer un garde partagé sur une route de la scène depuis la Slice du canal de
commandes, c'est changer le comportement d'un sous-système qu'aucun test de
cette Slice n'exerce. Le constat est réel et borné ; le correctif est commun.
