/* Lecture d'une présentation dans le Control Center (studio de présentation, Slice 12) : bande d'état + clavier.

   Ce module ne décide RIEN. Core possède la lecture (machine d'états, fenêtre de stage, ressources auxiliaires,
   mode) ; la page :

   1. affiche, hors plein écran, une bande lisible : QUI présente (rôle), OÙ l'on en est (scène, item, prochaine cue),
      depuis COMBIEN de temps contre l'objectif souple, et COMMENT en sortir (pause, précédent, suivant, plein écran,
      arrêt) ;
   2. lit le clavier sur l'élément HÔTE de la fenêtre de stage (le cadre sandboxé ne relaie aucune touche, R4) et appelle
      les MÊMES routes que la voix : `POST /api/presentation-studio/playback/<verbe>` (le relais force l'acteur `user`) ;
   3. entre en plein écran par `JarvisFullscreen.enter({object_id, keys:'host'})` dans le clic du bouton, et reçoit les
      touches du plein écran par `onNavigate` (pas de double traitement : la touche déjà traitée est `defaultPrevented`).

   Les titres, libellés et cues viennent du texte d'un auteur ou d'un modèle : ils ne passent que par `textContent`,
   jamais `innerHTML`, et jamais comme une consigne.

   Chaque commande est en vol visible (verbe, secondes écoulées), a une échéance (10 s) et se termine toujours dans un
   état d'où l'on peut agir : un refus de la machine est une information dite en clair, un échec de la fenêtre est un
   toast + une ligne de console + la cause dans la bande, une panne de Core est dite avec sa durée. */
