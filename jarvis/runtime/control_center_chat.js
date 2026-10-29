/* Chat — onglet bas-droit, panneau et composer (handoff jarvis-unified-chat-and-board-drop, Slice 06).

   Contrat : `docs/chat.md` (*Panel*, *Reading*, *Sending text*, *Voice
   channel*, *Error codes*). Le Chat montre la conversation du binding
   Session+Board actif — la MÊME que la voix — et y écrit par le MÊME Brain.

   **Routes.** Uniquement :
   - `GET /api/chat/state` : Board, conversation, état vocal, verrou.
   - `GET /api/conversations/events?projection=chat` : lecture COURTE (jamais
     `wait_ms`) depuis le dernier `next_cursor` reçu, `limit=500`, suivie tant
     que `has_more`.
   **Aucune requête tenue en attente** (QA S06) : Chrome partage six
   connexions par origine entre tous les onglets et la page en tient déjà
   plusieurs ; un long-poll par onglet affamait `/api/status` dès deux onglets.
   Une boucle par onglet, séquentielle (jamais deux requêtes du Chat en vol) :
   état puis événements, toutes les 1,5 s, toutes les 0,5 s pendant 20 s après
   un envoi ou un changement d'état. Seul le meneur (verrou Web Locks
   `jarvis.chat.<conversation_id>`) lit les événements et les diffuse sur
   `BroadcastChannel('jarvis.chat.<conversation_id>')` ; les suiveurs n'en
   lisent aucun. Sans l'un des deux : solo, même cadence. Panneau fermé ou
   onglet caché : aucune requête.
   - `POST /api/chat/turns` : un UUID v4 par message composé, réutilisé à
     chaque reprise (504 `core_timeout` = issue inconnue → même id).
   - `POST /api/chat/voice/disable` : « Passer au chat ».
   - `POST /api/chat/uploads` (Slice 07b) : UNE pièce jointe par requête,
     multipart `client_upload_id` puis `file`, par `XMLHttpRequest` (seul moyen
     d'avoir la progression d'envoi). L'état des pièces est pur
     (`JarvisChatModel.attachmentView` & co.) ; ici, les `File`, les requêtes et
     le rendu. Bouton « Joindre » (`input type=file multiple` caché) et dépôt sur
     le panneau seulement : un fichier déposé ailleurs ne fait rien et le
     navigateur ne l'ouvre jamais.
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
    count:'chatCount',send:'chatSend',attach:'chatAttach',file:'chatFile',files:'chatFiles',attNote:'chatAttNote',drop:'chatDrop'});
  const ROUTES=Object.freeze({state:'/api/chat/state',events:'/api/conversations/events',turns:'/api/chat/turns',
    disable:'/api/chat/voice/disable',uploads:'/api/chat/uploads'});
  /* Cadences et échéances (ms). `JarvisChat.config` est modifiable à chaud (tests : délai de 120 s
     raccourci sans toucher `Date.now`) ; `DEFAULTS` garde les valeurs du contrat.
     Une lecture relayée doit DURER PLUS que le relais (QA S06) : le relais rend à 10 s (délai de la
     session HTTP du Control Center vers Core) un 504 `core_timeout` qui nomme Jarvis Core ; un délai
     client plus court l'aurait coupé et accusé le Control Center. D'où état 13 s et arrêt du vocal 12 s.
     Pièces jointes : pas de progrès d'envoi pendant `uploadStallMs`, ou pas de réponse
     `uploadAnswerMs` après le dernier octet (relais : 120 s de lecture) → issue inconnue. */
  const DEFAULTS=Object.freeze({tickMs:1500,fastMs:500,fastWindowMs:20000,helloMs:1000,stateTimeoutMs:13000,
    readTimeoutMs:10000,pageLimit:500,sendTimeoutMs:20000,disableTimeoutMs:12000,replyDeadlineMs:120000,
    switchDeadlineMs:15000,slowStateMs:3000,uploadStallMs:30000,uploadAnswerMs:130000,existingWaitMs:15000,
    retryMs:Object.freeze([1000,2000,5000,10000])});
  const config={...DEFAULTS};
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
    core_unreachable:'Jarvis Core ne répond pas : message non envoyé.',
    core_unavailable:'Jarvis Core ne répond pas : message non envoyé.',
    core_stopping:'Core s’arrête : message non envoyé.',
    core_unauthorized:'Core a refusé le jeton du Control Center : message non envoyé.',
    invalid_core_response:'Réponse de Core illisible : message non envoyé.',
    forbidden_origin:'Origine refusée par le Control Center.',
    request_too_large:'Message trop volumineux pour le Control Center.',
    too_many_attachments:'Trop de pièces jointes pour un seul message : retirez-en puis renvoyez.',
    attachment_not_found:'Une pièce jointe n’existe plus chez Jarvis Core : retirez-la, joignez le fichier à nouveau, puis renvoyez.',
    attachment_not_ready:'Une pièce jointe n’est pas encore prête chez Jarvis Core : réessayez dans un instant.',
    attachment_not_allowed:'Une pièce jointe appartient à une autre Session : retirez-la, joignez le fichier à nouveau, puis renvoyez.',
    attachment_other_board:'Une pièce jointe a été ajoutée sur un autre Board : retirez-la, joignez le fichier à nouveau ici, puis renvoyez.',
    edited_after_unknown:'Texte modifié : il partira comme un NOUVEAU message. Le précédent a peut-être déjà été reçu par Jarvis — vérifiez le fil avant d’envoyer.',
  });
  /* Issue inconnue : le tour a peut-être été admis. Seule reprise sûre : le même id. */
  const UNKNOWN_OUTCOME=new Set(['core_timeout','client_timeout','network_error']);
  const STATE_ERRORS=Object.freeze({
    session_not_found:'Aucune Session ouverte : ouvrez un Board pour écrire.',
    binding_not_found:'Ce Board n’a pas d’agent lié.',
    /* Codes de Core relayés (503/504) : c'est Jarvis Core qui ne répond pas, pas le Control Center. */
    core_unreachable:'Jarvis Core ne répond pas.',core_unavailable:'Jarvis Core ne répond pas.',core_timeout:'Jarvis Core ne répond pas.',
    core_unconfigured:'Jarvis Core non configuré.',network_error:'Control Center injoignable.',client_timeout:'Control Center ne répond pas.',
  });

  /* Pièce jointe : code stable → phrase (la borne de Core est dite quand elle est connue). */
  const UPLOAD_ERRORS=Object.freeze({
    upload_empty:'Fichier vide : rien à joindre.',
    upload_name_invalid:'Nom de fichier illisible ou trop long (255 caractères au plus).',
    upload_incomplete:'Envoi coupé avant la fin.',
    upload_conflict:'Le fichier a changé depuis le premier essai.',
    upload_in_progress:'Le premier envoi est encore en cours chez Jarvis Core.',
    upload_storage_failed:'Jarvis Core n’a pas pu enregistrer le fichier.',
    upload_interrupted_reload:'Envoi interrompu par le rechargement de la page : joignez le fichier à nouveau.',
    core_unreachable:'Jarvis Core ne répond pas.',core_unavailable:'Jarvis Core ne répond pas.',core_unconfigured:'Jarvis Core non configuré.',
    core_stopping:'Jarvis Core s’arrête.',core_timeout:'Jarvis Core ne répond pas.',
    /* Délai client : le relais passe les octets à Core en flux et attend SA réponse — c'est Jarvis Core qui ne
       répond pas, comme le dit le verrou (QA S7b). Control Center injoignable = aucune connexion (`network_error`). */
    client_timeout:'Jarvis Core ne répond pas.',network_error:'Control Center injoignable.',
    invalid_response:'Réponse illisible du Control Center.',
  });
  function uploadErrorText(error){
    const M=Model;
    if(error.code==='upload_too_large')
      return error.limitBytes?`Trop volumineux : ${M.formatBytes(error.limitBytes)} au plus par fichier.`:'Trop volumineux pour Jarvis Core.';
    const base=UPLOAD_ERRORS[error.code]||`Échec (${error.code}).`;
    return error.sameId?`${base} Issue inconnue : « Réessayer » le renvoie sans doublon.`:base;
  }

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
    const S={open:false,state:null,stateError:null,lastStateErrorCode:null,stateSeq:0,serverLock:null,stateSig:null,
      switch:{phase:'idle',startedAt:null,code:null,requestId:null},
      sending:false,draft:null,sendError:null,sent:new Map(),
      feed:{cid:null,cursor:0,hydrated:false,role:'idle',phase:'idle',error:null,attempt:0,retryAt:null,
        channel:null,release:null,leading:false,helloAt:0},
      loop:{gen:0,wake:null,fastUntil:0,busySince:null},stateReadSince:null,
      /* Pièces jointes : état pur (modèle) ; `File` et requêtes en cours par clé ; noms des pièces d'un
         message envoyé, par corrélation (état local, perdu au rechargement : le nombre reste, `docs/chat.md`). */
      att:Model.createAttachments(),attTried:false,sentNames:new Map(),
      /* Conversations dont le brouillon gardé a déjà été relu dans CETTE page : le brouillon gardé ne sert
         qu'au rechargement ; ensuite la mémoire fait foi (un aller-retour de Board n'est pas un rechargement). */
      restored:new Set(),
      savedScroll:null,stickBottom:true,stats:{stateReads:0,eventReads:0,ticks:0,shared:0,sends:0}};

    const visible=()=>!doc.hidden;
    const active=()=>S.open&&visible();
    const locks=()=>root.navigator&&root.navigator.locks&&typeof root.navigator.locks.request==='function'?root.navigator.locks:null;
    const canShare=()=>!!(locks()&&typeof root.BroadcastChannel==='function');

    /* ---------- boucle : UNE requête courte à la fois, jamais d'attente tenue ----------
       Chrome partage six connexions par origine entre tous les onglets, et la
       page en tient déjà plusieurs (commandes plein écran, explorateur…). Le
       Chat n'en tient donc aucune : chaque tic lit l'état, puis — meneur ou
       solo seulement — les événements (`wait_ms` absent), en séquence. */
    function fast(reason){
      S.loop.fastUntil=now()+config.fastWindowMs;
      if(reason)log('fast_window',{reason});
      wakeLoop();
    }
    function wakeLoop(){if(S.loop.wake)S.loop.wake()}
    function startLoop(){
      const gen=++S.loop.gen;
      runLoop(gen);
    }
    function stopLoop(){S.loop.gen++;wakeLoop()}
    async function runLoop(gen){
      const alive=()=>gen===S.loop.gen&&active();
      while(alive()){
        S.stats.ticks++;S.loop.busySince=now();
        try{
          await readState();
          if(!alive())break;
          await feedStep(alive);
        }catch(error){
          /* Garde-fou : un tic ne casse jamais la boucle. */
          log('tick_failed',{error:String(error&&error.message||error)},'error');
        }
        S.loop.busySince=null;
        render();
        if(!alive())break;
        const delay=now()<S.loop.fastUntil?config.fastMs:config.tickMs;
        await new Promise(resolve=>{
          const done=()=>{clearTimeout(timer);if(S.loop.wake===done)S.loop.wake=null;resolve()};
          const timer=setTimeout(done,delay);S.loop.wake=done;
        });
      }
    }

    /* ---------- état ---------- */
    async function readState(){
      const seq=++S.stateSeq;S.stats.stateReads++;S.stateReadSince=now();
      try{
        const {value}=await request(ROUTES.state,{timeoutMs:config.stateTimeoutMs});
        S.stateReadSince=null;
        if(S.lastStateErrorCode)log('state_restored',{after:S.lastStateErrorCode});
        S.state=value;S.stateError=null;S.lastStateErrorCode=null;
        if(S.serverLock&&value.chat_writable&&seq>S.serverLock.seq)S.serverLock=null;
        if(S.switch.phase==='failed'&&value.chat_writable)S.switch={phase:'idle',startedAt:null,code:null,requestId:null};
        followSwitch(value);
        const voice=value.voice||{};
        const sig=`${value.conversation_id}|${voice.state}|${value.chat_writable}`;
        if(S.stateSig!==null&&sig!==S.stateSig)fast('state_changed');
        S.stateSig=sig;
        if(value.conversation_id!==model.conversationId)rescope(value.conversation_id||null);
      }catch(error){
        S.stateReadSince=null;
        const code=error.code||'unknown';
        S.stateError={code,at:now(),since:S.stateError&&S.stateError.code===code?S.stateError.since:now()};
        /* Session fermée ou Board sans binding : plus rien à montrer ni à écrire. */
        if(error.status===404){S.state=null;if(model.conversationId)rescope(null)}
        if(S.lastStateErrorCode!==S.stateError.code)log('state_failed',{code:S.stateError.code,status:error.status},'warn');
        S.lastStateErrorCode=S.stateError.code;
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
      }else if(now()-sw.startedAt>config.switchDeadlineMs){
        sw.phase='failed';sw.code='voice_disable_expired';log('voice_switch_failed',{code:sw.code,client_deadline:true},'warn');
      }
    }
    /* Changement de Board (ou de Session) : rien de l'ancienne conversation ne reste,
       pas même le texte du champ — un brouillon appartient à SA conversation. */
    function rescope(conversationId){
      const before=model.conversationId;
      leaveFeed();Model.reset(model,conversationId);
      S.sent.clear();S.stickBottom=true;nodes.clear();el.log.replaceChildren();
      if(S.sendError&&S.sendError.code!=='chat_conversation_not_foreground')S.sendError=null;
      S.draft=loadDraft(conversationId);el.input.value=S.draft?S.draft.text:'';
      /* Pièces gardées : relues UNE fois par page (rechargement). Un retour sur un Board déjà vu garde les
         pièces vivantes de la mémoire — un envoi encore en cours n'est pas « interrompu par le rechargement »
         (QA S7b). Le modèle écarte en plus toute pièce déjà présente (même `client_upload_id`). */
      if(S.draft&&conversationId&&!S.restored.has(conversationId))
        for(const saved of S.draft.att)Model.restoreAttachment(S.att,{...saved,cid:conversationId});
      if(conversationId)S.restored.add(conversationId);
      S.attTried=false;
      /* Les pièces jointes restent, liées à LEUR conversation : vues d'ici, elles sont « à renvoyer ». */
      const stale=Model.attachmentView(S.att,conversationId).stale;
      log('rescoped',{from:before,to:conversationId,stale_attachments:stale});
      flushExisting();
    }

    /* ---------- lecture des événements : un meneur par profil, partagé ----------
       Meneur = détenteur du verrou Web Locks `jarvis.chat.<conversation_id>` :
       lui seul lit `GET /api/conversations/events?projection=chat` (courte) et
       diffuse ses lignes sur `BroadcastChannel('jarvis.chat.<conversation_id>')`.
       Un suiveur ne lit aucun événement : il demande l'historique (`hello`) et
       signale ses envois (`poke`) pour que le meneur accélère. Sans Web Locks ou
       sans BroadcastChannel : solo, même cadence. */
    function joinFeed(cid){
      const f=S.feed;
      f.cid=cid;f.cursor=0;f.hydrated=false;f.error=null;f.attempt=0;f.retryAt=null;f.helloAt=0;
      f.phase='hydrating';f.role=canShare()?'follower':'solo';
      if(canShare()){
        try{f.channel=new root.BroadcastChannel(LOCK_NAME+cid);f.channel.onmessage=event=>onShared(cid,event.data)}
        catch(error){f.channel=null;f.role='solo';log('channel_failed',{error:String(error)},'warn')}
      }
    }
    function leaveFeed(){
      const f=S.feed;
      if(f.release){f.release();f.release=null}
      f.leading=false;
      if(f.channel){try{f.channel.close()}catch(_error){/* argued: closing a closed channel is a no-op */}f.channel=null}
      f.cid=null;f.role='idle';f.phase='idle';
    }
    function share(message){
      const f=S.feed;if(!f.channel)return;
      try{f.channel.postMessage(message);S.stats.shared++}catch(error){log('share_failed',{error:String(error)},'warn')}
    }
    function onShared(cid,message){
      const f=S.feed;
      if(!message||typeof message!=='object'||f.cid!==cid||model.conversationId!==cid)return;
      if(message.type==='rows'&&f.role==='follower'&&Array.isArray(message.rows)){
        /* Le modèle garde une ligne par `event_id` : un `hello` rejoué ne double rien (QA S06). */
        Model.applyPage(model,message.rows);
        if(Number.isInteger(message.cursor)&&message.cursor>f.cursor)f.cursor=message.cursor;
        if(!f.hydrated){f.hydrated=true;log('hydrated',{conversation_id:cid,shared:true,items:Model.items(model).length})}
        f.phase='live';f.error=message.error||null;
        render();
      }else if(message.type==='hello'&&f.leading){
        share({type:'rows',rows:Model.storedRows(model),cursor:f.cursor,error:f.error});
      }else if(message.type==='poke'&&f.leading){
        fast('follower_sent');
      }
    }
    /* Prend le verrou s'il est libre ; le garde jusqu'à `leaveFeed`. */
    function tryLead(cid){
      return new Promise(resolve=>{
        locks().request(LOCK_NAME+cid,{ifAvailable:true},lock=>{
          if(!lock||S.feed.cid!==cid){resolve(false);return undefined}
          resolve(true);
          return new Promise(release=>{S.feed.release=release});
        }).catch(error=>{log('lock_failed',{error:String(error)},'warn');resolve(false)});
      });
    }
    async function feedStep(alive){
      const cid=model.conversationId,f=S.feed;
      /* Pas encore de conversation (état pas lu, ou en échec) : aucune lecture d'événements. */
      if(!cid){if(f.cid)leaveFeed();return}
      if(f.cid!==cid){leaveFeed();joinFeed(cid)}
      if(f.role==='follower'&&!f.leading){
        if(await tryLead(cid)){
          if(!alive()||f.cid!==cid){if(f.release){f.release();f.release=null}return}
          f.leading=true;f.role='leader';log('leading',{conversation_id:cid,cursor:f.cursor});
        }else{
          if(!f.hydrated&&now()-f.helloAt>config.helloMs){f.helloAt=now();share({type:'hello'})}
          return;
        }
      }
      if(f.retryAt&&now()<f.retryAt)return;
      try{
        let page;
        do{
          S.stats.eventReads++;
          ({value:page}=await request(eventsUrl(cid,f.cursor),{timeoutMs:config.readTimeoutMs}));
          if(!alive()||f.cid!==cid)return;
          if(!Array.isArray(page.events)||!Number.isInteger(page.next_cursor)||page.next_cursor<f.cursor||typeof page.has_more!=='boolean'){
            const invalid=new Error('page d’événements hors contrat');invalid.code='invalid_page';throw invalid;
          }
          const fresh=page.events.filter(row=>row&&row.event&&row.event.conversation_id===cid);
          Model.applyPage(model,fresh);f.cursor=page.next_cursor;
          if(fresh.length)share({type:'rows',rows:fresh,cursor:f.cursor});
          else if(!f.hydrated)share({type:'rows',rows:[],cursor:f.cursor});
        }while(page.has_more&&alive());
        if(!f.hydrated){f.hydrated=true;log('hydrated',{conversation_id:cid,cursor:f.cursor,items:Model.items(model).length})}
        if(f.error)log('read_restored',{after:f.error.code});
        f.phase='live';f.error=null;f.attempt=0;f.retryAt=null;
      }catch(error){
        if(!alive()||f.cid!==cid)return;
        const delay=config.retryMs[Math.min(f.attempt,config.retryMs.length-1)];f.attempt++;
        f.phase='retry';f.error={code:error.code||'unknown',status:error.status};f.retryAt=now()+delay;
        log('read_failed',{code:f.error.code,status:error.status,retry_ms:delay},'warn');
        share({type:'rows',rows:[],cursor:f.cursor,error:f.error});
      }
    }
    function eventsUrl(conversationId,cursor){
      return `${ROUTES.events}?conversation_id=${encodeURIComponent(conversationId)}&after_sequence=${cursor}&limit=${config.pageLimit}&projection=chat`;
    }

    /* ---------- envoi ---------- */
    function loadDraft(conversationId){
      if(!conversationId)return null;
      try{const v=JSON.parse(store('get',STORAGE.draft+conversationId)||'null');
        if(!v||typeof v.id!=='string'||typeof v.text!=='string')return null;
        const att=Array.isArray(v.att)?v.att.filter(a=>a&&typeof a.name==='string'):[];
        return {id:v.id,text:v.text,cid:conversationId,att,sig:null}}catch(_error){return null}
    }
    /* Le brouillon est rangé sous SA conversation : jamais envoyé dans une autre. Il garde le texte et
       les pièces jointes prêtes (id d'Artifact, nom, taille) ; une pièce encore en cours est notée
       interrompue (avec son `client_upload_id`) : c'est l'enregistrement de REPRISE APRÈS RECHARGEMENT,
       relu une fois par page (`rescope`) — au rechargement elle le dit, jamais perdue en silence. */
    function draftAttachments(cid){
      return Model.attachmentView(S.att,cid).items.filter(i=>i.status!=='stale'&&i.state!=='failed')
        .map(i=>i.state==='ready'?{name:i.name,size:i.size,mime:i.mime,artifactId:i.artifactId,readable:i.readable,clientUploadId:i.clientUploadId,
          ...(i.existing?{existing:true}:{})}
          :{name:i.name,size:i.size,clientUploadId:i.clientUploadId,interrupted:true});
    }
    /* Brouillon gardé de la conversation `cid`, même quand elle n'est pas affichée : une pièce qui finit,
       qu'on retire ou qu'on « Renvoie ici » depuis un autre Board met à jour SON brouillon (sinon un
       rechargement la dirait interrompue alors qu'elle est prête). Texte inchangé ; un autre jeu de pièces
       prêtes est un autre message (nouvel id). */
    function persistDraft(cid){
      if(!cid)return;
      if(cid===model.conversationId){saveDraft();return}
      const saved=loadDraft(cid),att=draftAttachments(cid),text=saved?saved.text:'';
      if(!text&&!att.length){store('set',STORAGE.draft+cid,null);return}
      const ready=list=>list.filter(a=>a.artifactId).map(a=>a.artifactId).sort().join(',');
      const id=saved&&ready(saved.att)===ready(att)?saved.id:uuid4();
      store('set',STORAGE.draft+cid,JSON.stringify({id,text,att}));
    }
    function saveDraft(){
      const cid=model.conversationId;if(!cid)return;
      const text=el.input.value,sig=Model.attachmentSignature(S.att,cid);
      const att=draftAttachments(cid);
      if(!text&&!att.length){S.draft=null;store('set',STORAGE.draft+cid,null);return}
      /* Un texte ou un jeu de pièces modifié est un nouveau message : nouvel id. Inchangé : même id (reprise). */
      if(!S.draft||S.draft.cid!==cid||S.draft.text!==text||(S.draft.sig!==null&&S.draft.sig!==sig))S.draft={id:uuid4(),text,cid,att:[],sig};
      S.draft.sig=sig;
      store('set',STORAGE.draft+cid,JSON.stringify({id:S.draft.id,text,att}));
    }
    /* Après une issue inconnue, un texte OU des pièces modifiés font un autre message : la promesse
       « sans doublon » ne vaut plus, et le précédent a peut-être été reçu. */
    function draftEdited(){
      const err=S.sendError;
      if(err&&UNKNOWN_OUTCOME.has(err.code)){
        if(el.input.value!==err.text||Model.attachmentSignature(S.att,model.conversationId)!==err.sig)S.sendError={code:'edited_after_unknown',retry:false};
      }else if(err&&err.code!=='edited_after_unknown')S.sendError=null;
      saveDraft();render();
    }
    async function send(){
      const view=composerView(S);
      if(S.sending)return;
      if(view.locked){flashLock();return}
      const text=el.input.value,conversationId=model.conversationId;
      const att=Model.attachmentView(S.att,conversationId);
      /* Pièces : envoi refusé tant qu'une pièce est en cours ou en échec (aucune perte silencieuse),
         et un message doit porter du texte (`BrainTurnInput` l'exige) : on le dit, on n'invente rien. */
      if(att.blocked||(att.ids.length&&!text.trim())){
        S.attTried=true;log('turn_held',{reason:att.blocked||'text_required',attachments:att.ids.length,uploading:att.uploading,failed:att.failed});
        render();flash(el.attNote);if(!att.blocked)el.input.focus();return;
      }
      if(!text.trim()){el.input.focus();return}
      if(text.length>MAX_TEXT){S.sendError={code:'chat_text_too_long',retry:false};render();return}
      saveDraft();
      const id=S.draft.id,ids=att.ids.slice(),sig=Model.attachmentSignature(S.att,conversationId);
      S.sending=true;S.sendError=null;S.sendStartedAt=now();S.stats.sends++;render();
      log('turn_sending',{correlation_id:'chat:'+id,conversation_id:conversationId,chars:text.length,attachments:ids.length});
      try{
        const body={conversation_id:conversationId,client_request_id:id,content:text};
        if(ids.length)body.attachments=ids;
        const {status,value}=await request(ROUTES.turns,{method:'POST',timeoutMs:config.sendTimeoutMs,body});
        const correlation=typeof value.correlation_id==='string'&&value.correlation_id?value.correlation_id:'chat:'+id;
        log('turn_admitted',{correlation_id:correlation,status,duplicate:!!value.duplicate,attachments:ids.length});
        /* Les noms des pièces envoyées ne vivent qu'ici (état local du message) ; bornés aux 50 derniers. */
        const sent=Model.takeSent(S.att,conversationId,ids);
        for(const item of sent)files.delete(item.key);
        if(sent.length){S.sentNames.set(correlation,sent);while(S.sentNames.size>50)S.sentNames.delete(S.sentNames.keys().next().value)}
        S.attTried=false;
        if(model.conversationId===conversationId){
          Model.markPending(model,correlation);
          if(!S.sent.has(correlation))S.sent.set(correlation,{at:now()});
          if(el.input.value===text)el.input.value='';
          S.draft=null;
        }
        store('set',STORAGE.draft+conversationId,null);
        if(model.conversationId===conversationId)saveDraft();
        S.stickBottom=true;
        if(S.feed.leading||S.feed.role==='solo')fast('sent');else{share({type:'poke'});S.loop.fastUntil=now()+config.fastWindowMs}
      }catch(error){
        const code=error.code||'unknown';
        log('turn_refused',{correlation_id:'chat:'+id,status:error.status,code},'warn');
        if(code==='chat_input_locked'){
          S.serverLock={reason:(error.body&&error.body.reason)||'voice_unknown',seq:S.stateSeq};fast('locked');
        }else if(code==='chat_conversation_not_foreground'){
          S.sendError={code,retry:false};fast('not_foreground');
        }else if(code==='chat_request_conflict'){
          S.draft=null;S.sendError={code,retry:false};
        }else{
          S.sendError={code,retry:UNKNOWN_OUTCOME.has(code)||error.status>=500||error.status===0,text,id,sig};
        }
      }finally{
        S.sending=false;render();
        if(S.open&&!S.sendError)el.input.focus();
      }
    }

    /* ---------- pièces jointes : une requête par fichier ---------- */
    const files=new Map(),uploads=new Map();
    function attachFiles(list,via){
      const chosen=[...(list||[])];
      if(!chosen.length)return;
      const cid=model.conversationId;
      if(!cid){say('Aucune conversation liée : impossible de joindre un fichier.');log('attach_refused',{via,reason:'no_conversation'},'warn');return}
      if(S.sending){say('Envoi du message en cours : joignez le fichier juste après.');log('attach_refused',{via,reason:'sending'},'warn');return}
      for(const file of chosen){
        const item=Model.addAttachment(S.att,{name:file.name,size:file.size,mime:file.type,cid,clientUploadId:uuid4()});
        files.set(item.key,file);upload(item.key);
      }
      log('attached',{via,count:chosen.length,conversation_id:cid});
      say(chosen.length>1?`${chosen.length} fichiers en cours d’envoi.`:'Fichier en cours d’envoi.');
      draftEdited();
    }
    /* XMLHttpRequest : la progression d'envoi (`upload.onprogress`). Échéances : aucun progrès pendant
       `uploadStallMs`, ou aucune réponse `uploadAnswerMs` après le dernier octet → issue inconnue
       (`client_timeout`), reprise avec le même id. Jamais de nom de fichier dans le journal. */
    function upload(key){
      const item=S.att.items.find(i=>i.key===key),file=files.get(key);
      if(!item||!file)return;
      const xhr=new root.XMLHttpRequest(),form=new root.FormData();
      form.append('client_upload_id',item.clientUploadId);form.append('file',file,file.name);
      const job={xhr,startedAt:now(),lastAt:now(),sentAt:null,why:null,timer:null};
      uploads.set(key,job);
      log('upload_started',{key,size:file.size,attempt:item.attempts,same_id:item.replay});
      /* Le brouillon gardé suivi est celui de la conversation de la PIÈCE, pas celle affichée (QA S7b). */
      const settle=fn=>{if(uploads.get(key)!==job)return;clearInterval(job.timer);uploads.delete(key);fn();
        const held=S.att.items.find(i=>i.key===key);persistDraft(held?held.cid:item.cid);render()};
      xhr.upload.onprogress=event=>{
        job.lastAt=now();Model.attachmentProgress(S.att,key,event.loaded,event.lengthComputable?event.total:file.size);
        if(now()-(job.paintAt||0)>200){job.paintAt=now();render()}
      };
      xhr.upload.onload=()=>{job.lastAt=now();job.sentAt=now();Model.attachmentSent(S.att,key);render()};
      xhr.onload=()=>settle(()=>{
        let body=null;
        try{body=xhr.responseText?JSON.parse(xhr.responseText):null}catch(_error){body=null}
        if((xhr.status===200||xhr.status===201)&&body&&body.ok===true){
          const ready=Model.attachmentReady(S.att,key,body);
          if(ready&&ready.state==='ready'){
            log('upload_ready',{key,artifact_id:ready.artifactId,size:ready.size,mime:ready.mime,brain_readable:ready.readable,replayed:!!body.replayed,status:xhr.status});
            say(ready.readable?'Pièce prête.':'Pièce prête, mais le Brain ne pourra pas la lire.');
          }else log('upload_failed',{key,code:'invalid_response',status:xhr.status},'warn');
          return;
        }
        const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
        const code=(body&&body.code)||(envelope&&envelope.code)||`http_${xhr.status}`;
        const message=(body&&typeof body.error==='string'&&body.error)||(envelope&&envelope.message)||'';
        failUpload(key,{code,status:xhr.status,limitBytes:Model.uploadLimitFrom(message)});
      });
      xhr.onerror=()=>settle(()=>failUpload(key,{code:'network_error',status:0}));
      xhr.onabort=()=>settle(()=>{if(job.why)failUpload(key,{code:job.why,status:0})});
      /* Garde-fou : la requête ne peut pas attendre sans fin, même si le navigateur la garde en file. */
      job.timer=setInterval(()=>{
        const quiet=now()-job.lastAt;
        if(job.sentAt?now()-job.sentAt>config.uploadAnswerMs:quiet>config.uploadStallMs){job.why='client_timeout';xhr.abort()}
      },1000);
      xhr.open('POST',ROUTES.uploads);xhr.send(form);
    }
    function failUpload(key,failure){
      const {item,autoRetry}=Model.attachmentFailed(S.att,key,failure);
      if(!item)return;
      log('upload_failed',{key,code:failure.code,status:failure.status,same_id:item.error.sameId,auto_retry:autoRetry},'warn');
      if(autoRetry){
        /* La reprise au même id a appris que l'essai précédent avait échoué chez Core : nouvel id, une fois. */
        Model.retryAttachment(S.att,key,uuid4());upload(key);return;
      }
      say(`Échec d’une pièce jointe : ${uploadErrorText(item.error)}`);
    }
    function retryUpload(key){
      const item=Model.retryAttachment(S.att,key,uuid4());
      if(!item)return;
      log('upload_retry',{key,same_id:item.replay,attempt:item.attempts});
      upload(key);render();
    }
    function rebindUpload(key){
      const cid=model.conversationId;
      if(!cid||!files.has(key))return;
      const before=S.att.items.find(i=>i.key===key),from=before&&before.cid;
      const item=Model.rebindAttachment(S.att,key,cid,uuid4());
      if(!item)return;
      log('upload_rebound',{key,conversation_id:cid});
      upload(key);draftEdited();persistDraft(from);
    }
    function removeUpload(key){
      const held=S.att.items.find(i=>i.key===key),from=held&&held.cid;
      const before=Model.removeAttachment(S.att,key);
      if(before===null)return;
      const job=uploads.get(key);
      if(job){clearInterval(job.timer);uploads.delete(key);job.xhr.abort()}
      files.delete(key);
      log('upload_removed',{key,was:before});
      say('Pièce retirée.');
      draftEdited();if(from!==model.conversationId)persistDraft(from);
      el.input.focus();
    }

    /* ---------- pièce déjà chez Core (orbital-ui Slice 05, D7) ----------
       « Envoyer à Jarvis » d'une capture d'écran : la pièce est un Artifact `complete` de Core ; ni
       téléversement, ni octet dans la page (le brouillon garde l'id, le nom, la taille). Le panneau
       s'ouvre et le champ prend le focus : le texte reste exigé, rien ne part tout seul. Sans
       conversation connue (panneau jamais ouvert), la pièce attend la première lecture d'état, au plus
       `existingWaitMs` ; Core reste juge à l'envoi (`attachment_not_allowed`, `attachment_not_ready`).
       L'attente se voit (QA S05, polish 1) : une puce « En attente de la conversation… N s » avec sa croix
       qui l'annule ; à l'échéance, une puce d'échec qui reste jusqu'à ce qu'on la ferme. */
    let waitingExisting=null,existingFailed=null,existingRow=null;
    function attachExisting(spec){
      const id=spec&&typeof spec.artifact_id==='string'?spec.artifact_id:'';
      if(!/^jart_[A-Za-z0-9_]{1,96}$/.test(id)){log('attach_existing_refused',{reason:'bad_artifact_id'},'warn');return {ok:false,code:'invalid_artifact_id'}}
      if(S.sending){
        say('Envoi du message en cours : joignez la capture juste après.');
        log('attach_existing_refused',{artifact_id:id,reason:'sending'},'warn');return {ok:false,code:'sending'};
      }
      const item={artifactId:id,name:String(spec.original_name||'pièce').slice(0,200),
        size:Number.isFinite(spec.size_bytes)?spec.size_bytes:0,mime:typeof spec.mime_type==='string'?spec.mime_type:''};
      open();
      existingFailed=null;
      if(!model.conversationId){
        if(waitingExisting)clearTimeout(waitingExisting.timer);
        waitingExisting={item,since:now(),timer:setTimeout(()=>{
          waitingExisting=null;existingFailed={item};
          say('Aucune conversation liée : la capture n’a pas été jointe.');
          log('attach_existing_refused',{artifact_id:id,reason:'no_conversation'},'warn');render();
        },config.existingWaitMs)};
        log('attach_existing_waiting',{artifact_id:id});
        render();
        return {ok:true,pending:true};
      }
      return {ok:true,pending:false,key:placeExisting(item)};
    }
    function placeExisting(item){
      const cid=model.conversationId;
      const placed=Model.addExistingAttachment(S.att,{...item,cid});
      log('attached_existing',{artifact_id:item.artifactId,conversation_id:cid,key:placed.key});
      say('Capture jointe : écrivez votre message puis envoyez.');
      draftEdited();
      if(S.open)el.input.focus();
      return placed.key;
    }
    function flushExisting(){
      if(!waitingExisting||!model.conversationId)return;
      const {item,timer}=waitingExisting;waitingExisting=null;clearTimeout(timer);
      placeExisting(item);
    }
    /* La croix de la puce d'attente ou d'échec : l'attente s'arrête, rien n'est joint. */
    function dismissExisting(){
      if(waitingExisting){
        clearTimeout(waitingExisting.timer);
        log('attach_existing_cancelled',{artifact_id:waitingExisting.item.artifactId});
        waitingExisting=null;say('Capture non jointe.');
      }
      existingFailed=null;render();
      if(S.open)el.input.focus();
    }
    function existingView(){
      if(waitingExisting)return {name:waitingExisting.item.name,status:'waiting',text:'En attente de la conversation…',
        time:elapsed(now()-waitingExisting.since),busy:true};
      if(existingFailed)return {name:existingFailed.item.name,status:'failed',text:'Non jointe : aucune conversation liée',time:'',busy:false};
      return null;
    }

    /* ---------- bascule voix → chat ---------- */
    async function switchToChat(){
      if(S.switch.phase==='pending')return;
      S.switch={phase:'pending',startedAt:now(),code:null,requestId:null};render();
      log('voice_switch_requested',{});
      try{
        const {value}=await request(ROUTES.disable,{method:'POST',timeoutMs:config.disableTimeoutMs,body:{client_request_id:uuid4()}});
        S.switch.requestId=value.request_id||null;
        if(!value.request_id){S.switch.phase='idle'}
      }catch(error){
        S.switch.phase='failed';S.switch.code=error.code||'unknown';
        log('voice_switch_failed',{code:S.switch.code,status:error.status},'warn');
      }finally{fast('voice_switch');render()}
    }

    /* ---------- rendu ---------- */
    let announcer=null;
    function say(text){if(announcer){announcer.textContent='';setTimeout(()=>{announcer.textContent=text},30)}}
    function flash(node){
      if(!node||node.hidden)return;
      node.classList.remove('flash');void node.offsetWidth;node.classList.add('flash');
    }
    function flashLock(){flash(el.lock)}
    /* UNE ligne d'état cohérente avec le verrou (QA S06) : jamais « En direct » quand l'état ne se lit plus. */
    function feedLine(){
      const f=S.feed;
      if(S.stateError){
        const cause=STATE_ERRORS[S.stateError.code]||`État illisible (${S.stateError.code}).`;
        return {tone:'bad',text:S.state?`Connexion interrompue · ${cause.replace(/\.$/,'')} · nouvel essai`:cause,time:S.state?elapsed(now()-S.stateError.since):''};
      }
      /* Lecture d'état lente (le relais rend à 10 s) : dit, avec son compteur, avant toute autre ligne. */
      if(S.stateReadSince&&now()-S.stateReadSince>config.slowStateMs)
        return {tone:'warn',text:'Jarvis tarde à répondre · lecture de l’état',time:elapsed(now()-S.stateReadSince)};
      if(!model.conversationId)return {tone:'muted',text:S.state?'Aucune conversation':'Lecture de l’état…'};
      if(f.phase==='hydrating')return {tone:'busy',text:'Chargement de la conversation…'};
      if(f.phase==='retry'){
        const left=Math.ceil(((f.retryAt||now())-now())/1000);
        if(left>0)return {tone:'warn',text:`Lecture interrompue (${f.error.code}) · nouvel essai`,time:`dans ${left} s`};
        /* Échéance passée : l'essai est parti (ou attend sa place dans la file du navigateur). Compteur depuis son départ. */
        const since=Math.max(f.retryAt||0,S.loop.busySince||0)||now();
        return {tone:'busy',text:`Lecture interrompue (${f.error.code}) · nouvel essai en cours`,time:elapsed(now()-since)};
      }
      if(f.role==='follower'&&f.error)return {tone:'warn',text:`Lecture interrompue (${f.error.code}) · l’onglet qui lit réessaie`};
      if(f.phase==='live')return {tone:'ok',text:f.role==='follower'?'En direct · lu par un autre onglet':'En direct'};
      return {tone:'muted',text:'En pause'};
    }
    function boardLabel(){
      const t=doc.getElementById('boardsTitle');const title=t&&t.textContent.trim();
      return title?`Board · ${title}`:'Même conversation que la voix';
    }
    const FAIL_TEXT=code=>`Le Brain n’a pas pu traiter ce message (${code}).`;
    const plural=(n,one,many)=>`${n} ${n>1?many:one}`;
    /* Lignes du fil, gardées par clé : un nouveau message AJOUTE un nœud, les autres
       ne bougent pas — le lecteur d'écran (`role=log`, `aria-relevant=additions`)
       n'annonce que le nouveau, et le défilement reste là où l'utilisateur l'a mis. */
    const nodes=new Map();
    function bubble(item,count,names){
      const li=doc.createElement('li');
      li.className=`chat-msg ${item.role}${item.role==='brain'&&item.status==='failed'?' failed':''}`;
      li.dataset.eventId=item.event_id;
      const who=doc.createElement('span');who.className='chat-who';
      who.textContent=item.role==='user'?'Vous':(item.status==='failed'?'Jarvis · échec':'Jarvis');
      li.append(who,doc.createTextNode(item.text==null?'':String(item.text)));
      if(count)li.append(attachmentsLine(count,names));
      return li;
    }
    /* « N pièce(s) jointe(s) » (`attributes.attachment_count`) ; noms seulement depuis l'état local du
       message envoyé ici ; sinon (rechargement, autre onglet) un lien vers l'inspecteur Workspace. */
    function attachmentsLine(count,names){
      const box=doc.createElement('span');box.className='chat-att';
      const head=doc.createElement('span');head.className='chat-att-count';head.textContent=plural(count,'pièce jointe','pièces jointes');
      box.append(head);
      if(names&&names.length){
        const list=doc.createElement('span');list.className='chat-att-names';
        /* Chaque nom isolé (`<bdi>`, texte seulement) : un U+202E dans un nom ne retourne pas le suivant. */
        names.forEach((n,i)=>{
          if(i)list.append(doc.createTextNode(' · '));
          const name=doc.createElement('bdi');name.textContent=n.name;list.append(name);
          if(n.readable===false)list.append(doc.createTextNode(' (non lisible par le Brain)'));
        });
        box.append(list);
      }else{
        const link=doc.createElement('button');link.type='button';link.className='chat-link';link.textContent='voir dans l’inspecteur';
        link.addEventListener('click',openInspector);box.append(link);
      }
      return box;
    }
    function line(cls,text){const li=doc.createElement('li');li.className=cls;li.textContent=text;return li}
    function renderLog(){
      const items=Model.items(model),wanted=[];
      for(const item of items){
        const count=item.role==='user'?Model.attachmentCount(model,item.event_id):0;
        const names=count&&S.sentNames.get(item.correlation_id)||null;
        wanted.push([`m:${item.event_id}${count?`:a${names?1:0}`:''}`,()=>bubble(item,count,names)]);
        if(item.role==='user'&&item.failure_code)
          wanted.push([`f:${item.event_id}:${item.failure_code}`,()=>line('chat-turnfail',FAIL_TEXT(item.failure_code))]);
      }
      for(const [correlation,info] of S.sent){
        const user=items.find(i=>i.role==='user'&&i.correlation_id===correlation);
        if(user&&!Model.isPending(model,correlation)){S.sent.delete(correlation);continue}
        const late=now()-info.at>config.replyDeadlineMs;
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

    /* Liste des pièces : une ligne par pièce, gardée par clé (le focus d'un bouton survit au rendu).
       Chaque attente montre ce qu'elle fait et depuis combien de temps ; chaque pièce a sa sortie (×). */
    const fileRows=new Map();
    function fileStatus(item){
      const started=uploads.get(item.key),since=started?elapsed(now()-(started.sentAt||started.startedAt)):'';
      if(item.status==='stale')return {text:'À renvoyer : jointe sur un autre Board, elle ne partira pas d’ici.',time:'',action:files.has(item.key)?'rebind':null};
      if(item.status==='uploading'){
        if(item.phase==='checking')return {text:'Vérification par Jarvis Core…',time:since,action:null,busy:true};
        const pct=item.total?Math.min(100,Math.floor(item.loaded*100/item.total)):0;
        return {text:`Envoi ${pct} %`,time:since,action:null,busy:true,pct};
      }
      if(item.status==='ready')return {text:'Prête',time:'',action:null};
      if(item.status==='unreadable')return {text:'Prête · jointe, mais le Brain ne pourra pas la lire',time:'',action:null};
      return {text:uploadErrorText(item.error),time:'',action:item.error.retryable&&files.has(item.key)?'retry':null};
    }
    function fileRow(item){
      const li=doc.createElement('li');li.className='chat-file';li.dataset.key=item.key;
      const name=doc.createElement('span');name.className='chat-file-name';
      const meta=doc.createElement('span');meta.className='chat-file-meta';
      const state=doc.createElement('span');state.className='chat-file-state';
      const text=doc.createElement('span');text.className='chat-file-text';
      const time=doc.createElement('span');time.className='chat-file-time';time.setAttribute('aria-hidden','true');
      state.append(text,time);
      const bar=doc.createElement('span');bar.className='chat-file-bar';bar.setAttribute('aria-hidden','true');bar.append(doc.createElement('i'));
      const act=doc.createElement('button');act.type='button';act.className='chat-link chat-file-act';
      act.addEventListener('click',()=>{const mode=act.dataset.mode;if(mode==='retry')retryUpload(item.key);else if(mode==='rebind')rebindUpload(item.key)});
      const x=doc.createElement('button');x.type='button';x.className='chat-file-x';x.textContent='×';
      x.addEventListener('click',()=>removeUpload(item.key));
      li.append(name,meta,state,act,x,bar);
      return li;
    }
    function renderFiles(view){
      const box=el.files,keep=new Set();
      let cursor=box.firstChild;
      for(const item of view.items){
        keep.add(item.key);
        let li=fileRows.get(item.key);
        if(!li){li=fileRow(item);fileRows.set(item.key,li)}
        if(li!==cursor)box.insertBefore(li,cursor);else cursor=cursor.nextSibling;
        const st=fileStatus(item);
        li.dataset.status=item.status;
        put(li.querySelector('.chat-file-name'),item.name||'(sans nom)');
        put(li.querySelector('.chat-file-meta'),Model.formatBytes(item.size));
        put(li.querySelector('.chat-file-text'),st.text);
        put(li.querySelector('.chat-file-time'),st.time);
        li.querySelector('.chat-file-bar').hidden=!st.busy;
        li.querySelector('.chat-file-bar i').style.width=st.pct===undefined?'100%':`${st.pct}%`;
        li.classList.toggle('indeterminate',!!st.busy&&st.pct===undefined);
        const act=li.querySelector('.chat-file-act');
        act.hidden=!st.action;act.dataset.mode=st.action||'';
        put(act,st.action==='rebind'?'Renvoyer ici':'Réessayer');
        li.querySelector('.chat-file-x').setAttribute('aria-label',`Retirer ${item.name||'la pièce'}`);
      }
      for(const [key,li] of fileRows)if(!keep.has(key)){li.remove();fileRows.delete(key)}
      /* Une capture qui attend sa conversation (ou qui n'a pas pu être jointe) : sa puce, à la fin. */
      const pending=existingView();
      if(pending){
        if(!existingRow){
          existingRow=fileRow({key:'existing-wait'});
          existingRow.classList.add('chat-file-existing');
          existingRow.querySelector('.chat-file-x').replaceWith(existingRow.querySelector('.chat-file-x').cloneNode(true));
          existingRow.querySelector('.chat-file-x').addEventListener('click',dismissExisting);
        }
        if(existingRow.parentNode!==box||existingRow.nextSibling)box.appendChild(existingRow);
        existingRow.dataset.status=pending.status;
        put(existingRow.querySelector('.chat-file-name'),pending.name);
        put(existingRow.querySelector('.chat-file-meta'),'');
        put(existingRow.querySelector('.chat-file-text'),pending.text);
        put(existingRow.querySelector('.chat-file-time'),pending.time);
        existingRow.querySelector('.chat-file-bar').hidden=!pending.busy;
        existingRow.classList.toggle('indeterminate',pending.busy);
        existingRow.querySelector('.chat-file-act').hidden=true;
        existingRow.querySelector('.chat-file-x').setAttribute('aria-label',pending.busy?'Annuler l’ajout de la capture':'Fermer ce message');
      }else if(existingRow&&existingRow.parentNode){existingRow.remove()}
      box.hidden=!view.items.length&&!pending;
    }
    /* Ce que les pièces imposent à l'envoi, dit à côté du composer (pas une erreur : une consigne). */
    function attachmentNote(view,text){
      if(view.uploading)return {tone:'info',text:`Envoi possible dès que ${view.uploading>1?`les ${view.uploading} pièces sont prêtes`:'la pièce est prête'}.`};
      if(view.failed)return {tone:'warn',text:'Une pièce est en échec : réessayez-la ou retirez-la avant d’envoyer.'};
      if(view.ids.length&&!text.trim())return {tone:S.attTried?'warn':'info',text:'Ajoutez un message pour accompagner les fichiers.'};
      return null;
    }

    function render(){
      if(!S.open)return;
      /* Écran étroit : la pile de notifications se pose sous l'en-tête et la ligne d'état (règle de la page). */
      const below=Math.round(el.feed.getBoundingClientRect().bottom+8);
      if(below>8&&below!==S.toastsTop){S.toastsTop=below;doc.documentElement.style.setProperty('--chat-toasts-top',below+'px')}
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
      const att=Model.attachmentView(S.att,model.conversationId);
      renderFiles(att);
      const attNote=attachmentNote(att,el.input.value);
      el.attNote.hidden=!attNote;
      if(attNote){el.attNote.dataset.tone=attNote.tone;put(el.attNote,attNote.text)}
      /* Joindre reste possible voix active (préparer n'est pas envoyer) ; pas sans conversation ni pendant un envoi. */
      el.attach.setAttribute('aria-disabled',String(!model.conversationId||S.sending));
      const empty=!el.input.value.trim(),over=el.input.value.length>MAX_TEXT;
      el.send.setAttribute('aria-disabled',String(!!view.locked||S.sending||empty||over||!!att.blocked));
      el.send.toggleAttribute('aria-busy',S.sending);
      put(el.send,S.sending?`Envoi… ${elapsed(now()-S.sendStartedAt)}`:'Envoyer');
      const len=el.input.value.length;
      put(el.count,len>MAX_TEXT-500?`${len} / ${MAX_TEXT}`:'');el.count.classList.toggle('over',over);
      const err=S.sendError;
      el.sendStatus.hidden=!err;
      if(err){
        put(el.sendText,UNKNOWN_OUTCOME.has(err.code)
          ?`Issue inconnue : ${err.code==='core_timeout'?'Jarvis Core':'le Control Center'} ne répond pas (${err.code}). Le message est peut-être déjà parti ; « Réessayer » le renvoie sans doublon.`
          :(SEND_ERRORS[err.code]||`Message non envoyé (${err.code}).`));
        el.retry.hidden=!err.retry;
      }
    }

    /* ---------- ouverture ---------- */
    function openTimeline(){const b=doc.getElementById('openTimeline');if(b)b.click()}
    /* Pièces d'un message relu (noms inconnus ici) : l'inspecteur Workspace, sur le Board de la conversation. */
    function openInspector(){
      const ws=root.JarvisWorkspace,board=S.state&&S.state.board_id;
      if(!ws||typeof ws.openBoard!=='function'||!board){
        log('inspector_unavailable',{board_id:board||null},'warn');
        say('Inspecteur Workspace indisponible : ouvrez-le depuis le dock.');return;
      }
      close({});
      Promise.resolve(ws.openBoard(board)).catch(error=>log('inspector_failed',{error:String(error&&error.message||error)},'error'));
      log('inspector_opened',{board_id:board});
    }
    /* Compteurs à la seconde : rendu local seulement, aucune requête. */
    let uiTimer=null;
    function resume(){
      if(!active())return;
      if(!uiTimer)uiTimer=setInterval(render,1000);
      startLoop();
    }
    function suspend(){
      if(uiTimer){clearInterval(uiTimer);uiTimer=null}
      stopLoop();leaveFeed();
    }
    function open(options){
      if(S.open)return;
      /* Un seul panneau latéral : `#panel` (closePanel nous ferme aussi : sans effet ici) et l'inspecteur du Studio. */
      try{if(typeof root.closePanel==='function')root.closePanel()}catch(error){log('close_panel_failed',{error:String(error)},'warn')}
      try{const insp=root.JarvisStudioInspector&&root.JarvisStudioInspector.instance;if(insp&&typeof insp.close==='function')insp.close()}
      catch(error){log('close_inspector_failed',{error:String(error)},'warn')}
      /* Sous 900 px la bande du Chat et celle des présentations ne tiennent pas côte à côte : le rail se replie (au-dessus, il reste à gauche du Chat). */
      try{const rail=root.JarvisPresentationRail;if(rail&&typeof rail.closeIfNarrow==='function')rail.closeIfNarrow()}catch(error){log('close_rail_failed',{error:String(error)},'warn')}
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
      el.input.addEventListener('input',draftEdited);
      /* Joindre : bouton accessible → `input type=file multiple` caché ; dépôt sur le panneau seulement. */
      el.attach.addEventListener('click',()=>{
        if(el.attach.getAttribute('aria-disabled')==='true'){
          say(S.sending?'Envoi du message en cours : joignez le fichier juste après.':'Aucune conversation liée : impossible de joindre un fichier.');return;
        }
        el.file.click();
      });
      el.file.addEventListener('change',()=>{attachFiles(el.file.files,'button');el.file.value=''});
      const hasFiles=event=>{const types=event.dataTransfer&&event.dataTransfer.types;return !!types&&[...types].includes('Files')};
      const showDrop=on=>{el.drop.hidden=!on;el.panel.classList.toggle('dropping',on)};
      el.panel.addEventListener('dragenter',event=>{if(!hasFiles(event))return;event.preventDefault();showDrop(true)});
      el.panel.addEventListener('dragover',event=>{
        if(!hasFiles(event))return;
        event.preventDefault();event.dataTransfer.dropEffect=model.conversationId&&!S.sending?'copy':'none';showDrop(true);
      });
      el.panel.addEventListener('dragleave',event=>{if(!el.panel.contains(event.relatedTarget))showDrop(false)});
      el.panel.addEventListener('drop',event=>{
        if(!hasFiles(event))return;
        event.preventDefault();showDrop(false);attachFiles(event.dataTransfer.files,'drop');
      });
      /* Ailleurs dans la page : un fichier déposé ne fait RIEN, et le navigateur ne l'ouvre jamais à la place
         de la page. Un futur dépôt (Board, Slice 08) qui appelle `preventDefault` d'abord garde la main. */
      doc.addEventListener('dragover',event=>{
        if(!hasFiles(event)||event.defaultPrevented)return;
        event.preventDefault();event.dataTransfer.dropEffect='none';
      });
      doc.addEventListener('drop',event=>{
        if(!hasFiles(event)||event.defaultPrevented)return;
        event.preventDefault();log('drop_ignored',{files:event.dataTransfer.files.length});
      });
      el.panel.addEventListener('keydown',event=>{
        if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close({restoreFocus:true})}
      });
      doc.addEventListener('visibilitychange',()=>{if(!S.open)return;if(visible()){log('resumed',{});resume()}else{log('suspended',{});suspend()}});
      /* Reprise : panneau rouvert au rechargement, après la fin du `<script>` de la page (closePanel et ses voisins initialisés). */
      if(store('get',STORAGE.open)==='1')setTimeout(()=>open({noFocus:true}),0);
      log('installed',{panel:DOM.panel,shared:canShare()});
    }

    return {install,open,close,attachExisting,toggle:()=>S.open?close({restoreFocus:true}):open(),isOpen:()=>S.open,
      snapshot:()=>({open:S.open,conversation_id:model.conversationId,cursor:S.feed.cursor,feed:{phase:S.feed.phase,role:S.feed.role,
        hydrated:S.feed.hydrated,error:S.feed.error,leading:S.feed.leading,heldRows:Model.storedRows(model).length},
        attachments:Model.attachmentView(S.att,model.conversationId),sentNames:[...S.sentNames.keys()],state:S.state,serverLock:S.serverLock,switch:{...S.switch},sending:S.sending,
        sendError:S.sendError,draft:S.draft?{id:S.draft.id}:null,pending:[...S.sent.keys()],stats:{...S.stats},view:composerView(S),
        items:Model.items(model)})};
  }

  const api={DOM,ROUTES,DEFAULTS,config,MAX_TEXT,composerView,uuid4,createChat,instance:null,
    open:o=>api.instance&&api.instance.open(o),close:o=>api.instance&&api.instance.close(o),
    /* Slice 05 (orbital-ui) : joindre un Artifact déjà chez Core ; `{ok:false, code:'chat_unavailable'}` sans panneau. */
    attachExisting:spec=>api.instance?api.instance.attachExisting(spec):{ok:false,code:'chat_unavailable'},
    isOpen:()=>!!(api.instance&&api.instance.isOpen())};
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(doc&&typeof root.fetch==='function'&&doc.getElementById('chatPanel')){
    try{api.instance=createChat();api.instance.install()}
    catch(error){log('install_failed',{error:String(error&&error.message||error)},'error')}
  }
  if(root)root.JarvisChat=api;
})(typeof window!=='undefined'?window:globalThis);
