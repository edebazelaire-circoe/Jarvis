# Réglages : le shell plein écran et ses primitives

**Statut :** contrat canonique du shell des Réglages (niveau 3 : implémentation réutilisable + tests).
**Introduit :** tâche `jarvis-settings-ui-reorganization`, Slice 02.
**S'appuie sur :** [`navigation-registry.md`](navigation-registry.md) (six catégories, sections, alias).

- Shell : `jarvis/runtime/control_center.html` (`#overlay` › `#settingsShell`, CSS « Réglages : shell plein
  écran », fonctions `renderTabs`, `renderTab`, `selectTab`, `openSettings`, `openSettingsTab`, `closeSettings`,
  `mountRegisteredSection`, `registerSettingsSection`).
- Navigation : `shellNavigation` / `shellTarget` de `control_center_settings_registry.js`.
- Primitives : `jarvis/runtime/control_center_settings_ui.js` (`window.JarvisSettingsUI`), inséré par
  `control_center.py` (`SETTINGS_UI_SCRIPT_FILE`/`_MARKER`) juste après le registre, avant l'état des Réglages (`SET`).
- Tests : `tests/unit/test_control_center_settings_shell_js.py` (node : primitives, cycle de vie d'une section,
  navigation lue au registre), `tests/unit/test_control_center_settings_registry_js.py` (routage des cibles),
  `tests/unit/test_settings_shell_browser.py` (vrai Chrome : clavier, focus, Échap, débordement à 100 % et 125 %,
  mouvement réduit), `tests/unit/test_jarvis_wheel_browser.py` (roue → catégories).

## 0. Le hub (premier niveau, 2026-10-23)

Sans cible, les Réglages s'ouvrent sur un **hub** : `#overlay` › `section#settingsHub` (role=dialog aria-modal,
nommé par son titre), au-dessus de JARVIS légèrement flouté et assombri (`.overlay[data-view=hub]` ; voile et flou
allégés le 25/10 pour que la scène se devine derrière). En tête : une grande icône d'engrenage
(`#settingsHubIcon`, `SETTINGS_ICON.settings`, même trait que les cartes), « JARVIS », le titre « Paramètres », un
filet ; plus de phrase d'introduction (retirée le 25/10, avec son `aria-describedby`). Un bouton × en haut à gauche
(`#settingsHubClose`), seul chrome du hub. L'en-tête et la grille forment un bloc centré verticalement. Au centre,
six cartes `button.set-hub-card [data-hub-category]` de mêmes dimensions (3 × 2, puis 2 colonnes sous 1100 px, une
sous 640 px), dessinées depuis `JarvisSettingsRegistry.CATEGORIES` : pictogramme, libellé, description, flèche ;
teinte de la catégorie (`SETTINGS_HUE`, partagée avec le rail).

- Ouvert par `openSettingsHub` : roue › Paramètres (plus de sous-menu), bouton Réglages (`#openSettings`), raccourci
  `ui_settings`. Une cible précise (`openSettingsTab(cible)` : liens internes, « Réglages de la voix ») ouvre
  toujours directement le shell.
- Une carte ouvre le shell sur sa catégorie (`enterSettingsCategory` → `openSettingsTab`), dans le même overlay ;
  la flèche ← (`#settingsBack`, en haut à gauche, à côté du ×) ramène au hub sans fermer l'overlay (le brouillon
  reste, `SET.dirty`).
- × ou Échap ferme le hub (`closeSettingsHub`, fondu inverse de 160 ms, sans animation en mouvement réduit) ; le
  focus revient à l'élément d'ouverture (l'ancre de la roue). Flèches entre les cartes ; Tab reste dans le hub.
- Le hub ne charge ni n'écrit aucun réglage et ne touche pas `SET.open`.
- Refonte page par page : une catégorie qui a sa propre page l'ouvre à la place du shell (`data-view=perso` pour
  Personnalisation, [`personalization-page.md`](personalization-page.md)) ; ses lignes « Réglages détaillés » ouvrent
  le shell sur une section. Architecture & Agents et Mémoire & Connaissances s'ouvrent dans le shell, **en page
  pleine** (§ 1 bis).

