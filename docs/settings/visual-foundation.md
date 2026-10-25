# Réglages — fondation visuelle partagée

> Niveau 3 (contrat + implémentation réutilisable + tests de conformité). Établi par la Slice 01 de la tâche
> `refonte-ui-settings` (2026-10-24). Les pages Personnalisation, Sous-agents, Architecture, Mémoire et Memory Center
> (Slices 02 à 06) se composent avec ce qui suit ; elles ne redéfinissent ni panneau verre, ni onglets, ni contrôles.

Implémentation : jetons `:root` et classes `.set-*` dans `jarvis/runtime/control_center.html` (bloc « fondation
visuelle partagée », juste après les primitives du shell) ; fragments et liaisons dans
`jarvis/runtime/control_center_settings_ui.js` (`window.JarvisSettingsUI`). Tests : `tests/unit/test_settings_visual_foundation_js.py`
(fragments, jetons), `tests/unit/test_settings_visual_foundation_browser.py` (vrai Chrome). Galerie de référence :
`tests/unit/_settings_primitives_gallery.js`.

## 1. Règles

- **Présentation seulement.** Une primitive ne porte aucun état métier : valeur, plage, désactivé, « en cours »,
  liste d'options et libellés viennent du contrôleur de la page (schéma servi, registre, catalogue). Aucune donnée de
  maquette dans la couche partagée.
- **Jetons, pas de valeurs en dur.** Couleur, rayon, espacement, taille de texte, lueur et rang d'empilement se lisent
  dans les jetons `--set-*`. Une page change une teinte en posant `--set-tone` (ou `.set-tone-*`) sur un ancêtre.
- **Le texte reste du texte.** Titres et réglages en sans-serif (`--set-font`) ; la monospace reste au code, aux
  identifiants et aux diagnostics. Pas de typographie « HUD » (capitales espacées) hors du fil d'Ariane.
- **Un état ne se dit jamais par la couleur seule** : pastille et badge portent un mot ; l'interrupteur a
  `aria-checked` et, au besoin, un texte d'état.
- **Pas de défilement horizontal de page.** Un contenu large défile dans son propre conteneur (`.set-table-scroll`,
  `.set-tabs-scroll`) ; tout enfant de grille a `min-width:0`.

## 2. Jetons (`:root`)

| Famille | Jetons | Remarque |
| --- | --- | --- |
| Encre | `--set-ink`, `--set-ink-2` (secondaire), `--set-ink-3` (atténué), `--set-ink-label` | anciennement sur `.settings-shell`, mêmes valeurs |
| Filets | `--set-hair`, `--set-hair-2`, `--set-hair-3`, `--set-hair-4` | du plus discret au survol |
| Verre | `--set-glass`, `--set-glass-2` (fin du dégradé), `--set-glass-sunken` (groupe enfoncé), `--set-glass-float` (flottant), `--set-field-bg`, `--set-blur`, `--set-veil` | opacités retenues des maquettes |
| Teintes | `--set-blue`, `--set-cyan` (= `--accent`), `--set-violet`, `--set-magenta`, `--set-teal`, `--set-amber`, `--set-accent` (bleu), `--set-accent-2` (violet), `--set-tone` (teinte courante, héritée) | le violet est un accent secondaire |
| Sémantique | `--set-ok`, `--set-warn`, `--set-bad`, `--set-off` | alias de `--ok`, `--warn`, `--danger` |
| Bord et lueur | `--set-edge` (34 %, repos), `--set-edge-hot` (72 %, actif), `--set-glow`, `--set-glow-hot`, `--set-lift` | ombres sans couleur : `box-shadow: var(--set-glow) var(--set-tone)` |
| Focus, désactivé | `--set-focus`, `--set-focus-w`, `--set-focus-offset`, `--set-disabled` (.7, même seuil que le shell) | |
| Rayons | `--set-r-xs` 6, `--set-r-sm` 10, `--set-r-md` 12 (contrôles), `--set-r-lg` 14 (lignes, tuiles), `--set-r-xl` 18 (panneaux), `--set-r-pill` | |
| Espacements | `--set-sp-1…8` (4 à 32 px), `--set-gap` (gouttière de grille), `--set-panel-pad`, `--set-view-pad`, `--set-view-max` | rythme 12–20 px |
| Texte | `--set-font`, `--set-mono`, `--set-fs-display`, `--set-fs-title`, `--set-fs-body`, `--set-fs-label`, `--set-fs-small`, `--set-fs-micro`, `--set-fs-stat` | |
| Contrôles | `--set-control-h` (40), `--set-control-h-sm` (32) | |
| Empilement | `--set-z-raised` 1, `--set-z-sticky` 2, `--set-z-float` 20, `--set-z-popover` 30, `--set-z-chrome` 40 | rangs **internes** à l'overlay (60) ou au workspace (55), voir § 5 |

