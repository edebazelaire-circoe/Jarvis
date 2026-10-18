/* Roue d'outils orbitale du bord gauche.

   Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 02 (architecture
   résolue `docs/06-resolved-architecture.md` D3, D4, §4, §10). Contrat :
   `docs/control-center-shell.md` › Roue d'outils.

   Refonte : handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 03 (cinq
   catégories, sous-menu courbe unique, nouvelle géométrie et nouvelle peau ;
   `docs/06-ui-visual-spec.md` › B).

   Une **nouvelle surface** (D3) : ni la palette Bare Hands, ni le rail de
   capture. Au repos, seule une ancre de `--shell-anchor-w` dépasse du bord
   gauche ; la souris qui l'atteint, la main Bare Hands dont le pointeur
   synthétique l'atteint (même `pointerover`, aucun geste nouveau), ou le
   clavier (Entrée, Espace, flèche droite sur l'ancre) déploient le même
   demi-disque en couches : un cœur lumineux, puis une bande de cinq
   catégories — JARVIS, Sélection, Dossier, Capture, Paramètres, dans cet
   ordre, chacune avec son icône et son libellé toujours lisibles.

   - Chaque catégorie porte un **arbre** (`menu:true`) : l'activer ouvre son
     sous-menu, un panneau de verre courbe accolé au bord extérieur de la
     bande, face au secteur. Un seul sous-menu existe à la fois : activer une
     autre catégorie **remplace** le précédent, fermer l'efface.
   - Survoler ou pointer un secteur le **met en avant** (contour du secteur,
     arc lumineux, et sa phrase d'état au cœur) ; l'activer, c'est `click` — souris, Entrée, Espace,
     pincement principal Bare Hands —, **jamais** `pointerup` : un pincement ne
     déclenche donc qu'une fois (Bare Hands envoie pointerdown, mousedown,
     pointerup, mouseup, click).
   - L'activation secondaire est le canal existant (D4) : clic droit, pincement
     pouce + majeur Bare Hands (un vrai `contextmenu`), touche `ContextMenu` ou
     `Maj+F10`. Jamais d'appui long (décision 22 de Bare Hands). Elle ouvre un
     **sous-arc** radial dont l'action fournit les entrées : le même motif
     servira au choix Souris / Bare Hands de Sélection (S03) et aux cibles de
     capture (S04).
   - Ce que fait une catégorie est **injecté** (`register`) : Sélection par
     `control_center_input_arbitration.js`, Capture (Capture d'écran,
     Enregistrer l'écran, Enregistrer l'audio dans son arbre) par
     `control_center_capture_wheel.js`, JARVIS et Paramètres par
     `control_center_jarvis_wheel.js` (Slice 04), Dossier par
     `control_center_dossier.js` (Slice 07). Une catégorie dont le module
     ne s'est pas installé le dit à l'activation (`tool_wheel.unbound`,
     « module non chargé ») : aucune action simulée. Une entrée
     `status:true` est une ligne d'état (lisible, focalisable, elle n'agit
     pas) ; activer une entrée inerte ne ferme pas la roue. `refresh(id)`
     relit le premier niveau d'un sous-menu ouvert quand son état change
     (Capture, JARVIS), sans le refermer ni déplacer le focus. `menu` peut aussi être une
     fonction relue à chaque clic ; une entrée du sous-menu qui porte
     `onSecondary` ouvre à son tour un **second niveau** à la place du premier,
     dans le même arbre (Sélection › Bare Hands ; Capture › Vidéo › cibles),
     `Échap` / flèche gauche y ramène. Une entrée `menu` (booléen ou fonction)
     ouvre ce second niveau dès l'activation principale.
   - Exclusivité : la roue et le panneau Board ne sont jamais ouverts
     ensemble (`docs/control-center-shell.md` › *Exclusive surfaces*). Ouvrir
     l'une ferme l'autre, par l'événement `JarvisShell.EXCLUSIVE_EVENT` ; le
     simple survol de l'ancre n'ouvre pas la roue tant que le panneau est
     ouvert (seule une activation explicite le fait).
   - Le déploiement ne dépend d'aucun aller-retour réseau et n'ajoute aucune
     boucle de sondage : ce module n'appelle ni `fetch` ni minuterie
     périodique ; sa seule minuterie est le délai de grâce d'une sortie du
     pointeur.

   Plus de drapeau depuis la Slice 04 (orbital-ui) : la roue se construit à
   l'installation et rend son hôte visible. L'hôte est déclaré `hidden` dans la page : si ce module ne s'installe pas, il le
   reste, et la colonne Bare Hands (masquée tant que la roue est visible)
   revient d'elle-même. Retour arrière : cacher ou retirer `#toolWheel`.

   Deux blocs : le **modèle pur** (géométrie, réducteur d'événements → effets),
   exécuté par node dans `tests/unit/test_tool_wheel_js.py`, et le **bloc
   navigateur** (DOM, focus, appels injectés), éprouvé dans Chrome par
   `tests/unit/test_tool_wheel_browser.py`. */
