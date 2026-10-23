/* Politique de routage par rôle, côté page : transport et lecture (jarvis-architecture-agents-settings-editor,
   Slice 06). Le rendu et l'état d'édition vivent dans `control_center_subagents_settings.js` (« Modèles du
   rôle ») ; ce module ne fait que parler au serveur et lire sa réponse, sans rien inventer.

   Contrat serveur : `docs/subagent-roles.md` § 10 (`jarvis/runtime/subagent_role_routing_http.py`), forme figée
   par `tests/fixtures/subagent_role_routing.json`. Interface d'un adaptateur, injecté dans la vue par
   `options.routing` :

     load()                                                  -> instantané         (lève une erreur `.code`)
     put(roleId, {base_revision, candidates, allow_general_fallback}) -> résultat d'écriture
     restore(roleId, {base_revision})                        -> résultat d'écriture

   Résultat d'écriture : `{ok:true, applies, snapshot}` ou `{ok:false, status, code, reason, snapshot}`. Seul un
   échec de TRANSPORT lève (`subagent_routing_timeout`, `subagent_routing_unreachable`) : l'issue est alors
   inconnue et la vue relit de force. Le serveur reste la seule vérité : harnesses, modèles, disponibilité,
   « lançable » (`selectable`) et aperçu viennent de lui, jamais d'une liste écrite ici.

   Deux adaptateurs : `createHttpAdapter` (les routes, montées par la Slice 07) et `createFixtureAdapter`
   (démonstration et tests ; il ne sert JAMAIS en production). */
