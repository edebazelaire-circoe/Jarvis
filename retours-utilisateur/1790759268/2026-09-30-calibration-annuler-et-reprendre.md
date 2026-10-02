# Calibration Bare Hands : pouvoir l'annuler, et la reprendre là où on l'a quittée

- **Date** : 2026-09-30
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain` (`.env`)
- **Session** : `retours-utilisateur/1790759268`, Control Center lancé à 11:07:48
  (09:07:48 UTC).
- **Périmètre** : la calibration de Bare Hands, c'est-à-dire la surimpression plein écran
  du Control Center et son parcours d'exercices (`neutral`, `c_pose`, `pinch_primary`…).
- **Demande explicite de l'utilisateur** : « un souci à **noter** ». Fiche seulement,
  aucun code modifié.

## Ce qu'a dit l'utilisateur

> « Ah y'a un souci à noter avec le calibrage. Euh... C'est que... Quand je termine une
> session de... enfin, quand je pars du calibrage, je suis censé pouvoir y retourner et
> retourner là où j'étais tu vois, donc je peux annuler, déjà il faudrait faire un bouton
> annuler le calibrage et voilà. Mais quand je quitte et quand je reviens sur le
> calibrage, il faut que ça soit toujours accessible »

Il y a deux demandes distinctes :

1. **Un bouton « Annuler la calibration »**, identifiable comme tel.
2. **La reprise** : quitter la calibration puis y revenir doit le ramener « là où
   j'étais ». La séance doit rester « toujours accessible », pas repartir de zéro.

## Comportement attendu

Une fois corrigé, l'utilisateur doit pouvoir constater ceci :

- Au milieu du parcours (par exemple sur `pinch_primary`), il quitte la surimpression
  par la croix, « Quitter » ou Échap, puis rouvre la calibration. Il **retombe sur le
  même exercice**, avec ce qu'il avait déjà fait : les exercices passés restent
  mesurés, l'historique des retours et des essais est toujours là, et un réglage
  d'essai en attente est encore présenté comme en attente.
- Il existe **une action d'annulation claire**, qui abandonne vraiment la séance. Après
  une annulation, la réouverture repart d'une séance neuve, et les réglages d'essai non
  acceptés sont défaits.
- Les deux gestes ne se confondent pas : **quitter** met la séance en pause, **annuler**
  la jette.

## Ce que fait le code aujourd'hui

Ces constats viennent d'une lecture rapide. Rien n'a été testé en réel.

- **Toute sortie jette la séance.** Dans
  `jarvis/runtime/control_center_barehands_calibration.js`, `cancel(why)` (l.4579)
  appelle `stop()` (l.4584). Or `stop()` remet l'index d'exercice à `-1`, vide les
  mesures (`collected`, `derived`), les revues, les tentatives et le cadre
  d'entraînement, et pose `session=null` (l.4595), avec pour commentaire « La séance
  s'efface avec le parcours (décision 41) ». Un commentaire de ce `stop()` dit qu'il
  couvre la croix, « Quitter », Échap, l'enregistrement et l'abandon. Toutes ces sorties
  finissent donc au même endroit.
- **Les essais sont défaits à la sortie.** `control_center_barehands.js:7464`,
  `onCancelled`, ferme la séance de l'agent, arrête la mesure et appelle
  `trials.discard('calibration_cancelled')`.
- **« Quitter » existe, « Annuler » non.** Le parcours propose « Quitter »
  (l.3648, l.3674), la croix « Quitter ce parcours » (l.1962) et Échap. En fin de
  parcours s'ajoutent « Quitter sans enregistrer » (l.4497-4499) et « Abandonner »
  (l.4574). Tous mènent à `cancel()` : il n'y a aujourd'hui **qu'une seule sortie**,
  et elle détruit la séance. Ce que l'utilisateur voit comme un simple départ est en
  réalité une annulation.
- **La séance ne vit qu'en mémoire de la page.** `session` (l.2975, ouvert par
  `openSession()` l.2976) contient les épisodes, les mesures, les faux événements, les
  revues et l'historique. Elle n'est jamais postée au serveur.

## Ce qui va contre la demande : la décision 41

`docs/barehands-contracts.md`, « Décision 41 — ce qui reste, ce qui s'efface »
(l.4169), classe `session_sample`, `pinch_episode`, `user_feedback`, `hypothesis`,
`trial_patch` et `trial_outcome` en rétention `session` : « en mémoire de la page
pendant la séance, **effacé à sa fin**, jamais posté ». La seule écriture persistante
est `accepted_trial_values`, faite sur « accept ».

La demande n'annule pas cette règle. Elle oblige à préciser **ce qu'est la « fin »
d'une séance**. Aujourd'hui, fermer la surimpression vaut fin de séance. L'utilisateur
voudrait que seule l'annulation, ou l'enregistrement, marque cette fin. Garder la séance
en mémoire de la page tant que la page reste ouverte semble compatible avec la lettre
de la décision 41, puisque rien n'est posté. La persister au-delà (rechargement de la
page, redémarrage) serait en revanche une vraie modification du contrat.

## Pistes

Rien n'est engagé. Ces pistes servent seulement à cadrer une reprise.

1. **Séparer deux sorties dans `stop()`** : une pause, qui ferme la coque et le cadre
   mais garde `session`, `at` et l'état de l'exercice, et une annulation, qui garde le
   comportement actuel. La croix, « Quitter » et Échap iraient à la pause, et un nouveau
   bouton « Annuler la calibration » à l'annulation.
2. **Décider du sort de l'essai en cours au moment de la pause.** Si on laisse un essai
   appliqué au moteur pendant que la calibration est fermée, Bare Hands tourne hors
   calibration avec des valeurs non acceptées. Si on le défait, il faudra le réappliquer
   à la reprise. Il faut trancher.
3. **La séance de l'agent** (`closeAgentSession`) et les outils `calibration_*` du
   cerveau supposent qu'une séance soit ouverte à l'écran. Une séance en pause devra
   avoir un état lisible par `calibration_status`, faute de quoi le cerveau croira la
   séance perdue.
4. Tests touchés probablement : `tests/unit/test_barehands_calibration_js.py`,
   `tests/unit/test_barehands_calibration_agent_js.py`,
   `tests/unit/test_barehands_calibration_events.py`.

## Ce dont je doute

- **Jusqu'où va « toujours accessible » ?** Il peut s'agir de la même page ouverte
  (quitter la surimpression, faire autre chose, revenir) ou d'une survie au
  rechargement du Control Center et au redémarrage de JARVIS. Le premier cas tient
  dans la décision 41. Le second la contredit et demanderait de persister des données
  de séance que le contrat interdit aujourd'hui d'écrire. **QUESTION à lui poser** :
  la séance doit-elle survivre à un rechargement de la page, voire à un redémarrage ?
- **« Quand je termine une session »** : il se reprend aussitôt (« enfin, quand je pars
  du calibrage »). Je l'ai lu comme un départ en cours de parcours, pas comme la fin
  normale du parcours. S'il parlait aussi d'une séance terminée et enregistrée, la
  reprise voudrait dire rouvrir une séance close, et ce serait une autre demande.
- **L'essai en attente pendant la pause** (piste 2) : l'utilisateur n'en a rien dit.
  C'est un choix de produit à lui soumettre, pas à trancher en silence.
- Le code a été lu, pas exécuté. Je n'ai pas reproduit en réel la perte de la séance
  à la sortie. C'est ce que dit le code, pas une observation à l'écran.