## 1. Ce que le shell possède

Le shell possède l'ouverture et la fermeture, les six catégories, les entrées d'une catégorie, le focus, le
clavier, le nettoyage des sections et la mise en page. Une section possède ses contrôles, ses données et sa
validation. Aucune valeur de réglage n'est écrite par le shell.

```
#overlay (plein écran, voile + flou légers du fond Jarvis)
└─ #settingsShell  role=dialog aria-modal
   ├─ #closeModal.set-hub-close « Fermer les réglages » (×, Échap)  ┐ ronds, fixes en haut à gauche, premiers dans
   ├─ #settingsBack.set-hub-back « Retour au menu des paramètres » (←) ┘ l'ordre du Tab ; dans les deux dispositions
   ├─ aside.set-rail
   │  ├─ h2#modalTitle « Paramètres »
   │  └─ nav#settingsCategories role=tablist (vertical ; horizontal sous 900 px)
   │       six button.set-cat role=tab [data-category] : pictogramme, libellé, description (registre)
   └─ main#settingsMain role=tabpanel
      ├─ .set-head : #settingsIntro (pictogramme + JarvisSettingsUI.intro + avis `notice` de la catégorie,
      │              p#settingsCategoryNotice)
      ├─ nav#modalTabs role=tablist : sections de la catégorie, button.set-item [data-section] ;
      │     catégorie à groupes (Avancé, Slice 08) : div.set-group role=none [data-settings-group] par groupe non
      │     vide, intitulé span.set-group-label (aria-hidden, monospace) qui décrit ses onglets (aria-describedby)
      ├─ #modalContent.set-body.content : le contenu, SEUL à défiler (disposition à rail ; en page pleine, § 1 bis)
      └─ footer.set-foot : #modalStatus (role=status, aria-live=polite) · #modalSave « Enregistrer »
```

