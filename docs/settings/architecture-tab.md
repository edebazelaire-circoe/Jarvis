# Onglet Architecture (Architecture & Agents)

Module : `jarvis/runtime/control_center_architecture_settings.js` (`window.JarvisArchitectureSettings`, aussi
`module.exports` pour node). Livré par la Slice 04 de `jarvis-architecture-agents-settings-editor` ; depuis la Slice 07
il est monté par la section `agents_models` › `architecture` avec l'adaptateur HTTP (`mountArchitectureSettings`,
[architecture-agents.md](architecture-agents.md) § 1). Contrat JSON du graphe :
`tasks/jarvis-architecture-agents-settings-editor/docs/11-graph-wire-contract.md`.

Règle : le composant est une **projection** du snapshot servi par le runtime. Il ne connaît aucune topologie, aucun
identifiant de nœud, et n'affiche jamais un état qu'il n'a pas reçu du serveur.

## 1. Montage

```js
const view = JarvisArchitectureSettings.mount(host, {
  adapter,                              // obligatoire, § 2
  onConfigureBrain: (nodeId, detail) => {},   // fenêtre du cerveau (Slice 05)
  subagentsTarget: 'subagents',         // facultatif : onglet des rôles (action rapide « Rôles des sous-agents »)
  timeoutMs: 15000,                     // échéance de chaque appel d'adaptateur
});
await view.ready;                       // première lecture terminée (succès ou erreur affichée)
view.destroy();                         // retire les écouteurs, arrête le compteur, vide l'hôte
```

Le style est injecté une fois dans `<head>` (`#jarvisArchitectureSettingsStyle`) ; il n'utilise que les jetons du
thème (`--set-*`, `--role-accent-*`, `--shell-dur*`) et compose les primitives de la fondation visuelle
([visual-foundation.md](visual-foundation.md) : `.set-panel`, `.set-medallion`, `.set-stat`, `.set-dot`, `.set-btn`,
`.set-switch`, `.set-table-*`). Le CSS propre au module ne porte que la composition et le graphe (préfixe `.arch-`).

Le contrôleur expose aussi, pour les tests et l'intégration : `load`, `loadLayout`, `select(type, id)`,
`toggle(id)`, `remove(id)`, `create({source, target})`, `setActivation(nodeId, active)`, `moveNode(id, x, y)`,
`saveLayout()`, `resetLayout()`, `loadJournal()`, `setConfiguring(nodeId|null)`, `openMenu(nodeId)`, `closeMenu()`,
`menuAction(action)`, `configure(nodeId, detail)`, `state`.

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
| `loadJournal()` | facultatif : entrées `{ts, kind, level, message, data}` du journal du Control Center ; sans lui, la carte Journal dit qu'il est indisponible |

Résultat d'écriture : `{ok:true, snapshot}` ou `{ok:false, status, code, reason, snapshot?}`. Un échec de transport
lève (`architecture_timeout`, `architecture_unreachable`) : l'issue est inconnue.

Fournis : `createHttpAdapter({fetch, base='/api/architecture', trace='/api/trace', timeoutMs})` (routes du contrat 11 ;
`loadJournal` lit `GET /api/trace?limit=500` et ne garde que les `architecture.*` et `brain_config.*`, sans les
lectures `*.read`, 40 au plus) et `createFixtureAdapter(snapshot, {layout, latencyMs, journal})`, qui simule le serveur
(révisions, `423`, `422`, `409`, `pending` des liaisons `core_restart`, création depuis `creatable` ; `loadJournal`
seulement si `journal` est donné) pour les tests et la démonstration seulement.

## 3. Composition (refonte-ui-settings, Slice 04)

Maquette : `tasks/refonte-ui-settings/references/ui/03-architecture-agents-architecture.png`. Chaque région est
calculée depuis ce que sert le runtime ; un élément de la maquette sans donnée n'est pas rendu.

| Région | Contenu | Source |
| --- | --- | --- |
| **État du système** | phrase d'état (tous actifs / n inactifs / n indisponibles, avec leurs noms, pastille + mot), modules actifs `a / n`, liaisons actives `e / m`, changements en attente, architecture vocale effective (lecture seule, lien vers Avancé), révision du snapshot | snapshot |
| **Règles d'architecture** | une ligne par liaison `required_locked` (sa `locked_reason`) puis `governed` (son but et le cerveau qui la règle) ; la liste défile au-delà de ~5 lignes ; une règle sélectionne sa liaison | snapshot |
| **Actions rapides** | Relire l'architecture ; Réinitialiser la disposition (deux temps : « Confirmer », inerte avec sa raison sans position enregistrée) ; Rôles des sous-agents (si `subagentsTarget`) ; attentes et notes de disposition | adaptateur |
| **Canevas** | toute la largeur, au plus trois colonnes de modules ; l'inspecteur flotte au bord opposé à l'élément choisi et n'existe que s'il y a une sélection ; sous 860 px de large, il passe sous le canevas | snapshot, disposition |
| **Journal d'architecture** | heure locale, module (cerveau nommé, liaison `A → B`, « Disposition », sinon la famille), message ; plus récent d'abord ; « Actualiser » ; relu après chaque écriture, relecture ou enregistrement de disposition | `loadJournal` |
| **Légende des liaisons** | les **canaux présents** dans le graphe (couleur), puis la mutabilité (trait) et l'attente | snapshot |