Durées et courbe : celles de la coque (`--shell-dur-fast`, `--shell-dur`, `--shell-ease`), remises à 0 sous
`prefers-reduced-motion` ; les primitives n'ont pas d'autres durées.

## 3. Primitives

Chaque ligne : classes (écrites à la main ou produites par le fragment), fragment `JarvisSettingsUI`, états.
Texte échappé par le fragment ; `icon` (un SVG), `body`, `control`, `aside`, `actions`, `items` sont du HTML de
l'appelant.

| Primitive | Classes | Fragment | États et accessibilité |
| --- | --- | --- | --- |
| Vue pleine fenêtre | `.set-view` > `.set-page` | — | seule à défiler ; `.set-page` est le conteneur des requêtes de grille |
| En-tête de page | `.set-page-head`, `.set-crumb`, `.set-title-row` > `.set-title-icon` + `.set-title`, `.set-lead`, `.set-rule` | — | titre léger `--set-fs-display` ; fil d'Ariane en texte ; icône de la catégorie (`settingsIcon`) à sa teinte, `aria-hidden` |
| Boutons de page | `.set-hub-close` (×), `.set-hub-back` (←) | — | ronds, fixes en haut à gauche (`--set-z-chrome`), nom accessible en français, anneau de focus |
| Panneau verre | `.set-panel` (+ `-hot`, `-quiet`), `.set-panel-head/-titles/-title/-desc/-aside/-body`, `.set-inset` | `panel({id,title,description,icon,tone,aside,body,variant,level})` | `section[aria-labelledby]` |
| Médaillon d'icône | `.set-medallion` (+ `-sm`, `-lg`) | `medallion({icon,tone,size})` | `aria-hidden` |
| Tuile de statistique | `.set-stat` (+ `-stack`), `.set-stat-icon/-value/-label` | `stat({value,label,icon,tone,stack})` | libellé obligatoire |
| Ligne libellé + contrôle | `.set-rows` > `.set-row` (+ `-plain`, `-wide`), `.set-row-icon/-text/-label/-hint/-control` | `row({id,label,hint,icon,tone,control,plain,wide})` | `<id>-label` et `<id>-hint` à référencer par le contrôle |
| Pastille d'état | `.set-dot` (+ `-ok`, `-warn`, `-bad`, `-info`, `-off`) ; badges `.set-badge*` du shell, `+ .set-badge-accent` | `dot(kind,text,{className})`, `badge(kind,text)` | toujours un mot (texte vide : erreur ; un état absent s'affiche « — » chez l'appelant) ; `className` : accroche ajoutée devant `set-dot` |
| Bouton néon | `.set-btn` (+ `-primary`, `-ghost`, `-danger`, `-sm`, `-icon`) | `button({id,label,variant,size,icon,iconOnly,tone,disabled,busy,data,describedBy})` | survol, pressé, focus, `disabled`, `aria-busy=true` (anneau tournant, figé sous mouvement réduit) |
| Liste déroulante | `.set-select` > `select` | `select({id,options,value,label,labelledBy,describedBy,disabled})` | native, chevron dessiné |
| Saisie | `.set-input` | — | `aria-invalid=true` : bord rouge |
| Curseur | `.set-range-field` (+ `-inline`, `-bare`) > `input.set-range`, `.set-range-value`, `.set-range-ends`/`.set-range-end` | `range({id,min,max,step,value,label,labelledBy,minLabel,maxLabel,inlineEnds,showValue,format,decimals,suffix,disabled})` | remplissage `--set-range-fill` dès le premier rendu ; `aria-valuetext` ; `--set-range-end-w` aligne les pistes d'une pile de curseurs à bornes en ligne ; désactivé : teinte neutre, sans lueur |
| Interrupteur | `button.set-switch[role=switch]` > `.set-switch-track` (+ `.set-switch-text`) | `toggle({id,checked,label,labelledBy,describedBy,stateText,tone,disabled,busy})` | `aria-checked` ; désactivé inerte, teinte neutre et piste pointillée |
| Zone de texte + compteur | `.set-textarea` > `textarea` + `.set-textarea-count` | `textarea({id,value,maxLength,placeholder,label,labelledBy,describedBy,rows})` | compteur lié par `aria-describedby` ; `[data-over]` au plafond |
| Onglets internes | `.set-tabs` (+ `-fill`, `-scroll`) > `.set-tab` | `tabs({id,label,items,selected,fill,scroll})` | `role=tablist`, tabulation itinérante, flèches/Début/Fin |
| Segmenté | `.set-seg` > `label.set-seg-opt` > `input[type=radio]` + `span` | — | groupe radio natif |
| Choix en cartes | `fieldset.set-choices` > `label.set-choice` | `choices({name,legend,items,value,disabled,tone})` | groupe radio natif, `legend` |
| Tableau dense | `.set-table-shell` > `.set-table-scroll` > `table.set-table` ; `.set-table-foot`, `.set-num` | `table({id,label,columns,body,foot})` | région nommée et focalisable (défilement au clavier), en-tête collant |
| Panneau flottant | `.set-float` (+ `-popover`), `.set-float-head/-titles/-eyebrow/-title/-actions` | `float({id,title,eyebrow,body,actions,tone,popover})` | `role=dialog` nommé ; `openFloat` (§ 4) |
| Grilles | `.set-grid` + `.set-span-{2…9,12}`, `.set-grid-auto` (`--set-col-min`), `.set-workbench` (`--set-rail-w`), `.set-stack` | — | § 6 |
| Teintes | `.set-tone-{blue,cyan,violet,magenta,teal,amber,ok,warn,bad,off}` | paramètre `tone` | |

