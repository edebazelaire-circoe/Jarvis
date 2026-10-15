/* Harnais CDP pour `test_control_center_chat_browser.py` (handoff jarvis-unified-chat-and-board-drop, Slice 06).

   Chrome sans tête, la page SERVIE (composée comme `ControlCenter.index`), et
   un `fetch` double posé avant tout script : `/api/status` (le vrai
   `refreshStatus` nourrit le contrôle Boards) et les quatre routes du Chat,
   avec un faux Core en mémoire (`window.__chat`) qui admet les tours, écrit
   les événements canoniques `user.transcript.accepted` /
   `brain.message.published` et suit le canal vocal. Le harnais pilote de vraies
   touches (`Input.dispatchKeyEvent`, `Input.insertText`) et de vrais clics, et
   relève rectangles, styles calculés, focus et appels réseau.

   Usage : node _chat_browser.mjs <page.html|http://…> <chrome.exe> <stepJSON> (URL http : vrai Control Center, aucun double)
   Étape : {width, height, reducedMotion?, setup?: js, extra?: module.mjs, actions: [...]}
   `extra` : module qui exporte `FAKE` (source JS posée après le faux Core, ex. le faux relais
   de pièces jointes `_chat_attachments_browser.mjs`, Slice 07b).
   Action : {eval}, {value, expr}, {key: 'Enter'|'Shift+Enter'|'Tab'|'Shift+Tab'|'Escape'|'Space'},
            {type: texte}, {click: sélecteur}, {wait: ms}, {until: js, ms}, {shot: chemin.png},
            {files: sélecteur d'input, paths} (DOM.setFileInputFiles), {drop: sélecteur, paths}
            (vrai glisser-déposer CDP `Input.dispatchDragEvent`), {chooserFiles: paths} (répond au
            sélecteur de fichiers natif intercepté ; `reads.choosers` compte ses ouvertures),
            {reload: true} (vrai `Page.reload` : les doubles reviennent, le localStorage reste),
            {viewport: [largeur, hauteur]}
   Sortie : {reads, console, errors}. */
import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

const [,,PAGE,CHROME,STEP]=process.argv;
const step=JSON.parse(STEP);
const EXTRA=step.extra?(await import(pathToFileURL(step.extra).href)).FAKE:'';

