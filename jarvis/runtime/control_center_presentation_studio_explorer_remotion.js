/* « Remotion Studio » dans Variantes (handoff jarvis-remotion-native-studio-playback-fix, Slice 11 ; contrat `docs/presentation-studio.md` ›
   *Remotion Studio from Variants (Level 3, Slice 11)*, § 1, § 6 #22, PX-1, PX-2).

   Module DOM exposé en `window.JarvisVariantsRemotionStudio` dans la page et en `module.exports` pour node. Variantes lui prête la scène à l'écran
   (présentation, variante, scène, son pin EXACT `{id, version}`), sa boîte de dialogue, sa pause et son journal ; il ne garde AUCUN état de
   présentation. Le processus natif `remotion studio`, son état et ses codes sont ceux de Core (`docs/remotion-studio.md`), lus par le relais
   `/api/local-capabilities/remotion/studio*` avec le client, la confirmation et les phrases de la carte du dialogue MCP
   (`JarvisRemotionStudioCore`, `control_center_remotion_studio.js`) : une porte de plus, pas un second client.

   Règles tenues ici :
   - **Deux espaces voisins, une identité.** Le bouton « Remotion Studio » de la ligne de scène ouvre LA scène à l'écran, à son pin exact (jamais
     « la dernière version »), dans l'onglet de Remotion Studio, l'interface native intacte : rien de Remotion Studio n'est dessiné ici, aucune
     ligne de temps n'est recopiée (SLICE 11 étape 4). Variantes reste ouvert, tel quel : variante, scène, image et arbre ne bougent pas ; la
     vidéo est mise en pause (une seule lecture à la fois). Le retour est l'onglet de Jarvis : au retour (`focus`, `visibilitychange`), l'état
     de Remotion Studio est relu et dit.
   - **Une seule autorité de source.** Ce que Remotion Studio modifie n'atteint jamais la variante (la publication est la Slice 12) : les
     fichiers modifiés sont comptés et dits « pas publiés », jamais « enregistrés ». Un pin différent (autre scène, autre version de la même
     source) est dit, jamais corrigé en silence.
   - **Rien sans clic ni confirmation.** La confirmation « hors du bac à sable » (risque, version, provenance de CETTE version) précède tout
     lancement ; « Annuler » ne lance rien. Le cerveau n'a pas de chemin ici (aucune commande, aucun outil).
   - **Ce qui attend se voit, un échec se dit.** Démarrage : compteur de secondes et échéance (2 min) ; échec : la phrase du code, le code, le
     journal de Remotion Studio, « Réessayer » ; environnement absent ou pas prêt : le bouton dit pourquoi au clic. Chaque échec est
     journalisé (`[studio-explorer] remotion_studio_*`, `obsClientLog` au niveau `warn` / `error`).
   - **Permission du navigateur.** Un onglet ne s'ouvre seul que tant que le clic de confirmation est récent (activation utilisateur) ; après
     un démarrage long, le navigateur le bloquerait : la ligne d'état offre alors « Ouvrir l'onglet Remotion Studio » (un vrai lien, un clic). */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const {cleanLine,HOST_ID}=Core;
  /* Le noyau de la carte : chargé après Variantes dans la page (lu à l'usage), requis par node. */
  const Studio=()=>root.JarvisRemotionStudioCore||(typeof require==='function'?require('./control_center_remotion_studio.js'):null);
  const TAB_NAME='jarvis-remotion-studio';
  const POLL_FAST_MS=2000;
  const POLL_READY_MS=15000;
  /* Sans `navigator.userActivation` : un clic de moins de 4 s est encore une permission d'ouvrir un onglet (Chrome en accorde 5). */
  const ACTIVATION_MS=4000;
  const DIAG_LINES=8;

  const CSS=`
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"]{margin-left:auto;min-height:30px;padding:0 12px;font-size:12px;flex:none}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"]+[data-act="present"]{margin-left:0}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][aria-disabled="true"]{opacity:.55;cursor:default}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][data-state="here"]{border-color:var(--jvx-ok);color:var(--jvx-ok)}
#${HOST_ID} .jvx-stage-note>[data-act="remotion_studio"][data-state="here"]::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
#${HOST_ID} .jvx-rms{flex:1 1 100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;min-width:0;margin:0;font-size:12.5px;color:var(--jvx-mute)}
#${HOST_ID} .jvx-rms[hidden]{display:none}
#${HOST_ID} .jvx-rms[data-tone="ok"] .jvx-rms-text{color:var(--jvx-ok)}
#${HOST_ID} .jvx-rms[data-tone="warn"] .jvx-rms-text{color:var(--jvx-warn)}
#${HOST_ID} .jvx-rms[data-tone="danger"] .jvx-rms-text{color:var(--jvx-danger)}
#${HOST_ID} .jvx-rms-text{min-width:0;flex:1 1 18em}
#${HOST_ID} .jvx-rms[data-spin="true"] .jvx-rms-text::before{content:"";display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:var(--jvx-accent);vertical-align:1px}
@media (prefers-reduced-motion:no-preference){#${HOST_ID} .jvx-rms[data-spin="true"] .jvx-rms-text::before{animation:jvxPulse 1.1s ease-in-out infinite}}
#${HOST_ID} .jvx-rms-link{color:var(--jvx-accent);font-weight:600;text-underline-offset:3px;white-space:nowrap}
#${HOST_ID} .jvx-rms .jvx-btn{min-height:28px;padding:0 10px;font-size:12px}
#${HOST_ID} .jvx-rms-log{flex:1 1 100%;min-width:0}
#${HOST_ID} .jvx-rms-log pre{margin:4px 0 0;max-height:7.5em;overflow:auto;white-space:pre-wrap;font:11.5px/1.35 ui-monospace,Consolas,monospace;color:var(--jvx-mute)}
#${HOST_ID} .jvx-theater:fullscreen .jvx-stage-note>[data-act="remotion_studio"],#${HOST_ID} .jvx-theater:fullscreen .jvx-rms{display:none}
`;

  /* Remotion ou HTML : la règle de `jarvis/domain/prefab.py` › `is_remotion_manifest` (v2 toujours ; v3 quand elle porte `source`), lue
     dans le manifeste brut que rend `GET /api/prefabs/{id}/{version}`. */
  function isRemotionManifest(manifest){
    if(!manifest||typeof manifest!=='object')return false;
    const v=manifest.schema_version;
    return v===2||(v===3&&Object.prototype.hasOwnProperty.call(manifest,'source'));
  }
  const RUNNABLE=new Set(['ready','running']);
  const plural=(n,one,many)=>`${n} ${n>1?many:one}`;

  /* Le modèle (pur) de la porte : le bouton et la ligne d'état, depuis la scène à l'écran et la vue de Core. `i` :
     {scene:{id,title,number,of,prefab}|null, scenes:[{id,title,prefab}], detail:{state,remotion}|null, studio, capability, readError,
      busy:{label,at}|null, actionError:{code,text}|null, run, needsClick, explain, now}. */
  function doorModel(i){
    const C=Studio();
    const scene=i.scene||null,st=i.studio||null,cap=i.capability||null,mine=scene&&scene.prefab;
    let blocked=null;
    if(i.run)blocked='Une présentation est en cours : Remotion Studio s’ouvre à son arrêt (« Arrêter »).';
    else if(!scene)blocked='Aucune scène à l’écran : choisissez une variante et une scène.';
    else if(!mine)blocked='Cette scène ne désigne aucune source : rien à ouvrir dans Remotion Studio.';
    else if(i.detail&&i.detail.state==='ready'&&!i.detail.remotion)blocked='Cette scène n’est pas une scène Remotion : Remotion Studio n’ouvre que les scènes Remotion.';
    else if(i.readError&&i.readError.code==='remotion_studio_unavailable')blocked='Ce Jarvis n’a pas de Remotion Studio (Core sans environnement Remotion).';
    else if(cap&&cap.status&&!RUNNABLE.has(cap.status)){
      const label=(C.CAPABILITY[cap.status]||{label:String(cap.status)}).label;
      blocked=`L’environnement Remotion n’est pas prêt (${label.toLowerCase()}) : installez-le ou réparez-le (carte « Présentations · moteur », onglet « Plugins externes » du dialogue MCP), puis réessayez.`;
    }
    const pin=st&&st.pin||null;
    const relation=!st||st.status!=='ready'||!pin||!mine?'none':pin.prefab_id===mine.id?(Number(pin.version)===Number(mine.version)?'here':'version'):'other';
    const button={label:'Remotion Studio',state:relation==='here'?'here':'idle',blocked,ariaLabel:'Remotion Studio',
      title:blocked||'Ouvrir la scène à l’écran dans Remotion Studio (un onglet à part, après confirmation)'};
    if(relation==='here'){button.ariaLabel='Remotion Studio, ouvert sur cette scène';button.title='Afficher l’onglet Remotion Studio de cette scène'}
    let status=null;
    const elapsed=since=>C.fmtDuration(Math.max(0,since));
    if(i.busy){
      button.state='busy';
      status={tone:'',spin:true,text:`${i.busy.label} ${elapsed((i.now-i.busy.at)/1000)} (${C.START_LIMIT_S/60} min au plus).`};
    }else if(i.actionError){
      status={tone:'danger',text:`Remotion Studio : ${i.actionError.text} (${i.actionError.code})`,retry:true};
    }else if(st&&st.status==='starting'){
      button.state='busy';
      status={tone:'',spin:true,text:`Remotion Studio démarre… ${elapsed(st.started_at?i.now/1000-st.started_at:0)} (${C.START_LIMIT_S/60} min au plus).`};
    }else if(st&&st.status==='stopping'){
      status={tone:'',spin:true,text:'Remotion Studio s’arrête…'};
    }else if(st&&st.status==='failed'){
      const code=st.last_error_code||'remotion_studio_failed';
      status={tone:'danger',text:`Remotion Studio est en échec : ${C.errorText(code)||cleanLine(st.last_error_detail,160)||'raison inconnue'} (${code})`,
        retry:!blocked,diagnostics:(st.diagnostics||[]).slice(-DIAG_LINES)};
    }else if(relation!=='none'){
      const parts=[];let tone='ok',link=null;
      if(relation==='here'){
        parts.push(i.needsClick?'Remotion Studio est prêt sur cette scène. Le navigateur n’ouvre un onglet qu’après un clic :'
          :`Remotion Studio est ouvert sur cette scène (source v${mine.version}), dans un autre onglet.`);
        link={url:st.url,label:i.needsClick||!(st.viewers>0)?'Ouvrir l’onglet Remotion Studio':'Afficher l’onglet Remotion Studio'};
      }else if(relation==='version'){
        tone='warn';
        parts.push(`Remotion Studio montre la version ${pin.version} de cette scène ; la variante utilise la version ${mine.version}. « Remotion Studio » y affiche la version de la variante, après confirmation.`);
      }else{
        tone='';
        const other=(i.scenes||[]).findIndex(s=>s.prefab&&s.prefab.id===pin.prefab_id&&Number(s.prefab.version)===Number(pin.version));
        const name=other>=0?`la scène ${other+1} (« ${cleanLine(i.scenes[other].title,50)} »)`:`une autre source (${cleanLine(pin.prefab_id,60)} v${pin.version})`;
        parts.push(`Remotion Studio est ouvert sur ${name}. « Remotion Studio » y affiche cette scène, après confirmation.`);
      }
      const wc=st.work_copy||{},modified=(wc.modified_files||[]).length,saved=wc.edits_saved||0;
      if(modified){tone='warn';parts.push(`${plural(modified,'fichier modifié','fichiers modifiés')} dans Remotion Studio : pas publiés, la variante n’a pas changé ; ils seront mis de côté à sa fermeture.`)}
      else if(saved)parts.push(`${plural(saved,'fichier modifié','fichiers modifiés')} dans Remotion Studio, mis de côté : pas publiés.`);
      status={tone,text:parts.join(' '),link};
    }else if(i.explain){
      status={tone:'warn',text:i.explain};
    }
    return {button,status,relation};
  }

  /* `ctx` : {doc,win,el,attrs,clear,button,later,cancelLater,now,log,announce,fetch,dialog:{open,close,current},
     scene()->{presentationId,variantId,variantNumber,scene,index,scenes}|null, running()->bool, pause()->void, isOpen()->bool} */
  function createRemotionDoor(ctx){
    const {doc,win,el,attrs,clear,later,cancelLater,now,log,announce}=ctx;
    const S={studio:null,capability:null,readError:null,busy:null,actionError:null,needsClick:false,explain:null,
      details:new Map(),started:false,poll:null,ticker:null,reading:null,generation:0,lastOk:null};
    const ui={};
    let client=null;
    const C=()=>Studio();
    function api(){
      if(client)return client;
      const core=C();
      if(!core||!ctx.fetch)return null;
      client=core.createClient({fetchImpl:(path,options)=>ctx.fetch(path,options),setTimeoutImpl:later,clearTimeoutImpl:cancelLater});
      return client;
    }
    const keyOf=prefab=>prefab?`${prefab.id}@${prefab.version}`:'';
    function view(){
      const at=ctx.scene();
      const scene=at&&at.scene?{id:at.scene.id,title:at.scene.title,number:at.index+1,of:at.scenes.length,prefab:at.scene.prefab}:null;
      return {at,scene,input:{scene,scenes:at?at.scenes:[],detail:scene?S.details.get(keyOf(scene.prefab))||null:null,studio:S.studio,capability:S.capability,
        readError:S.readError,busy:S.busy,actionError:S.actionError,run:ctx.running(),needsClick:S.needsClick,explain:S.explain,now:now()}};
    }
    function model(){return doorModel(view().input)}

    /* -------------------------------------------------------------- DOM */
    function buildButton(){
      ui.button=ctx.button('Remotion Studio','jvx-btn',()=>{request({via:'button'})},{attrs:{'data-act':'remotion_studio',
        title:'Ouvrir la scène à l’écran dans Remotion Studio (un onglet à part, après confirmation)'}});
      return ui.button;
    }
    function buildStatus(){
      ui.status=el('div','jvx-rms');ui.status.hidden=true;
      ui.text=el('span','jvx-rms-text');attrs(ui.text,{role:'status','aria-live':'polite'});
      ui.link=el('a','jvx-rms-link');attrs(ui.link,{target:'_blank',rel:'noopener noreferrer'});ui.link.hidden=true;
      ui.link.addEventListener('click',()=>{S.needsClick=false;log('remotion_studio_tab_opened',{via:'link'});later(render,0)});
      ui.retry=ctx.button('Réessayer','jvx-btn',()=>{S.actionError=null;request({via:'retry'})},{attrs:{'data-act':'remotion_studio_retry'}});ui.retry.hidden=true;
      ui.log=el('details','jvx-rms-log');ui.log.hidden=true;
      ui.log.appendChild(el('summary','','Journal de Remotion Studio'));ui.logText=el('pre');ui.log.appendChild(ui.logText);
      for(const node of [ui.text,ui.link,ui.retry,ui.log])ui.status.appendChild(node);
      return ui.status;
    }
    function render(){
      if(!ui.button)return;
      const m=model();
      const b=m.button;
      attrs(ui.button,{'aria-disabled':b.blocked||b.state==='busy'?'true':'false','aria-label':b.ariaLabel,title:b.title,'data-state':b.state});
      const s=m.status;
      ui.status.hidden=!s;
      if(!s)return;
      ui.status.setAttribute('data-tone',s.tone||'');ui.status.setAttribute('data-spin',s.spin?'true':'false');
      if(ui.text.textContent!==s.text)ui.text.textContent=s.text;
      ui.link.hidden=!s.link;
      if(s.link){ui.link.textContent=s.link.label;ui.link.setAttribute('href',s.link.url)}
      ui.retry.hidden=!s.retry;
      ui.log.hidden=!(s.diagnostics&&s.diagnostics.length);
      if(s.diagnostics&&s.diagnostics.length)ui.logText.textContent=s.diagnostics.map(line=>cleanLine(line,200)).join('\n');
    }

    /* -------------------------------------------------------------- lecture de l'état (Core) */
    async function refresh(reason){
      const c=api();
      if(!c||!ctx.isOpen())return;
      if(S.reading)return S.reading;
      const generation=S.generation;
      S.reading=(async()=>{
        try{
          const [studio,capability]=await Promise.all([c.studio(),c.capability().catch(error=>{
            /* intentional: without the capability view the button stays usable; Core's own refusal says why at the click */
            log('remotion_capability_read_failed',{code:error.code,status:error.status});return null})]);
          if(generation!==S.generation)return;
          S.studio=studio;S.capability=capability;S.readError=null;
          if(S.lastOk===false)log('remotion_studio_read_restored',{status:studio&&studio.status});
          S.lastOk=true;
        }catch(error){
          if(generation!==S.generation)return;
          const core=C();
          S.readError={code:error.code||'network',text:core&&core.errorText(error.code)||cleanLine(error.message,140)||'aucune réponse'};
          /* The first failed read of a page whose Core has no Remotion Studio is a normal state (said at the click); a read that WORKED
             and then fails is a fault, logged at `warn`. */
          log('remotion_studio_read_failed',{code:S.readError.code,status:error.status,reason},S.lastOk===true?'warn':undefined);
          S.lastOk=false;
        }finally{S.reading=null}
        render();schedule();
      })();
      return S.reading;
    }
    function hidden(){return !!doc&&doc.visibilityState==='hidden'}
    function schedule(){
      if(S.poll){cancelLater(S.poll);S.poll=null}
      if(!S.started||!ctx.isOpen()||hidden())return;
      const st=S.studio&&S.studio.status;
      const ms=S.busy||st==='starting'||st==='stopping'?POLL_FAST_MS:st==='ready'?POLL_READY_MS:0;
      if(ms)S.poll=later(()=>{S.poll=null;refresh('poll')},ms);
    }
    function tick(on){
      if(on&&!S.ticker){const step=()=>{S.ticker=later(()=>{S.ticker=null;render();if(S.busy||(S.studio&&S.studio.status==='starting'))step()},1000)};step()}
      if(!on&&S.ticker){cancelLater(S.ticker);S.ticker=null}
    }
    /* The return path: coming back to Jarvis's tab (or window) re-reads Remotion Studio and says what changed there. */
    function onBack(){if(S.started&&!hidden())refresh('return')}
    function start(){
      if(S.started)return;
      S.started=true;S.generation+=1;
      if(win&&typeof win.addEventListener==='function')win.addEventListener('focus',onBack);
      if(doc&&typeof doc.addEventListener==='function')doc.addEventListener('visibilitychange',onBack);
      render();refresh('open');
    }
    function stop(){
      if(!S.started)return;
      S.started=false;S.generation+=1;
      if(S.poll){cancelLater(S.poll);S.poll=null}
      tick(false);
      if(win&&typeof win.removeEventListener==='function')win.removeEventListener('focus',onBack);
      if(doc&&typeof doc.removeEventListener==='function')doc.removeEventListener('visibilitychange',onBack);
      S.explain=null;S.actionError=null;S.needsClick=false;S.details.clear();
    }

    /* -------------------------------------------------------------- la scène : Remotion ? provenance ? (lu une fois par pin) */
    function sync(){
      const v=view();
      if(S.explain&&!(v.scene&&model().button.blocked===S.explain))S.explain=null;
      const prefab=v.scene&&v.scene.prefab;
      const key=keyOf(prefab);
      if(prefab&&ctx.isOpen()&&!S.details.has(key))loadDetail(prefab);
      render();
    }
    async function loadDetail(prefab){
      const key=keyOf(prefab);
      const record={state:'loading',remotion:null,provenance:null};
      S.details.set(key,record);
      const c=api();
      if(!c){record.state='error';return record}
      try{
        const payload=await ctx.fetch(`/api/prefabs/${encodeURIComponent(prefab.id)}/${Number(prefab.version)}`,{method:'GET',cache:'no-store'});
        let body=null;
        try{body=await payload.json()}catch(_error){body=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
        if(!payload.ok)throw Object.assign(new Error(body&&body.error&&body.error.message||`HTTP ${payload.status}`),{code:body&&body.error&&body.error.code||`http_${payload.status}`});
        record.state='ready';record.remotion=isRemotionManifest(body&&body.manifest);
        record.provenance=body&&body.publication&&body.publication.provenance||null;
      }catch(error){
        /* Unknown is not « not Remotion »: the button stays usable, the click re-reads, Core refuses a wrong pin by its own code. */
        record.state='error';record.code=error.code||'network';
        log('remotion_scene_read_failed',{prefab:key,code:record.code});
      }
      render();
      return record;
    }

    /* -------------------------------------------------------------- la confirmation (dans la couche de Variantes) */
    function confirm(sceneView,detail,kind,returnFocus){
      const core=C();
      const label=`Scène ${sceneView.number} sur ${sceneView.of} « ${cleanLine(sceneView.title,60)} » · source v${sceneView.prefab.version}`;
      const spec=core.confirmSpec({id:sceneView.prefab.id,version:sceneView.prefab.version,label},detail&&detail.state==='ready'?detail.provenance:null,kind);
      return new Promise(resolve=>{
        let settled=false;
        const finish=value=>{if(settled)return;settled=true;resolve(value)};
        const dlg=ctx.dialog.open({kind:'remotion_studio',titleId:'jvxDialogTitle',returnFocus,onClose:()=>finish(false)});
        dlg.box.setAttribute('data-kind','remotion_studio');
        const h=el('h2','',spec.title);h.id='jvxDialogTitle';dlg.box.appendChild(h);
        const list=el('ul','jvx-confirm-lines');
        for(const [head,text] of spec.lines){const li=el('li');li.appendChild(el('strong','',head));li.appendChild(doc.createTextNode(text));list.appendChild(li)}
        dlg.box.appendChild(list);
        dlg.box.appendChild(el('p','','Variantes reste ouvert ici, sur cette scène. Ce que vous changez dans Remotion Studio n’est pas publié dans la variante.'));
        const actions=el('div','jvx-dialog-actions');
        const cancel=ctx.dialogButton(spec.cancelLabel,()=>{ctx.dialog.close(true);finish(false)});
        const go=ctx.dialogButton(spec.confirmLabel,()=>{finish(true);ctx.dialog.close(true)},{primary:true,danger:spec.danger});
        go.setAttribute('data-act','remotion_studio_confirm');
        actions.appendChild(cancel);actions.appendChild(go);dlg.box.appendChild(actions);
        (spec.danger?cancel:go).focus({preventScroll:true});
      });
    }

    /* -------------------------------------------------------------- ouvrir */
    function activationLive(){
      const ua=win&&win.navigator&&win.navigator.userActivation;
      if(ua&&typeof ua.isActive==='boolean')return ua.isActive;
      return !!S.busy&&now()-S.busy.at<ACTIVATION_MS;
    }
    function openTab(url,via){
      try{win.open(url,TAB_NAME,'noopener,noreferrer')}
      catch(error){log('remotion_studio_tab_failed',{via,error:cleanLine(error&&error.message,120)},'warn');S.needsClick=true;return false}
      log('remotion_studio_tab_opened',{via});
      return true;
    }
    async function request(options){
      const o=options||{};
      if(!ctx.isOpen())return {state:'refused',reason:'Variantes est fermé.'};
      if(S.busy){announce('Remotion Studio démarre déjà.');return {state:'busy'}}
      const v=view(),m=doorModel(v.input);
      if(m.button.blocked){
        S.explain=m.button.blocked;render();
        log('remotion_studio_blocked',{via:o.via,why:m.button.blocked.slice(0,60)});
        return {state:'refused',reason:m.button.blocked};
      }
      const core=C(),c=api();
      if(!core||!c){
        S.actionError={code:'remotion_studio_page_error',text:'le module de Remotion Studio n’est pas chargé dans cette page.'};render();
        log('remotion_studio_module_missing',{},'error');
        return {state:'failed',code:'remotion_studio_page_error'};
      }
      const sc=v.scene,st=S.studio;
      if(m.relation==='here'&&st.url){S.needsClick=!openTab(st.url,'button');render();return {state:'shown',url:st.url}}
      let detail=S.details.get(keyOf(sc.prefab));
      if(!detail||detail.state!=='ready')detail=await loadDetail(sc.prefab);
      if(detail.state==='ready'&&!detail.remotion){const again=doorModel(view().input);S.explain=again.button.blocked;render();return {state:'refused',reason:S.explain}}
      const kind=st&&st.status==='ready'?'switch':'open';
      const ok=await confirm(sc,detail,kind,o.returnFocus||ui.button);
      if(!ok){log('remotion_studio_cancelled',{via:o.via});announce('Remotion Studio : rien n’a été lancé.');return {state:'cancelled'}}
      /* Still the scene that was confirmed? (a poll, a hot reload or the user may have moved while the dialog was open) */
      const now2=view().scene;
      if(!now2||keyOf(now2.prefab)!==keyOf(sc.prefab)){S.explain='La scène a changé pendant la confirmation : rien n’a été lancé.';render();return {state:'cancelled'}}
      ctx.pause();
      S.busy={label:kind==='switch'?'Remotion Studio change de scène…':'Remotion Studio démarre…',at:now()};
      S.actionError=null;S.explain=null;S.needsClick=false;S.generation+=1;
      render();tick(true);schedule();
      log('remotion_studio_open_requested',{via:o.via,kind,prefab:keyOf(sc.prefab),scene_id:sc.id});
      let result;
      try{
        const studio=await c.write('open',{prefab_id:sc.prefab.id,version:Number(sc.prefab.version)});
        S.studio=studio;S.readError=null;S.lastOk=true;
        if(studio.status==='failed'){
          log('remotion_studio_open_failed',{code:studio.last_error_code,prefab:keyOf(sc.prefab)},'error');
          result={state:'failed',code:studio.last_error_code};
        }else if(studio.status==='ready'&&studio.url){
          const live=activationLive();
          S.needsClick=!live||!openTab(studio.url,'auto');
          if(S.needsClick)announce('Remotion Studio est prêt : cliquez « Ouvrir l’onglet Remotion Studio ».');
          log('remotion_studio_ready',{seconds:Math.round((now()-S.busy.at)/1000),tab:S.needsClick?'needs_click':'opened'});
          result={state:'ready',url:studio.url,tab:S.needsClick?'needs_click':'opened'};
        }else result={state:studio.status};
      }catch(error){
        S.actionError={code:error.code||'network',text:core.errorText(error.code)||cleanLine(error.message,160)||'l’action a échoué'};
        log('remotion_studio_open_failed',{code:S.actionError.code,status:error.status,prefab:keyOf(sc.prefab)},'error');
        result={state:'failed',code:S.actionError.code};
      }finally{
        S.busy=null;tick(false);render();
      }
      refresh('after_open');
      return result;
    }

    return Object.freeze({buildButton,buildStatus,render,sync,start,stop,refresh:()=>refresh('api'),request,model,
      state:()=>({studio:S.studio&&{status:S.studio.status,pin:S.studio.pin,url:S.studio.url},busy:!!S.busy,needsClick:S.needsClick,
        error:S.actionError,readError:S.readError,explain:S.explain})});
  }

  const api=Object.freeze({createRemotionDoor,doorModel,isRemotionManifest,CSS,TAB_NAME});
  root.JarvisVariantsRemotionStudio=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
