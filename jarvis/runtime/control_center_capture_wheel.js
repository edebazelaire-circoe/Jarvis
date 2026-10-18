/* Vues de capture : la catégorie Capture de la roue d'outils (Capture
   d'écran, Enregistrer l'écran, Enregistrer l'audio dans son arbre),
   sous-menus des cibles, et indicateurs transitoires `#recIndicators`.

   Refonte de la roue (`jarvis-board-ui-wheel-dossier-refactor`, Slice 03) :
   les trois anciens secteurs du premier niveau sont devenus les trois
   entrées du sous-menu de **Capture**. Slice 04 de la même tâche
   (`docs/06-ui-visual-spec.md` › E) : les entrées disent ce qu'elles font
   (« Enregistrer l'écran », « Enregistrer l'audio »), un sous-menu ouvert se
   relit quand une capture change (`JarvisToolWheel.refresh`), et les
   indicateurs quittent le centre d'état du bas pour le **haut-gauche** :
   `● REC 0:12 ■` rouge pour l'écran, micro + onde + durée + ■ pour l'audio,
   côte à côte, seulement tant que Core dit une capture ouverte.

   Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 04 ; architecture
   résolue §5 (D6), D3, D4 (contraignantes). Contrat : `docs/capture.md` ›
   *Interface* et `docs/control-center-shell.md` › *Tool wheel*.

   **Aucune vérité ici.** Tout vient du modèle de vue publié par le
   contrôleur (`JarvisCaptureRail.subscribe`, `control_center_capture_rail.js`),
   lui-même relu sur Core. Ce module ne sonde rien, ne tient aucun état de
   capture et n'écrit que par le contrôleur (`act`, `start`, `screenshot`,
   `stop`, `targets`). Ce ne sont pas des outils Bare Hands (D15) : aucun
   `data-bh-tool`.

   - **Catégorie Capture** (`JarvisToolWheel.register({id:'capture', menu:true})`) :
     l'activer ouvre son sous-menu, une entrée par canal. Activation simple
     d'une entrée = la cible par défaut — Vidéo et Audio démarrent, ou
     arrêtent leur capture ouverte ; Capture d'écran prend l'écran principal.
     Vidéo (ou Audio) avec **deux** captures ouvertes ou plus : l'activation
     ouvre la liste d'arrêt (`menu` de l'entrée, relu à chaque clic). L'état
     de chaque canal est projeté sur son entrée (cochée quand Core dit une
     capture ouverte, attente, panne, « ? » quand le statut est perdu), et
     leur somme sur le secteur Capture (`setStatus` : `live`, ton, phrase).
   - **Activation secondaire d'une entrée** (clic droit, pincement pouce +
     majeur, `ContextMenu`, `Maj+F10`, flèche droite ; jamais d'appui long,
     D4) : le second niveau des captures ouvertes à arrêter, puis des cibles
     que Core sait **vraiment**
     prendre (`GET /api/captures/targets`). Une seule cible : une entrée
     unique qui le dit (« Écran principal — seule cible disponible »), jamais
     omise, jamais un faux choix.
   - **Indicateurs** `#recIndicators` (rang 40, zone haut-gauche depuis la
     Slice 04 de la refonte ; avant, à gauche des pastilles du centre
     d'état) : une puce par capture ouverte — point rouge + `REC` + durée +
     carré d'arrêt pour l'écran, micro + onde + durée + carré d'arrêt pour
     l'audio —, qui reste quand la roue se replie ; l'activer arrête
     **cette** capture par le même contrôleur que la roue (`C.stop`, vie
     privée d'abord, statut perdu compris). Une attente de démarrage, une
     capture d'écran en cours puis prise, et la note du dernier refus (sous
     les puces) s'y lisent aussi. Rien d'ouvert, rien à dire : l'hôte est
     caché.

   Deux blocs : le **modèle pur** (`wedgeStatusOf`, `chipsOf`,
   `targetItemsOf`, exécutés par node dans `tests/unit/test_capture_rail_js.py`)
   et le **bloc navigateur** (DOM, roue), éprouvé dans Chrome par
   `tests/unit/test_capture_wheel_browser.py`. */
