/* Barehands en mode test : pointeur à mains nues pour le Control Center.

   Réimplémentation native et réduite de l'idée Barehands (aucun code upstream
   AGPL repris) : la webcam suit les mains avec MediaPipe Hand Landmarker, servi
   localement par le Control Center (/barehands/assets/…), sans service cloud.
   Chaque main détectée affiche un jeton qui suit l'index ; un pincement
   pouce-index clique sous le jeton.

   Deux parties, comme `control_center_work.js` :
   - `JarvisBarehandsCore`, logique pure (géométrie, pincement, cycle de vie
     avec dépendances injectées), exécutée telle quelle par les tests (node) ;
   - un bloc navigateur qui branche la caméra, la surimpression, les clics et
     l'onglet « Expérimental » des réglages. Les tests node ne l'exécutent pas. */

const JarvisBarehandsCore=(function(){
  /* Indices MediaPipe utiles : poignet, bout du pouce, bout de l'index, base du majeur. */
  const LM=Object.freeze({WRIST:0,THUMB_TIP:4,INDEX_TIP:8,MIDDLE_MCP:9});
  const DEFAULTS=Object.freeze({
    pressRatio:.28,     // pincé : pouce-index sous 28 % de la taille de la paume
    releaseRatio:.42,   // relâché au-dessus de 42 % (hystérésis : pas de clignotement)
    pressFrames:2,      // images consécutives pincées avant de valider
    cooldownMs:450,     // anti-rebond : délai minimal entre deux clics d'une même main
    margin:.12,         // bord de l'image ignoré : l'écran entier reste atteignable
    mirror:true,        // caméra frontale : l'image est vue en miroir
    smoothing:.45,      // lissage exponentiel du jeton (1 = aucun)
    lostGraceMs:250,    // une main perdue garde son état ce temps-là
  });
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));

  function options(overrides){
    const o={...DEFAULTS,...(overrides||{})};
    if(!(o.pressRatio>0&&o.pressRatio<o.releaseRatio))throw new RangeError('pressRatio doit être positif et inférieur à releaseRatio');
    o.margin=clamp(Number(o.margin)||0,0,.45);
    o.smoothing=clamp(Number(o.smoothing)||1,.01,1);
    o.pressFrames=Math.max(1,Math.round(o.pressFrames));
    return o;
  }

  function distance(a,b,aspect){
    return Math.hypot((a.x-b.x)*aspect,a.y-b.y);
  }

  /* Écart pouce-index rapporté à la paume (poignet → base du majeur) : même
     seuil quelle que soit la distance à la caméra. `aspect` = largeur/hauteur
     de l'image, les coordonnées MediaPipe étant normalisées par axe. */
  function pinchRatio(landmarks,aspect){
    if(!Array.isArray(landmarks)||landmarks.length<=LM.MIDDLE_MCP)return null;
    const k=Number(aspect)>0?Number(aspect):1;
    const palm=distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k);
    if(!(palm>1e-6))return null;
    return distance(landmarks[LM.THUMB_TIP],landmarks[LM.INDEX_TIP],k)/palm;
  }

  /* Point normalisé de la caméra → pixels de la fenêtre (miroir, marge, bornes). */
  function toScreen(point,viewport,overrides){
    const o=options(overrides);
    let x=clamp(Number(point&&point.x)||0,0,1),y=clamp(Number(point&&point.y)||0,0,1);
    if(o.mirror)x=1-x;
    const span=1-2*o.margin;
    return {
      x:clamp((x-o.margin)/span,0,1)*Math.max(0,viewport.width),
      y:clamp((y-o.margin)/span,0,1)*Math.max(0,viewport.height),
    };
  }

  function smooth(previous,next,alpha){
    if(!previous)return {x:next.x,y:next.y};
    return {x:previous.x+(next.x-previous.x)*alpha,y:previous.y+(next.y-previous.y)*alpha};
  }

  /* Pincement d'une main. États : open → pinching (en cours) → pressed.
     Le clic part une seule fois, au passage en pressed ; il faut relâcher
     au-delà de releaseRatio pour pouvoir recliquer, et cooldownMs absorbe les
     rebonds d'un relâchement bref. */
  function createPinchDetector(overrides){
    const o=options(overrides);
    let state='open',frames=0,lastClickAt=-Infinity;
    return {
      update(ratio,now){
        let click=false;
        if(ratio===null||ratio===undefined||!isFinite(ratio)){
          state='open';frames=0;
          return {state,progress:0,click};
        }
        if(state==='pressed'){
          if(ratio>o.releaseRatio){state='open';frames=0}
        }else if(ratio<=o.pressRatio){
          frames+=1;
          if(frames>=o.pressFrames){
            state='pressed';frames=0;
            if(now-lastClickAt>=o.cooldownMs){click=true;lastClickAt=now}
          }else state='pinching';
        }else if(ratio<o.releaseRatio){state='pinching';frames=0}
        else{state='open';frames=0}
        const progress=state==='pressed'?1:state==='open'?0:
          clamp((o.releaseRatio-ratio)/(o.releaseRatio-o.pressRatio),0,1);
        return {state,progress,click};
      },
      reset(){state='open';frames=0},
      state(){return state},
    };
  }

  function handKey(result,index){
    const groups=(result&&(result.handedness||result.handednesses))||[];
    const first=Array.isArray(groups[index])?groups[index][0]:null;
    return first&&first.categoryName?String(first.categoryName).toLowerCase():`hand-${index}`;
  }

  /* Résultat MediaPipe → jetons à afficher et clics à rejouer. Pendant un
     pincement, le jeton se fige là où il était quand les doigts ont commencé
     à se rapprocher : le clic tombe sur ce qui était visé, pas à côté. */
  function createHandTracker(overrides){
    const o=options(overrides);
    const hands=new Map();
    return {
      update(result,frame){
        const tokens=[],clicks=[],seen=new Set();
        const list=(result&&result.landmarks)||[];
        list.forEach((landmarks,index)=>{
          if(!Array.isArray(landmarks)||landmarks.length<=LM.INDEX_TIP)return;
          let id=handKey(result,index);
          if(seen.has(id))id=`${id}-${index}`;
          seen.add(id);
          let hand=hands.get(id);
          if(!hand){hand={detector:createPinchDetector(o),point:null,anchor:null,lastSeen:frame.now};hands.set(id,hand)}
          hand.lastSeen=frame.now;
          hand.point=smooth(hand.point,toScreen(landmarks[LM.INDEX_TIP],frame.viewport,o),o.smoothing);
          const pinch=hand.detector.update(pinchRatio(landmarks,frame.aspect),frame.now);
          if(pinch.state==='open')hand.anchor=null;
          else if(!hand.anchor)hand.anchor={...hand.point};
          const at=hand.anchor||hand.point;
          if(pinch.click)clicks.push({id,x:at.x,y:at.y});
          tokens.push({id,x:at.x,y:at.y,state:pinch.state,progress:pinch.progress,click:pinch.click,hover:false});
        });
        for(const [id,hand] of hands)if(!seen.has(id)&&frame.now-hand.lastSeen>o.lostGraceMs)hands.delete(id);
        return {tokens,clicks};
      },
      reset(){hands.clear()},
      size(){return hands.size},
    };
  }

  const MESSAGES=Object.freeze({
    off:{title:'Barehands éteint',detail:'Le mode test est désactivé.'},
    starting:{title:'Barehands démarre…',detail:'Chargement du suivi des mains et ouverture de la caméra.'},
    running:{title:'Barehands actif',detail:'Montrez une main à la caméra ; pincez pouce et index pour cliquer.'},
    disabled:{title:'Barehands arrêté',detail:'Mode test désactivé : caméra libérée, jetons retirés.'},
    camera_denied:{title:'Caméra refusée',detail:'Autorisez la caméra pour cette page dans le navigateur, puis réactivez l’interrupteur.'},
    camera_missing:{title:'Aucune caméra',detail:'Aucune webcam utilisable n’a été trouvée.'},
    camera_busy:{title:'Caméra indisponible',detail:'La webcam est occupée par une autre application ou ne répond pas.'},
    camera_ended:{title:'Caméra coupée',detail:'La webcam s’est arrêtée (débranchée ou coupée) : suivi arrêté.'},
    camera_unsupported:{title:'Caméra non prise en charge',detail:'Ce navigateur n’expose pas la caméra à cette page.'},
    assets_missing:{title:'Modèle introuvable',detail:'Les fichiers MediaPipe ne sont pas installés : lancez python scripts/bootstrap_third_party.py.'},
    tracking_failed:{title:'Suivi interrompu',detail:'Le suivi des mains a échoué : caméra libérée.'},
    start_failed:{title:'Démarrage impossible',detail:'Le suivi des mains n’a pas pu démarrer.'},
  });

  function classifyError(error){
    if(error&&typeof error.code==='string'&&MESSAGES[error.code])return error.code;
    const name=String((error&&error.name)||'');
    if(['NotAllowedError','PermissionDeniedError','SecurityError'].includes(name))return 'camera_denied';
    if(['NotFoundError','DevicesNotFoundError','OverconstrainedError'].includes(name))return 'camera_missing';
    if(['NotReadableError','TrackStartError','AbortError'].includes(name))return 'camera_busy';
    return 'start_failed';
  }

  /* Cycle de vie : tout ce qui est acquis (modèle, flux caméra, vidéo,
     surimpression, survol, boucle d'images) est rendu par un seul chemin,
     `teardown`, que l'arrêt soit voulu ou subi. `generation` invalide un
     démarrage encore en vol quand on éteint entre-temps. */
  function createController(deps){
    const tracker=createHandTracker(deps.options);
    let state='off',generation=0,landmarker=null,stream=null,video=null,frame=0,lastVideoTime=-1;

    function emit(code,error){
      const message=MESSAGES[code]||MESSAGES.start_failed;
      if(typeof deps.onStatus==='function')deps.onStatus({state,code,title:message.title,message:message.detail,error:error||null});
    }
    function stopStream(value){
      if(!value||typeof value.getTracks!=='function')return;
      for(const track of value.getTracks()){try{track.stop()}catch(_error){}}
    }
    function teardown(){
      if(frame){deps.cancelFrame(frame);frame=0}
      stopStream(stream);stream=null;
      if(video){try{video.dispose()}catch(_error){}video=null}
      if(landmarker){try{landmarker.close()}catch(_error){}landmarker=null}
      try{deps.interaction.clear()}catch(_error){}
      try{deps.overlay.unmount()}catch(_error){}
      tracker.reset();lastVideoTime=-1;
    }
    function fail(error,code){
      generation+=1;teardown();state='error';emit(code||classifyError(error),error);
    }
    function tick(){
      frame=0;
      if(state!=='running')return;
      const mine=generation;
      try{
        const now=deps.now();
        const time=video.currentTime();
        if(time!==lastVideoTime){
          lastVideoTime=time;
          const result=landmarker.detectForVideo(video.element,now);
          const out=tracker.update(result,{viewport:deps.viewport(),aspect:(video.width&&video.height)?video.width/video.height:4/3,now});
          deps.interaction.hover(out.tokens);
          deps.overlay.render(out.tokens);
          for(const click of out.clicks){
            deps.interaction.click(click);
            if(mine!==generation)return;  // le clic a éteint le mode test
          }
        }
      }catch(error){fail(error,'tracking_failed');return}
      if(mine===generation&&state==='running')frame=deps.requestFrame(tick);
    }
    async function enable(){
      if(state==='running'||state==='starting')return state;
      const mine=++generation;
      state='starting';emit('starting');
      try{
        if(typeof deps.getUserMedia!=='function')throw Object.assign(new Error('getUserMedia indisponible'),{code:'camera_unsupported'});
        const loaded=await deps.createLandmarker();
        if(mine!==generation){try{loaded.close()}catch(_error){}return state}
        landmarker=loaded;
        const opened=await deps.getUserMedia({audio:false,video:{facingMode:'user',width:{ideal:640},height:{ideal:480}}});
        if(mine!==generation){stopStream(opened);return state}
        stream=opened;
        const attached=await deps.attachVideo(opened);
        if(mine!==generation){try{attached.dispose()}catch(_error){}return state}
        video=attached;
        for(const track of (opened.getVideoTracks?opened.getVideoTracks():[])){
          if(typeof track.addEventListener==='function')track.addEventListener('ended',()=>{if(mine===generation)fail(null,'camera_ended')});
        }
        deps.overlay.mount();
        state='running';emit('running');
        frame=deps.requestFrame(tick);
      }catch(error){if(mine===generation)fail(error)}
      return state;
    }
    function disable(){
      const wasActive=state!=='off';
      generation+=1;teardown();state='off';
      emit(wasActive?'disabled':'off');
      return state;
    }
    return {enable,disable,state:()=>state,tick};
  }

  return {LM,DEFAULTS,MESSAGES,pinchRatio,toScreen,smooth,createPinchDetector,createHandTracker,classifyError,createController};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisBarehandsCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : caméra, surimpression, clics, onglet de réglages.
   -------------------------------------------------------------------------- */
