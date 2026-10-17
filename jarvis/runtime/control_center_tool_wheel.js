/* Roue d'outils orbitale du bord gauche.

   Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 02 (architecture
   résolue `docs/06-resolved-architecture.md` D3, D4, §4, §10). Contrat :
   `docs/control-center-shell.md` › Roue d'outils.

   Une **nouvelle surface** (D3) : ni la palette Bare Hands, ni le rail de
   capture. Au repos, seule une ancre de `--shell-anchor-w` dépasse du bord
   gauche ; la souris qui l'atteint, la main Bare Hands dont le pointeur
   synthétique l'atteint (même `pointerover`, aucun geste nouveau), ou le
   clavier (Entrée, Espace, flèche droite sur l'ancre) déploient le même
   demi-cercle de quatre secteurs : Sélection, Vidéo, Capture d'écran, Audio,
   dans cet ordre, sans outil de remplissage.

   - Survoler ou pointer un secteur le **met en avant** (un seul libellé, celui
     du secteur en avant) ; l'activer, c'est `click` — souris, Entrée, Espace,
     pincement principal Bare Hands —, **jamais** `pointerup` : un pincement ne
     déclenche donc qu'une fois (Bare Hands envoie pointerdown, mousedown,
     pointerup, mouseup, click).
   - L'activation secondaire est le canal existant (D4) : clic droit, pincement
     pouce + majeur Bare Hands (un vrai `contextmenu`), touche `ContextMenu` ou
     `Maj+F10`. Jamais d'appui long (décision 22 de Bare Hands). Elle ouvre un
     **sous-arc** radial dont l'action fournit les entrées : le même motif
     servira au choix Souris / Bare Hands de Sélection (S03) et aux cibles de
     capture (S04).
   - Ce que fait un secteur est **injecté** (`register`) : la sémantique de
     Sélection arrive en S03 (`control_center_input_arbitration.js`), les
     captures en S04 (`control_center_capture_wheel.js`). Un secteur non
     branché le dit (journal + notification), il ne fait pas semblant. Un
     secteur `menu:true` (Sélection) ouvre son sous-arc dès l'activation
     principale — `menu` peut aussi être une fonction relue à chaque clic
     (Vidéo avec deux enregistrements ouverts : la liste d'arrêt) ; une
     entrée du sous-arc qui porte
     `onSecondary` ouvre à son tour un **second niveau** à la place du premier
     (Sélection › Bare Hands : outils, Veille, Aide, Diagnostic, Calibration),
     `Échap` / flèche gauche y ramène.
   - Le déploiement ne dépend d'aucun aller-retour réseau et n'ajoute aucune
     boucle de sondage : ce module n'appelle ni `fetch` ni minuterie
     périodique ; sa seule minuterie est le délai de grâce d'une sortie du
     pointeur.

   Plus de drapeau depuis la Slice 04 : les quatre secteurs sont branchés, la
   roue se construit à l'installation et rend son hôte visible. L'hôte est
   déclaré `hidden` dans la page : si ce module ne s'installe pas, il le
   reste, et la colonne Bare Hands (masquée tant que la roue est visible)
   revient d'elle-même. Retour arrière : cacher ou retirer `#toolWheel`.

   Deux blocs : le **modèle pur** (géométrie, réducteur d'événements → effets),
   exécuté par node dans `tests/unit/test_tool_wheel_js.py`, et le **bloc
   navigateur** (DOM, focus, appels injectés), éprouvé dans Chrome par
   `tests/unit/test_tool_wheel_browser.py`. */