(function(root){
  'use strict';

  /* ------------------------------------------------- les emplacements */

  /* Ordre verrouillé (docs/06-ui-visual-spec.md › B) ; `heading` : le titre
     du sous-menu de la catégorie. */
  const SLOTS=Object.freeze([
    Object.freeze({id:'jarvis',label:'JARVIS',heading:'État de Jarvis'}),
    Object.freeze({id:'selection',label:'Sélection',heading:'Sélection'}),
    Object.freeze({id:'dossier',label:'Dossier',heading:'Dossier du Board'}),
    Object.freeze({id:'capture',label:'Capture',heading:'Capture'}),
    Object.freeze({id:'settings',label:'Paramètres',heading:'Paramètres'}),
  ]);
  const SLOT_IDS=Object.freeze(SLOTS.map(slot=>slot.id));

  /* ------------------------------------------------- la géométrie

     Centre de la roue sur le bord gauche, à mi-hauteur de son hôte. Les
     angles se comptent depuis l'axe horizontal vers la droite, positifs vers
     le bas (repère de l'écran). Trois couches : le cœur (`hubRadius`, rien ne
     s'y active), la bande des catégories (de `hubRadius` à `radius`), et le
     sous-menu courbe, posé au-delà de `subInner`. Les secteurs se partagent
     `spanDeg` à parts égales ; chaque secteur entier, du cœur au bord, est la
     cible du pointeur (aucun trou où la main « tomberait »). */
  const GEOMETRY=Object.freeze({
    radius:224,        // = --shell-wheel-r
    hubRadius:76,      // le cœur : rien ne s'y active
    iconRadius:150,    // rayon des icônes (libellé dessous)
    dot:48,            // côté de la cible visible icône + libellé (≥ --shell-wedge-min)
    wedgeMin:48,       // = --shell-wedge-min
    spanDeg:170,       // ouverture totale, centrée sur l'horizontale
    subInner:238,      // bord intérieur (concave) du sous-menu courbe
    subRowH:50,        // hauteur d'une ligne du sous-menu
    subRowW:256,       // largeur d'une ligne du sous-menu
    subHeadH:30,       // titre du sous-menu
    subPad:10,         // marge intérieure du panneau
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

  /* Tracé SVG d'un secteur annulaire (contour du secteur en avant, arc
     lumineux), dans le même repère que `sectorPolygon`. */
  function sectorPath(startDeg,endDeg,inner,outer,g=GEOMETRY){
    const p=(r,deg)=>`${round(r*Math.cos(rad(deg)))} ${round(g.radius+r*Math.sin(rad(deg)))}`;
    const large=Math.abs(endDeg-startDeg)>180?1:0;
    return `M ${p(outer,startDeg)} A ${outer} ${outer} 0 ${large} 1 ${p(outer,endDeg)} `
      +`L ${p(inner,endDeg)} A ${inner} ${inner} 0 ${large} 0 ${p(inner,startDeg)} Z`;
  }

  /* Le sous-menu courbe : un titre puis `count` lignes empilées, centrées
     sur la hauteur du secteur parent (ou sur `centreY`, la ligne parente
     d'un second niveau), tenues dans la hauteur de la roue (±radius). Le
     bord gauche de chaque ligne suit l'arc intérieur `subInner` : la pile
     épouse la roue, comme un anneau de plus. Rend les lignes (`x`, `y` =
     centre vertical, `top`, `h`, dans le repère du centre de la roue), le
     titre, les bornes et `path`, le panneau de verre (bord concave sur
     `subInner`, bord convexe sur `outer`), dans le repère de la boîte du
     panneau (centre en (0, radius)). Une liste longue resserre ses lignes
     (40 px au moins) plutôt que de sortir de la roue : neuf lignes tiennent ;
     au-delà, la pile déborde (aucun arbre actuel n'en a autant). */
  function layoutSubMenu(count,midDeg,g=GEOMETRY,centreY){
    const n=Math.max(0,count|0);
    const room=2*(g.radius-6)-2*g.subPad-g.subHeadH;
    const rowH=n?Math.max(40,Math.min(g.subRowH,Math.floor(room/n))):g.subRowH;
    const total=2*g.subPad+g.subHeadH+n*rowH;
    const wanted=Number.isFinite(centreY)?centreY:g.subInner*Math.sin(rad(midDeg));
    const lim=g.radius-6;
    const top=Math.max(-lim,Math.min(wanted-total/2,lim-total));
    const bottom=top+total;
    const edge=(y0,y1)=>{
      const near=y0<=0&&y1>=0?0:Math.min(Math.abs(y0),Math.abs(y1));
      return Math.sqrt(Math.max(0,g.subInner*g.subInner-near*near))+g.subPad;
    };
    const headTop=top+g.subPad;
    const head={x:round(edge(headTop,headTop+g.subHeadH)),y:round(headTop+g.subHeadH/2),h:g.subHeadH};
    const rows=[];
    let outer=g.subInner+g.subPad;
    for(let i=0;i<n;i+=1){
      const y0=headTop+g.subHeadH+i*rowH,y1=y0+rowH;
      const x=edge(y0,y1);
      outer=Math.max(outer,Math.hypot(x+g.subRowW+g.subPad,Math.max(Math.abs(y0),Math.abs(y1))));
      rows.push({index:i,x:round(x),y:round(y0+rowH/2),top:round(y0),h:rowH});
    }
    outer=Math.ceil(outer);
    const inX=y=>round(Math.sqrt(Math.max(0,g.subInner*g.subInner-y*y)));
    const outX=y=>round(Math.sqrt(Math.max(0,outer*outer-y*y)));
    const by=y=>round(g.radius+y);
    const path=`M ${inX(top)} ${by(top)} A ${g.subInner} ${g.subInner} 0 0 1 ${inX(bottom)} ${by(bottom)} `
      +`L ${outX(bottom)} ${by(bottom)} A ${outer} ${outer} 0 0 0 ${outX(top)} ${by(top)} Z`;
    return {rows,head,top:round(top),bottom:round(bottom),rowH,outer,right:round(Math.max(...rows.map(r=>r.x+g.subRowW),head.x)+g.subPad),path};
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
          /* `blocked` : une autre surface exclusive est ouverte (panneau
             Board) ; le survol ne la lui retire pas, seule une activation
             explicite (clic, pincement, clavier) le fait. */
          if(!s.open&&input.blocked)fx.push({do:'journal',key:'tool_wheel.hover_blocked',data:{by:input.blocked}});
          else if(!s.open)openWith('pointer',input.source||'mouse');
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
        }else if(s.open&&input.target==='item'&&s.sub&&input.menu&&s.sub.level===1){
          /* Une entrée `menu` ouvre son second niveau au lieu d'agir. */
          itemSecondary(input.index,input.source||'mouse',input.t);
        }else if(s.open&&input.target==='item'&&s.sub&&input.inert){
          /* Une entrée inerte (ligne d'état, entrée indisponible) : rien
             n'agit, la roue reste ouverte (QA S03, polish 1). */
          fx.push({do:'journal',key:'tool_wheel.item_inert',data:{slot:s.sub.slot,index:input.index}});
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
          /* Flèche droite sur une catégorie à arbre : son sous-menu, qui est à
             droite (le focus y entre). */
          if(key==='ArrowRight'&&input.menu){fx.push({do:'preventDefault'});secondary(i,'keyboard',input.t);break}
          const moves={ArrowDown:i+1,ArrowRight:i+1,ArrowUp:i-1,ArrowLeft:i-1,Home:0,End:n-1};
          if(key in moves){
            fx.push({do:'preventDefault'});
            s.openedBy='keyboard';s.sub=null;
            focusWedge(moves[key],true);
          }else if(key==='Escape'&&s.sub){
            /* Le sous-menu ouvert à la souris, focus resté sur sa catégorie :
               Échap ferme la couche du dessus seulement. */
            fx.push({do:'preventDefault'});s.sub=null;s.lastSecondary=null;
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
          }else if(key==='ContextMenu'||(key==='F10'&&input.shiftKey)||(key==='ArrowRight'&&input.popup)){
            /* Flèche droite sur une entrée qui a un second niveau : l'ouvrir. */
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
      case 'exclusive':
        /* Une autre surface exclusive s'ouvre (panneau Board) : la roue lui
           cède la place ; le focus est à elle, il n'est pas rendu à l'ancre. */
        close('exclusive',false);
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
    /* ---- Slice 03 (refonte) : les cinq catégories, même grille, même trait ----
       JARVIS : l'onde de la voix ; Dossier : la chemise ; Capture : le viseur
       et son objectif ; Paramètres : trois curseurs. */
    jarvis:Object.freeze({paths:Object.freeze(['M12 6.5v11','M8.6 9v6','M15.4 9v6','M5.2 10.8v2.4','M18.8 10.8v2.4']),dots:Object.freeze([])}),
    dossier:Object.freeze({paths:Object.freeze([
      'M3.8 7.2a1.6 1.6 0 0 1 1.6-1.6h3.9l1.9 2.1h7.4a1.6 1.6 0 0 1 1.6 1.6v8.3a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6z',
      'M3.8 10.4h16.4']),dots:Object.freeze([])}),
    capture:Object.freeze({paths:Object.freeze([
      'M4 8.2V5.8A1.8 1.8 0 0 1 5.8 4h2.4','M15.8 4h2.4A1.8 1.8 0 0 1 20 5.8v2.4',
      'M20 15.8v2.4a1.8 1.8 0 0 1-1.8 1.8h-2.4','M8.2 20H5.8A1.8 1.8 0 0 1 4 18.2v-2.4',
      'M12 8.4a3.6 3.6 0 1 1 0 7.2a3.6 3.6 0 1 1 0-7.2z']),dots:Object.freeze([[12,12,1.2]])}),
    settings:Object.freeze({paths:Object.freeze([
      'M4 7h8.2','M16.6 7H20','M4 12h2.6','M11 12h9','M4 17h10.2','M18.6 17H20',
      'M14.4 4.8a2.2 2.2 0 1 1 0 4.4a2.2 2.2 0 1 1 0-4.4z','M8.8 9.8a2.2 2.2 0 1 1 0 4.4a2.2 2.2 0 1 1 0-4.4z',
      'M16.4 14.8a2.2 2.2 0 1 1 0 4.4a2.2 2.2 0 1 1 0-4.4z']),dots:Object.freeze([])}),
    chevron:Object.freeze({paths:Object.freeze(['M9.6 6.4l5.4 5.6-5.4 5.6']),dots:Object.freeze([])}),
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
    /* ---- jarvis-board-ui-wheel-dossier-refactor S04 : le sous-menu JARVIS ----
       Touche d'éveil : une touche de clavier ; Agent : le brain, une tête et
       son onde ; Sous-agents : trois nœuds reliés (le dessin du panneau). */
    key:Object.freeze({paths:Object.freeze(['M4.5 7.5h15a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 15V9a1.5 1.5 0 0 1 1.5-1.5z',
      'M7 13.2h10']),dots:Object.freeze([[7,10.4,.8],[10.3,10.4,.8],[13.7,10.4,.8],[17,10.4,.8]])}),
    agent:Object.freeze({paths:Object.freeze(['M12 4a6.4 6.4 0 0 1 6.4 6.4c0 2.3-1.2 4-2.6 5.2V19H8.2v-3.4A6.4 6.4 0 0 1 12 4z',
      'M9.4 10.6h1.4l1-2 1.4 4 1-2h1']),dots:Object.freeze([])}),
    subagents:Object.freeze({paths:Object.freeze(['M6 3.8a2.2 2.2 0 1 1 0 4.4a2.2 2.2 0 1 1 0-4.4z',
      'M18 9.8a2.2 2.2 0 1 1 0 4.4a2.2 2.2 0 1 1 0-4.4z','M6 15.8a2.2 2.2 0 1 1 0 4.4a2.2 2.2 0 1 1 0-4.4z',
      'M8.2 6.6 15.8 11','M8.2 17.4l7.6-4.4']),dots:Object.freeze([])}),
    /* ---- Slice 04 : arrêter un enregistrement, et la coche d'une capture prise ---- */
    stop:Object.freeze({paths:Object.freeze(['M7.5 7.5h9v9h-9z']),dots:Object.freeze([])}),
    done:Object.freeze({paths:Object.freeze(['M5.5 12.5l4.2 4.2 8.8-9.4']),dots:Object.freeze([])}),
    /* ---- Slice 06 : les actions de Sélection ----
       Œil ouvert (afficher), œil barré (masquer), un point, une capsule et un
       cadre (changer la forme), un cadre dont sort une flèche (retirer la
       représentation du Board). Ranger réutilise la chemise du Dossier. */
    eye:Object.freeze({paths:Object.freeze(['M3 12s3.4-6 9-6 9 6 9 6-3.4 6-9 6-9-6-9-6z',
      'M12 9.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5z']),dots:Object.freeze([])}),
    eye_off:Object.freeze({paths:Object.freeze(['M3 12s3.4-6 9-6c1.6 0 3 .5 4.2 1.2','M21 12s-3.4 6-9 6c-1.6 0-3-.5-4.2-1.2',
      'M4.5 19.5l15-15']),dots:Object.freeze([])}),
    form:Object.freeze({paths:Object.freeze(['M3.5 10.5h5a2 2 0 0 1 0 4h-5a2 2 0 0 1 0-4z',
      'M13.5 6.5h7v11h-7z']),dots:Object.freeze([[6,6,1.2]])}),
    remove:Object.freeze({paths:Object.freeze(['M4 5.5h9v13H4z','M11 12h9.5','M17.5 9l3 3-3 3']),dots:Object.freeze([])}),
  });

  const DOM=Object.freeze({hostId:'toolWheel',styleId:'toolWheelStyle',menuId:'toolWheelMenu',
    labelId:'toolWheelLabel',hintId:'toolWheelHint',subHeadId:'toolWheelSubHead'});

  const api=Object.freeze({
    SLOTS,SLOT_IDS,GEOMETRY,ART,DOM,LEAVE_GRACE_MS,SECONDARY_DEDUPE_MS,
    minSeparationDeg,layoutWedges,sectorPolygon,sectorPath,layoutSubMenu,initialState,reduce,viewOf,
  });
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- la feuille

     Référence : `assets/style-reference-radial-ui.png` de la tâche, sans la
     copier. Un demi-disque de verre sombre en couches (cœur lumineux retenu,
     bande des catégories, anneaux fins cyan), la catégorie en avant cernée
     d'un contour clair et d'un arc lumineux, et son sous-menu : un panneau de
     verre courbe dont le bord concave épouse la roue. Monospace de la page,
     petites capitales espacées pour les noms de section, icônes au trait
     de 1.5. Le mouvement dit l'état (le demi-disque glisse depuis le bord,
     le sous-menu sort de la bande) et vaut zéro sous
     `prefers-reduced-motion` : toutes les durées passent par `--shell-dur*`,
     que la page remet à 0 ms. Aucune conduite n'attend une fin de
     transition. Aucun `z-index` ici : les rangs de l'hôte (30 au repos, 37
     ouvert) vivent dans la page et au registre. `--tw-scale` réduit la roue
     entière sur une fenêtre basse ou étroite (les cibles restent ≥ 40 px). */
  const H='#'+DOM.hostId;
  const ACCENT='var(--accent,#6ee7ff)';
  const STYLE=`
${H}{--tw-scale:1;--tw-hub:${GEOMETRY.hubRadius}px;--tw-ink:var(--text,#d8edf7);--tw-mute:var(--muted,#7190a0);
  --tw-line:color-mix(in srgb,${ACCENT} 22%,transparent);--tw-line-hi:color-mix(in srgb,${ACCENT} 78%,transparent);
  --tw-glass:rgba(5,12,18,.86);--tw-glass-deep:rgba(3,8,13,.92);
  font:13px/1.25 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--tw-ink)}
@media(max-height:620px){${H}{--tw-scale:.86}}
@media(max-height:520px){${H}{--tw-scale:.76}}
@media(max-width:560px){${H}{--tw-scale:.84}}
${H} .tw-anchor{position:relative;display:block;width:var(--shell-anchor-w);height:112px;margin:0;padding:0;
  border:1px solid var(--shell-stroke);border-left:0;border-radius:0 12px 12px 0;background:var(--shell-glass-bg);
  backdrop-filter:blur(12px);cursor:pointer;pointer-events:auto;
  transition:border-color var(--shell-dur-fast) var(--shell-ease),background var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-anchor::before{content:"";position:absolute;left:4px;top:30px;bottom:30px;width:2px;border-radius:2px;
  background:linear-gradient(to bottom,transparent,color-mix(in srgb,${ACCENT} 70%,transparent),transparent)}
${H} .tw-anchor[data-tw-tone=error]{border-color:var(--sem-problem,#ff6a4d)}
${H} .tw-anchor[data-tw-tone=error]::before{background:var(--sem-problem,#ff6a4d)}
${H} .tw-anchor[data-tw-tone=wait]{border-color:var(--sem-working,#4da3ff)}
${H} .tw-anchor[data-tw-tone=wait]::before{background:var(--sem-working,#4da3ff)}
${H} .tw-anchor[data-tw-tone]::after{position:absolute;left:0;right:0;top:8px;text-align:center;
  font:700 10px/1 ui-monospace,Consolas,monospace;content:"!" / "";color:var(--sem-problem,#ff6a4d)}
${H} .tw-anchor[data-tw-tone=wait]::after{content:"…" / "";color:var(--sem-working,#4da3ff)}
${H} .tw-anchor:hover,${H} .tw-anchor[aria-expanded=true]{border-color:var(--shell-stroke-active);
  background:var(--shell-glass-strong)}
${H} .tw-anchor:focus-visible{outline:var(--shell-focus-w) solid var(--shell-focus);outline-offset:2px}
${H} .tw-panel{position:absolute;left:0;top:50%;width:calc(var(--shell-wheel-r) + 1px);height:calc(var(--shell-wheel-r) * 2);
  margin-top:calc(var(--shell-wheel-r) * -1);pointer-events:none;visibility:hidden;opacity:0;
  transform:translateX(-32px) scale(calc(var(--tw-scale) * .92));transform-origin:0 50%;
  transition:opacity var(--shell-dur) var(--shell-ease),transform var(--shell-dur) var(--shell-ease),visibility 0s linear var(--shell-dur)}
${H}[data-open] .tw-panel{visibility:visible;opacity:1;transform:scale(var(--tw-scale));
  transition:opacity var(--shell-dur) var(--shell-ease),transform var(--shell-dur) var(--shell-ease),visibility 0s}
/* Couche 1 : le demi-disque de verre, plus dense vers le cœur ; ombre portée
   douce (décalée vers le bas), pas de halo coloré. */
${H} .tw-disc{position:absolute;inset:0;border-radius:0 100% 100% 0 / 0 50% 50% 0;
  background:radial-gradient(circle at 0 50%,var(--tw-glass-deep) 0,var(--tw-glass-deep) 34%,var(--tw-glass) 35%,rgba(5,12,18,.8) 100%);
  backdrop-filter:blur(16px);box-shadow:0 16px 44px rgba(0,0,0,.42)}
${H} .tw-ring{position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible;pointer-events:none;fill:none;
  stroke:var(--tw-line);stroke-width:1}
${H} .tw-ring .tw-ring-outer{stroke:color-mix(in srgb,${ACCENT} 46%,transparent);stroke-width:1.2}
${H} .tw-ring .tw-ring-halo{stroke:color-mix(in srgb,${ACCENT} 16%,transparent)}
${H} .tw-ring .tw-tick{stroke:color-mix(in srgb,${ACCENT} 30%,transparent)}
${H} .tw-ring .tw-split{stroke:color-mix(in srgb,${ACCENT} 13%,transparent)}
${H} .tw-ring .tw-sec{fill:transparent;stroke:transparent;
  transition:fill var(--shell-dur-fast) var(--shell-ease),stroke var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-ring .tw-sec.is-on{fill:color-mix(in srgb,${ACCENT} 8%,transparent);stroke:color-mix(in srgb,${ACCENT} 52%,transparent)}
${H} .tw-ring .tw-arc{stroke:transparent;stroke-width:3;stroke-linecap:round;
  transition:stroke var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-ring .tw-arc.is-on{stroke:var(--tw-line-hi);filter:drop-shadow(0 0 4px color-mix(in srgb,${ACCENT} 55%,transparent))}
/* Couche 2 : le cœur, la petite lueur Jarvis ; il porte la phrase de la
   catégorie en avant (nom + état projeté). */
${H} .tw-core{position:absolute;left:calc(var(--tw-hub) * -1);top:calc(50% - var(--tw-hub));width:calc(var(--tw-hub) * 2);
  height:calc(var(--tw-hub) * 2);border-radius:50%;pointer-events:none;
  border:1px solid color-mix(in srgb,${ACCENT} 34%,transparent);
  background:radial-gradient(circle at 50% 50%,rgba(225,250,255,.9) 0,color-mix(in srgb,${ACCENT} 62%,transparent) 5%,
    color-mix(in srgb,${ACCENT} 22%,transparent) 22%,color-mix(in srgb,${ACCENT} 7%,transparent) 44%,transparent 66%);
  box-shadow:inset 0 0 0 7px rgba(3,8,13,.55),inset 0 0 0 8px color-mix(in srgb,${ACCENT} 16%,transparent)}
${H} .tw-label{position:absolute;left:14px;top:50%;width:calc(var(--tw-hub) - 20px);transform:translateY(-50%);
  display:grid;gap:3px;pointer-events:none;overflow-wrap:anywhere}
${H} .tw-label .tw-label-name{font-size:9px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:${ACCENT}}
${H} .tw-label .tw-label-sep{display:none}
${H} .tw-label .tw-label-state{font-size:10px;line-height:1.3;color:var(--tw-ink)}
${H} .tw-label .tw-label-state:empty{display:none}
${H} .tw-label[hidden],${H} .tw-sub[hidden]{display:none}
/* Couche 3 : la bande des catégories ; chaque secteur entier est la cible. */
${H} .tw-wedge{position:absolute;inset:0;margin:0;padding:0;border:0;background:transparent;color:inherit;
  cursor:pointer;pointer-events:auto;-webkit-tap-highlight-color:transparent}
${H} .tw-dot{position:absolute;width:84px;height:56px;transform:translate(-50%,-50%);display:grid;justify-items:center;
  align-content:center;gap:5px;border-radius:12px;color:var(--tw-mute);
  transition:color var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-dot svg{width:24px;height:24px}
${H} .tw-name{font-size:9.5px;font-weight:600;letter-spacing:.11em;text-transform:uppercase;white-space:nowrap;color:var(--tw-ink);opacity:.82}
${H} .tw-wedge.is-focus .tw-dot,${H} .tw-wedge[aria-expanded=true] .tw-dot{color:${ACCENT}}
${H} .tw-wedge.is-focus .tw-name,${H} .tw-wedge[aria-expanded=true] .tw-name{color:${ACCENT};opacity:1}
${H} .tw-wedge.is-focus .tw-dot svg,${H} .tw-wedge[aria-expanded=true] .tw-dot svg{filter:drop-shadow(0 0 5px color-mix(in srgb,${ACCENT} 45%,transparent))}
${H} .tw-wedge:focus-visible .tw-dot{outline:var(--shell-focus-w) solid var(--shell-focus);outline-offset:0}
${H} .tw-wedge[aria-disabled=true] .tw-dot{opacity:.55}
${H} .tw-dot .tw-badge{position:absolute;left:calc(50% + 6px);top:2px;width:15px;height:15px;border-radius:50%;
  display:grid;place-items:center;font:700 10px/1 ui-monospace,Consolas,monospace;color:#0b0f14;pointer-events:none}
${H} .tw-dot .tw-badge[data-tw-tone=error]{background:var(--sem-problem,#ff6a4d)}
/* « ? » d'un état inconnu (statut des captures perdu) : gris et pointillé,
   jamais la couleur seule ; il ne colore pas l'ancre. */
${H} .tw-dot .tw-badge[data-tw-tone=unknown]{background:var(--muted,#7190a0);outline:1px dashed var(--text,#d8edf7);outline-offset:1px}
${H} .tw-dot .tw-badge[data-tw-tone=wait]{background:transparent;border:2px solid var(--sem-working,#4da3ff);
  border-right-color:transparent;animation:tw-spin 1s linear infinite}
/* Un canal ouvert (Capture : un enregistrement en cours) : icône ambre et
   point plein — l'état coché du secteur (aria-checked), lisible sans la couleur. */
${H} .tw-wedge[aria-checked=true] .tw-dot,${H} .tw-wedge[data-tw-live] .tw-dot{color:var(--sem-alert,#ff9f43)}
${H} .tw-wedge[aria-checked=true] .tw-dot::after,${H} .tw-wedge[data-tw-live] .tw-dot::after{content:"";position:absolute;left:calc(50% - 21px);top:4px;width:9px;height:9px;
  border-radius:50%;background:var(--sem-alert,#ff9f43);box-shadow:0 0 0 2px var(--tw-glass-deep)}
@keyframes tw-spin{to{transform:rotate(360deg)}}
/* Couche 4 : le sous-menu courbe. Le verre est découpé par \`clip-path: path()\`
   (le tracé de \`layoutSubMenu\`) ; le liseré est un SVG au-dessus, sans
   pointeur ; un clic sur le verre reste « dans » la roue. */
${H} .tw-sub{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;
  animation:tw-sub-in var(--shell-dur) var(--shell-ease)}
@keyframes tw-sub-in{from{opacity:0;transform:translateX(-12px)}to{opacity:1;transform:none}}
${H} .tw-sub-glass{position:absolute;left:0;top:0;height:100%;pointer-events:auto;
  background:linear-gradient(100deg,rgba(7,17,25,.9),rgba(4,10,15,.84));backdrop-filter:blur(18px)}
${H} .tw-sub-line{position:absolute;left:0;top:0;height:100%;overflow:visible;pointer-events:none;fill:none;
  stroke:var(--tw-line);stroke-width:1}
${H} .tw-sub-line .tw-sub-link{stroke:var(--tw-line-hi);stroke-width:2;stroke-linecap:round}
${H} .tw-subhead{position:absolute;transform:translateY(-50%);margin:0;padding:0 0 0 4px;white-space:nowrap;
  font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:color-mix(in srgb,${ACCENT} 80%,var(--tw-ink))}
${H} .tw-item{position:absolute;box-sizing:border-box;display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;align-items:center;
  column-gap:11px;margin:0;padding:0 10px 0 6px;border:1px solid transparent;border-radius:10px;
  background:transparent;color:var(--tw-ink);font:inherit;font-size:12.5px;text-align:left;cursor:pointer;pointer-events:auto;
  transition:border-color var(--shell-dur-fast) var(--shell-ease),background var(--shell-dur-fast) var(--shell-ease),color var(--shell-dur-fast) var(--shell-ease)}
${H} .tw-item+.tw-item::before{content:"";position:absolute;left:52px;right:10px;top:-3px;height:1px;background:var(--tw-line);opacity:.6}
${H} .tw-item.is-focus{border-color:color-mix(in srgb,${ACCENT} 52%,transparent);background:color-mix(in srgb,${ACCENT} 9%,transparent)}
${H} .tw-item:focus-visible{outline:var(--shell-focus-w) solid var(--shell-focus);outline-offset:1px}
${H} .tw-tile{grid-column:1;grid-row:1;display:grid;place-items:center;width:34px;height:34px;border-radius:9px;border:1px solid var(--tw-line);
  background:rgba(255,255,255,.025);color:color-mix(in srgb,${ACCENT} 82%,var(--tw-ink))}
${H} .tw-tile svg{width:18px;height:18px}
${H} .tw-copy{grid-column:2;grid-row:1;display:grid;gap:2px;min-width:0}
${H} .tw-item .tw-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
${H} .tw-item .tw-note{color:var(--tw-mute);font-size:10.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
${H} .tw-chev{grid-column:4;grid-row:1;width:14px;height:14px;color:var(--tw-mute)}
${H} .tw-item[aria-checked=true]{color:${ACCENT}}
${H} .tw-item[aria-checked=true]::after{grid-column:3;grid-row:1;content:"" / "";width:8px;height:8px;border-radius:50%;background:${ACCENT};
  box-shadow:0 0 0 3px color-mix(in srgb,${ACCENT} 18%,transparent)}
${H} .tw-item[aria-checked=true] .tw-tile{border-color:color-mix(in srgb,${ACCENT} 60%,transparent)}
${H} .tw-item[data-tw-tone=error] .tw-tile{border-color:color-mix(in srgb,var(--sem-problem,#ff6a4d) 70%,transparent);color:var(--sem-problem,#ff6a4d)}
${H} .tw-item[data-tw-tone=error] .tw-note{color:var(--sem-problem,#ff6a4d)}
${H} .tw-item[data-tw-tone=wait] .tw-note{color:var(--sem-working,#4da3ff)}
${H} .tw-item[data-tw-tone=busy] .tw-tile{border-color:color-mix(in srgb,var(--sem-alert,#ff9f43) 70%,transparent);color:var(--sem-alert,#ff9f43)}
${H} .tw-item[data-tw-tone=busy] .tw-note{color:var(--sem-alert,#ff9f43)}
${H} .tw-item[aria-disabled=true]{cursor:default}
${H} .tw-item[aria-disabled=true] .tw-text{color:color-mix(in srgb,var(--tw-ink) 72%,transparent)}
${H} .tw-item[aria-disabled=true] .tw-tile{border-style:dashed;color:var(--tw-mute)}
/* Ligne d'état (Slice 04, sous-menu JARVIS) : un fait, pas une commande. Pas de cadre de tuile ni de
   chevron, le texte garde son contraste, la valeur courante se lit en couleur d'accent ; un fait non
   confirmé (unknown) a une tuile pointillée et un « ? » ; hors ligne (off), la valeur est atténuée. */
${H} .tw-item[data-tw-kind=status]{cursor:default}
${H} .tw-item[data-tw-kind=status] .tw-text{color:var(--tw-ink)}
${H} .tw-item[data-tw-kind=status] .tw-tile{border-style:solid;border-color:transparent;background:transparent;color:var(--tw-mute)}
${H} .tw-item[data-tw-kind=status] .tw-note{color:color-mix(in srgb,${ACCENT} 78%,var(--tw-ink))}
${H} .tw-item[data-tw-tone=unknown] .tw-tile{border-style:dashed;border-color:var(--tw-line)}
${H} .tw-item[data-tw-tone=unknown] .tw-note,${H} .tw-item[data-tw-tone=off] .tw-note{color:var(--tw-mute)}
${H} .tw-item[data-tw-tone=unknown] .tw-note::before{content:"? ";font-weight:700}
${H} .tw-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(prefers-reduced-motion:reduce){
  ${H} .tw-dot .tw-badge[data-tw-tone=wait]{animation:none}
  ${H} .tw-sub{animation:none}
}
@media(forced-colors:active){
  ${H} .tw-anchor,${H} .tw-item,${H} .tw-tile{border-color:CanvasText}
  ${H} .tw-disc,${H} .tw-sub-glass{background:Canvas;forced-color-adjust:none;border:1px solid CanvasText}
  ${H} .tw-sub-glass{border:0}
  ${H} .tw-core{border-color:CanvasText;background:Canvas}
  ${H} .tw-dot,${H} .tw-name,${H} .tw-label .tw-label-name,${H} .tw-subhead{color:CanvasText}
  ${H} .tw-wedge.is-focus .tw-dot,${H} .tw-wedge.is-focus .tw-name,${H} .tw-wedge[aria-expanded=true] .tw-name,${H} .tw-item.is-focus{color:Highlight}
  ${H} .tw-item.is-focus{border-color:Highlight}
  ${H} .tw-ring,${H} .tw-ring .tw-ring-outer,${H} .tw-ring .tw-tick,${H} .tw-ring .tw-split,${H} .tw-sub-line{stroke:CanvasText}
  ${H} .tw-ring .tw-sec.is-on,${H} .tw-ring .tw-arc.is-on,${H} .tw-sub-line .tw-sub-link{stroke:Highlight}
  ${H} .tw-wedge[aria-checked=true] .tw-dot::after,${H} .tw-wedge[data-tw-live] .tw-dot::after,${H} .tw-dot .tw-badge,${H} .tw-item[aria-checked=true]::after{forced-color-adjust:none;background:Highlight;color:HighlightText}
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
  /* Les anneaux : bord extérieur, anneau fin au-delà (texture), graduations
     fines sur le cœur, séparations radiales entre catégories ; puis, par
     secteur, son contour (`tw-sec`) et son arc lumineux (`tw-arc`), allumés
     pour la catégorie en avant. Décoratif (`aria-hidden`, aucun pointeur). */
  function ring(wedges){
    const g=GEOMETRY,cy=g.radius;
    const svg=svgEl('svg',{class:'tw-ring',viewBox:`0 0 ${g.radius+1} ${g.radius*2}`,'aria-hidden':'true',focusable:'false'});
    const at=(r,deg)=>`${round(r*Math.cos(rad(deg)))} ${round(cy+r*Math.sin(rad(deg)))}`;
    const arc=(r,a,b)=>`M ${at(r,a)} A ${r} ${r} 0 0 1 ${at(r,b)}`;
    const line=(r0,r1,deg)=>`M ${at(r0,deg)} L ${at(r1,deg)}`;
    const half=g.spanDeg/2;
    svg.appendChild(svgEl('path',{class:'tw-ring-outer',d:arc(g.radius-1,-89,89)}));
    svg.appendChild(svgEl('path',{class:'tw-ring-halo',d:arc(g.radius-9,-half,half),'stroke-dasharray':'1 5'}));
    svg.appendChild(svgEl('path',{d:arc(g.hubRadius,-89,89)}));
    /* Graduations du cœur : une tous les 10°, plus longue tous les 30°. */
    for(let deg=-80;deg<=80;deg+=10)
      svg.appendChild(svgEl('path',{class:'tw-tick',d:line(g.hubRadius+4,g.hubRadius+(deg%30===0?11:7),deg)}));
    for(const deg of [...wedges.map(w=>w.startDeg),wedges[wedges.length-1].endDeg])
      svg.appendChild(svgEl('path',{class:'tw-split',d:line(g.hubRadius+14,g.radius-14,deg)}));
    const secs=wedges.map(w=>{
      const sec=svgEl('path',{class:'tw-sec',d:sectorPath(w.startDeg+.6,w.endDeg-.6,g.hubRadius+3,g.radius-4)});
      svg.appendChild(sec);
      return sec;
    });
    const arcs=wedges.map(w=>{
      const a=svgEl('path',{class:'tw-arc',d:arc(g.radius-1,w.startDeg+3,w.endDeg-3)});
      svg.appendChild(a);
      return a;
    });
    return {svg,secs,arcs};
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
      const rings=ring(wedgesGeo);
      panel.appendChild(rings.svg);
      const core=document.createElement('div');core.className='tw-core';core.setAttribute('aria-hidden','true');
      panel.appendChild(core);
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
        /* Le libellé, toujours visible ; le nom accessible le porte déjà. */
        const name=document.createElement('span');name.className='tw-name';name.textContent=slot.label;
        name.setAttribute('aria-hidden','true');
        dot.appendChild(name);
        const badge=document.createElement('span');badge.className='tw-badge';badge.hidden=true;
        badge.setAttribute('aria-hidden','true');
        dot.appendChild(badge);
        b.appendChild(dot);
        menu.appendChild(b);
        return b;
      });
      panel.appendChild(menu);
      /* Le relevé du cœur : nom de la catégorie en avant, puis son état. */
      const label=document.createElement('div');
      label.id=DOM.labelId;label.className='tw-label';label.hidden=true;label.setAttribute('aria-hidden','true');
      const labelName=document.createElement('span');labelName.className='tw-label-name';
      const labelSep=document.createElement('span');labelSep.className='tw-label-sep';
      const labelState=document.createElement('span');labelState.className='tw-label-state';
      label.append(labelName,labelSep,labelState);
      panel.appendChild(label);
      const sub=document.createElement('div');
      sub.className='tw-sub';sub.hidden=true;sub.setAttribute('role','menu');
      panel.appendChild(sub);
      const hint=document.createElement('span');
      hint.id=DOM.hintId;hint.className='tw-sr';
      hint.textContent='Entrée ou flèche droite : ouvrir la catégorie. Clic droit, Maj+F10 ou pincement pouce-majeur : plus de choix. Échap : fermer.';
      panel.appendChild(hint);
      const anchor=document.createElement('button');
      anchor.type='button';anchor.className='tw-anchor';
      anchor.setAttribute('aria-label','Outils');anchor.title='Outils';
      anchor.setAttribute('aria-haspopup','menu');anchor.setAttribute('aria-controls',DOM.menuId);
      anchor.setAttribute('aria-expanded','false');
      /* L'ancre avant le panneau : ordre de tabulation ancre → secteur →
         suite de la page (Tab sort de la roue et la ferme). */
      host.appendChild(anchor);host.appendChild(panel);
      return {panel,menu,wedges,label,labelName,labelSep,labelState,sub,anchor,secs:rings.secs,arcs:rings.arcs,
        items:[],itemSpecs:[],parentSpecs:null,subLayout:null,shownIcons:SLOTS.map(slot=>slot.id)};
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
      /* La catégorie allumée : celle dont le sous-menu est ouvert, sinon
         celle en avant. */
      const lit=view.sub?view.sub.slot:(state.open?state.focus:-1);
      built.wedges.forEach((b,i)=>{
        const w=view.wedges[i];
        const action=actions.get(SLOTS[i].id);
        b.classList.toggle('is-focus',w.focused);
        b.tabIndex=w.tabindex;
        b.setAttribute('aria-disabled',String(!action));
        if(action&&(action.menu||typeof action.onSecondary==='function'))b.setAttribute('aria-haspopup','menu');
        else b.removeAttribute('aria-haspopup');
        b.setAttribute('aria-expanded',String(!!view.sub&&view.sub.slot===i));
        built.secs[i].classList.toggle('is-on',lit===i);
        built.arcs[i].classList.toggle('is-on',lit===i);
        paintStatus(i);
      });
      if(view.label){
        const status=statuses.get(SLOTS[state.focus].id);
        built.labelName.textContent=view.label;
        built.labelSep.textContent=status&&status.text?' · ':'';
        built.labelState.textContent=status&&status.text?status.text:'';
        built.label.hidden=false;
      }else built.label.hidden=true;
      if(!view.sub){
        if(built.items.length||built.subLayout){built.sub.textContent='';built.items=[];built.itemSpecs=[];built.subLayout=null}
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
      /* `live` : quelque chose tourne dans l'arbre de la catégorie (Capture :
         un enregistrement ouvert) — point ambre, et la phrase dans le nom. */
      if(status&&status.live)b.setAttribute('data-tw-live','');else b.removeAttribute('data-tw-live');
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

    /* Le sous-menu courbe de la catégorie `slotIndex` : verre découpé, liseré
       (le tronçon face au secteur parent est allumé), titre, lignes. Il
       **remplace** tout sous-menu précédent : un seul arbre est monté.
       `parent` (second niveau) : l'entrée du premier niveau qui l'ouvre ; la
       pile se centre sur elle et le titre la nomme. */
    function fillSub(slotIndex,items,parent){
      const g=GEOMETRY,slot=SLOTS[slotIndex],geo=wedgesGeo[slotIndex];
      const lay=layoutSubMenu(items.length,geo.midDeg,g,parent?parent.y:undefined);
      built.sub.textContent='';
      const width=Math.ceil(lay.outer+2);
      const glass=document.createElement('div');glass.className='tw-sub-glass';
      glass.style.width=`${width}px`;glass.style.clipPath=`path('${lay.path}')`;
      built.sub.appendChild(glass);
      const line=svgEl('svg',{class:'tw-sub-line',width,height:2*g.radius,viewBox:`0 0 ${width} ${2*g.radius}`,
        'aria-hidden':'true',focusable:'false'});
      line.style.width=`${width}px`;
      line.appendChild(svgEl('path',{d:lay.path}));
      /* Le lien : l'arc intérieur du panneau, sur l'ouverture du secteur
         parent (tenu dans la hauteur du panneau). */
      const clampDeg=y=>Math.asin(Math.max(-1,Math.min(1,y/g.subInner)))*180/Math.PI;
      const from=Math.max(geo.startDeg+2,clampDeg(lay.top+4)),to=Math.min(geo.endDeg-2,clampDeg(lay.bottom-4));
      if(to>from){
        const at=deg=>`${round(g.subInner*Math.cos(rad(deg)))} ${round(g.radius+g.subInner*Math.sin(rad(deg)))}`;
        line.appendChild(svgEl('path',{class:'tw-sub-link',d:`M ${at(from)} A ${g.subInner} ${g.subInner} 0 0 1 ${at(to)}`}));
      }
      built.sub.appendChild(line);
      const head=document.createElement('p');
      head.id=DOM.subHeadId;head.className='tw-subhead';
      head.textContent=parent?String(parent.label):slot.heading;
      head.style.left=`${lay.head.x}px`;head.style.top=`${g.radius+lay.head.y}px`;
      built.sub.appendChild(head);
      built.sub.setAttribute('aria-label',parent?`${slot.label} › ${parent.label}`:slot.label);
      built.subLayout=lay;
      built.itemSpecs=items;
      built.items=items.map((spec,j)=>{
        const row=lay.rows[j];
        const b=document.createElement('button');
        b.type='button';b.className='tw-item';
        if(spec.id!=null)b.setAttribute('data-tw-item',String(spec.id));
        /* `toggle` : une entrée qui allume ou éteint (un enregistrement) est une case à cocher, pas un choix exclusif. */
        b.setAttribute('role',typeof spec.checked!=='boolean'?'menuitem':spec.toggle?'menuitemcheckbox':'menuitemradio');
        if(typeof spec.checked==='boolean')b.setAttribute('aria-checked',String(spec.checked));
        if(spec.disabled)b.setAttribute('aria-disabled','true');
        if(['error','wait','busy','unknown','off'].includes(spec.tone))b.setAttribute('data-tw-tone',spec.tone);
        /* `status` : une ligne d'état, lisible au clavier, qui n'agit pas (Slice 04). */
        if(spec.status===true){b.setAttribute('data-tw-kind','status');b.setAttribute('aria-disabled','true')}
        const text=String(spec.label==null?'':spec.label);
        const note=spec.note==null?'':String(spec.note);
        /* `detail` : la phrase longue (un motif d'indisponibilité), dans le nom
           accessible et l'infobulle ; `note` reste courte à l'écran. */
        const detail=spec.detail==null?note:String(spec.detail);
        const spoken=!detail?text:note&&!detail.startsWith(note)?`${text} — ${note} — ${detail}`:`${text} — ${detail}`;
        const art=spec.icon?icon(spec.icon):null;
        if(art){const tile=document.createElement('span');tile.className='tw-tile';tile.appendChild(art);b.appendChild(tile)}
        const copy=document.createElement('span');copy.className='tw-copy';
        const t=document.createElement('span');t.className='tw-text';t.textContent=text;copy.appendChild(t);
        /* Une espace entre le texte et la note (sans effet dans la grille) : lu d'un trait, « principal1:08 »
           n'était plus dans le nom (axe, WCAG 2.5.3). */
        if(note){const n=document.createElement('span');n.className='tw-note';n.textContent=note;copy.append(' ',n)}
        b.appendChild(copy);
        /* Le nom commence par ce que l'entrée montre, texte puis note (WCAG 2.5.3, orbital-ui QA S09 P6) : une
           phrase longue qui ne reprend pas la note s'ajoute après elle. */
        if(art||note)b.setAttribute('aria-label',spoken);
        b.title=spoken;
        if(typeof spec.onSecondary==='function'){
          b.setAttribute('aria-haspopup','menu');
          const chev=icon('chevron');chev.setAttribute('class','tw-chev');b.appendChild(chev);
        }
        b.style.left=`${row.x}px`;b.style.top=`${g.radius+row.top+3}px`;
        b.style.width=`${g.subRowW}px`;b.style.height=`${row.h-6}px`;
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
      /* Le second niveau se centre sur l'entrée parente, lue avant que
         « Chargement… » ne remplace la pile. */
      const row=built.subLayout&&built.subLayout.rows[itemIndex];
      const parent={label:String(spec.label),y:row?row.y:undefined};
      log('info','tool_wheel.item_secondary',{slot:slot.id,item:spec.id==null?itemIndex:spec.id,source});
      const show=items=>{
        if(!state.open||!state.sub||state.sub.slot!==slotIndex)return;
        if(!Array.isArray(items)){log('info','tool_wheel.item_secondary_none',{slot:slot.id,index:itemIndex,source});return}
        fillSub(slotIndex,items,parent);
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
              /* Toutes les catégories sont branchées depuis la Slice 07 : sans gestionnaire, c'est que son
                 module ne s'est pas installé (voir la console : `…install_failed`). */
              log('warn','tool_wheel.unbound',{slot:slot.id,source:fx.source});
              notify(`${slot.label} indisponible`,'Son module ne s’est pas chargé : rechargez la page ; le détail est dans le journal.');
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
        announce(state.open);
      }
    }

    /* Surfaces exclusives (docs/control-center-shell.md › Exclusive surfaces) :
       la roue dit quand elle s'ouvre ou se ferme ; une autre surface qui
       s'ouvre la ferme. `othersOpen` : les surfaces ouvertes ailleurs, pour
       que le survol de l'ancre ne leur retire pas la place. */
    const EXCLUSIVE_EVENT=(root.JarvisShell&&root.JarvisShell.EXCLUSIVE_EVENT)||'jarvis:shell-exclusive';
    const EXCLUSIVE_ID='tool-wheel';
    const othersOpen=new Set();
    function announce(open){
      try{document.dispatchEvent(new CustomEvent(EXCLUSIVE_EVENT,{detail:{id:EXCLUSIVE_ID,open:!!open}}))}
      catch(error){log('warn','tool_wheel.exclusive_announce_failed',{error:errorText(error)})}
    }
    function onExclusive(event){
      const d=event&&event.detail;
      if(!d||typeof d.id!=='string'||d.id===EXCLUSIVE_ID)return;
      if(d.open)othersOpen.add(d.id);else othersOpen.delete(d.id);
      if(d.open&&state.open){
        log('info','tool_wheel.yield',{to:d.id});
        dispatch({type:'exclusive',by:d.id});
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
    /* Pointeur immobile (Slice 08, QA S03 polish 2 et 7) : après une touche, la roue ou un sous-menu se
       redessine sous une souris qui n'a pas bougé et Chrome envoie un `pointerover` de confiance **sans**
       `pointermove` sur ce qui apparaît dessous ; le focus clavier y tombait (flèche droite sur Capture
       focalisait Audio). Un tel survol est ignoré jusqu'au premier vrai mouvement, qui rend alors le survol
       de la cible sous le pointeur. Le pointeur de Bare Hands (événements synthétiques) n'est pas concerné. */
    let pointerStill=false,hoverKey=null;
    function hover(event,t){
      hoverKey=`${t.target}:${t.index}`;
      dispatch({type:'pointerover',...t,source:pointerSource(event),
        blocked:t.target==='anchor'&&othersOpen.size?[...othersOpen][0]:null},event);
    }
    function onOver(event){
      lastOverId=event.pointerId===undefined?null:event.pointerId;
      const t=targetOf(event.target);
      if(t.target!=='anchor'&&t.target!=='wedge'&&t.target!=='item')return;
      if(t.target!=='anchor'&&event.isTrusted&&pointerStill){
        log('info','tool_wheel.hover_ignored',{target:t.target,index:t.index,reason:'pointer_still'});
        return;
      }
      hover(event,t);
    }
    function onMove(event){
      if(!event.isTrusted)return;
      const t=targetOf(event.target);
      const was=pointerStill;
      pointerStill=false;
      if(was&&(t.target==='wedge'||t.target==='item')&&hoverKey!==`${t.target}:${t.index}`)hover(event,t);
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
    /* Une entrée qui n'agit pas : désactivée, ligne d'état, ou sans action ni second niveau. */
    function isInert(spec){
      return !spec||spec.disabled===true||spec.status===true
        ||(typeof spec.onActivate!=='function'&&typeof spec.onSecondary!=='function');
    }
    function onClick(event){
      const t=targetOf(event.target);
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item'){
        const menu=t.target==='wedge'?isMenu(actions.get(SLOTS[t.index].id))
          :t.target==='item'&&isMenu(built.itemSpecs[t.index]);
        dispatch({type:'click',...t,detail:event.detail,source:clickSource(event),menu,
          inert:t.target==='item'&&!menu&&isInert(built.itemSpecs[t.index])},event);
      }
    }
    function onContext(event){
      const t=targetOf(event.target);
      if(t.target==='wedge'||t.target==='item'){
        dispatch({type:'contextmenu',...t,source:contextSource(event)},event);
      }
    }
    function onKey(event){
      const t=targetOf(event.target);
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item'){pointerStill=true;hoverKey=null}
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item')
        dispatch({type:'keydown',...t,key:event.key,shiftKey:event.shiftKey,
          menu:t.target==='wedge'&&isMenu(actions.get(SLOTS[t.index].id)),
          popup:t.target==='item'&&!!built.itemSpecs[t.index]&&typeof built.itemSpecs[t.index].onSecondary==='function'},event);
    }
    function onFocusOut(event){
      const to=event.relatedTarget;
      if(state.open&&to&&!host.contains(to))dispatch({type:'focusOutside'},event);
    }
    const LISTENERS=[['pointerover',onOver],['pointermove',onMove],['pointerout',onOut],['pointerdown',onDown],['click',onClick],
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
      document.addEventListener(EXCLUSIVE_EVENT,onExclusive);
      render();
    }

    /* Branche un emplacement. `action` : `{id, onActivate(ctx), onSecondary?(ctx),
       menu?}` — `onSecondary` rend la liste du sous-arc (`[{id?, label,
       disabled?, checked?, icon?, note?, detail?, tone?:'error'|'wait'|'busy',
       menu?, onActivate?(ctx), onSecondary?(ctx)}]`) ou une promesse de cette
       liste ; `menu:true` (ou une fonction qui le rend) ouvre ce sous-menu
       dès l'activation principale — sur une entrée, il ouvre son second
       niveau. Un nouvel enregistrement remplace le précédent.
       Rend la fonction qui débranche. */
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
       'unknown', text?, checked?, live?}` (ou `null` pour l'effacer). `unknown` marque
       le secteur d'un « ? » sans colorer l'ancre ; `checked` (booléen) en
       fait une case cochée (`menuitemcheckbox`). Peint tout de suite, roue
       ouverte ou non ; journalisé seulement quand il change. */
    function setStatus(id,status){
      if(!SLOT_IDS.includes(id))
        throw Object.assign(new TypeError(`JarvisToolWheel.setStatus : emplacement inconnu « ${id} »`),
          {code:'tool_wheel_unknown_slot'});
      const next=status&&typeof status==='object'
        ?Object.freeze({icon:status.icon||null,tone:status.tone||null,text:status.text==null?'':String(status.text),
          checked:typeof status.checked==='boolean'?status.checked:null,live:status.live===true}):null;
      const before=statuses.get(id)||null;
      if(JSON.stringify(before)===JSON.stringify(next))return;
      if(next)statuses.set(id,next);else statuses.delete(id);
      render();
      log('info','tool_wheel.status',{slot:id,tone:next&&next.tone,text:next&&next.text,checked:next&&next.checked});
    }

    /* Relire le premier niveau du sous-menu ouvert de `id` (Slice 04) : son
       état a changé (une capture qui démarre, la voix qui s'endort). Rien ne
       se passe si ce sous-menu n'est pas ouvert, s'il est au second niveau
       (ses choix peuvent dépendre d'une lecture réseau, relancée seulement
       par l'utilisateur), si l'action rend une promesse, ou si les entrées
       n'ont pas changé. L'entrée en avant et le focus clavier restent sur la
       même ligne. Rend `true` quand le sous-menu a été redessiné. */
    const signatureOf=items=>JSON.stringify(items.map(it=>[it.id,it.label,it.note,it.detail,it.checked,it.tone,it.disabled,
      it.status,it.icon,typeof it.onSecondary==='function']));
    function refresh(id){
      const index=SLOT_IDS.indexOf(id);
      if(index<0)throw Object.assign(new TypeError(`JarvisToolWheel.refresh : emplacement inconnu « ${id} »`),
        {code:'tool_wheel_unknown_slot'});
      if(!built||!state.open||!state.sub||state.sub.slot!==index||(state.sub.level||1)!==1||built.parentSpecs)return false;
      const action=actions.get(id);
      if(!action||typeof action.onSecondary!=='function')return false;
      let items;
      try{items=action.onSecondary({slot:id,source:'refresh'})}
      catch(error){log('error','tool_wheel.refresh_failed',{slot:id,error:errorText(error)});return false}
      if(!Array.isArray(items))return false;
      const sig=signatureOf(items);
      if(sig===signatureOf(built.itemSpecs))return false;
      const focused=built.items.indexOf(document.activeElement);
      const keep=state.sub.focus;
      fillSub(index,items);
      dispatch({type:'subOpen',slot:index,count:items.length,source:'refresh',level:1,
        focus:keep>=0&&keep<items.length?keep:undefined});
      if(focused>=0){
        const el=built.items[Math.min(focused,built.items.length-1)];
        if(el)try{el.focus({preventScroll:true})}catch(_){el.focus()}
      }
      log('info','tool_wheel.refreshed',{slot:id,items:items.length});
      return true;
    }

    mount();
    root.JarvisToolWheel=Object.freeze({
      register,setStatus,refresh,
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
