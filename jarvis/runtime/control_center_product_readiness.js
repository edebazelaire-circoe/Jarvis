/* Préparation de JARVIS et premier lancement, côté page (jarvis-presentation-edition-v1, Slice 07).

   Contrat : `docs/product-install.md` › *Onboarding UI* ; données : `GET /api/product/readiness`
   (`jarvis/runtime/product_readiness.py`, texte écrit par `jarvis/domain/product_readiness.py`). Ce module ne décide
   rien : il montre le rapport du serveur, lance les actions NOMMÉES qu'il propose, et le relit.

   - **Quand il s'ouvre** : au chargement d'une page d'édition produit (`<html data-product-edition>` différent de
     `full`) si le premier lancement n'est pas fait OU si une ligne indispensable n'est plus prête ; sur demande
     (`open()`, l'accueil des présentations, `#preparation`). « Plus tard » le ferme pour cette page.
   - **Ce qu'il montre** : trois groupes (Indispensable, Comptes et services, Ce poste), une ligne par fait, son état
     en mots et en pictogramme, une phrase, ses actions, ses détails (la cause exacte, repliée). Une barre dit combien
     d'indispensables sont prêts.
   - **Rien ne reste muet** (RULE ZERO) : une action en cours montre son libellé, un compteur de secondes et une
     échéance (`ACTION_DEADLINE_MS`) ; une relecture en cours le dit ; un échec dit sa cause et son code, à l'écran
     ET au journal (`[readiness] readiness.<clé>`, `obsClientLog` quand la page en a un) ; chaque bouton est rendu
     dans un `finally`. Tant qu'une ligne est « En cours », le rapport est relu toutes les `POLL_MS`.
   - **Commencer** (actif quand tout l'indispensable est prêt) : `POST /api/product/onboarding/complete` → Board
     Présentation actif, jamais Assistant.

   Bloc pur (`parse`, `progressOf`, `headlineOf`, `shouldOpen`, `homeLineOf`, `elapsed`) exécuté par node dans
   `tests/unit/test_product_readiness_js.py` ; bloc navigateur éprouvé par
   `tests/unit/test_product_readiness_browser.py`. */