const FAKE=`(()=>{
  const ev=(seq,type,conv,corr,content,attrs)=>({sequence:seq,recorded_at:new Date(Date.UTC(2026,9,14,9,0,seq)).toISOString(),
    event:{schema_version:1,event_id:'cev-'+conv+'-'+seq,event_type:type,actor:type.startsWith('user')?'user':'brain',
      conversation_id:conv,producer:'fake',visibility:'public',occurred_at:new Date(Date.UTC(2026,9,14,9,0,seq)).toISOString(),
      started_at:null,ended_at:null,span_id:null,session_id:'voice-1',turn_id:null,correlation_id:corr,parent_event_id:null,
      task_id:null,work_id:null,speech_id:null,outcome_id:null,trace_ref:null,content,attributes:attrs}});
  const C=window.__chat={seq:0,rows:[],calls:[],turns:[],disables:[],turnPlan:null,disablePlan:'ack',replyMs:250,acceptMs:0,
    boards:{default:'Jarvis',board_b:'Projet Atlas'},
    state:{schema_version:1,jarvis_session_id:'jsess_1',board_id:'default',conversation_id:'conv-a',
      voice:{state:'background',epoch:'ep-1',revision:1,report_age_ms:300,request:null},chat_writable:true,locked_reason:null}};
  C.add=(type,conv,corr,content,attrs)=>{C.seq++;C.rows.push(ev(C.seq,type,conv,corr,content,attrs||{}));return C.seq};
  C.say=(conv,corr,text,status)=>C.add('brain.message.published',conv,corr,text,{kind:'turn_result',status:status||'completed'});
  C.user=(conv,corr,text)=>C.add('user.transcript.accepted',conv,corr,text,{source:'text',addressing:'addressed'});
  /* Fil de départ : voix et texte mélangés, une réponse multi-lignes, un contenu qui ressemble à du HTML. */
  C.user('conv-a','voice:1','Bonjour Jarvis');
  C.say('conv-a','voice:1','Bonjour. Que puis-je faire ?');
  C.user('conv-a','chat:00000000-0000-4000-8000-000000000001','Montre <b>gras</b> & <img src=x onerror=alert(1)>');
  C.say('conv-a','chat:00000000-0000-4000-8000-000000000001','Voici le plan :\\n1. Lire\\n2. Résumer');
  C.user('conv-b','voice:9','Ouvre le Board Atlas');
  C.say('conv-b','voice:9','Board Atlas ouvert.');
  C.lockVoice=(state,reason)=>{C.state.voice.state=state;C.state.chat_writable=false;C.state.locked_reason=reason};
  C.unlockVoice=()=>{C.state.voice.state='background';C.state.chat_writable=true;C.state.locked_reason=null};
  C.board=(id,conv)=>{C.state.board_id=id;C.state.conversation_id=conv};
  const json=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  const refuse=(status,code,extra)=>json(status,Object.assign({ok:false,code,error:code,core_status:status},extra||{}));
  const sleep=(ms,signal)=>new Promise((ok,ko)=>{const t=setTimeout(ok,ms);
    if(signal)signal.addEventListener('abort',()=>{clearTimeout(t);ko(new DOMException('aborted','AbortError'))},{once:true})});
  const admit=(body)=>{
    const corr='chat:'+body.client_request_id;
    const seen=C.rows.some(r=>r.event.correlation_id===corr&&r.event.event_type==='user.transcript.accepted')||C.admitted&&C.admitted.has(corr);
    if(seen)return {corr,duplicate:true};
    (C.admitted=C.admitted||new Set()).add(corr);
    const count=Array.isArray(body.attachments)?body.attachments.length:0;
    const write=()=>{C.add('user.transcript.accepted',body.conversation_id,corr,body.content,
        Object.assign({source:'text',addressing:'addressed'},count?{attachment_count:count}:{}));
      if(C.replyMs!==null)setTimeout(()=>C.say(body.conversation_id,corr,'Réponse : '+body.content),C.replyMs)};
    if(C.acceptMs)setTimeout(write,C.acceptMs);else write();
    return {corr,duplicate:false};
  };
  window.fetch=async(path,init)=>{
    const method=(init&&init.method)||'GET',url=new URL(path,'http://x'),signal=init&&init.signal;
    C.calls.push(method+' '+path);
    if(path==='/api/status')return json(200,{voice_state:'idle',voice_online:false,agent:{name:'claude',state:'running'},
      agent_cli:'claude',error_count:0,background:C.background||null,
      boards:{available:true,active:{board_id:C.state.board_id,title:C.boards[C.state.board_id]},jarvis_session_id:'jsess_1',
        bindings:[{board_id:C.state.board_id,lifecycle:'foreground',agent_cli:'claude',closed:false}],error:null}});
    if(url.pathname==='/api/boards'&&method==='GET')return json(200,{boards:Object.entries(C.boards).map(([board_id,title])=>
      ({board_id,title,status:'active'})),active_board_id:C.state.board_id});
    if(url.pathname==='/api/sessions/current')return json(200,{session:{jarvis_session_id:'jsess_1',
      started_at:new Date().toISOString(),visited_board_ids:['default']}});
    if(url.pathname==='/api/presentation-studio/presentations')return json(200,{presentations:[],problems:[]});
    if(url.pathname==='/api/chat/state')return C.stateError?refuse(503,C.stateError):json(200,JSON.parse(JSON.stringify(C.state)));
    if(url.pathname==='/api/conversations/events'){
      const q=url.searchParams,conv=q.get('conversation_id'),after=+q.get('after_sequence'),limit=+q.get('limit'),
        wait=+(q.get('wait_ms')||0);
      if(q.get('projection')!=='chat')return refuse(400,'invalid_request');
      const page=()=>C.rows.filter(r=>r.event.conversation_id===conv&&r.sequence>after).slice(0,limit);
      const end=Date.now()+Math.min(wait,1500);
      let rows=page();
      while(!rows.length&&Date.now()<end){await sleep(50,signal);rows=page()}
      const last=rows.length?rows[rows.length-1].sequence:Math.max(after,C.seq);
      return json(200,{schema_version:1,events:rows,next_cursor:last,has_more:false,skipped_rows:0});
    }
    if(url.pathname==='/api/chat/turns'){
      const body=JSON.parse(init.body);C.turns.push(body);
      const plan=C.turnPlan;
      if(plan==='slow')await sleep(700);
      if(plan==='locked'){C.lockVoice('active','voice_active');return refuse(409,'chat_input_locked',{reason:'voice_active'})}
      if(plan==='not_foreground'){C.board('board_b','conv-b');C.turnPlan=null;
        return refuse(409,'chat_conversation_not_foreground',{current_conversation_id:'conv-b'})}
      const r=admit(body);
      if(plan==='timeout_once'){C.turnPlan=null;return refuse(504,'core_timeout')}
      return json(r.duplicate?200:202,{ok:true,correlation_id:r.corr,turn_id:'brain-turn-'+r.corr,duplicate:r.duplicate});
    }
    if(url.pathname==='/api/chat/voice/disable'){
      const body=JSON.parse(init.body);C.disables.push(body);
      const id='vcr-'+C.disables.length;
      C.state.voice.state='switching';C.state.locked_reason='voice_switching';
      C.state.voice.request={request_id:id,status:'pending',code:null};
      setTimeout(()=>{
        if(C.disablePlan==='ack'){C.unlockVoice();C.state.voice.request={request_id:id,status:'accepted',code:null}}
        else{C.lockVoice('active','voice_active');C.state.voice.request={request_id:id,status:'failed',code:'voice_disable_failed'}}
      },700);
      return json(202,{request_id:id,state:'switching',status:'pending'});
    }
    return json(404,{ok:false,code:'http_error',error:'not stubbed'});
  };
  /* Stockage vidé au PREMIER document de l'onglet seulement : un {reload} garde le brouillon (sessionStorage survit). */
  try{if(!sessionStorage.getItem('__chatTab')){localStorage.clear();sessionStorage.setItem('__chatTab','1')}}catch(_){}
  return 'ok';
})()`;

