/* Faux relais `POST /api/chat/uploads` pour `test_control_center_chat_attachments_browser.py` (Slice 07b).

   Exporte `FAKE`, une source posée par `_chat_browser.mjs` (option d'étape `extra`) juste après
   son faux Core (`window.__chat`). La vue envoie chaque pièce par `XMLHttpRequest` (progression
   d'envoi) : ce double remplace `XMLHttpRequest` pour la seule route des pièces et rejoue le
   contrat de `docs/chat.md` › *Attachments* (Core `PUT /v1/uploads/{client_upload_id}` relayé) :

   - identité rejouable : même `client_upload_id` déjà `complete` → 200 `replayed` ; un id dont
     l'essai a ÉCHOUÉ côté Core → 409 `upload_conflict` (la ligne `failed` est immuable) ;
   - lisibilité par le Brain (Claude) : texte, PNG/JPEG/GIF/WebP, PDF ; le reste `brain_readable=false` ;
   - refus avec le message de Core (« the file exceeds the N-byte upload bound »).

   Plans par nom de fichier (`__chat.uploadPlans[nom] = plan`) :
   `big` 413 · `network_once` Core finit, la réponse se perd (issue inconnue) · `timeout_then_failed`
   504 `core_timeout` alors que Core a échoué (la reprise au même id reçoit 409) · `incomplete` 400 ·
   `slow` envoi lent (`slowMs`) · `hang` aucun octet ne part (file d'attente du navigateur).
   Journal : `__chat.uploads` (une entrée par requête : id, nom, taille, ordre des champs, issue). */
export const FAKE=`(()=>{
  const C=window.__chat,Real=window.XMLHttpRequest;
  C.uploads=[];C.uploadPlans={};C.uploadMs=240;C.slowMs=2500;C.answerMs=80;C.store=new Map();C.bound=1048576;
  const READABLE={png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',gif:'image/gif',webp:'image/webp',pdf:'application/pdf',txt:'text/plain',md:'text/plain'};
  const extOf=name=>(String(name).split('.').pop()||'').toLowerCase();
  const artifactOf=id=>'jart_up_'+id.replace(/-/g,'').slice(0,40);
  class FakeUpload{constructor(){this.onprogress=null;this.onload=null}}
  class FakeXHR{
    constructor(){this.upload=new FakeUpload();this.status=0;this.responseText='';this.readyState=0;this.timers=[];this.done=false}
    open(method,url){this.method=method;this.url=url;this.readyState=1}
    setRequestHeader(){}
    later(ms,fn){this.timers.push(setTimeout(()=>{if(!this.done)fn()},ms))}
    finish(kind,status,body){
      if(this.done)return;this.done=true;this.timers.forEach(clearTimeout);this.readyState=4;
      if(kind==='error'){this.onerror&&this.onerror(new ProgressEvent('error'));return}
      this.status=status;this.responseText=JSON.stringify(body);this.onload&&this.onload(new ProgressEvent('load'));
    }
    abort(){
      if(this.done)return;this.done=true;this.timers.forEach(clearTimeout);
      if(this.entry)this.entry.outcome='aborted';
      this.onabort&&this.onabort(new ProgressEvent('abort'));
    }
    send(form){
      const id=String(form.get('client_upload_id')),file=form.get('file'),name=file&&file.name||'';
      const plan=C.uploadPlans[name]||null,entry={id,name,size:file?file.size:0,type:file?file.type:'',order:[...form.keys()],outcome:null};
      this.entry=entry;C.uploads.push(entry);
      if(plan==='hang')return;
      const total=entry.size,steps=4,span=plan==='slow'?C.slowMs:C.uploadMs;
      for(let i=1;i<=steps;i++)this.later(span*i/steps,()=>{
        const loaded=Math.round(total*i/steps);
        this.upload.onprogress&&this.upload.onprogress({loaded,total,lengthComputable:true});
        if(i===steps){this.upload.onload&&this.upload.onload({});this.later(C.answerMs,()=>this.answer(id,file,plan,entry))}
      });
    }
    answer(id,file,plan,entry){
      const refuse=(status,code,message)=>{entry.outcome=code;this.finish('load',status,{ok:false,code,error:message||code,core_status:status})};
      const prior=C.store.get(id);
      if(prior&&prior.state==='failed')return refuse(409,'upload_conflict','a previous attempt with this client_upload_id failed');
      if(prior&&prior.state==='complete'){
        if(prior.size!==file.size)return refuse(409,'upload_conflict','same client_upload_id, other bytes');
        entry.outcome='replayed';return this.finish('load',200,{ok:true,...prior.answer,replayed:true});
      }
      if(plan==='big'||file.size>C.bound){C.store.set(id,{state:'failed'});return refuse(413,'upload_too_large','the file exceeds the '+C.bound+'-byte upload bound')}
      if(plan==='incomplete'){C.store.set(id,{state:'failed'});return refuse(400,'upload_incomplete','the browser stopped sending the file')}
      if(plan==='timeout_then_failed'){C.uploadPlans[file.name]=null;C.store.set(id,{state:'failed'});
        return refuse(504,'core_timeout','Core did not answer in time; resend the same client_upload_id')}
      const mime=READABLE[extOf(file.name)]||'application/octet-stream';
      const answer={artifact_id:artifactOf(id),original_name:file.name,mime_type:mime,size_bytes:file.size,state:'complete',
        brain_readable:mime!=='application/octet-stream'};
      C.store.set(id,{state:'complete',size:file.size,answer});
      if(plan==='network_once'){C.uploadPlans[file.name]=null;entry.outcome='lost';return this.finish('error')}
      entry.outcome='created';this.finish('load',201,{ok:true,...answer,replayed:false});
    }
  }
  window.XMLHttpRequest=function(){return new FakeXHR()};
  window.XMLHttpRequest.Real=Real;
  /* Un tour qui cite une pièce inconnue de Core : 404 \`attachment_not_found\` (garde de Core, étape 5). */
  const fetchBefore=window.fetch;
  window.fetch=async(path,init)=>{
    if(String(path)==='/api/chat/turns'&&init&&init.body){
      const body=JSON.parse(init.body),known=new Set([...C.store.values()].filter(v=>v.state==='complete').map(v=>v.answer.artifact_id));
      if(Array.isArray(body.attachments)&&body.attachments.some(a=>!known.has(a))){
        C.calls.push('POST /api/chat/turns');C.turns.push(body);
        return new Response(JSON.stringify({ok:false,code:'attachment_not_found',error:'unknown',core_status:404}),{status:404,headers:{'Content-Type':'application/json'}});
      }
    }
    return fetchBefore(path,init);
  };
  return 'ok';
})()`;
