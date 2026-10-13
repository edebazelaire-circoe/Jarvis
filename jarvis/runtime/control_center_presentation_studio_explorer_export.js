/* « Exporter la vidéo » dans Variantes (handoff jarvis-remotion-master-project-studio-export, Slice 08 ; contrat
   `docs/remotion-master-project.md` § 10, § 13, `docs/presentation-studio.md` › *Remotion Studio from Variants*).

   Module DOM exposé en `window.JarvisVariantsVideoExport` dans la page et en `module.exports` pour node. Variantes lui prête la variante à
   l'écran (présentation, variante, révisions, titre), la préparation de la vidéo entière que la porte « Remotion Studio » a lue (la MÊME vue de
   Core, `GET .../master-project` : jamais une seconde lecture ni un calcul de compatibilité ici) et son journal.

   Règles tenues ici :
   - **Une action, la vidéo entière.** « Exporter la vidéo » fige la variante à l'écran (révisions exactes) et demande à Core le rendu de son
     projet maître (`settings.scope: "master"`, MP4) par la route d'export existante (`POST /api/local-capabilities/remotion/render/jobs`).
     Jamais une scène présentée comme la vidéo, jamais un collage d'extraits. Pas prête : le bouton est inerte et dit la phrase du § 3.
   - **Ce qui attend se voit.** Demande puis rendu : pastille animée, phase en mots, images faites sur le total, secondes écoulées, délai de
     Core ; « Annuler l'export » tant que Core l'accepte. Le suivi a une échéance (le délai du travail + 2 min) : passée, la ligne le dit.
   - **Un échec se dit.** Le code et la phrase de Core, « Réessayer » ; trois lectures d'état ratées de suite : l'erreur reste affichée.
     Chaque étape est journalisée (`[studio-explorer] video_export_*`, `warn` / `error` pour un échec).
   - **Le résultat est un Artefact.** Terminé : son identifiant, sa taille, « Ouvrir la vidéo » (le fichier servi par Jarvis) ; il apparaît
     aussi dans les Artefacts du Board. Un export lancé ailleurs (voix, autre fenêtre) sur la même vidéo entière est repris à l'ouverture. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,HOST_ID}=Core;
  const Studio=()=>root.JarvisRemotionStudioCore||(typeof require==='function'?require('./control_center_remotion_studio.js'):null);
  const JOBS='/api/local-capabilities/remotion/render/jobs';
  const POLL_MS=2000;
  const POLL_FAILURES=3;
  const POST_DEADLINE_MS=65000;     // the relay answers in 60 s at most (freeze + package check)
  const READ_DEADLINE_MS=15000;
  const FOLLOW_MARGIN_S=120;        // the follow-up outlives Core's own job timeout by 2 min, then says so
  const TERMINAL=new Set(['complete','failed','cancelled']);
  /* Core's phases in words (the Board's list, `control_center_workspace.js`, says « scène » where a master job bundles the whole video). */
  const PHASES=Object.freeze({queued:'En file d’attente',preparing:'Préparation de la copie figée',bundling:'Empaquetage de la vidéo entière',
    opening_browser:'Ouverture du navigateur de rendu',selecting_composition:'Lecture de la composition',rendering:'Rendu des images',
    encoding:'Encodage',verifying:'Vérification du fichier',storing:'Enregistrement de l’Artefact',complete:'Terminé',failed:'Échoué',cancelled:'Annulé'});

  const CSS=`
#${HOST_ID} .jvx-stage-note>[data-act="video_export"]{min-height:30px;padding:0 12px;font-size:12px;flex:none}
#${HOST_ID} .jvx-stage-note>[data-act="video_export"][aria-disabled="true"]{opacity:.55;cursor:default}
#${HOST_ID} .jvx-vx{flex:1 1 100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;min-width:0;margin:0;font-size:12.5px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-vx[hidden]{display:none}
#${HOST_ID} .jvx-vx-text{min-width:0;flex:1 1 18em;font-variant-numeric:tabular-nums}
#${HOST_ID} .jvx-vx[data-tone="ok"] .jvx-vx-text{color:var(--jvx-ok)}
#${HOST_ID} .jvx-vx[data-tone="warn"] .jvx-vx-text{color:var(--jvx-warn)}
#${HOST_ID} .jvx-vx[data-tone="danger"] .jvx-vx-text{color:var(--jvx-danger)}
#${HOST_ID} .jvx-vx[data-spin="true"] .jvx-vx-text::before{content:"";display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:var(--jvx-accent);vertical-align:1px}
@media (prefers-reduced-motion:no-preference){#${HOST_ID} .jvx-vx[data-spin="true"] .jvx-vx-text::before{animation:jvxPulse 1.1s ease-in-out infinite}}
#${HOST_ID} .jvx-vx-link{color:var(--jvx-accent);font-weight:600;text-underline-offset:3px;white-space:nowrap}
#${HOST_ID} .jvx-vx .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-theater:fullscreen .jvx-stage-note>[data-act="video_export"],#${HOST_ID} .jvx-theater:fullscreen .jvx-vx{display:none}
`;

  const fmtDuration=s=>{const C=Studio();return C?C.fmtDuration(s):`${Math.round(s)} s`};
  function fmtBytes(n){
    if(!(n>=0))return '';
    if(n<1024*1024)return `${Math.max(1,Math.round(n/1024))} Ko`;
    return `${String(Math.round(n/1024/1024*10)/10).replace('.',',')} Mo`;
  }
  function facts(plan){
    const c=plan&&plan.composition||{};
    const n=Array.isArray(plan&&plan.scenes)?plan.scenes.length:0;
    const seconds=c.fps>0&&Number.isInteger(c.duration_in_frames)?`${String(Math.round(c.duration_in_frames/c.fps*10)/10).replace('.',',')} s`:null;
    return {count:n,scenes:`${n} scène${n>1?'s':''}`,seconds};
  }

  /* The pure model: the button and the line, from the master view and the export state. `i` :
     {master:{state,plan,error,loading}, run, x:{status,job,error,started,cancelling,pollErrors,lost}|null, explain, now}. */
  function exportModel(i){
    const m=i.master||{state:'idle'},plan=m.plan,x=i.x||null;
    const C=Studio();
    let blocked=null;
    if(i.run)blocked='Une présentation est en cours : l’export de la vidéo se lance à son arrêt (« Arrêter »).';
    else if(plan&&plan.status==='incompatible')blocked=`Vidéo entière indisponible : ${C.masterReasonSentence(plan.reason,plan.detail)} Chaque scène reste exportable depuis les Artefacts du Board.`;
    else if(!plan&&m.state==='error')blocked=`La vidéo entière n’a pas pu être lue (${m.error&&m.error.code||'erreur'}) : cliquez pour réessayer.`;
    else if(!plan)blocked='Lecture de la vidéo entière…';
    const f=facts(plan);
    const busy=!!x&&(x.status==='starting'||x.status==='running');
    const button={label:'Exporter la vidéo',blocked,state:busy?'busy':'idle',retryRead:!plan&&m.state==='error'&&!i.run,
      title:blocked||(busy?'Un export de la vidéo entière est en cours (ci-dessous).'
        :`Rendre la vidéo entière (${f.scenes}${f.seconds?`, ${f.seconds}`:''}) en MP4 : un Artefact relié à une copie figée de la variante`)};
    let status=null;
    const elapsed=x&&x.started?fmtDuration(Math.max(0,(i.now-x.started)/1000)):'';
    if(x&&x.status==='starting'){
      status={tone:'',spin:true,text:`Export de la vidéo entière : demande envoyée, la variante est figée… ${elapsed}`};
    }else if(x&&x.status==='running'){
      const job=x.job||{};
      const bits=[PHASES[job.phase]||cleanLine(job.phase,40)||'…'];
      if(job.frames_total)bits.push(`${job.frames_done||0}/${job.frames_total} images (${job.percent||0} %)`);
      if(job.queue_position)bits.push(`${job.queue_position}e en file`);
      bits.push(elapsed);
      if(job.timeout_s)bits.push(`délai ${Math.round(job.timeout_s/60)} min au plus`);
      let text=`Export de la vidéo entière (${job.scene_count?`${job.scene_count} scènes`:f.scenes}) — ${bits.join(' · ')}`;
      if(x.pollErrors)text+=` · lecture de l’état en échec (${x.pollErrors}/${POLL_FAILURES})`;
      status={tone:'',spin:true,text,cancel:job.can_cancel!==false&&!x.cancelling,cancelling:!!x.cancelling};
      if(x.cancelling)status.text+=' · annulation demandée…';
    }else if(x&&x.status==='lost'){
      status={tone:'warn',text:`Aucune fin lue après ${elapsed} : l’export continue peut-être dans Core ; son résultat apparaîtra dans les Artefacts du Board.`,dismiss:true};
    }else if(x&&x.status==='error'){
      status={tone:'danger',text:`Export impossible : ${x.error.text} (${x.error.code})`,retry:!blocked,dismiss:true};
    }else if(x&&x.status==='done'&&x.job){
      const job=x.job;
      if(job.state==='complete'){
        const size=fmtBytes(job.size_bytes);
        status={tone:'ok',text:job.deduplicated?`Vidéo entière déjà exportée à l’identique : Artefact ${job.artifact_id}${size?` (${size})`:''}, rien n’a été refait.`
          :`Vidéo entière exportée : Artefact ${job.artifact_id}${size?` (${size})`:''}.`,
          link:{url:`/api/artifacts/${encodeURIComponent(job.artifact_id)}/payload`,label:'Ouvrir la vidéo'},dismiss:true};
      }else if(job.state==='cancelled'){
        status={tone:'warn',text:'Export de la vidéo entière annulé : aucun fichier n’a été gardé.',retry:!blocked,dismiss:true};
      }else{
        status={tone:'danger',text:`Export de la vidéo entière échoué : ${cleanLine(job.error_detail,200)||'raison inconnue'} (${job.error_code||'presentation_render_failed'})`,
          retry:!blocked,dismiss:true};
      }
    }else if(i.explain){
      status={tone:'warn',text:i.explain};
    }
    return {button,status};
  }

  /* `ctx` : {doc,el,attrs,button,later,cancelLater,now,log,announce,fetch,isOpen()->bool,running()->bool,
     scene()->{presentationId,variantId,revision,presentationRevision}|null, master()->{state,plan,error,loading}, rereadMaster()->Promise,
     reload()->Promise (relit la variante : une révision périmée)} */
  function createVideoExport(ctx){
    const {el,attrs,later,cancelLater,now,log,announce}=ctx;
    const S={x:null,explain:null,ticker:null,generation:0,restoredFor:''};
    const ui={};

    async function call(method,path,body,deadline){
      const controller=typeof AbortController!=='undefined'?new AbortController():null;
      const timer=controller?later(()=>controller.abort(),deadline):null;
      let response;
      try{
        response=await ctx.fetch(path,{method,cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},
          body:body===undefined?undefined:JSON.stringify(body),signal:controller?controller.signal:undefined});
      }catch(error){
        const timeout=error&&error.name==='AbortError';
        throw Object.assign(new Error(timeout?`aucune réponse en ${Math.round(deadline/1000)} s`:cleanLine(error&&error.message,160)||'réseau'),
          {code:timeout?'timeout':'network',status:0});
      }finally{if(timer)cancelLater(timer)}
      let payload=null;
      try{payload=await response.json()}catch(_error){payload=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
      if(!response.ok){
        const e=payload&&payload.error||{};
        throw Object.assign(new Error(e.message||`HTTP ${response.status}`),{code:e.code||`http_${response.status}`,status:response.status,info:e});
      }
      return payload||{};
    }

    function model(){
      return exportModel({master:ctx.master(),run:ctx.running(),x:S.x,explain:S.explain,now:now()});
    }
    function buildButton(){
      ui.button=ctx.button('Exporter la vidéo','jvx-btn',()=>{start({via:'button'})},{attrs:{'data-act':'video_export'}});
      return ui.button;
    }
    function buildStatus(){
      ui.status=el('div','jvx-vx');ui.status.hidden=true;
      ui.text=el('span','jvx-vx-text');attrs(ui.text,{role:'status','aria-live':'polite'});
      ui.link=el('a','jvx-vx-link');attrs(ui.link,{target:'_blank',rel:'noopener noreferrer'});ui.link.hidden=true;
      ui.cancel=ctx.button('Annuler l’export','jvx-btn',()=>{cancel({via:'button'})},{attrs:{'data-act':'video_export_cancel'}});ui.cancel.hidden=true;
      ui.retry=ctx.button('Réessayer','jvx-btn',()=>{start({via:'retry'})},{attrs:{'data-act':'video_export_retry'}});ui.retry.hidden=true;
      ui.dismiss=ctx.button('Fermer','jvx-btn',()=>{dismiss()},{attrs:{'data-act':'video_export_dismiss'}});ui.dismiss.hidden=true;
      for(const node of [ui.text,ui.link,ui.cancel,ui.retry,ui.dismiss])ui.status.appendChild(node);
      return ui.status;
    }
    function render(){
      if(!ui.button)return;
      const m=model(),b=m.button;
      /* Hidden while nothing asked for the whole video (an HTML deck: the door reads it only for a Remotion scene) and during a run. */
      const run=ctx.running();
      ui.button.hidden=run||((!ctx.scene()||ctx.master().state==='idle')&&!S.x);
      attrs(ui.button,{'aria-disabled':b.blocked||b.state==='busy'?'true':'false',title:b.title,'data-state':b.state});
      const s=m.status;
      ui.status.hidden=!s||run;
      if(!s)return;
      ui.status.setAttribute('data-tone',s.tone||'');ui.status.setAttribute('data-spin',s.spin?'true':'false');
      if(ui.text.textContent!==s.text)ui.text.textContent=s.text;
      ui.link.hidden=!s.link;
      if(s.link){ui.link.textContent=s.link.label;ui.link.setAttribute('href',s.link.url)}
      ui.cancel.hidden=!s.cancel;
      ui.retry.hidden=!s.retry;
      ui.dismiss.hidden=!s.dismiss;
    }
    function tick(){
      if(S.ticker)return;
      const step=()=>{S.ticker=later(()=>{S.ticker=null;render();if(S.x&&(S.x.status==='starting'||S.x.status==='running'))step()},1000)};
      step();
    }

    async function start(options){
      const o=options||{};
      if(!ctx.isOpen())return {state:'refused',reason:'Variantes est fermé.'};
      if(S.x&&(S.x.status==='starting'||S.x.status==='running')){announce('Un export de la vidéo entière est déjà en cours.');return {state:'busy'}}
      const m=model();
      if(m.button.retryRead){
        S.explain=null;render();
        log('video_export_master_reread',{via:o.via});
        await ctx.rereadMaster();render();
        return {state:'reread'};
      }
      if(m.button.blocked){
        S.explain=m.button.blocked;S.x=null;render();
        log('video_export_blocked',{via:o.via,why:m.button.blocked.slice(0,60)});
        return {state:'refused',reason:m.button.blocked};
      }
      const at=ctx.scene(),plan=ctx.master().plan;
      if(!at||!Number.isInteger(at.revision)||!Number.isInteger(at.presentationRevision)){
        S.explain='La variante à l’écran n’est pas encore lue : réessayez dans un instant.';render();
        log('video_export_no_basis',{via:o.via},'warn');
        return {state:'refused',reason:S.explain};
      }
      const generation=++S.generation;
      const x=S.x={status:'starting',job:null,error:null,started:now(),pollErrors:0,cancelling:false,variantId:at.variantId,projectKey:plan.project_key};
      S.explain=null;render();tick();
      log('video_export_requested',{via:o.via,variant_id:at.variantId,variant_revision:at.revision,project_key:plan.project_key,scenes:facts(plan).count});
      try{
        const answer=await call('POST',JOBS,{presentation_id:at.presentationId,variant_id:at.variantId,
          expected_presentation_revision:at.presentationRevision,expected_variant_revision:at.revision,format:'mp4',settings:{scope:'master'}},POST_DEADLINE_MS);
        if(S.x!==x||generation!==S.generation)return {state:'superseded'};
        x.job=answer.job||null;
        if(!x.job||!x.job.job_id)throw Object.assign(new Error('Core n’a rendu aucun travail d’export.'),{code:'presentation_render_no_job',status:202});
        x.started=now()-Math.round((Number(x.job.elapsed_s)||0)*1000);
        x.status=TERMINAL.has(x.job.state)?'done':'running';
        log('video_export_started',{job:x.job.job_id,artifact:x.job.artifact_id,state:x.job.state,snapshot_replayed:!!answer.job.snapshot_replayed});
        announce('Export de la vidéo entière lancé.');
      }catch(error){
        if(S.x!==x)return {state:'superseded'};
        const C=Studio(),info=error.info||{};
        let text=cleanLine(error.message,200)||'la demande a échoué';
        if(error.code==='presentation_render_master_incompatible'&&info.reason)text=C.masterReasonSentence(info.reason,info.detail);
        if(error.code==='presentation_studio_stale_revision')text='la variante a changé depuis sa lecture : elle est relue, relancez l’export.';
        x.status='error';x.error={code:error.code||'network',text};
        log('video_export_failed',{code:x.error.code,status:error.status},error.status>=500||!error.status?'error':'warn');
        if(error.code==='presentation_studio_stale_revision'&&ctx.reload)Promise.resolve(ctx.reload()).catch(e=>log('video_export_reload_failed',{error:cleanLine(e&&e.message,120)},'warn'));
        if(error.code==='presentation_render_master_incompatible')ctx.rereadMaster();
        render();
        return {state:'failed',code:x.error.code};
      }
      render();
      if(x.status==='running')follow(x);
      else finish(x);
      return {state:x.status,job:x.job};
    }

    async function follow(x){
      if(x.following)return;
      x.following=true;
      try{
        while(S.x===x&&x.status==='running'){
          await new Promise(resolve=>later(resolve,POLL_MS));
          if(S.x!==x)break;
          const limit=((Number(x.job&&x.job.timeout_s)||600)+FOLLOW_MARGIN_S)*1000;
          if(now()-x.started>limit){
            x.status='lost';log('video_export_follow_expired',{job:x.job.job_id,seconds:Math.round((now()-x.started)/1000)},'warn');render();break;
          }
          try{
            const body=await call('GET',`${JOBS}/${encodeURIComponent(x.job.job_id)}`,undefined,READ_DEADLINE_MS);
            if(S.x!==x)break;
            x.job=body.job||x.job;x.pollErrors=0;
          }catch(error){
            /* A failed read says nothing about the render: said on the line, retried, three in a row and the error stays. */
            x.pollErrors+=1;
            log('video_export_poll_failed',{job:x.job.job_id,code:error.code,status:error.status,count:x.pollErrors},'warn');
            if(x.pollErrors>=POLL_FAILURES){
              x.status='error';x.error={code:error.code||'network',text:`l’état de l’export n’a pas pu être lu ${POLL_FAILURES} fois de suite (${cleanLine(error.message,120)}) ; il continue peut-être dans Core.`};
              log('video_export_lost',{job:x.job.job_id,code:x.error.code},'error');render();break;
            }
          }
          if(TERMINAL.has(x.job.state)){x.status='done';finish(x);break}
          render();
        }
      }finally{x.following=false}
    }
    function finish(x){
      const job=x.job||{};
      const level=job.state==='complete'?undefined:job.state==='cancelled'?'warn':'error';
      log('video_export_finished',{job:job.job_id,state:job.state,artifact:job.artifact_id,code:job.error_code||null,deduplicated:!!job.deduplicated},level);
      if(job.state==='complete')announce('Vidéo entière exportée.');
      render();
    }
    async function cancel(options){
      const x=S.x,o=options||{};
      if(!x||x.status!=='running'||x.cancelling||!x.job)return {state:'refused'};
      x.cancelling=true;render();
      log('video_export_cancel_requested',{via:o.via,job:x.job.job_id});
      try{
        const body=await call('POST',`${JOBS}/${encodeURIComponent(x.job.job_id)}/cancel`,{},45000);
        if(S.x!==x)return {state:'superseded'};
        x.job=body.job||x.job;
        if(TERMINAL.has(x.job.state)){x.status='done';finish(x)}
        return {state:'requested'};
      }catch(error){
        x.cancelling=false;
        S.explain=`L’annulation a échoué : ${cleanLine(error.message,160)} (${error.code||'network'}). L’export continue.`;
        log('video_export_cancel_failed',{job:x.job.job_id,code:error.code,status:error.status},'error');
        return {state:'failed',code:error.code};
      }finally{render()}
    }
    function dismiss(){
      if(S.x&&(S.x.status==='starting'||S.x.status==='running'))return;
      S.x=null;S.explain=null;render();
    }
    /* An export of THIS whole video already running in Core (voice, another window, a reloaded page) is picked up once per key. */
    async function restore(){
      const at=ctx.scene(),m=ctx.master();
      const key=m&&m.plan&&m.plan.status==='ready'?m.plan.project_key:'';
      if(!at||!key||S.restoredFor===key||(S.x&&(S.x.status==='starting'||S.x.status==='running')))return;
      S.restoredFor=key;
      try{
        const body=await call('GET',JOBS,undefined,READ_DEADLINE_MS);
        const job=(Array.isArray(body.jobs)?body.jobs:[]).find(j=>j&&j.scope==='master'&&j.project_key===key&&!TERMINAL.has(j.state));
        if(!job||S.x)return;
        const x=S.x={status:'running',job,error:null,started:now()-Math.round((Number(job.elapsed_s)||0)*1000),pollErrors:0,cancelling:false,
          variantId:at.variantId,projectKey:key};
        log('video_export_restored',{job:job.job_id,state:job.state});
        render();tick();follow(x);
      }catch(error){
        log('video_export_restore_failed',{code:error.code,status:error.status},'warn');
      }
    }
    /* Variants calls this when the master view changed (a new revision, another variant): a finished line of another variant is cleared. */
    function sync(){
      const at=ctx.scene();
      if(S.x&&at&&S.x.variantId!==at.variantId&&S.x.status!=='starting'&&S.x.status!=='running')S.x=null;
      if(S.explain&&!model().button.blocked)S.explain=null;
      render();
      restore();
    }
    function stop(){
      S.generation+=1;S.x=null;S.explain=null;S.restoredFor='';
      if(S.ticker){cancelLater(S.ticker);S.ticker=null}
    }
    return Object.freeze({buildButton,buildStatus,render,sync,stop,start,cancel,model,
      state:()=>({status:S.x&&S.x.status||'idle',job:S.x&&S.x.job,error:S.x&&S.x.error,explain:S.explain})});
  }

  const api=Object.freeze({createVideoExport,exportModel,CSS,PHASES});
  root.JarvisVariantsVideoExport=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