(function(root){
  'use strict';

  const ROUTE='/api/presentation-studio/playback';
  const COMMAND_TIMEOUT_MS=10000;
  const POLL_ACTIVE_MS=1500;
  const POLL_IDLE_MS=5000;
  const POLL_BACKOFF_MAX_MS=15000;
  const QUEUE_MAX=4;
  const STYLE_ID='jv-studio-player-style';
  const BAND_ID='jvStudioBand';
  const STOPPED_NOTICE_MS=12000;
  const LINK_LOST_AFTER=2;

  const ROLE_LABEL=Object.freeze({user_presenter:'Vous présentez',jarvis_presenter:'Jarvis présente',rehearsal:'Répétition'});
  const PHASE_LABEL=Object.freeze({playing:'En cours',paused:'En pause',detour:'Détour',resuming:'Reprise…',ended:'Terminé',stopped:'Arrêtée'});
  /* Touche -> action. Pas d'Échap en plein écran (le navigateur le garde pour sortir) ; hors plein écran Échap met en pause. */
  const KEYS=Object.freeze({
    ArrowRight:'next',ArrowDown:'next',PageDown:'next',' ':'next',
    ArrowLeft:'previous',ArrowUp:'previous',PageUp:'previous',Backspace:'previous',
    Home:'first',End:'last',p:'toggle_pause',P:'toggle_pause',Escape:'pause',
  });
  /* Les refus de la machine (codes stables de Core), dits à l'humain. */
  const REFUSALS=Object.freeze({
    not_running:'Aucune présentation en cours.',already_running:'Une présentation est déjà en cours.',
    paused:'La lecture est en pause : reprenez d\'abord.',in_detour:'Une ressource annexe est à l\'écran : revenez du détour d\'abord.',
    resuming:'La scène est en cours de reprise : un instant.',at_start:'C\'est déjà le premier élément.',
    at_end:'La présentation est terminée.',locked_sequence_active:'Une séquence verrouillée est en cours : attendez sa fin, ou arrêtez.',
    interruption_refused:'Cet élément ne peut être interrompu que par l\'arrêt.',aux_stack_full:'Trop de ressources annexes ouvertes.',
    no_detour:'Aucun détour en cours.',unknown_target:'Cet endroit n\'existe pas dans la présentation.',
    unknown_anchor:'Cette ancre n\'existe pas sur la scène.',mode_switch_refused:'Le mode d\'interaction n\'a pas pu être changé pour cette lecture.',
    illegal_transition:'Pas possible maintenant.',empty_score:'La partition est vide.',role_invalid:'Ce rôle ne convient pas.',
  });
  const PROBLEMS=Object.freeze({
    mode_restore_failed:'Le mode d\'interaction n\'a pas pu être rétabli : choisissez-le dans le sélecteur de mode.',
    aux_retire_failed:'Une ressource annexe n\'a pas pu être retirée de la scène.',
    stage_release_failed:'La fenêtre de scène n\'a pas pu être retirée.',
    aux_stage_failed:'La ressource annexe n\'a pas pu s\'afficher.',score_problems:'La partition ne correspond plus aux scènes : corrigez-la.',
    art_direction_changed:'La direction artistique a changé pendant la lecture.',
    anchor_control_not_toggle:'Une ancre pilote un réglage qui n\'est pas un interrupteur : le repère est suivi, pas l\'image.',
  });

  const STYLE=`
#${BAND_ID}{position:fixed;left:18px;bottom:18px;z-index:34;box-sizing:border-box;width:min(580px,calc(100vw - 150px));
  display:grid;gap:8px;padding:12px 14px;border-radius:10px;border:1px solid var(--line,#183343);
  background:var(--panel,rgba(6,12,18,.94));color:var(--text,#d8edf7);font:13px/1.45 system-ui,Segoe UI,sans-serif;
  box-shadow:0 10px 36px rgba(0,0,0,.5)}
#${BAND_ID}[hidden]{display:none}
#${BAND_ID}[data-kind="problem"]{border-color:var(--warn,#ffb85c)}
#${BAND_ID} .jvsp-head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
#${BAND_ID} .jvsp-role{font-weight:650;color:var(--accent,#6ee7ff)}
#${BAND_ID} .jvsp-phase{padding:1px 8px;border-radius:999px;border:1px solid var(--line,#183343);font-size:12px}
#${BAND_ID}[data-phase="paused"] .jvsp-phase,#${BAND_ID}[data-phase="detour"] .jvsp-phase{border-color:var(--warn,#ffb85c);color:var(--warn,#ffb85c)}
#${BAND_ID} .jvsp-clock{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--muted,#7190a0)}
#${BAND_ID} .jvsp-clock[data-over="1"]{color:var(--warn,#ffb85c)}
#${BAND_ID} .jvsp-where{font-size:14px;font-weight:600;overflow-wrap:anywhere}
#${BAND_ID} .jvsp-line{color:var(--muted,#7190a0);overflow-wrap:anywhere;margin:0}
#${BAND_ID} .jvsp-line:empty{display:none}
#${BAND_ID} .jvsp-note{margin:0;color:var(--warn,#ffb85c);overflow-wrap:anywhere}
#${BAND_ID} .jvsp-note:empty{display:none}
#${BAND_ID} .jvsp-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
#${BAND_ID} button{font:inherit;min-height:34px;padding:0 12px;border-radius:8px;cursor:pointer;
  border:1px solid var(--line,#183343);background:transparent;color:inherit}
#${BAND_ID} button:hover:not(:disabled){border-color:var(--accent,#6ee7ff)}
#${BAND_ID} button:disabled{opacity:.5;cursor:default}
#${BAND_ID} button:focus-visible{outline:2px solid var(--accent,#6ee7ff);outline-offset:2px}
#${BAND_ID} .jvsp-stop{margin-left:auto;border-color:var(--danger,#ff6577);color:var(--danger,#ff6577)}
#${BAND_ID} .jvsp-keys{font-size:11px;color:var(--muted,#7190a0)}
@media (forced-colors:active){#${BAND_ID}{border-color:CanvasText}}
`;

  function messageOf(error){return String(error&&error.message||error||'erreur inconnue')}
  function pad(n){return n<10?'0'+n:String(n)}
  function clock(ms){const s=Math.max(0,Math.floor(ms/1000));return pad(Math.floor(s/60))+':'+pad(s%60)}
  function editable(target){
    if(!target)return false;
    const tag=String(target.tagName||'').toUpperCase();
    return tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'||target.isContentEditable===true;
  }

  function createStudioPlayer(deps){
    const doc=deps.document;
    const win=deps.window||root;
    const request=deps.request;
    const now=deps.now||(()=>Date.now());
    const setT=deps.setTimeout||((fn,ms)=>win.setTimeout(fn,ms));
    const clearT=deps.clearTimeout||(id=>win.clearTimeout(id));
    const setI=deps.setInterval||((fn,ms)=>win.setInterval(fn,ms));
    const clearI=deps.clearInterval||(id=>win.clearInterval(id));
    const toast=typeof deps.toast==='function'?deps.toast:null;
    const fullscreen=deps.fullscreen||null;
    const log=deps.log||((level,event,data)=>{
      const line=`[studio] ${event} ${JSON.stringify(data||{})}`;
      if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
    });
    const stats={polls:0,pollFailures:0,commands:0,refused:0,failed:0,keys:0,dropped:0};

    let view={phase:'idle',running:false};
    let viewAt=now();
    let inflight=null;            /* {verb, at} */
    let queue=Promise.resolve();
    let queued=0;
    let notice=null;              /* {text, kind:'info'|'problem', until:number|null} */
    let failures=0;
    let linkLostSince=null;
    let pollTimer=null;
    let ticker=null;
    let started=false;
    let visible=true;
    let band=null;
    let stageEl=null;
    let unsubscribeNav=null;
    let dismissedRun=null;        /* run_id dont la bande « arrêtée » a été fermée à la main */
    let stoppedSeen=null;         /* {runId, at} : première fois qu'on voit cette fin */
    const ui={};

    /* ---------------------------------------------------------------- bande */
    function ensureStyle(){
      if(doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=STYLE;
      (doc.head||doc.body).appendChild(style);
    }
    function button(label,onClick,cls){
      const b=doc.createElement('button');
      b.setAttribute('type','button');b.className=cls||'';b.textContent=label;
      b.addEventListener('click',onClick);
      return b;
    }
    function build(){
      if(band)return band;
      ensureStyle();
      band=doc.createElement('section');
      band.id=BAND_ID;band.setAttribute('role','region');band.setAttribute('aria-label','Lecture de présentation');
      band.hidden=true;
      const head=doc.createElement('div');head.className='jvsp-head';
      ui.role=doc.createElement('span');ui.role.className='jvsp-role';
      ui.phase=doc.createElement('span');ui.phase.className='jvsp-phase';
      ui.clock=doc.createElement('span');ui.clock.className='jvsp-clock';
      head.appendChild(ui.role);head.appendChild(ui.phase);head.appendChild(ui.clock);
      ui.where=doc.createElement('div');ui.where.className='jvsp-where';
      ui.where.setAttribute('role','status');ui.where.setAttribute('aria-live','polite');
      ui.item=doc.createElement('p');ui.item.className='jvsp-line';
      ui.next=doc.createElement('p');ui.next.className='jvsp-line';
      ui.note=doc.createElement('p');ui.note.className='jvsp-note';ui.note.setAttribute('role','alert');
      const actions=doc.createElement('div');actions.className='jvsp-actions';
      ui.prev=button('◀ Précédent',()=>{command('previous')},'jvsp-prev');
      ui.pause=button('Pause',()=>{command(view.phase==='paused'?'resume':'pause')},'jvsp-pause');
      ui.nextBtn=button('Suivant ▶',()=>{command('next')},'jvsp-next');
      ui.full=button('Plein écran',()=>{enterFullscreen()},'jvsp-full');
      ui.stop=button('Arrêter',()=>{command('stop')},'jvsp-stop');
      ui.dismiss=button('Fermer',()=>{notice=null;dismissedRun=view.last_run&&view.last_run.run_id||view.run_id||null;render()},'jvsp-close');
      [ui.prev,ui.pause,ui.nextBtn,ui.full,ui.stop,ui.dismiss].forEach(b=>actions.appendChild(b));
      ui.keys=doc.createElement('div');ui.keys.className='jvsp-keys';
      ui.keys.textContent='← → Espace : naviguer · P ou Échap : pause · Début / Fin · cliquez la scène pour le clavier';
      [head,ui.where,ui.item,ui.next,ui.note,actions,ui.keys].forEach(n=>band.appendChild(n));
      doc.body.appendChild(band);
      return band;
    }

    function activeRun(){return view.running===true&&view.phase!=='stopped'&&view.phase!=='idle'}
    function itemElapsedMs(){
      if(!view.elapsed)return 0;
      const live=view.phase==='playing'||view.phase==='resuming';
      return view.elapsed.item_ms+(live?Math.max(0,now()-viewAt):0);
    }
    function problemsText(){
      const codes=[...(view.problems||[]),...(view.notices||[])];
      return codes.map(code=>PROBLEMS[code]||(String(code).startsWith('stage_')?`La scène n'a pas suivi (${code}).`:`Problème : ${code}`));
    }
    function render(){
      build();
      const last=!activeRun()&&view.phase==='stopped'&&view.last_run||null;
      if(last&&(!stoppedSeen||stoppedSeen.runId!==last.run_id))stoppedSeen={runId:last.run_id,at:now()};
      /* Une fin propre s'efface seule ; une fin qui laisse un problème (mode non rétabli, fenêtre non retirée, mode changé
         par l'utilisateur, plantage) reste affichée jusqu'à ce qu'on la ferme. */
      const lingers=last&&((last.problems&&last.problems.length)||last.reason==='mode_changed_by_user'||last.reason==='crashed');
      const showStopped=!!last&&dismissedRun!==last.run_id&&(lingers||now()-stoppedSeen.at<STOPPED_NOTICE_MS);
      const lost=linkLostSince!==null;
      const show=activeRun()||showStopped||!!notice||(lost&&!!last);
      band.hidden=!show;
      if(!show){return}
      const phase=view.phase||'idle';
      band.setAttribute('data-phase',phase);
      const problems=activeRun()?problemsText():[];
      band.setAttribute('data-kind',problems.length||lost||notice&&notice.kind==='problem'?'problem':'ok');
      if(activeRun()){
        ui.role.textContent=ROLE_LABEL[view.role]||'Présentation';
        ui.phase.textContent=PHASE_LABEL[phase]||phase;
        const scene=view.scene||{},pos=view.position||{};
        ui.where.textContent=`Scène ${scene.number||'?'}/${scene.of||'?'} · ${scene.title||'(sans titre)'}  — élément ${pos.index||'?'}/${pos.of||'?'}`;
        const item=view.item||{};
        const who=item.presenter==='user'?'vous':item.presenter==='jarvis'?'Jarvis':'silence';
        ui.item.textContent=`${item.label||'Élément'} · ${who}`+(view.silence?' (silence voulu)':'')+(view.sequence?` · séquence ${view.sequence.step}/${view.sequence.of}`:'')+
          (view.detour?` · détour : ${view.detour.title}`:'');
        const next=view.next;
        ui.next.textContent=next?`Ensuite : ${next.item_label||next.scene_title||'élément suivant'}`+
          (next.cue&&next.cue.armable?` — dites « ${(next.cue.phrases||[])[0]||next.cue.label} »`+(next.cue.armed?'':' (pas encore armé)'):''):'Dernier élément.';
        const el=view.elapsed||{},ms=itemElapsedMs();
        ui.clock.textContent=clock(ms)+(el.item_target_ms?` / ${clock(el.item_target_ms)}`:'');
        ui.clock.setAttribute('data-over',el.item_target_ms&&ms>el.item_target_ms?'1':'0');
        ui.clock.title=el.item_target_ms?'Temps passé sur cet élément / objectif souple (jamais une limite)':'Temps passé sur cet élément';
        const lines=[];
        if(view.jarvis_speaks)lines.push('Jarvis présente : mode réglé sur SIMPLE pour cette lecture, rétabli à l\'arrêt ; votre préférence est inchangée.');
        if(view.art_direction==='unchecked')lines.push('Direction artistique non vérifiée.');
        lines.push(...problems);
        if(lost)lines.push(`Core ne répond plus depuis ${Math.round((now()-linkLostSince)/1000)} s : l'état affiché peut être périmé.`);
        if(notice)lines.push(notice.text);
        if(inflight)lines.push(`${inflight.verb}… ${Math.round((now()-inflight.at)/1000)} s`);
        ui.note.textContent=lines.join(' ');
        const busy=!!inflight;
        ui.prev.disabled=busy||phase==='detour'||phase==='paused'||phase==='resuming';
        ui.nextBtn.disabled=busy||phase==='detour'||phase==='paused'||phase==='resuming'||phase==='ended';
        ui.pause.disabled=busy||phase==='detour'||phase==='ended';
        ui.pause.textContent=phase==='paused'?'Reprendre':'Pause';
        ui.full.disabled=busy||!view.stage_object_id||!fullscreen;
        ui.stop.disabled=false;ui.stop.textContent='Arrêter';
        ui.dismiss.hidden=true;ui.keys.hidden=false;
      }else{
        const ended=view.last_run||{};
        ui.role.textContent='Présentation';ui.phase.textContent=PHASE_LABEL.stopped;ui.clock.textContent='';
        ui.where.textContent=ended.reason==='mode_changed_by_user'?'Lecture arrêtée : mode changé par vous.':
          ended.reason==='crashed'?'Lecture interrompue par une erreur de Core.':'Lecture arrêtée.';
        ui.item.textContent='';ui.next.textContent='';
        const lines=(ended.problems||[]).map(code=>PROBLEMS[code]||`Problème : ${code}`);
        if(lost)lines.push(`Core ne répond plus depuis ${Math.round((now()-linkLostSince)/1000)} s.`);
        if(notice)lines.push(notice.text);
        ui.note.textContent=lines.join(' ');
        [ui.prev,ui.pause,ui.nextBtn,ui.full,ui.stop].forEach(b=>{b.hidden=true});
        ui.dismiss.hidden=false;ui.keys.hidden=true;
      }
      if(activeRun())[ui.prev,ui.pause,ui.nextBtn,ui.full,ui.stop].forEach(b=>{b.hidden=false});
    }

    /* ---------------------------------------------------------------- vue venue de Core */
    function adopt(next){
      const was=view;
      view=next&&typeof next==='object'?next:{phase:'idle',running:false};
      viewAt=now();
      prepareStage();
      if(notice&&notice.until!==null&&now()>=notice.until)notice=null;
      render();
    }
    function setNotice(text,kind,ms){notice={text,kind:kind||'info',until:ms?now()+ms:null};render()}

    /* ---------------------------------------------------------------- réseau */
    async function call(url,options){
      const timeoutMs=options.timeoutMs||COMMAND_TIMEOUT_MS;
      let timer=null;
      const timeout=new Promise((_,reject)=>{timer=setT(()=>reject(new Error(`Core ne répond pas depuis ${Math.round(timeoutMs/1000)} s`)),timeoutMs)});
      try{return await Promise.race([request(url,options),timeout])}
      finally{if(timer!==null)clearT(timer)}
    }

    async function refresh(){
      stats.polls++;
      try{
        const answer=await call(ROUTE,{method:'GET',timeoutMs:6000});
        if(answer.status!==200){
          const error=answer.body&&answer.body.error||{};
          throw new Error(String(error.message||`HTTP ${answer.status}`)+(error.code?` (${error.code})`:''));
        }
        failures=0;
        if(linkLostSince!==null){linkLostSince=null;log('info','studio.link_restored',{})}
        adopt(answer.body&&answer.body.state);
      }catch(error){
        failures++;stats.pollFailures++;
        log('warn','studio.poll_failed',{error:messageOf(error),failures});
        if(failures>=LINK_LOST_AFTER&&linkLostSince===null&&(activeRun()||view.phase==='stopped')){
          linkLostSince=now();
          if(toast)toast({title:'Lecture : Core injoignable',sub:messageOf(error),kind:'bad'});
          console.error('[studio] studio.link_lost '+JSON.stringify({error:messageOf(error)}));
        }
        render();
      }
    }
    function schedule(){
      if(!started||!visible)return;
      if(pollTimer!==null)clearT(pollTimer);
      const base=activeRun()?POLL_ACTIVE_MS:POLL_IDLE_MS;
      const delay=failures?Math.min(POLL_BACKOFF_MAX_MS,base*Math.pow(2,failures-1)):base;
      pollTimer=setT(async()=>{pollTimer=null;await refresh();schedule()},delay);
    }

    /* ---------------------------------------------------------------- commandes */
    function command(verb,body){
      if(queued>=QUEUE_MAX){stats.dropped++;log('warn','studio.command_dropped',{verb});return Promise.resolve(null)}
      queued++;
      const run=queue.then(()=>send(verb,body||{}));
      queue=run.catch(()=>null).then(()=>{queued--});
      return run;
    }
    async function send(verb,body){
      stats.commands++;
      inflight={verb,at:now()};
      render();
      try{
        const answer=await call(`${ROUTE}/${encodeURIComponent(verb)}`,{method:'POST',body:JSON.stringify(body),timeoutMs:COMMAND_TIMEOUT_MS});
        const payload=answer.body||{};
        if(answer.status===200&&payload.status==='applied'){
          notice=null;adopt(payload.state);return payload;
        }
        if(answer.status===409&&payload.status==='refused'){
          stats.refused++;
          adopt(payload.state||view);
          setNotice(REFUSALS[payload.reason]||payload.message||'Commande refusée.','info',6000);
          log('info','studio.refused',{verb,reason:payload.reason});
          return payload;
        }
        if(payload.status==='stage_failed'){
          stats.failed++;
          adopt(payload.state||view);
          const text=`La scène n'a pas suivi : ${payload.message||payload.reason||'cause inconnue'}`;
          setNotice(text,'problem',null);
          if(toast)toast({title:'Lecture : la scène n\'a pas suivi',sub:String(payload.message||payload.reason||''),kind:'bad'});
          console.error('[studio] studio.stage_failed '+JSON.stringify({verb,reason:payload.reason,message:payload.message}));
          return payload;
        }
        const error=payload.error||{};
        throw new Error(String(error.message||`HTTP ${answer.status}`)+(error.code?` (${error.code})`:''));
      }catch(error){
        stats.failed++;
        const text=`${verb} impossible : ${messageOf(error)}`;
        setNotice(text,'problem',null);
        if(toast)toast({title:'Lecture : commande impossible',sub:messageOf(error),kind:'bad'});
        console.error('[studio] studio.command_failed '+JSON.stringify({verb,error:messageOf(error)}));
        return null;
      }finally{
        inflight=null;render();
      }
    }

    /* ---------------------------------------------------------------- clavier : sur l'élément hôte */
    function navigate(action){
      if(!activeRun())return false;
      if(action==='next'){command('next');return true}
      if(action==='previous'){command('previous');return true}
      if(action==='first'){command('goto',{position:1});return true}
      if(action==='last'){command('goto',{position:(view.position&&view.position.of)||1});return true}
      if(action==='toggle_pause'){command(view.phase==='paused'?'resume':'pause');return true}
      if(action==='pause'){if(view.phase==='playing'){command('pause');return true}return false}
      return false;
    }
    function handleKey(event){
      if(!activeRun()||event.defaultPrevented||event.ctrlKey||event.altKey||event.metaKey)return false;
      if(editable(event.target))return false;
      const action=KEYS[event.key];
      if(!action)return false;
      if(!navigate(action))return false;
      stats.keys++;
      event.preventDefault();
      return true;
    }
    function stageElement(){
      const id=view.stage_object_id;
      if(!id)return doc.getElementById('sceneLayer');
      for(const el of Array.from(doc.querySelectorAll('[data-object-id]'))){
        if(el.dataset&&el.dataset.objectId===id&&el.isConnected!==false)return el;
      }
      return null;   /* the stage window is not on screen (yet): no key acts on another window */
    }
    /* Le clavier est lu sur le corps de la page (les touches y remontent), mais n'agit que si la cible est DANS l'hôte du stage :
       l'élément de la fenêtre peut naître après l'état de Core (le rendu de la scène a son propre rythme) et un écouteur posé sur lui
       dépendrait de l'ordre des deux. La touche déjà traitée par la couche plein écran est `defaultPrevented` : `handleKey` l'ignore. */
    function onBodyKey(event){
      if(!activeRun())return;
      const host=stageElement();
      if(!host||!event.target||!host.contains(event.target))return;
      handleKey(event);
    }
    function prepareStage(){
      const el=activeRun()?stageElement():null;
      if(el===stageEl)return;
      stageEl=el;
      if(el&&!el.hasAttribute('tabindex'))el.setAttribute('tabindex','-1');   /* focalisable au clic : c'est ainsi que le clavier arrive */
      if(el)log('info','studio.stage_ready',{object_id:view.stage_object_id||null});
    }

    /* ---------------------------------------------------------------- plein écran */
    async function enterFullscreen(){
      if(!fullscreen||!view.stage_object_id)return null;
      let result;
      try{
        result=await fullscreen.enter({object_id:view.stage_object_id,keys:'host'});
      }catch(error){
        setNotice(`Plein écran impossible : ${messageOf(error)}`,'problem',null);
        console.error('[studio] studio.fullscreen_failed '+JSON.stringify({error:messageOf(error)}));
        return null;
      }
      if(result&&result.state==='entered')return result;
      const why=result&&result.reason?` ${result.reason}`:'';
      const text=result&&result.state==='unsupported'?`Plein écran indisponible dans ce navigateur.${why}`:
        result&&result.state==='needs_gesture'?'Cliquez l\'invite pour entrer en plein écran.':
        `Plein écran refusé.${why}`;
      setNotice(text,result&&result.state==='needs_gesture'?'info':'problem',8000);
      log('warn','studio.fullscreen_not_entered',{state:result&&result.state,code:result&&result.code});
      return result;
    }

    /* ---------------------------------------------------------------- cycle de vie */
    function start(){
      if(started)return;
      started=true;
      build();
      doc.body.addEventListener('keydown',onBodyKey);
      if(fullscreen&&typeof fullscreen.onNavigate==='function'){
        unsubscribeNav=fullscreen.onNavigate(event=>{navigate(event&&event.action)});
      }
      ticker=setI(()=>{if(activeRun()||linkLostSince!==null||inflight)render()},1000);
      refresh().then(schedule);
    }
    function stop(){
      started=false;
      if(pollTimer!==null){clearT(pollTimer);pollTimer=null}
      if(ticker!==null){clearI(ticker);ticker=null}
      if(unsubscribeNav){unsubscribeNav();unsubscribeNav=null}
      doc.body.removeEventListener('keydown',onBodyKey);
      stageEl=null;
    }
    function setVisible(value){
      const next=!!value;if(next===visible)return;visible=next;
      if(!visible){if(pollTimer!==null){clearT(pollTimer);pollTimer=null}return}
      if(started)refresh().then(schedule);
    }

    return {start,stop,setVisible,refresh,command,navigate,handleKey,enterFullscreen,render,adopt,
      view:()=>view,band:()=>band,stageElement:()=>stageEl,stats:()=>Object.assign({},stats),
      state:()=>({inflight,failures,linkLostSince,notice,started,visible}),
      /* Pour l'explorateur de variantes (Slice 18) : démarre une lecture par la MÊME route que la voix. */
      startRun:(presentationId,role,extra)=>command('start',Object.assign({presentation_id:presentationId,role},extra||{}))};
  }

  const api=Object.freeze({ROUTE,KEYS,ROLE_LABEL,PHASE_LABEL,REFUSALS,PROBLEMS,COMMAND_TIMEOUT_MS,POLL_ACTIVE_MS,POLL_IDLE_MS,
    BAND_ID,STYLE,STYLE_ID,createStudioPlayer,clock});
  root.JarvisStudioPlayerCore=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installStudioPlayer(){
    const request=async(url,options)=>{
      const response=await fetch(url,{method:options.method||'GET',headers:options.body?{'Content-Type':'application/json'}:undefined,
        body:options.body});
      let body=null;
      try{body=await response.json()}catch(error){body=null /* non-JSON answer: the caller reports the HTTP status */}
      return {status:response.status,body};
    };
    const player=createStudioPlayer({document,window,request,fullscreen:window.JarvisFullscreen||null,
      toast:typeof toast==='function'?toast:null});
    document.addEventListener('visibilitychange',()=>player.setVisible(document.visibilityState!=='hidden'));
    window.JarvisStudioPlayer=Object.freeze({start:player.start,stop:player.stop,refresh:player.refresh,command:player.command,
      startRun:player.startRun,navigate:player.navigate,enterFullscreen:player.enterFullscreen,view:player.view,stats:player.stats});
    player.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la scène avec elle. */
  try{installStudioPlayer()}
  catch(error){console.error('[studio] studio.player_not_installed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
