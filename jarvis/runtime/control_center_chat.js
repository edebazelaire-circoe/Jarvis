/* Chat — onglet bas-droit, panneau et composer (handoff jarvis-unified-chat-and-board-drop, Slice 06).

   Contrat : `docs/chat.md` (*Panel*, *Reading*, *Sending text*, *Voice
   channel*, *Error codes*). Le Chat montre la conversation du binding
   Session+Board actif — la MÊME que la voix — et y écrit par le MÊME Brain.

   **Routes.** Uniquement :
   - `GET /api/chat/state` : Board, conversation, état vocal, verrou. Lu chaque
     seconde, panneau ouvert et onglet visible ; rien sinon.
   - `GET /api/conversations/events?projection=chat` : hydratation depuis 0
     (`limit=500`, `next_cursor` tant que `has_more`), puis long-poll
     `wait_ms=25000` depuis le dernier `next_cursor` reçu. Une seule attente
     longue par profil : verrou Web Locks `jarvis.chat.<conversation_id>` ; les
     autres onglets lisent avec `wait_ms=0` toutes les 5 s ; sans Web Locks,
     mode solo. Panneau fermé ou onglet caché : aucune requête.
   - `POST /api/chat/turns` : un UUID v4 par message composé, réutilisé à
     chaque reprise (504 `core_timeout` = issue inconnue → même id).
   - `POST /api/chat/voice/disable` : « Passer au chat ».
   Les routes `/api/agent/*` contournent les événements canoniques : ce module
   ne les appelle jamais.

   **Vérité serveur.** Une bulle n'existe que si l'événement canonique existe :
   le message envoyé reste un ÉTAT local (« transmis… », pas une bulle) jusqu'au
   `user.transcript.accepted` de sa corrélation. Le verrou affiché vient de
   `/api/chat/state` ; un 409 `chat_input_locked` reçu malgré tout repasse en
   lecture seule jusqu'à une relecture d'état postérieure qui dit le contraire.
   Les règles de bulles (promotion, repli, échecs) sont celles du modèle pur
   `control_center_chat_model.js` (Slice 02) ; le contenu est posé en
   `textContent`, jamais en HTML.

   **RÈGLE ZÉRO.** Chaque attente dit ce qu'elle fait, depuis combien de temps,
   et a une échéance : envoi (client 20 s, relais 15 s), réponse (120 s →
   phrase honnête et lien vers la chronologie), arrêt du vocal (Core 10 s,
   client 15 s → « Réessayer »), lecture (reprise à pas croissants, affichée).
   Journal : console `[chat] chat.<événement> {…}`, jamais un texte de message.

   **Panneau.** Un seul panneau latéral ouvert : s'ouvrir ferme `#panel`
   (`closePanel`) et l'inspecteur du Studio ; `openPanel`/`closePanel` de la
   page ferment le Chat. Esc ferme et rend le focus à l'onglet. */
