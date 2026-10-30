/* Projection publique du viewer d'agent (mouse-organization-viewer, S04).
   Work State reste seul propriétaire du statut. Historique : identité/mission,
   jamais déclaration, prompt, traces ou raisonnement. Pas de polling ni d'envoi.
   L'intégrateur injecte le lecteur JSON et le journal existants de la page. */
(function(root){
  'use strict';
  const Layout=root.JarvisSceneLayout||(typeof require==='function'?require('./control_center_scene_layout.js'):null);
  const LIMITS=Object.freeze({work:64,instances:1024,missions:256,children:32,artifacts:24,findings:8,timeoutMs:5000});
  const STATUSES=new Set(['pending','running','blocked','completed','failed','cancelled','interrupted']);
  const ACTIVE=new Set(['pending','running','blocked']);
  const SOURCE=/^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/;
  const ROLE=/^[a-z][a-z_-]{1,23}$/;
  const ARTIFACT=/^jart_[0-9a-f]{32}$/;
  const text=(v,n)=>typeof v==='string'?v.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g,'').slice(0,n):'';
  const id=v=>typeof v==='string'&&v.length>0&&v.length<=128&&v===v.trim()&&!/[\u0000-\u001f\u007f]/.test(v)?v:null;
  const source=v=>typeof v==='string'&&SOURCE.test(v)?v:null;
  const role=v=>typeof v==='string'&&ROLE.test(v)?v:null;
  const key=(s,e)=>JSON.stringify([s,e]);
  const iso=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v))?new Date(Date.parse(v)).toISOString():null;
  const fraction=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1?v:null;
  const count=v=>Number.isSafeInteger(v)&&v>=0?v:null;
  const error=(code,message)=>Object.assign(new Error(message),{code});
  function identityOf(object){
    const ref=object&&object.work_ref;
    if(!object||!id(object.object_id)||!['agent','job'].includes(object.kind)||!ref||!source(ref.source)||!id(ref.external_id))
      throw error('agent_detail_identity_invalid','Cet objet ne porte pas une identité de travail valide.');
    return {source:ref.source,external_id:ref.external_id,work_id:id(ref.work_id)};
  }
  const matches=(item,identity)=>!!item&&item.source===identity.source&&item.external_id===identity.external_id;
  const instanceMatches=(item,identity)=>!!item&&item.work_source===identity.source&&item.work_external_id===identity.external_id&&!!id(item.instance_id);
  const issue=(code,message)=>({code:source(code)||'agent_detail_failed',message:text(message,300)});
  function publicWork(item){
    const status=STATUSES.has(item.status)?item.status:'unknown';
    const start=iso(item.started_at),end=iso(item.ended_at);
    return {source:source(item.source),external_id:id(item.external_id),work_id:id(item.work_id),
      status,label:text(item.label,160),activity:text(item.activity,160),summary:text(item.summary,1000),
      role_id:role(item.role_id),progress_fraction:fraction(item.progress_fraction),
      started_at:start,ended_at:end&&start&&Date.parse(end)>=Date.parse(start)?end:null,
      tokens:count(item.tokens),tool_uses:count(item.tool_uses)};
  }
  function workItems(work,degraded){
    if(!work||work.source!=='core'||work.core_reachable!==true||!id(work.store_id)||!Number.isSafeInteger(work.revision)||work.revision<0||!Array.isArray(work.items)||work.items.length>LIMITS.work){
      degraded.push(issue(work&&work.error&&work.error.code||'work_unavailable',work&&work.error&&work.error.message||'État de travail Core indisponible.'));
      return [];
    }
    const items=work.items.filter(item=>item&&source(item.source)&&id(item.external_id));
    const keys=new Set(items.map(item=>key(item.source,item.external_id)));
    if(items.length!==work.items.length||keys.size!==items.length){degraded.push(issue('work_payload_invalid','Instantané de travail Core illisible.'));return []}
    return items;
  }
  function artifactsOf(scene,objectId,degraded){
    if(!scene)return [];
    if(!scene.objects||!scene.relations||typeof scene.objects.get!=='function'||typeof scene.relations.values!=='function'||scene.objects.size>512||scene.relations.size>1024){
      degraded.push(issue('scene_payload_invalid','Liens des artefacts indisponibles.'));return [];
    }
    const ids=Layout.artifactsExplaining(scene,objectId);
    if(ids.length>LIMITS.artifacts)degraded.push(issue('artifacts_truncated',`Les ${LIMITS.artifacts} premiers artefacts liés sont affichés.`));
    return ids.slice(0,LIMITS.artifacts).map(object_id=>{
      const object=scene.objects.get(object_id),payload=object.payload||{};
      const artifactId=[payload.registry_artifact_id,payload.artifact_id].find(value=>typeof value==='string'&&ARTIFACT.test(value));
      return {object_id,artifact_id:artifactId||null,title:text(payload.title,160)||'Artefact',relation:'explains'};
    });
  }
  function project(input){
    const p=input||{},object=p.object,identity=identityOf(object),degraded=[];
    for(const e of (Array.isArray(p.errors)?p.errors:[]).slice(0,8))degraded.push(issue(e.code,e.message));
    const items=workItems(p.work,degraded),raw=items.find(item=>matches(item,identity));
    const conflict=raw&&identity.work_id&&id(raw.work_id)&&identity.work_id!==raw.work_id;
    if(conflict)degraded.push(issue('work_identity_conflict','L’identité du travail a changé : état vivant inconnu.'));
    const live=raw&&!conflict?publicWork(raw):null;
    if(!live)degraded.push(issue('work_not_tracked','Ce travail n’est plus suivi par Core : état vivant inconnu.'));
    else if(live.status==='unknown')degraded.push(issue('work_status_invalid','Statut du travail illisible.'));
    let instance=null;
    if(p.instance){
      if(instanceMatches(p.instance,identity))instance=p.instance;
      else degraded.push(issue('mission_identity_conflict','L’historique reçu ne correspond pas à ce travail.'));
    }
    const ref=object.role_ref||{};
    const missionId=id(instance&&instance.mission_id)||(instance?null:id(ref.mission_id));
    const tree=p.tree&&Array.isArray(p.tree.missions)&&p.tree.missions.length<=LIMITS.missions&&Array.isArray(p.tree.instances)&&p.tree.instances.length<=LIMITS.instances?p.tree:null;
    if(p.tree&&!tree)degraded.push(issue('mission_payload_invalid','Historique de mission illisible.'));
    const mission=tree&&missionId?tree.missions.find(m=>m&&m.mission_id===missionId):null;
    const roleId=role(instance&&instance.role_id)||role(live&&live.role_id)||role(ref.role_id);
    if(instance&&live&&role(instance.role_id)&&role(live.role_id)&&instance.role_id!==live.role_id)
      degraded.push(issue('role_identity_conflict','Les sources publiques indiquent des rôles différents.'));
    const children=new Map();
    for(const child of conflict?[]:items){
      if(child.source!==identity.source||child.parent_external_id!==identity.external_id||matches(child,identity))continue;
      children.set(key(child.source,child.external_id),{item:child,instance:null});
    }
    if(tree&&instance)for(const child of tree.instances){
      if(!child||child.parent_instance_id!==instance.instance_id||child.instance_id===instance.instance_id||!source(child.work_source)||!id(child.work_external_id)||!id(child.instance_id))continue;
      const childIdentity={source:child.work_source,external_id:child.work_external_id};
      if(childIdentity.source===identity.source&&childIdentity.external_id===identity.external_id)continue;
      children.set(key(childIdentity.source,childIdentity.external_id),{item:conflict?null:items.find(item=>matches(item,childIdentity))||null,instance:child});
    }
    if(children.size>LIMITS.children)degraded.push(issue('children_truncated',`Les ${LIMITS.children} premiers travaux enfants sont affichés.`));
    const steps=[...children.values()].slice(0,LIMITS.children).map(child=>{
      const w=child.item?publicWork(child.item):null,i=child.instance;
      return {source:w?w.source:i.work_source,external_id:w?w.external_id:i.work_external_id,instance_id:id(i&&i.instance_id),
        label:w&&w.label||text(i&&i.label,160)||'Travail enfant',status:w?w.status:'unknown',activity:w?w.activity:'',
        summary:w?w.summary:'',progress_fraction:w?w.progress_fraction:null};
    });
    const status=live?live.status:'unknown';
    const canStop=object.kind==='job'&&identity.source==='job'&&ACTIVE.has(status);
    const stopReason=canStop?null:identity.source!=='job'||object.kind!=='job'?'Ce sous-agent ne dispose pas d’un arrêt individuel.':status==='unknown'?'État vivant inconnu : arrêt non disponible.':'Ce travail est déjà terminé.';
    const findings=[];
    if(live&&live.summary)findings.push({source:identity.source,external_id:identity.external_id,text:live.summary});
    for(const child of steps)if(child.summary&&findings.length<LIMITS.findings)findings.push({source:child.source,external_id:child.external_id,text:child.summary});
    return {schema_version:1,object_id:object.object_id,identity,title:live&&live.label||text(object.payload&&object.payload.title,160)||'Agent',
      mission:mission?{mission_id:missionId,objective:text(mission.objective,1000)}:null,
      role:roleId?{role_id:roleId}:null,instance_id:id(instance&&instance.instance_id),status,live_unknown:status==='unknown',
      started_at:live?live.started_at:null,ended_at:live?live.ended_at:null,activity:live?live.activity:'',summary:live?live.summary:'',
      progress_fraction:live?live.progress_fraction:null,counters:{tokens:live?live.tokens:null,tool_uses:live?live.tool_uses:null},
      published_plan:null,plan_notice:'Aucun plan public n’a été publié.',steps,findings,artifacts:artifactsOf(p.scene,object.object_id,degraded),
      actions:{stop:{enabled:canStop,method:'POST',path:'/api/jobs/cancel',body:{source:identity.source,external_id:identity.external_id},reason:stopReason},
        ask:{enabled:true,mode:'main_chat',target:{source:identity.source,external_id:identity.external_id,instance_id:id(instance&&instance.instance_id),mission_id:missionId},
          prefill:`À propos du travail ${identity.source}/${identity.external_id} : `}},
      provenance:{status:live?'work_state':null,timing:live?'work_state':null,mission:mission?'mission_history':null,
        role:instance&&role(instance.role_id)?'mission_history':live&&live.role_id?'work_state':roleId?'scene.role_ref':null,
        steps:'work_state+mission_history',findings:'work_state.summary',artifacts:'scene.explains'},degraded};
  }

  /* Une lecture à la demande, bornée et annulable. La page possède son rythme
     de rafraîchissement et son rendu d'attente/erreur ; pas de seconde boucle. */
  function createReader(options){
    const o=options||{};
    if(typeof o.fetchJson!=='function'||typeof o.log!=='function')throw new TypeError('Agent detail requires fetchJson and log.');
    const timeoutMs=Math.max(50,Math.min(15000,Number(o.timeoutMs)||LIMITS.timeoutMs));
    const now=o.now||(()=>Date.now()),setTimer=o.setTimeout||setTimeout,clearTimer=o.clearTimeout||clearTimeout;
    let active=null,sequence=0,state={phase:'idle',model:null,error:null,started_at:null,deadline_at:null};
    function publish(next){state=next;if(o.onState)o.onState(next)}
    function cancel(){
      if(active){const previous=active;active=null;sequence++;previous.controller.abort();previous.resolve(null);clearTimer(previous.timer);o.log('info','agent_detail.cancelled',{sequence:previous.seq})}
      publish({phase:'idle',model:null,error:null,started_at:null,deadline_at:null});
    }
    async function load(input){
      cancel();
      const identity=identityOf(input&&input.object),seq=++sequence,controller=new AbortController();
      const started=now(),issues=[];
      const op={seq,controller,timer:null,resolve:null};active=op;
      const interrupted=new Promise(resolve=>{op.resolve=resolve});
      publish({phase:'loading',model:null,error:null,started_at:started,deadline_at:started+timeoutMs});
      o.log('info','agent_detail.loading',{object_id:input.object.object_id,source:identity.source});
      async function read(path,part){
        try{
          const body=await o.fetchJson(path,{signal:controller.signal});
          if(!body||typeof body!=='object'||Array.isArray(body))throw error('agent_detail_payload_invalid','Réponse de lecture illisible.');
          return body;
        }catch(e){
          if(controller.signal.aborted)return null;
          const code=source(e&&e.code)||'agent_detail_read_failed';
          issues.push(issue(code,e&&e.message||'Lecture impossible.'));
          o.log(e&&e.status===404?'info':'warn','agent_detail.read_failed',{part,code});
          return null;
        }
      }
      op.timer=setTimer(()=>{
        if(active!==op)return;
        controller.abort();op.resolve({timeout:true});
      },timeoutMs);
      try{
        const task=(async()=>{
          const [work,instance]=await Promise.all([read('/api/work','work'),read(`/api/missions/work/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.external_id)}`,'instance')]);
          if(active!==op||controller.signal.aborted)return null;
          const missionId=instanceMatches(instance,identity)?id(instance.mission_id):id(input.object.role_ref&&input.object.role_ref.mission_id);
          const tree=missionId?await read('/api/missions/'+encodeURIComponent(missionId),'mission'):null;
          return project({...input,work,instance,tree,errors:issues});
        })();
        const result=await Promise.race([task,interrupted]);
        if(active!==op||seq!==sequence)return null;
        if(result&&result.timeout)throw error('agent_detail_timeout',`Lecture interrompue après ${Math.round(timeoutMs/1000*10)/10} s. Réessayez.`);
        const next={phase:result.degraded.length?'degraded':'ready',model:result,error:null,started_at:started,deadline_at:started+timeoutMs};
        publish(next);o.log('info','agent_detail.loaded',{object_id:input.object.object_id,status:result.status,degraded:result.degraded.length});return next;
      }catch(e){
        if(active!==op)return null;
        const failure=issue(e&&e.code,e&&e.message||'Lecture du travail impossible.');
        const next={phase:'error',model:null,error:failure,started_at:started,deadline_at:started+timeoutMs};
        publish(next);o.log('error','agent_detail.failed',{object_id:input.object.object_id,code:failure.code});return next;
      }finally{clearTimer(op.timer);if(active===op)active=null}
    }
    return {load,cancel,snapshot:()=>state};
  }
  const api=Object.freeze({LIMITS,identityOf,project,createReader});
  root.JarvisAgentDetail=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