(function(root){
  'use strict';

  /* La catégorie de la roue, puis ses entrées (ordre du sous-menu,
     docs/06-ui-visual-spec.md › E) -> commande du contrôleur. `slot` garde
     l'ancien nom du canal : c'est l'identifiant de l'entrée (`data-tw-item`). */
  const CATEGORY='capture';
  /* `short` : le nom du canal dans la phrase du secteur (« Écran : en cours »). */
  const WEDGES=Object.freeze([
    Object.freeze({slot:'screenshot',control:'screenshot',label:'Capture d’écran',short:'Capture d’écran',hint:'une image de l’écran'}),
    Object.freeze({slot:'video',control:'screen',label:'Enregistrer l’écran',short:'Écran',hint:'vidéo de l’écran'}),
    Object.freeze({slot:'audio',control:'audio',label:'Enregistrer l’audio',short:'Audio',hint:'le micro de Voice'}),
  ]);
  const TARGET_CHANNEL=Object.freeze({screen:'screen',screenshot:'screen',audio:'audio'});
  const DEFAULT_DEVICE='default';
  const DOM=Object.freeze({hostId:'recIndicators',styleId:'recIndicatorsStyle',chipsId:'recIndicatorsChips',
    noteId:'recIndicatorsNote',liveId:'recIndicatorsLive',detailPrefix:'recIndicatorsDetail-'});
  /* La confirmation d'une capture d'écran reste (comme le contrôleur). */
  const NAMES=Object.freeze({
    screen:'Enregistrement d’écran',audio:'Enregistrement audio',screenshot:'Capture d’écran',
  });

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);

  /* Le nom court d'un appareil, quand ce n'est pas la cible par défaut :
     `display2` -> « écran 2 », un jeton d'entrée audio tel quel (raccourci). */
  function deviceTag(device){
    const d=String(device||DEFAULT_DEVICE);
    if(d===DEFAULT_DEVICE)return '';
    const screen=/^display(\d+)$/.exec(d);
    if(screen)return `écran ${screen[1]}`;
    return d.length>18?`${d.slice(0,17)}…`:d;
  }

  /* ------------------------------------------------- le secteur

     Ce que le contrôleur dit d'un canal, projeté sur son secteur : jamais un
     compteur dans le texte (il rejoint le nom accessible, qui ne doit pas
     changer chaque seconde). */
  function wedgeStatusOf(control){
    if(!isObject(control))return null;
    if(control.kind==='shot'){
      switch(control.state){
        case 'busy':return {tone:'wait',text:'capture en cours…'};
        case 'error':return {tone:'error',text:`échec${control.code?` (${control.code})`:''}`};
        case 'unknown':return {tone:'unknown',text:'état inconnu, Jarvis injoignable'};
        case 'done':return {text:'enregistrée'};
        default:return null;
      }
    }
    const open=(control.captures||[]).filter(c=>c.state!=='unknown').length;
    const more=open>1?`${open} en cours`:'en cours';
    switch(control.state){
      case 'starting':return {tone:'wait',text:'démarrage…',checked:!!control.pressed};
      /* Coché = Core dit une capture ouverte (`pressed`) : un arrêt en attente
         pendant la perte du statut ne l'est plus (QA S04 P6). */
      case 'stopping':return {tone:'wait',text:'arrêt…',checked:!!control.pressed};
      case 'stuck':return {tone:'error',text:`arrêt bloqué (${control.code||'inconnu'})`,checked:true};
      case 'active':return control.pendingStart
        ?{tone:'wait',text:`${more}, démarrage…`,checked:true}:{text:more,checked:true};
      case 'error':return {tone:'error',text:`échec${control.code?` (${control.code})`:''}`,checked:false};
      case 'unknown':return {tone:'unknown',
        text:control.action==='stop'?'état inconnu — arrêt possible':'état inconnu, Jarvis injoignable',checked:false};
      default:return {checked:false};
    }
  }

  /* ------------------------------------------------- la catégorie

     `byChannel` : `{screenshot, video, audio}` -> ce que `wedgeStatusOf` en
     dit (ou `null`). Le secteur Capture porte leur somme : `live` quand un
     enregistrement est ouvert, le ton le plus grave (panne, inconnu,
     attente), et une phrase par canal qui a quelque chose à dire. */
  function categoryStatusOf(byChannel){
    const list=WEDGES.map(w=>({w,st:isObject(byChannel)?byChannel[w.slot]:null})).filter(x=>isObject(x.st));
    const tone=['error','unknown','wait'].find(tn=>list.some(x=>x.st.tone===tn))||null;
    const live=list.some(x=>x.st.checked===true);
    const text=list.filter(x=>x.st.text).map(x=>`${x.w.short} : ${x.st.text}`).join(' · ');
    if(!tone&&!live&&!text)return null;
    return {tone,live,text};
  }

  /* L'entrée d'un canal dans le sous-menu de Capture, sans action (le bloc
     navigateur la branche). Vidéo et Audio sont des cases à cocher
     (`toggle`) : cochées quand Core dit une capture ouverte. */
  function channelItemOf(w,status){
    const st=isObject(status)?status:null;
    const item={id:w.slot,icon:w.slot,label:w.label,note:st&&st.text?st.text:w.hint};
    if(w.control!=='screenshot'){item.toggle=true;item.checked=!!(st&&st.checked)}
    if(st&&st.tone==='error')item.tone='error';
    else if(st&&st.tone==='wait')item.tone='wait';
    else if(st&&st.checked)item.tone='busy';
    return item;
  }

  /* ------------------------------------------------- les indicateurs

     Une puce par capture ouverte (la plus ancienne d'abord, écran puis
     audio), une puce d'attente pour un démarrage dont Core ne montre pas
     encore la ligne, une puce pour la capture d'écran en cours ou juste
     prise. `name` est stable (le nom accessible), `detail` porte la durée
     (la description), `timer` est ce que l'œil lit. Une puce d'écran montre
     « REC » : son nom commence par ce mot, pour l'Accès vocal (« cliquer REC »)
     et WCAG 2.5.3 (orbital-ui QA S09 P6). */
  const recName=(channel,name)=>channel==='screen'?`REC — ${name.charAt(0).toLowerCase()}${name.slice(1)}`:name;
  function chipsOf(view){
    const out=[];
    if(!isObject(view)||!isObject(view.controls))return out;
    for(const channel of ['screen','audio']){
      const control=view.controls[channel];
      if(!isObject(control))continue;
      const captures=control.captures||[];
      for(const c of captures){
        const tag=deviceTag(c.device);
        out.push(Object.freeze({key:c.captureId,channel,captureId:c.captureId,device:c.device,tag,state:c.state,
          action:c.action,timer:c.timer,detail:c.detail,code:c.code||null,
          name:recName(channel,tag?`${c.label} (${tag})`:c.label)}));
      }
      const pend=control.pendingStart;
      if(pend&&!captures.some(c=>c.state==='starting')){
        const tag=deviceTag(pend.device);
        out.push(Object.freeze({key:`start:${channel}`,channel,captureId:null,device:pend.device,tag,
          state:'starting',action:null,timer:`${pend.waited} s`,detail:`attente depuis ${pend.waited} s`,code:null,
          name:recName(channel,`${NAMES[channel]} : démarrage…${tag?` (${tag})`:''}`)}));
      }
    }
    const shot=view.controls.screenshot;
    if(isObject(shot)&&(shot.state==='busy'||shot.state==='done')){
      out.push(Object.freeze({key:'shot',channel:'screenshot',captureId:null,device:shot.device||DEFAULT_DEVICE,
        tag:'',state:shot.state,action:null,timer:shot.state==='busy'?shot.timer:'',detail:shot.detail,code:null,
        name:shot.state==='busy'?'Capture d’écran en cours…':'Capture d’écran enregistrée'}));
    }
    return out;
  }

  /* ------------------------------------------------- le sous-arc des cibles

     `control` : le modèle de vue de la commande ; `listing` : la réponse de
     Core pour son canal (`{available, devices, code?}`) ou `null` ; `error` :
     l'échec de la lecture des cibles ; `reachable` : le statut tient.
     Rend des entrées **sans** action (le bloc navigateur les branche) :
     `{id, kind:'stop'|'target'|'none', captureId?, device?, label, note?,
     detail?, disabled?, tone?, icon}`. */
  function targetItemsOf(controlId,control,listing,error,reachable,refusal){
    const items=[];
    const say=typeof refusal==='function'?refusal:(code=>String(code||'cause inconnue'));
    const channel=TARGET_CHANNEL[controlId];
    const recording=new Set();
    if(controlId!=='screenshot'&&isObject(control)){
      for(const c of control.captures||[]){
        if(c.state==='starting'||c.state==='active'||c.state==='stopping'||c.state==='stuck'||c.state==='unknown')
          recording.add(String(c.device||DEFAULT_DEVICE));
        const tag=deviceTag(c.device);
        const what=controlId==='screen'?(tag||'écran principal'):(tag||'micro de Voice');
        items.push({id:`stop:${c.captureId}`,kind:'stop',captureId:c.captureId,device:c.device,icon:'stop',
          label:c.state==='stuck'?`Réessayer l’arrêt — ${what}`:`Arrêter — ${what}`,note:c.timer||undefined,
          detail:c.label+(c.detail?`, ${c.detail}`:''),disabled:c.action!=='stop'||undefined,
          tone:c.state==='stuck'?'error':c.state==='stopping'?'wait':undefined});
      }
    }
    const icon=controlId==='screen'?'video':controlId;
    if(error){
      const code=error.code||null;
      items.push({id:'targets:error',kind:'none',icon,label:'Cibles illisibles',note:say(code),
        detail:`${say(code)}${code?` (${code})`:''}`,disabled:true,tone:'error'});
      return items;
    }
    if(!isObject(listing)){
      items.push({id:'targets:none',kind:'none',icon,label:'Cibles illisibles',note:'réponse vide',disabled:true,tone:'error'});
      return items;
    }
    if(listing.available===false){
      items.push({id:'targets:unavailable',kind:'none',icon,label:'Aucune cible',note:say(listing.code),
        detail:`${say(listing.code)}${listing.code?` (${listing.code})`:''}`,disabled:true,tone:'error'});
      return items;
    }
    const devices=(Array.isArray(listing.devices)?listing.devices:[]).filter(d=>isObject(d)&&typeof d.token==='string');
    const only=devices.length===1;
    for(const d of devices){
      const busy=controlId!=='screenshot'&&recording.has(d.token);
      const size=Number.isFinite(d.width)&&Number.isFinite(d.height)?`${d.width}×${d.height}`:'';
      let label=String(d.label||d.token),note=size||undefined,detail,disabled;
      if(only)label=`${label} — seule cible disponible`;
      if(only&&listing.code)detail=`${say(listing.code)} (${listing.code}) : seule la cible par défaut est proposée`;
      /* La phrase longue commence par la note montrée (« en cours ») : le nom commence par ce que l'entrée montre
         (WCAG 2.5.3, orbital-ui QA S09 P6). */
      if(busy){disabled=true;note='en cours';detail='en cours d’enregistrement sur cette cible'}
      else if(!reachable){disabled=true;detail='état des captures inconnu, Jarvis injoignable : rien ne démarre'}
      items.push({id:`target:${d.token}`,kind:'target',device:d.token,icon,label,note,detail,disabled});
    }
    if(!devices.length)
      items.push({id:'targets:none',kind:'none',icon,label:'Aucune cible',note:'liste vide',disabled:true,tone:'error'});
    return items;
  }

  const api=Object.freeze({CATEGORY,WEDGES,TARGET_CHANNEL,DOM,deviceTag,wedgeStatusOf,categoryStatusOf,channelItemOf,
    chipsOf,targetItemsOf});
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- la feuille

     Puces de verre sombre, trait fin, chiffres tabulaires, posées en haut à
     gauche (Slice 04 de la refonte, `docs/06-ui-visual-spec.md` › E). L'écran
     qui enregistre est **rouge** (`--danger`) : point qui respire, `REC`, la
     durée, puis le carré d'arrêt dans sa case ; l'audio est **ambre**
     (`--sem-alert`) : micro, une onde de trois barres, la durée, le carré.
     Une attente balaie ; une panne porte « ! » ; un état inconnu « ? » et un
     trait pointillé — jamais la couleur seule. Les puces vont côte à côte et
     passent à la ligne vers le bas ; la note d'un refus s'ouvre sous elles.
     Aucun `z-index` ici : le rang de l'hôte (40) vit dans la page et au
     registre. Mouvement réduit : rien ne bouge, les chiffres continuent. */
  const H='#'+DOM.hostId;
  const STYLE=`
${H}{font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--text,#d8edf7)}
${H} [hidden]{display:none!important}
${H} .ri-chips{display:flex;flex-wrap:wrap;justify-content:flex-start;gap:6px}
${H} .ri-chip{--ri-ink:var(--sem-alert,#ff9f43);position:relative;display:inline-flex;align-items:center;gap:7px;
  height:34px;margin:0;padding:0 10px 0 9px;border:1px solid color-mix(in srgb,var(--ri-ink) 55%,transparent);
  border-radius:var(--shell-radius,12px);background:var(--shell-glass-strong,rgba(4,10,15,.8));
  backdrop-filter:blur(12px);color:var(--ri-ink);font:inherit;letter-spacing:.06em;cursor:pointer;
  transition:border-color var(--shell-dur-fast,120ms) var(--shell-ease,ease),background var(--shell-dur-fast,120ms) var(--shell-ease,ease)}
${H} .ri-chip:hover:not([aria-disabled=true]){border-color:var(--ri-ink);background:color-mix(in srgb,var(--ri-ink) 12%,var(--shell-glass-strong,rgba(4,10,15,.8)))}
${H} .ri-chip:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:2px}
${H} .ri-chip[aria-disabled=true]{cursor:default}
/* L'écran qui enregistre : rouge, comme le voyant d'une caméra. */
${H} .ri-chip[data-ri-channel=screen]{--ri-ink:var(--danger,#ff5f6d)}
${H} .ri-chip[data-ri-state=starting],${H} .ri-chip[data-ri-state=stopping],${H} .ri-chip[data-ri-state=busy]{--ri-ink:var(--sem-working,#4da3ff);cursor:progress}
${H} .ri-chip[data-ri-state=stuck]{--ri-ink:var(--sem-problem,#ff6a4d)}
${H} .ri-chip[data-ri-state=done]{--ri-ink:var(--sem-done,#68e0a0)}
${H} .ri-chip[data-ri-state=unknown]{--ri-ink:var(--muted,#7190a0);border-style:dashed}
${H} .ri-chip svg{flex:none;width:16px;height:16px}
${H} .ri-dot{flex:none;width:9px;height:9px;border-radius:50%;background:var(--ri-ink);
  animation:riBreathe 2.4s ease-in-out infinite}
@keyframes riBreathe{0%,100%{opacity:.45}50%{opacity:1}}
${H} .ri-tag{font-weight:700;letter-spacing:.14em}
${H} .ri-time{font-variant-numeric:tabular-nums;color:var(--text,#d8edf7)}
${H} .ri-dev{color:var(--muted,#7190a0);font-size:11px}
${H} .ri-mark{flex:none;display:grid;place-items:center;width:15px;height:15px;border-radius:50%;
  font-size:10px;font-weight:700;line-height:1;color:#05080b;background:var(--ri-ink)}
/* La marque d'arrêt : ce qu'activer la puce fait, un carré plein dans sa case, séparé de la durée. */
${H} .ri-stop{flex:none;position:relative;width:20px;height:20px;margin-left:2px;border-radius:6px;
  border:1px solid color-mix(in srgb,var(--ri-ink) 55%,transparent);background:color-mix(in srgb,var(--ri-ink) 14%,transparent)}
${H} .ri-stop::after{content:"";position:absolute;left:50%;top:50%;width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:1.5px;background:var(--ri-ink)}
${H} .ri-chip:hover:not([aria-disabled=true]) .ri-stop{background:color-mix(in srgb,var(--ri-ink) 28%,transparent)}
${H} .ri-chip[data-ri-state=stopping] .ri-stop{opacity:.45}
/* L'onde de l'audio : trois barres qui respirent tant que Core dit l'enregistrement ouvert. */
${H} .ri-wave{flex:none;display:inline-flex;align-items:center;gap:2px;height:14px}
${H} .ri-wave i{display:block;width:2px;height:100%;border-radius:1px;background:var(--ri-ink);transform-origin:50% 50%;
  animation:riWave 1.1s ease-in-out infinite}
${H} .ri-wave i:nth-child(2){animation-delay:-.35s}
${H} .ri-wave i:nth-child(3){animation-delay:-.7s}
@keyframes riWave{0%,100%{transform:scaleY(.35)}50%{transform:scaleY(1)}}
${H} .ri-wait{position:absolute;left:9px;right:9px;bottom:3px;height:2px;border-radius:2px;overflow:hidden;
  background:color-mix(in srgb,var(--ri-ink) 22%,transparent)}
${H} .ri-wait::after{content:"";position:absolute;top:0;bottom:0;left:0;width:42%;border-radius:2px;
  background:var(--ri-ink);animation:riSweep 1.25s ease-in-out infinite}
@keyframes riSweep{from{transform:translateX(-115%)}to{transform:translateX(255%)}}
/* La note : la phrase d'un refus, posée sous les puces, alignée sur leur bord gauche (Slice 04). */
${H} .ri-note{position:absolute;left:0;top:calc(100% + 8px);
  width:max-content;max-width:min(420px,calc(100vw - 2 * var(--shell-gutter,18px)));margin:0;
  padding:8px 32px 8px 11px;border:1px solid var(--shell-stroke-active,rgba(110,231,255,.4));border-radius:10px;
  background:var(--panel,rgba(6,12,18,.94));color:var(--text,#d8edf7);font-size:11.5px;line-height:1.45;
  box-shadow:0 10px 28px rgba(0,0,0,.45)}
${H} .ri-note[hidden]{display:none}
${H} .ri-note[data-ri-tone=bad]{border-color:color-mix(in srgb,var(--sem-problem,#ff6a4d) 60%,transparent);background:rgba(35,7,12,.94)}
${H} .ri-note[data-ri-tone=warn]{border-color:color-mix(in srgb,var(--sem-alert,#ff9f43) 60%,transparent);background:rgba(38,23,5,.94)}
${H} .ri-note-close{position:absolute;right:5px;top:5px;width:22px;height:22px;display:grid;place-items:center;padding:0;
  border:1px solid transparent;border-radius:6px;background:transparent;color:var(--muted,#7190a0);font:inherit;font-size:13px;cursor:pointer}
${H} .ri-note-close:hover{color:var(--text,#d8edf7);border-color:var(--line,#183343)}
${H} .ri-note-close:focus-visible{outline:2px solid var(--shell-focus,#6ee7ff);outline-offset:1px}
${H} .ri-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(prefers-reduced-motion:reduce){
  ${H} .ri-dot{animation:none;opacity:1}
  ${H} .ri-wave i{animation:none;transform:scaleY(.7)}
  ${H} .ri-wait::after{animation:none;width:100%;opacity:.6}
  ${H} .ri-chip{transition:none}
}
@media(forced-colors:active){
  ${H} .ri-chip{border:1px solid ButtonText;color:ButtonText;background:ButtonFace}
  ${H} .ri-chip[data-ri-state=unknown]{border-style:dashed}
  ${H} .ri-chip[data-ri-state=active]{border:2px solid Highlight}
  ${H} .ri-dot,${H} .ri-stop::after,${H} .ri-mark,${H} .ri-wave i{forced-color-adjust:none;background:Highlight;color:HighlightText}
  ${H} .ri-stop{border-color:ButtonText;background:ButtonFace}
  ${H} .ri-time,${H} .ri-dev{color:ButtonText}
  ${H} .ri-note{border-color:CanvasText}
}`;

  /* ------------------------------------------------- le bloc navigateur */

  const SVG_NS='http://www.w3.org/2000/svg';
  const log=(level,key,data)=>{
    const line=`[capture] ${key} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);
    else if(level==='warn')console.warn(line);
    else console.info(line);
  };

  function installCaptureViews(){
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error(`JarvisCaptureViews : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'capture_views_host_missing'});
    const C=window.JarvisCaptureRail,W=window.JarvisToolWheel,M=window.JarvisCaptureRailModule;
    const missing=[!C&&'JarvisCaptureRail',!W&&'JarvisToolWheel',!M&&'JarvisCaptureRailModule'].filter(Boolean);
    if(missing.length)
      throw Object.assign(new Error(`JarvisCaptureViews : ${missing.join(', ')} absent`),{code:'capture_views_dependency_missing'});
    const refusal=code=>M.refusalText(code,'',null);

    if(!document.getElementById(DOM.styleId)){
      const style=document.createElement('style');style.id=DOM.styleId;style.textContent=STYLE;
      document.head.appendChild(style);
    }
    host.textContent='';
    host.setAttribute('role','region');host.setAttribute('aria-label','Enregistrements et captures');
    const noteBox=document.createElement('div');
    noteBox.id=DOM.noteId;noteBox.className='ri-note';noteBox.hidden=true;
    const noteText=document.createElement('span');
    const close=document.createElement('button');
    close.type='button';close.className='ri-note-close';close.textContent='×';close.setAttribute('aria-label','Fermer le message');
    close.addEventListener('click',()=>{C.dismiss();focusAfterRemoval(null)});
    noteBox.append(noteText,close);
    const strip=document.createElement('div');
    strip.id=DOM.chipsId;strip.className='ri-chips';strip.setAttribute('role','group');
    strip.setAttribute('aria-label','Enregistrements en cours');
    const live=document.createElement('div');
    live.id=DOM.liveId;live.className='ri-sr';live.setAttribute('role','status');live.setAttribute('aria-live','polite');
    host.append(noteBox,strip,live);
    host.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&C.note()){event.preventDefault();C.dismiss();focusAfterRemoval(null)}
    });

    const chips=new Map();  // clé -> {el, parts, chip}
    let seq=0,lastAnnounce=-1;

    function icon(name){
      const art=W.ART&&W.ART[name];
      if(!art)return null;
      const svg=document.createElementNS(SVG_NS,'svg');
      for(const [k,v] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':1.6,
        'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(k,String(v));
      svg.setAttribute('data-ri-glyph',name);
      for(const d of art.paths){const p=document.createElementNS(SVG_NS,'path');p.setAttribute('d',d);svg.appendChild(p)}
      for(const [cx,cy,r] of art.dots||[]){
        const c=document.createElementNS(SVG_NS,'circle');c.setAttribute('cx',cx);c.setAttribute('cy',cy);c.setAttribute('r',r);
        c.setAttribute('fill','currentColor');c.setAttribute('stroke','none');svg.appendChild(c);
      }
      return svg;
    }

    /* Une puce disparue qui avait le focus : il passe à la suivante, sinon à
       l'ancre de la roue — jamais perdu sur `body`. */
    function focusAfterRemoval(index){
      if(!host.contains(document.activeElement)&&document.activeElement!==document.body)return;
      const list=[...strip.querySelectorAll('.ri-chip')];
      const next=index===null?list[0]:list[Math.min(index,list.length-1)];
      if(next){try{next.focus({preventScroll:true})}catch(_){next.focus()}}
      else W.focusAnchor();
    }

    function build(chip){
      const el=document.createElement('button');
      el.type='button';el.className='ri-chip';
      el.setAttribute('data-ri-key',chip.key);el.setAttribute('data-ri-channel',chip.channel);
      const detail=document.createElement('span');detail.className='ri-sr';detail.id=`${DOM.detailPrefix}${++seq}`;
      detail.setAttribute('aria-hidden','true');
      const parts={lead:document.createElement('span'),tag:document.createElement('span'),wave:document.createElement('span'),
        time:document.createElement('span'),dev:document.createElement('span'),mark:document.createElement('span'),
        stop:document.createElement('span'),wait:document.createElement('span'),detail,glyph:null};
      parts.lead.style.display='contents';
      parts.tag.className='ri-tag';parts.time.className='ri-time';parts.dev.className='ri-dev';
      parts.mark.className='ri-mark';parts.stop.className='ri-stop';parts.wait.className='ri-wait';
      parts.wave.className='ri-wave';for(let i=0;i<3;i+=1)parts.wave.appendChild(document.createElement('i'));
      for(const k of ['tag','wave','time','dev','mark','stop','wait'])parts[k].setAttribute('aria-hidden','true');
      el.append(parts.lead,parts.tag,parts.wave,parts.time,parts.dev,parts.mark,parts.stop,parts.wait,detail);
      el.addEventListener('click',()=>activateChip(el.getAttribute('data-ri-key')));
      return {el,parts,chip};
    }

    function activateChip(key){
      const entry=chips.get(key);
      if(!entry)return;
      const chip=entry.chip;
      if(chip.action==='stop'&&chip.captureId){
        log('info','capture_views.chip_stop',{channel:chip.channel,capture_id:chip.captureId,state:chip.state});
        C.stop(chip.captureId);
      }else if(!C.view().reachable)C.wake();
    }

    function paintChip(entry,chip){
      const {el,parts}=entry;
      entry.chip=chip;
      el.setAttribute('data-ri-state',chip.state);
      el.setAttribute('aria-disabled',chip.action==='stop'?'false':'true');
      /* Nom stable (un nom qui change chaque seconde serait réannoncé) ; la
         durée passe par la description. */
      if(el.getAttribute('aria-label')!==chip.name){el.setAttribute('aria-label',chip.name);el.title=chip.name}
      parts.detail.textContent=chip.detail||'';
      if(chip.detail)el.setAttribute('aria-describedby',parts.detail.id);else el.removeAttribute('aria-describedby');
      const glyph=chip.channel==='screen'?'':chip.channel==='audio'?'audio':chip.state==='done'?'done':'screenshot';
      if(glyph!==parts.glyph){
        parts.lead.textContent='';
        if(glyph){const svg=icon(glyph);if(svg)parts.lead.appendChild(svg)}
        else{const dot=document.createElement('span');dot.className='ri-dot';dot.setAttribute('aria-hidden','true');parts.lead.appendChild(dot)}
        parts.glyph=glyph;
      }
      parts.tag.textContent=chip.channel==='screen'?'REC':'';
      parts.tag.hidden=chip.channel!=='screen';
      /* L'onde ne bat que pour un enregistrement audio que Core dit ouvert. */
      parts.wave.hidden=!(chip.channel==='audio'&&chip.state==='active');
      parts.time.textContent=chip.state==='done'?'enregistrée':chip.timer||'';
      parts.time.hidden=!parts.time.textContent;
      parts.dev.textContent=chip.tag||'';parts.dev.hidden=!chip.tag;
      const mark=chip.state==='stuck'?'!':chip.state==='unknown'?'?':'';
      parts.mark.textContent=mark;parts.mark.hidden=!mark;
      parts.stop.hidden=!(chip.action==='stop'||chip.state==='stopping');
      parts.wait.hidden=!(chip.state==='starting'||chip.state==='stopping'||chip.state==='busy');
    }

    function renderChips(view){
      const list=chipsOf(view);
      const wanted=new Set(list.map(c=>c.key));
      const before=[...strip.children];
      let lostFocusAt=null;
      for(const [key,entry] of chips){
        if(wanted.has(key))continue;
        if(entry.el.contains(document.activeElement))lostFocusAt=before.indexOf(entry.el);
        entry.el.remove();chips.delete(key);
      }
      list.forEach((chip,index)=>{
        let entry=chips.get(chip.key);
        if(!entry){entry=build(chip);chips.set(chip.key,entry)}
        paintChip(entry,chip);
        if(strip.children[index]!==entry.el)strip.insertBefore(entry.el,strip.children[index]||null);
      });
      if(lostFocusAt!==null)focusAfterRemoval(lostFocusAt);
      return list.length;
    }

    function renderNote(view){
      const note=view.note;
      if(note){
        noteBox.hidden=false;noteBox.setAttribute('data-ri-tone',note.tone);
        if(noteText.textContent!==note.text)noteText.textContent=note.text;
      }else{noteBox.hidden=true;noteText.textContent=''}
      return !!note;
    }

    /* Ce que chaque canal dit, gardé pour le sous-menu ; leur somme sur le
       secteur Capture. Avant la première lecture, rien n'est su : aucun état
       projeté. */
    let byChannel={};
    function channelStatuses(view){
      const out={};
      for(const w of WEDGES)out[w.slot]=view.settled?wedgeStatusOf(view.controls[w.control]):null;
      return out;
    }
    function paintWedges(view){
      byChannel=channelStatuses(view);
      try{W.setStatus(CATEGORY,categoryStatusOf(byChannel))}
      catch(error){log('error','capture_views.wedge_paint_failed',{slot:CATEGORY,error:String(error&&error.message||error)})}
    }

    function render(view){
      const count=renderChips(view);
      const noted=renderNote(view);
      host.hidden=!(count||noted);
      if(view.announce&&view.announce.seq!==lastAnnounce){
        lastAnnounce=view.announce.seq;live.textContent=view.announce.text||'';
      }
      paintWedges(view);
      /* Le sous-menu de Capture ouvert se relit (une capture démarrée
         ailleurs, un arrêt confirmé) ; sans changement, rien n'est redessiné. */
      if(typeof W.refresh==='function'){
        try{W.refresh(CATEGORY)}
        catch(error){log('error','capture_views.refresh_failed',{error:String(error&&error.message||error)})}
      }
    }

    /* ---- les secteurs ---- */

    const stoppable=control=>(C.view().controls[control].captures||[]).filter(c=>c.action==='stop');

    function activate(w,ctx){
      log('info','capture_views.activate',{slot:w.slot,source:ctx&&ctx.source||null});
      return C.act(w.control);
    }

    async function secondary(w,ctx){
      const view=C.view();
      const control=view.controls[w.control];
      let listing=null,error=null;
      try{
        const all=await C.targets();
        listing=isObject(all)?all[TARGET_CHANNEL[w.control]]:null;
      }catch(caught){error=caught}
      const now=C.view();
      const specs=targetItemsOf(w.control,now.controls[w.control]||control,listing,error,now.reachable,refusal);
      log('info','capture_views.targets_offered',{slot:w.slot,source:ctx&&ctx.source||null,
        items:specs.map(s=>s.kind+(s.disabled?'-':'')).join(','),error:error&&error.code||null});
      return specs.map(spec=>({...spec,onActivate:spec.disabled?undefined:item=>{
        if(spec.kind==='stop'){
          log('info','capture_views.stop_chosen',{slot:w.slot,capture_id:spec.captureId,source:item&&item.source||null});
          return C.stop(spec.captureId);
        }
        log('info','capture_views.target_chosen',{slot:w.slot,device:spec.device,source:item&&item.source||null});
        return w.control==='screenshot'?C.screenshot({device:spec.device}):C.start(w.control,{device:spec.device});
      }}));
    }

    /* La catégorie : son sous-menu relit l'état des canaux à chaque
       ouverture, et à chaque peinture du contrôleur tant qu'il est ouvert
       (`render` -> `W.refresh`). */
    W.register({id:CATEGORY,menu:true,
      onActivate:()=>{/* `menu:true` : l'activation ouvre le sous-menu. */},
      onSecondary:ctx=>{
        const now=channelStatuses(C.view());
        if(!ctx||ctx.source!=='refresh')log('info','capture_views.menu',{source:ctx&&ctx.source||null});
        return WEDGES.map(w=>({...channelItemOf(w,now[w.slot]),
          /* Deux captures ouvertes ou plus : l'activation simple ne choisit pas
             laquelle arrêter, elle ouvre la liste. */
          menu:w.control==='screenshot'?false:()=>stoppable(w.control).length>=2,
          onActivate:item=>activate(w,item),
          onSecondary:item=>secondary(w,item)}));
      }});

    C.subscribe(render);
    window.JarvisCaptureViews=Object.freeze({chips:()=>chipsOf(C.view()),render:()=>render(C.view()),
      /* Ce que chaque canal projette (relevé des tests et des preuves). */
      channels:()=>channelStatuses(C.view())});
    log('info','capture_views.installed',{host:DOM.hostId,category:CATEGORY,items:WEDGES.map(w=>w.slot)});
  }

  try{installCaptureViews()}
  catch(error){
    console.error('[capture] capture_views.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
