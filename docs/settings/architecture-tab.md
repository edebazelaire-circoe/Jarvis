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
  timeoutMs: 15000,                     // échéance de chaque appel d'adaptateur
});
await view.ready;                       // première lecture terminée (succès ou erreur affichée)
view.destroy();                         // retire les écouteurs, arrête le compteur, vide l'hôte
```

Le style est injecté une fois dans `<head>` (`#jarvisArchitectureSettingsStyle`) ; il n'utilise que les jetons du
thème (`--set-*`, `--role-accent-*`, `--shell-dur*`) et compose les primitives de la fondation visuelle
([visual-foundation.md](visual-foundation.md) : `.set-stat`, `.set-dot`, `.set-btn`, `.set-switch`). Le CSS propre
au module ne porte que la composition (canevas, barre d'outils, panneaux, zoom, messages) et le graphe (préfixe
`.arch-`).

Le contrôleur expose aussi, pour les tests et l'intégration : `load`, `loadLayout`, `select(type, id)`,
`toggle(id)`, `remove(id)`, `create({source, target})`, `setActivation(nodeId, active)`, `moveNode(id, x, y)`,
`saveLayout()`, `resetLayout()`, `setConfiguring(nodeId|null)`, `openMenu(nodeId)`, `closeMenu()`,
`menuAction(action)`, `configure(nodeId, detail)`, `zoomTo(z, at?)`, `zoomBy(facteur, at?)`, `panBy(dx, dy)`,
`fitView()`, `togglePanel('manage'|'state'|'legend')`, `closePanel()`, `reload()` (relecture avec message),
`exportDocument()`, `exportArchitecture()`, `planImport(doc)`, `importArchitecture(doc)`, `state`. Le module exporte
aussi `ZOOM` (`MIN` 0,3, `MAX` 3, `STEP` 1,2, `PAN_THRESHOLD` 4 px), `EXPORT_FORMAT`, `clampZoom`, `zoomAnchor`,
`wheelFactor` (fonctions pures, testées sous node).

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
`createFixtureAdapter(snapshot, {layout, latencyMs})`, qui simule le serveur (révisions, `423`, `422`, `409`, `pending`
des liaisons `core_restart`, création depuis `creatable`) pour les tests et la démonstration seulement. Le journal
d'architecture (`loadJournal`, `GET /api/trace`) a été retiré avec sa carte (retours Human du 25/10).

## 3. Composition (graphe plein espace, retours Human du 25/10)

La page Architecture est le graphe : la section porte `fill: true` au registre
([navigation-registry.md](navigation-registry.md)) ; sous l'en-tête de la page (fil d'Ariane, icône et titre, phrase,
onglets), le canevas prend **toute la largeur et toute la hauteur restantes** de la fenêtre et suit son
redimensionnement. Même modèle de défilement que les autres pages ([settings-shell.md](settings-shell.md) § 1 bis) :
une seule zone qui défile, l'en-tête avec le contenu ; ici le contenu est simplement à la taille de l'écran, il n'y a
donc rien à faire défiler (sur un très petit écran, la hauteur minimale du graphe, 320 px, fait revenir le défilement
normal). Les cartes qui entouraient le graphe (État, Règles, Actions rapides, Journal, Légende) sont supprimées.

| Région | Contenu | Source |
| --- | --- | --- |
| **Canevas** | tout l'espace ; il ne défile pas : la vue est une translation puis une échelle du monde (`transform`), ajustée au canevas à l'ouverture et au redimensionnement tant qu'elle n'a pas été réglée à la main ; au plus trois colonnes de modules | snapshot, disposition |
| **Barre d'outils** (en haut à droite, par-dessus) | **Relire** (relit le snapshot ; le résultat s'affiche dans un message court) · **Gestion** · **État** (pastille de couleur : vert tous actifs, ambre inactifs, rouge losange indisponibles) · **Légende** ; chacun des trois derniers ouvre un petit panneau ancré sous la barre, fermé au clic dehors, par Échap (focus rendu au bouton) ou par un second clic | snapshot, adaptateur |
| **Panneau Gestion** | « Sauvegarder cette architecture » (fichier JSON téléchargé) ; « Charger une architecture… » (fichier JSON) ; « Réinitialiser la disposition » (deux temps, inerte avec sa raison sans position enregistrée) | adaptateur |
| **Panneau État** | phrase d'état (tous actifs / n inactifs / n indisponibles, avec leurs noms), modules actifs `a / n`, liaisons actives `e / m`, changements en attente, architecture vocale effective (lecture seule, lien vers Avancé), révision du snapshot | snapshot |
| **Panneau Légende** | les **canaux présents** (couleur), la mutabilité (trait), l'attente, puis les commandes souris et clavier | snapshot |
| **Zoom** (en bas à droite) | − · niveau en % · + · Recentrer (tout le graphe dans la vue, jamais au-delà de 100 %) | vue |
| **Messages** (en bas à gauche) | refus et avis généraux, attentes, notes de disposition, retour court d'une action (Relire, sauvegarde, chargement) avec un × | état local |
| **Inspecteur** | gardé : seul éditeur d'une liaison (bascule, suppression) ou d'un nœud (liaisons possibles, Configurer…) ; flotte au bord opposé à l'élément choisi, sous la barre et au-dessus du zoom, seulement s'il y a une sélection | snapshot |