## 4. Liaisons DOM

Chacune ne touche qu'aux éléments donnés et rend sa fonction de détachement (à appeler au `destroy` de la section).

- `bindRange(input,{format,onInput})` / `syncRange` : remplissage, texte de valeur, `aria-valuetext`.
- `bindCounter(textarea)` / `syncCounter` : compteur `n/max`, `data-over`.
- `bindToggle(button,onChange)` / `setToggle(button,checked)` : bascule **l'affichage** et appelle `onChange(next)` ;
  le contrôleur repose l'état réel par `setToggle` après un refus ou un échec.
- `wireTabs(list,onSelect)` / `setTab(list,id,{focus})` : clic, flèches, Début, Fin.
- `openFloat(panel,{trigger,initialFocus,onClose})` → `close(reason)` (idempotent : rouvrir un panneau déjà ouvert
  rend le même `close`, sans doubler les écouteurs) : focus dans le panneau, `aria-expanded` sur le
  déclencheur ; Échap (consommé : les Réglages ne se ferment pas), `[data-set-float-close]` ou un clic extérieur
  ferment et rendent le focus au déclencheur (`reason` : `escape`, `button`, `outside`, `api`).
- `bindAll(host)` : tous les curseurs et compteurs d'un rendu neuf.

## 5. Empilement et focus

- Les rangs `--set-z-*` ordonnent des enfants **dans** l'overlay des Réglages (60) ou le workspace (55) ; ils sont
  déclarés au registre de `docs/control-center-shell.md` (§ Contained ranks : préfixes `.set-table`, `.set-float`).
  Un panneau flottant est en `position:absolute` dans son conteneur positionné ; un module qui a besoin d'une couche
  plein écran garde la sienne (ex. `.bcp-layer`) et l'inscrit au registre.
- Anneau de focus : `outline: var(--set-focus-w) solid var(--set-focus)`, décalé de `--set-focus-offset`. Une règle à
  spécificité nulle le pose dans `.set-view`, `.set-page` et `.set-float` (le shell a déjà la sienne) ; une primitive
  peut le préciser, jamais le retirer.
- Désactivé : opacité `--set-disabled`, curseur interdit, plus de lueur ni de déplacement ; un contrôle désactivé
  n'est pas un arrêt de Tab.

## 6. Grilles et largeurs

- `.set-grid` : 12 colonnes. Requêtes de **conteneur** sur `.set-page` : sous 1080 px de large, 2 colonnes
  (`.set-span-2…6` → une colonne, `.set-span-7…12` → la rangée) ; sous 640 px, une colonne. Sans ancêtre
  `.set-page`, la grille ne se replie pas (elle se resserre sans déborder).
- `.set-page` (`container-type:inline-size`) n'est **pas** un bloc conteneur pour ses descendants `position:fixed`
  (vérifié dans Chrome : un enfant fixe se place sur la fenêtre). Une couche plein écran (`.bcp-layer`) peut donc
  vivre dedans. Seul bloc conteneur préexistant à surveiller : `.overlay` sous le thème Cosmos (`backdrop-filter`).
  Un panneau `.set-float` (absolu) se place par rapport à son ancêtre positionné le plus proche.
- `.set-grid-auto` : 3/2/1 colonnes sans requête (chaque colonne ≥ `--set-col-min`, 300 px par défaut).
- `.set-workbench` : surface de travail + rail (`--set-rail-w`), une colonne sous 1080 px de conteneur.
- Mesuré sans débordement horizontal (page, vue, panneaux) à 1672×941, 1254×1254, 1280×800, 125 % de zoom de
  1672×941 (1338×753) et de 1254×1254 (1003×1003), 1000×800 et 600×900.

## 7. Où le CSS propre à une page est permis

