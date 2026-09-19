# Un bloc de réglages Bare Hands en version étrangère est écrasé sans un mot

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
