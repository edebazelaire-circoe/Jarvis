# Onglet Architecture (Architecture & Agents)

Module : `jarvis/runtime/control_center_architecture_settings.js` (`window.JarvisArchitectureSettings`, aussi
`module.exports` pour node). Livré par la Slice 04 de `jarvis-architecture-agents-settings-editor` ; la Slice 07 le
monte dans la catégorie `agents_models` et y branche l'adaptateur HTTP. Contrat JSON du graphe :
`tasks/jarvis-architecture-agents-settings-editor/docs/11-graph-wire-contract.md`.

Règle : le composant est une **projection** du snapshot servi par le runtime. Il ne connaît aucune topologie, aucun
identifiant de nœud, et n'affiche jamais un état qu'il n'a pas reçu du serveur.

## 1. Montage

```js
const view = JarvisArchitectureSettings.mount(host, {
  adapter,                              // obligatoire, § 2
  onConfigureBrain: (nodeId, detail) => {},   // fenêtre du cerveau (Slice 05)
  timeoutMs: 15000,                     // échéance de chaque appel d'adaptateur
});
await view.ready;                       // première lecture terminée (succès ou erreur affichée)
view.destroy();                         // retire les écouteurs, arrête le compteur, vide l'hôte
```

Le style est injecté une fois dans `<head>` (`#jarvisArchitectureSettingsStyle`) ; il n'utilise que les jetons du
thème (`--accent`, `--ok`, `--danger`, `--warn`, `--role-accent-*`, `--set-*`, `--shell-glass-strong`).

Le contrôleur expose aussi, pour les tests et l'intégration : `load`, `loadLayout`, `select(type, id)`,
`toggle(id)`, `remove(id)`, `create({source, target})`, `setActivation(nodeId, active)`, `moveNode(id, x, y)`,
`saveLayout()`, `openMenu(nodeId)`, `closeMenu()`, `menuAction(action)`, `configure(nodeId, detail)`, `state`.

## 2. Adaptateur

| Méthode | Rend |
| --- | --- |
| `load()` | le snapshot (lève une erreur portant `.code` sinon) |
| `setConnection(id, {base_revision, enabled})` | résultat d'écriture |
| `createConnection({base_revision, source, target, channel})` | résultat d'écriture |
| `removeConnection(id, {base_revision})` | résultat d'écriture |
| `loadLayout()` | `{revision, positions}` |
| `saveLayout({base_revision, positions})` | `{ok:true, layout}` ou `{ok:false, status, code, reason, layout?}` |
| `setNodeActivation(id, {base_revision, active})` | facultatif, hors contrat 11 : sans lui, aucune entrée Activer/Désactiver |

Résultat d'écriture : `{ok:true, snapshot}` ou `{ok:false, status, code, reason, snapshot?}`. Un échec de transport
lève (`architecture_timeout`, `architecture_unreachable`) : l'issue est inconnue.

Fournis : `createHttpAdapter({fetch, base='/api/architecture', timeoutMs})` (routes du contrat 11) et
`createFixtureAdapter(snapshot, {layout, latencyMs})`, qui simule le serveur (révisions, `423`, `422`, `409`,
`pending` des liaisons `core_restart`, création depuis `creatable`) pour les tests et la démonstration seulement.

## 3. Comportement

- **Après chaque écriture**, l'écran montre le snapshot renvoyé. Refus : raison et code du serveur affichés
  (`role="alert"`), snapshot du refus appliqué s'il est fourni, sinon relecture. `409` : relecture systématique.
  Issue inconnue (transport) : relecture forcée. Une liaison `required_locked` ou `governed` est refusée sans appel.
