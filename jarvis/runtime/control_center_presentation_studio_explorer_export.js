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
   - **Un échec se dit.** Une phrase française par code connu (`EXPORT_ERRORS`), le code de Core en petit à côté (et son détail anglais
     pour un code inconnu) ; « Réessayer » seulement quand un nouvel essai peut réussir (réseau, délai, Core injoignable, rendu échoué, variante
     relue), jamais pour un poste sans moteur, une copie qui lit un Board en direct, une vidéo pas prête ni un rendu dont l'échec se répéterait
     à l'identique (`JOB_FAILURES` : une scène qui lève, un rendu ou un fichier trop gros, une composition qui ne correspond pas). Trois lectures d'état ratées de
     suite : l'erreur reste affichée.
     Chaque étape est journalisée (`[studio-explorer] video_export_*`, `warn` / `error` pour un échec).
   - **Le résultat est un Artefact.** Terminé : son identifiant, sa taille, « Ouvrir la vidéo » (le fichier servi par Jarvis) ; il apparaît
     aussi dans les Artefacts du Board. Un export lancé ailleurs (voix, autre fenêtre) sur la même vidéo entière est repris à l'ouverture.
   - **Une copie chez l'utilisateur, seulement sur son geste** (presentation-edition-v1 Slice 03, `docs/export.md`). « Enregistrer une
     copie dans Documents » COPIE l'Artefact terminé (`POST /api/exports {artifact_id}`) : jamais un chemin, jamais automatique. En cours :
     pastille et secondes ; fait : le `display_path` rendu par Core (numéroté si le nom était pris ; « déjà là » si les mêmes octets y
     sont) ; refus : sa phrase et son code. Aucun chemin en dur ici : la racine est celle que Core dit. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,HOST_ID}=Core;
  const Studio=()=>root.JarvisRemotionStudioCore||(typeof require==='function'?require('./control_center_remotion_studio.js'):null);
  const JOBS='/api/local-capabilities/remotion/render/jobs';
  const EXPORTS='/api/exports';
  const SAVE_DEADLINE_MS=125000;    // the relay waits 120 s for a copy of up to 512 MiB
  const SAVE_LABEL='Enregistrer une copie dans Documents';
  /* An explicit copy to the user's folder refused or failed, in the user's words (`docs/export.md` › *Errors*). */
  const SAVE_ERRORS=Object.freeze({
    export_destination_unavailable:'Le dossier Documents de ce poste est introuvable : rien n’a été copié.',
    export_destination_unsafe:'Le dossier d’export est un lien ou une jonction, ou il n’est pas sur ce poste : Jarvis n’y écrit pas. Rien n’a été copié.',
    export_destination_forbidden:'Le dossier d’export se trouve dans les données internes de Jarvis : refusé, rien n’a été copié.',
    export_collision_exhausted:'Tous les noms de ce fichier sont déjà pris dans le dossier d’export : rien n’a été écrasé.',
    export_source_unavailable:'Le fichier interne de cet export est absent ou ne correspond plus à son enregistrement : exportez de nouveau.',
    export_source_not_exportable:'Cet Artefact n’est pas un fichier final : rien n’a été copié.',
    export_source_not_found:'Cet Artefact n’existe plus : rien n’a été copié.',
    export_failed:'La copie n’a pas pu être écrite (disque plein, chemin trop long ou refus du système) : rien n’a été gardé.',
    export_invalid:'Jarvis a refusé cette demande de copie : rien n’a été copié.',
    export_unavailable:'La copie dans Documents n’est pas disponible sur ce poste : rien n’a été copié.',
  });
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
/* The small print wraps inside the line (Slice 09 polish, R3): Core's code and English detail are one long word-less run at 1280×720. */
#${HOST_ID} .jvx-vx-code{flex:0 1 auto;min-width:0;max-width:100%;font:11px/1.3 ui-monospace,Consolas,monospace;color:var(--jvx-mute);overflow-wrap:anywhere}
#${HOST_ID} .jvx-vx-code[hidden]{display:none}
#${HOST_ID} .jvx-vx-link{color:var(--jvx-accent);font-weight:600;text-underline-offset:3px;white-space:nowrap}
#${HOST_ID} .jvx-vx .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-theater:fullscreen .jvx-stage-note>[data-act="video_export"],#${HOST_ID} .jvx-theater:fullscreen .jvx-vx{display:none}
`;

  /* A refusal in the user's words (QA Slice 08 polish): what happened and what to do; `retry` only when another try can work. The code
     stays visible in small print beside the sentence. */
  const NO_ENGINE='L’export vidéo n’est pas disponible sur ce poste (moteur Remotion absent).';
  const EXPORT_ERRORS=Object.freeze({
    presentation_render_unavailable:{text:NO_ENGINE,retry:false},
    presentation_render_runtime_unavailable:{text:NO_ENGINE,retry:false},
    presentation_render_browser_unavailable:{text:'L’export vidéo n’est pas disponible sur ce poste : aucun Chrome ni Edge n’a été trouvé pour le rendu.',retry:false},
    remotion_studio_unavailable:{text:NO_ENGINE,retry:false},
    live_ref_not_authorised:{text:'Les scènes lisent en direct des fichiers d’un Board : lancez l’export depuis les Artefacts de ce Board.',retry:false},
    presentation_studio_stale_revision:{text:'La variante a changé depuis sa lecture : elle est relue, relancez l’export.',retry:true},
    presentation_render_queue_full:{text:'La file d’export de Core est pleine : réessayez quand un export en cours sera fini.',retry:true},
    presentation_render_no_job:{text:'Core n’a rendu aucun travail d’export.',retry:true},
    presentation_render_snapshot_invalid:{text:'Jarvis n’a pas pu préparer la copie figée de cette variante : rien n’a été exporté. Le motif de Core est noté à côté.',retry:false,detail:true},
  });
  /* A failed render job whose failure a retry of the same frozen variant would repeat (Slice 09 polish, R3): no « Réessayer », the sentence
     says what to change. Any other job failure (crash, timeout, interruption, full disk, …) stays retryable. */
  const JOB_FAILURES=Object.freeze({
    presentation_render_master_scene_failed:{text:'Export de la vidéo entière échoué : une scène a échoué pendant le rendu, aucun fichier n’a été gardé. Corrigez-la, puis exportez de nouveau.'},
    presentation_render_composition_mismatch:{text:'Export de la vidéo entière échoué : la composition rendue n’est pas celle du projet, aucun fichier n’a été gardé.'},
    presentation_render_job_too_large:{text:'Export de la vidéo entière échoué : le rendu dépasse la place permise pour un export, aucun fichier n’a été gardé.'},
    presentation_render_output_too_large:{text:'Export de la vidéo entière échoué : la vidéo produite dépasse la taille permise, aucun fichier n’a été gardé.'},
  });
  /* `scene n (pss_…) failed while rendering: …` (Core's `error_detail` of `presentation_render_master_scene_failed`) -> n, or 0. */
  function failedScenePosition(detail){
    const match=/\bscene (\d{1,3}) \(/.exec(String(detail||''));
    return match?Number(match[1]):0;
  }
  /* A failed render job in the user's words: {text, retry}. */
  function describeJobFailure(job){
    const code=job&&job.error_code||'presentation_render_failed';
    const known=JOB_FAILURES[code];
    if(!known)return {text:'Export de la vidéo entière échoué : aucun fichier n’a été gardé.',retry:true};
    const n=code==='presentation_render_master_scene_failed'?failedScenePosition(job.error_detail):0;
    return {text:n?`Export de la vidéo entière échoué : la scène ${n} a échoué pendant le rendu, aucun fichier n’a été gardé. Corrigez la scène ${n}, puis exportez de nouveau.`:known.text,retry:false};
  }
  /* Transient failures: the request or a read did not get through, nothing says the export cannot work. */
  const TRANSIENT=new Set(['network','timeout','core_unreachable','core_timeout','http_error']);
  /* `error`: {code, status, message, info}. Returns {code, text, detail, retry}. */
  function describeExportError(error){
    const code=error&&error.code||'network',info=error&&error.info||{};
    if(code==='presentation_render_master_incompatible'){
      const C=Studio();
      return {code,text:info.reason&&C?C.masterReasonSentence(info.reason,info.detail):'La vidéo entière n’est pas prête : rien n’a été exporté.',detail:'',retry:false};
    }
    const known=EXPORT_ERRORS[code];
    if(known)return {code,text:known.text,detail:known.detail?cleanLine(error&&error.message,160):'',retry:known.retry};
    const detail=cleanLine(error&&error.message,160);
    if(code==='timeout')return {code,text:`Core n’a pas répondu à temps (${detail}) : l’export a peut-être démarré ; réessayer reprend le même.`,detail:'',retry:true};
    if(TRANSIENT.has(code)||!(error&&error.status)||error.status>=500)return {code,text:'La demande d’export n’a pas abouti : Core est injoignable ou en erreur.',detail,retry:true};
    return {code,text:'Core a refusé l’export de la vidéo entière.',detail,retry:false};
  }

  const fmtDuration=s=>{const C=Studio();return C?C.fmtDuration(s):`${Math.round(s)} s`};
  function fmtBytes(n){
    if(!(n>=0))return '';
    if(n<1024*1024)return `${Math.max(1,Math.round(n/1024))} Ko`;
    return `${String(Math.round(n/1024/1024*10)/10).replace('.',',')} Mo`;
  }
  const sceneCount=n=>`${n} scène${n>1?'s':''}`;
  function facts(plan){
    const c=plan&&plan.composition||{};
    const n=Array.isArray(plan&&plan.scenes)?plan.scenes.length:0;
    const seconds=c.fps>0&&Number.isInteger(c.duration_in_frames)?`${String(Math.round(c.duration_in_frames/c.fps*10)/10).replace('.',',')} s`:null;
    return {count:n,scenes:sceneCount(n),seconds};
  }

  /* The pure model: the button and the line, from the master view and the export state. `i` :
     {master:{state,plan,error,loading}, run, x:{status,job,error,started,cancelling,pollErrors,lost}|null, explain, now}. */
  function exportModel(i){
    const m=i.master||{state:'idle'},plan=m.plan,x=i.x||null;
    const C=Studio();
    let blocked=null;
    if(i.run)blocked='Une présentation est en cours : l’export de la vidéo se lance à son arrêt (« Arrêter »).';
    else if(plan&&plan.status==='incompatible')blocked=`${C.masterReasonSentence(plan.reason,plan.detail)} Exportez plutôt les scènes une à une depuis les Artefacts du Board.`;
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
      let text=`Export de la vidéo entière (${job.scene_count?sceneCount(job.scene_count):f.scenes}) — ${bits.join(' · ')}`;
      if(x.pollErrors)text+=` · lecture de l’état en échec (${x.pollErrors}/${POLL_FAILURES})`;
      status={tone:'',spin:true,text,cancel:job.can_cancel!==false&&!x.cancelling,cancelling:!!x.cancelling};
      if(x.cancelling)status.text+=' · annulation demandée…';
    }else if(x&&x.status==='lost'){
      status={tone:'warn',text:`Aucune fin lue après ${elapsed} : l’export continue peut-être dans Core ; son résultat apparaîtra dans les Artefacts du Board.`,dismiss:true};
    }else if(x&&x.status==='error'){
      status={tone:'danger',text:x.error.text,code:x.error.detail?`${x.error.code} · ${x.error.detail}`:x.error.code,retry:!!x.error.retry&&!blocked,dismiss:true};
    }else if(x&&x.status==='done'&&x.job){
      const job=x.job;
      if(job.state==='complete'){
        const size=fmtBytes(job.size_bytes);
        status={tone:'ok',text:job.deduplicated?`Vidéo entière déjà exportée à l’identique : Artefact ${job.artifact_id}${size?` (${size})`:''}, rien n’a été refait.`
          :`Vidéo entière exportée : Artefact ${job.artifact_id}${size?` (${size})`:''}.`,
          link:{url:`/api/artifacts/${encodeURIComponent(job.artifact_id)}/payload`,label:'Ouvrir la vidéo'},dismiss:true};
        const save=x.save||null;
        status.save=!save||save.status==='error';
        if(save&&save.status==='saving'){
          status.spin=true;status.tone='';status.text+=` Copie en cours… ${fmtDuration(Math.max(0,(i.now-save.started)/1000))}`;
        }else if(save&&save.status==='saved'){
          const r=save.result||{},where=r.destination&&r.destination.display_path||r.file_name||'le dossier d’export';
          status.text+=r.already_exported?` Déjà dans ${where} : rien n’a été recopié.`
            :` Copie enregistrée : ${where}${r.renamed?' (le nom était pris : numéroté, rien n’a été écrasé)':''}.`;
          status.save=false;
        }else if(save&&save.status==='error'){
          status.tone='danger';status.text+=` ${save.error.text}`;status.code=save.error.code+(save.error.detail?` · ${save.error.detail}`:'');
        }
      }else if(job.state==='cancelled'){
        status={tone:'warn',text:'Export de la vidéo entière annulé : aucun fichier n’a été gardé.',retry:!blocked,dismiss:true};
      }else{
        /* A failed render is retried by « Réessayer » unless the failure would repeat (`JOB_FAILURES`). Core's English detail goes to the small
           print with its code. */
        const detail=cleanLine(job.error_detail,160),why=describeJobFailure(job);
        status={tone:'danger',text:why.text,
          code:`${job.error_code||'presentation_render_failed'}${detail?` · ${detail}`:''}`,retry:why.retry&&!blocked,dismiss:true};
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
      ui.code=el('span','jvx-vx-code');ui.code.hidden=true;
      ui.link=el('a','jvx-vx-link');attrs(ui.link,{target:'_blank',rel:'noopener noreferrer'});ui.link.hidden=true;
      ui.cancel=ctx.button('Annuler l’export','jvx-btn',()=>{cancel({via:'button'})},{attrs:{'data-act':'video_export_cancel'}});ui.cancel.hidden=true;
      ui.retry=ctx.button('Réessayer','jvx-btn',()=>{start({via:'retry'})},{attrs:{'data-act':'video_export_retry'}});ui.retry.hidden=true;
      ui.dismiss=ctx.button('Fermer','jvx-btn',()=>{dismiss()},{attrs:{'data-act':'video_export_dismiss'}});ui.dismiss.hidden=true;
      ui.save=ctx.button(SAVE_LABEL,'jvx-btn',()=>{save({via:'button'})},{attrs:{'data-act':'video_export_save'}});ui.save.hidden=true;
      for(const node of [ui.text,ui.code,ui.link,ui.save,ui.cancel,ui.retry,ui.dismiss])ui.status.appendChild(node);
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
      ui.code.hidden=!s.code;
      if(s.code&&ui.code.textContent!==s.code)ui.code.textContent=s.code;
      ui.link.hidden=!s.link;
      if(s.link){ui.link.textContent=s.link.label;ui.link.setAttribute('href',s.link.url)}
      ui.cancel.hidden=!s.cancel;
      ui.retry.hidden=!s.retry;
      ui.dismiss.hidden=!s.dismiss;
      ui.save.hidden=!s.save;
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
        x.status='error';x.error=describeExportError(error);
        log('video_export_failed',{code:x.error.code,status:error.status,retry:x.error.retry,message:cleanLine(error.message,160)},
          error.status>=500||!error.status?'error':'warn');
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
              x.status='error';x.error={code:error.code||'network',detail:cleanLine(error.message,120),retry:true,
                text:`L’état de l’export n’a pas pu être lu ${POLL_FAILURES} fois de suite : il continue peut-être dans Core ; son résultat apparaîtra dans les Artefacts du Board.`};
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
      /* Said to the page (Sessions & Boards › Artefacts re-reads the Board's renders: the new one appears there without a reload). */
      if(typeof root.dispatchEvent==='function'&&typeof root.CustomEvent==='function'){
        try{root.dispatchEvent(new root.CustomEvent('jarvis:presentation-render-finished',{detail:{job_id:job.job_id||null,state:job.state||null,artifact_id:job.artifact_id||null}}))}
        catch(error){log('render_finished_event_failed',{error:cleanLine(error&&error.message,120)},'warn')}
      }
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
    /* « Enregistrer une copie dans Documents » : a COPY of the finished Artifact, only on this click (never automatic, never a path). */
    async function save(options){
      const x=S.x,o=options||{};
      const job=x&&x.job;
      if(!x||x.status!=='done'||!job||job.state!=='complete'||!job.artifact_id)return {state:'refused'};
      if(x.save&&x.save.status==='saving')return {state:'busy'};
      const attempt=x.save={status:'saving',started:now(),result:null,error:null};
      render();tick();
      log('video_export_save_requested',{via:o.via,artifact:job.artifact_id});
      try{
        const body=await call('POST',EXPORTS,{artifact_id:job.artifact_id},SAVE_DEADLINE_MS);
        if(x.save!==attempt)return {state:'superseded'};
        attempt.status='saved';attempt.result=body.export||{};
        log('video_export_saved',{artifact:job.artifact_id,file_name:attempt.result.file_name,renamed:!!attempt.result.renamed,size:attempt.result.size_bytes});
        announce(attempt.result.already_exported?'Cette copie est déjà dans vos documents.':'Copie enregistrée dans vos documents.');
        return {state:'saved',result:attempt.result};
      }catch(error){
        if(x.save!==attempt)return {state:'superseded'};
        const code=error.code||'network';
        const known=SAVE_ERRORS[code];
        attempt.status='error';
        attempt.error={code,text:known||(code==='timeout'?'Core n’a pas répondu à temps : la copie a peut-être été faite, regardez dans le dossier d’export avant de réessayer.'
          :'La copie n’a pas abouti.'),detail:known&&code!=='export_failed'?'':cleanLine(error.message,160)};
        log('video_export_save_failed',{artifact:job.artifact_id,code,status:error.status,message:cleanLine(error.message,160)},
          error.status>=500||!error.status?'error':'warn');
        return {state:'failed',code};
      }finally{render()}
    }
    function dismiss(){
      if(S.x&&(S.x.status==='starting'||S.x.status==='running'))return;
      if(S.x&&S.x.save&&S.x.save.status==='saving')return;
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
    return Object.freeze({buildButton,buildStatus,render,sync,stop,start,cancel,save,model,
      state:()=>({status:S.x&&S.x.status||'idle',job:S.x&&S.x.job,error:S.x&&S.x.error,explain:S.explain})});
  }

  const api=Object.freeze({createVideoExport,exportModel,describeExportError,describeJobFailure,EXPORT_ERRORS,JOB_FAILURES,SAVE_ERRORS,CSS,PHASES});
  root.JarvisVariantsVideoExport=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