(function(root){
  'use strict';
  const BASE='/api/subagent-role-routing';
  const DEFAULT_TIMEOUT_MS=15000;
  const UNKNOWN_OUTCOME=new Set(['subagent_routing_timeout','subagent_routing_unreachable']);
  const clone=v=>JSON.parse(JSON.stringify(v));
  const obj=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:{};
  const str=v=>v==null?'':String(v);

  function codedError(code,message,extra){const e=new Error(message);e.code=code;Object.assign(e,extra||{});return e}

  /* --- lecture tolérante d'un instantané ---------------------------------------------------------------
     Une réponse partielle (autre version, champ retiré) ne doit jamais figer l'écran : chaque partie est ramenée à
     une forme sûre, et ce qui manque est nommé pour que la vue le dise. */
  function normalizeCandidate(c,i){
    const x=obj(c);
    return {agent:str(x.agent),model:str(x.model),position:Number.isInteger(x.position)?x.position:i,label:str(x.label),
      available:x.available!==false,unavailable_reason:str(x.unavailable_reason),
      selectable:x.selectable!==false,selectable_reason:str(x.selectable_reason)};
  }
  const ROLE_FIELDS=['role_id','provenance','explicit','candidates','allow_general_fallback','fallback','preview'];
  function normalizeRole(r){
    const x=obj(r),fb=obj(x.fallback),list=v=>Array.isArray(v)?v.map(normalizeCandidate):[];
    return {role_id:str(x.role_id),marker:str(x.marker),name:str(x.name),aliases:Array.isArray(x.aliases)?x.aliases.map(str):[],
      default_profile:str(x.default_profile),provenance:str(x.provenance),explicit:x.explicit===true,
      inherited_profile:str(x.inherited_profile)||str(x.default_profile),binding:x.binding===true,binding_reason:str(x.binding_reason),
      restorable:x.restorable===true,allow_general_fallback:x.allow_general_fallback!==false,candidates:list(x.candidates),
      fallback:{enabled:fb.enabled===true,profile:str(fb.profile)||'general',candidates:list(fb.candidates)},
      preview:x.preview&&typeof x.preview==='object'?x.preview:null,
      missing:ROLE_FIELDS.filter(k=>!Object.prototype.hasOwnProperty.call(x,k))};
  }
  function normalizeHarness(h){
    const x=obj(h);
    return {id:str(x.id),label:str(x.label)||str(x.id),provider:str(x.provider),available:x.available!==false,unavailable_reason:str(x.unavailable_reason),
      models:(Array.isArray(x.models)?x.models:[]).map(m=>{const y=obj(m);return {model:str(y.model),label:str(y.label)||str(y.model),
        available:y.available!==false,unavailable_reason:str(y.unavailable_reason)}})};
  }
  function normalizeSnapshot(data){
    const x=obj(data);
    if(!Array.isArray(x.roles))throw codedError('subagent_routing_payload_invalid','réponse sans liste de rôles routés');
    const store=obj(x.store),catalog=obj(x.catalog),compat=obj(x.compatibility);
    return {schema_version:x.schema_version,revision:x.revision==null?null:str(x.revision),applies:str(x.applies),
      store:{status:str(store.status)||'ok',code:str(store.code),reason:str(store.reason)},
      catalog:{status:str(catalog.status)||'ok',reason:str(catalog.reason)},
      compatibility:{delegation_mode:str(compat.delegation_mode),profiles_enabled:compat.profiles_enabled===true,note:str(compat.note)},
      degraded:x.degraded&&typeof x.degraded==='object'?{code:str(x.degraded.code),reason:str(x.degraded.reason)}:null,
      roles:x.roles.filter(r=>r&&typeof r==='object'&&typeof r.role_id==='string'&&r.role_id).map(normalizeRole),
      harnesses:(Array.isArray(x.harnesses)?x.harnesses:[]).filter(h=>h&&typeof h==='object'&&h.id).map(normalizeHarness)};
  }

  /* Libellé et disponibilité d'un couple (agent, modèle) d'après le catalogue servi. Un couple absent du
     catalogue reste visible, dit « hors catalogue » : jamais effacé ni deviné. */
  function describeRef(snapshot,ref){
    const h=(snapshot&&snapshot.harnesses||[]).find(x=>x.id===ref.agent);
    const m=h&&h.models.find(x=>x.model===ref.model);
    if(!h)return {label:`${ref.agent}:${ref.model||'défaut'}`,available:false,unavailable_reason:'Harness absent du catalogue servi.'};
    if(!m)return {label:`${h.label} · ${ref.model||'défaut'}`,available:false,unavailable_reason:'Modèle absent du catalogue servi.'};
    return {label:`${h.label} · ${m.label}`,available:h.available&&m.available,unavailable_reason:m.unavailable_reason||h.unavailable_reason};
  }
  const sameRef=(a,b)=>a.agent===b.agent&&a.model===b.model;
  const sameList=(a,b)=>a.length===b.length&&a.every((x,i)=>sameRef(x,b[i]));

  /* --- transport HTTP ----------------------------------------------------------------------------------- */
  function createHttpAdapter(options){
    const o=options||{},base=o.base||BASE,timeoutMs=Number(o.timeoutMs)>0?Number(o.timeoutMs):DEFAULT_TIMEOUT_MS;
    const fetchImpl=o.fetch||(root.fetch&&root.fetch.bind(root));
    async function call(path,init){
      const ctl=typeof root.AbortController==='function'?new root.AbortController():null;
      const timer=ctl&&root.setTimeout?root.setTimeout(()=>ctl.abort(),timeoutMs):null;
      let r;
      try{r=await fetchImpl(base+path,{...(init||{}),headers:{'Content-Type':'application/json'},signal:ctl?ctl.signal:undefined})}
      catch(e){
        if(e&&e.name==='AbortError')throw codedError('subagent_routing_timeout',`Pas de réponse du Control Center après ${Math.round(timeoutMs/1000)} s.`);
        throw codedError('subagent_routing_unreachable','Control Center injoignable : '+(e&&e.message||e));
      }finally{if(timer!=null&&root.clearTimeout)root.clearTimeout(timer)}
      const text=await r.text();let body;
      try{body=text?JSON.parse(text):{}}catch(_e){body={ok:false,code:'subagent_routing_payload_invalid',reason:'Réponse non JSON : '+text.slice(0,160)}}
      const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
      const code=str(body.code)||(envelope&&str(envelope.code))||(r.headers&&r.headers.get&&r.headers.get('X-Jarvis-Error-Code'))||'';
      const reason=str(body.reason)||(envelope&&str(envelope.message))||(typeof body.error==='string'?body.error:'')||('HTTP '+r.status);
      return {status:r.status,ok:r.ok&&body.ok!==false,body:obj(body),code,reason};
    }
    const result=x=>x.ok?{ok:true,applies:str(x.body.applies),snapshot:x.body.snapshot||null}
      :{ok:false,status:x.status,code:x.code||'subagent_routing_refused',reason:x.reason,snapshot:x.body.snapshot||null};
    return {
      async load(){
        const x=await call('',{method:'GET'});
        if(!x.ok)throw codedError(x.code||'subagent_routing_load_failed',x.reason,{status:x.status,snapshot:x.body.snapshot||null});
        return x.body;
      },
      async put(roleId,body){return result(await call('/'+encodeURIComponent(roleId),{method:'PUT',body:JSON.stringify(body)}))},
      async restore(roleId,{base_revision}){return result(await call('/'+encodeURIComponent(roleId)+'?base_revision='+encodeURIComponent(base_revision??''),{method:'DELETE'}))},
    };
  }

  /* --- adaptateur de démonstration et de test ------------------------------------------------------------
     Simule le serveur du § 10 sur une copie de l'instantané : révision globale `rr-<n>`, 404, 409, 422 (liste
     vide, aucun candidat de l'hôte, doublon), restauration d'un rôle hérité refusée. L'hôte (seul CLI qui lance
     des sous-agents) se déduit de l'instantané lui-même : l'agent des candidats `selectable`. Pannes à la
     demande : `failNext({status,code,reason})`, `throwNext(code)` (issue inconnue ; `writes:true` écrit
     quand même), `degradeNext()` (écriture réussie, relecture dégradée). NE SERT JAMAIS en production. */
  function createFixtureAdapter(snapshot,options){
    const o=options||{};
    const initial=clone(snapshot);
    let snap=clone(snapshot),n=Number(String(snap.revision||'rr-0').replace(/^rr-/,''))||0;
    const calls=[];let fail=null,thrown=null,degrade=false;
    const host=o.hostAgent||((snap.roles||[]).flatMap(r=>r.candidates||[]).find(c=>c.selectable)||{}).agent||'';
    const delay=()=>o.latencyMs>0?new Promise(r=>setTimeout(r,o.latencyMs)):Promise.resolve();
    const refuse=(status,code,reason)=>({ok:false,status,code,reason,snapshot:clone(snap)});
    const view=(ref,i)=>{const d=describeRef(normalizeSnapshot(snap),ref);const selectable=d.available&&ref.agent===host;
      return {agent:ref.agent,model:ref.model,position:i,label:d.label,available:d.available,unavailable_reason:d.available?'':d.unavailable_reason,
        selectable,selectable_reason:selectable?'':(d.available?'Seul le CLI hôte lance des sous-agents.':d.unavailable_reason)}};
    function preview(role){
      if(!role.explicit)return initial.roles.find(r=>r.role_id===role.role_id).preview;
      const pick=role.candidates.find(c=>c.selectable)||(role.allow_general_fallback?role.fallback.candidates.find(c=>c.selectable):null);
      if(!pick)return {outcome:'refused',reason:'no_candidate',detail:'Aucun candidat lançable pour ce rôle.'};
      const first=role.candidates.indexOf(pick)===0;
      return {outcome:'selected',agent:pick.agent,model:pick.model,reason:first?'preferred':role.candidates.includes(pick)?'fallback':'general_fallback',
        considered:role.candidates.slice(0,role.candidates.includes(pick)?role.candidates.indexOf(pick)+1:undefined).map(c=>c.selectable?{agent:c.agent,model:c.model,eligible:true}
          :{agent:c.agent,model:c.model,eligible:false,code:c.available?'agent_not_host':'model_unavailable',detail:c.selectable_reason}),
        role_id:role.role_id,provenance:'explicit'};
    }
    async function guard(kind){
      calls.push(kind);await delay();
      if(thrown){const t=thrown;thrown=null;if(!t.writes)throw codedError(t.code,t.message);return t}
      return null;
    }
    function finish(){
      n+=1;snap.revision='rr-'+n;
      if(degrade){degrade=false;return {ok:true,applies:'live',snapshot:{ok:true,revision:null,applies:'live',roles:[],harnesses:[],
        degraded:{code:'role_routing_snapshot_failed',reason:'Lecture de la politique des rôles impossible (OSError) ; relisez la page.'}}}}
      return {ok:true,applies:'live',snapshot:clone(snap)};
    }
    return {
      calls,
      get snapshot(){return clone(snap)},
      failNext(f){fail=f},throwNext(code,extra){thrown={code,message:code==='subagent_routing_timeout'?'Pas de réponse du Control Center après 15 s.':'Control Center injoignable : simulé',...(extra||{})}},
      degradeNext(){degrade=true},
      async load(){const t=await guard(['load']);if(t)throw codedError(t.code,t.message);
        if(fail&&fail.on==='load'){const f=fail;fail=null;throw codedError(f.code,f.reason,{status:f.status})}return clone(snap)},
      async put(roleId,body){
        const t=await guard(['put',roleId,clone(body)]);
        if(fail&&fail.on!=='load'){const f=fail;fail=null;return refuse(f.status,f.code,f.reason)}
        const role=snap.roles.find(r=>r.role_id===roleId||(r.aliases||[]).includes(roleId));
        if(!role)return refuse(404,'role_routing_unknown_role',`Rôle inconnu : ${roleId}.`);
        if(body.base_revision!==snap.revision)return refuse(409,'role_routing_revision_stale',`La politique a changé (révision ${snap.revision}) ; relisez avant d'enregistrer.`);
        const list=Array.isArray(body.candidates)?body.candidates:null;
        if(!list)return refuse(422,'routing_bad_candidates','« candidates » doit être une liste.');
        if(!list.length)return refuse(422,'role_routing_empty_candidates','Une liste vide est refusée : restaurez le rôle pour revenir à l’héritage.');
        const seen=new Set();for(const c of list){const k=c.agent+'\u0000'+c.model;if(seen.has(k))return refuse(422,'routing_duplicate_candidate','Candidat en double.');seen.add(k)}
        if(!list.some(c=>c.agent===host))return refuse(422,'role_routing_no_host_candidate',`Le rôle « ${role.name} » doit compter au moins un candidat de « ${host} » : seul ce CLI hôte lance des sous-agents.`);
        Object.assign(role,{provenance:'explicit',explicit:true,restorable:true,binding:true,binding_reason:'Politique du rôle appliquée à chaque lancement de ce rôle.',
          allow_general_fallback:body.allow_general_fallback!==false,candidates:list.map((c,i)=>view(c,i))});
        role.fallback={...role.fallback,enabled:role.allow_general_fallback};
        role.preview=preview(role);
        if(t&&t.writes){n+=1;snap.revision='rr-'+n;throw codedError(t.code,t.message)}
        return finish();
      },
      async restore(roleId,{base_revision}){
        const t=await guard(['restore',roleId,{base_revision}]);
        if(fail&&fail.on!=='load'){const f=fail;fail=null;return refuse(f.status,f.code,f.reason)}
        const i=snap.roles.findIndex(r=>r.role_id===roleId);
        if(i<0)return refuse(404,'role_routing_unknown_role',`Rôle inconnu : ${roleId}.`);
        if(base_revision!==snap.revision)return refuse(409,'role_routing_revision_stale',`La politique a changé (révision ${snap.revision}).`);
        if(!snap.roles[i].explicit)return refuse(409,'role_routing_not_explicit',`Le rôle « ${snap.roles[i].name} » hérite déjà de son profil.`);
        const was=clone(initial.roles.find(r=>r.role_id===roleId));
        snap.roles[i]=was.explicit?{...was,provenance:'inherited:'+was.inherited_profile,explicit:false,restorable:false,binding:false,
          binding_reason:'Héritée : la politique par profil s’applique.',candidates:clone(was.fallback.candidates),preview:{outcome:'cli_default',reason:'compatibility',detail:'Le CLI garde son propre modèle (aucune liste ne s’impose).'}}:was;
        if(t&&t.writes){n+=1;snap.revision='rr-'+n;throw codedError(t.code,t.message)}
        return finish();
      },
    };
  }

  const api=Object.freeze({BASE,UNKNOWN_OUTCOME,normalizeSnapshot,describeRef,sameRef,sameList,createHttpAdapter,createFixtureAdapter});
  root.JarvisSubagentRouting=api;
  if(typeof module==='object'&&module&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
