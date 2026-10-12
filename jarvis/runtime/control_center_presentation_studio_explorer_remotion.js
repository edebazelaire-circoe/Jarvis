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
   - **Une seule autorité de source.** Ce que Remotion Studio modifie n'atteint la variante QUE par « Publier dans la variante… » (Slice 12) :
     une confirmation qui nomme la base et les fichiers, puis Core publie une NOUVELLE version par la porte d'édition de source (compilation,
     conflit si la scène a changé, version précédente intacte) ; « Revenir à … » republie l'ancienne (`restore_version`). Avant, les
     fichiers modifiés sont comptés et dits « pas encore publiés », jamais « enregistrés ». Un pin différent (autre scène, autre version de
     la même source) est dit, jamais corrigé en silence ; changer de scène avec des fichiers non publiés le dit dans la confirmation (ils
     sont mis de côté, `discard_unpublished`).
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
  /* Publication (Slice 12) : Core répond en 135 s au plus (compilation réelle comprise). */
  const PUBLISH_LIMIT_S=150;
  const RESTORE_DEADLINE_MS=90000;

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
#${HOST_ID} .jvx-rms-files{margin:4px 0 0;padding:6px 8px 6px 22px;max-height:12em;overflow:auto;border:1px solid var(--jvx-line-strong);border-radius:6px;font:12px/1.4 ui-monospace,Consolas,monospace}
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
      busy:{label,at}|null, actionError:{code,text}|null, run, needsClick, explain, now,
      publishing:{at,label}|null, published:{published,previous,status,sceneId}|null, publishError:{code,text,diagnostics}|null}. */
  /* L'espace de travail de Remotion Studio (Slice 12) face à la scène à l'écran : 'here' (sa base est le pin de la scène : publiable ici),
     'other' (une autre version ou une autre scène), 'none' (aucune base connue). Vrai que Remotion Studio soit ouvert ou arrêté. */
  function workspaceOf(st,mine){
    const wc=st&&st.work_copy||{};
    const files=Array.isArray(wc.modified_files)?wc.modified_files:[];
    const count=typeof wc.unpublished==='number'?wc.unpublished:files.length;
    const base=wc.base||(st&&st.pin)||null;
    const relation=!base||!mine?'none':base.prefab_id===mine.id&&Number(base.version)===Number(mine.version)?'here':'other';
    /* `digest` : l'empreinte de CETTE liste, renvoyée avec `publish` (Core refuse si l'espace a changé depuis : QA Slice 12, I1).
       `setAside` : ce que le dernier lancement a mis de côté parce que ce n'était pas la forme de l'espace (B1). */
    const setAside=Array.isArray(wc.set_aside)?wc.set_aside:[];
    return {count,files,base,relation,saved:wc.edits_saved||0,digest:typeof wc.digest==='string'?wc.digest:null,setAside};
  }

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
    /* The tab is opened `noopener` (security): a browser cannot bring back a tab opened that way, so a click here opens ANOTHER tab; the words
       say so (Slice 11 QA polish, decided by agent 0: keep `noopener`). */
    if(relation==='here'){button.ariaLabel='Remotion Studio, ouvert sur cette scène';button.title='Ouvrir un autre onglet Remotion Studio sur cette scène (celui déjà ouvert reste où il est)'}
    let status=null;
    const elapsed=since=>C.fmtDuration(Math.max(0,since));
    const ws=workspaceOf(st,mine);
    const publish={offered:false,count:ws.count,files:ws.files,base:ws.base,relation:ws.relation};
    if(i.publishing){
      button.state='busy';
      status={tone:'',spin:true,text:`${i.publishing.label} ${elapsed((i.now-i.publishing.at)/1000)} (${Math.round(PUBLISH_LIMIT_S/60*10)/10} min au plus).`};
      return {button,status,relation,publish};
    }
    /* A refused or finished publication of THIS scene is said first; the files still unpublished (a retouch after a failed build, new
       edits after a publication) are said with it, and « Publier dans la variante… » stays offered. */
    const here=scene&&((i.publishError&&i.publishError.sceneId===scene.id)||(i.published&&i.published.sceneId===scene.id));
    if(here){
      const work=workspaceText(ws,i.scenes,blocked);
      publish.offered=!!(work&&work.offered);
      if(i.publishError&&i.publishError.sceneId===scene.id){
        const e=i.publishError;
        status={tone:'danger',text:`Publication refusée : ${e.text} (${e.code})`,diagnostics:e.diagnostics||[],publish:publish.offered};
      }else{
        const p=i.published,prev=p.previous;
        /* Variants re-reads the variant after a publication (`ctx.reload`): the new version is on screen, nothing to wait for. A first publication
           forks the scene's own source id, so its « v1 » and the base's « v1 » are two different versions: then they are not numbered. */
        const sameSource=prev&&prev.prefab_id===p.published.prefab_id;
        const before=prev?(sameSource?`la v${prev.version}`:'la version d’avant'):'';
        const done=p.status==='already_published'?`Déjà publié : la scène utilise déjà cette version (v${p.published.version}).`
          :p.restored?`Revenu au contenu d’avant : publié comme nouvelle version (v${p.published.version}).`
          :`Publié dans la variante : nouvelle version de la scène (v${p.published.version})${prev?` ; ${before} reste disponible`:''}.`;
        status={tone:work?'warn':'ok',text:work?`${done} ${work.text}`:done,publish:publish.offered,
          revert:prev&&!p.restored&&p.status!=='already_published'?{label:`Revenir à ${before}`,target:prev}:null};
      }
    }
    if(status){/* intentional: said above; the usual lines below are for a scene without a publication outcome */}
    else if(i.busy){
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
        link={url:st.url,label:i.needsClick||!(st.viewers>0)?'Ouvrir l’onglet Remotion Studio':'Ouvrir un autre onglet Remotion Studio'};
      }else if(relation==='version'){
        tone='warn';
        parts.push(`Remotion Studio montre la version ${pin.version} de cette scène ; la variante utilise la version ${mine.version}. « Remotion Studio » y affiche la version de la variante, après confirmation.`);
      }else{
        tone='';
        const other=(i.scenes||[]).findIndex(s=>s.prefab&&s.prefab.id===pin.prefab_id&&Number(s.prefab.version)===Number(pin.version));
        const name=other>=0?`la scène ${other+1} (« ${cleanLine(i.scenes[other].title,50)} »)`:`une autre source (${cleanLine(pin.prefab_id,60)} v${pin.version})`;
        parts.push(`Remotion Studio est ouvert sur ${name}. « Remotion Studio » y affiche cette scène, après confirmation.`);
      }
      const work=workspaceText(ws,i.scenes,blocked);
      if(work){tone='warn';parts.push(work.text);publish.offered=work.offered}
      else if(ws.saved)parts.push(`${plural(ws.saved,'fichier mis','fichiers mis')} de côté (studio-edits) à votre demande : pas ${ws.saved>1?'publiés':'publié'}.`);
      status={tone,text:parts.join(' '),link,publish:publish.offered};
    }else if(ws.count&&workspaceText(ws,i.scenes,blocked)){
      /* Remotion Studio arrêté (fermé, arrêt automatique, Jarvis relancé) : ses fichiers non publiés sont toujours là, publiables ici. */
      const work=workspaceText(ws,i.scenes,blocked);
      publish.offered=work.offered;
      status={tone:'warn',text:work.text,publish:publish.offered};
    }else if(i.explain){
      status={tone:'warn',text:i.explain};
    }
    if(ws.setAside.length&&ws.relation==='here'){
      const n=ws.setAside.length,named=ws.setAside.slice(0,6).map(f=>cleanLine(f,60)).join(', ')+(n>6?'…':'');
      const said=`Au dernier lancement, ${plural(n,'élément étranger','éléments étrangers')} à l’espace de travail (${named}) ${n>1?'ont été mis':'a été mis'} de côté dans studio-edits : jamais ${n>1?'exécutés':'exécuté'} ni ${n>1?'publiés':'publié'}.`;
      status=status?{...status,tone:status.tone==='danger'?'danger':'warn',text:`${status.text} ${said}`}:{tone:'warn',text:said};
    }
    return {button,status,relation,publish};
  }

  function workspaceText(ws,scenes,blocked){
    if(!ws.count)return null;
    const n=plural(ws.count,'fichier modifié','fichiers modifiés'),pub=ws.count>1?'publiés':'publié';
    if(ws.relation==='here')return {offered:!blocked,
      text:`${n} dans Remotion Studio, pas encore ${pub} : la variante n’a pas changé.`};
    const at=(scenes||[]).findIndex(s=>s.prefab&&ws.base&&s.prefab.id===ws.base.prefab_id&&Number(s.prefab.version)===Number(ws.base.version));
    if(at>=0)return {offered:false,text:`${n} dans Remotion Studio sur la scène ${at+1}, pas ${pub} : à publier depuis cette scène-là ; ouvrir celle-ci dans Remotion Studio les mettra de côté (après confirmation).`};
    /* A base that no scene on screen pins: an earlier version of this scene (a publication whose end was interrupted, a « Revenir »), or a
       library version opened from the MCP card. Publishing is offered: Core alone decides (already published -> rebased, else conflict). */
    const where=ws.base?`la version ${ws.base.version} de ${cleanLine(ws.base.prefab_id,60)}`:'une autre version';
    return {offered:!blocked&&!!ws.base,text:`${n} dans Remotion Studio sur ${where}, pas ${pub} ; la scène utilise une autre version : Jarvis vérifiera avant de publier (conflit si elle a changé).`};
  }

  /* `ctx` : {doc,win,el,attrs,clear,button,later,cancelLater,now,log,announce,fetch,dialog:{open,close,current},
     scene()->{presentationId,variantId,variantNumber,revision,scene,index,scenes}|null, running()->bool, pause()->void, isOpen()->bool,
     reload()->Promise (Slice 12 : relit la variante après une publication ou un retour, pour que Variantes montre la nouvelle version)} */
  function createRemotionDoor(ctx){
    const {doc,win,el,attrs,clear,later,cancelLater,now,log,announce}=ctx;
    const S={studio:null,capability:null,readError:null,busy:null,actionError:null,needsClick:false,explain:null,
      details:new Map(),started:false,asked:false,poll:null,ticker:null,reading:null,generation:0,lastOk:null,
      publishing:null,published:null,publishError:null};
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
        readError:S.readError,busy:S.busy,actionError:S.actionError,run:ctx.running(),needsClick:S.needsClick,explain:S.explain,now:now(),
        publishing:S.publishing,published:S.published,publishError:S.publishError}};
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
      ui.publish=ctx.button('Publier dans la variante…','jvx-btn',()=>{publish({via:'button'})},{attrs:{'data-act':'remotion_studio_publish',
        title:'Publier les fichiers modifiés dans Remotion Studio comme nouvelle version de cette scène (après confirmation)'}});ui.publish.hidden=true;
      ui.revert=ctx.button('Revenir','jvx-btn',()=>{revert({via:'button'})},{attrs:{'data-act':'remotion_studio_revert'}});ui.revert.hidden=true;
      ui.log=el('details','jvx-rms-log');ui.log.hidden=true;
      ui.log.appendChild(el('summary','','Journal de Remotion Studio'));ui.logText=el('pre');ui.log.appendChild(ui.logText);
      for(const node of [ui.text,ui.link,ui.publish,ui.revert,ui.retry,ui.log])ui.status.appendChild(node);
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
      ui.publish.hidden=!s.publish;
      ui.revert.hidden=!s.revert;
      if(s.revert&&ui.revert.textContent!==s.revert.label)ui.revert.textContent=s.revert.label;
      ui.log.hidden=!(s.diagnostics&&s.diagnostics.length);
      if(s.diagnostics&&s.diagnostics.length)ui.logText.textContent=s.diagnostics.map(line=>cleanLine(line,200)).join('\n');
    }

    /* -------------------------------------------------------------- lecture de l'état (Core) */
    async function refresh(reason){
      const c=api();
      if(!c||!ctx.isOpen())return;
      S.asked=true;
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
      const ms=S.busy||st==='starting'||st==='stopping'?POLL_FAST_MS:st==='ready'||(S.studio&&S.studio.work_copy&&S.studio.work_copy.unpublished)?POLL_READY_MS:0;
      if(ms)S.poll=later(()=>{S.poll=null;refresh('poll')},ms);
    }
    function tick(on){
      if(on&&!S.ticker){const step=()=>{S.ticker=later(()=>{S.ticker=null;render();if(S.busy||S.publishing||(S.studio&&S.studio.status==='starting'))step()},1000)};step()}
      if(!on&&S.ticker){cancelLater(S.ticker);S.ticker=null}
    }
    /* The return path: coming back to Jarvis's tab (or window) re-reads Remotion Studio and says what changed there. */
    function onBack(){if(S.started&&!hidden()&&S.asked)refresh('return')}
    function start(){
      if(S.started)return;
      S.started=true;S.generation+=1;
      if(win&&typeof win.addEventListener==='function')win.addEventListener('focus',onBack);
      if(doc&&typeof doc.addEventListener==='function')doc.addEventListener('visibilitychange',onBack);
      render();   // Core's Remotion Studio is read once a Remotion scene is on screen (`loadDetail`): an HTML deck never asks
    }
    function stop(){
      if(!S.started)return;
      S.started=false;S.generation+=1;
      if(S.poll){cancelLater(S.poll);S.poll=null}
      tick(false);
      if(win&&typeof win.removeEventListener==='function')win.removeEventListener('focus',onBack);
      if(doc&&typeof doc.removeEventListener==='function')doc.removeEventListener('visibilitychange',onBack);
      S.explain=null;S.actionError=null;S.needsClick=false;S.details.clear();S.asked=false;S.published=null;S.publishError=null;
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
        if(record.remotion&&!S.asked)refresh('scene');   // the first Remotion scene on screen: what is Remotion Studio doing?
      }catch(error){
        /* Unknown is not « not Remotion »: the button stays usable, the click re-reads, Core refuses a wrong pin by its own code. */
        record.state='error';record.code=error.code||'network';
        log('remotion_scene_read_failed',{prefab:key,code:record.code});
      }
      render();
      return record;
    }

    /* -------------------------------------------------------------- la confirmation (dans la couche de Variantes) */
    function confirm(sceneView,detail,kind,returnFocus,discard){
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
        if(discard){const li=el('li');li.setAttribute('data-line','discard');li.appendChild(el('strong','','Fichiers non publiés : '));
          li.appendChild(doc.createTextNode(`${plural(discard.count,'fichier modifié','fichiers modifiés')} dans Remotion Studio (sur v${discard.base.version}) ${discard.count>1?'seront mis':'sera mis'} de côté (studio-edits), pas publiés.`));list.appendChild(li)}
        dlg.box.appendChild(list);
        dlg.box.appendChild(el('p','','Variantes reste ouvert ici, sur cette scène. Ce que vous changez dans Remotion Studio n’atteint la variante que par « Publier dans la variante… ».'));
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
      if(S.busy||S.publishing){announce(S.busy?'Remotion Studio démarre déjà.':'Une publication est en cours.');return {state:'busy'}}
      S.publishError=null;
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
      const ws=workspaceOf(st,sc.prefab);
      const discard=ws.count&&ws.relation==='other'?{count:ws.count,base:ws.base}:null;
      const ok=await confirm(sc,detail,kind,o.returnFocus||ui.button,discard);
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
        const body={prefab_id:sc.prefab.id,version:Number(sc.prefab.version)};
        if(discard)body[core.DISCARD_FIELD]=true;   // the user read the line above: their unpublished files are set aside, never silently
        const studio=await c.write('open',body);
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

    /* -------------------------------------------------------------- publier (Slice 12) */
    function confirmPublish(sc,ws,returnFocus){
      return new Promise(resolve=>{
        let settled=false;
        const finish=value=>{if(settled)return;settled=true;resolve(value)};
        const dlg=ctx.dialog.open({kind:'remotion_studio_publish',titleId:'jvxDialogTitle',returnFocus,onClose:()=>finish(false)});
        dlg.box.setAttribute('data-kind','remotion_studio_publish');
        const h=el('h2','','Publier dans la variante ?');h.id='jvxDialogTitle';dlg.box.appendChild(h);
        const list=el('ul','jvx-confirm-lines');
        const line=(head,text,key)=>{const li=el('li');if(key)li.setAttribute('data-line',key);li.appendChild(el('strong','',head));li.appendChild(doc.createTextNode(text));list.appendChild(li)};
        line('Scène : ',`Scène ${sc.number} sur ${sc.of} « ${cleanLine(sc.title,60)} »`,'scene');
        line('Fichiers : ',`${plural(ws.count,'fichier modifié','fichiers modifiés')} dans Remotion Studio, tous publiés tels quels :`,'files');
        /* Chaque fichier, sans troncature (liste défilante) : ce que Core publiera est exactement cette liste (son empreinte part avec
           la confirmation ; un fichier changé depuis fait refuser la publication). */
        const files=el('ul','jvx-rms-files');files.setAttribute('data-line','files-list');attrs(files,{tabindex:'0','aria-label':`${ws.count} fichiers à publier`});
        for(const f of ws.files)files.appendChild(el('li','',cleanLine(f,160)));
        list.lastChild.appendChild(files);
        line('Ce qui se passe : ',`Jarvis compile la scène puis la publie comme NOUVELLE version ; la v${sc.prefab.version} n’est pas modifiée et reste disponible (« Revenir »).`,'what');
        line('Refusé si : ','la scène a changé depuis l’ouverture dans Remotion Studio, elle ne compile pas, ou elle importe autre chose que react et remotion.','refused');
        dlg.box.appendChild(list);
        const actions=el('div','jvx-dialog-actions');
        const cancel=ctx.dialogButton('Annuler',()=>{ctx.dialog.close(true);finish(false)});
        const go=ctx.dialogButton('Publier',()=>{finish(true);ctx.dialog.close(true)},{primary:true});
        go.setAttribute('data-act','remotion_studio_publish_confirm');
        actions.appendChild(cancel);actions.appendChild(go);dlg.box.appendChild(actions);
        cancel.focus({preventScroll:true});   // publier écrit une nouvelle version : une touche Entrée égarée ne publie rien (QA Slice 12, P-a)
      });
    }
    async function publish(options){
      const o=options||{};
      if(S.publishing||S.busy){announce('Une opération sur Remotion Studio est en cours.');return {state:'busy'}}
      const v=view(),m=doorModel(v.input);
      if(!m.publish.offered||!v.scene){return {state:'refused',reason:'Rien à publier dans cette scène.'}}
      const core=C(),c=api();
      if(!core||!c){S.publishError={code:'remotion_studio_page_error',text:'le module de Remotion Studio n’est pas chargé dans cette page.',sceneId:v.scene.id};
        log('remotion_studio_module_missing',{},'error');render();return {state:'failed'}}
      const sc=v.scene,at=v.at,ws=workspaceOf(S.studio,sc.prefab);
      if(!ws.digest){S.publishError={code:'remotion_studio_page_error',text:'la liste des fichiers n’a pas encore été lue : réessayez dans un instant.',sceneId:sc.id};
        log('remotion_studio_publish_no_listing',{via:o.via},'warn');render();refresh('no_listing');return {state:'refused'}}
      const ok=await confirmPublish(sc,ws,o.returnFocus||ui.publish);
      if(!ok){log('remotion_studio_publish_cancelled',{via:o.via});announce('Rien n’a été publié.');return {state:'cancelled'}}
      const now2=view().scene;
      if(!now2||keyOf(now2.prefab)!==keyOf(sc.prefab)){S.explain='La scène a changé pendant la confirmation : rien n’a été publié.';render();return {state:'cancelled'}}
      S.publishing={at:now(),label:'Publication dans la variante…'};S.publishError=null;S.published=null;S.explain=null;
      render();tick(true);
      log('remotion_studio_publish_requested',{via:o.via,prefab:keyOf(sc.prefab),scene_id:sc.id,files:ws.count,digest:ws.digest.slice(0,12)});
      let result;
      try{
        const answer=await c.write('publish',{presentation_id:at.presentationId,variant_id:at.variantId,scene_id:sc.id,
          base:{prefab_id:ws.base.prefab_id,version:Number(ws.base.version)},   // the workspace base the user saw, checked by Core
          digest:ws.digest});   // the listing the user confirmed: Core refuses (listing_changed) if the workspace no longer gives it
        if(answer&&answer.studio)S.studio=answer.studio;
        const p=answer&&answer.publish||{};
        S.published={published:p.published,previous:p.previous,status:p.status,sceneId:sc.id,presentationId:at.presentationId,variantId:at.variantId};
        log('remotion_studio_published',{status:p.status,published:p.published&&`${p.published.prefab_id}@${p.published.version}`,
          seconds:Math.round((now()-S.publishing.at)/1000)});
        announce(`Publié : source v${p.published&&p.published.version}.`);
        result={state:'published',published:p.published,previous:p.previous,status:p.status};
      }catch(error){
        const info=error.info||{};
        const diagnostics=(info.diagnostics||[]).slice(0,DIAG_LINES).map(d=>d&&typeof d==='object'?`${d.file}:${d.line}:${d.column} ${d.text}`:String(d));
        let text=core.errorText(error.code)||cleanLine(error.message,200)||'la publication a échoué';
        if(error.code==='remotion_studio_publish_conflict'&&info.current)text+=` La variante utilise la v${info.current.version} ; Remotion Studio a été ouvert sur la v${info.base&&info.base.version}.`;
        if(error.code==='remotion_studio_publish_import_refused'&&info.imports)text+=` (${info.imports.slice(0,4).join(', ')})`;
        if(error.code==='remotion_studio_publish_refused'&&info.publish_code)text+=` ${cleanLine(error.message,220)} [${info.publish_code}]`;
        if(error.code==='remotion_studio_publish_invalid_file')text+=` ${cleanLine(error.message,220)}`;
        if(error.code==='remotion_studio_publish_listing_changed'&&typeof info.count==='number')text+=` (${plural(info.count,'fichier modifié','fichiers modifiés')} maintenant)`;
        S.publishError={code:error.code||'network',text,diagnostics,sceneId:sc.id};
        log('remotion_studio_publish_failed',{code:S.publishError.code,publish_code:info.publish_code,status:error.status},
          error.status>=500||!error.status?'error':'warn');
        result={state:'refused',code:S.publishError.code};
      }finally{
        S.publishing=null;tick(false);render();
      }
      if(result.state==='published'&&ctx.reload)await Promise.resolve(ctx.reload()).catch(error=>log('remotion_studio_reload_failed',{error:cleanLine(error&&error.message,120)},'warn'));
      refresh('after_publish');
      return result;
    }
    /* « Revenir à … » : la porte d'édition de source republie l'ancien contenu comme NOUVELLE version (`restore_version`). */
    async function revert(options){
      const o=options||{};
      const p=S.published,at=ctx.scene();
      if(!p||!p.previous||S.publishing)return {state:'refused'};
      if(!at||at.presentationId!==p.presentationId||at.variantId!==p.variantId||!at.scene||at.scene.id!==p.sceneId){
        S.explain='La scène publiée n’est plus à l’écran : rien n’a été changé.';render();return {state:'refused'};
      }
      S.publishing={at:now(),label:'Retour à la version d’avant…'};S.publishError=null;render();tick(true);
      log('remotion_studio_revert_requested',{via:o.via,target:`${p.previous.prefab_id}@${p.previous.version}`});
      let result;
      try{
        const path=`/api/presentation-studio/presentations/${encodeURIComponent(p.presentationId)}/variants/${encodeURIComponent(p.variantId)}/source-edits`;
        const response=await ctx.fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',
          body:JSON.stringify({actor:'user',basis:{variant_revision:Number(at.revision)},scene_id:p.sceneId,
            files:{restore_version:{id:p.previous.prefab_id,version:Number(p.previous.version)}}})});
        let body=null;
        try{body=await response.json()}catch(_error){body=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
        const status=body&&body.status;
        if(!response.ok||!['reloaded','reloaded_state_reset','repinned','pending_mount'].includes(status)){
          const e=body&&body.error||{};
          throw Object.assign(new Error(e.message||body&&body.message||`HTTP ${response.status}`),{code:e.code||body&&body.code||status||`http_${response.status}`,status:response.status});
        }
        S.published={...p,published:{prefab_id:body.published.id,version:body.published.version},restored:true,status};
        log('remotion_studio_reverted',{status,published:`${body.published.id}@${body.published.version}`});
        result={state:'reverted',published:S.published.published};
      }catch(error){
        S.publishError={code:error.code||'network',text:`le retour à la version d’avant a échoué : ${cleanLine(error.message,200)}`,diagnostics:[],sceneId:p.sceneId};
        log('remotion_studio_revert_failed',{code:S.publishError.code,status:error.status},'error');
        result={state:'failed',code:S.publishError.code};
      }finally{S.publishing=null;tick(false);render()}
      if(result.state==='reverted'&&ctx.reload)await Promise.resolve(ctx.reload()).catch(error=>log('remotion_studio_reload_failed',{error:cleanLine(error&&error.message,120)},'warn'));
      refresh('after_revert');
      return result;
    }

    return Object.freeze({buildButton,buildStatus,render,sync,start,stop,refresh:()=>refresh('api'),request,model,publish,revert,
      state:()=>({studio:S.studio&&{status:S.studio.status,pin:S.studio.pin,url:S.studio.url,work_copy:S.studio.work_copy||null},busy:!!S.busy,
        needsClick:S.needsClick,error:S.actionError,readError:S.readError,explain:S.explain,publishing:!!S.publishing,published:S.published,
        publishError:S.publishError})});
  }

  const api=Object.freeze({createRemotionDoor,doorModel,workspaceOf,isRemotionManifest,CSS,TAB_NAME,PUBLISH_LIMIT_S});
  root.JarvisVariantsRemotionStudio=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
