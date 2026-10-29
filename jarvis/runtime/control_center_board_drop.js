/* Dépôt sur le Board affiché (handoff jarvis-unified-chat-and-board-drop, Slice 08, `docs/chat.md` › Board drop).

   Un fichier, une image ou un lien glissé sur la scène du Board affiché devient
   un Artefact de ce Board (`upload` ou `link`, provenance `board_drop`) — jamais
   un message du Chat, jamais un tour du Brain ; une image devient en plus une fenêtre de la scène (Core, `scene_object_id`).

   - **Zone** : `#app` lui-même, le fond (`.face`) et la scène (`#sceneLayer`,
     nœuds compris). Les commandes de la page (dock, barre, panneaux, Chat,
     contrôle Boards…) n'en sont pas : le panneau du Chat garde son propre
     dépôt (Slice 07b) et un dépôt sur lui n'atterrit jamais aussi sur le Board.
   - **Seuls `dragenter`, `dragover`, `dragleave` et `drop`** sont écoutés, et
     seulement quand ils portent des fichiers (`Files`) ou un lien
     (`text/uri-list`). Aucun écouteur de pointeur : les gestes de la scène
     (clic, glisser, menu) ne passent jamais par ici.
   - **Calque** `#boardDrop` (au-dessus de la scène, `pointer-events:none`) :
     « Déposer sur « Board » » pendant le survol ; refus dit en mots (aucun
     Board affiché, bascule en cours).
   - **Envoi** : un fichier par requête, `XMLHttpRequest` `POST /api/boards/drop?board_id=`
     (`FormData` `client_upload_id` puis `file`, progression d'envoi), un lien
     par `POST /api/boards/drop-link` `{client_upload_id, url, board_id}` ;
     l'URL n'est **jamais** récupérée (ni ici, ni par Core). File d'attente :
     un envoi à la fois.
   - **Plateau** `#boardDropTray` : une ligne par élément, état en mots,
     compteur vivant, échéances (aucun progrès 30 s, aucune réponse 130 s,
     lien 20 s), « Réessayer » (même id si l'issue est inconnue, sinon un
     nouveau), « Voir dans l'inspecteur » (`JarvisWorkspace.openBoard`), ×
     (annule un envoi en vol). Un succès dit où l'élément est allé.
   - **Journal** (console `[board-drop] board_drop.<événement>`) : ids, tailles,
     types, codes ; jamais un nom de fichier ni une URL.

   N'expose que `window.JarvisBoardDrop`. Les parties pures (`carried`,
   `urlsOf`, `errorText`…) sont exportées pour node. */