Écartés de la maquette, faute de donnée ou d'action réelle : latence moyenne et requêtes par minute (aucune mesure
servie), « Charger un preset » / « Sauvegarder comme preset » (aucun préréglage d'architecture), puces de
responsabilités des nœuds (le snapshot n'en décrit pas), filtre « Tous les modules » et pause du journal, curseur
continu de délégation (le contrat a cinq niveaux, voir [brain-config-panel.md](brain-config-panel.md)).

### 3.1 Sémantique visuelle du graphe

- **Canal = couleur** (`--ch-*` posés sur `.arch`, tous des jetons `--set-*`) : requête bleu, réponse et parole
  magenta, audio cyan, appel d'outil sarcelle, événement violet, autre gris. Trait et pointe de flèche prennent la
  couleur du canal ; une liaison active a une lueur, une liaison désactivée n'en a pas.
- **Mutabilité = trait** (inchangé) : obligatoire plein épais avec gaine et cadenas, modifiable plein (désactivée :
  pointillé atténué), supprimable tirets mixtes, gouvernée points. Le libellé porte le même pictogramme et le canal.
- **Nœud** : médaillon lumineux teinté (`visual.accent` ou type), nom, type · processus, état en mot (Actif, Inactif,
  Ombre, Indisponible), cadenas « système », ports (cinq au plus) colorés par canal. Inactif ou indisponible : bord
  pointillé sans lueur (indisponible : bord rouge). Sélectionné : bord et lueur pleins. Configuré : cadre pointillé
  lumineux autour du nœud tant que sa fenêtre est ouverte (`brain-config:shown` / `brain-config:closed`).
- **Disposition** : glisser ou Maj+flèches ne change que les coordonnées ; « Réinitialiser la disposition » enregistre
  `positions: {}` (la disposition automatique reprend) et n'écrit aucune liaison.

## 4. Comportement

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

## 5. Accessibilité et événements

- Tab : cartes du bandeau (lien de l'architecture vocale, règles, actions), puis les modules, puis les libellés de
  liaisons, puis l'inspecteur, le journal et la légende. Entrée sur un module ou un libellé ouvre l'inspecteur et y
  place le focus ; Entrée sur une règle sélectionne sa liaison et met le focus sur son libellé ; Échap ferme le menu,
  annule une création, puis désélectionne en rendant le focus à l'élément d'origine (les Réglages restent ouverts).
- Menu d'un cerveau : clic droit, touche Menu ou Maj+F10, ou le bouton « … » du nœud (tactile). Flèches, Début/Fin,
  Échap. Entrées : Configurer… (si `configurable`), Inspecter, Activer/Désactiver (seulement si
  `activation.mutable` et `adapter.setNodeActivation`), sinon la raison du verrou.
- Les états de liaison ne reposent pas sur la couleur : trait (plein épais + gaine, plein, pointillé atténué, tirets
  mixtes, points), pictogramme (cadenas, interrupteur, prise, lien sortant) et texte. La couleur ne dit que le canal,
  aussi écrit dans le libellé. Le niveau d'une entrée du journal est lu (« avertissement », « erreur ») en plus de sa
  pastille.
- `prefers-reduced-motion` : transitions et pulsation des ports coupées, rotation d'attente ralentie.
- **`architecture:configure-brain`** : `CustomEvent` émis sur l'hôte (bouillonne), `detail = {nodeId, field, source}`
  avec `source` ∈ `menu | inspector | governed`, `field` le champ gouverneur (`delegation`…) et `opener` (`node` | `button` pour le menu, sinon `null`) : la fenêtre du cerveau y rend le focus ; `onConfigureBrain`
  reçoit les mêmes valeurs.
- Bandeau de l'architecture vocale effective, lecture seule, avec `data-settings-open="<settings_target>"`
  (`architecture_compat`), pris en charge par le lien interne des Réglages.
- Journal : `console.info('architecture_settings.loaded' | 'write_ok' | 'layout_saved' | 'journal_loaded' | 'configure_brain')`,
  `console.error(code, …)` et `obsClientLog` quand la page l'expose.

## 6. Écarts au contrat 11 (à valider par agent 0 / Slice 01)

- `creatable` (liste facultative de `{source:{node,port}, target:{node,port}, channel, purpose?}`) : le contrat ne
  dit pas comment le snapshot annonce une création légale ; sans ce champ, aucune création n'est proposée.
- `setNodeActivation` et sa route : absents du contrat ; l'entrée de menu reste cachée tant qu'ils manquent.
- `visual.accent` (jeton facultatif d'un nœud) : sinon teinte stable dérivée de `brain_type`.

Tests : `tests/unit/test_control_center_architecture_settings_js.py` (node),
`tests/unit/test_architecture_settings_browser.py` (Chrome sans tête sur une page statique, harnais
`_architecture_settings_browser.mjs`) et `tests/unit/test_architecture_workspace_browser.py` (vrai Control Center
isolé : composition, débordement à 1672×941, 1254×1254, 1280×800 et 1000×800 fenêtre ouverte, règles et inspecteur
flottant, réinitialisation de la disposition, journal illisible). Fixtures : `tests/fixtures/architecture_snapshot_fixture_ui.json` (UI) et les snapshots réels de la Slice 01
(`architecture_snapshot_duplex.json`, `architecture_snapshot_simple.json`), copiés tels quels.