const READ=`(()=>{
  const q=s=>document.querySelector(s);
  const box=el=>{if(!el)return null;const r=el.getBoundingClientRect();if(!r.width&&!r.height)return null;
    return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height,z:getComputedStyle(el).zIndex}};
  const tab=q('#chatTab'),panel=q('#chatPanel'),input=q('#chatInput'),lock=q('#chatLock'),sw=q('#chatSwitch');
  const hit=el=>{const r=el&&el.getBoundingClientRect();if(!r||!r.width)return null;
    const h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!(h&&el.contains(h))};
  const snap=window.JarvisChat&&window.JarvisChat.instance?window.JarvisChat.instance.snapshot():null;
  return {
    tab:box(tab),panel:box(panel),dock:box(q('.dock')),toasts:box(q('#toasts')),sidePanel:box(q('#panel.open')),
    input:box(input),send:box(q('#chatSend')),head:box(q('#chatPanel header')),close:box(q('#chatClose')),
    pills:box(q('#bgPills:not([hidden])')),agt:box(q('#agentsButton')),toast:box(q('#toasts .toast')),
    voicehint:getComputedStyle(q('#voiceHint')).visibility,closeHit:hit(q('#chatClose')),boardsPanel:box(q('#boardsPanel')),inspector:box(q('#jvStudioInspector')),
    tabHit:hit(tab),inputHit:hit(input),
    open:panel.classList.contains('open')&&!panel.hidden,sideOpen:q('#panel').classList.contains('open'),
    expanded:tab.getAttribute('aria-expanded'),
    bubbles:[...document.querySelectorAll('#chatLog .chat-msg')].map(li=>({role:li.classList.contains('user')?'user':'brain',
      text:li.childNodes[1]?li.childNodes[1].textContent:'',who:li.querySelector('.chat-who').textContent,
      elements:li.querySelectorAll('*').length})),
    notes:[...document.querySelectorAll('#chatLog .chat-note,#chatLog .chat-turnfail,#chatLog .chat-empty')].map(li=>li.className+'|'+li.textContent),
    feed:q('#chatFeedText').textContent,sub:q('#chatSub').textContent,
    lock:{hidden:lock.hidden,text:q('#chatLockText').textContent,tone:lock.dataset.tone||null,
      switchHidden:sw.hidden,switchText:sw.textContent},
    composer:{ariaDisabled:input.getAttribute('aria-disabled'),readOnly:input.readOnly,disabled:input.disabled,value:input.value,
      sendDisabled:q('#chatSend').getAttribute('aria-disabled'),sendText:q('#chatSend').textContent},
    files:[...document.querySelectorAll('#chatFiles .chat-file')].map(li=>({status:li.dataset.status,
      name:li.querySelector('.chat-file-name').textContent,meta:li.querySelector('.chat-file-meta').textContent,
      state:li.querySelector('.chat-file-text').textContent,time:li.querySelector('.chat-file-time').textContent,
      act:li.querySelector('.chat-file-act').hidden?null:li.querySelector('.chat-file-act').textContent})),
    attNote:q('#chatAttNote').hidden?null:q('#chatAttNote').textContent,attach:{ariaDisabled:q('#chatAttach').getAttribute('aria-disabled'),box:box(q('#chatAttach'))},
    drop:!q('#chatDrop').hidden,
    attLines:[...document.querySelectorAll('#chatLog .chat-msg .chat-att')].map(n=>n.textContent),
    sendStatus:{hidden:q('#chatSendStatus').hidden,text:q('#chatSendText').textContent,retryHidden:q('#chatRetry').hidden},
    active:document.activeElement&&(document.activeElement.id||document.activeElement.className||document.activeElement.tagName),
    motion:{panel:getComputedStyle(panel).animationName,dots:(()=>{const d=q('#chatLog .chat-dots i');return d?getComputedStyle(d).animationName:null})()},
    scrollWidth:document.documentElement.scrollWidth,viewport:{w:innerWidth,h:innerHeight},
    fake:window.__chat?{calls:window.__chat.calls.slice(),turns:window.__chat.turns.slice(),disables:window.__chat.disables.slice()}:null,
    snap};
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-chat-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu',
  '--disable-extensions','--allow-file-access-from-files','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[],errors=[],choosers=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
      if(text.startsWith('[chat]')||msg.params.type==='error')consoleLines.push(msg.params.type+' '+text);
    }else if(msg.method==='Page.fileChooserOpened'){
      choosers.push(msg.params);
    }else if(msg.method==='Runtime.exceptionThrown'){
      errors.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}));
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const KEYS={Enter:{code:'Enter',keyCode:13,text:'\r'},Tab:{code:'Tab',keyCode:9},Escape:{code:'Escape',keyCode:27},
    Space:{code:'Space',keyCode:32,text:' ',key:' '}};
  const press=async combo=>{
    const shift=combo.startsWith('Shift+'),key=shift?combo.slice(6):combo,k=KEYS[key];
    if(!k)throw new Error('touche inconnue '+combo);
    const modifiers=shift?8:0;
    const name=k.key||key;
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:name,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,text:k.text,modifiers});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:name,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,modifiers});
  };
  const click=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;const r=el.getBoundingClientRect();return r.width?{x:r.left+r.width/2,y:r.top+r.height/2}:null})()`);
    if(!at)throw new Error('clic : introuvable ou caché '+selector);
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])
      await send('Input.dispatchMouseEvent',{type,x:at.x,y:at.y,button:'left',clickCount:1});
  };

  const centre=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;const r=el.getBoundingClientRect();return r.width?{x:r.left+r.width/2,y:r.top+r.height/2}:null})()`);
    if(!at)throw new Error('cible introuvable ou cachée '+selector);
    return at;
  };
  await send('Page.enable');await send('Runtime.enable');await send('DOM.enable');
  await send('Page.setInterceptFileChooserDialog',{enabled:true});
  /* Une URL http = la page d'un VRAI Control Center, sans aucun double (preuve sur pile isolée). */
  const REAL=/^https?:/.test(PAGE);
  await send('Page.addScriptToEvaluateOnNewDocument',{source:REAL?(step.setup||'1'):FAKE+(EXTRA?';'+EXTRA:'')+(step.setup?';'+step.setup:'')});
  await send('Emulation.setEmulatedMedia',{features:step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]});
  await send('Emulation.setDeviceMetricsOverride',{width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
  const settled=async()=>{
    for(let i=0;i<200;i+=1){
      await sleep(50);
      if(await evaluate(`document.readyState==='complete'&&!!(window.JarvisChat&&window.JarvisChat.instance)`).catch(()=>false))break;
    }
    await sleep(1200);
  };
  await send('Page.navigate',{url:REAL?PAGE:'file:///'+PAGE.replace(/\\/g,'/')});
  await settled();
  const reads={};
  for(const action of step.actions){
    try{
      if(action.eval!==undefined)await evaluate(action.eval);
      else if(action.value!==undefined)reads[action.value]=await evaluate(action.expr||READ);
      else if(action.key!==undefined)await press(action.key);
      else if(action.type!==undefined)await send('Input.insertText',{text:action.type});
      else if(action.click!==undefined)await click(action.click);
      else if(action.files!==undefined){
        const {root}=await send('DOM.getDocument',{depth:0});
        const {nodeId}=await send('DOM.querySelector',{nodeId:root.nodeId,selector:action.files});
        if(!nodeId)throw new Error('input introuvable '+action.files);
        await send('DOM.setFileInputFiles',{nodeId,files:action.paths});
      }else if(action.drop!==undefined){
        const at=await centre(action.drop),data={items:[],files:action.paths,dragOperationsMask:1};
        for(const type of ['dragEnter','dragOver','drop'])
          await send('Input.dispatchDragEvent',{type,x:at.x,y:at.y,data,modifiers:0});
      }else if(action.chooserFiles!==undefined){
        const last=choosers[choosers.length-1];
        if(!last)throw new Error('aucun sélecteur de fichiers ouvert');
        await send('DOM.setFileInputFiles',{backendNodeId:last.backendNodeId,files:action.chooserFiles});
      }
      else if(action.reload!==undefined){await send('Page.reload',{ignoreCache:true});await sleep(100);await settled()}
      else if(action.viewport!==undefined)await send('Emulation.setDeviceMetricsOverride',{width:action.viewport[0],height:action.viewport[1],deviceScaleFactor:1,mobile:false});
      else if(action.wait!==undefined)await sleep(action.wait);
      else if(action.until!==undefined){
        const end=Date.now()+(action.ms||5000);let ok=false;
        while(Date.now()<end){ok=!!(await evaluate(action.until));if(ok)break;await sleep(50)}
        reads['until:'+(action.name||action.until)]=ok;
      }else if(action.shot!==undefined){
        const shot=await send('Page.captureScreenshot',{format:'png'});
        writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
      }
    }catch(error){reads.failed={action,error:String(error.message||error).slice(0,400)};break}
  }
  reads.choosers=choosers.length;
  ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines,errors}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  killTree(chrome);
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* Windows tient le dossier */}
}

function killTree(child){
  if(process.platform==='win32'&&child.pid){
    try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore'});return}
    catch(_){/* deja sorti */}
  }
  child.kill();
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{
      const list=await (await fetch(url)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n ecoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
