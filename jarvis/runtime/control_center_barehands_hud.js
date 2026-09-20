/* Bare Hands — contrôle de cycle de vie de la barre du haut.

   Décision 1 de l'affinage d'UI : Bare Hands est un contrôle de premier plan
   de l'écran principal, et non d'abord une fonction de l'onglet Expérimental.
   Ce module en est la seule implantation : un bouton carré à icône de main en
   haut à gauche, et un sélecteur visuel à trois états ouvert au clic
   (décisions 2 à 6).

   **Ce module ne tient aucun cycle de vie.** C'est une projection, et le mot
   est littéral : il n'a ni variable d'état, ni minuterie de cycle de vie, ni
   optimisme local. Il s'abonne à `JarvisBarehands.openLifecycleSeam` et peint
   ce qu'il reçoit ; il change d'état en appelant les **mêmes portes** que le
   panneau et que la voix (`enable` / `disable` / `activate` / `sleep`). Une
   seconde mémoire ici serait exactement la dérive que la décision 7 interdit :
   un réveil en C, un retour en veille après 30 s ou une caméra refusée
   changeraient l'état sans que le bouton le sache, et l'écran mentirait sans
   que rien ne tombe.

   Ce qu'il tient, lui, est de l'affichage et rien d'autre : le compteur de
   secondes du démarrage (RÈGLE ZÉRO — une attente sans borne doit dire depuis
   combien de temps elle dure, sans quoi « ça travaille » et « c'est figé » se
   ressemblent), l'ouverture du sélecteur, et le curseur de navigation au
   clavier.

   Les cinq présentations, et pourquoi elles sont cinq alors que la décision 6
   n'offre que trois modes :

   - `off` — gris fortement atténué (décision 3) ;
   - `sleep` — bleu Jarvis ordinaire, sans emphase (décision 4) ;
   - `active` — bleu électrique plus clair, avec un halo discret (décision 5).
     **Pas vert** : l'idée d'un actif vert a été explicitement retirée ;
   - `starting` — le démarrage attend `getUserMedia`, donc une invite de
     permission qu'un humain met le temps qu'il veut à lire. Le peindre
     « éteint » dirait que l'utilisateur l'a voulu, et le peindre « en veille »
     dirait que ça marche. Il a donc sa présentation, son mouvement et son
     compteur, et le sélecteur reste atteignable pour en sortir ;
   - `error` — arrêté **sans** l'avoir demandé (contrat § 1). Ce n'est pas un
     quatrième mode sélectionnable : aucune pastille n'est cochée, et le `code`
     du motif (`camera_denied`, `camera_busy`, `assets_missing`…) s'affiche tel
     quel. Une caméra refusée peinte comme un `off` choisi est exactement la
     panne qui disparaît de l'état, et c'est pour l'empêcher qu'`ERROR` existe.

   Insertion : `control_center.py` / `control_center.html`, APRÈS
   `control_center_barehands.js`, qui pose `window.JarvisBarehands` et la
   couture de cycle de vie. Le bloc navigateur les lit au chargement et
   **refuse de s'installer** sans eux : servi trop tôt, le contrôle n'apparaît
   pas et la console dit pourquoi, à l'insertion et non trois clics plus tard.
   Le refus est **rattrapé ici**, comme celui du canal de commandes, parce que
   la page servie concatène tous ses modules dans une seule balise `<script>` :
   une levée qui remonterait emporterait la scène, la timeline et le Test Lab
   avec elle. L'ordre est asserté par `test_barehands_hud_js`. */
