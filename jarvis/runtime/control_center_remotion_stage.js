/* Page de la scène Remotion (handoff jarvis-remotion-presentation-integration, Slice 10 ; `docs/remotion-isolation.md` § 10).

   Ce script tourne dans `GET /remotion-stage?id=<prefab>&v=<version>` : un petit document de confiance, de l'origine du Control Center,
   encadré par la fenêtre de scène (prefab host) et qui, lui, ENCADRE le bac à sable (`<iframe sandbox="allow-scripts">` d'une origine
   dédiée). Il existe pour une seule raison : la page qui monte un cadre Remotion porte `Content-Security-Policy: frame-src <origine du
   bac à sable>` et RIEN d'autre (jamais l'origine du visualiseur ni de Core). La page principale du Control Center encadre déjà un
   visualiseur ; ce document-ci n'en encadre pas.

   Rôle :
   - demande à Core (par `/api/remotion/player/...`) la page du cadre, compilée à la demande (compteur visible, échéance 150 s) ;
   - crée le cadre avec exactement `IFRAME_ATTRIBUTES` (jamais `allow-same-origin`), vérifie la SOURCE de chaque message
     (`createSupervisor.accept(event, iframe.contentWindow)` : pas de logique de confiance à côté) ;
   - appelle `supervisor.tick()` toutes les 250 ms tant qu'un cadre est monté (sans `tick()`, ni ping ni retrait) ; jeton de ping :
     `strongToken()` par défaut (128 bits), jamais un `token()` plus faible ;
   - n'envoie au cadre que des `inputProps` (le contenu de la diapositive) et des ordres `play`/`pause`/`seek`/`cue` ;
   - dit à l'écran chaque état : préparation (compteur), prêt, échec typé (moteur indisponible, compilation avec fichier:ligne,
     source refusée), cadre retiré par le chien de garde (raison en clair + « Recharger la scène ») ;
   - rend compte à la fenêtre parente par `{rsh: 1, type: 'status'}` (états `shell`, `preparing`, `ready`, `failed`, `killed`) et lit
     d'elle `props`, `control`, `cue`, `teardown` (même origine, source = `window.parent` : un autre cadre ne la pilote pas).
   Aucun secret ici : aucun jeton de Core n'existe dans cette page (les routes `/api/...` sont celles de la page de l'utilisateur). */
