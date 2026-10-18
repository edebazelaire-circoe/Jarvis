/* Sélection Souris / Bare Hands et reprise de la main par la souris.

   Handoff `jarvis-board-orbital-ui-workspace-rail`, Slice 03 ; architecture
   résolue `docs/06-resolved-architecture.md` §4 (D5, contraignante). Contrat :
   `docs/control-center-shell.md` › Selection method, et
   `docs/barehands-contracts.md` › La palette d'outils (§ 8).

   **Aucun propriétaire nouveau.** La méthode de Sélection est une
   **projection** du cycle de vie Bare Hands (`openLifecycleSeam`) :

   | cycle de vie        | Sélection montre                          |
   |---------------------|-------------------------------------------|
   | `active`, `sleep`   | Bare Hands                                |
   | `off`               | Souris (caméra rendue, la posture en C ne peut rien) |
   | `error`             | Bare Hands, marque de panne + `code`      |
   | démarrage           | Bare Hands, marque d'attente + compteur   |

   - **Souris** = `JarvisBarehandsHudControl.selectMethod('mouse')`, donc
     `JarvisBarehands.disable()` : le retour à Bare Hands n'est possible que
     par un choix explicite (roue, voix) — par construction, sans champ neuf.
   - **Bare Hands** = `selectMethod('bare_hands')`, la séquence `activate()`
     puis `enable()` du contrôle du haut. Voix : `barehands_activate`.
   - **Reprise souris** (`decide`, pur) : seulement des événements de
     pointeur **réels** (`isTrusted` et un `pointerId` qui n’est pas celui de Bare
     Hands), seulement en `active`. Appui, clic, molette, menu contextuel :
     tout de suite. Mouvement : longueur de trajet `>= distancePx` **et**
     déplacement net `>= netPx` dans une fenêtre glissante de `windowMs` — le
     tremblement s'annule dans le net, une dérive lente n'atteint jamais le
     trajet dans la fenêtre. Une transition par épisode, puis plus rien tant
     que le cycle de vie n'a pas changé ; `cooldownMs` après chaque entrée en
     `active` (choix explicite, voix, réveil en C). Une reprise **refusée**
     (choix en vol, échec) rouvre l'épisode : l'événement délibéré suivant
     retente.
   - **Parcours exemptés** : tant qu'un parcours Bare Hands est ouvert
     (`JarvisBarehands.openFlow()` : calibration, test), aucune reprise — ces
     parcours se conduisent à la souris par construction, et une reprise y
     éteindrait Bare Hands sous une surimpression restée ouverte.

   Deux blocs, comme la roue : le **modèle pur** (exécuté par node dans
   `tests/unit/test_input_arbitration_js.py`, propriétés sur 10 000 tirages)
   et le **bloc navigateur** (écouteurs du document, branchement du secteur
   Sélection de `JarvisToolWheel`, éprouvé par
   `tests/unit/test_selection_method_browser.py`). */