(function(root){
  'use strict';

  /* Les contrats, lus **directement** : un module de page absent est une
     erreur d'insertion, pas un état d'exécution. Le vocabulaire du cycle de
     vie vit là-bas et nulle part ailleurs — aucun nom n'est recopié ici. */
  const BH=root.JarvisBarehandsContracts
    ||(typeof JarvisBarehandsContracts!=='undefined'?JarvisBarehandsContracts:null);
  if(!BH)throw new Error('JarvisBarehandsHud : control_center_barehands_contracts.js doit être inséré avant ce module');

  /* Les identifiants que la page, les tests et les Slices suivantes cherchent.
     Le menu contextuel de la Slice 02 s'accrochera à `triggerId` ; la palette
     d'outils de la Slice 03 viendra sous `hostId`. */
  const DOM=Object.freeze({
    hostId:'barehandsHud',
    styleId:'barehandsHudStyle',
    triggerId:'barehandsHudButton',
    chooserId:'barehandsHudChooser',
    captionId:'barehandsHudCaption',
    noteId:'barehandsHudNote',
    hintId:'barehandsHudHint',
    announceId:'barehandsHudAnnounce',
    /* L'attribut que chaque pastille du sélecteur porte, sur le modèle de
       `data-barehands-tool` de l'onglet Expérimental. */
    modeAttribute:'data-barehands-mode',
    toneAttribute:'data-bh-tone',
    /* Le nom sous lequel ce module s'inscrit à la couture. Il est lisible par
       `JarvisBarehands.lifecycleSeam()` : « le bouton écoute » ne doit pas
       s'écrire comme « personne n'écoute ». */
    seamName:'hud',
  });

  /* Les trois modes **sélectionnables**, dans l'ordre où ils se présentent :
     éteint, veille, actif. Les noms viennent du contrat ; `ERROR` n'y est pas,
     et c'est tout le propos. */
  const MODES=Object.freeze([BH.LIFECYCLE.OFF,BH.LIFECYCLE.SLEEP,BH.LIFECYCLE.ACTIVE]);
  /* Présentations. Les trois premières sont les modes ; les deux autres sont
     des états que l'on subit et que l'on ne choisit pas. */
  const TONE=Object.freeze({OFF:BH.LIFECYCLE.OFF,SLEEP:BH.LIFECYCLE.SLEEP,
    ACTIVE:BH.LIFECYCLE.ACTIVE,STARTING:'starting',ERROR:BH.LIFECYCLE.ERROR});

  const MODE_LABEL=Object.freeze({off:'Éteint',sleep:'Veille',active:'Actif'});
  const CAPTION=Object.freeze({off:'ÉTEINT',sleep:'VEILLE',active:'ACTIF',
    starting:'DÉMARRAGE',error:'INTERROMPU'});
  /* Ce que chaque mode **fait**, en français, sous le sélecteur. Trois phrases
     et trois conséquences réelles : OFF est le seul où le réveil en C ne peut
     rien, parce que c'est le seul où la caméra est rendue. */
  const MODE_HINT=Object.freeze({
    off:'Caméra libérée. La posture en C ne peut pas rallumer Bare Hands.',
    sleep:`Guetteur léger (${Math.round(1000/BH.WAKE_INTERVAL_MS)} images par seconde, aucun clic) : la posture en C réveille l’interaction.`,
    active:`Les mains pilotent l’interface. Sans main exploitable, retour en veille au bout de ${Math.round(BH.SLEEP_TIMEOUT_MS/1000)} s.`,
  });

  /* -------------------------------------------------------- vue, sans DOM */

  /* Ce que la couture publie, traduit en ce que l'écran doit peindre. Pur :
     aucune lecture de page, aucune horloge — c'est ce que les tests exercent
     sans navigateur. */
  function presentationOf(snapshot){
    const snap=snapshot&&typeof snapshot==='object'?snapshot:{};
    const lifecycle=BH.LIFECYCLES.includes(String(snap.lifecycle))
      ?String(snap.lifecycle)
      :BH.lifecycleOfControllerState(String(snap.state||BH.LIFECYCLE.OFF));
    const starting=!!snap.starting;
    const tone=starting?TONE.STARTING:lifecycle;
    return Object.freeze({
      tone,lifecycle,starting,
      /* La pastille cochée. **Aucune** pendant un démarrage (rien n'a encore
         atterri) et aucune sur une panne (personne ne l'a choisie) : cocher
         `off` dans ces deux cas est précisément le mensonge que la décision 7
         et le contrat § 1 refusent. */
      selected:!starting&&MODES.includes(lifecycle)?lifecycle:null,
      code:snap.code===undefined||snap.code===null?null:String(snap.code),
      title:String(snap.title||''),message:String(snap.message||''),
      enabled:!!snap.enabled,
      /* Une écriture de réglage en vol : `saveSettings` refuserait la suivante
         avec un mot que personne n'a demandé, donc le sélecteur se désarme et
         le bouton le montre. */
      busy:!!snap.busy,
    });
  }

  /* L'étiquette sous le bouton. Le démarrage y porte **son compteur** : c'est
     la seule chose qui distingue une attente qui avance d'une page figée, et
     elle continue de monter même quand les animations sont coupées. */
  function captionOf(view,seconds){
    if(view.tone===TONE.STARTING)return `${CAPTION.starting} ${Math.max(0,Math.round(seconds||0))} S`;
    return CAPTION[view.tone]||CAPTION.off;
  }

  /* La phrase lue par les lecteurs d'écran et affichée au survol. Elle dit
     l'état, le motif quand il y en a un, et **comment en sortir** quand
     l'attente peut durer. */
  function labelOf(view,seconds){
    if(view.tone===TONE.STARTING)
      return `Bare Hands démarre depuis ${Math.max(0,Math.round(seconds||0))} secondes. `
        +'Si le navigateur attend votre autorisation, répondez à l’invite ; '
        +'choisissez Éteint pour annuler — la caméra est rendue dès qu’elle arrive.';
    if(view.tone===TONE.ERROR)
      return `Bare Hands s’est interrompu${view.code?` (${view.code})`:''}. `
        +`${view.message||view.title} Choisissez un mode pour relancer.`;
    return `Bare Hands : ${MODE_LABEL[view.tone]||view.tone}. Ouvrir le choix du mode.`;
  }

  /* Le bandeau du sélecteur : ce qu'il faut savoir avant de choisir. Vide
     quand il n'y a rien à dire — un bandeau permanent cesse d'être lu. */
  function noteOf(view,seconds,failure){
    if(failure)return {tone:'bad',text:failure};
    if(view.tone===TONE.ERROR)
      return {tone:'bad',text:`${view.title}${view.code?` · ${view.code}`:''} — ${view.message}`};
    if(view.tone===TONE.STARTING)
      return {tone:'wait',text:`Démarrage depuis ${Math.max(0,Math.round(seconds||0))} s. `
        +'Choisir Éteint annule et rend la caméra.'};
    /* L'interrupteur maître dit non alors que le moteur tourne : cela arrive
       quand l'enregistrement du réglage a échoué (le moteur suit, le fichier
       non). Le dire plutôt que le laisser découvrir au rechargement. */
    if(!view.enabled&&BH.isLiveLifecycle(view.lifecycle))
      return {tone:'wait',text:'Le réglage n’a pas été enregistré : Bare Hands sera éteint au prochain chargement.'};
    return null;
  }

  /* ------------------------------------------------- la main schématique */

  const SVG_NS='http://www.w3.org/2000/svg';
  /* Décision 20 : des mains **schématiques**, en trait, pas d'anatomie. C'est
     le premier tracé de ce vocabulaire dans la page — des os droits, des
     articulations marquées, un châssis de paume — et la calibration reprendra
     celui-ci plutôt que d'en dessiner un second. Le tracé vit ici, en données,
     pour que les deux usages (bouton 64 px, pastille 46 px) soient le même
     dessin à deux tailles. */
  const HAND_PALM='M6.5 12.6v4.2a3.8 3.8 0 0 0 3.8 3.8h3.9a3.9 3.9 0 0 0 3.9-3.9v-4.1';
  const HAND_BONES=Object.freeze([
    'M6.5 12.6h11.6',          // châssis des jointures
    'M9 12.4V6.7',             // index
    'M12 12.1V5.2',            // majeur
    'M15 12.4V6.7',            // annulaire
    'M17.7 12.6V8.7',          // auriculaire
    'M7 13.5 4.7 10.8',        // pouce
  ]);
  const HAND_JOINTS=Object.freeze([[9,9.4],[12,8.5],[15,9.4],[17.7,10.5],[5.85,11.95]]);

  function handIcon(doc,size){
    const svg=doc.createElementNS(SVG_NS,'svg');
    svg.setAttribute('viewBox','0 0 24 24');
    svg.setAttribute('class','bh-hud-icon');
    svg.setAttribute('width',String(size));svg.setAttribute('height',String(size));
    svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width','1.5');
    svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');
    svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
    for(const d of [HAND_PALM].concat(HAND_BONES)){
      const path=doc.createElementNS(SVG_NS,'path');
      path.setAttribute('d',d);svg.appendChild(path);
    }
    for(const joint of HAND_JOINTS){
      const dot=doc.createElementNS(SVG_NS,'circle');
      dot.setAttribute('cx',String(joint[0]));dot.setAttribute('cy',String(joint[1]));
      dot.setAttribute('r','.95');dot.setAttribute('fill','currentColor');
      dot.setAttribute('stroke','none');svg.appendChild(dot);
    }
    return svg;
  }

  /* ------------------------------------------------------------- la feuille

     Les couleurs passent par l'indirection de thème, comme partout ailleurs
     dans Bare Hands : jamais un hexadécimal nu, toujours le jeton suivi de son
     repli. L'échelle des trois tons est écrite **une seule fois** et portée
     par `data-bh-tone` : le bouton et les trois pastilles du sélecteur la
     lisent par héritage de propriétés personnalisées, donc « actif » a la même
     définition aux deux endroits, par construction et non par recopie. */
  const ACCENT='var(--omega-accent,var(--accent,#6ee7ff))';
  const MUTED='var(--omega-muted,var(--muted,#7190a0))';
  const DANGER='var(--omega-danger,var(--danger,#ff6577))';

  const STYLE=`
/* **Aucun \`z-index\` sur l'emplacement, et c'est délibéré.** Un rang posé ici
   ouvrirait un contexte d'empilement, et le sélecteur — 36, au-dessus du
   bandeau GPT-Live — s'y retrouverait enfermé sous les 32 du bouton : il
   passerait derrière le panneau (33) et derrière la bannière (35) qu'il est
   censé recouvrir. Les rangs vivent donc sur les deux éléments positionnés
   eux-mêmes. Même raison pour la variante étroite plus bas, qui centre par
   \`calc()\` et non par \`transform\` : une transformation ouvre le même piège. */
#${DOM.hostId}{position:absolute;top:76px;left:18px;width:64px;
  display:flex;flex-direction:column;align-items:center;gap:7px;
  font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;
  /* \`.topbar\` coupe les événements de pointeur pour laisser passer les clics
     vers le visage. Ce contrôle vit à côté d'elle et non dedans, mais il les
     rétablit chez lui : rangé un jour sous un parent inerte, il resterait
     cliquable au lieu de se taire. */
  pointer-events:auto}
#${DOM.hostId}[data-bh-tone=off],#${DOM.hostId} [data-bh-tone=off]{
  --bh-hud-ink:color-mix(in srgb,${MUTED} 55%,transparent);
  --bh-hud-line:color-mix(in srgb,${MUTED} 20%,transparent);
  --bh-hud-face:rgba(3,8,12,.62);--bh-hud-glow:none;
  --bh-hud-cap:color-mix(in srgb,${MUTED} 72%,transparent)}
#${DOM.hostId}[data-bh-tone=sleep],#${DOM.hostId} [data-bh-tone=sleep],
#${DOM.hostId}[data-bh-tone=starting]{
  --bh-hud-ink:color-mix(in srgb,${ACCENT} 78%,transparent);
  --bh-hud-line:color-mix(in srgb,${ACCENT} 26%,transparent);
  --bh-hud-face:rgba(3,8,12,.82);--bh-hud-glow:none;
  --bh-hud-cap:color-mix(in srgb,${ACCENT} 68%,transparent)}
/* Plus clair **et** entouré : c'est la seule présentation qui porte un halo,
   et c'est ce qui la rend lisible d'un coup d'œil à côté de la veille. */
#${DOM.hostId}[data-bh-tone=active],#${DOM.hostId} [data-bh-tone=active]{
  --bh-hud-ink:color-mix(in srgb,${ACCENT} 84%,#fff);
  --bh-hud-line:color-mix(in srgb,${ACCENT} 66%,transparent);
  --bh-hud-face:color-mix(in srgb,${ACCENT} 9%,rgba(3,8,12,.86));
  --bh-hud-glow:0 0 0 1px color-mix(in srgb,${ACCENT} 24%,transparent),
    0 0 26px color-mix(in srgb,${ACCENT} 30%,transparent),
    inset 0 0 20px color-mix(in srgb,${ACCENT} 12%,transparent);
  --bh-hud-cap:color-mix(in srgb,${ACCENT} 88%,#fff)}
#${DOM.hostId}[data-bh-tone=error]{
  --bh-hud-ink:color-mix(in srgb,${DANGER} 88%,transparent);
  --bh-hud-line:color-mix(in srgb,${DANGER} 52%,transparent);
  --bh-hud-face:rgba(22,6,10,.86);
  --bh-hud-glow:0 0 20px color-mix(in srgb,${DANGER} 24%,transparent);
  --bh-hud-cap:${DANGER}}
#${DOM.hostId} .bh-hud-btn{position:relative;z-index:32;width:64px;height:64px;display:grid;place-items:center;
  padding:0;border:1px solid var(--bh-hud-line);border-radius:12px;background:var(--bh-hud-face);
  color:var(--bh-hud-ink);box-shadow:var(--bh-hud-glow);cursor:pointer;
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
  transition:color .18s ease,border-color .18s ease,box-shadow .26s ease,background .18s ease,transform .12s ease}
#${DOM.hostId} .bh-hud-btn:hover{border-color:color-mix(in srgb,var(--bh-hud-ink) 72%,transparent)}
#${DOM.hostId} .bh-hud-btn:active{transform:scale(.96)}
#${DOM.hostId} .bh-hud-btn:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
#${DOM.hostId} .bh-hud-icon{display:block;color:inherit}
/* Le halo qui respire, et lui seul : l'actif est le seul état où quelque
   chose tourne vraiment, donc le seul à avoir le droit de bouger au repos. */
#${DOM.hostId}[data-bh-tone=active] .bh-hud-btn::before{content:'';position:absolute;inset:-7px;
  border-radius:17px;pointer-events:none;
  background:radial-gradient(closest-side,color-mix(in srgb,${ACCENT} 20%,transparent),transparent 78%);
  animation:bhHudBreathe 3.6s ease-in-out infinite}
@keyframes bhHudBreathe{0%,100%{opacity:.5}50%{opacity:1}}
/* RÈGLE ZÉRO : une attente se voit bouger. Armée pendant le démarrage **et**
   pendant une écriture de réglage en vol — les deux peuvent durer, et une
   page immobile ne dit pas laquelle des deux. */
#${DOM.hostId} .bh-hud-wait{position:absolute;left:9px;right:9px;bottom:8px;height:2px;border-radius:2px;
  overflow:hidden;display:none;background:color-mix(in srgb,var(--bh-hud-ink) 22%,transparent)}
#${DOM.hostId}[data-bh-tone=starting] .bh-hud-wait,
#${DOM.hostId}[data-bh-busy=true] .bh-hud-wait{display:block}
#${DOM.hostId} .bh-hud-wait::after{content:'';position:absolute;top:0;bottom:0;left:0;width:42%;
  border-radius:2px;background:currentColor;animation:bhHudSweep 1.25s ease-in-out infinite}
@keyframes bhHudSweep{from{transform:translateX(-115%)}to{transform:translateX(255%)}}
/* Une panne ne se lit pas « éteint » : elle porte une marque qu'aucun mode ne
   porte, en plus de sa couleur. */
#${DOM.hostId} .bh-hud-alert{position:absolute;right:-4px;top:-4px;width:12px;height:12px;border-radius:50%;
  display:none;background:${DANGER};box-shadow:0 0 10px color-mix(in srgb,${DANGER} 60%,transparent)}
#${DOM.hostId}[data-bh-tone=error] .bh-hud-alert{display:block}
#${DOM.hostId} .bh-hud-cap{position:relative;z-index:32;width:max-content;max-width:136px;text-align:center;white-space:nowrap;
  font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--bh-hud-cap);
  transition:color .18s ease}
/* Le sélecteur : trois fois le **même** motif de main, directement cliquables
   (décision 6). Ni liste déroulante, ni cycle aveugle. */
#${DOM.hostId} .bh-hud-pop{position:absolute;z-index:36;top:100%;left:0;margin-top:12px;
  min-width:244px;padding:13px 14px 12px;border:1px solid var(--line,#183343);border-radius:12px;
  background:var(--panel,rgba(6,12,18,.94));box-shadow:0 18px 44px rgba(0,0,0,.5);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
  animation:bhHudPop .16s ease-out}
#${DOM.hostId} .bh-hud-pop[hidden]{display:none}
@keyframes bhHudPop{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
#${DOM.hostId} .bh-hud-pop h3{margin:0 0 10px;font-size:9px;font-weight:400;letter-spacing:.18em;
  text-transform:uppercase;color:${MUTED}}
#${DOM.hostId} .bh-hud-opts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
#${DOM.hostId} .bh-hud-opt{display:flex;flex-direction:column;align-items:center;gap:7px;
  padding:9px 4px 8px;border:1px solid transparent;border-radius:10px;background:transparent;
  color:inherit;font:inherit;cursor:pointer;transition:background .14s ease,border-color .14s ease}
#${DOM.hostId} .bh-hud-opt:hover:not([disabled]){background:rgba(110,231,255,.05);border-color:var(--line,#183343)}
#${DOM.hostId} .bh-hud-opt:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
#${DOM.hostId} .bh-hud-opt[disabled]{opacity:.45;cursor:not-allowed}
#${DOM.hostId} .bh-hud-opt[aria-checked=true]{border-color:color-mix(in srgb,${ACCENT} 45%,transparent);
  background:rgba(110,231,255,.07)}
#${DOM.hostId} .bh-hud-chip{width:46px;height:46px;display:grid;place-items:center;border-radius:10px;
  border:1px solid var(--bh-hud-line);background:var(--bh-hud-face);color:var(--bh-hud-ink);
  box-shadow:var(--bh-hud-glow)}
/* Le halo de l'actif, à l'échelle de la pastille : le même effet, pas la même
   taille — un halo de 64 px autour d'un carré de 46 px baverait sur ses
   voisins et « actif » cesserait d'être lisible comme un choix parmi trois. */
#${DOM.hostId} .bh-hud-chip[data-bh-tone=active]{
  box-shadow:0 0 0 1px color-mix(in srgb,${ACCENT} 24%,transparent),
    0 0 15px color-mix(in srgb,${ACCENT} 28%,transparent)}
#${DOM.hostId} .bh-hud-note{margin:0 0 10px;padding:7px 9px;border-radius:8px;font-size:10px;line-height:1.5;
  color:${DANGER};border:1px solid color-mix(in srgb,${DANGER} 34%,transparent);background:rgba(35,7,12,.45)}
#${DOM.hostId} .bh-hud-note[data-bh-note=wait]{color:var(--warn,#ffb85c);
  border-color:color-mix(in srgb,var(--warn,#ffb85c) 34%,transparent);background:rgba(38,23,5,.45)}
#${DOM.hostId} .bh-hud-note[hidden]{display:none}
#${DOM.hostId} .bh-hud-hint{margin:11px 0 0;font-size:10px;line-height:1.55;color:${MUTED};min-height:3.1em}
#${DOM.hostId} .bh-hud-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:700px){
  /* En dessous de 700 px la barre du haut se resserre (\`left:10px\`), la marque
     disparaît et la bannière GPT-Live vient occuper la bande juste sous elle :
     le coin haut-gauche n'est plus libre. Le contrôle descend donc sur le bord
     gauche, en miroir du dock — le même côté que la palette d'outils à venir,
     et plus aucun croisement avec le texte de la marque ni avec la bannière. */
  #${DOM.hostId}{top:calc(50% - 41px);left:10px}
}
@media(prefers-reduced-motion:reduce){
  /* Le mouvement s'arrête, pas l'information : le compteur de secondes sous le
     bouton continue de monter, et c'est lui qui distingue « ça travaille » de
     « c'est figé » quand plus rien ne bouge. */
  #${DOM.hostId} .bh-hud-btn,#${DOM.hostId} .bh-hud-cap,#${DOM.hostId} .bh-hud-opt{transition:none}
  #${DOM.hostId} .bh-hud-btn::before,#${DOM.hostId} .bh-hud-wait::after,
  #${DOM.hostId} .bh-hud-pop{animation:none}
}`;

  /* ------------------------------------------------------- le contrôle DOM */

  /* Toutes les dépendances sont injectées : le document, la surface Bare Hands
     et l'horloge. Rien n'est lu dans un global depuis l'intérieur, ce qui est
     la seule façon d'exercer ce contrôle sous node. */
  function createHudControl(deps){
    const doc=deps.document,host=deps.host;
    const surfaceOf=deps.surface,now=deps.now;
    const arm=deps.setInterval,disarm=deps.clearInterval,later=deps.setTimeout;
    const log=deps.log||function(){};

    let snapshot=null,view=presentationOf(null);
    let opened=false,cursor=0,failure='',choosing=false;
    /* L'horloge du démarrage. C'est de l'**affichage** : elle ne décide de
       rien, elle ne survit pas au départ du démarrage, et le cycle de vie
       n'en dépend pas. */
    let bootSince=0,bootTimer=0,spoken='';

    ensureStyle();
    const trigger=doc.createElement('button');
    trigger.id=DOM.triggerId;trigger.className='bh-hud-btn';
    trigger.setAttribute('type','button');
    trigger.setAttribute('aria-haspopup','menu');
    trigger.setAttribute('aria-expanded','false');
    trigger.setAttribute('aria-controls',DOM.chooserId);
    trigger.appendChild(handIcon(doc,34));
    const wait=doc.createElement('span');
    wait.className='bh-hud-wait';wait.setAttribute('aria-hidden','true');
    trigger.appendChild(wait);
    const alert=doc.createElement('span');
    alert.className='bh-hud-alert';alert.setAttribute('aria-hidden','true');
    trigger.appendChild(alert);
    host.appendChild(trigger);

    const caption=doc.createElement('span');
    caption.id=DOM.captionId;caption.className='bh-hud-cap';
    caption.setAttribute('aria-hidden','true');
    host.appendChild(caption);

    const pop=doc.createElement('div');
    pop.id=DOM.chooserId;pop.className='bh-hud-pop';
    pop.setAttribute('role','menu');
    pop.setAttribute('aria-label','Mode Bare Hands');
    pop.hidden=true;
    const popTitle=doc.createElement('h3');
    popTitle.textContent='Bare Hands';
    pop.appendChild(popTitle);
    const note=doc.createElement('p');
    note.id=DOM.noteId;note.className='bh-hud-note';note.hidden=true;
    pop.appendChild(note);
    const opts=doc.createElement('div');
    opts.className='bh-hud-opts';
    pop.appendChild(opts);

    const options=MODES.map((mode,index)=>{
      const el=doc.createElement('button');
      el.setAttribute('type','button');
      /* `menuitemradio` et non `radio` : dans un menu, les flèches **déplacent
         le focus sans choisir**, et c'est exactement ce qu'il faut ici.
         Un groupe de radios choisit en passant dessus ; traverser ce
         sélecteur-là au clavier ouvrirait la caméra puis la rendrait à chaque
         touche — un défaut plausible que personne n'a demandé. */
      el.setAttribute('role','menuitemradio');
      el.setAttribute(DOM.modeAttribute,mode);
      el.className='bh-hud-opt';
      el.setAttribute('aria-checked','false');
      el.setAttribute('tabindex','-1');
      const chip=doc.createElement('span');
      chip.className='bh-hud-chip';
      chip.setAttribute(DOM.toneAttribute,mode);
      chip.setAttribute('aria-hidden','true');
      chip.appendChild(handIcon(doc,26));
      el.appendChild(chip);
      const cap=doc.createElement('span');
      cap.className='bh-hud-cap';cap.textContent=CAPTION[mode];
      el.appendChild(cap);
      el.addEventListener('click',()=>{choose(mode)});
      el.addEventListener('keydown',event=>onOptionKey(event,index));
      el.addEventListener('focus',()=>{cursor=index;paintHint(mode)});
      el.addEventListener('mouseenter',()=>paintHint(mode));
      el.addEventListener('focusout',scheduleOutsideClose);
      opts.appendChild(el);
      return {mode,el,chip};
    });

    const hint=doc.createElement('p');
    hint.id=DOM.hintId;hint.className='bh-hud-hint';
    pop.appendChild(hint);
    host.appendChild(pop);

    const announce=doc.createElement('div');
    announce.id=DOM.announceId;announce.className='bh-hud-sr';
    announce.setAttribute('role','status');
    announce.setAttribute('aria-live','polite');
    host.appendChild(announce);

    trigger.addEventListener('click',()=>{opened?close({focus:true}):open()});
    trigger.addEventListener('keydown',onTriggerKey);
    trigger.addEventListener('focusout',scheduleOutsideClose);

    function ensureStyle(){
      if(doc.getElementById(DOM.styleId))return;
      const style=doc.createElement('style');
      style.id=DOM.styleId;style.textContent=STYLE;
      doc.head.appendChild(style);
    }

    /* ------------------------------------------------------------ peinture */

    const bootSeconds=()=>bootSince?Math.max(0,(now()-bootSince)/1000):0;

    function paintHint(mode){hint.textContent=MODE_HINT[mode]||''}

    /* Le compteur de démarrage. Armé **par l'état**, jamais par un clic : un
       démarrage venu de la voix ou d'un rechargement doit compter comme celui
       qu'on a déclenché soi-même. */
    function paintBootClock(){
      if(view.tone!==TONE.STARTING){
        if(bootTimer){disarm(bootTimer);bootTimer=0}
        bootSince=0;return;
      }
      if(bootSince)return;
      bootSince=now();
      bootTimer=arm(()=>{
        if(view.tone!==TONE.STARTING){disarm(bootTimer);bootTimer=0;bootSince=0;return}
        paintClockText();
      },1000);
    }

    function paintClockText(){
      const seconds=bootSeconds();
      caption.textContent=captionOf(view,seconds);
      trigger.setAttribute('aria-label',labelOf(view,seconds));
      trigger.setAttribute('title',labelOf(view,seconds));
      if(opened)paintNote(seconds);
    }

    function paintNote(seconds){
      const said=noteOf(view,seconds,failure);
      note.hidden=!said;
      note.textContent=said?said.text:'';
      if(said)note.setAttribute('data-bh-note',said.tone);
      else note.removeAttribute('data-bh-note');
    }

    function paint(){
      host.setAttribute(DOM.toneAttribute,view.tone);
      host.setAttribute('data-bh-lifecycle',view.lifecycle);
      host.setAttribute('data-bh-busy',view.busy?'true':'false');
      trigger.setAttribute('aria-busy',view.tone===TONE.STARTING||view.busy?'true':'false');
      paintBootClock();
      paintClockText();
      for(let i=0;i<options.length;i+=1){
        const option=options[i];
        const on=option.mode===view.selected;
        option.el.setAttribute('aria-checked',on?'true':'false');
        option.el.disabled=view.busy;
        /* Un seul arrêt de tabulation dans le menu : le curseur, qui vaut le
           mode courant tant que personne n'a déplacé le focus. */
        option.el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      if(!opened){
        const at=options.findIndex(option=>option.mode===view.selected);
        cursor=at<0?0:at;
        for(let i=0;i<options.length;i+=1)
          options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      paintNote(bootSeconds());
      if(!hint.textContent)paintHint(view.selected||MODES[cursor]);
      speak();
    }

    /* Ce que le lecteur d'écran entend, et **seulement quand ça change** : une
       région vivante qui répète le même mot à chaque repeinture cesse d'être
       écoutée. */
    function speak(){
      const line=view.tone===TONE.ERROR
        ?`Bare Hands interrompu${view.code?` : ${view.code}`:''}.`
        :view.tone===TONE.STARTING?'Bare Hands démarre.'
        :`Bare Hands : ${MODE_LABEL[view.tone]||view.tone}.`;
      if(line===spoken)return;
      spoken=line;announce.textContent=line;
    }

    /* --------------------------------------------------------- ouverture */

    function open(){
      if(opened)return false;
      opened=true;
      pop.hidden=false;
      trigger.setAttribute('aria-expanded','true');
      paintNote(bootSeconds());
      paintHint(options[cursor].mode);
      focusAt(cursor);
      return true;
    }

    function close(options_){
      if(!opened)return false;
      opened=false;
      pop.hidden=true;
      trigger.setAttribute('aria-expanded','false');
      if(options_&&options_.focus&&typeof trigger.focus==='function')
        try{trigger.focus()}catch(_error){/* retiré entre-temps */}
      return true;
    }

    function focusAt(index){
      cursor=(index+options.length)%options.length;
      for(let i=0;i<options.length;i+=1)
        options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      const target=options[cursor].el;
      if(typeof target.focus==='function')try{target.focus()}catch(_error){/* retiré entre-temps */}
      paintHint(options[cursor].mode);
    }

    function onTriggerKey(event){
      const key=event&&event.key;
      if(key==='Escape'&&opened){event.preventDefault();close({focus:true});return}
      if(key!=='ArrowDown'&&key!=='ArrowUp')return;
      event.preventDefault();
      if(!opened)open();
      else focusAt(key==='ArrowDown'?cursor+1:cursor-1);
    }

    function onOptionKey(event,index){
      const key=event&&event.key;
      if(key==='Escape'){event.preventDefault();close({focus:true});return}
      if(key==='Home'||key==='End'){event.preventDefault();focusAt(key==='Home'?0:options.length-1);return}
      const step=key==='ArrowRight'||key==='ArrowDown'?1
        :key==='ArrowLeft'||key==='ArrowUp'?-1:0;
      if(!step)return;
      event.preventDefault();
      focusAt(index+step);
    }

    /* Le focus a quitté le contrôle : le menu se ferme. Vérifié **après** que
       le focus a atterri — `focusout` part avant que `activeElement` ne soit à
       jour, et refermer trop tôt volerait le clic qu'on est en train de faire. */
    function scheduleOutsideClose(){
      later(()=>{
        if(!opened)return;
        const at=doc.activeElement;
        if(at===trigger)return;
        for(const option of options)if(option.el===at)return;
        close({focus:false});
      },0);
    }

    /* ------------------------------------------------------------- choix */

    /* Les transitions, sur les **mêmes portes** que le panneau et que la voix.
       Rien n'est réimplanté : une seconde implantation de « réveiller »
       diverge le jour où l'une des deux change, et personne ne voit laquelle
       l'utilisateur a prise. */
    async function choose(mode){
      if(choosing)return null;
      if(!MODES.includes(mode))
        throw Object.assign(new Error(`mode Bare Hands inconnu : ${mode}`),
          {code:'barehands_hud_mode_unknown'});
      choosing=true;failure='';
      close({focus:true});
      try{
        const surface=surfaceOf();
        if(!surface)
          throw Object.assign(new Error('window.JarvisBarehands absent'),
            {code:'barehands_hud_surface_missing'});
        if(mode===BH.LIFECYCLE.OFF){
          /* OFF est le seul mode où la posture en C ne peut rien, parce que
             c'est le seul où la caméra est **rendue** et l'interrupteur maître
             écrit à faux — donc le seul qui survive au rechargement. C'est
             `disable()`, jamais `sleep()`. */
          await surface.disable();
        }else if(mode===BH.LIFECYCLE.SLEEP){
          /* Endormir d'abord si la main pilote : `enable()` ne fait pas sortir
             d'ACTIVE, personne d'autre ne le ferait. Puis `enable()`, qui arme
             le guetteur depuis `off` comme depuis une panne, et persiste le
             maître. */
          if(view.lifecycle===BH.LIFECYCLE.ACTIVE)await surface.sleep();
          await surface.enable();
        }else{
          /* `activate()` porte la chaîne entière depuis `off` ou depuis une
             panne : il allume, guette, puis réveille, en une seule attente.
             `enable()` vient **après**, pour persister le maître sans rien
             éteindre. Appelé avant, il laisserait le contrôleur en démarrage —
             et `activate()`, qui rend la main tout de suite dans cet état,
             n'aurait rien à réveiller. */
          await surface.activate();
          await surface.enable();
        }
        log('info','barehands.hud_mode_selected',{mode});
        return mode;
      }catch(error){
        /* Un refus se dit, sous sa cause réelle, à l'écran **et** au journal.
           Le silence ici rendrait « le bouton n'a rien fait » indiscernable de
           « le bouton a fait quelque chose qui a échoué ». */
        failure=`Le mode « ${MODE_LABEL[mode]} » n’a pas été pris : ${(error&&error.message)||error}`;
        log('error','barehands.hud_mode_refused',
          {mode,code:(error&&error.code)||null,error:String((error&&error.message)||error)});
        announce.textContent=failure;spoken=failure;
        /* **Le refus se voit.** Le sélecteur s'était refermé sur le choix ; il
           se rouvre sur la phrase qui dit pourquoi, là où l'utilisateur vient
           de cliquer. Une région vivante seule ne parle qu'aux lecteurs
           d'écran, et un contrôle qui redevient silencieux après un clic est
           indiscernable d'un contrôle qui n'a rien reçu. */
        open();
        paintNote(bootSeconds());
        return null;
      }finally{
        choosing=false;
        paint();
      }
    }

    function render(next){
      snapshot=next;
      view=presentationOf(next);
      paint();
      return view;
    }

    render(null);

    return {
      element:host,trigger,chooser:pop,
      render,choose,open,close,
      isOpen:()=>opened,
      /* Ce que l'écran **peint**, par opposition à ce que le moteur dit : les
         deux doivent coïncider, et c'est la seule façon de le vérifier sans
         lire des pixels. */
      presentation:()=>view,
      snapshot:()=>snapshot,
      failure:()=>failure,
      destroy(){
        if(bootTimer){disarm(bootTimer);bootTimer=0}
        trigger.remove();caption.remove();pop.remove();announce.remove();
      },
    };
  }

  const api=Object.freeze({DOM,MODES,TONE,MODE_LABEL,MODE_HINT,CAPTION,STYLE,
    presentationOf,captionOf,labelOf,noteOf,handIcon,createHudControl});
  root.JarvisBarehandsHud=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installJarvisBarehandsHud(){
    const surface=window.JarvisBarehands;
    if(!surface)
      throw new Error('JarvisBarehandsHud : control_center_barehands.js doit être inséré avant ce module');
    if(typeof surface.openLifecycleSeam!=='function')
      throw Object.assign(new Error('JarvisBarehandsHud : la couture de cycle de vie manque sur window.JarvisBarehands'),
        {code:'barehands_hud_seam_missing'});
    /* L'emplacement est **déclaré dans la page**, pas fabriqué ici : c'est lui
       qui porte le rang d'empilement du registre de `control_center.html`, et
       un contrôle qui se poserait tout seul au bout du `body` en sortirait
       sans que rien ne le dise. Absent, on refuse sous un nom cherchable
       plutôt que de choisir un parent plausible. */
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error(`JarvisBarehandsHud : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'barehands_hud_host_missing'});

    const control=createHudControl({
      document,host,
      surface:()=>window.JarvisBarehands,
      now:()=>Date.now(),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),
      log:(level,event,data)=>{
        const line=`[barehands] ${event} ${JSON.stringify(data)}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    /* **L'abonnement, et rien d'autre.** Le contrôle ne sonde pas, ne devine
       pas et ne part d'aucun état d'usine : la couture lui remet l'instantané
       courant tout de suite, puis chaque transition, d'où qu'elle vienne. */
    surface.openLifecycleSeam(DOM.seamName,state=>control.render(state));
    window.JarvisBarehandsHudControl=Object.freeze({
      presentation:control.presentation,snapshot:control.snapshot,
      isOpen:control.isOpen,open:control.open,close:control.close,
      choose:control.choose,failure:control.failure,
    });
    console.info('[barehands] barehands.hud_installed '
      +JSON.stringify({seam:surface.lifecycleSeam()}));
  }

  /* **La levée reste, mais elle ne sort pas d'ici.** La page servie n'a qu'une
     seule balise `<script>` : tous les modules Bare Hands, la scène, la
     timeline, le Test Lab et ~2500 lignes de logique de page y sont concaténés,
     donc une levée non rattrapée avorterait tout ce qui suit. L'intention
     — casser à l'insertion, pas trois clics plus tard — est juste ; son rayon
     ne doit pas l'être. Rattrapée ici, la panne garde sa portée : ce contrôle
     ne s'installe pas, le reste de la page vit, et la console porte la cause. */
  try{
    installJarvisBarehandsHud();
  }catch(error){
    console.error('[barehands] barehands.hud_not_installed '
      +JSON.stringify({code:(error&&error.code)||null,
        error:String((error&&error.message)||error)}));
  }
})(typeof window!=='undefined'?window:globalThis);
