# Un bloc de réglages Bare Hands en version étrangère est écrasé sans un mot

**Statut : FERMÉ** — décidé par le Human, implanté au début de la Slice 08.
Décision et résolution en fin de fichier.

**Découvert** : reprise de la Slice 07 (QA de `1411421`, constat R6).
**Portée** : hors Slice — la Slice 07 n'a pas introduit ce comportement, et le
refermer demande une décision de produit sur ce que `GET /api/barehands` doit
dire à la page.

## Ce qui se passe

`barehands_test_mode.load()` est une lecture **tolérante** : un bloc dont
`schema_version` n'est ni la version courante ni une version convertible rend
tous les défauts, Bare Hands éteint — ce qui est le bon choix, et il est testé.
Mais il le fait en silence :

- aucun bandeau, aucun toast, aucune entrée de journal ;
- `describe()` rapporte `schema_version: 2`, donc la page ne peut pas
  distinguer « des défauts parce qu'illisible » de « des défauts parce que
  neuf » ;
- la première écriture ordinaire **remplace** le bloc (`apply` part de
  `load()`, c'est-à-dire des défauts, et réécrit la clé entière).

Scénario complet : un utilisateur lance un Jarvis plus récent qui écrit une v3,
revient à cette version, rouvre l'onglet Expérimental, recoche Bare Hands — et
ses réglages v3 sont détruits sans qu'un seul mot ne soit passé à l'écran ni
dans le journal.

Le contrat JS, lui, refuse une version étrangère **bruyamment**
(`barehands_schema_version_unsupported`, avec sa phrase). L'asymétrie est le
cœur du constat : la même situation se dit d'un côté du fil et se tait de
l'autre.

## Ce que le test existant couvre, et ce qu'il ne couvre pas

Couvert : une **charge utile** en v99 est refusée par `apply` avec son code.
Non couvert : un **bloc stocké** en version étrangère, que seul un client
revenu en arrière produit — c'est-à-dire exactement le scénario ci-dessus.

## Pistes

1. `describe()` rapporte la version réellement lue (`stored_schema_version`) et
   un indicateur `unreadable`, que la page traduit en bandeau : « réglages
   écrits par une version plus récente, ils ne sont pas appliqués ».
2. Une entrée de journal `settings.barehands.foreign_version` à la lecture, une
   seule fois par démarrage (la lecture est fréquente).
3. Décider si la première écriture doit **conserver** l'ancien bloc sous une
   clé d'archive plutôt que l'écraser.

La 1 et la 2 sont la partie « qu'on puisse le voir » ; la 3 est la seule qui
demande vraiment un arbitrage.

## Fichiers

`jarvis/runtime/barehands_test_mode.py` (`load`, `describe`, `apply`),
`jarvis/runtime/control_center.py` (`get_barehands`, `save_barehands`),
`jarvis/runtime/control_center_barehands.js` (affichage du bandeau).

## Décision du Human

**Un bloc stocké en version étrangère est ARCHIVÉ, puis remplacé par les
défauts.** Les trois pistes ci-dessus sont retenues ensemble, la 3 — la seule
qui demandait un arbitrage — dans sa forme « conserver sous une clé d'archive »
plutôt que « écraser » ou « refuser de démarrer ».

Ce qui a tranché : Bare Hands doit rester joignable avec un fichier qu'il ne
sait pas lire (la lecture tolérante était le bon choix et le reste), mais
« tolérant » ne peut pas vouloir dire « muet ». Détruire des réglages est une
action ; personne ne l'avait demandée, et rien ne la disait.

## Résolution

`jarvis/runtime/barehands_test_mode.py`

- `inspect(settings)` rend `{present, stored_schema_version, unreadable,
  archive_key}` : c'est lui qui sépare « des défauts parce qu'illisible » de
  « des défauts parce que neuf », que `load()` rendait à l'octet près.
- `archive_unreadable(settings)` range le bloc **tel quel** sous
  `barehands_test_mode_archived_v<N>` à la racine du fichier de réglages.
  `apply` l'appelle **juste avant** d'écrire : c'est le dernier instant où le
  bloc étranger existe encore, et un refus d'écriture n'archive donc rien.
- `archived_keys(settings)` liste ce qui a déjà été mis de côté.
- `describe()` publie `stored_schema_version` (`null` quand rien n'est
  enregistré), `unreadable` et `archived`. `schema_version` garde son sens :
  ce que **ce serveur écrit**.

`jarvis/runtime/control_center.py`

- `get_barehands` journalise `settings.barehands.foreign_version`
  (`barehands_stored_version_unreadable`) **une fois par processus** : la
  lecture part à chaque ouverture de l'onglet, et un journal noyé est illisible.
  Ce qui ne s'épuise pas, lui, est dans la réponse.
- `save_barehands` journalise `settings.barehands.archived`
  (`barehands_stored_version_archived`) avec la clé, la version et
  `replaced_previous_archive`. Ligne **séparée** de `settings.barehands` : les
  mêler rendrait l'archivage invisible dans un filtre sur l'écriture.

`jarvis/runtime/control_center_barehands.js`

- `applyStored` / `storedHtml` : le bandeau de l'onglet Expérimental dit la
  version lue, que cette version ne sait pas l'écrire, que les valeurs d'usine
  s'appliquent, et — après l'écriture — **sous quelle clé** le bloc est rangé.
  « Ils ont survécu » sans dire où n'est pas une réponse.

Points tranchés en passant : la clé porte la version archivée (deux retours en
arrière depuis deux versions différentes laissent deux archives) ; un numéro
non numérique va sous `…_vunknown` ; une archive de même version est remplacée
par la plus récente, et le journal le dit ; le bloc est archivé **sans
normalisation**.

## Tests

`tests/unit/test_barehands_test_mode.py` — `inspect` sur les cinq états (neuf,
v1, v2, étranger, numéro illisible) ; le scénario complet du retour en arrière,
archive comprise ; deux versions étrangères qui ne se recouvrent pas ; un refus
qui n'archive rien ; la route, son bandeau et ses deux lignes de journal, dont
la ligne unique par processus.

`tests/unit/test_barehands_tools_settings_js.py` — le bandeau à l'écran avant
et après l'écriture, et un onglet neuf qui ne crie pas au loup. Le double de
serveur de ce fichier porte désormais les trois champs que la vraie route
envoie, et un test de parité le vérifie contre `describe()` : un double qui ne
peut pas tomber comme le vrai ne prouve rien.

Contrat mis à jour : `docs/barehands-contracts.md` § 9.