(function(root){
  'use strict';

  const ROUTES=Object.freeze({file:'/api/boards/drop',link:'/api/boards/drop-link'});
  const CONFIG={stallMs:30000,answerMs:130000,linkMs:20000,doneMs:12000,cancelledMs:5000,hoverIdleMs:450,maxItems:20};
  const DOM=Object.freeze({app:'app',scene:'sceneLayer',layer:'boardDrop',title:'boardDropTitle',sub:'boardDropSub',
    tray:'boardDropTray',list:'boardDropList',chat:'chatPanel'});
  /* Issue inconnue (Core a peut-être fini) : on reprend avec le MÊME id, Core rejoue sans doublon. */
  const SAME_ID=new Set(['core_timeout','client_timeout','network_error','upload_in_progress']);
  /* Refus qu'un nouvel essai du même élément recevrait à l'identique. */
  const FINAL=new Set(['upload_too_large','upload_empty','upload_name_invalid','link_invalid','too_many_items','folder']);
  const ERRORS=Object.freeze({
    board_drop_target_inactive:'Le Board affiché a changé : rien n’a été ajouté. « Réessayer » dépose sur le Board affiché.',
    link_invalid:'Lien refusé : http ou https seulement, sans identifiant, 2048 caractères au plus.',
    upload_empty:'Fichier vide : rien à ajouter.',
    upload_incomplete:'Envoi coupé avant la fin.',
    upload_conflict:'Conflit d’envoi : « Réessayer » le renvoie sous un nouvel identifiant.',
    upload_in_progress:'Déjà en cours d’envoi dans Jarvis Core.',
    upload_storage_failed:'Jarvis Core n’a pas pu enregistrer le fichier sur le disque.',
    upload_name_invalid:'Nom de fichier illisible ou trop long (255 caractères au plus).',
    core_unreachable:'Jarvis Core injoignable.',
    core_unconfigured:'Le Control Center ne connaît pas Jarvis Core.',
    core_timeout:'Jarvis Core ne répond pas.',
    client_timeout:'Aucune réponse dans le délai.',
    network_error:'Control Center injoignable.',
    session_not_found:'Aucune Session ouverte dans Jarvis Core.',
    board_not_found:'Ce Board n’existe plus.',
    board_archived:'Ce Board est archivé : dépôt impossible.',
    forbidden_origin:'Refusé par le Control Center (origine de la page).',
    core_unavailable:'Le dépôt sur un Board n’est pas disponible dans ce Jarvis Core.',
    invalid_response:'Réponse illisible du Control Center.',
    too_many_items:`Trop d’éléments d’un coup : ${CONFIG.maxItems} au plus par dépôt.`,
    folder:'Dossier : déposez les fichiers eux-mêmes.',
  });

  /* ---------------------------------------------------------------- pur */

  /* Ce que porte un glisser : 'files', 'link' ou null (texte seul, élément de la page…). */
  function carried(types){
    const list=types?[...types]:[];
    if(list.includes('Files'))return 'files';
    if(list.includes('text/uri-list'))return 'link';
    return null;
  }

  /* `text/uri-list` (RFC 2483) : une URL par ligne, `#` commente. Doublons retirés, ordre gardé. */
  function urlsOf(text){
    const out=[];
    for(const line of String(text||'').split(/\r?\n/)){
      const url=line.trim();
      if(url&&!url.startsWith('#')&&!out.includes(url))out.push(url);
    }
    return out;
  }

  function formatBytes(n){
    if(!Number.isFinite(n)||n<0)return '';
    if(n<1024)return `${n} o`;
    const units=['Ko','Mo','Go'];let v=n/1024,u=0;
    while(v>=1024&&u<units.length-1){v/=1024;u++}
    return `${v>=10?Math.round(v):Math.round(v*10)/10} ${units[u]}`.replace('.',',');
  }

  /* Borne dite par Core : « the file exceeds the N-byte upload bound ». */
  function limitFrom(message){
    const m=/exceeds the (\d+)-byte/.exec(String(message||''));
    return m?Number(m[1]):null;
  }

  function errorText(code,message,sameId){
    if(code==='upload_too_large'){
      const bound=limitFrom(message);
      return bound?`Trop volumineux : ${formatBytes(bound)} au plus par fichier.`:'Trop volumineux pour Jarvis Core.';
    }
    const base=ERRORS[code]||`Échec (${code})${message?' : '+String(message).slice(0,160):''}.`;
    return SAME_ID.has(code)?`${base} Issue inconnue : « Réessayer » le renvoie sans doublon.`:base;
  }

  const elapsedText=ms=>{const s=Math.max(0,Math.round(ms/1000));return s<60?`${s} s`:`${Math.floor(s/60)} min ${String(s%60).padStart(2,'0')} s`};

  const PURE=Object.freeze({ROUTES,CONFIG,ERRORS,SAME_ID,FINAL,carried,urlsOf,formatBytes,limitFrom,errorText,elapsedText});
  if(typeof module!=='undefined'&&module.exports)module.exports=PURE;
  if(typeof window==='undefined'||typeof document==='undefined'){root.JarvisBoardDrop=PURE;return}

  /* ---------------------------------------------------------------- page */

  function log(event,data,level){
    const line='[board-drop] board_drop.'+event+' '+JSON.stringify(data||{});
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
  }
  function uuid4(){
    const cr=root.crypto;
    if(cr&&typeof cr.randomUUID==='function')return cr.randomUUID();
    const b=new Uint8Array(16);cr.getRandomValues(b);b[6]=(b[6]&0x0f)|0x40;b[8]=(b[8]&0x3f)|0x80;
    const h=[...b].map(x=>x.toString(16).padStart(2,'0')).join('');
    return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
  }
  const $=id=>document.getElementById(id);
  const now=()=>Date.now();

  /* Le Board affiché, tel que le contrôle Boards le tient (statut à 1 Hz). Core reste juge (409). */
  function target(){
    const control=root.JarvisBoardsControl;
    if(!control||typeof control.activeId!=='function')return {ok:false,why:'Contrôle Boards absent : Board affiché inconnu.'};
    let view=null;
    try{view=control.presentation()}catch(error){log('board_read_failed',{error:String(error&&error.message||error)},'error')}
    if(view&&view.tone==='pending')return {ok:false,why:'Changement de Board en cours : déposez une fois la bascule finie.'};
    const id=control.activeId();
    if(!id||!view||view.tone!=='ready')return {ok:false,why:`Aucun Board affiché confirmé${view&&view.sub?` (${view.sub})`:''}.`};
    return {ok:true,id,title:view.title||id};
  }

  function install(){
    const app=$(DOM.app),layer=$(DOM.layer),tray=$(DOM.tray),list=$(DOM.list);
    if(!app||!layer||!tray||!list){
      log('install_failed',{missing:[DOM.app,DOM.layer,DOM.tray,DOM.list].filter(id=>!$(id))},'error');
      return null;
    }
    const items=[];let busy=null,ticker=null,hoverTimer=null,hovered=false;

    /* ------------------------------------------------ zone et calque */

    const onScene=node=>{
      if(!node||node.nodeType!==1)return false;
      if(node===app||node===document.body||node.classList.contains('face'))return true;
      const scene=$(DOM.scene);
      return !!(scene&&scene.contains(node));
    };
    const editable=node=>!!(node&&node.closest&&node.closest('input,textarea,[contenteditable=""],[contenteditable="true"]'));
    function showLayer(kind,goal){
      layer.hidden=false;layer.dataset.kind=kind;layer.dataset.tone=goal.ok?'ok':'bad';
      $(DOM.title).textContent=goal.ok?`Déposer sur « ${goal.title} »`:'Dépôt impossible ici';
      $(DOM.sub).textContent=goal.ok
        ?(kind==='link'?'Le lien est gardé tel quel dans les Artefacts du Board, jamais ouvert.'
          :'Ajoutés aux Artefacts de ce Board. Ni message au Chat, ni Brain.')
        :goal.why;
      clearTimeout(hoverTimer);
      /* `dragleave` n'est pas fiable (sortie de la fenêtre, iframe) : sans `dragover` récent, le calque part. */
      hoverTimer=setTimeout(hideLayer,CONFIG.hoverIdleMs);
    }
    function hideLayer(){clearTimeout(hoverTimer);layer.hidden=true;hovered=false}

    function onDrag(event){
      const kind=carried(event.dataTransfer&&event.dataTransfer.types);
      if(!kind)return;
      if(!onScene(event.target)){hideLayer();return}
      event.preventDefault();
      const goal=target();
      event.dataTransfer.dropEffect=goal.ok?'copy':'none';
      if(!hovered){hovered=true;log('hover',{kind,accepted:goal.ok,board_id:goal.ok?goal.id:null})}
      showLayer(kind,goal);
    }
    app.addEventListener('dragenter',onDrag);
    app.addEventListener('dragover',onDrag);
    app.addEventListener('dragleave',event=>{if(!event.relatedTarget||!app.contains(event.relatedTarget))hideLayer()});
    app.addEventListener('drop',event=>{
      const kind=carried(event.dataTransfer&&event.dataTransfer.types);
      if(!kind||!onScene(event.target))return;
      event.preventDefault();hideLayer();
      dropped(kind,event.dataTransfer);
    });
    /* Un lien lâché sur une commande de la page n'ouvre jamais l'URL à la place du Control Center
       (le texte d'un champ, lui, le reçoit comme d'habitude). Les fichiers : garde du Chat (07b). */
    document.addEventListener('dragover',event=>{
      if(event.defaultPrevented||carried(event.dataTransfer&&event.dataTransfer.types)!=='link'||editable(event.target))return;
      event.preventDefault();event.dataTransfer.dropEffect='none';
    });
    document.addEventListener('drop',event=>{
      if(event.defaultPrevented||carried(event.dataTransfer&&event.dataTransfer.types)!=='link'||editable(event.target))return;
      event.preventDefault();log('drop_ignored',{kind:'link',reason:'outside_scene'});
    });
    window.addEventListener('drop',hideLayer);
    window.addEventListener('dragend',hideLayer);

    /* ------------------------------------------------ dépôt */

    function dropped(kind,data){
      const goal=target();
      const entries=[];
      if(kind==='files'){
        const files=[...(data.files||[])],dirs=new Set();
        [...(data.items||[])].forEach((item,i)=>{
          try{const entry=item.webkitGetAsEntry&&item.webkitGetAsEntry();if(entry&&entry.isDirectory)dirs.add(i)}
          catch(_error){/* intentional: sans `webkitGetAsEntry`, le dossier est refusé par Core (corps vide ou illisible) */}
        });
        files.forEach((file,i)=>entries.push(dirs.has(i)?{kind:'file',file,refused:'folder'}:{kind:'file',file}));
      }else{
        let text='';
        try{text=data.getData('text/uri-list')}catch(error){log('read_failed',{kind:'link',error:String(error&&error.message||error)},'warn')}
        for(const url of urlsOf(text))entries.push({kind:'link',url});
      }
      log('dropped',{kind,count:entries.length,board_id:goal.ok?goal.id:null,accepted:goal.ok});
      if(!entries.length){add({kind,name:kind==='link'?'Lien':'Dépôt',meta:'',status:'failed',text:'Rien de lisible dans ce dépôt.',final:true});return}
      const extra=entries.splice(CONFIG.maxItems);
      for(const entry of entries){
        const item=add({kind:entry.kind,name:entry.kind==='link'?entry.url:(entry.file.name||'fichier'),
          meta:entry.kind==='link'?'Lien':formatBytes(entry.file.size),file:entry.file||null,url:entry.url||null,
          status:'queued',text:'En attente…'});
        if(entry.refused){fail(item,{code:entry.refused,status:0});continue}
        if(!goal.ok){fail(item,{code:'no_target',status:0,text:goal.why});continue}
        item.boardId=goal.id;item.boardTitle=goal.title;
      }
      if(extra.length)add({kind,name:`${extra.length} élément(s) de plus`,meta:'',status:'failed',
        text:errorText('too_many_items'),final:true});
      pump();
    }

    function add(fields){
      const item=Object.assign({key:uuid4(),id:uuid4(),since:now(),job:null,boardId:null,boardTitle:'',final:false},fields);
      items.push(item);render();return item;
    }

    function pump(){
      if(busy)return;
      const next=items.find(item=>item.status==='queued'&&item.boardId);
      if(!next){tick();return}
      busy=next;next.since=now();
      (next.kind==='link'?sendLink:sendFile)(next);
      tick();
    }

    function settle(item){if(busy===item)busy=null;item.job=null;render();pump()}

    function succeed(item,body){
      item.status='done';item.since=now();
      item.text=`Ajouté au Board « ${item.boardTitle} »${body.relinked?' (le Board a changé pendant l’envoi : rattaché à celui-ci)':''}${body.replayed?' · déjà reçu, sans doublon':''}${body.scene_object_id?' · image affichée sur la scène':''}.`;
      item.artifactId=body.artifact_id;
      setTimeout(()=>remove(item,'expired'),CONFIG.doneMs);
    }

    function fail(item,error){
      item.status='failed';item.since=now();item.code=error.code;item.sameId=SAME_ID.has(error.code);
      item.text=error.text||errorText(error.code,error.message,item.sameId);
      item.final=item.final||FINAL.has(error.code);
      log(item.kind==='link'?'link_failed':'upload_failed',{key:item.key,code:error.code,status:error.status||0,
        same_id:item.sameId},'warn');
    }

    function answerOf(status,raw){
      let body=null;try{body=raw?JSON.parse(raw):null}catch(_error){body=null}
      if((status===200||status===201)&&body&&body.ok===true&&body.artifact_id)return {ok:true,body};
      if(status===200||status===201)return {ok:false,code:'invalid_response',status};
      return {ok:false,code:(body&&body.code)||`http_${status}`,message:body&&body.error,status};
    }

    function sendFile(item){
      const xhr=new XMLHttpRequest(),form=new FormData(),job={xhr,lastAt:now(),sentAt:0,why:null,timer:null};
      item.job=job;item.status='uploading';item.text='Envoi 0 %';item.progress=0;
      form.append('client_upload_id',item.id);form.append('file',item.file,item.file.name);
      log('upload_started',{key:item.key,size:item.file.size,board_id:item.boardId});
      const done=fn=>{clearInterval(job.timer);if(item.job!==job)return;fn();settle(item)};
      xhr.upload.onprogress=event=>{
        job.lastAt=now();
        if(event.lengthComputable&&event.total){item.progress=Math.min(100,Math.round(event.loaded*100/event.total));item.text=`Envoi ${item.progress} %`;render()}
      };
      xhr.upload.onload=()=>{job.lastAt=now();job.sentAt=now();item.progress=100;item.text='Vérification par Jarvis Core…';render()};
      xhr.onload=()=>done(()=>{
        const answer=answerOf(xhr.status,xhr.responseText);
        if(!answer.ok)return fail(item,answer);
        succeed(item,answer.body);
        log('upload_done',{key:item.key,artifact_id:answer.body.artifact_id,status:xhr.status,size:answer.body.size_bytes,
          mime:answer.body.mime_type,replayed:!!answer.body.replayed,relinked:!!answer.body.relinked,board_id:item.boardId});
      });
      xhr.onerror=()=>done(()=>fail(item,{code:'network_error',status:0}));
      xhr.onabort=()=>done(()=>{
        if(job.why==='cancelled'){item.status='cancelled';item.text='Envoi annulé.';item.since=now();
          log('cancelled',{key:item.key});setTimeout(()=>remove(item,'cancelled'),CONFIG.cancelledMs)}
        else fail(item,{code:job.why||'client_timeout',status:0});
      });
      /* Échéance que rien ne peut tenir ouverte : aucun progrès, ou aucune réponse après le dernier octet. */
      job.timer=setInterval(()=>{
        const late=job.sentAt?now()-job.sentAt>CONFIG.answerMs:now()-job.lastAt>CONFIG.stallMs;
        if(late){job.why='client_timeout';xhr.abort()}
      },500);
      xhr.open('POST',`${ROUTES.file}?board_id=${encodeURIComponent(item.boardId)}`);
      xhr.send(form);
      render();
    }

    async function sendLink(item){
      const controller=new AbortController(),job={controller,why:null};
      item.job=job;item.status='uploading';item.text='Enregistrement du lien par Jarvis Core…';render();
      log('link_started',{key:item.key,board_id:item.boardId});
      const timer=setTimeout(()=>{job.why='client_timeout';controller.abort()},CONFIG.linkMs);
      let outcome;
      try{
        const response=await fetch(ROUTES.link,{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
          body:JSON.stringify({client_upload_id:item.id,url:item.url,board_id:item.boardId})});
        outcome=answerOf(response.status,await response.text());
      }catch(error){
        outcome={ok:false,code:job.why||(error&&error.name==='AbortError'?'cancelled':'network_error'),status:0};
      }finally{clearTimeout(timer)}
      if(item.job!==job)return;
      if(outcome.ok){
        succeed(item,outcome.body);
        log('link_done',{key:item.key,artifact_id:outcome.body.artifact_id,replayed:!!outcome.body.replayed,
          relinked:!!outcome.body.relinked,board_id:item.boardId});
      }else if(outcome.code==='cancelled'){
        item.status='cancelled';item.text='Envoi annulé.';item.since=now();log('cancelled',{key:item.key});
        setTimeout(()=>remove(item,'cancelled'),CONFIG.cancelledMs);
      }else fail(item,outcome);
      settle(item);
    }

    function retry(item){
      const goal=target();
      if(!goal.ok){item.text=goal.why;item.since=now();render();return}
      const same=item.sameId&&goal.id===item.boardId;
      if(!same)item.id=uuid4();
      item.boardId=goal.id;item.boardTitle=goal.title;item.status='queued';item.text='En attente…';item.since=now();
      log('retry',{key:item.key,same_id:same,board_id:goal.id});
      render();pump();
    }

    function remove(item,why){
      const at=items.indexOf(item);
      if(at<0)return;
      if(item.job){
        if(item.kind==='link'){item.job.why='cancelled';item.job.controller.abort();return}
        item.job.why='cancelled';item.job.xhr.abort();return;
      }
      items.splice(at,1);
      if(why==='dismissed')log('dismissed',{key:item.key,status:item.status});
      render();
    }

    /* Vue Artefacts de l'inspecteur Workspace, filtrée sur le Board où l'élément est allé. */
    function inspect(item){
      const W=root.JarvisWorkspace,said=error=>{
        log('inspector_failed',{board_id:item.boardId,error:String(error&&error.message||error)},'error');
        item.text=`Inspecteur indisponible : ${String(error&&error.message||error).slice(0,120)}`;render();
      };
      log('inspector_opened',{board_id:item.boardId});
      try{W.open();Promise.resolve(W.act('goto',{view:'artifacts',scope:'board',id:item.boardId})).catch(said)}
      catch(error){said(error)}
    }

    /* ------------------------------------------------ rendu */

    function tick(){
      const live=items.some(item=>item.status==='uploading'||item.status==='queued');
      if(live&&!ticker)ticker=setInterval(render,1000);
      if(!live&&ticker){clearInterval(ticker);ticker=null}
    }

    function row(item){
      const li=document.createElement('li');
      li.className='board-drop-item';li.dataset.status=item.status;li.dataset.key=item.key;
      const name=document.createElement('span');name.className='board-drop-name';name.textContent=item.name;name.title=item.name;
      const meta=document.createElement('span');meta.className='board-drop-meta';meta.textContent=item.meta;
      const state=document.createElement('span');state.className='board-drop-state';state.textContent=item.text;
      const time=document.createElement('span');time.className='board-drop-time';
      time.textContent=item.status==='uploading'||item.status==='queued'?elapsedText(now()-item.since):'';
      const bar=document.createElement('span');bar.className='board-drop-bar';
      bar.style.setProperty('--p',`${item.status==='uploading'?(item.progress||0):item.status==='done'?100:0}%`);
      const act=document.createElement('button');act.type='button';act.className='action small board-drop-act';
      act.hidden=true;
      if(item.status==='failed'&&!item.final){act.hidden=false;act.textContent='Réessayer';act.onclick=()=>retry(item)}
      else if(item.status==='done'&&root.JarvisWorkspace&&typeof root.JarvisWorkspace.act==='function'){
        act.hidden=false;act.textContent='Voir dans l’inspecteur';act.onclick=()=>inspect(item);
      }
      const x=document.createElement('button');x.type='button';x.className='board-drop-x';x.textContent='×';
      x.setAttribute('aria-label',item.status==='uploading'?`Annuler l’envoi de ${item.name}`:`Retirer ${item.name}`);
      x.onclick=()=>remove(item,'dismissed');
      li.append(name,meta,x,state,time,act,bar);
      return li;
    }

    function render(){
      list.replaceChildren(...items.map(row));
      tray.hidden=!items.length;
    }

    log('installed',{layer:DOM.layer,tray:DOM.tray});
    return {snapshot:()=>items.map(item=>({key:item.key,id:item.id,kind:item.kind,status:item.status,text:item.text,
      boardId:item.boardId,artifactId:item.artifactId||null,code:item.code||null})),hideLayer};
  }

  let instance=null;
  try{instance=install()}
  catch(error){console.error('[board-drop] board_drop.install_failed '+JSON.stringify({error:String(error&&error.message||error)}))}
  root.JarvisBoardDrop=Object.freeze({...PURE,instance});
})(typeof globalThis!=='undefined'?globalThis:this);
