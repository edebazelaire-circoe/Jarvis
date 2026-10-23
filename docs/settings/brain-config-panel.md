# Fenêtre de configuration d'un cerveau (Architecture & Agents)

Module : `jarvis/runtime/control_center_brain_config_panel.js` (`window.JarvisBrainConfigPanel`, aussi
`module.exports` pour node). Livré par la Slice 05 de `jarvis-architecture-agents-settings-editor` ; la Slice 07 le
branche sur le canevas ([architecture-tab.md](architecture-tab.md)) avec l'adaptateur HTTP. Contrat serveur :
[../brain-config.md](../brain-config.md) (`GET` / `PATCH /api/brains/{id}/config`).

Il n'y a **pas d'onglet « Cerveau »** : cette fenêtre flottante est la seule surface de configuration d'un
cerveau. Elle s'ouvre depuis le canevas (clic droit ou bouton « … » › Configurer…, bouton de l'inspecteur, ou
liaison gouvernée), flotte au-dessus du graphe, qui reste visible, et se glisse par son en-tête.

Règle : la fenêtre est une **projection** du descripteur servi par le runtime. Elle n'affiche que les champs qu'il
expose, avec leurs choix, `editable`, `reason` et `applies` ; aucun nom de modèle, aucun identifiant de cerveau,
aucune topologie n'est écrit dans le module.

## 1. Montage

```js
const win = JarvisBrainConfigPanel.open(panelsHost, {
  adapter,                        // obligatoire, § 2
  brainId: nodeId,                // identifiant du nœud du graphe (voice, luna, core, tool_brain)
  field,                          // facultatif : champ à montrer (« delegation » depuis une liaison gouvernée)
  returnFocus: JarvisBrainConfigPanel.canvasReturnFocus(canvasHost, nodeId, detail), // facultatif
  anchor: () => canvasHost.querySelector(`[data-arch-node="${nodeId}"]`),            // facultatif : hauteur initiale
  nodeLabel: id => label,         // facultatif : nom des pairs dans le résumé des connexions
  onFocusConnection: id => view.select('connection', id),  // « Voir sur le graphe »
  onSaved: ({brainId, field, applies, changed, config}) => view.load(), // relire le graphe (liaison gouvernée)
  onClose: ({brainId}) => {},
  timeoutMs: 15000,
});
win.close();     // ferme ; avec un brouillon, demande d'abord (rend false)
win.destroy();   // démonte sans condition (changement de page)
```

- `panelsHost` ne doit **pas** être l'hôte du canevas (il réécrit son contenu à chaque rendu) ; s'il l'est, la
  fenêtre se pose sur son parent. La couche est `position: fixed`.
- **Une seule fenêtre à la fois** (`JarvisBrainConfigPanel.current`) : `open()` sur un autre cerveau remplace la
  fenêtre en place ; avec un brouillon non appliqué, une confirmation « Abandonner et ouvrir / Continuer
  l'édition » s'affiche d'abord. Pendant un enregistrement, le remplacement est refusé et dit pourquoi.
- Le contrôleur expose aussi `show`, `apply`, `discard`, `setDraft(field, value)`, `reload`, `confirm(bool)`,
  `moveBy(dx, dy)`, `state`, `brainId`, `dirty`, `element`.
- Événements sur l'hôte (bouillonnent) : `brain-config:saved` (même `detail` que `onSaved`).
- Lien « Ouvrir Sous-agents » : `data-settings-open="subagents"`, pris en charge par le lien interne des
  Réglages (la Slice 07 ajuste l'identifiant si l'onglet Sous-agents change de nom).

## 2. Adaptateur

| Méthode | Rend |
| --- | --- |
| `load(brainId)` | le descripteur ; sinon lève une erreur `.code` (`.status`, `.config` éventuel) |
| `patch(brainId, body)` | `{ok:true, changed, applies, config}` ou `{ok:false, status, code, reason, field, config}` |