(function(root){
  'use strict';
  const doc=root&&root.document;
  const Model=root&&root.JarvisChatModel;

  const DOM=Object.freeze({tab:'chatTab',panel:'chatPanel',sub:'chatSub',close:'chatClose',feed:'chatFeed',
    feedText:'chatFeedText',feedTime:'chatFeedTime',timeline:'chatTimeline',log:'chatLog',lock:'chatLock',lockText:'chatLockText',lockTime:'chatLockTime',
    switchButton:'chatSwitch',input:'chatInput',sendStatus:'chatSendStatus',sendText:'chatSendText',retry:'chatRetry',
    count:'chatCount',send:'chatSend'});
  const ROUTES=Object.freeze({state:'/api/chat/state',events:'/api/conversations/events',turns:'/api/chat/turns',
    disable:'/api/chat/voice/disable'});
  const TIMING=Object.freeze({stateMs:1000,stateTimeoutMs:8000,longWaitMs:25000,followerMs:5000,pageLimit:500,readGraceMs:10000,
    sendTimeoutMs:20000,disableTimeoutMs:10000,replyDeadlineMs:120000,switchDeadlineMs:15000,
    retryMs:[1000,2000,5000,10000]});
  /* Bornes du contrat (`docs/chat.md` › *Configurable bounds*). */
  const MAX_TEXT=8192;
  const STORAGE={open:'jarvis.chat.open',draft:'jarvis.chat.draft.'};
  const LOCK_NAME='jarvis.chat.';

  /* Codes stables → phrases. Un code inconnu est cité tel quel. */
  const SEND_ERRORS=Object.freeze({
    chat_text_too_long:'Message trop long : 8192 caractères au plus.',
    chat_request_conflict:'Ce message a déjà été envoyé avec un autre texte. Renvoyez-le : il partira comme un nouveau message.',
    chat_conversation_not_foreground:'Le Board affiché a changé : message non envoyé. Vérifiez la conversation puis renvoyez.',
    session_not_found:'Aucune Session ouverte : message non envoyé.',
    binding_not_found:'Ce Board n’a pas d’agent lié : message non envoyé.',
    core_unreachable:'Core injoignable : message non envoyé.',
    core_unavailable:'Core indisponible : message non envoyé.',
    core_stopping:'Core s’arrête : message non envoyé.',
    core_unauthorized:'Core a refusé le jeton du Control Center : message non envoyé.',
    invalid_core_response:'Réponse de Core illisible : message non envoyé.',
    forbidden_origin:'Origine refusée par le Control Center.',
    request_too_large:'Message trop volumineux pour le Control Center.',
  });
  /* Issue inconnue : le tour a peut-être été admis. Seule reprise sûre : le même id. */
  const UNKNOWN_OUTCOME=new Set(['core_timeout','client_timeout','network_error']);
  const STATE_ERRORS=Object.freeze({
    session_not_found:'Aucune Session ouverte : ouvrez un Board pour écrire.',
    binding_not_found:'Ce Board n’a pas d’agent lié.',
    core_unreachable:'Core injoignable.',core_unavailable:'Core indisponible.',core_timeout:'Core ne répond pas.',
    core_unconfigured:'Core non configuré.',network_error:'Control Center injoignable.',client_timeout:'Control Center ne répond pas.',
  });

  const now=()=>Date.now();
  const elapsed=ms=>{const s=Math.max(0,Math.round(ms/1000));return s<60?`${s} s`:`${Math.floor(s/60)} min ${String(s%60).padStart(2,'0')} s`};
  function log(event,data,level){
    const line='[chat] chat.'+event+' '+JSON.stringify(data||{});
    const c=root&&root.console;if(!c)return;
    if(level==='error')c.error(line);else if(level==='warn')c.warn(line);else c.info(line);
  }
  function uuid4(){
    const cr=root.crypto;
    if(cr&&typeof cr.randomUUID==='function')return cr.randomUUID();
    const b=new Uint8Array(16);cr.getRandomValues(b);b[6]=(b[6]&0x0f)|0x40;b[8]=(b[8]&0x3f)|0x80;
    const h=[...b].map(x=>x.toString(16).padStart(2,'0')).join('');
    return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
  }
  function store(kind,key,value){
    try{const s=root.localStorage;if(!s)return null;
      if(kind==='get')return s.getItem(key);
      if(value===null)s.removeItem(key);else s.setItem(key,value);
    }catch(_error){/* argued: storage is a per-viewer convenience (private window, blocked site data) */}
    return null;
  }

  /* Requête JSON bornée. Erreur : `code` stable (corps `{ok:false,code}` du
     Control Center, ou `{error:{code}}` de Core), `status` (0 sans réponse). */
  async function request(path,{method='GET',body=null,timeoutMs,signal=null}={}){
    const ctl=new AbortController();let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;ctl.abort()},timeoutMs);
    const onAbort=()=>ctl.abort();
    if(signal){if(signal.aborted)ctl.abort();else signal.addEventListener('abort',onAbort,{once:true})}
    let response,text;
    try{
      response=await root.fetch(path,{method,cache:'no-store',signal:ctl.signal,
        headers:body===null?undefined:{'Content-Type':'application/json'},body:body===null?undefined:JSON.stringify(body)});
      text=await response.text();
    }catch(error){
      const failure=new Error(timedOut?'délai dépassé':(signal&&signal.aborted?'annulé':String(error&&error.message||error)));
      failure.code=timedOut?'client_timeout':(signal&&signal.aborted?'aborted':'network_error');failure.status=0;throw failure;
    }finally{clearTimeout(timer);if(signal)signal.removeEventListener('abort',onAbort)}
    let value=null;
    try{value=text?JSON.parse(text):{}}catch(_error){value=null}
    if(!response.ok){
      const envelope=value&&typeof value.error==='object'&&value.error?value.error:null;
      const failure=new Error((envelope&&envelope.message)||(value&&typeof value.error==='string'&&value.error)||`HTTP ${response.status}`);
      failure.status=response.status;failure.code=(value&&value.code)||(envelope&&envelope.code)||`http_${response.status}`;
      failure.body=value||{};throw failure;
    }
    if(!value||typeof value!=='object'){
      const failure=new Error('réponse non JSON');failure.code='invalid_response';failure.status=response.status;throw failure;
    }
    return {status:response.status,value};
  }

  /* Ce que le composer montre, déduit de l'état serveur et des attentes locales (pur). */
  function composerView(S){
    const state=S.state,voice=state&&state.voice||{};
    if(S.stateError)return {locked:true,tone:'bad',text:STATE_ERRORS[S.stateError.code]||`État du chat illisible (${S.stateError.code}).`,action:null};
    if(!state)return {locked:true,tone:'info',text:'Lecture de l’état du chat…',action:null};
    if(!state.conversation_id)return {locked:true,tone:'bad',text:'Aucune conversation liée à ce Board.',action:null};
    const switching=voice.state==='switching'||S.switch.phase==='pending';
    if(state.chat_writable&&!S.serverLock&&voice.state!=='switching')return {locked:false};
    if(switching)return {locked:true,tone:'info',text:'Arrêt du vocal…',since:S.switch.startedAt||null,action:null};
    const reason=(S.serverLock&&S.serverLock.reason)||state.locked_reason||'voice_unknown';
    /* Seul NOTRE dernier échec de bascule est montré : Core garde l'issue d'une ancienne demande, qui ne dit rien du présent. */
    if(S.switch.phase==='failed')
      return {locked:true,tone:'bad',text:`Le vocal ne s’est pas arrêté (${S.switch.code}). Désactivez le vocal pour écrire.`,action:'retry'};
    if(reason==='voice_unknown')return {locked:true,tone:'info',text:'Lecture de l’état du vocal… (quelques secondes après le démarrage de Core)',action:null};
    const what={voice_active:'Le vocal est actif.',voice_connecting:'Le vocal se connecte.',voice_error:'Le vocal est en erreur.'}[reason]||'Le vocal tient la conversation.';
    return {locked:true,tone:'warn',text:`${what} Désactivez le vocal pour écrire.`,action:'switch'};
  }

  function createChat(){
    const el=Object.fromEntries(Object.entries(DOM).map(([k,id])=>[k,doc.getElementById(id)]));
    const missing=Object.entries(el).filter(([,v])=>!v).map(([k])=>DOM[k]);
    if(missing.length)throw new Error('emplacements manquants : '+missing.join(', '));
    if(!Model)throw new Error('JarvisChatModel absent');

    const model=Model.createChatModel(null);
    const S={open:false,state:null,stateError:null,lastStateErrorCode:null,stateSeq:0,stateInFlight:false,serverLock:null,
      switch:{phase:'idle',startedAt:null,code:null,requestId:null},
      sending:false,draft:null,sendError:null,sent:new Map(),
      feed:{gen:0,cursor:0,hydrated:false,role:'solo',phase:'idle',error:null,retryAt:null,ctl:null,wake:null},
      timer:null,savedScroll:null,stickBottom:true,stats:{stateReads:0,eventReads:0,longPolls:0,sends:0}};

    const visible=()=>!doc.hidden;
    const active=()=>S.open&&visible();

    /* ---------- état ---------- */
    async function readState(){
      if(S.stateInFlight||!active())return;
      S.stateInFlight=true;const seq=++S.stateSeq;S.stats.stateReads++;
      try{
        const {value}=await request(ROUTES.state,{timeoutMs:TIMING.stateTimeoutMs});
        if(S.lastStateErrorCode)log('state_restored',{after:S.lastStateErrorCode});
        S.state=value;S.stateError=null;
        if(S.serverLock&&value.chat_writable&&seq>S.serverLock.seq)S.serverLock=null;
        if(S.switch.phase==='failed'&&value.chat_writable)S.switch={phase:'idle',startedAt:null,code:null,requestId:null};
        followSwitch(value);
        if(value.conversation_id!==model.conversationId)rescope(value.conversation_id||null);
      }catch(error){
        S.stateError={code:error.code||'unknown',at:now()};
        /* Session fermée ou Board sans binding : plus rien à montrer ni à écrire. */
        if(error.status===404){S.state=null;if(model.conversationId)rescope(null)}
        if(!S.lastStateErrorCode||S.lastStateErrorCode!==S.stateError.code)log('state_failed',{code:S.stateError.code,status:error.status},'warn');
      }finally{
        S.lastStateErrorCode=S.stateError&&S.stateError.code;
        S.stateInFlight=false;render();
      }
    }
    function followSwitch(state){
      const sw=S.switch;if(sw.phase!=='pending')return;
      const voice=state.voice||{},req=voice.request||null;
      if(state.chat_writable&&voice.state!=='switching'){
        sw.phase='idle';log('voice_switched',{after_ms:now()-sw.startedAt});
        say('Vocal arrêté : vous pouvez écrire.');
        if(S.open)el.input.focus();
      }else if(req&&(!sw.requestId||req.request_id===sw.requestId)&&(req.status==='failed'||req.status==='expired')){
        sw.phase='failed';sw.code=req.code||`voice_disable_${req.status}`;log('voice_switch_failed',{code:sw.code},'warn');
      }else if(now()-sw.startedAt>TIMING.switchDeadlineMs){
        sw.phase='failed';sw.code='voice_disable_expired';log('voice_switch_failed',{code:sw.code,client_deadline:true},'warn');
      }
    }
    /* Changement de Board (ou de Session) : rien de l'ancienne conversation ne reste. */
    function rescope(conversationId){
      const before=model.conversationId;
      stopFeed();Model.reset(model,conversationId);
      S.feed.cursor=0;S.feed.hydrated=false;S.sent.clear();S.stickBottom=true;nodes.clear();el.log.replaceChildren();
      /* Le texte en cours reste dans le champ (il part, s'il part, comme un NOUVEAU message de ce Board :
         nouvel id). Champ vide : le brouillon gardé pour cette conversation revient (reprise après rechargement). */
      if(S.sendError&&S.sendError.code!=='chat_conversation_not_foreground')S.sendError=null;
      if(el.input.value){S.draft=null}else{S.draft=loadDraft(conversationId);el.input.value=S.draft?S.draft.text:''}
      log('rescoped',{from:before,to:conversationId});
      if(conversationId&&active())startFeed();
    }

    /* ---------- lecture des événements ---------- */
    function eventsUrl(conversationId,cursor,waitMs){
      return `${ROUTES.events}?conversation_id=${encodeURIComponent(conversationId)}&after_sequence=${cursor}&limit=${TIMING.pageLimit}&projection=chat${waitMs?`&wait_ms=${waitMs}`:''}`;
    }
    function startFeed(){
      stopFeed();
      if(!active()||!model.conversationId)return;
      const gen=++S.feed.gen;runFeed(gen,model.conversationId);
    }
    function stopFeed(){
      S.feed.gen++;
      if(S.feed.ctl){S.feed.ctl.abort();S.feed.ctl=null}
      if(S.feed.wake)S.feed.wake();
      S.feed.phase='idle';
    }
    function pokeFeed(){if(S.feed.wake)S.feed.wake()}
    function pause(ms,alive){
      return new Promise(resolve=>{
        const done=()=>{clearTimeout(timer);if(S.feed.wake===done)S.feed.wake=null;resolve()};
        const timer=setTimeout(done,ms);S.feed.wake=done;
        if(!alive())done();
      });
    }
    async function runFeed(gen,conversationId){
      const alive=()=>gen===S.feed.gen&&active()&&model.conversationId===conversationId;
      const read=async waitMs=>{
        /* Contrôleur propre à CETTE requête : une génération qui s'achève ne doit pas oublier celui de la suivante. */
        const ctl=new AbortController();S.feed.ctl=ctl;S.stats.eventReads++;if(waitMs)S.stats.longPolls++;
        let page;
        try{({value:page}=await request(eventsUrl(conversationId,S.feed.cursor,waitMs),{timeoutMs:waitMs+TIMING.readGraceMs,signal:ctl.signal}))}
        finally{if(S.feed.ctl===ctl)S.feed.ctl=null}
        if(!alive())return null;
        if(!Array.isArray(page.events)||!Number.isInteger(page.next_cursor)||page.next_cursor<S.feed.cursor||typeof page.has_more!=='boolean'){
          const invalid=new Error('page d’événements hors contrat');invalid.code='invalid_page';throw invalid;
        }
        Model.applyPage(model,page);S.feed.cursor=page.next_cursor;S.feed.error=null;S.feed.attempt=0;
        render();
        return page;
      };
      const catchUp=async()=>{let page;do{page=await read(0)}while(page&&page.has_more&&alive())};
      const locks=root.navigator&&root.navigator.locks&&typeof root.navigator.locks.request==='function'?root.navigator.locks:null;
      S.feed.attempt=0;
      while(alive()){
        try{
          if(!S.feed.hydrated){
            S.feed.phase='hydrating';render();
            await catchUp();if(!alive())return;
            S.feed.hydrated=true;log('hydrated',{conversation_id:conversationId,cursor:S.feed.cursor,items:Model.items(model).length});
          }
          S.feed.phase='live';render();
          if(locks){
            const led=await locks.request(LOCK_NAME+conversationId,{ifAvailable:true},async lock=>{
              if(!lock)return false;
              S.feed.role='leader';render();
              while(alive()){const page=await read(TIMING.longWaitMs);if(page&&page.has_more)await catchUp()}
              return true;
            });
            if(!led&&alive()){S.feed.role='follower';render();await catchUp();await pause(TIMING.followerMs,alive)}
          }else{
            S.feed.role='solo';
            const page=await read(TIMING.longWaitMs);if(page&&page.has_more)await catchUp();
          }
        }catch(error){
          if(!alive()||error.code==='aborted')return;
          const delay=TIMING.retryMs[Math.min(S.feed.attempt,TIMING.retryMs.length-1)];S.feed.attempt++;
          S.feed.phase='retry';S.feed.error={code:error.code||'unknown',status:error.status};S.feed.retryAt=now()+delay;
          log('read_failed',{code:S.feed.error.code,status:error.status,retry_ms:delay},'warn');
          render();
          await pause(delay,alive);
        }
      }
    }

    /* ---------- envoi ---------- */
    function loadDraft(conversationId){
      if(!conversationId)return null;
      try{const v=JSON.parse(store('get',STORAGE.draft+conversationId)||'null');
        return v&&typeof v.id==='string'&&typeof v.text==='string'?v:null}catch(_error){return null}
    }
    function saveDraft(){
      if(!model.conversationId)return;
      const text=el.input.value;
      if(!text){store('set',STORAGE.draft+model.conversationId,null);return}
      /* Un texte modifié est un nouveau message : nouvel id. Inchangé : même id (reprise). */
      if(!S.draft||S.draft.text!==text)S.draft={id:uuid4(),text};
      store('set',STORAGE.draft+model.conversationId,JSON.stringify(S.draft));
    }
    async function send(){
      const view=composerView(S);
      if(S.sending)return;
      if(view.locked){flashLock();return}
      const text=el.input.value;
      if(!text.trim()){el.input.focus();return}
      if(text.length>MAX_TEXT){S.sendError={code:'chat_text_too_long',retry:false};render();return}
      if(!S.draft||S.draft.text!==text)S.draft={id:uuid4(),text};
      saveDraft();
      const conversationId=model.conversationId,id=S.draft.id;
      S.sending=true;S.sendError=null;S.sendStartedAt=now();S.stats.sends++;render();
      log('turn_sending',{correlation_id:'chat:'+id,conversation_id:conversationId,chars:text.length});
      try{
        const {status,value}=await request(ROUTES.turns,{method:'POST',timeoutMs:TIMING.sendTimeoutMs,
          body:{conversation_id:conversationId,client_request_id:id,content:text}});
        const correlation=typeof value.correlation_id==='string'&&value.correlation_id?value.correlation_id:'chat:'+id;
        log('turn_admitted',{correlation_id:correlation,status,duplicate:!!value.duplicate});
        if(model.conversationId===conversationId){
          Model.markPending(model,correlation);
          if(!S.sent.has(correlation))S.sent.set(correlation,{at:now()});
        }
        if(el.input.value===text)el.input.value='';
        S.draft=null;store('set',STORAGE.draft+conversationId,null);
        S.stickBottom=true;pokeFeed();
      }catch(error){
        const code=error.code||'unknown';
        log('turn_refused',{correlation_id:'chat:'+id,status:error.status,code},'warn');
        if(code==='chat_input_locked'){
          S.serverLock={reason:(error.body&&error.body.reason)||'voice_unknown',seq:S.stateSeq};
          S.stateInFlight=false;readState();
        }else if(code==='chat_conversation_not_foreground'){
          S.sendError={code,retry:false};readState();
        }else if(code==='chat_request_conflict'){
          S.draft=null;S.sendError={code,retry:false};
        }else{
          S.sendError={code,retry:UNKNOWN_OUTCOME.has(code)||error.status>=500||error.status===0};
        }
      }finally{
        S.sending=false;render();
        if(S.open&&!S.sendError)el.input.focus();
      }
    }

    /* ---------- bascule voix → chat ---------- */
    async function switchToChat(){
      if(S.switch.phase==='pending')return;
      S.switch={phase:'pending',startedAt:now(),code:null,requestId:null};render();
      log('voice_switch_requested',{});
      try{
        const {value}=await request(ROUTES.disable,{method:'POST',timeoutMs:TIMING.disableTimeoutMs,body:{client_request_id:uuid4()}});
        S.switch.requestId=value.request_id||null;
        if(!value.request_id){S.switch.phase='idle'}
      }catch(error){
        S.switch.phase='failed';S.switch.code=error.code||'unknown';
        log('voice_switch_failed',{code:S.switch.code,status:error.status},'warn');
      }finally{S.stateInFlight=false;readState()}
    }

    /* ---------- rendu ---------- */
    let announcer=null;
    function say(text){if(announcer){announcer.textContent='';setTimeout(()=>{announcer.textContent=text},30)}}
    function flashLock(){
      if(el.lock.hidden)return;
      el.lock.classList.remove('flash');void el.lock.offsetWidth;el.lock.classList.add('flash');
    }
    function feedLine(){
      const f=S.feed;
      if(S.stateError&&!S.state)return {tone:'bad',text:STATE_ERRORS[S.stateError.code]||`État illisible (${S.stateError.code})`};
      if(!model.conversationId)return {tone:'muted',text:S.state?'Aucune conversation':'Lecture de l’état…'};
      if(f.phase==='hydrating')return {tone:'busy',text:'Chargement de la conversation…'};
      if(f.phase==='retry'){
        const left=Math.max(0,Math.ceil(((f.retryAt||now())-now())/1000));
        return {tone:'warn',text:`Lecture interrompue (${f.error.code}) · nouvel essai`,time:`dans ${left} s`};
      }
      if(f.phase==='live')return {tone:'ok',text:f.role==='follower'?'En direct · relu toutes les 5 s (un autre onglet écoute)':'En direct'};
      return {tone:'muted',text:'En pause'};
    }
    function boardLabel(){
      const t=doc.getElementById('boardsTitle');const title=t&&t.textContent.trim();
      return title?`Board · ${title}`:'Même conversation que la voix';
    }
    const FAIL_TEXT=code=>`Le Brain n’a pas pu traiter ce message (${code}).`;
    /* Lignes du fil, gardées par clé : un nouveau message AJOUTE un nœud, les autres
       ne bougent pas — le lecteur d'écran (`role=log`, `aria-relevant=additions`)
       n'annonce que le nouveau, et le défilement reste là où l'utilisateur l'a mis. */
    const nodes=new Map();
    function bubble(item){
      const li=doc.createElement('li');
      li.className=`chat-msg ${item.role}${item.role==='brain'&&item.status==='failed'?' failed':''}`;
      li.dataset.eventId=item.event_id;
      const who=doc.createElement('span');who.className='chat-who';
      who.textContent=item.role==='user'?'Vous':(item.status==='failed'?'Jarvis · échec':'Jarvis');
      li.append(who,doc.createTextNode(item.text==null?'':String(item.text)));
      return li;
    }
    function line(cls,text){const li=doc.createElement('li');li.className=cls;li.textContent=text;return li}
    function renderLog(){
      const items=Model.items(model),wanted=[];
      for(const item of items){
        wanted.push([`m:${item.event_id}`,()=>bubble(item)]);
        if(item.role==='user'&&item.failure_code)
          wanted.push([`f:${item.event_id}:${item.failure_code}`,()=>line('chat-turnfail',FAIL_TEXT(item.failure_code))]);
      }
      for(const [correlation,info] of S.sent){
        const user=items.find(i=>i.role==='user'&&i.correlation_id===correlation);
        if(user&&!Model.isPending(model,correlation)){S.sent.delete(correlation);continue}
        const late=now()-info.at>TIMING.replyDeadlineMs;
        wanted.push([`n:${correlation}:${user?'admitted':'sent'}:${late?'late':'wait'}`,()=>note(info.at,!!user,late)]);
      }
      if(!wanted.length&&model.conversationId&&S.feed.hydrated)
        wanted.push(['empty',()=>line('chat-empty','Aucun message dans cette conversation. Écrivez à Jarvis ci-dessous ; la voix et le chat partagent le même fil.')]);
      const box=el.log,atBottom=S.stickBottom||box.scrollHeight-box.scrollTop-box.clientHeight<40;
      const keep=new Map();let cursor=box.firstChild,changed=false;
      for(const [key,make] of wanted){
        const node=nodes.get(key)||make();keep.set(key,node);
        if(node===cursor){cursor=cursor.nextSibling;continue}
        box.insertBefore(node,cursor);changed=true;
      }
      while(cursor){const next=cursor.nextSibling;box.removeChild(cursor);cursor=next;changed=true}
      nodes.clear();for(const [key,node] of keep)nodes.set(key,node);
      box.querySelectorAll('.chat-note time[data-since]').forEach(t=>{t.textContent=elapsed(now()-Number(t.dataset.since))});
      if(changed&&atBottom)box.scrollTop=box.scrollHeight;
      if(changed)S.stickBottom=false;
    }
    /* Attente d'un message envoyé : un ÉTAT, pas une bulle. Compteur visuel seulement (aria-hidden) ;
       après 120 s, phrase honnête et lien vers la chronologie, jamais un faux message. */
    function note(since,admitted,late){
      const li=doc.createElement('li');li.className='chat-note'+(late?' late':'');
      if(late){
        const span=doc.createElement('span');span.textContent='Toujours en cours, ou réponse non affichable ici —';
        const link=doc.createElement('button');link.type='button';link.className='chat-link';link.textContent='voir la chronologie complète';
        link.addEventListener('click',openTimeline);
        li.append(span,link);return li;
      }
      const dots=doc.createElement('span');dots.className='chat-dots';dots.setAttribute('aria-hidden','true');
      dots.append(doc.createElement('i'),doc.createElement('i'),doc.createElement('i'));
      const text=doc.createElement('span');text.textContent=admitted?'Jarvis traite votre message…':'Message transmis · enregistrement…';
      const time=doc.createElement('time');time.dataset.since=String(since);time.setAttribute('aria-hidden','true');time.textContent=elapsed(now()-since);
      li.append(dots,text,time);return li;
    }
    /* Texte réécrit seulement s'il change : une zone vivante n'est pas relancée pour rien. */
    function put(node,text){if(node.textContent!==text)node.textContent=text}
    function render(){
      if(!S.open)return;
      put(el.sub,boardLabel());
      /* Les compteurs vivent hors des zones `role=status` (aria-hidden) : le lecteur d'écran n'est pas relancé chaque seconde. */
      const feed=feedLine();el.feed.dataset.tone=feed.tone;put(el.feedText,feed.text);put(el.feedTime,feed.time||'');
      renderLog();
      const view=composerView(S);
      el.lock.hidden=!view.locked;
      if(view.locked){
        el.lock.dataset.tone=view.tone;put(el.lockText,view.text);
        put(el.lockTime,view.since?elapsed(now()-view.since):'');
        el.switchButton.hidden=!view.action;
        put(el.switchButton,view.action==='retry'?'Réessayer':'Passer au chat');
      }else{put(el.lockText,'');put(el.lockTime,'')}
      el.input.setAttribute('aria-disabled',String(!!view.locked));
      el.input.readOnly=!!view.locked||S.sending;
      el.input.toggleAttribute('aria-busy',S.sending);
      const empty=!el.input.value.trim(),over=el.input.value.length>MAX_TEXT;
      el.send.setAttribute('aria-disabled',String(!!view.locked||S.sending||empty||over));
      el.send.toggleAttribute('aria-busy',S.sending);
      put(el.send,S.sending?`Envoi… ${elapsed(now()-S.sendStartedAt)}`:'Envoyer');
      const len=el.input.value.length;
      put(el.count,len>MAX_TEXT-500?`${len} / ${MAX_TEXT}`:'');el.count.classList.toggle('over',over);
      const err=S.sendError;
      el.sendStatus.hidden=!err;
      if(err){
        put(el.sendText,UNKNOWN_OUTCOME.has(err.code)
          ?`Issue inconnue (${err.code}) : le message est peut-être déjà parti. « Réessayer » le renvoie sans doublon.`
          :(SEND_ERRORS[err.code]||`Message non envoyé (${err.code}).`));
        el.retry.hidden=!err.retry;
      }
    }

    /* ---------- ouverture ---------- */
    function openTimeline(){const b=doc.getElementById('openTimeline');if(b)b.click()}
    function tick(){if(!active())return;readState();render()}
    function startTimers(){if(!S.timer)S.timer=setInterval(tick,TIMING.stateMs)}
    function stopTimers(){if(S.timer){clearInterval(S.timer);S.timer=null}}
    function resume(){
      if(!active())return;
      startTimers();S.stateInFlight=false;readState();
      if(model.conversationId)startFeed();
    }
    function suspend(){stopTimers();stopFeed()}
    function open(options){
      if(S.open)return;
      /* Un seul panneau latéral : `#panel` (closePanel nous ferme aussi : sans effet ici) et l'inspecteur du Studio. */
      try{if(typeof root.closePanel==='function')root.closePanel()}catch(error){log('close_panel_failed',{error:String(error)},'warn')}
      try{const insp=root.JarvisStudioInspector&&root.JarvisStudioInspector.instance;if(insp&&typeof insp.close==='function')insp.close()}
      catch(error){log('close_inspector_failed',{error:String(error)},'warn')}
      S.open=true;el.panel.hidden=false;el.panel.classList.add('open');
      el.tab.setAttribute('aria-expanded','true');
      store('set',STORAGE.open,'1');
      S.stickBottom=S.savedScroll===null;
      render();
      /* Défilement conservé d'une ouverture à l'autre (un `display:none` le remet à zéro). */
      el.log.scrollTop=S.savedScroll!==null?S.savedScroll:el.log.scrollHeight;S.savedScroll=null;
      resume();
      if(!(options&&options.noFocus))el.input.focus();
      log('opened',{conversation_id:model.conversationId});
    }
    function close(options){
      if(!S.open)return;
      const box=el.log;
      S.savedScroll=box.scrollHeight-box.scrollTop-box.clientHeight<40?null:box.scrollTop;
      S.open=false;suspend();
      el.panel.classList.remove('open');el.panel.hidden=true;
      el.tab.setAttribute('aria-expanded','false');
      store('set',STORAGE.open,null);
      if(options&&options.restoreFocus)el.tab.focus();
      log('closed',{});
    }

    function install(){
      announcer=doc.createElement('span');announcer.className='chat-sr';announcer.setAttribute('role','status');
      el.panel.appendChild(announcer);
      el.tab.addEventListener('click',()=>S.open?close({restoreFocus:true}):open());
      el.close.addEventListener('click',()=>close({restoreFocus:true}));
      el.timeline.addEventListener('click',openTimeline);
      el.switchButton.addEventListener('click',()=>switchToChat());
      el.send.addEventListener('click',()=>send());
      el.retry.addEventListener('click',()=>send());
      el.input.addEventListener('keydown',event=>{
        if(event.isComposing||event.keyCode===229)return;
        if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();return}
        /* Saisie dans un composer verrouillé : l'explication se signale (elle est aussi lue via aria-describedby). */
        if((event.key.length===1||event.key==='Backspace'||event.key==='Delete')&&!event.ctrlKey&&!event.metaKey&&composerView(S).locked)flashLock();
      });
      el.input.addEventListener('input',()=>{
        if(S.sendError&&!UNKNOWN_OUTCOME.has(S.sendError.code))S.sendError=null;
        saveDraft();render();
      });
      el.panel.addEventListener('keydown',event=>{
        if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close({restoreFocus:true})}
      });
      doc.addEventListener('visibilitychange',()=>{if(!S.open)return;if(visible()){log('resumed',{});resume()}else{log('suspended',{});suspend()}});
      /* Reprise : panneau rouvert au rechargement, après la fin du `<script>` de la page (closePanel et ses voisins initialisés). */
      if(store('get',STORAGE.open)==='1')setTimeout(()=>open({noFocus:true}),0);
      log('installed',{panel:DOM.panel,locks:!!(root.navigator&&root.navigator.locks)});
    }

    return {install,open,close,toggle:()=>S.open?close({restoreFocus:true}):open(),isOpen:()=>S.open,
      snapshot:()=>({open:S.open,conversation_id:model.conversationId,cursor:S.feed.cursor,feed:{phase:S.feed.phase,role:S.feed.role,
        hydrated:S.feed.hydrated,error:S.feed.error},state:S.state,serverLock:S.serverLock,switch:{...S.switch},sending:S.sending,
        sendError:S.sendError,draft:S.draft?{id:S.draft.id}:null,pending:[...S.sent.keys()],stats:{...S.stats},view:composerView(S),
        items:Model.items(model)})};
  }

  const api={DOM,ROUTES,TIMING,MAX_TEXT,composerView,uuid4,createChat,instance:null,
    open:o=>api.instance&&api.instance.open(o),close:o=>api.instance&&api.instance.close(o),
    isOpen:()=>!!(api.instance&&api.instance.isOpen())};
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(doc&&typeof root.fetch==='function'&&doc.getElementById('chatPanel')){
    try{api.instance=createChat();api.instance.install()}
    catch(error){log('install_failed',{error:String(error&&error.message||error)},'error')}
  }
  if(root)root.JarvisChat=api;
})(typeof window!=='undefined'?window:globalThis);