(function installJarvisBarehands(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const Core=JarvisBarehandsCore;
  /* Noms partagés avec la scène et la page (identité de pointeur, formes du
     DOM) : `control_center_barehands_contracts.js`, inséré juste avant. Le
     bloc pur ci-dessus ne le lit pas — les tests node le chargent seul. */
  const BH=JarvisBarehandsContracts;
  const API='/api/barehands';
  const ASSET_BASE='/barehands/assets';
  const TAB_ID='experimental';
  /* Ce qu'un jeton « survole » : l'élément cliquable le plus proche. */
  const INTERACTIVE='button,a[href],input,select,textarea,label,summary,[role="button"],[role="tab"],[tabindex]:not([tabindex="-1"]),.choice,.acard,.toast';
  const ACCENT='var(--omega-accent,var(--accent,#6ee7ff))';

  const STYLE=`
#jarvisHands{position:fixed;inset:0;z-index:2147483000;pointer-events:none;overflow:hidden}
#jarvisHands .jh-token{position:absolute;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
  color:${ACCENT};border:2px solid currentColor;background:color-mix(in srgb,currentColor 12%,transparent);
  box-shadow:0 0 16px color-mix(in srgb,currentColor 45%,transparent),inset 0 0 8px color-mix(in srgb,currentColor 25%,transparent);
  transition:width .12s ease,height .12s ease,margin .12s ease,background .12s ease;will-change:transform}
#jarvisHands .jh-token::after{content:'';position:absolute;left:50%;top:50%;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:50%;background:currentColor}
#jarvisHands .jh-ring{position:absolute;inset:-7px;border-radius:50%;
  background:conic-gradient(currentColor calc(var(--jh-progress,0) * 1turn),transparent 0);
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2px));
          mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2px))}
#jarvisHands .jh-token.hover{width:46px;height:46px;margin:-23px 0 0 -23px;background:color-mix(in srgb,currentColor 24%,transparent)}
#jarvisHands .jh-token.pinching{border-style:dashed}
#jarvisHands .jh-token.pressed{width:24px;height:24px;margin:-12px 0 0 -12px;background:color-mix(in srgb,currentColor 60%,transparent)}
#jarvisHands .jh-token.clicked::before{content:'';position:absolute;inset:-3px;border-radius:50%;border:2px solid currentColor;animation:jhClick .38s ease-out forwards}
@keyframes jhClick{from{transform:scale(1);opacity:.95}to{transform:scale(2.6);opacity:0}}
#jarvisHands .jh-badge{position:fixed;left:18px;bottom:18px;padding:6px 10px;border-radius:999px;font:10px/1 ui-monospace,SFMono-Regular,Consolas,monospace;
  letter-spacing:.12em;color:${ACCENT};border:1px solid color-mix(in srgb,currentColor 35%,transparent);background:rgba(3,8,12,.55);backdrop-filter:blur(12px)}
.jarvis-hand-hover{outline:2px solid ${ACCENT}!important;outline-offset:2px!important}
@media(prefers-reduced-motion:reduce){#jarvisHands .jh-token{transition:none}#jarvisHands .jh-token.clicked::before{animation:none}}`;

  /* La feuille ci-dessus écrit ses sélecteurs en clair : elle est lue telle
     quelle par les tests. Le contrat reste la source des noms, et un test
     (`test_barehands_contracts_js`) refuse qu'ils divergent. */
  function ensureStyle(){
    if(document.getElementById(BH.DOM.styleId))return;
    const style=document.createElement('style');
    style.id=BH.DOM.styleId;style.textContent=STYLE;
    document.head.appendChild(style);
  }

  function createOverlay(){
    let root=null,badge=null;
    const tokens=new Map();
    return {
      mount(){
        ensureStyle();
        if(root)return;
        root=document.createElement('div');root.id=BH.DOM.rootId;root.setAttribute('aria-hidden','true');
        badge=document.createElement('div');badge.className=BH.DOM.badgeClass;badge.textContent='MAINS · TEST';
        root.appendChild(badge);document.body.appendChild(root);
      },
      unmount(){
        if(root)root.remove();
        root=null;badge=null;tokens.clear();
      },
      render(list){
        if(!root)return;
        const seen=new Set();
        for(const token of list){
          seen.add(token.id);
          let el=tokens.get(token.id);
          if(!el){el=document.createElement('div');el.className=BH.DOM.tokenClass;el.innerHTML=`<span class="${BH.DOM.ringClass}"></span>`;root.appendChild(el);tokens.set(token.id,el)}
          el.style.transform=`translate3d(${token.x.toFixed(1)}px,${token.y.toFixed(1)}px,0)`;
          el.style.setProperty('--jh-progress',token.progress.toFixed(3));
          el.classList.toggle('hover',!!token.hover);
          el.classList.toggle('pinching',token.state==='pinching');
          el.classList.toggle('pressed',token.state==='pressed');
          if(token.click){el.classList.remove('clicked');void el.offsetWidth;el.classList.add('clicked')}
        }
        for(const [id,el] of tokens)if(!seen.has(id)){el.remove();tokens.delete(id)}
        if(badge)badge.textContent=list.length?`MAINS · ${list.length}`:'MAINS · TEST';
      },
    };
  }

  function createInteraction(){
    const hovered=new Map();
    /* Identité de pointeur par main (contrat Slice 01, constat F2). La fente 0
       vaut `BH.POINTER_ID_BASE` : une main seule envoie exactement les mêmes
       événements qu'avant. La seconde main a enfin le sien, au lieu que deux
       mains parlent sous un identifiant unique. */
    const slots=BH.createSlotAllocator(BH.MAX_HANDS);
    const identityOf=id=>{
      const slot=slots.slot(id);
      return slot===null?null:{pointerId:BH.pointerIdForSlot(slot),isPrimary:slot===0};
    };
    function targetAt(x,y){
      const el=document.elementFromPoint(x,y);
      return el&&!el.closest(BH.DOM.rootSelector)?el:null;
    }
    function pointer(type,el,x,y,buttons,identity){
      const init={bubbles:true,cancelable:true,composed:true,view:window,clientX:x,clientY:y,button:0,buttons};
      if(type.startsWith('pointer')&&typeof PointerEvent==='function')
        el.dispatchEvent(new PointerEvent(type,{...init,pointerId:identity.pointerId,pointerType:BH.POINTER_TYPE,isPrimary:identity.isPrimary}));
      else if(!type.startsWith('pointer'))el.dispatchEvent(new MouseEvent(type,init));
    }
    function release(id){
      const previous=hovered.get(id);
      hovered.delete(id);
      const identity=identityOf(id);
      if(previous&&identity&&![...hovered.values()].includes(previous)){
        previous.classList.remove(BH.DOM.hoverClass);
        pointer('pointerout',previous,0,0,0,identity);pointer('mouseout',previous,0,0,0,identity);
      }
    }
    return {
      hover(tokens){
        const live=new Set();
        for(const token of tokens){
          live.add(token.id);
          const identity=identityOf(token.id);
          const raw=targetAt(token.x,token.y);
          const el=raw&&raw.closest(INTERACTIVE);
          token.hover=!!el;
          if(hovered.get(token.id)===el)continue;
          release(token.id);
          if(el&&identity){
            hovered.set(token.id,el);el.classList.add(BH.DOM.hoverClass);
            pointer('pointerover',el,token.x,token.y,0,identity);pointer('mouseover',el,token.x,token.y,0,identity);
          }
        }
        for(const id of [...hovered.keys()])if(!live.has(id))release(id);
        // Une main partie rend sa fente : deux mains qui vont et viennent en
        // retrouvent toujours une.
        slots.retain(live);
      },
      /* Un vrai clic : la séquence qu'enverrait une souris, sur l'élément exact
         sous le jeton (les écouteurs, labels, cases et liens réagissent). */
      click({id,x,y}){
        const raw=targetAt(x,y);
        const identity=identityOf(id);
        if(!raw||!identity)return false;
        pointer('pointerdown',raw,x,y,1,identity);pointer('mousedown',raw,x,y,1,identity);
        const focusable=raw.closest('button,a[href],input,select,textarea,summary,[tabindex]');
        if(focusable&&typeof focusable.focus==='function'){try{focusable.focus({preventScroll:true})}catch(_error){}}
        pointer('pointerup',raw,x,y,0,identity);pointer('mouseup',raw,x,y,0,identity);pointer('click',raw,x,y,0,identity);
        return true;
      },
      clear(){for(const id of [...hovered.keys()])release(id);slots.clear()},
    };
  }

  function attachVideo(stream){
    return new Promise((resolve,reject)=>{
      const el=document.createElement('video');
      el.muted=true;el.playsInline=true;el.autoplay=true;el.setAttribute('aria-hidden','true');
      el.style.cssText='position:fixed;left:-8px;top:-8px;width:4px;height:4px;opacity:0;pointer-events:none';
      const handle={element:el,get width(){return el.videoWidth||640},get height(){return el.videoHeight||480},
        currentTime:()=>el.currentTime,dispose(){try{el.pause()}catch(_error){}el.srcObject=null;el.remove()}};
      const timer=setTimeout(()=>{handle.dispose();reject(Object.assign(new Error('La vidéo ne démarre pas'),{code:'camera_busy'}))},10000);
      el.addEventListener('loadeddata',()=>{clearTimeout(timer);el.play().catch(()=>{});resolve(handle)},{once:true});
      el.srcObject=stream;document.body.appendChild(el);
    });
  }

  let visionModule=null;
  async function createLandmarker(){
    const state=await api(API);
    applyAssets(state);
    if(!state.assets||!state.assets.installed)throw Object.assign(new Error('assets manquants'),{code:'assets_missing'});
    let mod;
    try{
      if(!visionModule)visionModule=import(`${ASSET_BASE}/vision_bundle.mjs`);
      mod=await visionModule;
    }catch(error){visionModule=null;throw Object.assign(new Error(String(error&&error.message||error)),{code:'assets_missing'})}
    const fileset=await mod.FilesetResolver.forVisionTasks(`${ASSET_BASE}/wasm`);
    const settings=delegate=>({
      baseOptions:{modelAssetPath:`${ASSET_BASE}/models/hand_landmarker.task`,delegate},
      runningMode:'VIDEO',numHands:2,minHandDetectionConfidence:.6,minHandPresenceConfidence:.5,minTrackingConfidence:.5,
    });
    try{return await mod.HandLandmarker.createFromOptions(fileset,settings('GPU'))}
    catch(_gpu){return await mod.HandLandmarker.createFromOptions(fileset,settings('CPU'))}
  }

  const view={enabled:false,assets:null,busy:false,error:'',
    status:{state:'off',code:'off',title:Core.MESSAGES.off.title,message:Core.MESSAGES.off.detail,error:null}};

  const controller=Core.createController({
    getUserMedia:navigator.mediaDevices&&typeof navigator.mediaDevices.getUserMedia==='function'
      ?constraints=>navigator.mediaDevices.getUserMedia(constraints):null,
    createLandmarker,attachVideo,
    overlay:createOverlay(),interaction:createInteraction(),
    requestFrame:fn=>requestAnimationFrame(fn),cancelFrame:id=>cancelAnimationFrame(id),
    now:()=>performance.now(),viewport:()=>({width:window.innerWidth,height:window.innerHeight}),
    onStatus:onStatus,
  });

  function onStatus(status){
    const previous=view.status;
    view.status=status;
    if(status.state==='error'&&status.error)console.warn('[barehands]',status.code,status.error);
    const notify=status.state==='error'||status.state==='running'||(status.code==='disabled'&&previous.state!=='error');
    if(notify&&typeof toast==='function')
      toast({title:status.title,sub:status.message,kind:status.state==='error'?'bad':status.state==='running'?'ok':'warn',ms:status.state==='error'?9000:4000});
    refreshPanel();
  }

  function applyAssets(state){if(state&&state.assets)view.assets=state.assets}

  function applyServerState(state){
    applyAssets(state);
    view.enabled=!!(state&&state.enabled===true);
    if(view.enabled)controller.enable();
    else if(controller.state()!=='off')controller.disable();
    refreshPanel();
  }

  async function setEnabled(enabled){
    view.busy=true;view.error='';
    // Éteindre n'attend pas l'écriture : la caméra est libérée tout de suite.
    if(!enabled&&controller.state()!=='off')controller.disable();
    refreshPanel();
    try{
      const state=await api(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});
      view.busy=false;applyServerState(state);
    }catch(error){
      view.busy=false;view.error=`Réglage non enregistré : ${error.message}`;
      refreshPanel();
    }
  }

  function statusHtml(){
    const s=view.status,cls=s.state==='error'?'bad':'info';
    const error=view.error?`<div class="notice bad">${esc(view.error)}</div>`:'';
    return `${error}<div class="notice ${cls}"><strong>${esc(s.title)}</strong><div class="hint">${esc(s.message)}</div></div>`;
  }

  function assetsHtml(){
    const assets=view.assets;
    return assets&&!assets.installed
      ?`<div class="notice bad"><strong>Modèle MediaPipe absent</strong><div class="hint">Fichiers manquants : ${assets.missing.map(esc).join(', ')}. Lancez <code>${esc(assets.install_hint)}</code> puis réessayez.</div></div>`:'';
  }

  function panelHtml(){
    const missing=assetsHtml();
    return `<section>
      <h3>Barehands · mode test</h3>
      <div class="hint" style="margin-bottom:14px">Piloter l'interface à mains nues. La webcam suit vos mains <strong>localement</strong> (MediaPipe, aucun envoi vers un service cloud). Le réglage est enregistré immédiatement et reste actif au prochain chargement de la page.</div>
      <div class="field inline"><input type="checkbox" id="f_barehands" data-barehands-toggle ${view.enabled?'checked':''} ${view.busy?'disabled':''}>
        <div><label for="f_barehands">Activer Barehands (mode test) <span class="tag warn">TEST</span></label>
        <div class="hint">Désactivé par défaut. Éteint, la caméra est libérée et les jetons disparaissent.</div></div></div>
      <div id="barehandsStatus">${statusHtml()}</div>
      <div id="barehandsAssets">${missing}</div>
      <h3>Gestes</h3>
      <ul class="hint" style="padding-left:18px;line-height:1.7">
        <li>Chaque main visible affiche un jeton rond qui suit le bout de l'index ; il grossit au survol d'un élément cliquable.</li>
        <li>Rapprocher pouce et index remplit l'anneau du jeton (pincement en cours) ; le jeton se fige pour viser.</li>
        <li>Pincement franc : clic sous le jeton (onde visuelle). Rouvrir les doigts avant de recliquer.</li>
      </ul>
      <div class="hint" style="margin-top:10px">Limites du mode test : pas de glisser-déposer ni de défilement ; une liste déroulante ne s'ouvre pas au pincement (le navigateur l'interdit aux clics simulés) ; le visage ai-visualizer (iframe) ne reçoit pas les clics.</div>
    </section>`;
  }

  function refreshPanel(){
    if(typeof SET==='undefined'||!SET.open||SET.tab!==TAB_ID)return;
    const toggle=document.getElementById('f_barehands');
    if(toggle){toggle.checked=view.enabled;toggle.disabled=view.busy}
    const status=document.getElementById('barehandsStatus');
    if(status)status.innerHTML=statusHtml();
    const assets=document.getElementById('barehandsAssets');
    if(assets)assets.innerHTML=assetsHtml();
  }

  function installSettingsTab(){
    if(typeof TABS==='undefined'||!Array.isArray(TABS)||TABS.some(tab=>tab.id===TAB_ID))return;
    TABS.push({id:TAB_ID,label:'Expérimental',save:false});
    const baseRenderTab=renderTab;
    renderTab=async function(){
      if(SET.tab!==TAB_ID)return baseRenderTab();
      if(typeof destroyAgentCatalog==='function')destroyAgentCatalog();
      SET.renderRevision=(SET.renderRevision||0)+1;
      modalSave.style.display='none';
      modalSub.textContent='Fonctions en test : appliquées et enregistrées immédiatement.';
      modalContent.innerHTML=panelHtml();
      const toggle=document.getElementById('f_barehands');
      if(toggle)toggle.addEventListener('change',()=>setEnabled(toggle.checked));
      say('','');
      // Relire la présence des assets sans redessiner l'onglet.
      api(API).then(state=>{applyAssets(state);refreshPanel()}).catch(()=>{});
    };
  }

  window.JarvisBarehands=Object.freeze({
    version:1,core:Core,contracts:BH,
    state:()=>({enabled:view.enabled,status:view.status,assets:view.assets,controller:controller.state()}),
    enable:()=>setEnabled(true),disable:()=>setEnabled(false),
    // Diagnostic sans caméra : poser un jeton et cliquer depuis la console.
    adapters:Object.freeze({createOverlay,createInteraction}),
  });

  setTimeout(()=>{
    installSettingsTab();
    api(API).then(applyServerState).catch(()=>{});
  },0);
  window.addEventListener('pagehide',()=>{if(controller.state()!=='off')controller.disable()});
})();