(function(root){
  'use strict';

  /* ------------------------------------------------- les emplacements */

  const SLOTS=Object.freeze([
    Object.freeze({id:'selection',label:'Sélection'}),
    Object.freeze({id:'video',label:'Vidéo'}),
    Object.freeze({id:'screenshot',label:'Capture d’écran'}),
    Object.freeze({id:'audio',label:'Audio'}),
  ]);
  const SLOT_IDS=Object.freeze(SLOTS.map(slot=>slot.id));

  /* ------------------------------------------------- la géométrie

     Centre de la roue sur le bord gauche, à mi-hauteur de son hôte. Les
     angles se comptent depuis l'axe horizontal vers la droite, positifs vers
     le bas (repère de l'écran). Les secteurs se partagent `spanDeg` à parts
     égales ; chaque secteur entier, de `hubRadius` à `radius`, est la cible du
     pointeur (aucun trou entre deux secteurs où la main « tomberait »). */
  const GEOMETRY=Object.freeze({
    radius:200,        // = --shell-wheel-r
    hubRadius:44,      // le moyeu : rien ne s'y active
    iconRadius:122,    // rayon des pastilles d'icône
    dot:52,            // diamètre d'une pastille (≥ --shell-wedge-min)
    wedgeMin:48,       // = --shell-wedge-min
    spanDeg:156,       // ouverture totale, centrée sur l'horizontale
    subRadius:236,     // rayon du sous-arc
    subStepDeg:15,     // pas angulaire entre deux entrées du sous-arc
    subLimitDeg:78,    // le sous-arc ne dépasse pas ±78° (reste à l'écran)
  });

  /* Séparation minimale entre deux centres de pastilles : la cible minimale
     plus 8 px d'air, mesurés sur l'arc des icônes. */
  function minSeparationDeg(g=GEOMETRY){
    return (g.wedgeMin+8)/g.iconRadius*180/Math.PI;
  }

  const rad=deg=>deg*Math.PI/180;
  const round=n=>Math.round(n*100)/100;

  function layoutWedges(count=SLOTS.length,g=GEOMETRY){
    const step=g.spanDeg/count;
    const out=[];
    for(let i=0;i<count;i+=1){
      const startDeg=-g.spanDeg/2+step*i;
      const midDeg=startDeg+step/2;
      out.push({index:i,startDeg:round(startDeg),endDeg:round(startDeg+step),midDeg:round(midDeg),
        x:round(g.iconRadius*Math.cos(rad(midDeg))),y:round(g.iconRadius*Math.sin(rad(midDeg)))});
    }
    return out;
  }

  /* Polygone `clip-path` d'un secteur, en px, dans la boîte du panneau
     (largeur `radius`, hauteur `2·radius`, centre en (0, radius)). */
  function sectorPolygon(startDeg,endDeg,g=GEOMETRY,steps=10){
    const pts=[];
    const at=(r,deg)=>`${round(r*Math.cos(rad(deg)))}px ${round(g.radius+r*Math.sin(rad(deg)))}px`;
    for(let i=0;i<=steps;i+=1)pts.push(at(g.radius,startDeg+(endDeg-startDeg)*i/steps));
    for(let i=steps;i>=0;i-=1)pts.push(at(g.hubRadius,startDeg+(endDeg-startDeg)*i/steps));
    return `polygon(${pts.join(',')})`;
  }

  /* Entrées d'un sous-arc, centrées sur l'angle du secteur parent, tenues
     dans ±subLimitDeg (une liste longue glisse vers le centre).
     `align:'start'` (second niveau, Slice 03) : la liste **part** de l'angle
     donné (l'entrée parente) et descend, au lieu de s'y centrer — elle ne
     remonte donc pas dans le coin du haut, où vivent d'autres contrôles. */
  function layoutSubArc(count,midDeg,g=GEOMETRY,align){
    const span=g.subStepDeg*(count-1);
    let first=align==='start'?midDeg:midDeg-span/2;
    first=Math.max(-g.subLimitDeg,Math.min(first,g.subLimitDeg-span));
    const out=[];
    for(let i=0;i<count;i+=1){
      const deg=first+g.subStepDeg*i;
      out.push({index:i,deg:round(deg),x:round(g.subRadius*Math.cos(rad(deg))),y:round(g.subRadius*Math.sin(rad(deg)))});
    }
    return out;
  }

  /* ------------------------------------------------- le réducteur

     Toute la conduite de la roue est ici, sans DOM : un état, une entrée,
     un nouvel état et une liste d'effets que le bloc navigateur exécute.

     Entrées : `{type, target:'anchor'|'wedge'|'item'|'outside', index,
     inside, key, shiftKey, detail, source, t}`.
     Effets : `activate`, `secondary`, `item`, `itemSecondary`, `subBack`,
     `focus`, `restoreFocus`, `armLeave`, `cancelLeave`, `preventDefault`,
     `journal`.

     `input.menu` (clic sur un secteur) : le secteur ouvre son sous-arc au lieu
     d'agir. `subOpen` porte `level` (1 ou 2), `parent` (l'entrée du niveau 1
     qui a ouvert le niveau 2) et `focus` (l'entrée à mettre en avant). */
  const LEAVE_GRACE_MS=400;
  const SECONDARY_DEDUPE_MS=500;

  function initialState(count=SLOTS.length){
    return {open:false,openedBy:null,focus:-1,count,sub:null,lastSecondary:null};
  }

  function reduce(state,input){
    const s={...state};
    const fx=[];
    const n=s.count;
    const openWith=(by,reason)=>{
      s.open=true;s.openedBy=by;s.sub=null;
      fx.push({do:'cancelLeave'},{do:'journal',key:'tool_wheel.open',data:{reason}});
    };
    const close=(reason,restore)=>{
      if(!s.open)return;
      /* La déduplication des activations secondaires ne vaut que pour une
         ouverture : rouvrir et redemander dans la demi-seconde est un geste
         neuf (Slice 03, Sélection rouverte juste après un choix). */
      s.open=false;s.openedBy=null;s.sub=null;s.focus=-1;s.lastSecondary=null;
      fx.push({do:'cancelLeave'});
      if(restore)fx.push({do:'restoreFocus'});
      fx.push({do:'journal',key:'tool_wheel.close',data:{reason}});
    };
    const focusWedge=(i,move)=>{
      s.focus=((i%n)+n)%n;
      if(move)fx.push({do:'focus',target:'wedge',index:s.focus});
    };
    const secondary=(i,by,t)=>{
      fx.push({do:'preventDefault'});
      const last=s.lastSecondary;
      if(last&&last.index===i&&Number.isFinite(t)&&t-last.t<SECONDARY_DEDUPE_MS)return;
      s.lastSecondary={index:i,t};
      s.focus=i;
      fx.push({do:'secondary',index:i,source:by});
    };
    /* Activation secondaire d'une entrée du premier niveau : même
       déduplication que pour un secteur (Maj+F10 puis le `contextmenu` que le
       navigateur en tire comptent une fois). */
    const itemSecondary=(j,by,t)=>{
      if(!s.sub||s.sub.level!==1)return;
      const key=`item:${s.sub.slot}:${j}`;
      const last=s.lastSecondary;
      if(last&&last.index===key&&Number.isFinite(t)&&t-last.t<SECONDARY_DEDUPE_MS)return;
      s.lastSecondary={index:key,t};
      fx.push({do:'itemSecondary',slot:s.sub.slot,index:j,source:by});
    };
    switch(input.type){
      case 'pointerover':
        if(input.target==='anchor'){
          if(!s.open)openWith('pointer',input.source||'mouse');
          else fx.push({do:'cancelLeave'});
        }else if(s.open&&input.target==='wedge'){
          fx.push({do:'cancelLeave'});
          /* Un autre secteur pointé : le sous-arc ouvert ne lui appartient
             pas, il se ferme (sinon il resterait affiché sans libellé). */
          if(s.sub&&s.sub.slot!==input.index)s.sub=null;
          focusWedge(input.index,false);
          fx.push({do:'focus',target:'wedge',index:s.focus,onlyIfInside:true});
        }else if(s.open&&input.target==='item'&&s.sub){
          fx.push({do:'cancelLeave'});
          s.sub={...s.sub,focus:input.index};
          fx.push({do:'focus',target:'item',index:input.index,onlyIfInside:true});
        }
        break;
      case 'pointerout':
        if(s.open&&!input.inside&&s.openedBy==='pointer')fx.push({do:'armLeave',ms:LEAVE_GRACE_MS});
        break;
      case 'leave':
        close('leave',true);
        break;
      case 'click':
        if(input.target==='anchor'){
          /* La source vient du bloc navigateur (`clickSource`) : un pincement
             Bare Hands est un `click` de `detail` 0, comme le clavier, mais
             il ne déplace pas le focus. Sans source (tests), `detail`. */
          const by=input.source?(input.source==='keyboard'?'keyboard':'pointer')
            :(input.detail===0?'keyboard':'pointer');
          if(!s.open)openWith(by,by==='keyboard'?'keyboard':(input.source||'mouse'));
          else if(by==='keyboard')s.openedBy='keyboard';
          if(by==='keyboard')focusWedge(s.focus<0?0:s.focus,true);
        }else if(s.open&&input.target==='wedge'&&input.menu){
          secondary(input.index,input.source||'mouse',input.t);
        }else if(s.open&&input.target==='wedge'){
          s.focus=input.index;
          fx.push({do:'activate',index:input.index,source:input.source});
          close('activate',true);
        }else if(s.open&&input.target==='item'&&s.sub){
          fx.push({do:'item',slot:s.sub.slot,index:input.index,source:input.source});
          close('activate',true);
        }
        break;
      case 'contextmenu':
        if(s.open&&input.target==='wedge')secondary(input.index,input.source||'mouse',input.t);
        else if(s.open&&input.target==='item'){
          fx.push({do:'preventDefault'});
          itemSecondary(input.index,input.source||'mouse',input.t);
        }
        break;
      case 'keydown':{
        const key=input.key;
        if(input.target==='anchor'){
          if(key==='ArrowRight'){
            fx.push({do:'preventDefault'});
            if(!s.open)openWith('keyboard','keyboard');
            s.openedBy='keyboard';
            focusWedge(s.focus<0?0:s.focus,true);
          }else if(key==='Escape'&&s.open){fx.push({do:'preventDefault'});close('escape',true)}
          break;
        }
        if(!s.open)break;
        if(input.target==='wedge'){
          const i=input.index;
          if(key==='ContextMenu'||(key==='F10'&&input.shiftKey)){secondary(i,'keyboard',input.t);break}
          const moves={ArrowDown:i+1,ArrowRight:i+1,ArrowUp:i-1,ArrowLeft:i-1,Home:0,End:n-1};
          if(key in moves){
            fx.push({do:'preventDefault'});
            s.openedBy='keyboard';s.sub=null;
            focusWedge(moves[key],true);
          }else if(key==='Escape'){fx.push({do:'preventDefault'});close('escape',true)}
        }else if(input.target==='item'&&s.sub){
          const j=input.index,m=s.sub.count;
          const moves={ArrowDown:j+1,ArrowUp:j-1,Home:0,End:m-1};
          if(key in moves){
            fx.push({do:'preventDefault'});
            const k=((moves[key]%m)+m)%m;
            s.sub={...s.sub,focus:k};
            fx.push({do:'focus',target:'item',index:k});
          }else if((key==='Escape'||key==='ArrowLeft')&&s.sub.level>1){
            /* Second niveau : retour au premier, sur l'entrée qui l'a ouvert. */
            s.lastSecondary=null;
            fx.push({do:'preventDefault'},{do:'subBack',slot:s.sub.slot,parent:s.sub.parent});
          }else if(key==='Escape'||key==='ArrowLeft'){
            fx.push({do:'preventDefault'});
            const parent=s.sub.slot;s.sub=null;
            focusWedge(parent,true);
          }else if(key==='ContextMenu'||(key==='F10'&&input.shiftKey)){
            fx.push({do:'preventDefault'});
            itemSecondary(j,'keyboard',input.t);
          }
        }
        break;
      }
      case 'subOpen':
        if(!s.open)break;
        {
          const level=input.level===2?2:1;
          const wanted=Number.isInteger(input.focus)&&input.focus>=0&&input.focus<input.count?input.focus
            :(input.source==='keyboard'&&input.count?0:-1);
          s.sub={slot:input.slot,count:input.count,focus:wanted,level,parent:level===2?input.parent:-1};
          if(wanted>=0&&input.source==='keyboard')fx.push({do:'focus',target:'item',index:wanted});
        }
        break;
      case 'focusOutside':
        close('blur',false);
        break;
      case 'pointerdownOutside':
        close('outside',false);
        break;
      case 'open':
        if(!s.open)openWith(input.by||'pointer','api');
        break;
      case 'close':
        close(input.reason||'api',true);
        break;
      default:
        break;
    }
    return {state:s,effects:fx};
  }

  /* Ce qu'affiche un état : fermé, l'ancre seule. */
  function viewOf(state){
    return {
      anchor:{visible:true,expanded:state.open},
      panel:{visible:state.open},
      wedges:SLOTS.slice(0,state.count).map((slot,i)=>({id:slot.id,focused:state.open&&state.focus===i,
        tabindex:i===(state.focus<0?0:state.focus)?0:-1})),
      label:state.open&&state.focus>=0&&!state.sub?SLOTS[state.focus].label:null,
      sub:state.open&&state.sub?{slot:state.sub.slot,count:state.sub.count,focus:state.sub.focus,
        level:state.sub.level||1}:null,
    };
  }

  /* ------------------------------------------------- les icônes

     Vocabulaire de la palette Bare Hands : grille de 24, trait de 1.5, bouts
     ronds. Écran, appareil photo et micro sont les dessins de l'ancien rail
     de capture (Slice 10), qui vivent ici seuls depuis la Slice 04 : les vues
     de capture (`control_center_capture_wheel.js`) les lisent sur
     `JarvisToolWheel.ART`. `stop` : le carré plein des listes d'arrêt. */
  const ART=Object.freeze({
    selection:Object.freeze({paths:Object.freeze(['M6.2 3.8l11.2 8.4-5.1 1 2.9 5.4-2.2 1.2-2.9-5.5-3.9 3.3z']),dots:Object.freeze([])}),
    video:Object.freeze({paths:Object.freeze([
      'M5 4.8h14a1.5 1.5 0 0 1 1.5 1.5v8.4a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V6.3A1.5 1.5 0 0 1 5 4.8z',
      'M12 16.2v3.4','M8.8 19.6h6.4']),dots:Object.freeze([[12,10.5,2.2]])}),
    screenshot:Object.freeze({paths:Object.freeze([
      'M4.2 8.6a1.6 1.6 0 0 1 1.6-1.6h2.4l1.5-2.2h4.6l1.5 2.2h2.4a1.6 1.6 0 0 1 1.6 1.6v8.8'
        +'a1.6 1.6 0 0 1-1.6 1.6H5.8a1.6 1.6 0 0 1-1.6-1.6z',
      'M12 9.4a3.4 3.4 0 1 1 0 6.8a3.4 3.4 0 1 1 0-6.8z']),dots:Object.freeze([[17.1,9.7,.85]])}),
    audio:Object.freeze({paths:Object.freeze([
      'M12 3.6a2.6 2.6 0 0 1 2.6 2.6v5a2.6 2.6 0 0 1-5.2 0v-5A2.6 2.6 0 0 1 12 3.6z',
      'M6.6 11.2a5.4 5.4 0 0 0 10.8 0','M12 16.6v3.6','M9.2 20.2h5.6']),dots:Object.freeze([])}),
    /* ---- Slice 03 : les deux méthodes de Sélection et le second niveau ----
       Souris : le corps et la molette, rien d'autre. Bare Hands : **pas** la
       main de l'ancien sélecteur (rejetée par l'utilisateur) ; un cadre de
       suivi (les quatre coins de la caméra) autour du geste qui clique : le
       pouce et l'index qui montent se rejoindre sur un point de contact, le
       pincement. Même grille de 24, même trait de 1.5, bouts ronds. */
    mouse:Object.freeze({paths:Object.freeze([
      'M12 3.6c-2.9 0-5.1 2.3-5.1 5.2v6.4c0 2.9 2.2 5.2 5.1 5.2s5.1-2.3 5.1-5.2V8.8c0-2.9-2.2-5.2-5.1-5.2z',
      'M12 6.6v2.8']),dots:Object.freeze([])}),
    bare_hands:Object.freeze({paths:Object.freeze([
      'M4 8.4V6.2A2.2 2.2 0 0 1 6.2 4h2.2','M15.6 4h2.2A2.2 2.2 0 0 1 20 6.2v2.2',
      'M20 15.6v2.2a2.2 2.2 0 0 1-2.2 2.2h-2.2','M8.4 20H6.2A2.2 2.2 0 0 1 4 17.8v-2.2',
      'M7.2 16.6c-.4-4.4 2.2-8 6-8.6','M10.6 16.8c.6-2.2 1.8-3.8 3.2-4.6']),dots:Object.freeze([[14.4,8.6,1.2]])}),
    pointer:Object.freeze({paths:Object.freeze(['M6.2 3.8l11.2 8.4-5.1 1 2.9 5.4-2.2 1.2-2.9-5.5-3.9 3.3z']),dots:Object.freeze([])}),
    pan:Object.freeze({paths:Object.freeze(['M12 4v16','M4 12h16','M9.6 6.4L12 4l2.4 2.4','M9.6 17.6L12 20l2.4-2.4',
      'M6.4 9.6L4 12l2.4 2.4','M17.6 9.6L20 12l-2.4 2.4']),dots:Object.freeze([])}),
    select:Object.freeze({paths:Object.freeze(['M9 4.5h6','M9 19.5h6','M12 4.5v15']),dots:Object.freeze([])}),
    sleep:Object.freeze({paths:Object.freeze(['M19.2 14.4A7.4 7.4 0 1 1 9.6 4.8a5.9 5.9 0 0 0 9.6 9.6z']),dots:Object.freeze([])}),
    help:Object.freeze({paths:Object.freeze(['M12 3.8a8.2 8.2 0 1 1 0 16.4a8.2 8.2 0 1 1 0-16.4z',
      'M9.6 9.7a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1.8-1.1 1.5v.5']),dots:Object.freeze([[12,16.7,.9]])}),
    diagnostics:Object.freeze({paths:Object.freeze(['M3.5 12.5h4l2.1-5.5 4 10 2.2-4.5h4.7']),dots:Object.freeze([])}),
    calibration:Object.freeze({paths:Object.freeze(['M12 6a6 6 0 1 1 0 12a6 6 0 1 1 0-12z',
      'M12 3v3','M12 18v3','M3 12h3','M18 12h3']),dots:Object.freeze([[12,12,1]])}),
    /* ---- Slice 04 : arrêter un enregistrement, et la coche d'une capture prise ---- */
    stop:Object.freeze({paths:Object.freeze(['M7.5 7.5h9v9h-9z']),dots:Object.freeze([])}),
    done:Object.freeze({paths:Object.freeze(['M5.5 12.5l4.2 4.2 8.8-9.4']),dots:Object.freeze([])}),
  });

  const DOM=Object.freeze({hostId:'toolWheel',styleId:'toolWheelStyle',menuId:'toolWheelMenu',
    labelId:'toolWheelLabel',hintId:'toolWheelHint'});

  const api=Object.freeze({
    SLOTS,SLOT_IDS,GEOMETRY,ART,DOM,LEAVE_GRACE_MS,SECONDARY_DEDUPE_MS,
    minSeparationDeg,layoutWedges,sectorPolygon,layoutSubArc,initialState,reduce,viewOf,
  });
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- la feuille

     Traits fins cyan, verre retenu, demi-disque au bord gauche ; libellé sur
     le seul secteur en avant. Le mouvement dit l'état (le demi-disque glisse
     depuis le bord) et vaut zéro sous `prefers-reduced-motion` : toutes les
     durées passent par `--shell-dur*`, que la page remet à 0 ms. Aucune
     conduite n'attend une fin de transition. Aucun `z-index` ici : les rangs
     de l'hôte (30 au repos, 37 ouvert) vivent dans la page et au registre. */
  const H='#'+DOM.hostId;
  const ACCENT='var(--accent,#6ee7ff)';
  const STYLE=`
${H}{font:13px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--text,#d8edf7)}
${H} .tw-anchor{position:relative;display:block;width:var(--shell-anchor-w);height:112px;margin:0;padding:0;
  border:1px solid var(--shell-stroke);border-left:0;border-radius:0 12px 12px 0;background:var(--shell-glass-bg);
  backdrop-filter:blur(12px);cursor:pointer;pointer-events:auto;
  transition:border-color var(--shell-dur-fast) var(--shell-ease),background var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-anchor::before{content:"";position:absolute;left:4px;top:28px;bottom:28px;width:2px;border-radius:2px;
  background:color-mix(in srgb,${ACCENT} 55%,transparent)}
${H} .tw-anchor[data-tw-tone=error]{border-color:var(--sem-problem,#ff6a4d)}
${H} .tw-anchor[data-tw-tone=error]::before{background:var(--sem-problem,#ff6a4d)}
${H} .tw-anchor[data-tw-tone=wait]{border-color:var(--sem-working,#4da3ff)}
${H} .tw-anchor[data-tw-tone=wait]::before{background:var(--sem-working,#4da3ff)}
${H} .tw-anchor[data-tw-tone]::after{position:absolute;left:0;right:0;top:8px;text-align:center;
  font:700 10px/1 ui-monospace,Consolas,monospace;content:"!" / "";color:var(--sem-problem,#ff6a4d)}
${H} .tw-anchor[data-tw-tone=wait]::after{content:"…" / "";color:var(--sem-working,#4da3ff)}
${H} .tw-anchor:hover,${H} .tw-anchor[aria-expanded=true]{border-color:var(--shell-stroke-active);
  background:var(--shell-glass-strong)}
${H} .tw-panel{position:absolute;left:0;top:50%;width:calc(var(--shell-wheel-r) + 1px);height:calc(var(--shell-wheel-r) * 2);
  margin-top:calc(var(--shell-wheel-r) * -1);pointer-events:none;visibility:hidden;opacity:0;
  transform:translateX(-28px) scale(.94);transform-origin:0 50%;
  transition:opacity var(--shell-dur) var(--shell-ease),transform var(--shell-dur) var(--shell-ease),visibility 0s linear var(--shell-dur)}
${H}[data-open] .tw-panel{visibility:visible;opacity:1;transform:none;
  transition:opacity var(--shell-dur) var(--shell-ease),transform var(--shell-dur) var(--shell-ease),visibility 0s}
${H} .tw-disc{position:absolute;inset:0;border-radius:0 100% 100% 0 / 0 50% 50% 0;background:var(--shell-glass-bg);
  backdrop-filter:blur(14px);box-shadow:0 10px 40px rgba(0,0,0,.28)}
${H} .tw-ring{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none;fill:none;
  stroke:color-mix(in srgb,${ACCENT} 34%,transparent);stroke-width:1}
${H} .tw-ring .tw-ring-outer{stroke:color-mix(in srgb,${ACCENT} 62%,transparent);stroke-width:1.5}
${H} .tw-ring .tw-tick{stroke:color-mix(in srgb,${ACCENT} 40%,transparent)}
${H} .tw-wedge{position:absolute;inset:0;margin:0;padding:0;border:0;background:transparent;color:inherit;
  cursor:pointer;pointer-events:auto;-webkit-tap-highlight-color:transparent}
${H} .tw-dot{position:absolute;width:52px;height:52px;margin:-26px 0 0 -26px;display:grid;place-items:center;
  border-radius:50%;border:1px solid var(--shell-stroke);background:var(--shell-glass-strong);
  color:var(--muted,#7190a0);
  transition:color var(--shell-dur-fast) var(--shell-ease),border-color var(--shell-dur-fast) var(--shell-ease),
    box-shadow var(--shell-dur-fast) var(--shell-ease),transform var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-wedge.is-focus .tw-dot{color:${ACCENT};border-color:${ACCENT};transform:scale(1.08);
  box-shadow:0 0 0 4px color-mix(in srgb,${ACCENT} 14%,transparent),0 0 22px color-mix(in srgb,${ACCENT} 30%,transparent)}
${H} .tw-wedge:focus-visible .tw-dot{outline:var(--shell-focus-w) solid var(--shell-focus);outline-offset:4px}
${H} .tw-wedge[aria-disabled=true] .tw-dot{opacity:.55}
${H} .tw-label{position:absolute;transform:translateY(-50%);white-space:nowrap;padding:7px 12px;border-radius:999px;
  border:1px solid var(--shell-stroke-active);background:var(--shell-glass-strong);backdrop-filter:blur(12px);
  color:var(--text,#d8edf7);letter-spacing:.04em;pointer-events:none}
${H} .tw-label[hidden],${H} .tw-sub[hidden]{display:none}
${H} .tw-sub{position:absolute;inset:0;pointer-events:none}
${H} .tw-item{position:absolute;transform:translateY(-50%);max-width:260px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;margin:0;padding:7px 12px;border-radius:999px;border:1px solid var(--shell-stroke);
  background:var(--shell-glass-strong);backdrop-filter:blur(12px);color:var(--text,#d8edf7);font:inherit;
  cursor:pointer;pointer-events:auto;
  transition:border-color var(--shell-dur-fast) var(--shell-ease),color var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-item.is-focus{border-color:${ACCENT};color:${ACCENT}}
${H} .tw-item[aria-checked=true]::before{content:"● " / "";color:${ACCENT}}
${H} .tw-item{display:inline-flex;align-items:center;gap:8px}
${H} .tw-item svg{flex:none;width:18px;height:18px}
${H} .tw-item .tw-text{overflow:hidden;text-overflow:ellipsis}
${H} .tw-item .tw-note{color:var(--muted,#7190a0);font-size:11px;overflow:hidden;text-overflow:ellipsis}
${H} .tw-item[data-tw-tone=error]{border-color:color-mix(in srgb,var(--sem-problem,#ff6a4d) 70%,transparent)}
${H} .tw-item[data-tw-tone=error] .tw-note{color:var(--sem-problem,#ff6a4d)}
${H} .tw-item[data-tw-tone=wait] .tw-note{color:var(--sem-working,#4da3ff)}
${H} .tw-dot .tw-badge{position:absolute;right:-3px;top:-3px;width:16px;height:16px;border-radius:50%;
  display:grid;place-items:center;font:700 11px/1 ui-monospace,Consolas,monospace;color:#0b0f14;pointer-events:none}
${H} .tw-dot .tw-badge[data-tw-tone=error]{background:var(--sem-problem,#ff6a4d)}
/* Slice 04 : « ? » d'un état inconnu (statut des captures perdu) — gris et
   pointillé, jamais la couleur seule ; il ne colore pas l'ancre. */
${H} .tw-dot .tw-badge[data-tw-tone=unknown]{background:var(--muted,#7190a0);outline:1px dashed var(--text,#d8edf7);outline-offset:1px}
/* Un canal ouvert (Vidéo, Audio) : anneau ambre et point plein au coin —
   l'état coché du secteur (aria-checked), lisible sans la couleur. */
${H} .tw-wedge[aria-checked=true] .tw-dot{border-color:var(--sem-alert,#ff9f43);color:var(--sem-alert,#ff9f43)}
${H} .tw-wedge[aria-checked=true] .tw-dot::after{content:"";position:absolute;left:-2px;top:-2px;width:12px;height:12px;
  border-radius:50%;background:var(--sem-alert,#ff9f43);box-shadow:0 0 0 2px var(--shell-glass-strong)}
${H} .tw-dot .tw-badge[data-tw-tone=wait]{background:transparent;border:2px solid var(--sem-working,#4da3ff);
  border-right-color:transparent;animation:tw-spin 1s linear infinite}
@keyframes tw-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){${H} .tw-dot .tw-badge[data-tw-tone=wait]{animation:none}}
${H} .tw-item[aria-disabled=true]{color:var(--muted,#7190a0);cursor:default}
${H} .tw-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(forced-colors:active){
  ${H} .tw-anchor,${H} .tw-dot,${H} .tw-item,${H} .tw-label{border-color:CanvasText}
  ${H} .tw-wedge.is-focus .tw-dot,${H} .tw-item.is-focus{border-color:Highlight;color:Highlight}
  ${H} .tw-wedge[aria-checked=true] .tw-dot{border:2px solid Highlight}
  ${H} .tw-wedge[aria-checked=true] .tw-dot::after,${H} .tw-dot .tw-badge{forced-color-adjust:none;background:Highlight;color:HighlightText}
  ${H} .tw-ring,${H} .tw-ring .tw-ring-outer,${H} .tw-ring .tw-tick{stroke:CanvasText}
}`;

  /* ------------------------------------------------- le bloc navigateur */

  const SVG_NS='http://www.w3.org/2000/svg';
  const log=(level,key,data)=>{
    const line=`[tool_wheel] ${key} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);
    else if(level==='warn')console.warn(line);
    else console.info(line);
  };
  /* La notification de la page (`toast`, déclaration de fonction remontée du
     même `<script>`) ; absente (tests node, page réduite), le journal suffit. */
  const notify=(title,sub)=>{
    try{if(typeof toast==='function')toast({title,sub,kind:'bad'})}
    catch(error){log('warn','tool_wheel.notify_failed',{error:String(error&&error.message||error)})}
  };
  const errorText=error=>String((error&&error.message)||error||'erreur inconnue');

  function svgEl(name,attrs){
    const el=document.createElementNS(SVG_NS,name);
    for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));
    return el;
  }
  /* `name` : une clé d'`ART`, ou un dessin `{paths, dots}` fourni par une
     action injectée. */
  function icon(name){
    const art=typeof name==='string'?ART[name]:name;
    if(!art||!Array.isArray(art.paths))return null;
    const svg=svgEl('svg',{viewBox:'0 0 24 24',width:22,height:22,fill:'none',stroke:'currentColor',
      'stroke-width':1.5,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'});
    for(const d of art.paths)svg.appendChild(svgEl('path',{d}));
    for(const [cx,cy,r] of art.dots||[])svg.appendChild(svgEl('circle',{cx,cy,r,fill:'currentColor',stroke:'none'}));
    return svg;
  }
  /* L'anneau : arc extérieur, arc du moyeu, une graduation par frontière de
     secteur. Décoratif (`aria-hidden`, aucun pointeur). */
  function ring(wedges){
    const g=GEOMETRY,cy=g.radius;
    const svg=svgEl('svg',{class:'tw-ring',viewBox:`0 0 ${g.radius+1} ${g.radius*2}`,'aria-hidden':'true',focusable:'false'});
    const arc=(r,a,b)=>{
      const p=deg=>`${round(r*Math.cos(rad(deg)))} ${round(cy+r*Math.sin(rad(deg)))}`;
      return `M ${p(a)} A ${r} ${r} 0 0 1 ${p(b)}`;
    };
    svg.appendChild(svgEl('path',{class:'tw-ring-outer',d:arc(g.radius-1,-88,88)}));
    svg.appendChild(svgEl('path',{d:arc(g.hubRadius,-88,88)}));
    svg.appendChild(svgEl('path',{d:arc(g.iconRadius+34,-g.spanDeg/2,g.spanDeg/2),'stroke-dasharray':'2 7'}));
    for(const w of [...wedges.map(w=>w.startDeg),wedges[wedges.length-1].endDeg]){
      const c=Math.cos(rad(w)),s=Math.sin(rad(w));
      svg.appendChild(svgEl('path',{class:'tw-tick',d:`M ${round((g.radius-12)*c)} ${round(cy+(g.radius-12)*s)} L ${round((g.radius-1)*c)} ${round(cy+(g.radius-1)*s)}`}));
    }
    return svg;
  }

  function installToolWheel(){
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error(`JarvisToolWheel : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'tool_wheel_host_missing'});
    const actions=new Map();
    /* L'état qu'une action injectée **projette** sur son secteur (Slice 03 :
       la méthode de Sélection, sa panne, son attente) : icône, ton, phrase.
       Ce n'est pas un état de la roue — l'action le relit chez son
       propriétaire et le repose ici à chaque changement. */
    const statuses=new Map();
    const wedgesGeo=layoutWedges();
    let state=initialState(),built=null,leaveTimer=null,focusInside=false;
    /* Le dernier `pointerdown` vu sur la roue : un `click` Bare Hands est un
       `MouseEvent` sans `pointerId` ; la source se lit sur l'appui qui l'a
       précédé. */
    let lastDown={pointerId:null,t:0};
    /* Le dernier `pointerover` vu sur la roue (Slice 02, reprise QA P2) : un
       `contextmenu` Bare Hands (pincement pouce + majeur) n'a pas de
       `pointerId` et ne suit pas forcément un pincement récent ; le pointeur
       qui survolait la cible dit qui l'a envoyé. */
    let lastOverId=null;

    const isBareHands=id=>{
      const BH=root.JarvisBarehandsContracts;
      return !!(BH&&typeof BH.isBareHandsPointerId==='function'&&BH.isBareHandsPointerId(id));
    };
    const pointerSource=event=>isBareHands(event&&event.pointerId)?'barehands':'mouse';
    const contextSource=event=>{
      if(isBareHands(event.pointerId)||isBareHands(lastOverId)
        ||isBareHands(lastDown.pointerId)&&Date.now()-lastDown.t<800)return 'barehands';
      return event.button===2||event.detail?'mouse':'keyboard';
    };
    const clickSource=event=>{
      if(event.detail===0&&Date.now()-lastDown.t>800)return 'keyboard';
      return isBareHands(lastDown.pointerId)&&Date.now()-lastDown.t<800?'barehands':'mouse';
    };

    function build(){
      host.textContent='';
      const panel=document.createElement('div');
      panel.className='tw-panel';
      const disc=document.createElement('div');disc.className='tw-disc';
      panel.appendChild(disc);
      panel.appendChild(ring(wedgesGeo));
      const menu=document.createElement('div');
      menu.id=DOM.menuId;menu.setAttribute('role','menu');menu.setAttribute('aria-label','Outils');
      menu.setAttribute('aria-orientation','vertical');
      const wedges=wedgesGeo.map((geo,i)=>{
        const slot=SLOTS[i];
        const b=document.createElement('button');
        b.type='button';b.className='tw-wedge';b.setAttribute('role','menuitem');
        b.setAttribute('data-tw-slot',slot.id);b.setAttribute('aria-label',slot.label);
        b.setAttribute('aria-describedby',DOM.hintId);
        b.style.clipPath=sectorPolygon(geo.startDeg,geo.endDeg);
        const dot=document.createElement('span');dot.className='tw-dot';
        dot.style.left=`${geo.x}px`;dot.style.top=`${GEOMETRY.radius+geo.y}px`;
        dot.appendChild(icon(slot.id));
        const badge=document.createElement('span');badge.className='tw-badge';badge.hidden=true;
        badge.setAttribute('aria-hidden','true');
        dot.appendChild(badge);
        b.appendChild(dot);
        menu.appendChild(b);
        return b;
      });
      panel.appendChild(menu);
      const label=document.createElement('div');
      label.id=DOM.labelId;label.className='tw-label';label.hidden=true;label.setAttribute('aria-hidden','true');
      panel.appendChild(label);
      const sub=document.createElement('div');
      sub.className='tw-sub';sub.hidden=true;sub.setAttribute('role','menu');
      panel.appendChild(sub);
      const hint=document.createElement('span');
      hint.id=DOM.hintId;hint.className='tw-sr';
      hint.textContent='Clic droit, Maj+F10 ou pincement pouce-majeur : plus de choix. Échap : fermer.';
      panel.appendChild(hint);
      const anchor=document.createElement('button');
      anchor.type='button';anchor.className='tw-anchor';
      anchor.setAttribute('aria-label','Outils');anchor.title='Outils';
      anchor.setAttribute('aria-haspopup','menu');anchor.setAttribute('aria-controls',DOM.menuId);
      anchor.setAttribute('aria-expanded','false');
      /* L'ancre avant le panneau : ordre de tabulation ancre → secteur →
         suite de la page (Tab sort de la roue et la ferme). */
      host.appendChild(anchor);host.appendChild(panel);
      return {panel,menu,wedges,label,sub,anchor,items:[],itemSpecs:[],parentSpecs:null,
        shownIcons:SLOTS.map(slot=>slot.id)};
    }

    function targetOf(el){
      if(!built||!el||typeof el.closest!=='function')return {target:'outside'};
      if(el.closest('.tw-anchor'))return {target:'anchor'};
      const wedge=el.closest('.tw-wedge');
      if(wedge)return {target:'wedge',index:built.wedges.indexOf(wedge)};
      const item=el.closest('.tw-item');
      if(item)return {target:'item',index:built.items.indexOf(item)};
      return host.contains(el)?{target:'inside'}:{target:'outside'};
    }

    function render(){
      if(!built)return;
      const view=viewOf(state);
      if(view.panel.visible)host.setAttribute('data-open','');else host.removeAttribute('data-open');
      built.anchor.setAttribute('aria-expanded',String(view.anchor.expanded));
      /* Au repos seule l'ancre se voit : une panne ou une attente projetée
         sur un secteur s'y lit aussi (marque + phrase dans le nom), sinon un
         démarrage lancé depuis la roue disparaîtrait avec elle. */
      const toned=[...statuses.values()].find(st=>st.tone==='error')||[...statuses.values()].find(st=>st.tone==='wait');
      if(toned){
        built.anchor.setAttribute('data-tw-tone',toned.tone);
        built.anchor.setAttribute('aria-label',`Outils — ${toned.text}`);built.anchor.title=`Outils — ${toned.text}`;
      }else{
        built.anchor.removeAttribute('data-tw-tone');
        built.anchor.setAttribute('aria-label','Outils');built.anchor.title='Outils';
      }
      built.wedges.forEach((b,i)=>{
        const w=view.wedges[i];
        b.classList.toggle('is-focus',w.focused);
        b.tabIndex=w.tabindex;
        b.setAttribute('aria-disabled',String(!actions.has(SLOTS[i].id)));
        paintStatus(i);
      });
      if(view.label){
        const geo=wedgesGeo[state.focus];
        const status=statuses.get(SLOTS[state.focus].id);
        built.label.textContent=status&&status.text?`${view.label} · ${status.text}`:view.label;
        built.label.style.left=`${geo.x+38}px`;built.label.style.top=`${GEOMETRY.radius+geo.y}px`;
        built.label.hidden=false;
      }else built.label.hidden=true;
      if(!view.sub){
        if(built.items.length){built.sub.textContent='';built.items=[];built.itemSpecs=[]}
        built.sub.hidden=true;
      }else{
        built.sub.hidden=false;
        built.items.forEach((b,j)=>{b.classList.toggle('is-focus',view.sub.focus===j);b.tabIndex=j===Math.max(0,view.sub.focus)?0:-1});
      }
    }

    /* Ce qu'une action projette sur son secteur : l'icône (la méthode de
       Sélection courante), une marque (panne, attente) et la phrase, ajoutée
       au nom accessible — l'état ne passe jamais par la couleur seule. */
    function paintStatus(i){
      const slot=SLOTS[i],b=built.wedges[i],status=statuses.get(slot.id)||null;
      /* `checked` (Slice 04) : un canal de capture ouvert. Le secteur devient
         une case à cocher de menu, son état se lit sans la couleur. */
      if(status&&typeof status.checked==='boolean'){
        b.setAttribute('role','menuitemcheckbox');b.setAttribute('aria-checked',String(status.checked));
      }else{b.setAttribute('role','menuitem');b.removeAttribute('aria-checked')}
      const dot=b.querySelector('.tw-dot'),badge=dot.querySelector('.tw-badge');
      const want=status&&status.icon?status.icon:slot.id;
      if(built.shownIcons[i]!==want){
        const svg=icon(want)||icon(slot.id);
        const old=dot.querySelector('svg');
        if(old)dot.replaceChild(svg,old);else dot.insertBefore(svg,badge);
        built.shownIcons[i]=want;
      }
      const tone=status&&(status.tone==='error'||status.tone==='wait'||status.tone==='unknown')?status.tone:null;
      badge.hidden=!tone;
      if(tone){badge.setAttribute('data-tw-tone',tone);badge.textContent=tone==='error'?'!':tone==='unknown'?'?':''}
      else{badge.removeAttribute('data-tw-tone');badge.textContent=''}
      b.setAttribute('aria-label',status&&status.text?`${slot.label} — ${status.text}`:slot.label);
    }

    function fillSub(slotIndex,items,fromDeg){
      built.sub.textContent='';
      const geo=Number.isFinite(fromDeg)?layoutSubArc(items.length,fromDeg,GEOMETRY,'start')
        :layoutSubArc(items.length,wedgesGeo[slotIndex].midDeg);
      built.sub.setAttribute('aria-label',SLOTS[slotIndex].label);
      built.itemSpecs=items;
      built.items=items.map((spec,j)=>{
        const b=document.createElement('button');
        b.type='button';b.className='tw-item';
        if(spec.id!=null)b.setAttribute('data-tw-item',String(spec.id));
        b.setAttribute('role',typeof spec.checked==='boolean'?'menuitemradio':'menuitem');
        if(typeof spec.checked==='boolean')b.setAttribute('aria-checked',String(spec.checked));
        if(spec.disabled)b.setAttribute('aria-disabled','true');
        if(spec.tone==='error'||spec.tone==='wait')b.setAttribute('data-tw-tone',spec.tone);
        const text=String(spec.label==null?'':spec.label);
        const note=spec.note==null?'':String(spec.note);
        /* `detail` : la phrase longue (un motif d'indisponibilité), dans le nom
           accessible et l'infobulle ; `note` reste courte à l'écran. */
        const detail=spec.detail==null?note:String(spec.detail);
        const spoken=!detail?text:note&&!detail.startsWith(note)?`${text} — ${note} — ${detail}`:`${text} — ${detail}`;
        const art=spec.icon?icon(spec.icon):null;
        if(art)b.appendChild(art);
        if(art||note){
          const t=document.createElement('span');t.className='tw-text';t.textContent=text;b.appendChild(t);
          /* Une espace entre le texte et la note (sans effet dans la boîte flex) : lu d'un trait, « principal1:08 »
             n'était plus dans le nom (axe, WCAG 2.5.3). */
          if(note){const n=document.createElement('span');n.className='tw-note';n.textContent=note;b.append(' ',n)}
          /* Le nom commence par ce que l'entrée montre, texte puis note (WCAG 2.5.3, orbital-ui QA S09 P6) : une
             phrase longue qui ne reprend pas la note s'ajoute après elle. */
          b.setAttribute('aria-label',spoken);
        }else b.textContent=text;
        b.title=spoken;
        if(typeof spec.onSecondary==='function')b.setAttribute('aria-haspopup','menu');
        b.style.left=`${geo[j].x}px`;b.style.top=`${GEOMETRY.radius+geo[j].y}px`;
        built.sub.appendChild(b);
        return b;
      });
    }

    /* Appel d'un rappel injecté : synchrone ou promesse, son échec se voit
       (notification) et se journalise, avec la cause réelle. */
    function invoke(what,label,fn,ctx){
      try{
        const out=fn(ctx);
        if(out&&typeof out.then==='function')
          out.then(null,error=>{
            log('error','tool_wheel.action_failed',{what,slot:ctx.slot,error:errorText(error)});
            notify(`${label} : action impossible`,errorText(error));
          });
        return out;
      }catch(error){
        log('error','tool_wheel.action_failed',{what,slot:ctx.slot,error:errorText(error)});
        notify(`${label} : action impossible`,errorText(error));
        return undefined;
      }
    }

    function openSecondary(index,source){
      const slot=SLOTS[index];
      const action=actions.get(slot.id);
      if(!action||typeof action.onSecondary!=='function'){
        log('info','tool_wheel.secondary_none',{slot:slot.id,source});
        return;
      }
      log('info','tool_wheel.secondary',{slot:slot.id,source});
      const show=(items,from)=>{
        if(!state.open)return;
        if(!Array.isArray(items)){
          log('info','tool_wheel.secondary_none',{slot:slot.id,source,from});
          return;
        }
        fillSub(index,items);
        built.parentSpecs=null;
        dispatch({type:'subOpen',slot:index,count:items.length,source,level:1});
      };
      const out=invoke('secondary',slot.label,action.onSecondary,{slot:slot.id,source});
      if(out&&typeof out.then==='function'){
        /* Tant que l'action prépare ses choix, le sous-arc le dit. */
        show([{label:'Chargement…',disabled:true}],'pending');
        out.then(items=>{if(state.sub&&state.sub.slot===index)show(items,'resolved')},()=>{
          if(state.sub&&state.sub.slot===index)dispatch({type:'keydown',target:'item',index:0,key:'Escape'});
        });
      }else show(out,'sync');
    }

    /* Second niveau : l'entrée `itemIndex` du premier niveau fournit ses
       propres choix (`onSecondary`), posés **à la place** du premier niveau ;
       celui-ci est gardé pour le retour (`subBack`). */
    function openItemSecondary(slotIndex,itemIndex,source,specs){
      const slot=SLOTS[slotIndex],spec=specs[itemIndex];
      if(!spec||spec.disabled||typeof spec.onSecondary!=='function'){
        log('info','tool_wheel.item_secondary_none',{slot:slot.id,index:itemIndex,source});
        return;
      }
      const parents=specs;
      log('info','tool_wheel.item_secondary',{slot:slot.id,item:spec.id==null?itemIndex:spec.id,source});
      const show=items=>{
        if(!state.open||!state.sub||state.sub.slot!==slotIndex)return;
        if(!Array.isArray(items)){log('info','tool_wheel.item_secondary_none',{slot:slot.id,index:itemIndex,source});return}
        /* Le second niveau part de l'angle de l'entrée parente. */
        const from=layoutSubArc(parents.length,wedgesGeo[slotIndex].midDeg)[itemIndex];
        fillSub(slotIndex,items,from?from.deg:undefined);
        built.parentSpecs=parents;
        dispatch({type:'subOpen',slot:slotIndex,count:items.length,source,level:2,parent:itemIndex});
      };
      const out=invoke('secondary',String(spec.label),spec.onSecondary,{slot:slot.id,item:spec.id,source});
      if(out&&typeof out.then==='function'){
        show([{label:'Chargement…',disabled:true}]);
        out.then(show,()=>{});
      }else show(out);
    }
    function subBack(slotIndex,parent){
      const parents=built&&built.parentSpecs;
      if(!parents||!state.open)return;
      fillSub(slotIndex,parents);
      built.parentSpecs=null;
      dispatch({type:'subOpen',slot:slotIndex,count:parents.length,source:'keyboard',level:1,focus:parent});
    }

    function run(effects,event,specs){
      for(const fx of effects){
        switch(fx.do){
          case 'preventDefault':if(event&&typeof event.preventDefault==='function')event.preventDefault();break;
          case 'cancelLeave':if(leaveTimer!==null){clearTimeout(leaveTimer);leaveTimer=null}break;
          case 'armLeave':
            if(leaveTimer!==null)clearTimeout(leaveTimer);
            leaveTimer=setTimeout(()=>{leaveTimer=null;dispatch({type:'leave'})},fx.ms);
            break;
          case 'focus':{
            const list=fx.target==='item'?built.items:built.wedges;
            const el=list[fx.index];
            if(!el)break;
            if(fx.onlyIfInside&&!host.contains(document.activeElement))break;
            try{el.focus({preventScroll:true})}catch(_){el.focus()}
            break;
          }
          case 'restoreFocus':
            /* Le focus ne reste jamais sur un élément caché : il revient à
               l'ancre, qui l'avait ouvert. */
            if(built&&(focusInside||built.panel.contains(document.activeElement))){
              try{built.anchor.focus({preventScroll:true})}catch(_){built.anchor.focus()}
            }
            break;
          case 'activate':{
            const slot=SLOTS[fx.index];
            const action=actions.get(slot.id);
            if(!action){
              log('warn','tool_wheel.unbound',{slot:slot.id,source:fx.source});
              notify(`${slot.label} : outil pas encore branché`,'Cet outil arrive dans une prochaine version.');
              break;
            }
            log('info','tool_wheel.activate',{slot:slot.id,source:fx.source});
            invoke('activate',slot.label,action.onActivate,{slot:slot.id,source:fx.source});
            break;
          }
          case 'secondary':openSecondary(fx.index,fx.source);break;
          case 'itemSecondary':openItemSecondary(fx.slot,fx.index,fx.source,specs);break;
          case 'subBack':subBack(fx.slot,fx.parent);break;
          case 'item':{
            const spec=specs[fx.index];
            const slot=SLOTS[fx.slot];
            if(!spec||spec.disabled||typeof spec.onActivate!=='function'){
              log('info','tool_wheel.item_inert',{slot:slot.id,index:fx.index});
              break;
            }
            log('info','tool_wheel.item',{slot:slot.id,item:spec.id==null?fx.index:spec.id,source:fx.source});
            /* Le choix ferme la roue ; le second niveau gardé n'a plus d'objet. */
            if(built)built.parentSpecs=null;
            invoke('item',String(spec.label),spec.onActivate,{slot:slot.id,item:spec.id,source:fx.source});
            break;
          }
          case 'journal':log('info',fx.key,fx.data);break;
          default:break;
        }
      }
    }

    function dispatch(input,event){
      const before=state.open;
      /* Lu AVANT de peindre : sous mouvement réduit, le panneau devient
         invisible tout de suite et Chrome retire le focus de ce qu'il cache ;
         lu après, le focus serait déjà perdu sur `body`. */
      focusInside=!!(built&&built.panel.contains(document.activeElement));
      /* Les entrées du sous-arc, lues avant que la fermeture ne les efface. */
      const specs=built?built.itemSpecs:[];
      const out=reduce(state,{t:Date.now(),...input});
      state=out.state;
      render();
      run(out.effects,event,specs);
      if(before!==state.open){
        /* Écouteurs de document seulement tant que la roue est ouverte. */
        if(state.open){
          document.addEventListener('pointerdown',onDocDown,true);
          document.addEventListener('keydown',onDocKey,true);
        }else{
          document.removeEventListener('pointerdown',onDocDown,true);
          document.removeEventListener('keydown',onDocKey,true);
          if(built)built.parentSpecs=null;
        }
      }
    }

    function onDocDown(event){
      if(!host.contains(event.target))dispatch({type:'pointerdownOutside'},event);
    }
    /* Échap ferme aussi une roue ouverte à la souris quand le focus est
       ailleurs dans la page (reprise QA P3) ; dans la roue, `onKey` décide. */
    function onDocKey(event){
      if(event.key==='Escape'&&!host.contains(event.target))dispatch({type:'close',reason:'escape'},event);
    }
    function onOver(event){
      lastOverId=event.pointerId===undefined?null:event.pointerId;
      const t=targetOf(event.target);
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item')
        dispatch({type:'pointerover',...t,source:pointerSource(event)},event);
    }
    function onOut(event){
      /* Souris : `relatedTarget` dit où va le pointeur. Bare Hands n'en donne
         pas (`null`) : une sortie suivie d'aucune entrée ferme après le délai
         de grâce. */
      const to=event.relatedTarget;
      dispatch({type:'pointerout',inside:!!(to&&host.contains(to))},event);
    }
    function onDown(event){lastDown={pointerId:event.pointerId,t:Date.now()}}
    /* `menu` : un booléen, ou une fonction relue à chaque clic (Slice 04). */
    function isMenu(action){
      if(!action)return false;
      if(typeof action.menu!=='function')return !!action.menu;
      try{return !!action.menu()}
      catch(error){log('error','tool_wheel.menu_failed',{slot:action.id,error:errorText(error)});return false}
    }
    function onClick(event){
      const t=targetOf(event.target);
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item')
        dispatch({type:'click',...t,detail:event.detail,source:clickSource(event),
          menu:t.target==='wedge'&&isMenu(actions.get(SLOTS[t.index].id))},event);
    }
    function onContext(event){
      const t=targetOf(event.target);
      if(t.target==='wedge'||t.target==='item'){
        dispatch({type:'contextmenu',...t,source:contextSource(event)},event);
      }
    }
    function onKey(event){
      const t=targetOf(event.target);
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item')
        dispatch({type:'keydown',...t,key:event.key,shiftKey:event.shiftKey},event);
    }
    function onFocusOut(event){
      const to=event.relatedTarget;
      if(state.open&&to&&!host.contains(to))dispatch({type:'focusOutside'},event);
    }
    const LISTENERS=[['pointerover',onOver],['pointerout',onOut],['pointerdown',onDown],['click',onClick],
      ['contextmenu',onContext],['keydown',onKey],['focusout',onFocusOut]];

    /* La roue se construit une fois, à l'installation (Slice 04 : plus de
       drapeau). */
    function mount(){
      if(!document.getElementById(DOM.styleId)){
        const style=document.createElement('style');
        style.id=DOM.styleId;style.textContent=STYLE;document.head.appendChild(style);
      }
      state=initialState();
      built=build();
      for(const [type,fn] of LISTENERS)host.addEventListener(type,fn);
      render();
    }

    /* Branche un emplacement. `action` : `{id, onActivate(ctx), onSecondary?(ctx),
       menu?}` — `onSecondary` rend la liste du sous-arc (`[{id?, label,
       disabled?, checked?, icon?, note?, tone?, onActivate?(ctx),
       onSecondary?(ctx)}]`) ou une promesse de cette liste ; `menu:true` (ou
       une fonction qui le rend) ouvre ce sous-arc dès l'activation
       principale. Rend la fonction qui débranche. */
    function register(action){
      if(!action||!SLOT_IDS.includes(action.id))
        throw Object.assign(new TypeError(`JarvisToolWheel.register : emplacement inconnu « ${action&&action.id} » (attendus : ${SLOT_IDS.join(', ')})`),
          {code:'tool_wheel_unknown_slot'});
      if(typeof action.onActivate!=='function')
        throw Object.assign(new TypeError(`JarvisToolWheel.register : « ${action.id} » sans onActivate`),
          {code:'tool_wheel_no_activate'});
      actions.set(action.id,action);
      render();
      log('info','tool_wheel.registered',{slot:action.id,secondary:typeof action.onSecondary==='function'});
      return ()=>{if(actions.get(action.id)===action){actions.delete(action.id);render()}};
    }

    /* Ce qu'une action projette sur son secteur : `{icon?, tone?:'error'|'wait'|
       'unknown', text?, checked?}` (ou `null` pour l'effacer). `unknown` marque
       le secteur d'un « ? » sans colorer l'ancre ; `checked` (booléen) en
       fait une case cochée (`menuitemcheckbox`). Peint tout de suite, roue
       ouverte ou non ; journalisé seulement quand il change. */
    function setStatus(id,status){
      if(!SLOT_IDS.includes(id))
        throw Object.assign(new TypeError(`JarvisToolWheel.setStatus : emplacement inconnu « ${id} »`),
          {code:'tool_wheel_unknown_slot'});
      const next=status&&typeof status==='object'
        ?Object.freeze({icon:status.icon||null,tone:status.tone||null,text:status.text==null?'':String(status.text),
          checked:typeof status.checked==='boolean'?status.checked:null}):null;
      const before=statuses.get(id)||null;
      if(JSON.stringify(before)===JSON.stringify(next))return;
      if(next)statuses.set(id,next);else statuses.delete(id);
      render();
      log('info','tool_wheel.status',{slot:id,tone:next&&next.tone,text:next&&next.text,checked:next&&next.checked});
    }

    mount();
    root.JarvisToolWheel=Object.freeze({
      register,setStatus,
      status:id=>statuses.get(id)||null,
      open(){dispatch({type:'open'})},
      close(){dispatch({type:'close'})},
      isOpen:()=>state.open,
      /* L'ancre : là où le focus revient quand un indicateur disparaît. */
      focusAnchor(){if(built)try{built.anchor.focus({preventScroll:true})}catch(_){built.anchor.focus()}},
      snapshot:()=>({...state,sub:state.sub&&{...state.sub}}),
      SLOTS,GEOMETRY,ART,
    });
    /* Montrée **après** sa publication (QA S04 P8) : une roue visible sans
       `JarvisToolWheel` serait une ancre que personne ne peut brancher, et la
       colonne Bare Hands, qui revient quand l'hôte reste caché, serait
       masquée pour rien. */
    host.hidden=false;
    log('info','tool_wheel.installed',{host:DOM.hostId});
  }

  try{installToolWheel()}
  catch(error){
    console.error('[tool_wheel] tool_wheel.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
