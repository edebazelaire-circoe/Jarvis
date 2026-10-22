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

## 1. Ce que le shell possède

Le shell possède l'ouverture et la fermeture, les six catégories, les entrées d'une catégorie, le focus, le
clavier, le nettoyage des sections et la mise en page. Une section possède ses contrôles, ses données et sa
validation. Aucune valeur de réglage n'est écrite par le shell.

```
#overlay (plein écran, voile + flou du fond Jarvis)
└─ #settingsShell  role=dialog aria-modal
   ├─ aside.set-rail
   │  ├─ h2#modalTitle « Réglages »
   │  └─ nav#settingsCategories role=tablist (vertical ; horizontal sous 900 px)
   │       six button.set-cat role=tab [data-category] : pictogramme, libellé, description (registre)
   └─ main#settingsMain role=tabpanel
      ├─ .set-head : #settingsIntro (pictogramme + JarvisSettingsUI.intro + avis `notice` de la catégorie,
      │              p#settingsCategoryNotice) · #closeModal « Fermer · Échap »
      ├─ nav#modalTabs role=tablist : sections de la catégorie, button.set-item [data-section] ;
      │     catégorie à groupes (Avancé, Slice 08) : div.set-group role=none [data-settings-group] par groupe non
      │     vide, intitulé span.set-group-label (aria-hidden, monospace) qui décrit ses onglets (aria-describedby)
      ├─ #modalContent.set-body.content : le contenu, SEUL à défiler
      └─ footer.set-foot : #modalStatus (role=status, aria-live=polite) · #modalSave « Enregistrer »
```

Les identifiants historiques (`overlay`, `modalTitle`, `modalTabs`, `modalContent`, `modalStatus`, `modalSave`,
`closeModal`) sont conservés : les modules et leurs tests les lisent. `#settingsRelated` (liens « encore dans ») et
`#modalSub` (phrase d'onglet hérité) sont retirés avec le système d'onglets (Slice 09). Les noms de fonctions
`renderTabs` (navigation), `renderTab` (monte la section active) et `selectTab` (ouvre une cible) restent : ce sont
les points d'appel du shell et des modules, ils ne concernent plus d'onglet.

## 2. Emplacement et routage

L'emplacement est `SET.category`, puis `SET.section` (une section enregistrée de cette catégorie, ou rien si la
catégorie est vide). `SET.lastItem[catégorie]` retient la dernière section ouverte dans chaque catégorie pendant la
session. Il n'y a plus d'onglet hérité (`SET.tab` et `TABS` retirés à la Slice 09).

- `selectTab(cible)` et `openSettingsTab(cible)` acceptent une catégorie, une section ou un alias hérité de la table
  `LEGACY_TAB_ALIASES` du registre (`settingsTarget` → `shellTarget`) ;
  [`../legacy/settings-tab-aliases.md`](../legacy/settings-tab-aliases.md) dit lesquels restent.
- Cible inconnue (y compris un ancien ID retiré) : toujours signalée (`console.warn('settings_target_unknown',
  {target})`). `openSettingsTab` ouvre alors le shell sur sa catégorie par défaut (`DEFAULT_CATEGORY` du registre,
  Voix & audio ; si les réglages sont déjà ouverts, l'emplacement y passe) ; `selectTab` et les liens internes
  (`openSettingsLink`) ne changent rien.
- Catégorie seule : dernière section ouverte dans la catégorie, sinon la première.
- `settingsTabs()` rend les six catégories (`{id, label, description}`) : le sous-menu Paramètres de la roue
  Jarvis en fait une ligne par catégorie ; la ligne « Réglages de la voix » ouvre `'voice_audio'`
  (`VOICE_SETTINGS_TARGET` du module de la roue).
- `ui_tab_next` / `ui_tab_prev` (Ctrl+→ / Ctrl+← par défaut) parcourent les six catégories par
  `cycleCategory`, en boucle.

## 3. Clavier, focus, fermeture

- À l'ouverture, l'élément d'ouverture est retenu et le focus va à la catégorie active. À la fermeture, il revient
  à l'élément d'ouverture s'il est encore dans la page (un bouton du popover « Plus d’outils » rend le focus à
  « Plus d’outils »), sinon au bouton Réglages. Il n'est jamais volé à un élément focalisé hors du shell.
- Les deux listes (`#settingsCategories`, `#modalTabs`) sont des onglets ARIA à **activation manuelle** :
  flèches (les deux axes), Début, Fin déplacent le focus sans rien charger ; Entrée, Espace ou un clic ouvre.
  Une catégorie charge des données : la parcourir au clavier ne doit pas déclencher six chargements.
- Après chaque rendu de la navigation, le focus revient sur l'entrée active de la liste qui l'avait. Changer de
  section ou de catégorie alors que le focus est dans le contenu (un bouton de la section, puis Ctrl+→) le porte à
  l'entrée ouverte, arrivée marquée (`landFocus`, contour visible) : le contenu est remplacé, il ne tombe jamais sur
  `body` (passe de finitions avant la Slice 10).
- Tab et Maj+Tab bouclent dans le shell ; depuis `body`, ils y entrent.
- Quelle que soit la route d'ouverture (bouton, raccourci `s`, roue › Paramètres, `openSettingsTab`), le focus
  finit sur la catégorie active : la roue ne reprend pas un focus qu'une action a porté hors d'elle, et le retour
  à la fermeture se fait sur l'ancre de la roue quand c'est elle qui a ouvert.
- Après « Enregistrer » (bouton désactivé pendant l'envoi), le focus est rendu au bouton.
- **Liens internes (Slice 06).** Un lien d'une section vers une autre cible passe par
  `openSettingsLink(cible, {focus})` (c'est aussi `context.open` des sections et `openTab` du module des sous-agents) :
  le bouton cliqué disparaît avec la section, le focus irait sur `body`. Il va à l'élément `focus` (sélecteur dans le
  contenu) s'il est déjà dessiné — rendu focalisable par `tabindex=-1` au besoin —, sinon à l'entrée ouverte dans
  `#modalTabs` (journal `settings_link_focus_fallback` quand un sélecteur n'a rien trouvé). Cas : « Modifier dans
  Interface & interactions › Raccourcis » → la touche `wake_toggle` ; « Voir le diagnostic » du Mot d'éveil →
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
  par-dessus garde son Échap). Le bouton « Fermer » et `ui_close` ferment aussi.
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
  (`settings_section_rejected`, avec `code`) et affiché en notice dans la catégorie visée (Avancé & diagnostic si
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
  Agents & modèles, l'état du module Mot d'éveil).
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

## 6. Langage visuel

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