**Sauvegarder / charger une architecture.** Le serveur n'a aucune notion d'architecture enregistrée (ni profil, ni
préréglage, ni export) : aucune route ni migration n'a été ajoutée. Le fichier (`format: "jarvis.architecture"`,
`version: 1`) garde la révision lue, l'architecture vocale (pour information), chaque liaison (`id`, source, cible,
canal, mutabilité, état voulu, `pending` compris) et la disposition. Le charger réapplique, par les routes existantes et
avec la révision courante : les bascules des liaisons `toggleable` dont l'état diffère, la suppression des liaisons
`creatable_removable` absentes du fichier, la création des liaisons du fichier que `creatable` permet, puis la
disposition des modules connus (`saveLayout`). Ce qui est verrouillé, gouverné ou inconnu du runtime est ignoré et
compté ; un refus du serveur est compté et dit. Les réglages des cerveaux n'en font pas partie (fenêtre du cerveau).

Écartés, faute de donnée ou d'action réelle : latence moyenne et requêtes par minute (aucune mesure servie), puces de
responsabilités des nœuds (le snapshot n'en décrit pas), curseur continu de délégation (le contrat a cinq niveaux, voir
[brain-config-panel.md](brain-config-panel.md)). Retirés le 25/10 (« le reste ne sert à rien ») : la carte des règles
d'architecture, les actions rapides (dont le lien « Rôles des sous-agents », doublon de l'onglet Sous-agents) et le
journal d'architecture.

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
- **Vue** (affichage seulement, rien n'est écrit) : molette sur le canevas = zoom autour du point sous le pointeur
  (borné à 0,3×–3×) ; boutons + / − (pas de 1,2) et Recentrer ; **clic droit maintenu** = déplacement de la vue, qui ne
  commence qu'au-delà de 4 px : un clic droit immobile ouvre toujours le menu du cerveau, un clic droit qui a déplacé
  la vue n'ouvre ni ce menu ni celui du navigateur (le menu contextuel qui suit le relâchement est ignoré 600 ms).
  Glisser un nœud au clic gauche reste intact (déplacement divisé par le zoom). Un module ou une liaison focalisé au
  clavier hors de la vue y est ramené.

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

- Tab : les modules, puis les libellés de liaisons, puis la barre d'outils (Relire, Gestion, État, Légende ; le
  panneau ouvert suit son bouton), le zoom, les messages et l'inspecteur. Les boutons de panneau portent
  `aria-expanded` et `aria-controls` ; la pastille d'État a son équivalent texte. Entrée sur un module ou un libellé
  ouvre l'inspecteur et y place le focus ; Échap ferme le menu, puis le panneau ouvert (focus rendu à son bouton),
  annule une création, puis désélectionne en rendant le focus à l'élément d'origine (les Réglages restent ouverts).
- Menu d'un cerveau : clic droit, touche Menu ou Maj+F10, ou le bouton « … » du nœud (tactile). Flèches, Début/Fin,
  Échap. Entrées : Configurer… (si `configurable`), Inspecter, Activer/Désactiver (seulement si
  `activation.mutable` et `adapter.setNodeActivation`), sinon la raison du verrou.
- Les états de liaison ne reposent pas sur la couleur : trait (plein épais + gaine, plein, pointillé atténué, tirets
  mixtes, points), pictogramme (cadenas, interrupteur, prise, lien sortant) et texte. La couleur ne dit que le canal,
  aussi écrit dans le libellé.
- `prefers-reduced-motion` : transitions et pulsation des ports coupées, rotation d'attente ralentie.
- **`architecture:configure-brain`** : `CustomEvent` émis sur l'hôte (bouillonne), `detail = {nodeId, field, source}`
  avec `source` ∈ `menu | inspector | governed`, `field` le champ gouverneur (`delegation`…) et `opener` (`node` | `button` pour le menu, sinon `null`) : la fenêtre du cerveau y rend le focus ; `onConfigureBrain`
  reçoit les mêmes valeurs.
- Ligne de l'architecture vocale effective (panneau État), lecture seule, avec `data-settings-open="<settings_target>"`
  (`architecture_compat`), pris en charge par le lien interne des Réglages.
- Journal console : `console.info('architecture_settings.loaded' | 'write_ok' | 'layout_saved' | 'exported' | 'imported' | 'configure_brain')`,
  `console.error(code, …)` et `obsClientLog` quand la page l'expose.

## 6. Écarts au contrat 11 (à valider par agent 0 / Slice 01)

- `creatable` (liste facultative de `{source:{node,port}, target:{node,port}, channel, purpose?}`) : le contrat ne
  dit pas comment le snapshot annonce une création légale ; sans ce champ, aucune création n'est proposée.
- `setNodeActivation` et sa route : absents du contrat ; l'entrée de menu reste cachée tant qu'ils manquent.
- `visual.accent` (jeton facultatif d'un nœud) : sinon teinte stable dérivée de `brain_type`.

Tests : `tests/unit/test_control_center_architecture_settings_js.py` (node),
`tests/unit/test_architecture_settings_browser.py` (Chrome sans tête sur une page statique, harnais
`_architecture_settings_browser.mjs` : molette, boutons de zoom, clic droit maintenu) et
`tests/unit/test_architecture_workspace_browser.py` (vrai Control Center isolé : graphe à la taille de l'écran, barre
d'outils et panneaux, débordement à 1672×941, 1254×1254, 1280×800 et 1000×800 fenêtre ouverte, relecture avec message,
réinitialisation de la disposition). Fixtures : `tests/fixtures/architecture_snapshot_fixture_ui.json` (UI) et les snapshots réels de la Slice 01
(`architecture_snapshot_duplex.json`, `architecture_snapshot_simple.json`), copiés tels quels.
