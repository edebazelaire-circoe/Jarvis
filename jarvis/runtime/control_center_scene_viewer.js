/* Scene → existing object viewer/providers; public agent template only.
   No geometry owner. All writes are injected canonical action adapters. */
(function(root){
  'use strict';
  const REG=/^jart_[0-9a-f]{32}$/;
  const words={pending:'En attente',running:'En cours',blocked:'Bloqué',completed:'Terminé',failed:'Échec',cancelled:'Annulé',interrupted:'Interrompu',unknown:'État inconnu'};
  const STYLE=`
#jvObjectViewer .scv-agent,#jvObjectViewer .scv-grid-form{max-width:1100px;margin:0 auto;padding:clamp(16px,3vw,40px);font-size:15px;line-height:1.55;overflow-wrap:anywhere}
#jvObjectViewer .scv-document{padding:clamp(16px,2vw,28px);line-height:1.65;overflow-wrap:anywhere}
#jvObjectViewer .scv-agent-head{display:flex;align-items:flex-start;gap:20px;justify-content:space-between;flex-wrap:wrap;margin-bottom:32px}
#jvObjectViewer .scv-agent h2{font-size:clamp(22px,3vw,34px);margin:0 0 12px;line-height:1.2}
#jvObjectViewer .scv-agent h3{font-size:17px;margin:28px 0 10px}
#jvObjectViewer .scv-agent p{max-width:75ch;margin:8px 0}
#jvObjectViewer .scv-agent-columns{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:36px}
#jvObjectViewer .scv-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#jvObjectViewer .scv-note{color:var(--muted,#a8bdc9);font-size:14px}
#jvObjectViewer .scv-live{display:flex;gap:10px;align-items:center;min-height:28px}
#jvObjectViewer .scv-live[data-busy=true]::before{content:'';width:14px;height:14px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:scv-spin .8s linear infinite}
#jvObjectViewer .scv-action-result{padding:12px 0;white-space:pre-wrap}
#jvObjectViewer .scv-artifacts{display:flex;gap:8px;flex-wrap:wrap}
#jvObjectViewer .scv-step{margin:10px 0}
#jvObjectViewer .scv-progress{display:block;width:min(100%,400px);margin:14px 0}
#jvObjectViewer .scv-grid-picker{display:grid;grid-template-columns:repeat(6,30px);gap:4px;margin:20px 0}
#jvObjectViewer .scv-grid-picker button{min-height:30px;padding:0}
#jvObjectViewer .scv-grid-fields{display:flex;gap:18px;flex-wrap:wrap;align-items:end}
#jvObjectViewer .scv-grid-fields label{display:grid;gap:6px}
#jvObjectViewer .scv-grid-fields input{width:100px;padding:8px;color:inherit;background:transparent;border:1px solid var(--line,#536674);border-radius:6px;font:inherit}
@keyframes scv-spin{to{transform:rotate(360deg)}}
@media(max-width:760px){#jvObjectViewer .scv-agent-columns{grid-template-columns:1fr;gap:0}}
@media(prefers-reduced-motion:reduce){#jvObjectViewer .scv-live::before{animation-duration:2s}}
`;
  function create(deps){
    const d=deps,doc=d.document||root.document,win=d.window||root,L=d.layout||root.JarvisSceneLayout;
    const el=(tag,cls,text)=>{const e=doc.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e};
    const button=(text,fn)=>{const b=el('button','',text);b.type='button';b.addEventListener('click',fn);return b};
    if(!doc.getElementById('scene-viewer-style')){const style=el('style');style.id='scene-viewer-style';style.textContent=STYLE;doc.head.append(style)}
    let viewer=null,prefabSerial=0;
    function currentViewer(){
      if(viewer)return viewer;
      viewer=root.JarvisObjectViewer.create({document:doc,window:win,log:d.log});
      // The incumbent global ui_close shortcut prevents native dialog cancel.
      // Providers handle their keys first; modal keys then stay inside the modal.
      viewer.element.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Escape'&&!event.defaultPrevented){event.preventDefault();viewer.close()}});
      return viewer;
    }
    const canView=item=>!!item&&item.visibility==='visible'&&['artifact','window'].includes(item.kind);
    const title=item=>L.cleanLine(item&&item.payload&&item.payload.title||'Document',160);
    function textEntry(item,text){return {id:item.object_id,title:title(item),kind:'provider',mount(slot){
      slot.classList.add('scv-document');d.appendBlocks(slot,L.markdownBlocks(text||'Ce document ne contient pas de texte.'));return {};}}}
    function prefabEntry(item,prefab){return {id:item.object_id,title:title(item),kind:'provider',mount(slot,ctx){
      const objectId='viewer-'+(++prefabSerial)+'-'+item.object_id.slice(0,100);
      const host=root.JarvisPrefabHost.createPrefabHost({document:doc,window:win,mode:'preview',
        fetchBundle:root.JarvisPrefabHost.bundleFetcher((path,options)=>win.fetch(path,{...options,cache:'no-store'})),
        onEscape:()=>currentViewer().close(),
        onKey:(id,key)=>{if(id===objectId&&key==='Escape'&&doc.activeElement?.tagName==='IFRAME'&&slot.contains(doc.activeElement))currentViewer().close()},
        onOutcome:outcome=>{if(outcome.outcome==='mounted')ctx.ready();else ctx.fail(new Error(outcome.message||outcome.reason||'Prefab illisible.'))},
        log:(event,data)=>d.log(event.includes('error')||event.includes('failed')?'error':'info',event,data)});
      host.mount(slot,{object_id:objectId,prefab:{id:prefab.id,version:prefab.version},props:prefab.props,data:prefab.data,title:title(item)});
      return {pending:true,dispose:()=>host.destroy(),pause:()=>host.pause(objectId),resume:()=>host.resume(objectId)};
    }}}
    async function entryFor(item,signal){
      const prefab=L.prefabOf(item);if(prefab)return prefabEntry(item,prefab);
      const payload=item.payload||{},artifactId=[payload.registry_artifact_id,payload.artifact_id].find(v=>typeof v==='string'&&REG.test(v));
      if(artifactId){
        const body=await d.fetchJson(`/api/artifacts/${encodeURIComponent(artifactId)}?text_chars=16000`,{signal});
        const a=body&&body.artifact;if(!a||a.artifact_id!==artifactId)throw new Error('Métadonnées du document illisibles.');
        const mime=typeof a.mime_type==='string'?a.mime_type:'';
        if(mime.startsWith('image/')&&a.has_payload!==false)return {id:item.object_id,title:title(item),kind:'image',artifactId};
        if(mime==='application/pdf')return {id:item.object_id,title:title(item),kind:'pdf',artifactId};
        if(typeof a.text==='string')return textEntry(item,a.text+(a.text_truncated?'\n\nAperçu tronqué ; ouvrez le fichier source depuis le Dossier.':''));
        return {id:item.object_id,title:title(item),kind:'unsupported',artifactId,message:'Ce fichier ne possède pas d’aperçu textuel compatible.'};
      }
      const parts=[typeof payload.summary==='string'?payload.summary:'',...L.itemsOf(payload).map(i=>[i.label,i.ref,i.href||i.url].filter(Boolean).join(' — '))].filter(Boolean);
      return parts.length?textEntry(item,parts.join('\n\n')):{id:item.object_id,title:title(item),kind:'unsupported',message:'Cet objet ne contient pas de document affichable.'};
    }
    async function entriesFor(ids,signal){
      const state=d.scene(),items=ids.map(id=>state&&state.objects.get(id)).filter(canView),entries=new Array(items.length);let next=0;
      async function worker(){while(next<items.length){if(signal.aborted)throw Object.assign(new Error('Lecture annulée.'),{name:'AbortError'});const index=next++,item=items[index];
        try{entries[index]=await entryFor(item,signal)}catch(error){if(signal.aborted)throw error;d.log('error','scene.viewer_entry_failed',{object_id:item.object_id,code:error.code||'document_read_failed'});
          entries[index]={id:item.object_id,title:title(item),kind:'unsupported',message:String(error.message||error).slice(0,300)};}}}
      await Promise.all(Array.from({length:Math.min(4,items.length)},worker));return {entries,skipped:ids.length-items.length};
    }
    function prepare(){
      if(doc.fullscreenElement)throw new Error('Quittez le plein écran de présentation avant d’ouvrir ce viewer.');
      const other=doc.querySelector('dialog[open]:not(#jvObjectViewer)');if(other)throw new Error('Fermez la boîte de dialogue ouverte avant d’ouvrir ce viewer.');
      if(d.beforeOpen)d.beforeOpen();
    }
    function open(ids,anchorId){
      prepare();const scene=d.scene(),anchor=scene&&scene.objects.get(anchorId||ids[ids.length-1]);
      if(!anchor)throw new Error('Cet objet n’est plus sur le Board.');
      const v=currentViewer(),options={returnFocus:d.focusElement(anchor.object_id),onClose:d.onClose};
      if(['agent','job'].includes(anchor.kind))return v.openCustom({id:anchor.object_id,title:title(anchor),mount:(slot,ctx)=>mountAgent(anchor,slot,ctx)},options);
      const selected=ids.includes(anchor.object_id)?ids:[anchor.object_id];
      return v.openCustom({id:'scene-document-read',title:'Lecture des documents',mount:async(slot,ctx)=>{
        const resolved=await entriesFor(selected,ctx.signal);if(ctx.signal.aborted)return {};
        if(!resolved.entries.length)throw new Error('Aucun document compatible dans cette sélection.');
        v.openObjects(resolved.entries,{title:resolved.entries.length>1?'Comparer les documents':resolved.entries[0].title,
          notice:resolved.skipped?`${resolved.skipped} objet(s) incompatible(s) écarté(s).`:'',push:false});
        return {};
      }},options);
    }
    function mountAgent(object,slot,ctx){
      const host=el('article','scv-agent');host.dataset.status='unknown';slot.append(host);
      const head=el('div','scv-agent-head'),intro=el('div'),heading=el('h2','',title(object)),status=el('p');status.dataset.agentStatus='';
      const duration=el('p','scv-note'),actions=el('div','scv-actions'),stop=button('Arrêter',()=>stopJob()),ask=button('Poser une question',()=>askAgent());
      stop.dataset.agentAction='stop';ask.dataset.agentAction='ask';stop.disabled=true;ask.disabled=true;actions.append(stop,ask);intro.append(heading,status,duration);head.append(intro,actions);
      const live=el('p','scv-live'),actionNote=el('p','scv-action-result');live.setAttribute('role','status');actionNote.setAttribute('role','status');
      const retry=button('Réessayer la lecture',()=>refresh());retry.dataset.agentAction='retry';
      const columns=el('div','scv-agent-columns'),main=el('div'),side=el('div');columns.append(main,side);host.append(head,live,retry,actionNote,columns);
      let disposed=false,paused=false,model=null,refreshTimer=0,started=0,busyAction=null,stopWait=null,contentStamp='';
      const reader=root.JarvisAgentDetail.createReader({fetchJson:d.fetchJson,log:d.log,onState:update});
      function note(message,busy=false){actionNote.textContent=message;actionNote.dataset.busy=String(busy);actionNote.classList.toggle('scv-live',busy)}
      function update(state){
        if(disposed||paused||state.phase==='idle')return;started=state.started_at||Date.now();live.dataset.busy=String(state.phase==='loading');
        live.textContent=state.phase==='loading'?'Lecture de l’état public…':state.error?state.error.message:'';
        retry.hidden=state.phase==='loading';
        if(state.model){model=state.model;render()}
        else if(state.phase==='error'){model=null;contentStamp='';duration.textContent='Durée inconnue';host.dataset.status='unknown';status.textContent='État inconnu';main.replaceChildren();side.replaceChildren();stop.disabled=true;ask.disabled=true;}
      }
      function render(){
        if(!model)return;host.dataset.status=model.status;heading.textContent=model.title;status.textContent=[words[model.status]||words.unknown,model.role&&model.role.role_id].filter(Boolean).join(' · ');
        stop.disabled=!model.actions.stop.enabled||!!busyAction||!!stopWait;stop.title=model.actions.stop.reason||'Demander l’arrêt du job';ask.disabled=!!busyAction;
        const stamp=JSON.stringify([model.mission,model.activity,model.live_unknown,model.progress_fraction,model.plan_notice,model.steps,model.findings,model.artifacts,model.actions.stop.reason,model.degraded]);
        if(stamp!==contentStamp){
        const focusedArtifact=side.contains(doc.activeElement)?doc.activeElement.dataset.agentArtifact:null,scroll=slot.scrollTop;
        main.replaceChildren(el('h3','','Mission'),el('p','',model.mission?model.mission.objective:'Aucune mission publiée pour ce travail.'),
          el('h3','','Activité actuelle'),el('p','',model.activity||(model.live_unknown?'Le statut vivant n’est plus connu.':'Aucune activité publique supplémentaire.')));
        if(model.progress_fraction!==null){const progress=el('progress','scv-progress');progress.max=1;progress.value=model.progress_fraction;progress.setAttribute('aria-label','Avancement public');main.append(progress,el('p','scv-note',Math.round(model.progress_fraction*100)+' %'))}
        main.append(el('h3','','Travaux visibles'),el('p','scv-note',model.plan_notice));
        const list=el('ul');for(const step of model.steps){const li=el('li','scv-step',`${words[step.status]||words.unknown} · ${step.label}${step.activity?' — '+step.activity:''}`);list.append(li)}
        main.append(list);if(!model.steps.length)main.append(el('p','scv-note','Aucun travail enfant public.'));
        side.replaceChildren(el('h3','','Conclusions publiques'));
        if(!model.findings.length)side.append(el('p','scv-note','Aucune conclusion publique pour le moment.'));
        for(const finding of model.findings)side.append(el('p','',finding.text));
        side.append(el('h3','','Artefacts liés'));const artifacts=el('div','scv-artifacts');
        for(const artifact of model.artifacts){const b=button(artifact.title,()=>openArtifact(artifact.object_id));b.dataset.agentArtifact=artifact.object_id;artifacts.append(b)}
        side.append(artifacts);if(!model.artifacts.length)side.append(el('p','scv-note','Aucun artefact lié.'));
        if(model.actions.stop.reason)side.append(el('p','scv-note',model.actions.stop.reason));
        for(const issue of model.degraded)side.append(el('p','scv-note',issue.message));
        contentStamp=stamp;if(focusedArtifact){const replacement=[...artifacts.children].find(b=>b.dataset.agentArtifact===focusedArtifact);if(replacement)replacement.focus({preventScroll:true})}slot.scrollTop=scroll;
        }
        if(stopWait&&!['pending','running','blocked'].includes(model.status)&&model.status!=='unknown'){stopWait=null;note('État confirmé par Core : '+words[model.status]);stop.disabled=true}
        tick();
      }
      function tick(){
        if(disposed||paused)return;
        if(model){const elapsed=typeof root.taskElapsed==='function'?root.taskElapsed({status:model.status,started_ms:Date.parse(model.started_at||''),ended_ms:Date.parse(model.ended_at||'')},typeof root.serverNow==='function'?root.serverNow():Date.now()):null;
          duration.textContent=elapsed===null?'Durée inconnue':'Durée : '+Math.floor(elapsed/1000)+' s';}
        if(live.dataset.busy==='true')live.textContent=`Lecture de l’état public… ${Math.floor((Date.now()-started)/1000)} s`;
        if(busyAction)note(`${busyAction.label}… ${Math.floor((Date.now()-busyAction.at)/1000)} s`,true);
        if(stopWait){const waited=Date.now()-stopWait.at;if(waited>=stopWait.deadline){stopWait=null;note('La fin du job n’a pas été confirmée dans le délai. Vérifiez son état avant de réessayer.');if(model)stop.disabled=!model.actions.stop.enabled}
          else note(`${stopWait.message} · ${Math.floor(waited/1000)} s`,true)}
      }
      async function refresh(){
        win.clearTimeout(refreshTimer);if(disposed||paused||reader.snapshot().phase==='loading')return;
        await reader.load({object,scene:d.scene()});if(!disposed&&!paused)refreshTimer=win.setTimeout(refresh,5000);
      }
      async function act(label,fn){
        if(disposed||busyAction)return;busyAction={label,at:Date.now()};stop.disabled=true;ask.disabled=true;
        try{await fn()}catch(error){if(!disposed){note(String(error.message||error));d.log('error','scene.viewer_action_failed',{object_id:object.object_id,action:label,code:error.code||'action_failed'})}}
        finally{busyAction=null;if(!disposed&&model){stop.disabled=!model.actions.stop.enabled||!!stopWait;ask.disabled=false}}
      }
      function stopJob(){if(!model||!model.actions.stop.enabled)return;return act('Demande d’arrêt',async()=>{
        const action=model.actions.stop,response=await d.sendJson(action.path,action.body,{signal:ctx.signal,timeoutMs:10000});
        if(response.status!==200)throw Object.assign(new Error(response.body&&response.body.error&&response.body.error.message||`HTTP ${response.status}`),{code:response.body&&response.body.error&&response.body.error.code});
        const result=root.JarvisSceneInteract.stopOutcome(response.body.outcome,response.body.status);note(result.title+' · '+result.sub);
        if(!result.terminal)stopWait={at:Date.now(),deadline:d.cancelDeadlineMs?d.cancelDeadlineMs():20000,message:result.title+' · '+result.sub};
        d.log('info','scene.viewer_stop',{object_id:object.object_id,outcome:response.body.outcome});refresh();
      })}
      function askAgent(){if(!model)return;return act('Ouverture du brouillon',async()=>{
        const chat=root.JarvisChat;if(!chat||!chat.prefill)throw new Error('Le chat est indisponible.');
        const result=await chat.prefill({text:model.actions.ask.prefill,target:model.actions.ask.target,signal:ctx.signal});
        if(!result.ok)throw Object.assign(new Error(result.message||result.code),{code:result.code});
        if(ctx.signal.aborted)return;currentViewer().close();chat.open();
      })}
      function openArtifact(id){return act('Lecture de l’artefact',async()=>{
        const controller=new AbortController(),relay=()=>controller.abort();ctx.signal.addEventListener('abort',relay,{once:true});
        const deadline=win.setTimeout(()=>controller.abort(),10000);
        try{const resolved=await entriesFor([id],controller.signal);if(!ctx.signal.aborted){if(!resolved.entries.length)throw new Error('Cet artefact n’est plus disponible sur le Board.');currentViewer().openObjects(resolved.entries,{push:true,title:resolved.entries[0].title})}}
        finally{win.clearTimeout(deadline);ctx.signal.removeEventListener('abort',relay)}
      })}
      const clock=win.setInterval(tick,500);refresh();ctx.ready();
      return {dispose(){disposed=true;reader.cancel();win.clearTimeout(refreshTimer);win.clearInterval(clock)},
        pause(){paused=true;reader.cancel();win.clearTimeout(refreshTimer)},resume(){if(disposed)return;paused=false;refresh()}};
    }
    function grid(ids,apply,anchorId){
      prepare();const v=currentViewer();return v.openCustom({id:'organize-grid',title:'Organiser en grille',mount(slot){
        const form=el('form','scv-grid-form'),caption=el('p','',`${ids.length} objets · choisissez les lignes et colonnes.`),picker=el('div','scv-grid-picker');
        picker.setAttribute('role','group');picker.setAttribute('aria-label','Choisir une grille');
        const fields=el('div','scv-grid-fields'),rows=el('input'),cols=el('input'),feedback=el('p','scv-action-result');feedback.setAttribute('role','status');
        for(const [input,name,label] of [[rows,'rows','Lignes'],[cols,'cols','Colonnes']]){input.name=name;input.type='number';input.min='1';input.max='64';input.value='2';const l=el('label','',label);l.append(input);fields.append(l)}
        for(let r=1;r<=6;r++)for(let c=1;c<=6;c++){const b=button('',()=>{rows.value=String(r);cols.value=String(c);caption.textContent=`${r} lignes × ${c} colonnes · ${ids.length} objets`});b.dataset.rows=r;b.dataset.cols=c;b.setAttribute('aria-label',`${r} lignes × ${c} colonnes`);picker.append(b)}
        const submit=el('button','','Appliquer la grille');submit.type='submit';submit.dataset.organizeApply='';fields.append(submit);form.append(caption,picker,fields,feedback);slot.append(form);
        form.addEventListener('submit',event=>{event.preventDefault();try{const size=root.JarvisObjectViewer.gridSize(Number(rows.value),Number(cols.value));if(size.rows*size.cols<ids.length)throw new Error('La grille ne contient pas assez de cases.');v.close();apply(size)}
          catch(error){feedback.textContent=String(error.message||error);d.log('info','scene.grid_refused',{code:'invalid_grid'})}});return {};
      }},{returnFocus:d.focusElement(anchorId),onClose:d.onClose});
    }
    return {open,grid,canView,isOpen:()=>!!viewer&&viewer.isOpen(),close:()=>viewer&&viewer.close(),snapshot:()=>viewer?viewer.snapshot():{open:false}};
  }
  const api=Object.freeze({create,STYLE});root.JarvisSceneViewer=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