(function(root){
  'use strict';

  const ROUTE='/api/product/readiness';
  const ACTION_ROUTE='/api/product/readiness/actions/';
  const COMPLETE_ROUTE='/api/product/onboarding/complete';
  const QUIT_ROUTE='/api/product/quit';
  const READ_DEADLINE_MS=15000;
  const ACTION_DEADLINE_MS=45000;
  const POLL_MS=3000;
  const HOST_ID='jvReadiness';
  const STATES=Object.freeze(['ready','action_needed','in_progress','optional','unavailable']);

  /* Action nommée du serveur → ligne qu'elle fait avancer (secondes « En cours depuis »). */
  const RUNNING_KEYS=Object.freeze({render:/^render_/,runtimes:/^verify_installation$/,brain:/^brain_sign_in$/});

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
  const text=v=>v===undefined||v===null?'':String(v);

  /* ------------------------------------------------ logique pure */

  /* Charge du serveur → rapport, ou `{ok:false, code}`. Une ligne mal formée rend tout le rapport illisible : la page ne
     devine jamais un état. */
  function parse(payload){
    if(!isObject(payload)||payload.schema!=='jarvis.product-readiness'||!Array.isArray(payload.items))
      return {ok:false,code:'readiness_payload_invalid'};
    const items=[];
    for(const row of payload.items){
      if(!isObject(row)||typeof row.item_id!=='string'||!STATES.includes(row.state)||!Array.isArray(row.actions))
        return {ok:false,code:'readiness_payload_invalid'};
      items.push(Object.freeze({id:row.item_id,group:text(row.group),label:text(row.label),required:row.required===true,
        state:row.state,stateLabel:text(row.state_label),summary:text(row.summary),detail:row.detail?text(row.detail):'',
        actions:Object.freeze(row.actions.filter(isObject).map(a=>Object.freeze({id:text(a.action_id),label:text(a.label),
          kind:text(a.kind),primary:a.primary!==false})))}));
    }
    const groups=Array.isArray(payload.groups)?payload.groups.filter(isObject).map(g=>Object.freeze({id:text(g.group),label:text(g.label)})):[];
    const onboarding=isObject(payload.onboarding)?payload.onboarding:{};
    const launcher=isObject(payload.launcher)?payload.launcher:{};
    return {ok:true,report:Object.freeze({ready:payload.ready===true,items:Object.freeze(items),groups:Object.freeze(groups),
      edition:text(payload.edition),installed:payload.installed===true,checkedAt:text(payload.checked_at),
      running:Object.freeze(isObject(payload.running_elapsed_s)?{...payload.running_elapsed_s}:{}),
      onboarded:onboarding.completed===true,managed:launcher.managed===true})};
  }

  function progressOf(report){
    const required=(report&&report.items||[]).filter(i=>i.required);
    const done=required.filter(i=>i.state==='ready').length;
    return {done,total:required.length,remaining:required.length-done};
  }

  function headlineOf(report){
    if(!report)return {tone:'unknown',title:'Préparation de JARVIS',text:'Lecture de l’état de JARVIS…'};
    const p=progressOf(report);
    if(report.ready)return {tone:'ready',title:report.onboarded?'JARVIS est prêt':'Bienvenue dans JARVIS',
      text:report.onboarded?'Tout l’indispensable est en place.':'Tout l’indispensable est en place. Vous pouvez commencer votre première présentation.'};
    const busy=report.items.some(i=>i.required&&i.state==='in_progress');
    const left=p.remaining===1?'Encore 1 étape':`Encore ${p.remaining} étapes`;
    return {tone:busy?'working':'todo',title:report.onboarded?'JARVIS demande votre attention':'Bienvenue dans JARVIS',
      text:`${left} avant votre première présentation. Les comptes et services sont facultatifs : vous pourrez les relier plus tard.`};
  }

  /* Ouvrir au chargement ? Édition produit seulement ; premier lancement à faire, ou un indispensable n'est plus prêt. */
  function shouldOpen(report,pageEdition){
    if(!report||!pageEdition||pageEdition==='full')return false;
    return !report.onboarded||!report.ready;
  }

  /* Ligne de l'accueil des présentations (I-006 point 2) : ce qui reste, ou la liste des comptes reliés. */
  function homeLineOf(report){
    if(!report)return null;
    const p=progressOf(report);
    if(!report.ready)return {tone:'todo',text:p.remaining===1?'1 étape à terminer avant votre première vidéo.':
      `${p.remaining} étapes à terminer avant votre première vidéo.`,action:'Voir la préparation'};
    const services=report.items.filter(i=>i.group==='services'&&i.state!=='unavailable');
    const linked=services.filter(i=>i.state==='ready').length;
    return {tone:'ready',text:services.length?`JARVIS est prêt. Comptes reliés : ${linked} sur ${services.length}.`:'JARVIS est prêt.',
      action:'Préparation et comptes'};
  }

  function elapsed(seconds){
    const s=Math.max(0,Math.floor(Number(seconds)||0));
    return s<60?`${s} s`:`${Math.floor(s/60)} min ${String(s%60).padStart(2,'0')} s`;
  }

  const pure={ROUTE,ACTION_ROUTE,COMPLETE_ROUTE,READ_DEADLINE_MS,ACTION_DEADLINE_MS,POLL_MS,parse,progressOf,headlineOf,
    shouldOpen,homeLineOf,elapsed};

  /* ------------------------------------------------ page */

  const CSS=`
#${HOST_ID}{position:fixed;inset:0;z-index:62;display:grid;place-items:center;padding:24px;background:radial-gradient(110% 80% at 50% 0%,rgba(14,44,58,.42),transparent 62%),rgba(2,6,10,.72);backdrop-filter:blur(8px) saturate(.9);font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--text,#d8edf7)}
#${HOST_ID}[hidden]{display:none}
#${HOST_ID} .rd-card{width:min(760px,100%);max-height:calc(100vh - 48px);display:grid;grid-template-rows:auto minmax(0,1fr) auto;background:linear-gradient(180deg,rgba(9,19,27,.97),rgba(5,11,17,.97));border:1px solid var(--shell-stroke,rgba(174,205,220,.12));border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.55),0 2px 0 rgba(255,255,255,.03) inset;overflow:hidden;animation:rd-in 260ms cubic-bezier(.2,.7,.2,1)}
@keyframes rd-in{from{opacity:0;transform:translateY(10px) scale(.985);filter:blur(3px)}to{opacity:1;transform:none;filter:none}}
@media(prefers-reduced-motion:reduce){#${HOST_ID} .rd-card{animation:none}#${HOST_ID} .rd-spin{animation:none}}
#${HOST_ID} header{padding:22px 26px 16px;border-bottom:1px solid rgba(174,205,220,.08)}
#${HOST_ID} .rd-top{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}
#${HOST_ID} h2{margin:0;font-size:21px;line-height:1.25;font-weight:650;letter-spacing:-.01em;text-wrap:balance}
#${HOST_ID} .rd-lede{margin:6px 0 0;color:var(--muted,#7190a0);max-width:62ch}
#${HOST_ID} .rd-later{flex:none;padding:6px 12px;border:1px solid rgba(174,205,220,.18);border-radius:999px;background:none;color:var(--muted,#7190a0);font:inherit;font-size:12.5px;cursor:pointer}
#${HOST_ID} .rd-later:hover{color:var(--text,#d8edf7);border-color:rgba(174,205,220,.4)}
#${HOST_ID} .rd-meter{margin-top:16px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center}
#${HOST_ID} .rd-bar{height:6px;border-radius:999px;background:rgba(174,205,220,.1);overflow:hidden}
#${HOST_ID} .rd-bar>i{display:block;height:100%;width:100%;transform:scaleX(var(--p,0));transform-origin:0 50%;background:linear-gradient(90deg,var(--accent,#6ee7ff),var(--ok,#68e0a0));border-radius:inherit;transition:transform 420ms cubic-bezier(.2,.7,.2,1)}
#${HOST_ID} .rd-count{font-size:12px;color:var(--muted,#7190a0);font-variant-numeric:tabular-nums}
#${HOST_ID} .rd-body{overflow:auto;padding:6px 26px 18px;scrollbar-gutter:stable}
#${HOST_ID} h3{margin:20px 0 8px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted,#7190a0)}
#${HOST_ID} h3 small{font-weight:400;letter-spacing:0;text-transform:none;margin-left:8px;opacity:.8}
#${HOST_ID} ul{list-style:none;margin:0;padding:0;display:grid;gap:2px}
#${HOST_ID} li.rd-item{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:4px 12px;align-items:start;padding:12px 10px;border-radius:10px}
#${HOST_ID} li.rd-item[data-state=action_needed][data-required=true]{background:rgba(255,159,67,.06)}
#${HOST_ID} li.rd-item:hover{background:rgba(174,205,220,.04)}
#${HOST_ID} .rd-icon{width:20px;height:20px;margin-top:1px;color:var(--muted,#7190a0)}
#${HOST_ID} [data-state=ready] .rd-icon{color:var(--ok,#68e0a0)}
#${HOST_ID} [data-state=action_needed] .rd-icon{color:var(--sem-alert,#ff9f43)}
#${HOST_ID} [data-state=in_progress] .rd-icon{color:var(--sem-working,#4da3ff)}
#${HOST_ID} .rd-spin{animation:rd-turn 1.1s linear infinite;transform-origin:50% 50%}
@keyframes rd-turn{to{transform:rotate(360deg)}}
#${HOST_ID} .rd-label{font-weight:600}
#${HOST_ID} .rd-chip{justify-self:end;font-size:11.5px;padding:2px 9px;border-radius:999px;border:1px solid rgba(174,205,220,.16);color:var(--muted,#7190a0);white-space:nowrap}
#${HOST_ID} [data-state=ready] .rd-chip{border-color:rgba(104,224,160,.35);color:var(--ok,#68e0a0)}
#${HOST_ID} [data-state=action_needed] .rd-chip{border-color:rgba(255,159,67,.4);color:var(--sem-alert,#ff9f43)}
#${HOST_ID} [data-state=in_progress] .rd-chip{border-color:rgba(77,163,255,.45);color:var(--sem-working,#4da3ff)}
#${HOST_ID} .rd-summary{grid-column:2/4;margin:0;color:#b7cfdb;max-width:70ch}
#${HOST_ID} .rd-actions{grid-column:2/4;display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
#${HOST_ID} .rd-actions:empty{display:none}
#${HOST_ID} button.rd-act{padding:6px 13px;border-radius:8px;border:1px solid rgba(174,205,220,.22);background:rgba(174,205,220,.05);color:var(--text,#d8edf7);font:inherit;font-size:12.5px;cursor:pointer}
#${HOST_ID} button.rd-act[data-primary=true]{border-color:color-mix(in srgb,var(--accent,#6ee7ff) 55%,transparent);background:color-mix(in srgb,var(--accent,#6ee7ff) 12%,transparent)}
#${HOST_ID} button.rd-act:hover{border-color:var(--accent,#6ee7ff)}
#${HOST_ID} button[aria-disabled=true]{opacity:.55;cursor:progress}
#${HOST_ID} button:focus-visible,#${HOST_ID} summary:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:var(--shell-focus-offset,2px)}
#${HOST_ID} .rd-said{grid-column:2/4;margin:4px 0 0;font-size:12.5px;color:var(--sem-working,#4da3ff)}
#${HOST_ID} .rd-said[data-kind=failed]{color:var(--danger,#ff6577)}
#${HOST_ID} .rd-said[data-kind=ok]{color:var(--ok,#68e0a0)}
#${HOST_ID} .rd-link{color:var(--accent,#6ee7ff);text-decoration:underline;text-underline-offset:3px}
#${HOST_ID} details{grid-column:2/4;margin-top:2px;font-size:12px;color:var(--muted,#7190a0)}
#${HOST_ID} summary{cursor:pointer;width:max-content}
#${HOST_ID} details code{display:block;margin-top:4px;white-space:pre-wrap;word-break:break-word;color:#9fb8c5}
#${HOST_ID} footer{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;justify-content:space-between;padding:14px 26px;border-top:1px solid rgba(174,205,220,.08);background:rgba(3,8,12,.6)}
#${HOST_ID} .rd-status{font-size:12.5px;color:var(--muted,#7190a0);min-height:1.5em}
#${HOST_ID} .rd-status[data-kind=failed]{color:var(--danger,#ff6577)}
#${HOST_ID} .rd-foot-actions{display:flex;gap:10px;align-items:center;margin-left:auto}
#${HOST_ID} .rd-quit{padding:6px 10px;border:0;background:none;color:var(--muted,#7190a0);font:inherit;font-size:12.5px;text-decoration:underline;text-underline-offset:3px;cursor:pointer}
#${HOST_ID} .rd-start{padding:9px 20px;border-radius:10px;border:1px solid color-mix(in srgb,var(--ok,#68e0a0) 60%,transparent);background:color-mix(in srgb,var(--ok,#68e0a0) 16%,transparent);color:var(--text,#d8edf7);font:inherit;font-weight:600;cursor:pointer}
#${HOST_ID} .rd-start[aria-disabled=true]{border-color:rgba(174,205,220,.18);background:none;color:var(--muted,#7190a0);cursor:not-allowed}
@media(max-width:600px){#${HOST_ID}{padding:10px}#${HOST_ID} header,#${HOST_ID} .rd-body,#${HOST_ID} footer{padding-left:16px;padding-right:16px}#${HOST_ID} li.rd-item{grid-template-columns:22px minmax(0,1fr)}#${HOST_ID} .rd-chip{grid-column:2;justify-self:start}}
@media(forced-colors:active){#${HOST_ID} .rd-card{border-color:CanvasText}#${HOST_ID} button{border-color:ButtonText}}
#presentationRail .jvr-ready{margin:4px 4px 10px;padding:10px 12px;border-radius:10px;border:1px solid rgba(174,205,220,.12);background:rgba(174,205,220,.04);display:grid;gap:6px}
#presentationRail .jvr-ready[data-tone=todo]{border-color:rgba(255,159,67,.35);background:rgba(255,159,67,.06)}
#presentationRail .jvr-ready-text{margin:0;font-size:11.5px;line-height:1.45;color:var(--text,#d8edf7)}
#presentationRail .jvr-ready-open{justify-self:start;padding:3px 10px;border:1px solid rgba(174,205,220,.22);border-radius:999px;background:none;color:var(--text,#d8edf7);font:inherit;font-size:11.5px;cursor:pointer}
#presentationRail .jvr-ready-open:hover{border-color:var(--accent,#6ee7ff)}
#presentationRail .jvr-ready-open:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:var(--shell-focus-offset,2px)}
`;

  const ICONS=Object.freeze({
    ready:[['circle',{cx:'12',cy:'12',r:'9'}],['path',{d:'M8 12.5l2.6 2.6L16 9.5'}]],
    action_needed:[['circle',{cx:'12',cy:'12',r:'9'}],['path',{d:'M12 7.5v5.5'}],['path',{d:'M12 16.3v.2'}]],
    in_progress:[['path',{d:'M12 3a9 9 0 1 0 9 9',class:'rd-spin'}]],
    optional:[['circle',{cx:'12',cy:'12',r:'9','stroke-dasharray':'2.5 3'}]],
    unavailable:[['circle',{cx:'12',cy:'12',r:'9'}],['path',{d:'M8 12h8'}]],
  });

  function createView(deps){
    const d=deps||{};
    const doc=d.document,win=d.window||root;
    const fetchImpl=d.fetch;
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms)),cancel=d.clearTimeout||(id=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms)),stopEvery=d.clearInterval||(id=>clearInterval(id));
    const now=d.now||(()=>Date.now());
    const sink=d.console||null;
    /* Ouvrir une adresse : rend la fenêtre, ou `null` si le navigateur l'a bloquée (sans `noopener`, qui rendrait
       toujours `null` : l'opener est coupé à la main). */
    const openUrl=d.openUrl||(url=>{const w=win.open(url,'_blank');if(w){try{w.opener=null}catch(_e){/* intentional: cross-origin already */}}return w});
    /* Revue m4 : une fenêtre ouverte APRÈS un `await` peut être bloquée (activation de l'utilisateur expirée). Une action
       qui ouvre une page réserve donc sa fenêtre AU CLIC, puis la dirige ; bloquée quand même, la ligne donne un lien. */
    const preOpen=d.preOpen||(d.openUrl?null:(()=>{try{const w=win.open('about:blank','_blank');if(w){try{w.opener=null}catch(_e){/* intentional */}}return w}catch(_e){return null}}));
    const navigate=d.navigate||(target=>{if(target==='connections'&&typeof win.openSettingsTab==='function')win.openSettingsTab('connections')});
    const notify=d.toast||null;
    const S={report:null,error:null,loading:null,open:false,dismissed:false,busy:null,said:{},status:null,poll:0,tick:0,
      starting:false,quitting:false,returnFocus:null,lastRead:0};
    const listeners=new Set();
    let host=null,ui=null;
    if(doc)ensureStyleSoon();
    function ensureStyleSoon(){try{ensureStyle()}catch(error){log('error','style_failed',{error:text(error&&error.message)})}}

    function log(level,key,data){
      const line=`[readiness] readiness.${key} ${JSON.stringify(data||{})}`;
      try{if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}}
      catch(_e){/* intentional: a broken console must not break the page */}
      try{const obs=d.obsClientLog||win.obsClientLog;if(level!=='info'&&typeof obs==='function')obs(level,level==='error'?'ERROR':'WARN',`readiness_${key}`,data||{})}
      catch(_e){/* intentional: the journal is optional on this page */}
    }

    /* Requête bornée : la réponse ET son corps tiennent dans l'échéance ; un refus rend `{code, message}` du serveur. */
    async function call(method,path,deadline){
      let timer=0;
      const controller=typeof win.AbortController==='function'?new win.AbortController():null;
      const expiry=new Promise((_,reject)=>{timer=later(()=>{if(controller)controller.abort();
        reject(Object.assign(new Error(`pas de réponse après ${Math.round(deadline/1000)} s`),{code:'timeout'}))},deadline)});
      const read=(async()=>{
        if(!fetchImpl)throw Object.assign(new Error('la porte réseau de la page manque'),{code:'network'});
        const init={method,cache:'no-store',signal:controller?controller.signal:undefined};
        if(method==='POST'){init.headers={'Content-Type':'application/json'};init.body='{}'}
        const response=await fetchImpl(path,init);
        let body=null;try{body=await response.json()}catch(_e){body=null /* intentional: reported as unreadable below */}
        if(!response.ok){
          const e=isObject(body)&&isObject(body.error)?body.error:{};
          throw Object.assign(new Error(text(e.message)||`HTTP ${response.status}`),{code:text(e.code)||`http_${response.status}`,detail:text(e.detail)});
        }
        return body;
      })();
      expiry.catch(()=>{/* intentional: the race reports it */});read.catch(()=>{/* intentional: the race reports it */});
      try{return await Promise.race([read,expiry])}finally{if(timer)cancel(timer)}
    }

    function emit(){for(const fn of [...listeners]){try{fn(S.report)}catch(error){log('error','listener_failed',{error:text(error&&error.message)})}}}

    function accept(payload){
      const parsed=parse(payload);
      if(!parsed.ok)throw Object.assign(new Error('rapport illisible'),{code:parsed.code});
      S.report=parsed.report;S.error=null;S.lastRead=now();
      /* Une consigne d'action ne survit pas au changement de sa ligne (QA runtime m1 : « Moteur de rendu : installing »
         restait affiché sous une ligne déjà « Prêt »). Un échec reste jusqu'à la prochaine action. */
      for(const id of Object.keys(S.said)){
        const said=S.said[id],item=parsed.report.items.find(i=>i.id===id);
        if(!said||!item)continue;
        if(item.state==='ready'||(said.kind!=='failed'&&said.state&&said.state!==item.state))S.said[id]=null;
      }
      return parsed.report;
    }

    async function refresh(force){
      if(S.loading)return S.loading;
      S.loading=(async()=>{
        try{
          accept(await call('GET',ROUTE+(force?'?force=1':''),READ_DEADLINE_MS));
          log('info','read',{ready:S.report.ready,onboarded:S.report.onboarded,blocking:S.report.items.filter(i=>i.required&&i.state!=='ready').map(i=>i.id)});
        }catch(error){
          S.error={code:text(error&&error.code)||'network',message:text(error&&error.message)};
          log('warn','read_failed',S.error);
        }finally{
          S.loading=null;render();emit();schedulePoll();
        }
        return S.report;
      })();
      render();
      return S.loading;
    }

    function schedulePoll(){
      if(S.poll){cancel(S.poll);S.poll=0}
      const busy=S.report&&S.report.items.some(i=>i.state==='in_progress');
      if(S.open&&(busy||S.error))S.poll=later(()=>{S.poll=0;refresh(false)},POLL_MS);
    }

    async function act(item,action,button){
      if(S.busy)return;
      S.busy={item:item.id,action:action.id,since:now(),label:action.label};
      S.said[item.id]=null;render();
      /* Fenêtre réservée au clic (activation de l'utilisateur encore valable), dirigée quand l'adresse arrive. */
      let reserved=action.kind==='open'&&preOpen?preOpen():null;
      try{
        const outcome=await call('POST',ACTION_ROUTE+encodeURIComponent(action.id),ACTION_DEADLINE_MS);
        if(outcome&&outcome.report)accept(outcome.report);
        const status=text(outcome&&outcome.status);
        let blocked=null;
        if(status==='open'&&outcome.url){
          const url=text(outcome.url);
          let shown=null;
          if(reserved&&!reserved.closed){try{reserved.location.href=url;shown=reserved;reserved=null}catch(_e){shown=null}}
          if(!shown)shown=openUrl(url);
          if(!shown){blocked=url;log('warn','open_blocked',{action:action.id})}
        }
        if(status==='navigate'){close('navigate');navigate(text(outcome.target));}
        /* La ligne est déjà prête dans le rapport rendu : sa phrase dit tout, une consigne « en cours » serait périmée. */
        const after=S.report&&S.report.items.find(i=>i.id===item.id);
        S.said[item.id]=blocked?{kind:'info',state:after&&after.state,url:blocked,
            text:`${text(outcome&&outcome.message)} Votre navigateur a bloqué l’ouverture de la page : ouvrez-la avec ce lien.`}
          :after&&after.state==='ready'&&status!=='open'?null
          :{kind:status==='done'?'ok':'info',state:after&&after.state,text:text(outcome&&outcome.message)};
        log('info','action_done',{action:action.id,status});
      }catch(error){
        const code=text(error&&error.code)||'network';
        /* La phrase du serveur (mots de produit) dans la ligne ; le code et la cause technique sous « Détails » (revue m3). */
        S.said[item.id]={kind:'failed',text:text(error&&error.message)||'L’action n’a pas abouti.',
          detail:[code,text(error&&error.detail)].filter(Boolean).join(' : ')};
        log('error','action_failed',{action:action.id,code,message:text(error&&error.message),detail:text(error&&error.detail)});
      }finally{
        if(reserved){try{reserved.close()}catch(_e){/* intentional: the reserved window is already gone */}}
        S.busy=null;render();schedulePoll();
        if(button&&button.isConnected)button.focus({preventScroll:true});
      }
    }

    async function start(){
      if(S.starting||!S.report||!S.report.ready)return;
      S.starting=true;S.status={kind:'info',text:'Ouverture de votre Board Présentation…'};render();
      try{
        const answer=await call('POST',COMPLETE_ROUTE,ACTION_DEADLINE_MS);
        const board=answer&&answer.board||{};
        log('info','onboarding_completed',{board_kind:text(board.board_kind)});
        close('started');
        if(notify)notify({title:'JARVIS est prêt',sub:`Board « ${text(board.title)||'Présentations'} » ouvert. Créez votre première présentation à droite.`,kind:'ok'});
        await refresh(false);
      }catch(error){
        const code=text(error&&error.code)||'network';
        S.status={kind:'failed',text:`Le Board Présentation n’a pas pu s’ouvrir : ${text(error&&error.message)}`};
        log('error','onboarding_failed',{code,message:text(error&&error.message)});
      }finally{S.starting=false;render()}
    }

    async function quit(){
      if(S.quitting)return;
      S.quitting=true;S.status={kind:'info',text:'Arrêt de JARVIS demandé…'};render();
      try{await call('POST',QUIT_ROUTE,ACTION_DEADLINE_MS);S.status={kind:'info',text:'JARVIS s’arrête. Vous pouvez fermer cet onglet.'};log('info','quit_requested',{})}
      catch(error){S.status={kind:'failed',text:`Arrêt impossible : ${text(error&&error.message)}`};log('error','quit_failed',{code:text(error&&error.code),detail:text(error&&error.detail)})}
      finally{S.quitting=false;render()}
    }

    /* ---------------- rendu */

    function el(tag,cls,content){const n=doc.createElement(tag);if(cls)n.className=cls;if(content!==undefined)n.textContent=content;return n}
    function icon(state){
      const ns='http://www.w3.org/2000/svg',svg=doc.createElementNS(ns,'svg');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
      svg.setAttribute('stroke-width','1.8');svg.setAttribute('stroke-linecap','round');svg.setAttribute('class','rd-icon');
      svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
      for(const [tag,attrs] of ICONS[state]||ICONS.unavailable){const n=doc.createElementNS(ns,tag);for(const k of Object.keys(attrs))n.setAttribute(k,attrs[k]);svg.appendChild(n)}
      return svg;
    }
    function ensureStyle(){
      if(!doc||!doc.head||doc.getElementById('jvReadinessStyle'))return;
      const style=el('style');style.id='jvReadinessStyle';style.textContent=CSS;doc.head.appendChild(style);
    }
    function install(){
      if(host)return;
      ensureStyle();
      host=el('div');host.id=HOST_ID;host.hidden=true;host.setAttribute('role','dialog');host.setAttribute('aria-modal','true');
      host.setAttribute('aria-labelledby','jvReadinessTitle');host.setAttribute('aria-describedby','jvReadinessLede');
      const card=el('section','rd-card');
      const header=el('header');const top=el('div','rd-top');
      const titles=el('div');const title=el('h2');title.id='jvReadinessTitle';const lede=el('p','rd-lede');lede.id='jvReadinessLede';
      titles.append(title,lede);
      const later_=el('button','rd-later','Plus tard');later_.type='button';later_.addEventListener('click',()=>close('later'));
      top.append(titles,later_);
      const meter=el('div','rd-meter');const bar=el('div','rd-bar');bar.setAttribute('role','progressbar');bar.setAttribute('aria-label','Étapes indispensables prêtes');
      bar.append(el('i'));const count=el('span','rd-count');meter.append(bar,count);
      header.append(top,meter);
      const body=el('div','rd-body');body.setAttribute('tabindex','-1');
      const footer=el('footer');const status=el('p','rd-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
      const actions=el('div','rd-foot-actions');
      const quitBtn=el('button','rd-quit','Quitter JARVIS');quitBtn.type='button';quitBtn.addEventListener('click',quit);
      const startBtn=el('button','rd-start','Commencer');startBtn.type='button';startBtn.addEventListener('click',()=>{
        /* Premier lancement déjà fait : le bouton ferme seulement (jamais une bascule de Board non demandée). */
        if(S.report&&S.report.onboarded){close('done');return}
        if(startBtn.getAttribute('aria-disabled')==='true'){S.status={kind:'info',hint:true,text:'Terminez d’abord les étapes indispensables (en orange).'};render();return}
        start();
      });
      /* « Signaler un problème » (V1.2 Slice 07, I-010 point 3) : ferme la préparation et ouvre le rapport de problème. */
      const reportBtn=el('button','rd-quit','Signaler un problème');reportBtn.type='button';reportBtn.dataset.role='report-problem';
      reportBtn.addEventListener('click',()=>{const s=win.JarvisSupportReport;
        if(!s||typeof s.open!=='function'){S.status={kind:'failed',text:'Le rapport de problème n’est pas disponible : rechargez la page.'};render();log('error','support_missing',{});return}
        close('report');Promise.resolve(s.open({reason:'readiness'})).catch(error=>log('error','support_open_failed',{error:text(error&&error.message)}))});
      actions.append(reportBtn,quitBtn,startBtn);footer.append(status,actions);
      card.append(header,body,footer);host.append(card);
      host.addEventListener('keydown',event=>{
        if(event.key==='Escape'){event.preventDefault();close('escape');return}
        if(event.key==='Tab'){
          const focusable=[...host.querySelectorAll('button,summary,[tabindex="0"]')].filter(n=>!n.hidden&&n.offsetParent!==null);
          if(!focusable.length)return;
          const first=focusable[0],last=focusable[focusable.length-1];
          if(event.shiftKey&&doc.activeElement===first){event.preventDefault();last.focus()}
          else if(!event.shiftKey&&doc.activeElement===last){event.preventDefault();first.focus()}
        }
      });
      doc.body.appendChild(host);
      ui={title,lede,bar,count,body,status,quitBtn,startBtn,later:later_};
    }

    function rowFor(item){
      const li=el('li','rd-item');li.dataset.state=item.state;li.dataset.required=String(item.required);li.dataset.item=item.id;
      li.append(icon(item.state));
      const label=el('span','rd-label',item.label);const chip=el('span','rd-chip',item.stateLabel);
      li.append(label,chip);
      li.append(el('p','rd-summary',item.summary));
      const running=S.report&&S.report.running?S.report.running:{};
      const actions=el('div','rd-actions');
      for(const action of item.actions){
        const b=el('button','rd-act');b.type='button';b.dataset.action=action.id;b.dataset.primary=String(action.primary);
        const mine=S.busy&&S.busy.item===item.id&&S.busy.action===action.id;
        b.textContent=mine?`${action.label}… ${elapsed((now()-S.busy.since)/1000)}`:action.label;
        if(S.busy){b.setAttribute('aria-disabled','true');if(mine)b.setAttribute('aria-busy','true')}
        b.addEventListener('click',()=>{if(b.getAttribute('aria-disabled')==='true')return;act(item,action,b)});
        actions.append(b);
      }
      li.append(actions);
      const said=S.said[item.id];
      const key=RUNNING_KEYS[item.id]?Object.keys(running).find(k=>RUNNING_KEYS[item.id].test(k)):null;
      const serverRunning=item.state==='in_progress'&&key?running[key]:null;
      const since=serverRunning!==undefined&&serverRunning!==null?Number(serverRunning)+Math.max(0,(now()-S.lastRead)/1000):null;
      if(said&&said.text){
        const p=el('p','rd-said',said.text);p.dataset.kind=said.kind;p.setAttribute('role',said.kind==='failed'?'alert':'status');
        if(said.url){const a=el('a','rd-link','Ouvrir la page');a.href=said.url;a.target='_blank';a.rel='noopener noreferrer';p.append(' ',a)}
        li.append(p);
        if(said.detail){const det=el('details');det.append(el('summary','','Détails'),el('code','',said.detail));li.append(det)}
      }
      /* Compteur vivant tant que la ligne est « En cours » (QA runtime m1), même après la fin de la requête. */
      if(item.state==='in_progress'&&since!==null){
        li.append(el('p','rd-said',`En cours depuis ${elapsed(since)}.`));
      }
      if(item.detail){const det=el('details');det.append(el('summary','', 'Détails'),el('code','',item.detail));li.append(det)}
      return li;
    }

    function render(){
      if(!host||!S.open)return;
      const r=S.report;
      const head=headlineOf(r);
      ui.title.textContent=S.error&&!r?'Préparation de JARVIS':head.title;
      ui.lede.textContent=S.error&&!r?'L’état de JARVIS n’a pas pu être lu.':head.text;
      const p=progressOf(r);
      ui.bar.firstChild.style.setProperty('--p',p.total?String(Math.round(1000*p.done/p.total)/1000):'0');
      ui.bar.setAttribute('aria-valuemin','0');ui.bar.setAttribute('aria-valuemax',String(p.total));ui.bar.setAttribute('aria-valuenow',String(p.done));
      ui.count.textContent=r?`${p.done} sur ${p.total} indispensables prêts`:'';
      /* Garder le focus d'un bouton d'action à travers le rendu (la liste est reconstruite). */
      const active=doc.activeElement,keep=active&&host.contains(active)&&active.dataset&&active.dataset.action
        ?{item:active.closest('[data-item]')&&active.closest('[data-item]').dataset.item,action:active.dataset.action}:null;
      const openDetails=new Set([...host.querySelectorAll('li[data-item] details[open]')].map(n=>n.closest('li').dataset.item));
      ui.body.textContent='';
      if(!r){
        const p2=el('p','rd-said',S.error?`Lecture impossible : ${S.error.message} (${S.error.code}).`:'Lecture de l’état de JARVIS…');
        if(S.error){p2.dataset.kind='failed';p2.setAttribute('role','alert');const retry=el('button','rd-act','Réessayer');retry.type='button';
          retry.addEventListener('click',()=>refresh(true));ui.body.append(p2,retry)}
        else ui.body.append(p2);
      }else{
        for(const group of r.groups){
          const rows=r.items.filter(i=>i.group===group.id);
          if(!rows.length)continue;
          const h=el('h3','',group.label);
          if(group.id!=='essentials'){h.append(el('small','',group.id==='services'?'facultatif':'pour information'))}
          const ul=el('ul');for(const item of rows){const li=rowFor(item);if(openDetails.has(item.id)){const det=li.querySelector('details');if(det)det.open=true}ul.append(li)}
          ui.body.append(h,ul);
        }
        if(S.error){const warn=el('p','rd-said',`Dernière relecture impossible : ${S.error.message} (${S.error.code}). L’état affiché date de la lecture précédente.`);warn.dataset.kind='failed';ui.body.append(warn)}
      }
      if(keep){const again=host.querySelector(`li[data-item="${keep.item}"] button[data-action="${keep.action}"]`);if(again)again.focus({preventScroll:true})}
      const can=!!(r&&(r.ready||r.onboarded))&&!S.starting;
      /* Le pied ne contredit jamais le bouton : la consigne « terminez d'abord… » disparaît quand « Commencer » est actif. */
      if(can&&S.status&&S.status.hint)S.status=null;
      if(can)ui.startBtn.removeAttribute('aria-disabled');else ui.startBtn.setAttribute('aria-disabled','true');
      ui.startBtn.textContent=S.starting?'Ouverture…':r&&r.onboarded?'Fermer':'Commencer';
      ui.quitBtn.hidden=!(r&&r.managed);
      const status=S.status||(S.loading?{kind:'info',text:'Vérification…'}:r?{kind:'info',text:`Vérifié à ${checkedTime(r.checkedAt)}.`}:null);
      ui.status.textContent=status?status.text:'';ui.status.dataset.kind=status?status.kind:'';
    }
    function checkedTime(iso){const t=Date.parse(iso);if(!Number.isFinite(t))return '—';const dt=new Date(t);
      return `${String(dt.getHours()).padStart(2,'0')}:${String(dt.getMinutes()).padStart(2,'0')}:${String(dt.getSeconds()).padStart(2,'0')}`}

    function open(options){
      install();
      if(!S.open){S.returnFocus=doc.activeElement;S.open=true;host.hidden=false;S.status=null}
      if(!S.tick)S.tick=every(()=>{if(S.busy||(S.report&&S.report.items.some(i=>i.state==='in_progress')))render()},1000);
      render();
      const fresh=S.report&&now()-S.lastRead<2000;
      const read=fresh?Promise.resolve(S.report):refresh(!!(options&&options.force));
      if(ui.later&&!(options&&options.noFocus))ui.later.focus({preventScroll:true});
      log('info','opened',{reason:options&&options.reason||'request'});
      return read;
    }
    function close(reason){
      if(!S.open)return;
      S.dismissed=true;
      S.open=false;if(host)host.hidden=true;
      if(S.poll){cancel(S.poll);S.poll=0}
      if(S.tick){stopEvery(S.tick);S.tick=0}
      log('info','closed',{reason});
      const back=S.returnFocus;S.returnFocus=null;
      if(back&&back.isConnected&&typeof back.focus==='function'&&reason!=='navigate')back.focus({preventScroll:true});
    }

    return {
      open,close,refresh,
      state:()=>({report:S.report,error:S.error,open:S.open,busy:S.busy}),
      subscribe(fn){if(typeof fn==='function'){listeners.add(fn)}return ()=>listeners.delete(fn)},
      /* Démarrage de la page : une lecture ; ouverture si l'édition est un produit et que la préparation l'exige. */
      async boot(pageEdition){
        const wanted=win.location&&win.location.hash==='#preparation';
        if(!pageEdition||pageEdition==='full'){if(wanted)return open({reason:'hash'});return null}
        await refresh(false);
        if(wanted||(!S.dismissed&&shouldOpen(S.report,pageEdition)))return open({reason:wanted?'hash':'boot',noFocus:false});
        return null;
      },
      /* Ligne pour l'accueil des présentations : un élément prêt à poser, ou `null`. Relit si le rapport a plus d'une
         minute (jamais en boucle : une lecture à la fois, et l'accueil n'est pas abonné). */
      homeLine(){
        if(!S.loading&&(!S.report||now()-S.lastRead>60000)&&!S.error)refresh(false);
        const model=homeLineOf(S.report);
        if(!model)return null;
        const box=el('div','jvr-ready');box.dataset.tone=model.tone;
        const p=el('p','jvr-ready-text',model.text);if(model.tone==='todo')p.setAttribute('role','status');
        const b=el('button','jvr-ready-open',model.action);b.type='button';b.addEventListener('click',()=>open({reason:'home'}));
        box.append(p,b);
        return box;
      },
    };
  }

  const api=Object.assign({createView,instance:null},pure);
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root&&root.document&&typeof root.fetch==='function'){
    try{
      api.instance=createView({document:root.document,window:root,fetch:(p,i)=>root.fetch(p,i),console:root.console,
        toast:typeof root.toast==='function'?root.toast:null});
      api.open=o=>api.instance.open(o);
      api.homeLine=()=>api.instance.homeLine();
      const start=()=>{
        const edition=root.document.documentElement.getAttribute('data-product-edition');
        api.instance.boot(/^[a-z][a-z_-]*$/.test(edition||'')&&edition!=='unreadable'?edition:null).catch(error=>{
          try{root.console.error('[readiness] readiness.boot_failed '+JSON.stringify({error:text(error&&error.message)}))}catch(_e){/* intentional */}
        });
      };
      if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',start,{once:true});else start();
    }catch(error){
      try{root.console.error('[readiness] readiness.install_failed '+JSON.stringify({error:text(error&&error.message)}))}catch(_e){/* intentional */}
    }
  }
  if(root)root.JarvisReadiness=api;
})(typeof window!=='undefined'?window:globalThis);