(function(root){
  'use strict';

  /* ------------------------------------------------- les réglages

     Valeurs de D5, réglables à chaud (`JarvisInputArbitration.configure`),
     journalisées à chaque changement. */
  const DEFAULTS=Object.freeze({distancePx:48,netPx:24,windowMs:400,cooldownMs:1500});
  const BOUNDS=Object.freeze({distancePx:[4,2000],netPx:[2,2000],windowMs:[50,5000],cooldownMs:[0,60000]});
  /* Les entrées qui reprennent la main tout de suite. */
  const DISCRETE=Object.freeze(['pointerdown','click','wheel','contextmenu']);
  /* Plafond des échantillons gardés (au-delà, la fenêtre est de toute façon
     pleine : 1 000 Hz × 400 ms). */
  const MAX_SAMPLES=512;

  function normalizeParams(patch,base=DEFAULTS){
    const out={...base};
    for(const [key,raw] of Object.entries(patch||{})){
      if(!(key in BOUNDS))
        throw Object.assign(new TypeError(`réglage d'arbitrage inconnu : ${key}`),{code:'input_arbitration_unknown_param'});
      const n=Number(raw),[lo,hi]=BOUNDS[key];
      if(!Number.isFinite(n)||n<lo||n>hi)
        throw Object.assign(new RangeError(`${key} hors bornes (${lo}..${hi}) : ${raw}`),{code:'input_arbitration_bad_param'});
      out[key]=n;
    }
    if(out.netPx>out.distancePx)
      throw Object.assign(new RangeError(`netPx (${out.netPx}) ne peut dépasser distancePx (${out.distancePx})`),
        {code:'input_arbitration_bad_param'});
    return Object.freeze(out);
  }

  function initialState(){
    return {lifecycle:'off',samples:[],cooldownUntil:-Infinity,pending:false};
  }

  /* Trajet et net des échantillons de la fenêtre. */
  function measure(samples){
    let path=0;
    for(let i=1;i<samples.length;i+=1)
      path+=Math.hypot(samples[i].x-samples[i-1].x,samples[i].y-samples[i-1].y);
    const a=samples[0],b=samples[samples.length-1];
    const net=a&&b?Math.hypot(b.x-a.x,b.y-a.y):0;
    return {path,net};
  }

  /* Le cœur, pur : un état, un événement, des réglages → un nouvel état et,
     au plus, une reprise `{reason, distance_px, net_px, window_ms}`.

     Événements :
     - `{type:'lifecycle', lifecycle, t}` — chaque instantané de la couture ;
       un changement ouvre un nouvel épisode ; l'entrée en `active` arme le
       délai de grâce ;
     - `{type:'explicit', method:'bare_hands', t}` — le choix explicite (arme
       le délai avant même que le cycle de vie n'ait atterri) ;
     - `{type:'takeover_refused', t}` — la reprise émise n'a pas abouti
       (`selectMethod` occupé ou en échec) : l'épisode se rouvre, sans quoi
       `pending` resterait vrai pour toujours et la souris ne reprendrait plus ;
     - `{type, t, x, y, trusted, bareHands, flow}` pour `pointermove` et
       `DISCRETE` ; `flow` : le nom du parcours Bare Hands ouvert, ou rien. */
  function decide(state,event,params=DEFAULTS){
    const p=params;
    const s={...state};
    const none=()=>({state:s,takeover:null});
    if(!event||typeof event!=='object')return none();
    const t=Number(event.t);
    if(event.type==='lifecycle'){
      const next=String(event.lifecycle||'off');
      if(next!==s.lifecycle){
        if(next==='active')s.cooldownUntil=t+p.cooldownMs;
        s.lifecycle=next;s.samples=[];s.pending=false;
      }
      return none();
    }
    if(event.type==='takeover_refused'){
      s.pending=false;s.samples=[];
      return none();
    }
    if(event.type==='explicit'){
      if(event.method==='bare_hands'){s.cooldownUntil=t+p.cooldownMs;s.samples=[]}
      return none();
    }
    const discrete=DISCRETE.includes(event.type);
    if(!discrete&&event.type!=='pointermove')return none();
    /* Une main qui pilote produit des événements synthétiques : jamais
       `isTrusted`, et un `pointerId` de Bare Hands. Ni l'un ni l'autre ne
       reprend la main — sinon la main se couperait elle-même. */
    if(event.trusted!==true||event.bareHands===true)return none();
    /* Un parcours (calibration, test) se conduit à la souris : exempté. */
    if(event.flow){
      if(s.samples.length)s.samples=[];
      return none();
    }
    if(s.lifecycle!=='active'||s.pending){
      if(s.samples.length)s.samples=[];
      return none();
    }
    if(t<s.cooldownUntil){
      if(s.samples.length)s.samples=[];
      return none();
    }
    if(discrete){
      s.pending=true;s.samples=[];
      return {state:s,takeover:{reason:'click',input:event.type,distance_px:0,net_px:0,window_ms:p.windowMs}};
    }
    const x=Number(event.x),y=Number(event.y);
    if(!Number.isFinite(x)||!Number.isFinite(y)||!Number.isFinite(t))return none();
    const kept=s.samples.filter(sample=>t-sample.t<=p.windowMs);
    kept.push({t,x,y});
    s.samples=kept.length>MAX_SAMPLES?kept.slice(-MAX_SAMPLES):kept;
    const {path,net}=measure(s.samples);
    if(path>=p.distancePx&&net>=p.netPx){
      s.pending=true;s.samples=[];
      return {state:s,takeover:{reason:'movement',input:'pointermove',distance_px:Math.round(path),
        net_px:Math.round(net),window_ms:p.windowMs}};
    }
    return none();
  }

  /* ------------------------------------------------- la projection

     Ce que Sélection montre, à partir de l'instantané de la couture de cycle
     de vie (`JarvisBarehands.lifecycleStatus()`). `seconds` : la durée du
     démarrage, pour le compteur (RÈGLE ZÉRO). */
  function methodOf(snapshot,seconds){
    const snap=snapshot&&typeof snapshot==='object'?snapshot:{};
    const lifecycle=String(snap.lifecycle||'off');
    const code=snap.code===undefined||snap.code===null||snap.code===''?null:String(snap.code);
    const n=Math.max(0,Math.round(Number(seconds)||0));
    if(snap.starting===true)
      return Object.freeze({method:'bare_hands',tone:'wait',code:null,
        text:`Bare Hands · démarrage ${n} s`,
        note:`Démarrage depuis ${n} s — choisissez Souris pour annuler`});
    if(lifecycle==='error')
      return Object.freeze({method:'bare_hands',tone:'error',code,
        text:`Bare Hands · interrompu${code?` (${code})`:''}`,
        note:`Interrompu${code?` · ${code}`:''}${snap.title?` — ${snap.title}`:''}`});
    if(lifecycle==='active')
      return Object.freeze({method:'bare_hands',tone:null,code:null,text:'Bare Hands',note:''});
    if(lifecycle==='sleep')
      return Object.freeze({method:'bare_hands',tone:null,code:null,text:'Bare Hands · veille',note:'En veille'});
    return Object.freeze({method:'mouse',tone:null,code:null,text:'Souris',note:''});
  }

  /* Le premier niveau du sous-arc de Sélection : **exactement** Souris et
     Bare Hands. Une panne n'est jamais cochée Souris. */
  function selectionItems(view){
    const v=view||methodOf(null);
    return Object.freeze([
      Object.freeze({id:'mouse',label:'Souris',icon:'mouse',checked:v.method==='mouse'}),
      Object.freeze({id:'bare_hands',label:'Bare Hands',icon:'bare_hands',checked:v.method==='bare_hands',
        note:v.method==='bare_hands'?v.note:'',tone:v.tone}),
    ]);
  }

  /* Le second niveau (activation secondaire de « Bare Hands ») : les outils
     **installés** (`describeTools()`, aucune liste en dur) puis Veille, Aide,
     Diagnostic, Calibration. `quick` : `quickItems()` du contrôle du haut, qui
     dit pourquoi la calibration ne se choisit pas. */
  const QUICK_ITEMS=Object.freeze([
    Object.freeze({id:'help',act:'help',label:'Aide',icon:'help'}),
    Object.freeze({id:'diagnostics',act:'diagnostics',label:'Diagnostic',icon:'diagnostics'}),
    Object.freeze({id:'calibration',act:'calibration',label:'Calibration',icon:'calibration'}),
  ]);
  function bareHandsItems({tools,tool,lifecycle,quick}){
    const out=[];
    for(const d of Array.isArray(tools)?tools:[]){
      const installed=d.installed!==false;
      out.push(Object.freeze({id:`tool:${d.id}`,tool:d.id,label:String(d.label||d.id),icon:d.id,
        checked:d.id===tool,disabled:!installed,note:installed?'':'non installé',
        detail:installed?'':String(d.reason||'non installé')}));
    }
    out.push(Object.freeze({id:'sleep',label:'Veille',icon:'sleep',
      note:lifecycle==='sleep'?'en cours':''}));
    const blocked=new Map((Array.isArray(quick)?quick:[]).filter(q=>q&&q.note)
      .map(q=>[q.act,String(q.label||'').split(' — ').slice(1).join(' — ')||q.note]));
    for(const q of QUICK_ITEMS){
      const why=blocked.get(q.act)||'';
      out.push(Object.freeze({id:q.id,act:q.act,label:q.label,icon:q.icon,disabled:!!why,
        note:why?'indisponible':'',detail:why}));
    }
    return Object.freeze(out);
  }

  const api=Object.freeze({DEFAULTS,BOUNDS,DISCRETE,normalizeParams,initialState,decide,measure,
    methodOf,selectionItems,bareHandsItems,QUICK_ITEMS});
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- le bloc navigateur */

  const log=(level,key,data)=>{
    const line=`[input_arbitration] ${key} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);
    else if(level==='warn')console.warn(line);
    else console.info(line);
  };
  const notify=(title,sub,kind)=>{
    try{if(typeof toast==='function')toast({title,sub,kind:kind||'bad'})}
    catch(error){log('warn','input_arbitration.notify_failed',{error:String(error&&error.message||error)})}
  };
  const errorText=error=>String((error&&error.message)||error||'erreur inconnue');

  function installInputArbitration(){
    const surface=window.JarvisBarehands;
    const hud=window.JarvisBarehandsHudControl;
    const wheel=window.JarvisToolWheel;
    const C=window.JarvisBarehandsContracts;
    const missing=[!surface&&'JarvisBarehands',!hud&&'JarvisBarehandsHudControl',!wheel&&'JarvisToolWheel',
      !C&&'JarvisBarehandsContracts'].filter(Boolean);
    if(missing.length)
      throw Object.assign(new Error(`JarvisInputArbitration : ${missing.join(', ')} absent(s) — insérer ce module après eux`),
        {code:'input_arbitration_dependency_missing'});
    if(typeof hud.selectMethod!=='function'||typeof surface.openLifecycleSeam!=='function')
      throw Object.assign(new Error('JarvisInputArbitration : selectMethod ou la couture de cycle de vie manque'),
        {code:'input_arbitration_seam_missing'});

    let params=DEFAULTS,state=initialState(),snapshot=null,startedAt=0,startTimer=null;
    let returnStartedAt=0;
    const stats={takeovers:0,ignoredSynthetic:0,flowExempt:0,refusedTakeovers:0,lastTakeover:null,
      lastReturnMs:null,lastReturnOutcome:null};
    let exemptFlow=null;
    const now=()=>performance.now();

    function feed(event){
      const out=decide(state,event,params);
      state=out.state;
      if(out.takeover)takeover(out.takeover);
    }

    /* La reprise : la même porte que le choix « Souris », avec un motif qui
       ne change que la phrase du toast. */
    function takeover(info){
      stats.takeovers+=1;stats.lastTakeover={...info,at:Date.now()};
      log('info','input_arbitration.takeover',{reason:info.reason,input:info.input,distance_px:info.distance_px,
        net_px:info.net_px,window_ms:info.window_ms});
      choose('mouse',{source:'takeover',reason:'mouse_takeover'}).then(out=>{
        if(out!==null)return;
        stats.refusedTakeovers+=1;
        feed({type:'takeover_refused',t:now()});
        log('warn','input_arbitration.takeover_rearmed',{reason:info.reason,refused:stats.refusedTakeovers});
      }).catch(error=>log('error','input_arbitration.takeover_failed',{error:errorText(error)}));
    }

    /* Le parcours Bare Hands ouvert (calibration, test), lu à la source
       (`JarvisBarehands.openFlow()`, le garde qui refuse un second parcours).
       Journalisé à l'entrée et à la sortie de l'exemption. */
    function openFlowName(){
      let name=null;
      try{name=typeof surface.openFlow==='function'?surface.openFlow():null}
      catch(error){log('error','input_arbitration.flow_unreadable',{error:errorText(error)})}
      if(name!==exemptFlow){
        log('info',name?'input_arbitration.flow_exempt':'input_arbitration.flow_closed',{flow:name||exemptFlow});
        exemptFlow=name;
      }
      return name;
    }

    async function choose(method,ctx){
      const source=ctx&&ctx.source||'api';
      if(method==='bare_hands'){
        feed({type:'explicit',method,t:now()});
        returnStartedAt=now();
      }
      log('info','selection.method_requested',{method,source});
      let out=null;
      try{
        out=await hud.selectMethod(method,method==='mouse'&&ctx&&ctx.reason?{reason:ctx.reason}:undefined);
      }catch(error){
        log('error','selection.method_failed',{method,source,code:(error&&error.code)||null,error:errorText(error)});
        notify(`${method==='mouse'?'Souris':'Bare Hands'} : choix impossible`,errorText(error));
        return null;
      }
      if(out===null){
        const why=typeof hud.failure==='function'?hud.failure():'';
        if(why){
          log('error','selection.method_refused',{method,source,error:why});
          notify(`${method==='mouse'?'Souris':'Bare Hands'} : pas pris`,why);
        }else log('warn','selection.method_busy',{method,source});
      }else log('info','selection.method_selected',{method,source});
      return out;
    }

    function startSeconds(){return startedAt?(now()-startedAt)/1000:0}
    function paint(){
      const view=methodOf(snapshot,startSeconds());
      try{wheel.setStatus('selection',{icon:view.method==='mouse'?'mouse':'bare_hands',tone:view.tone,text:view.text})}
      catch(error){log('error','selection.paint_failed',{error:errorText(error)})}
      return view;
    }

    /* La couture : chaque transition, d'où qu'elle vienne (roue, contrôle,
       voix, réveil en C, retour en veille, panne). */
    surface.openLifecycleSeam('selection',snap=>{
      const was=snapshot;
      snapshot=snap;
      if(snap&&snap.starting){
        if(!startedAt)startedAt=now();
        if(!startTimer)startTimer=setInterval(paint,1000);
      }else{
        startedAt=0;
        if(startTimer){clearInterval(startTimer);startTimer=null}
      }
      feed({type:'lifecycle',lifecycle:snap&&snap.starting?'starting':(snap&&snap.lifecycle)||'off',t:now()});
      const view=paint();
      if(returnStartedAt&&snap&&!snap.starting&&snap.lifecycle!==(was&&was.lifecycle)){
        if(snap.lifecycle==='active'||snap.lifecycle==='error'||snap.lifecycle==='off'){
          stats.lastReturnMs=Math.round(now()-returnStartedAt);
          stats.lastReturnOutcome=snap.lifecycle;
          log(snap.lifecycle==='active'?'info':'warn','selection.bare_hands_return',
            {ms:stats.lastReturnMs,lifecycle:snap.lifecycle,code:snap.code||null});
          returnStartedAt=0;
        }
      }
      log('info','selection.projected',{method:view.method,tone:view.tone,lifecycle:snap&&snap.lifecycle,
        starting:!!(snap&&snap.starting)});
    });

    /* Les vrais événements de pointeur, au document, en capture : ils
       arrivent avant tout gestionnaire de page, et rien n'est empêché — le
       clic qui reprend la main fait aussi ce qu'il devait faire. */
    const onPointer=event=>{
      if(state.lifecycle!=='active'||state.pending)return;
      const bareHands=!!(C.isBareHandsPointerId&&C.isBareHandsPointerId(event.pointerId));
      if(!event.isTrusted||bareHands){stats.ignoredSynthetic+=1;return}
      /* Un `click` né du clavier (Entrée, Espace) n'est pas la souris. */
      if(event.type==='click'&&event.detail===0)return;
      const flow=openFlowName();
      if(flow)stats.flowExempt+=1;
      feed({type:event.type,t:now(),x:event.clientX,y:event.clientY,trusted:event.isTrusted===true,bareHands,flow});
    };
    for(const type of ['pointerdown','pointermove','click','contextmenu'])
      document.addEventListener(type,onPointer,{capture:true,passive:true});
    document.addEventListener('wheel',onPointer,{capture:true,passive:true});

    /* Le secteur Sélection de la roue : un sous-arc Souris / Bare Hands, et
       sous Bare Hands (activation secondaire) les outils et les actions
       rapides, par les **mêmes portes** que la bande et le menu du haut. */
    const runQuick=async act=>{
      const out=await hud.runQuick(act);
      /* Le contrôle du haut rend `null` sur un échec et l'écrit dans sa note,
         cachée roue allumée : la raison remonte ici, la roue la notifie. */
      if(out===null&&typeof hud.failure==='function'&&hud.failure())throw new Error(hud.failure());
      return out;
    };
    function secondLevel(){
      let tools=[],tool=null,quick=[];
      try{tools=surface.tools()}catch(error){log('error','selection.tools_unreadable',{error:errorText(error)})}
      try{tool=surface.tool()}catch(error){log('error','selection.tool_unreadable',{error:errorText(error)})}
      try{quick=hud.quickItems()}catch(error){log('warn','selection.quick_unreadable',{error:errorText(error)})}
      const lifecycle=snapshot&&snapshot.lifecycle;
      return bareHandsItems({tools,tool,lifecycle,quick}).map(item=>({...item,onActivate:async ctx=>{
        if(item.tool){
          /* Le seul chemin d'écriture de l'outil : `tool(id)` → `saveSettings({tool})`. */
          const saved=await surface.tool(item.tool);
          if(saved===null)throw Object.assign(new Error(`outil « ${item.label} » non enregistré`),{code:'barehands_tool_not_saved'});
          log('info','selection.tool_selected',{tool:item.tool,source:ctx.source});
          return saved;
        }
        if(item.id==='sleep'){
          const out=await hud.choose('sleep');
          if(out===null&&hud.failure())throw new Error(hud.failure());
          return out;
        }
        return runQuick(item.act);
      }}));
    }
    /* Après Souris / Bare Hands, les actions sur la sélection de la scène
       (Slice 06 de jarvis-board-ui-wheel-dossier-refactor) : Ranger, Masquer,
       forme, Retirer du Board, Masqués (N). La scène les fournit
       (`JarvisScene.selectionMenu`, chargée après ce module : lue à l'appel) ;
       sa panne n'éteint pas le choix de la méthode, elle se journalise. */
    function sceneRows(ctx){
      const scene=root.JarvisScene;
      if(!scene||typeof scene.selectionMenu!=='function')return [];
      try{
        const rows=scene.selectionMenu(ctx);
        return Array.isArray(rows)?rows:[];
      }catch(error){
        log('error','selection.actions_unreadable',{error:errorText(error)});
        return [];
      }
    }
    wheel.register({id:'selection',menu:true,
      onActivate:()=>{/* `menu:true` : l'activation ouvre le sous-arc. */},
      onSecondary:ctx=>[...selectionItems(methodOf(snapshot,startSeconds())).map(item=>({...item,
        onActivate:at=>choose(item.id,{source:at.source}),
        ...(item.id==='bare_hands'?{onSecondary:secondLevel}:{}),
      })),...sceneRows(ctx)],
    });

    root.JarvisInputArbitration=Object.freeze({
      get params(){return params},
      configure(patch){
        params=normalizeParams(patch,params);
        log('info','input_arbitration.configured',{...params});
        return params;
      },
      state:()=>({lifecycle:state.lifecycle,pending:state.pending,samples:state.samples.length,
        cooldownLeftMs:Math.max(0,Math.round(state.cooldownUntil-now()))}),
      stats:()=>({...stats}),
      view:()=>methodOf(snapshot,startSeconds()),
      selectMethod:(method,ctx)=>choose(method,{source:'api',...(ctx||{})}),
    });
    log('info','input_arbitration.installed',{...params});
  }

  try{installInputArbitration()}
  catch(error){
    console.error('[input_arbitration] input_arbitration.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