(function(root){
  'use strict';
  const P=root.RemotionSandboxProtocol||(typeof require==='function'?require('./remotion_sandbox_protocol.js'):null);
  /* Slice 13 : les inputProps sont construites et validées contre le contrat du descripteur AVANT de traverser vers le bac à sable. */
  const B=root.RemotionInputProps||(typeof require==='function'?require('./control_center_remotion_props.js'):null);
  const SHELL=1;
  const TICK_MS=250;
  const PREPARE_DEADLINE_MS=150000;
  const PROPS_COALESCE_MS=16;
  const CONTROL_HIDE_MS=2500;
  const PARENT_TYPES=Object.freeze(['props','control','cue','teardown']);
  const KILL_TEXT=Object.freeze({
    unresponsive:'La scène ne répond plus depuis 3 s : elle a été retirée.',
    memory:'La scène utilise trop de mémoire : elle a été retirée.',
    protocol_abuse:'La scène envoie des messages invalides : elle a été retirée.',
    no_ready:'La scène ne s’est pas lancée dans les 10 s : elle a été retirée.',
  });
  const PREFAB_ID=/^[a-z0-9][a-z0-9._-]{0,127}$/;

  function plainObject(value){return value!==null&&typeof value==='object'&&!Array.isArray(value)}
  function describe(error){return error&&typeof error.message==='string'?error.message:String(error)}

  /* Message de la fenêtre parente -> {ok, message} ; champs exacts (une clé de plus est un refus). */
  function parseParentMessage(event,parentWindow,origin){
    if(!event||event.source!==parentWindow||event.origin!==origin)return {ok:false,reason:'foreign'};
    const data=event.data;
    if(!plainObject(data)||data.rsh!==SHELL||!PARENT_TYPES.includes(data.type))return {ok:false,reason:'bad_message'};
    const allowed={props:['props','data'],control:['action','frame'],cue:['name','frame'],teardown:[]}[data.type];
    for(const key of Object.keys(data))if(key!=='rsh'&&key!=='type'&&!allowed.includes(key))return {ok:false,reason:'extra_field'};
    return {ok:true,message:data};
  }

  /* Erreur de Core (enveloppe {error:{code,message,diagnostics?}}) -> état d'échec affichable. */
  function failureOf(status,body){
    const error=body&&body.error&&typeof body.error==='object'?body.error:{};
    const code=typeof error.code==='string'?error.code:`http_${status}`;
    const message=typeof error.message==='string'&&error.message?error.message:`HTTP ${status}`;
    const diagnostics=Array.isArray(error.diagnostics)?error.diagnostics.slice(0,20).filter(plainObject).map((d)=>({
      file:String(d.file||''),line:Number(d.line)||0,column:Number(d.column)||0,text:String(d.text||'')})):[];
    const errors=Array.isArray(error.errors)?error.errors.slice(0,20).map(String):[];
    let title='La scène ne peut pas être jouée';
    let lead='Core a refusé de jouer la scène.';
    if(code==='presentation_studio_engine_unavailable'){
      title='Remotion n’est pas disponible';
      lead='Le moteur Remotion n’est pas prêt : la scène n’est pas jouée, et rien d’autre ne joue à sa place.';
    }else if(code==='presentation_studio_engine_unsupported'){
      title='Scène non utilisable avec ce moteur';
      lead='Cette scène n’est pas utilisable avec le moteur de la présentation.';
    }else if(code.startsWith('compile_')&&code!=='compile_runtime_unavailable'){
      title='La scène ne compile pas';
      lead='La source de la scène contient une erreur : corrigez-la, puis réessayez.';
    }else if(code==='invalid_definition'){
      title='La source de la scène est refusée';
      lead='La source a été refusée par les gardes de sécurité de Jarvis.';
    }else if(code==='unknown_prefab'||code==='unknown_version'){
      title='Scène introuvable';
      lead='Cette version de la scène n’existe pas.';
    }
    return {code,message,diagnostics,errors,title,lead};
  }

  function createStage(deps){
    const d=deps;
    const doc=d.document,win=d.window;
    const now=d.now||(()=>Date.now());
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancel=d.clearTimeout||((id)=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms));
    const stopEvery=d.clearInterval||((id)=>clearInterval(id));
    const state={phase:'shell',generation:0,props:{},data:{},propsRefused:0,lastProblems:[],descriptor:null,iframe:null,supervisor:null,tickTimer:null,prepareTimer:null,
      prepareSince:0,counterTimer:null,propsTimer:null,sent:'',playing:false,frame:0,frameAt:0,lastPong:0,mounted:false,
      killedReason:null,duration:0,fps:30,hideTimer:null,lastSupervisor:null,muted:true,controller:null,barTimer:null};
    const ui={};

    function el(tag,className,text){
      const node=doc.createElement(tag);
      if(className)node.className=className;
      if(text!==undefined)node.textContent=text;
      return node;
    }
    function tellParent(fields){
      try{d.parentWindow.postMessage(Object.assign({rsh:SHELL,type:'status'},fields),d.origin)}
      catch(error){d.log('warn','remotion.stage.parent_post_failed',{error:describe(error)})}
    }
    function report(event,fields){
      try{Promise.resolve(d.report(Object.assign({event},fields||{}))).catch((error)=>d.log('warn','remotion.stage.report_failed',{event,error:describe(error)}))}
      catch(error){d.log('warn','remotion.stage.report_failed',{event,error:describe(error)})}
    }

    /* ------------------------------------------------------------ interface */

    function build(){
      ui.root=doc.getElementById('stage');
      ui.panel=el('div','rs-panel');
      ui.panel.setAttribute('role','status');
      ui.panel.setAttribute('aria-live','polite');
      ui.host=el('div','rs-frame-host');
      ui.bar=el('div','rs-bar');
      ui.bar.hidden=true;
      ui.toggle=el('button','rs-btn','Pause');
      ui.toggle.type='button';
      ui.toggle.addEventListener('click',()=>{control(state.playing?'pause':'play');});
      ui.scrub=el('input','rs-scrub');
      ui.scrub.type='range';ui.scrub.min='0';ui.scrub.max='0';ui.scrub.value='0';ui.scrub.step='1';
      ui.scrub.setAttribute('aria-label','Position dans la scène');
      ui.scrub.addEventListener('input',()=>{control('seek',Number(ui.scrub.value))});
      ui.time=el('span','rs-time','');
      ui.sound=el('span','rs-sound','');
      ui.sound.title='Le navigateur n’autorise le son que sur un geste de l’utilisateur dans la scène : la lecture démarre muette.';
      ui.bar.append(ui.toggle,ui.scrub,ui.time,ui.sound);
      ui.root.append(ui.host,ui.panel,ui.bar);
      doc.addEventListener('pointermove',showBar);
      doc.addEventListener('focusin',showBar);
    }

    function showBar(){
      if(!state.mounted)return;
      ui.bar.hidden=false;
      cancel(state.hideTimer);
      state.hideTimer=later(()=>{
        if(state.playing&&!(doc.activeElement&&ui.bar.contains(doc.activeElement)))ui.bar.hidden=true;
      },CONTROL_HIDE_MS);
    }

    function setPanel(kind,title,lines,actions){
      ui.panel.className=`rs-panel rs-${kind}`;
      /* Un échec doit être annoncé, pas seulement affiché : `alert` ; l'attente reste un `status`. */
      ui.panel.setAttribute('role',kind==='failed'||kind==='killed'?'alert':'status');
      ui.panel.setAttribute('aria-live',kind==='failed'||kind==='killed'?'assertive':'polite');
      ui.panel.replaceChildren();
      if(kind==='ready'){ui.panel.hidden=true;return}
      ui.panel.hidden=false;
      ui.panel.append(el('p','rs-title',title));
      /* The action comes right after the title: in a small window the details scroll, the way out never does. */
      for(const action of actions||[]){
        const button=el('button','rs-btn',action.label);
        button.type='button';
        button.addEventListener('click',action.run);
        ui.panel.append(button);
      }
      for(const line of lines||[])ui.panel.append(el(line.startsWith('  ')?'pre':'p',line.startsWith('  ')?'rs-diag':'rs-line',line.trim()));
    }

    function counterText(){
      const seconds=Math.floor((now()-state.prepareSince)/1000);
      return `Préparation de la scène Remotion… ${seconds} s`;
    }

    /* ------------------------------------------------------------ démarrage */

    async function prepare(){
      const generation=++state.generation;
      teardownFrame();
      state.phase='preparing';state.mounted=false;state.descriptor=null;state.killedReason=null;
      state.prepareSince=now();
      abortPrepare();
      ui.bar.hidden=true;
      setPanel('wait',counterText(),['Compilation de la source (la première fois, jusqu’à deux minutes). Rien n’est joué avant que ce soit prêt.']);
      ui.panel.firstChild.textContent=counterText();
      stopEvery(state.counterTimer);
      state.counterTimer=every(()=>{
        if(state.phase==='preparing'&&ui.panel.firstChild)ui.panel.firstChild.textContent=counterText();
      },1000);
      cancel(state.prepareTimer);
      const controller=typeof AbortController==='function'?new AbortController():null;
      state.controller=controller;
      state.prepareTimer=later(()=>{
        if(generation!==state.generation||state.phase!=='preparing')return;
        if(controller)controller.abort();
        fail(generation,{code:'prepare_timeout',message:`La préparation dépasse ${PREPARE_DEADLINE_MS/1000} s : la scène n’a pas été jouée.`,
          diagnostics:[],errors:[],title:'La préparation est trop longue',lead:'La compilation prend plus de temps que prévu : la scène n’a pas été jouée. Réessayez, ou vérifiez la capacité Remotion.'});
      },PREPARE_DEADLINE_MS);
      tellParent({phase:'preparing'});
      let response,body=null;
      try{
        response=await d.fetch(`/api/remotion/player/${encodeURIComponent(d.prefabId)}/${encodeURIComponent(String(d.version))}`,
          {headers:{Accept:'application/json'},cache:'no-store',signal:controller?controller.signal:undefined});
        try{body=await response.json()}catch(_error){body=null}
      }catch(error){
        if(generation!==state.generation||state.phase!=='preparing')return;
        fail(generation,{code:'unreachable',message:`Le serveur ne répond pas : ${describe(error)}`,diagnostics:[],errors:[],title:'Core est injoignable',lead:'Le Control Center ne joint pas Core : la scène n’est pas jouée.'});
        return;
      }
      if(generation!==state.generation||state.phase!=='preparing')return;
      if(!response.ok||!body||body.kind!=='remotion'){fail(generation,failureOf(response.status,body));return}
      mountSandbox(generation,body);
    }

    /* La préparation en vol (requête vers Core, minuteries) est abandonnée : un démontage ou une nouvelle tentative ne laisse rien tourner. */
    function abortPrepare(){
      const controller=state.controller;
      state.controller=null;
      if(controller){try{controller.abort()}catch(_error){/* already settled */}}
      stopEvery(state.counterTimer);state.counterTimer=null;
      cancel(state.prepareTimer);state.prepareTimer=null;
    }

    function fail(generation,failure){
      if(generation!==state.generation)return;
      cancel(state.prepareTimer);stopEvery(state.counterTimer);
      teardownFrame();
      state.phase='failed';state.mounted=false;
      const lines=[failure.lead||failure.message];
      if(failure.lead)lines.push(`Détail : ${failure.message}`);
      lines.push(`Code : ${failure.code}`);
      for(const diag of failure.diagnostics)lines.push(`  ${diag.file}:${diag.line}:${diag.column}  ${diag.text}`);
      for(const text of failure.errors)lines.push(`  ${text}`);
      setPanel('failed',failure.title,lines,[{label:'Réessayer',run:()=>{prepare()}}]);
      ui.bar.hidden=true;
      tellParent({phase:'failed',reason:failure.code,message:failure.message.slice(0,300),title:failure.title});
      report('failed',{code:failure.code,diagnostics:failure.diagnostics.length});
      d.log('warn','remotion.stage.failed',{code:failure.code});
    }

    function mountSandbox(generation,descriptor){
      cancel(state.prepareTimer);stopEvery(state.counterTimer);
      /* Avant tout cadre : la page est ouverte par l'adresse que le bac à sable autorise, et l'adresse du cadre est bien celle de son origine. */
      if(descriptor.embedder_origin&&descriptor.embedder_origin!==d.origin){
        fail(generation,{code:'embedder_origin_mismatch',title:'Mauvaise adresse du Control Center',
          lead:`Ouvrez le Control Center via ${descriptor.embedder_origin} : cette page est ouverte via ${d.origin}, et le bac à sable de la scène n’accepte que la première.`,
          message:`embedder ${descriptor.embedder_origin} != page ${d.origin}`,diagnostics:[],errors:[]});
        return;
      }
      let pageOrigin='';
      try{pageOrigin=new URL(descriptor.page_url).origin}catch(_error){pageOrigin=''}
      if(!pageOrigin||pageOrigin!==descriptor.sandbox_origin){
        fail(generation,{code:'sandbox_origin_mismatch',title:'Adresse du bac à sable incohérente',
          lead:'Core a donné une adresse de cadre qui n’est pas celle de l’origine du bac à sable : la scène n’est pas montée.',
          message:`page_url origin ${pageOrigin||'invalid'} != sandbox_origin ${descriptor.sandbox_origin}`,diagnostics:[],errors:[]});
        return;
      }
      state.descriptor=descriptor;
      state.duration=descriptor.composition.durationInFrames;state.fps=descriptor.composition.fps;
      state.phase='mounting';
      setPanel('wait','Démarrage du bac à sable…',['La scène s’exécute dans un cadre isolé, sans accès à Jarvis.']);
      const iframe=doc.createElement('iframe');
      /* `sandbox` d'abord : le document ne doit jamais exister sans lui. Valeurs exactes de `IFRAME_ATTRIBUTES`. */
      iframe.setAttribute('sandbox',d.iframeAttributes.sandbox);
      iframe.setAttribute('allow',d.iframeAttributes.allow);
      iframe.setAttribute('referrerpolicy',d.iframeAttributes.referrerpolicy);
      iframe.setAttribute('loading',d.iframeAttributes.loading);
      iframe.setAttribute('title',`Scène ${descriptor.title||descriptor.prefab_id}`);
      iframe.className='rs-frame';
      /* Même schéma de couleur que le document du bac à sable (clair par défaut) : sinon le navigateur peint un fond blanc opaque. */
      iframe.style.colorScheme='light';
      state.iframe=iframe;
      const supervisor=P.createSupervisor({
        now,
        send:(message)=>postToFrame(iframe,message),
        kill:(reason,detail)=>{if(generation===state.generation)killed(generation,reason,detail)},
      });
      state.supervisor=supervisor;
      let loads=0;
      iframe.addEventListener('load',()=>{
        /* Le premier `load` est la page du bac à sable ; un second est une navigation du cadre (refusée par `frame-src` de cette page). */
        if(generation!==state.generation)return;
        if(++loads>1)killed(generation,'protocol_abuse','navigation');
      });
      /* `src` AVANT l'insertion : sinon le `load` de l'about:blank initial passerait pour une navigation. */
      iframe.src=descriptor.page_url;
      ui.host.replaceChildren(iframe);
      state.tickTimer=every(()=>{if(state.supervisor)state.supervisor.tick()},TICK_MS);
      tellParent({phase:'mounting',composition:descriptor.composition,engine_drift:!!descriptor.engine_drift});
    }

    function postToFrame(iframe,message){
      const view=iframe&&iframe.contentWindow;
      /* L'origine d'un cadre `sandbox` sans `allow-same-origin` est opaque : seule la cible '*' l'atteint. Ce message ne porte que des
         `inputProps` et des ordres de lecture ; l'expéditeur est de toute façon vérifié côté cadre (source + origine de l'hôte). */
      if(view)view.postMessage(message,'*');
    }

    function onFrameMessage(event){
      const iframe=state.iframe;
      if(!iframe||!state.supervisor||event.source!==iframe.contentWindow)return;
      const generation=state.generation;
      const result=state.supervisor.accept(event,iframe.contentWindow);
      if(!result.ok||generation!==state.generation)return;
      const message=result.message;
      switch(message.type){
        case 'ready':sandboxReady(generation);break;
        case 'pong':
          state.frame=message.frame;state.frameAt=now();state.lastPong=state.frameAt;state.muted=message.muted!==false;refreshBar();
          break;
        case 'violation':
          report('violation',{directive:message.directive});
          d.log('warn','remotion.stage.csp_violation',{directive:message.directive,blocked:message.blocked.slice(0,120)});
          break;
        case 'error':
          report('scene_error',{message:message.message.slice(0,200)});
          d.log('warn','remotion.stage.scene_error',{message:message.message.slice(0,200)});
          tellParent({phase:'scene_error',message:message.message.slice(0,300)});
          break;
        default:break;
      }
    }

    function sandboxReady(generation){
      const descriptor=state.descriptor;
      try{
        const built=B.buildInputProps(descriptor.input_contract,state.props,state.data);
        if(!built.ok)throw new Error(built.problems.join('; '));
        postToFrame(state.iframe,P.hostMessage('init',{composition:descriptor.composition,props:built.inputProps}));
        state.sent=JSON.stringify(built.inputProps);
      }catch(error){
        fail(generation,{code:'props_refused',message:`Les valeurs de la scène sont refusées par le bac à sable : ${describe(error)}`,
          diagnostics:[],errors:[],title:'Valeurs de la scène refusées',lead:'Le bac à sable a refusé les valeurs de la scène (trop grosses ou mal formées).'});
        return;
      }
      state.phase='ready';state.mounted=true;
      setPanel('ready');
      ui.bar.hidden=false;
      ui.scrub.max=String(Math.max(state.duration-1,0));
      state.playing=false;
      control('play');
      showBar();
      tellParent({phase:'ready',composition:descriptor.composition,engine_drift:!!descriptor.engine_drift});
      report('ready',{prefab_id:descriptor.prefab_id,version:descriptor.version});
      d.log('info','remotion.stage.ready',{prefab_id:descriptor.prefab_id,version:descriptor.version});
    }

    function killed(generation,reason,detail){
      if(generation!==state.generation)return;
      const text=KILL_TEXT[reason]||`La scène a été retirée (${reason}).`;
      /* Ce que le chien de garde avait compté (refus par raison, pongs) : gardé pour le diagnostic, jamais envoyé au cadre. */
      state.lastSupervisor=state.supervisor?state.supervisor.state():null;
      teardownFrame();
      state.phase='killed';state.mounted=false;state.killedReason=reason;
      setPanel('killed','Scène retirée par le chien de garde',[text],[{label:'Recharger la scène',run:()=>{prepare()}}]);
      ui.bar.hidden=true;
      tellParent({phase:'killed',reason,message:text,title:'Scène retirée par le chien de garde'});
      report('killed',{reason,detail:detail===null||detail===undefined?'':String(detail).slice(0,60)});
      d.log('warn','remotion.sandbox.killed',{reason,refused:state.lastSupervisor?state.lastSupervisor.refused:null});
    }

    function teardownFrame(){
      stopEvery(state.tickTimer);state.tickTimer=null;
      cancel(state.propsTimer);state.propsTimer=null;
      const iframe=state.iframe;
      state.iframe=null;state.supervisor=null;
      if(iframe){
        try{postToFrame(iframe,P.hostMessage('teardown'))}catch(_error){/* the frame is being removed anyway */}
        if(iframe.parentNode)iframe.parentNode.removeChild(iframe);
      }
    }

    /* ------------------------------------------------------------ ordres de la fenêtre parente */

    function control(action,frame){
      if(!state.mounted||!state.iframe)return false;
      try{
        if(action==='seek'){
          const target=Math.max(0,Math.min(state.duration-1,Math.floor(frame)));
          postToFrame(state.iframe,P.hostMessage('control',{action:'seek',frame:target}));
          state.frame=target;state.frameAt=now();
        }else{
          postToFrame(state.iframe,P.hostMessage('control',{action}));
          state.playing=action==='play';state.frameAt=now();
        }
      }catch(error){d.log('warn','remotion.stage.control_failed',{action,error:describe(error)});return false}
      refreshBar();
      return true;
    }

    function setProps(props,data){
      state.props=props;
      if(data!==undefined)state.data=data;
      if(!state.mounted)return;
      /* Coalescé : au plus un message `props` par 16 ms, le dernier gagne (changement rapide de couleur ou de durée). */
      if(state.propsTimer)return;
      state.propsTimer=later(()=>{
        state.propsTimer=null;
        if(!state.mounted||!state.iframe)return;
        /* Validé avant de traverser : une valeur refusée n'atteint jamais le bac à sable, la dernière valeur valide reste affichée. */
        const built=B.buildInputProps(state.descriptor.input_contract,state.props,state.data);
        if(!built.ok){
          state.propsRefused++;state.lastProblems=built.problems;
          d.log('warn','remotion.stage.props_rejected',{problems:built.problems.slice(0,3)});
          report('props_rejected',{diagnostics:built.problems.length});
          tellParent({phase:'scene_error',message:`Valeurs refusées, la scène garde les précédentes : ${built.problems[0]}`.slice(0,300)});
          return;
        }
        state.lastProblems=[];
        const text=JSON.stringify(built.inputProps);
        if(text===state.sent)return;
        try{
          postToFrame(state.iframe,P.hostMessage('props',{props:built.inputProps}));
          state.sent=text;
        }catch(error){d.log('warn','remotion.stage.props_refused',{error:describe(error)});tellParent({phase:'scene_error',message:`props refused: ${describe(error)}`.slice(0,300)})}
      },PROPS_COALESCE_MS);
    }

    function refreshBar(){
      if(!ui.bar)return;
      const projected=state.playing?state.frame+Math.round((now()-state.frameAt)/1000*state.fps):state.frame;
      const shown=Math.max(0,Math.min(state.duration-1,projected));
      ui.toggle.textContent=state.playing?'Pause':'Lecture';
      if(doc.activeElement!==ui.scrub)ui.scrub.value=String(shown);
      const seconds=(value)=>(value/state.fps).toFixed(1);
      ui.time.textContent=`${seconds(shown)} s / ${seconds(state.duration)} s`;
      ui.sound.textContent=state.muted?'Son coupé · cliquez la scène pour l’activer':'Son actif';
    }

    function onParentMessage(event){
      const parsed=parseParentMessage(event,d.parentWindow,d.origin);
      if(!parsed.ok)return;
      const m=parsed.message;
      switch(m.type){
        case 'props':if(plainObject(m.props)&&(m.data===undefined||plainObject(m.data)))setProps(m.props,m.data);break;
        case 'control':
          if(['play','pause','seek'].includes(m.action))control(m.action,m.frame);
          break;
        case 'cue':
          if(state.mounted&&state.iframe&&typeof m.name==='string'){
            try{postToFrame(state.iframe,P.hostMessage('cue',{name:m.name,frame:m.frame}))}catch(error){d.log('warn','remotion.stage.cue_refused',{error:describe(error)})}
          }
          break;
        case 'teardown':
          state.generation+=1;abortPrepare();teardownFrame();stopEvery(state.barTimer);state.barTimer=null;state.phase='removed';state.mounted=false;break;
        default:break;
      }
    }

    function start(){
      build();
      win.addEventListener('message',(event)=>{
        if(state.iframe&&event.source===state.iframe.contentWindow)onFrameMessage(event);
        else onParentMessage(event);
      });
      state.barTimer=every(()=>{if(state.mounted)refreshBar()},500);
      tellParent({phase:'shell'});
      prepare();
    }

    return {start,prepare,control,setProps,state:()=>({phase:state.phase,mounted:state.mounted,playing:state.playing,frame:state.frame,
      duration:state.duration,killedReason:state.killedReason,generation:state.generation,muted:state.muted,
      propsRefused:state.propsRefused,lastProblems:state.lastProblems.slice(0,3),
      supervisor:state.supervisor?state.supervisor.state():state.lastSupervisor||null})};
  }

  const api=Object.freeze({SHELL,TICK_MS,PREPARE_DEADLINE_MS,KILL_TEXT,PARENT_TYPES,parseParentMessage,failureOf,createStage});
  root.JarvisRemotionStage=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
