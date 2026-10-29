/* Coque du Control Center — zones, jetons et commandes de page.

   Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 01. Contrat
   canonique : `docs/control-center-shell.md`. Ce module n'a **aucun état** et
   ne dessine rien : il publie, sous `window.JarvisShell`, ce que les autres
   modules lisaient jusqu'ici chacun dans sa propre copie.

   - `CONTROL_SELECTOR` : les commandes de la page que la scène mesure comme
     des murs (une tenue s'arrête contre elles) et que le rail de capture
     évite. Une commande se déclare par l'attribut `data-shell-control` sur son
     hôte ; la liste n'est plus une chaîne recopiée dans deux modules.
   - `TOKENS` : miroir des jetons `--shell-*` / `--sem-*` posés sur `:root`
     par `control_center.html`. La feuille fait foi ; un test compare les deux.
   - `ZONES` : où vit chaque surface. Une slice qui déplace une surface met à
     jour la zone, le document et la feuille dans le même commit.

   Le registre des rangs d'empilement vit dans le document (une seule source),
   pas ici : `tests/unit/test_control_center_shell_layers.py` le compare aux
   feuilles réelles.

   Inséré par `ControlCenter.index` (`SHELL_SCRIPT_FILE`) **avant** les modules
   qui le lisent (rendu de la scène, rail de capture). Ceux-ci gardent une
   copie de repli de `CONTROL_SELECTOR`, identique (testé), et le disent au
   journal (`shell.missing`) s'ils ne trouvent pas ce module. */