Un échec de transport lève `brain_config_timeout` ou `brain_config_unreachable` : l'issue est inconnue.
Fournis : `createHttpAdapter({fetch, base='/api/brains', timeoutMs})` et `createFixtureAdapter(configs,
{latencyMs})`, qui simule le serveur (révision, `423`, `422`, `503`, `409` dont `prompt_override_concurrent`,
`pending_relaunch`) pour les tests et la démonstration **seulement** ; `script({result}|{error})` impose la
réponse suivante, `tamper(id, fn)` simule une écriture faite ailleurs.

## 3. Champs et rendu

| Champ du descripteur | Rendu |
| --- | --- |
| `label`, `brain_id`, `brain_type`, `process` | en-tête (identité stable, lecture seule) |
| `state`, `system`, `voice_architecture` | état (pastille + texte + raison), badge « Système » avec cadenas |
| `mission` | texte en lecture seule, avec sa raison |
| `provider` (Core) | liste des CLI du descripteur ; un indisponible reste listé, désactivé, avec sa raison |
| `model` | liste des choix du descripteur ; indisponibles et `unlisted` visibles avec leur raison ; `catalog.status ≠ ok` : avertissement, seul le défaut reste permis ; `provider` d'un modèle vocal : lecture seule |
| `delegation` | contrôle segmenté à cinq niveaux (`role="radiogroup"`, flèches, Début/Fin), libellés et explication du descripteur, échelle Moins / Plus, `enforcement` repliable, `stored_invalid` et `store` illisible signalés ; `launched` / `pending_relaunch` (§ 3.1) ; `not_applicable` : la raison, aucun contrôle |
| `instructions` | zone de texte si `editable`, compteur `n / max_length`, « Vider » ; sinon la raison |
| `activation` | contrôle segmenté seulement si `editable` et `choices` (Tool Brain) ; sinon état + raison |
| `connections` | entrantes / sortantes en lecture seule : pair, canal, active/coupée, `pending`, mutabilité (cadenas, interrupteur, prise, lien gouverné, avec texte), raison du verrou ; « Voir sur le graphe » appelle `onFocusConnection(id)` |
| `out_of_scope` | note « Ailleurs dans les Réglages » (personnalité, CLI technique) ; aucun contrôle |

Chaque section porte sa prise d'effet (`applies`) : « Effectif immédiatement », « au prochain tour », « au prochain
démarrage de Core », « … de la voix » ; une valeur inconnue s'affiche telle quelle. Après un enregistrement, la
puce devient « Enregistré · effectif … » (ou « Inchangé »). Aucun redémarrage n'est déclenché.

Rappel visible dans la section délégation : « Le choix du modèle de chaque rôle se fait dans l'onglet
Sous-agents. » La fenêtre ne contient aucun contrôle de personnalité (ton, politesse, longueur, humour), aucun
chemin, commande ni autorisation du CLI, et aucune écriture de connexion.

### 3.1 Relance du cerveau

`launched` (tendance reçue par le CLI vivant) et `pending_relaunch` (la valeur enregistrée attend la relance du
CLI) sont dits tels quels sous le contrôle : « « Proactive » est enregistré : effectif à la relance de Core Brain.
Le cerveau en cours d'exécution a reçu « Jamais ». » Sans attente, `launched` est rappelé en une ligne discrète.

## 4. Écriture : brouillon multi-champs, PATCH successifs

Choix : un **brouillon** couvre tous les champs, « Appliquer » l'envoie en **un PATCH par champ** (seul le couple
CLI + modèle de Core va ensemble), dans l'ordre délégation, modèle, activation, instructions. Chaque PATCH porte
la `revision` renvoyée par le précédent. Raisons : un seul geste Annuler / Appliquer pour toute la fenêtre (référence
visuelle, garde du brouillon à la fermeture), alors que le contrat n'accepte qu'un champ par écriture et que chaque
champ a son propre propriétaire, sa propre prise d'effet et ses propres refus.