- **`applies`** : `live`, `next_turn`, `core_restart`, `voice_restart` ; `null` pour une liaison `governed` (aucune
  « prise d'effet » affichée) ; une valeur inconnue s'affiche telle quelle.
- **`pending`** : le trait garde l'état vivant ; le libellé porte une horloge, l'inspecteur dit « effectif au
  prochain démarrage de Core » ou « … de la voix ». Aucun redémarrage n'est déclenché.
- **Codes de refus** : aucune liste fermée ; le `reason` du serveur et son `code` sont toujours affichés
  (`connection_unbindable`, `connection_not_removable`, `architecture_request_invalid`, `layout_invalid`…).
- **Disposition** : glisser un nœud (ou Maj+flèches, pas de 16 px) n'appelle que `saveLayout`, avec la révision lue ;
  `409 layout_revision_stale` relit la disposition et le dit. Sans disposition lisible, la disposition automatique
  sert et les déplacements ne sont pas enregistrés. La disposition automatique est générique (rangs depuis les
  endpoints, grille repliée sur 3, 2 ou 1 colonne selon la largeur du canevas, recalculée au redimensionnement par
  `ResizeObserver` ; les positions enregistrées ne bougent pas).
- **Tracé** : chaque liaison est une courbe quadratique, droite si rien ne gêne, arquée pour séparer deux liaisons
  entre les mêmes nœuds et pour contourner un nœud intermédiaire ou le bord gauche/haut du canevas. Un libellé se
  pose au milieu de sa courbe, sinon glisse le long d'elle ou de côté, au moindre recouvrement avec un autre
  libellé, un nœud ou une pointe de flèche.
- **Création** : seulement depuis les paires que le snapshot expose dans `creatable` (champ facultatif ajouté au
  contrat, voir § 5) ; les ports source deviennent des boutons, les ports cibles compatibles s'allument.
- **États** : chargement (compteur, échéance), erreur, injoignable, vide, version de contrat inattendue, éléments
  écartés (liaison vers un nœud absent).

## 4. Accessibilité et événements

- Tab : bandeau, Relire, puis les modules, puis les libellés de liaisons, puis l'inspecteur. Entrée sur un module ou
  un libellé ouvre l'inspecteur et y place le focus ; Échap ferme le menu, annule une création, puis désélectionne en
  rendant le focus à l'élément d'origine.
- Menu d'un cerveau : clic droit, touche Menu ou Maj+F10, ou le bouton « … » du nœud (tactile). Flèches, Début/Fin,
  Échap. Entrées : Configurer… (si `configurable`), Inspecter, Activer/Désactiver (seulement si
  `activation.mutable` et `adapter.setNodeActivation`), sinon la raison du verrou.
- Les états de liaison ne reposent pas sur la couleur : trait (plein épais + gaine, plein, pointillé atténué, tirets
  mixtes, points), pictogramme (cadenas, interrupteur, prise, lien sortant) et texte. Légende compacte sous le graphe.
- `prefers-reduced-motion` : transitions et pulsation des ports coupées, rotation d'attente ralentie.
- **`architecture:configure-brain`** : `CustomEvent` émis sur l'hôte (bouillonne), `detail = {nodeId, field, source}`
  avec `source` ∈ `menu | inspector | governed` et `field` le champ gouverneur (`delegation`…) ; `onConfigureBrain`
  reçoit les mêmes valeurs.
- Bandeau de l'architecture vocale effective, lecture seule, avec `data-settings-open="<settings_target>"`
  (`architecture_compat`), pris en charge par le lien interne des Réglages.
- Journal : `console.info('architecture_settings.loaded' | 'write_ok' | 'layout_saved' | 'configure_brain')`,
  `console.error(code, …)` et `obsClientLog` quand la page l'expose.

## 5. Écarts au contrat 11 (à valider par agent 0 / Slice 01)

- `creatable` (liste facultative de `{source:{node,port}, target:{node,port}, channel, purpose?}`) : le contrat ne
  dit pas comment le snapshot annonce une création légale ; sans ce champ, aucune création n'est proposée.
- `setNodeActivation` et sa route : absents du contrat ; l'entrée de menu reste cachée tant qu'ils manquent.
- `visual.accent` (jeton facultatif d'un nœud) : sinon teinte stable dérivée de `brain_type`.

Tests : `tests/unit/test_control_center_architecture_settings_js.py` (node) et
`tests/unit/test_architecture_settings_browser.py` (Chrome sans tête sur une page statique, harnais
`_architecture_settings_browser.mjs`). Fixtures : `tests/fixtures/architecture_snapshot_fixture_ui.json` (UI) et les snapshots réels de la Slice 01
(`architecture_snapshot_duplex.json`, `architecture_snapshot_simple.json`), copiés tels quels.