(function(root){
  'use strict';

  const CONTROL_ATTRIBUTE='data-shell-control';
  /* `#sceneLayer>.sc-status` : le bandeau d'état de la scène est créé par le
     rendu de la scène à chaque montage ; il ne peut pas porter l'attribut
     depuis la page, d'où sa mention explicite. */
  const CONTROL_SELECTOR=`[${CONTROL_ATTRIBUTE}],#sceneLayer>.sc-status`;

  /* Hôtes qui doivent porter l'attribut (le test vérifie la page servie). Un
     hôte pas encore déclaré serait listé avec la slice qui le déclarera
     (`slice`) ; l'aperçu de capture l'est depuis la Slice 05. */
  const CONTROL_HOSTS=Object.freeze([
    Object.freeze({selector:'.dock',zone:'top-left'}),
    Object.freeze({selector:'#bgPills',zone:'bottom-centre'}),
    Object.freeze({selector:'.live-banner',zone:'top-right'}),
    Object.freeze({selector:'#panel',zone:'right'}),
    Object.freeze({selector:'#chatPanel',zone:'right'}),
    Object.freeze({selector:'#barehandsHud',zone:'left-edge'}),
    Object.freeze({selector:'#barehandsPalette',zone:'left-edge'}),
    Object.freeze({selector:'#toolWheel',zone:'left-edge'}),
    Object.freeze({selector:'#presentationRail',zone:'right',createdBy:'control_center_presentation_rail.js'}),
    Object.freeze({selector:'#boardsHud',zone:'bottom-left'}),
    Object.freeze({selector:'#boardDropTray',zone:'bottom-centre'}),
    Object.freeze({selector:'#recIndicators',zone:'top-right'}),
    Object.freeze({selector:'#railDock',zone:'right-edge'}),
    Object.freeze({selector:'#screenshotPreview',zone:'left-low'}),
  ]);
  /* Zones de la coque (docs/06 §9). `right` : le rail actif de l'espace de
     travail (Slice 07), sous les panneaux latéraux qui s'ouvrent par-dessus. */
  const ZONES=Object.freeze({
    /* Libre au repos : le lanceur y est depuis le 2026-10-29 (il était en haut à droite). */
    'top-left':'lanceur global : Conversation, Agents, Errors, « Plus d’outils » (Réglages y est replié, refonte S04)',
    /* Depuis le 2026-10-29 : la puce GPT-Live, et sous elle les indicateurs d'enregistrement (REC, audio) tant qu'une capture est
       ouverte, à gauche des bandes ouvertes (`--shell-rails-open-w`). Vide au repos. */
    'top-right':'puce GPT-Live tant qu’une session est ouverte, indicateurs d’enregistrement (REC, audio) tant qu’une capture est ouverte ; vide au repos',
    'left-edge':'ancre et roue d’outils (JARVIS, Sélection, Dossier, Capture, Paramètres)',
    'left-low':'aperçu de la dernière capture d’écran (Slice 05), au-dessus du contexte bas-gauche',
    'bottom-left':'zone de contexte : carte Board (type, titre, bascule, présence de la voix), notes de la scène',
    'bottom-centre':'centre d’état (Slice 06) : pastilles d’arrière-plan ; plateau de dépôt au-dessus',
    /* Les boutons « Présentations » et « Chat » (`#railDock`), empilés, centrés en hauteur, à gauche de la bande ouverte la plus à gauche. */
    'right-edge':'boutons des rails : Présentations, et dessous Chat (#railDock)',
    'right':'bandes pleine hauteur : rail des présentations (#presentationRail, Slice 07), et le Chat (#chatPanel) toujours le plus à droite ; panneaux latéraux par-dessus',
    'centre':'Board / scène',
  });

  /* Miroir des jetons de `:root` (control_center.html). Valeur de base, puis
     valeurs responsives sous `max-width`. */
  const TOKENS=Object.freeze({
    '--shell-gutter':'18px',
    '--shell-bottom':'18px',
    '--shell-status-h':'44px',
    '--shell-control':'34px',
    '--shell-launcher-w':'154px',
    '--shell-panel-top':'64px',
    '--shell-panel-w':'500px',
    '--shell-panel-bottom':'68px',
    '--shell-rail-w':'272px',
    '--shell-chat-w':'min(500px,calc(100vw - 2 * var(--shell-gutter) - var(--shell-control) - 8px))',
    '--shell-anchor-w':'14px',
    '--shell-wheel-r':'224px',
    '--shell-wedge-min':'48px',
    '--shell-icon':'20px',
    '--shell-icon-sm':'15px',
    '--shell-radius':'12px',
    '--shell-glass-bg':'rgba(5,11,16,.46)',
    '--shell-glass-strong':'rgba(4,10,15,.80)',
    '--shell-stroke':'rgba(174,205,220,.12)',
    '--shell-stroke-active':'color-mix(in srgb,var(--accent) 46%,transparent)',
    '--shell-focus':'var(--accent)',
    '--shell-focus-w':'2px',
    '--shell-focus-offset':'2px',
    '--shell-band-bg':'linear-gradient(180deg,rgba(2,6,10,.82),rgba(3,8,13,.68))',
    '--shell-band-grain':'repeating-linear-gradient(0deg,rgba(255,255,255,.028) 0 1px,transparent 1px 3px),repeating-linear-gradient(90deg,rgba(255,255,255,.016) 0 1px,transparent 1px 3px)',
    '--shell-band-shadow':'-12px 0 40px rgba(0,0,0,.42),inset 1px 0 0 rgba(174,205,220,.08)',
    '--shell-chat-open-w':'0px',
    '--shell-rails-open-w':'0px',
    '--shell-panel-open-w':'0px',
    '--sem-alert':'#ff9f43',
    '--sem-done':'var(--ok)',
    '--sem-question':'var(--accent)',
    '--sem-working':'#4da3ff',
    '--sem-review':'#ffd166',
    '--sem-problem':'#ff6a4d',
    '--shell-ease':'cubic-bezier(.2,.7,.2,1)',
    '--shell-dur-fast':'120ms',
    '--shell-dur':'180ms',
  });
  const RESPONSIVE_TOKENS=Object.freeze({
    'max-width:700px':Object.freeze({'--shell-gutter':'10px','--shell-panel-top':'88px'}),
  });
  /* Sous `prefers-reduced-motion: reduce`, ces durées valent 0 ms. */
  const MOTION_TOKENS=Object.freeze(['--shell-dur-fast','--shell-dur']);

  /* Surfaces exclusives (jarvis-board-ui-wheel-dossier-refactor, Slice 03) :
     jamais deux ouvertes ensemble. Chacune annonce son ouverture et sa
     fermeture par cet événement de `document` (`detail: {id, open}`) et se
     ferme quand une autre s'ouvre. Pas d'état ici : chaque surface tient le
     sien. Les modules gardent une copie de repli du nom, identique (testé). */
  const EXCLUSIVE_EVENT='jarvis:shell-exclusive';
  const EXCLUSIVE_SURFACES=Object.freeze({
    'tool-wheel':'#toolWheel[data-open] (control_center_tool_wheel.js)',
    'board-panel':'#boardsPanel (control_center_boards.js)',
  });

  const api=Object.freeze({
    CONTROL_ATTRIBUTE,CONTROL_SELECTOR,CONTROL_HOSTS,ZONES,TOKENS,RESPONSIVE_TOKENS,MOTION_TOKENS,
    EXCLUSIVE_EVENT,EXCLUSIVE_SURFACES,
  });
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- bloc navigateur */

  root.JarvisShell=api;
  /* Une ligne au journal pour dire que la coque est là et combien de
     commandes elle voit ; un hôte attendu sans l'attribut est signalé (une
     commande non mesurée laisserait la scène glisser dessous). */
  const missing=[];
  for(const host of CONTROL_HOSTS){
    if(host.slice||host.createdBy)continue;
    const el=document.querySelector(host.selector);
    if(el&&!el.hasAttribute(CONTROL_ATTRIBUTE))missing.push(host.selector);
  }
  const controls=document.querySelectorAll(`[${CONTROL_ATTRIBUTE}]`).length;
  if(missing.length)console.warn(`[shell] shell.control_unmarked ${JSON.stringify({hosts:missing})}`);
  console.info(`[shell] shell.installed ${JSON.stringify({controls})}`);
})(typeof globalThis!=='undefined'?globalThis:this);