- Succès : la fenêtre montre la `config` renvoyée (sinon relit), retire le champ du brouillon, marque sa prise
  d'effet ; un brouillon devenu égal à la valeur du serveur disparaît.
- **Arrêt au premier refus** : rien n'est envoyé après lui. La raison et le code du serveur s'affichent
  (`role="alert"`) ; la `config` du refus est appliquée, sinon relecture ; le brouillon du champ refusé **et**
  des suivants est conservé. Les champs déjà enregistrés gardent leur marque : aucun enregistrement partiel caché.
- `409` (`brain_config_revision_stale`, `prompt_override_stale`, `prompt_override_concurrent`) : config relue,
  brouillon conservé ; pour les instructions, le texte actuel du serveur s'affiche à côté du brouillon ; un nouvel
  « Appliquer » envoie la nouvelle `effective_revision`.
- Issue inconnue (transport, échéance) : « Issue inconnue », relecture forcée ; ce qui reste marqué « Modifié »
  n'est pas appliqué.
- Changer de CLI désactive le choix du modèle (ses modèles ne sont connus qu'après relecture) : le PATCH part avec
  `provider` seul, le serveur garde le modèle enregistré pour ce CLI.
- Des instructions plus longues que `max_length` bloquent « Appliquer » et le disent.

## 5. Accessibilité, focus, mouvement

- `role="dialog"`, `aria-modal="false"` (le graphe reste utilisable à la souris), titre et sous-titre reliés.
- À l'ouverture, le focus va sur le titre (ou sur le contrôle de `field`). Tab et Maj+Tab tournent dans la fenêtre
  (ou dans la confirmation ouverte). Échap ferme ; avec un brouillon, il ouvre la confirmation, qu'un second Échap
  referme sans rien perdre.
- À la fermeture, le focus revient à ce qui a ouvert la fenêtre : `returnFocus` (élément ou fonction, relu à la
  fermeture : le canevas a pu se redessiner) ; `canvasReturnFocus(canvasHost, nodeId, detail)` choisit le bouton
  « … » quand `detail.opener === 'button'` (champ ajouté au détail de `architecture:configure-brain` par cette
  Slice), le bouton « Configurer… » de l'inspecteur, sinon le nœud. Sans `returnFocus`, l'élément actif à
  l'ouverture.
- Glisser par l'en-tête, ou le bouton de prise + flèches (pas de 16 px) ; la fenêtre reste dans l'écran. Position
  initiale : contre le bord droit de l'hôte (colonne de l'inspecteur), à la hauteur de l'ancre.
- Sous 720 px : panneau en bas d'écran sur toute la largeur, voile derrière (un clic ferme, avec garde), pas de
  glisser, aucun défilement horizontal.
- États qui durent : lecture et enregistrement montrent un compteur de secondes et une échéance (`timeoutMs`) ; à
  l'échéance, le code `brain_config_timeout` et « Relire ».
- `prefers-reduced-motion` : transitions et apparition coupées, rotation d'attente ralentie.
- Journal : `console.info('brain_config_panel.opened' | 'loaded' | 'saved' | 'closed' | 'focus_connection')`,
  `console.error(code, …)` et `obsClientLog` quand la page l'expose.

Tests : `tests/unit/test_brain_config_panel_js.py` (node : descripteurs core, voice, Tool Brain dérivé ; PATCH
successifs, refus, 409, conflit d'instructions, issue inconnue, catalogue 503, relance en attente, échéance,
adaptateurs) et `tests/unit/test_brain_config_panel_browser.py` (Chrome sans tête : canevas + fenêtre câblés comme
en Slice 07, focus, Tab, Échap, délégation au clavier, « Voir sur le graphe », glisser, remplacement, 420 px,
mouvement réduit). Fixtures : `tests/fixtures/brain_config_{core,voice}.json` de la Slice 02, copiées telles quelles.
