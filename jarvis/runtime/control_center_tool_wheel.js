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
     Sélection arrive en S03, les captures en S04. Un secteur non branché le
     dit (journal + notification), il ne fait pas semblant.
   - Le déploiement ne dépend d'aucun aller-retour réseau et n'ajoute aucune
     boucle de sondage : ce module n'appelle ni `fetch` ni minuterie
     périodique ; sa seule minuterie est le délai de grâce d'une sortie du
     pointeur.

   Drapeau : `JarvisToolWheel.enabled` vaut `false` par défaut (aucun secteur
   non branché n'atteint l'utilisateur) ; les tests l'allument, la Slice 04 le
   retire. Éteinte, la roue ne construit rien et son hôte reste `hidden`.

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
     dans ±subLimitDeg (une liste longue glisse vers le centre). */
  function layoutSubArc(count,midDeg,g=GEOMETRY){
    const span=g.subStepDeg*(count-1);
    let first=midDeg-span/2;
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
     Effets : `activate`, `secondary`, `item`, `focus`, `restoreFocus`,
     `armLeave`, `cancelLeave`, `preventDefault`, `journal`. */
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
      s.open=false;s.openedBy=null;s.sub=null;s.focus=-1;
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
        else if(s.open&&input.target==='item')fx.push({do:'preventDefault'});
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
          }else if(key==='Escape'||key==='ArrowLeft'){
            fx.push({do:'preventDefault'});
            const parent=s.sub.slot;s.sub=null;
            focusWedge(parent,true);
          }else if(key==='ContextMenu'||(key==='F10'&&input.shiftKey))fx.push({do:'preventDefault'});
        }
        break;
      }
      case 'subOpen':
        if(!s.open)break;
        s.sub={slot:input.slot,count:input.count,focus:input.source==='keyboard'&&input.count?0:-1};
        if(s.sub.focus===0)fx.push({do:'focus',target:'item',index:0});
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
      sub:state.open&&state.sub?{slot:state.sub.slot,count:state.sub.count,focus:state.sub.focus}:null,
    };
  }

  /* ------------------------------------------------- les icônes

     Vocabulaire de la palette Bare Hands et du rail de capture : grille de 24,
     trait de 1.5, bouts ronds. Écran, appareil photo et micro sont les dessins
     du rail de capture (`control_center_capture_rail.js` › ART), recopiés
     pour que la roue et le rail se lisent pareil pendant leur coexistence ;
     la copie du rail disparaît avec lui en Slice 04. */
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
${H} .tw-item[aria-disabled=true]{color:var(--muted,#7190a0);cursor:default}
${H} .tw-sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(forced-colors:active){
  ${H} .tw-anchor,${H} .tw-dot,${H} .tw-item,${H} .tw-label{border-color:CanvasText}
  ${H} .tw-wedge.is-focus .tw-dot,${H} .tw-item.is-focus{border-color:Highlight;color:Highlight}
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
  function icon(name){
    const art=ART[name];
    const svg=svgEl('svg',{viewBox:'0 0 24 24',width:22,height:22,fill:'none',stroke:'currentColor',
      'stroke-width':1.5,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'});
    for(const d of art.paths)svg.appendChild(svgEl('path',{d}));
    for(const [cx,cy,r] of art.dots)svg.appendChild(svgEl('circle',{cx,cy,r,fill:'currentColor',stroke:'none'}));
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
    const wedgesGeo=layoutWedges();
    let enabled=false,state=initialState(),built=null,leaveTimer=null,focusInside=false;
    /* Le dernier `pointerdown` vu sur la roue : un `click` Bare Hands est un
       `MouseEvent` sans `pointerId` ; la source se lit sur l'appui qui l'a
       précédé. */
    let lastDown={pointerId:null,t:0};
    /* Le dernier `pointerover` vu sur la roue (reprise QA P2) : un
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
      return {panel,menu,wedges,label,sub,anchor,items:[],itemSpecs:[]};
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
      built.wedges.forEach((b,i)=>{
        const w=view.wedges[i];
        b.classList.toggle('is-focus',w.focused);
        b.tabIndex=w.tabindex;
        b.setAttribute('aria-disabled',String(!actions.has(SLOTS[i].id)));
      });
      if(view.label){
        const geo=wedgesGeo[state.focus];
        built.label.textContent=view.label;
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

    function fillSub(slotIndex,items){
      built.sub.textContent='';
      const geo=layoutSubArc(items.length,wedgesGeo[slotIndex].midDeg);
      built.sub.setAttribute('aria-label',SLOTS[slotIndex].label);
      built.itemSpecs=items;
      built.items=items.map((spec,j)=>{
        const b=document.createElement('button');
        b.type='button';b.className='tw-item';
        b.setAttribute('role',typeof spec.checked==='boolean'?'menuitemradio':'menuitem');
        if(typeof spec.checked==='boolean')b.setAttribute('aria-checked',String(spec.checked));
        if(spec.disabled)b.setAttribute('aria-disabled','true');
        b.textContent=String(spec.label==null?'':spec.label);
        b.title=b.textContent;
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
        dispatch({type:'subOpen',slot:index,count:items.length,source});
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
          case 'item':{
            const spec=specs[fx.index];
            const slot=SLOTS[fx.slot];
            if(!spec||spec.disabled||typeof spec.onActivate!=='function'){
              log('info','tool_wheel.item_inert',{slot:slot.id,index:fx.index});
              break;
            }
            log('info','tool_wheel.item',{slot:slot.id,item:spec.id==null?fx.index:spec.id,source:fx.source});
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
    function onClick(event){
      const t=targetOf(event.target);
      if(t.target==='anchor'||t.target==='wedge'||t.target==='item')
        dispatch({type:'click',...t,detail:event.detail,source:clickSource(event)},event);
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

    function setEnabled(value){
      const next=value===true;
      if(next===enabled)return;
      enabled=next;
      if(enabled){
        if(!document.getElementById(DOM.styleId)){
          const style=document.createElement('style');
          style.id=DOM.styleId;style.textContent=STYLE;document.head.appendChild(style);
        }
        state=initialState();
        built=build();
        for(const [type,fn] of LISTENERS)host.addEventListener(type,fn);
        host.hidden=false;
        render();
      }else{
        if(state.open)dispatch({type:'close',reason:'disabled'});
        for(const [type,fn] of LISTENERS)host.removeEventListener(type,fn);
        host.textContent='';host.hidden=true;host.removeAttribute('data-open');built=null;
      }
      log('info','tool_wheel.enabled',{enabled});
    }

    /* Branche un emplacement. `action` : `{id, onActivate(ctx), onSecondary?(ctx)}`
       — `onSecondary` rend la liste du sous-arc (`[{id?, label, disabled?,
       checked?, onActivate?(ctx)}]`) ou une promesse de cette liste.
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

    root.JarvisToolWheel=Object.freeze({
      get enabled(){return enabled},
      set enabled(value){setEnabled(value)},
      register,
      open(){if(enabled)dispatch({type:'open'})},
      close(){if(enabled)dispatch({type:'close'})},
      isOpen:()=>state.open,
      snapshot:()=>({...state,sub:state.sub&&{...state.sub}}),
      SLOTS,GEOMETRY,
    });
    log('info','tool_wheel.installed',{host:DOM.hostId,enabled});
  }

  try{installToolWheel()}
  catch(error){
    console.error('[tool_wheel] tool_wheel.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