Les identifiants historiques (`overlay`, `modalTitle`, `modalTabs`, `modalContent`, `modalStatus`, `modalSave`,
`closeModal`) sont conservés : les modules et leurs tests les lisent. `#settingsRelated` (liens « encore dans ») et
`#modalSub` (phrase d'onglet hérité) sont retirés avec le système d'onglets (Slice 09). Les noms de fonctions
`renderTabs` (navigation), `renderTab` (monte la section active) et `selectTab` (ouvre une cible) restent : ce sont
les points d'appel du shell et des modules, ils ne concernent plus d'onglet.

## 1 bis. Catégories en page pleine (refonte-ui-settings, Slice 07)

Une catégorie qui porte `page: {lead}` au registre ([`navigation-registry.md`](navigation-registry.md)) —
aujourd'hui `agents_models` (Architecture & Agents) et `memory_knowledge` (Mémoire & Connaissances) — s'ouvre dans le
même shell, mais présentée comme la page Personnalisation et les maquettes 02 à 05 : `renderTabs` pose
`#settingsShell[data-layout=page]` (sinon `rail`). Un seul mécanisme : mêmes fonctions, mêmes identifiants, même
emplacement, même brouillon ; seule la présentation change.

```
#settingsShell[data-layout=page]   (aria-labelledby = #settingsCategoryTitle)
├─ #closeModal (×) · #settingsBack (←)  ronds, fixes en haut à gauche : le seul chrome qui ne défile pas
└─ main#settingsMain               LA zone qui défile (en-tête compris, jamais en largeur) ; centrée à --set-view-max
   ├─ .set-head › #settingsIntro › .set-page-intro : p.set-crumb « JARVIS › Paramètres » (texte)
   │     · .set-title-row (span.set-title-icon = icône de la carte du hub, `settingsIcon`) + h2.set-title#settingsCategoryTitle
   │     · p.set-lead (`page.lead`) · .set-rule
   ├─ nav#modalTabs role=tablist : onglets de page button.set-tab [data-section] (pictogramme + libellé)
   ├─ #modalContent : la section ; `[data-fill]` (section `fill`) : elle prend la hauteur restante de l'écran
   └─ footer.set-foot : seulement pour une section `save:'footer'` (aucune aujourd'hui)
```

- Pas de rail : `aside.set-rail` n'est pas rendu (`display:none`) ; on change de catégorie par ← (le hub) ou par un
  lien. Le fil d'Ariane n'est plus un bouton : un seul contrôle de retour au hub, la flèche ←. Pas d'avatar : aucune donnée de profil réelle derrière ces deux
  pages (le profil actif reste propre à Personnalisation).
- Les autres catégories (Personnalisation détaillée, Interface & Interactions, Plugins & MCP, Avancé & Diagnostics)
  gardent le shell à rail ; un lien interne d'une page pleine vers l'une d'elles (« Ouvrir les paramètres avancés »)
  rend le rail, et l'inverse.
- Inchangés : liens profonds et alias (`memory`, `semantic_retrieval`, `consolidation`, `main_agent`,
  `subagent_models`…), `openSettingsTab` / `openSettingsLink`, raccourcis `ui_settings` / `ui_close`, état d'onglet
  (`SET.lastItem`), Échap (menu → fenêtre → page), clavier des onglets (activation manuelle).
- Focus à l'ouverture : l'onglet de page ouvert (il n'y a pas de catégorie active à focaliser) ; de même quand on
  arrive du rail d'une autre catégorie (§ 3). L'avis de catégorie (`notice` du registre) se pose dans
  `.set-page-intro` comme dans `.set-intro`.
- Fenêtre d'un cerveau (Architecture) : sa zone d'ouverture (`architecturePanelZone`) commence sous les onglets de la
  page et sous le × ; elle ne couvre jamais le fil d'Ariane, le titre ni l'onglet actif à l'ouverture.
- Défilement (retours Human du 25/10, qui annulent l'en-tête fixe de la Slice 07) : **une seule zone de défilement
  par page**, `#settingsMain` ; le fil d'Ariane, le titre et les onglets défilent avec le contenu ; seuls × et ←
  restent fixes. Section `fill` (Architecture) : même modèle, mais le contenu est dimensionné à la hauteur restante
  sous l'en-tête (`#settingsShell[data-fill]`, posé par `renderTabs`), il n'y a donc rien à faire défiler ; aucune
  règle n'interdit le défilement, qui revient sur un très petit écran (hauteur minimale du contenu 360 px). La
  fenêtre d'un cerveau étant fixe, elle peut recouvrir l'en-tête si l'on fait défiler une page derrière elle.
- Rangs : `.settings-shell[data-layout=page] ` est inscrit au registre des couches de `docs/control-center-shell.md`
  (× et ← `--set-z-chrome`).
- Tests : `tests/unit/test_settings_page_layout_browser.py` (mise en page, rail, × et ←, icône devant le titre, focus,
  alias, défilement unique avec l'en-tête, Architecture à la taille de l'écran, captures finales des cinq vues),
  `tests/unit/test_architecture_workspace_browser.py` (chrome de la page atteignable, fenêtre du cerveau ouverte).

## 2. Emplacement et routage

L'emplacement est `SET.category`, puis `SET.section` (une section enregistrée de cette catégorie, ou rien si la
catégorie est vide). `SET.lastItem[catégorie]` retient la dernière section ouverte dans chaque catégorie pendant la
session. Il n'y a plus d'onglet hérité (`SET.tab` et `TABS` retirés à la Slice 09).

- `selectTab(cible)` et `openSettingsTab(cible)` acceptent une catégorie, une section ou un alias hérité de la table
  `LEGACY_TAB_ALIASES` du registre (`settingsTarget` → `shellTarget`) ;
  [`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md) dit lesquels restent.
- Cible inconnue (y compris un ancien ID retiré) : toujours signalée (`console.warn('settings_target_unknown',
  {target})`). `openSettingsTab` ouvre alors le shell sur sa catégorie par défaut (`DEFAULT_CATEGORY` du registre,
  Personnalisation ; si les réglages sont déjà ouverts, l'emplacement y passe) ; `selectTab` et les liens internes
  (`openSettingsLink`) ne changent rien.
- Catégorie seule : dernière section ouverte dans la catégorie, sinon la première.
- `settingsTabs()` rend les six catégories (`{id, label, description}`) : le sous-menu Paramètres de la roue
  Jarvis en fait une ligne par catégorie ; la ligne « Réglages de la voix » ouvre `'voice_audio'`
  (`VOICE_SETTINGS_TARGET` du module de la roue).
- `ui_tab_next` / `ui_tab_prev` (Ctrl+→ / Ctrl+← par défaut) parcourent les six catégories par
  `cycleCategory`, en boucle.

## 3. Clavier, focus, fermeture

- À l'ouverture, l'élément d'ouverture est retenu et le focus va à la catégorie active (page pleine : à l'onglet de
  page ouvert, § 1 bis). À la fermeture, il revient
  à l'élément d'ouverture s'il est encore dans la page (un bouton du popover « Plus d’outils » rend le focus à
  « Plus d’outils »), sinon au bouton Réglages. Il n'est jamais volé à un élément focalisé hors du shell.
- Les deux listes (`#settingsCategories`, `#modalTabs`) sont des onglets ARIA à **activation manuelle** :
  flèches (les deux axes), Début, Fin déplacent le focus sans rien charger ; Entrée, Espace ou un clic ouvre.
  Une catégorie charge des données : la parcourir au clavier ne doit pas déclencher six chargements.
- Après chaque rendu de la navigation, le focus revient sur l'entrée active de la liste qui l'avait. Exception : le
  rail choisit une catégorie en page pleine (§ 1 bis), qui masque le rail ; le focus va alors à l'onglet de page actif
  (à défaut le premier, puis « Paramètres » du fil d'Ariane), jamais sur `body` (reprise QA de la Slice 07). La
  consigne clavier du dialogue (`#settingsHelp`, son `aria-describedby`) suit la disposition : flèches haut et bas
  dans les catégories à rail, gauche et droite dans les onglets d'une page pleine. Changer de
  section ou de catégorie alors que le focus est dans le contenu (un bouton de la section, puis Ctrl+→) le porte à
  l'entrée ouverte, arrivée marquée (`landFocus`, contour visible) : le contenu est remplacé, il ne tombe jamais sur
  `body` (passe de finitions avant la Slice 10).
- Tab et Maj+Tab bouclent dans le shell ; depuis `body`, ils y entrent. Une touche déjà traitée par un module
  (`defaultPrevented` : piège de Tab de la fenêtre d'un cerveau, Architecture & Agents) lui reste : un seul piège actif.
- Quelle que soit la route d'ouverture (bouton, raccourci `s`, roue › Paramètres, `openSettingsTab`), le focus
  finit sur la catégorie active : la roue ne reprend pas un focus qu'une action a porté hors d'elle, et le retour
  à la fermeture se fait sur l'ancre de la roue quand c'est elle qui a ouvert.
- Après « Enregistrer » (bouton désactivé pendant l'envoi), le focus est rendu au bouton.
- **Liens internes (Slice 06).** Un lien d'une section vers une autre cible passe par
  `openSettingsLink(cible, {focus})` (c'est aussi `context.open` des sections et `openTab` du module des sous-agents) :
  le bouton cliqué disparaît avec la section, le focus irait sur `body`. Il va à l'élément `focus` (sélecteur dans le
  contenu) s'il est déjà dessiné — rendu focalisable par `tabindex=-1` au besoin —, sinon à l'entrée ouverte dans
  `#modalTabs` (journal `settings_link_focus_fallback` quand un sélecteur n'a rien trouvé). Cas : « Modifier dans
  Interface & Interactions › Raccourcis » → la touche `wake_toggle` ; « Voir le diagnostic » du Mot d'éveil →
  `#diagnostic_wake_word` ; « Régler la commande », renvois des sous-agents → l'entrée ouverte ; « Voir le
  diagnostic mémoire » passe aussi par là (`#diagnostic_memory`). L'arrivée passe par `JarvisSettingsUI.landFocus` : elle
  est marquée `data-settings-landed` (retiré quand le focus repart) et son contour se voit même quand le lien a été
  cliqué à la souris, où `:focus-visible` ne s'applique pas. **Maintien en vue** (`pinSettingsTarget`, retravail QA
  de la Slice 06, repris de la partie Mémoire de la Slice 05) : la cible trouvée est ramenée en vue à chaque changement
  de taille de son conteneur (une partie ou une section en haut, `block:'start'` ; une petite cible, touche ou bouton,
  juste assez pour être vue, `block:'nearest'`, sans cacher le libellé qui la précède ; les parties Voix et Mot d'éveil des Diagnostics grandissent en se remplissant) tant
  qu'elle a le focus, 4 s au plus ; molette, touche, pointeur ou toucher dans le contenu rendent la main aussitôt ; le
  lien suivant, un changement de section ou de catégorie et la fermeture (`cleanupSettingsSurface` → `stopSettingsPin`)
  arrêtent observateur, écoutes et minuteur. Testé : `test_interface_settings_browser.py` (partie Mot d'éveil visible
  après le remplissage de Voix), `test_wake_word_settings_browser.py`, `test_control_center_memory_settings_js.py`
  (gestes, minuteur, `destroy`), `test_memory_settings_browser.py`.
- **Échap ferme toujours**, même si `ui_close` est réaffecté, même depuis un champ et même quand le focus est
  retombé sur `body` (écoute sur `document` tant que les réglages sont ouverts), sauf : capture d'un raccourci en
  cours (elle le prend avant), zone de texte longue ou éditable (une saisie longue ne ferme pas la page),
  événement déjà consommé (`defaultPrevented`), ou cible hors du shell autre que `body` (une confirmation ouverte
  par-dessus garde son Échap). Le bouton « Fermer » et `ui_close` ferment aussi ; le raccourci `ui_close` (écoute
  de `window`) respecte lui aussi une touche déjà consommée (`defaultPrevented` : menu d'un nœud du canevas
  d'Architecture fermé par Échap, constat de la Slice 08 de `jarvis-architecture-agents-settings-editor`).
- **Pas de fermeture au clic extérieur.** Le shell couvre toute la fenêtre : il n'y a plus d'extérieur, et un clic
  dans un vide du shell fermerait par accident une page en cours de réglage.
- Focus visible : `outline` 2 px accent sur tout élément du shell en `:focus-visible`, champs hérités compris
  (`.field input:focus{outline:none}` ne l'efface plus dans le shell), et sur toute arrivée marquée
  `data-settings-landed`. Un rendu qui remplace une vue rend le focus au contrôle qui l'avait
  (`JarvisSettingsUI.keepFocus`) : sections mémoire, rôles et Work Methods, cartes de Connexions. « Enregistrer la
  mémoire » et « Annuler les changements » sont `aria-disabled` (pas `disabled`) quand ils ne servent à rien : le
  focus y reste pendant et après l'envoi.
- États désactivés et lecture seule : opacité 0,7 dans le shell (au lieu de 0,38 à 0,5), mesurés à 4,5:1 au moins
  sur le fond du shell (`test_settings_accessibility_browser.py`) ; un bloc déjà grisé (profil de routage éteint) ne
  grise pas une seconde fois ses commandes.
- Couleurs forcées (`forced-colors: active`) : l'entrée active est soulignée par `Highlight`, le contour de focus
  et les arrivées prennent `Highlight`, un contrôle désactivé passe en `GrayText` à pleine opacité, badges, notices et
  cartes gardent un trait `CanvasText`.
- `prefers-reduced-motion` : ni fondu d'ouverture, ni entrée du contenu, ni transitions du rail ; dans tout le shell,
  modules compris, animations et transitions réduites à 0,01 ms et une seule itération, défilement non animé.

## 4. Monter une section (Slices 03 à 08)

```js
registerSettingsSection({               // porte de la page : R.page.register derrière un filet
  id: 'wake_word', category: 'voice_audio', label: 'Mot d’éveil', order: 50,
  save: 'self',                         // 'footer' | 'self' | 'readonly' (navigation-registry.md § 2)
  mount(host, context) { … },           // dessine dans `host` (un <div class="set-mount"> neuf)
  destroy(host) { … },                  // arrête minuteurs, requêtes, écouteurs
});
```

- **Où :** le module s'enregistre à son chargement par `registerSettingsSection(spec)`. Un refus est journalisé
  (`settings_section_rejected`, avec `code`) et affiché en notice dans la catégorie visée (Avancé & Diagnostics si
  la catégorie est inconnue) ; la fonction rend `null`, jamais une exception.
- **Ordre des entrées :** sections enregistrées, dans l'ordre du registre (groupe déclaré, puis `order`). Dans une catégorie à groupes, les flèches parcourent les onglets
  seuls, jamais les intitulés ; la liste passe à la ligne au lieu de défiler (en dessous de 900 px, elle défile).
- **`mount(host, context)`** reçoit un hôte neuf à chaque montage. `context` :
  `revision`, `section`, `ui` (`JarvisSettingsUI`), `say(texte, 'ok'|'error'|'')` (pied d'état),
  `open(cible)` (ouvrir une autre cible), `isCurrent()` (faux dès que la section est quittée, la catégorie changée
  ou les réglages fermés : une réponse tardive vérifie `isCurrent()` avant d'écrire), `data()` / `draft()` (les
  données et le brouillon partagés de `/api/settings`), `markDirty()`.
- **`destroy(host)`** est appelé exactement une fois avant tout autre montage, tout changement de catégorie et à la
  fermeture (`cleanupSettingsSurface()` → `destroyRegisteredSection()`). Une exception y est journalisée
  (`settings_section_destroy_failed`) sans bloquer la suite.
- **Échec de montage :** un `mount` qui lève ou rejette laisse dans `host` une notice `role=alert` portant le
  message réel et le code `settings_section_mount_failed`, et la journalise.
- **Pied Enregistrer :** `save: 'footer'` montre le pied et le bouton ; la section écrit dans `context.draft()`,
  appelle `context.markDirty()`, et « Enregistrer » envoie `/api/settings` comme aujourd'hui (`saveDraft`).
  `self` et `readonly` cachent le pied : la section porte ses propres notices ; une catégorie vide aussi.
- Les brouillons ne sont pas gardés par le shell au changement de section : chaque module garde son contrat actuel
  (par exemple `SET.subagentDrafts` des rôles de sous-agents, le brouillon partagé `SET.draft` des sections Voix et
  de Runtime & CLI, l'état du module Mot d'éveil ; la fenêtre d'un cerveau perd son brouillon quand on quitte l'onglet
  Architecture).
- **Diagnostics en parties (Slice 03).** La section `advanced_diagnostics` / `diagnostics` (lecture seule) monte, dans
  l'ordre, les parties inscrites par `registerSettingsDiagnostic({id, label, order, mount(host, context), destroy()})` :
  chaque partie a son titre (`JarvisSettingsUI.section`), reçoit le même `context` que la section et est détruite avec
  elle ; un `mount` qui lève laisse une notice `role=alert` dans sa seule partie. Parties actuelles : Voix (page),
  Mot d'éveil (`control_center_wake_word.js`), Mémoire (page, `installMemorySettingsSections`), Bare Hands
  (`control_center_barehands.js`, Slice 06). Voir [`voice-audio.md`](voice-audio.md), [`memory.md`](memory.md) et
  [`interface-interactions.md`](interface-interactions.md).

## 5. Primitives (`window.JarvisSettingsUI`)

Fragments HTML purs aux classes `.set-*` (styles dans `control_center.html`). Tout paramètre texte est échappé ;
`body`, `control` et `items` sont du HTML déjà construit par l'appelant. Deux aides de focus (`keepFocus`,
`landFocus`) sont les seules à toucher au DOM, et seulement aux éléments qu'on leur donne.

| Primitive | Usage | Accessibilité |
| --- | --- | --- |
| `intro({id, title, description, level})` | tête d'une catégorie ou d'une page | `h2` (ou `h3` avec `level: 3`) |
| `section({id, title, description, body, advanced, applies, badges})` | un groupe titré | `section[aria-labelledby]` ; badges « Avancé » et moment d'application |
| `field({id, label, hint, control, inline})` | une ligne de champ | `label[for=id]` ; aide `#<id>-hint`, à référencer par `aria-describedby` dans `control` |
| `badge(kind, text)` | un état court (`info`, `ok`, `warn`, `bad`, `advanced`, `restart`) | toujours un mot, jamais la couleur seule |
| `appliesBadge(applies)` | moment d'application (`JarvisSettingsRegistry.APPLIES`) | texte : « Au prochain démarrage de Voice »… |
| `notice({kind, title, text, body, live})` | message `info`/`ok`/`warn`/`bad` | `live: 'polite'` → `role=status`, `'assertive'` → `role=alert` |
| `advanced({id, summary, body, open})` | divulgation « avancé » | `<details>` natif |
| `actions(items)` | rangée de boutons | — |
| `keepFocus(host, draw)` | redessiner `host` (`draw()`) sans perdre le focus | le contrôle focalisé (même `id`, sinon même premier attribut `data-*`) le reprend, s'il n'est pas désactivé |
| `landFocus(el, {scroll})` | porter le focus après un saut | marque `data-settings-landed` : contour visible même après un clic |

Depuis la Slice 01 de `refonte-ui-settings`, le même module fabrique aussi les primitives de la fondation visuelle
(panneau verre, médaillon, statistique, ligne, pastille, bouton, liste, curseur, interrupteur, zone de texte,
onglets, choix en cartes, tableau dense, panneau flottant) et leurs liaisons DOM : voir
[`visual-foundation.md`](visual-foundation.md).

## 6. Langage visuel

Contrat détaillé (jetons `--set-*`, primitives, grilles, empilement, où le CSS propre à une page est permis,
fixtures et captures) : [`visual-foundation.md`](visual-foundation.md). Résumé :

- Verre sombre retenu, liserés cyan/bleu fins ; lueur plus vive réservée à l'élément actif ou à l'appel principal ;
  violet en accent secondaire. Médaillons d'icône ronds au liseré néon. Rythme d'espacement de 12 à 20 px.
- Les jetons `--set-ink*`, `--set-hair*`, `--set-font`, `--set-mono` et `--set-field-bg` sont sur `:root` (mêmes
  valeurs qu'avant sur `.settings-shell`) : hub, pages pleine fenêtre, shell et Memory Center les partagent.

- Plein écran, sans cadre flottant : voile sombre `rgba(2,6,10,.80)` et flou de 22 px sur le fond Jarvis (26 px,
  voile plus léger, sous Cosmos : `control_center_work.js`).
- Rail des catégories : une destination par catégorie (pictogramme dessiné, teinte propre, libellé, description
  du registre). Pictogrammes et teintes (`SETTINGS_ICON`, `SETTINGS_HUE`) sont la seule donnée par identifiant de
  catégorie dans la page : de l'apparence, jamais une liste de navigation.
- Texte courant en sans-serif (`Segoe UI Variable Text`, `Segoe UI`, `system-ui`) ; la monospace reste au code,
  aux identifiants et aux diagnostics (`code`, `kbd`, `samp`, `pre`).
- Le contenu hérité garde ses contrôles ; le shell n'en change que la typographie de lecture (titres en casse
  normale, champs, aides, notices encadrées d'un trait de 1 px).
- Largeur : aucun débordement horizontal vérifié à 1920×1080 et 1366×768, à 100 % et 125 % de zoom ; sous 900 px
  le rail passe en barre horizontale défilante. Hauteur faible (≤ 700 px) : rail compacté.