- Composition de la page (placement dans la grille, tailles de rangées, régions propres : canevas, matrice de
  routage, lignes de rôles) : dans la feuille de la page (`control_center.html` pour Personnalisation, Mémoire,
  Memory Center ; `STYLE` du module pour Architecture et Sous-agents), sous le préfixe de la page (`.perso-`,
  `.arch-`, `.bcp-`, `.sar-`, `.mem-`, `.mc-`).
- Interdit dans une page : redéfinir l'apparence d'une primitive (verre, liseré, onglet, interrupteur, curseur,
  bouton), coder une couleur, un rayon ou une ombre que donne un jeton. Un besoin récurrent devient une primitive ici.
- La page Personnalisation a migré sur ces primitives (Slice 02, 2026-10-24) : ses doublons (`.perso-card`,
  `.perso-switch`, `.perso-seg`…) sont supprimés ; il ne reste sous `.perso-` que sa composition.
- Mémoire et Memory Center ont migré à la Slice 07 : panneaux `.set-panel` (`-hot` pour l'appel au Memory Center,
  `-quiet` pour la bande Avancé), médaillons, interrupteurs (`JarvisSettingsUI.toggle`), curseurs `.set-range`, cartes
  de mode `.set-choice` (seul écart voulu : le témoin radio reste visible au coin, pour l'état désactivé lisible),
  pastilles `.set-dot`, badges `.set-badge`, boutons `.set-btn`, onglets internes `.set-tabs-fill`, champs
  `.set-input`. Les classes `.mem-*` / `.mc-*` restantes sont la composition et des accroches de tests. Reprise QA :
  les filtres du Memory Center sont des `.set-select` (chevron), le compteur de conflits d'un candidat un
  `.set-badge-warn` ; la case « Remplacées » reste une case native (aucune primitive de case : l'interrupteur est un
  `button[role=switch]`, hors du formulaire de filtres) ; jetons morts `--mc-glass`, `--mem-glass`, `--mem-r` retirés ;
  colonnes Portée et Rétention du tableau des notes masquées sous 640 px de conteneur (et non 720), pour qu'elles se
  voient à 1254 px comme sur la maquette.
- Reste hors fondation, volontairement : `.mcpp-switch` (Plugins & MCP). Cette vue garde le style compact de la console
  MCP (hors maquettes) et son contrat de feuille est épinglé par `test_control_center_mcp_plugins_js.py` ; la migrer
  serait une refonte de Plugins & MCP, pas une convergence.
- Titres de panneau : les règles héritées `.content h3` et `.settings-shell .content h3` (titres de section des
  anciennes pages) excluent `.set-panel-title` et `.set-float-title` (Slice 07). Un panneau monté dans `#modalContent`
  garde la typographie de la fondation sans contournement local.

## 8. Fixtures et captures

Outillage : `tests/unit/settings_visual.py` (aide Python) sur le harnais CDP partagé
`tests/unit/_wake_word_settings_browser.mjs`.

- Fenêtres : `VIEWPORTS` = `wide` 1672×941 (maquettes 01-03), `square` 1254×1254 (04-05), `narrow` 1280×800 ;
  `zoomed(size)` donne la fenêtre CSS à 125 %. `REFERENCE_VIEWPORT[vue]` dit la fenêtre de chaque vue.
- Vues : `VIEWS` ouvre `hub`, `perso`, `subagents`, `architecture`, `memory`, `memory_center` depuis la page servie
  par la fixture `served` (Control Center isolé, runtime temporaire, jamais le JARVIS vivant). `memory_center` ouvre
  l'onglet Memory Center de Mémoire & Connaissances (sa seule maison depuis la Slice 06).
- Captures finales des cinq vues (Slice 07) : `tests/unit/test_settings_page_layout_browser.py`
  (`test_final_captures_of_the_five_views_have_no_horizontal_overflow`, une session de navigateur par vue : le plan
  passe en argument au harnais, de longueur bornée sous Windows).
- Fixtures déterministes : `stub(path, json, method=, status=)` dans l'étape (`stubs`) : la requête de la page reçoit
  ce JSON, le serveur n'est pas appelé. La donnée de démonstration vit dans le test, jamais dans un composant.
- Figer : `freeze()` met les animations à leur état final, coupe transitions et caret.
- Capturer : `capture_steps(VIEWS[vue], dossier, nom, viewports=[...], zoom=, stubs=, ext="jpg")` ouvre, attend,
  fige, mesure `OVERFLOW` (page et conteneurs des Réglages) et photographie `<nom>-<l>x<h>[-z125].<ext>`.
- Action `script` du harnais : évalue un fichier (fixture JS) puis une expression — un plan reste court.
- `JARVIS_BROWSER_SHOTS=<dossier>` garde les captures ; sinon elles vont dans le dossier temporaire du test.
  Preuves gardées en JPEG (`.jpg`, qualité 82).
