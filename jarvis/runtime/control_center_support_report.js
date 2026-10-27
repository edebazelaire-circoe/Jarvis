/* « Signaler un problème », côté page (jarvis-presentation-edition-v1-2, Slice 07).

   Contrat : `docs/support-report.md` ; routes : `jarvis/runtime/support_routes.py` (`/api/support/*`). Ce module ne
   décide rien : il montre l'aperçu du serveur, exige le consentement, puis lance les actes EXPLICITES de
   l'utilisateur (créer puis envoyer, ou créer puis enregistrer / télécharger).

   - **Ouverture** : `JarvisSupportReport.open({reason})`, depuis la vue des erreurs (bouton « Signaler un problème »)
     et le pied de la fenêtre de préparation.
   - **Aperçu** : Board actif, taille approximative, catégories incluses (masquées) et jamais incluses, destination et
     ce que fera « Envoyer ». La destination se modifie ici (réglage `support_email`, vide = défaut).
   - **Consentement** : sans la case cochée, « Envoyer » et « Enregistrer… » refusent et le disent.
   - **Rien ne reste muet** (RULE ZERO) : un acte en cours montre son libellé, un compteur de secondes et son échéance
     (`CREATE_DEADLINE_MS`, `SEND_DEADLINE_MS`) ; un échec dit la phrase du serveur et son code (rôle `alert`), à
     l'écran ET au journal (`[support] support.<clé>`, `obsClientLog` quand la page en a un) ; chaque bouton est
     rendu dans un `finally`. Un échec d'envoi garde le paquet et propose l'enregistrement.

   Bloc pur (`parsePreview`, `formatBytes`, `elapsed`, `blockedReason`) exécuté par node dans
   `tests/unit/test_support_report_js.py` ; bloc navigateur éprouvé par `tests/unit/test_support_report_browser.py`. */
(function(root){
  'use strict';

  const PREVIEW_ROUTE='/api/support/preview';
  const CREATE_ROUTE='/api/support/reports';
  const DESTINATION_ROUTE='/api/support/destination';
  const PREVIEW_DEADLINE_MS=15000;
  const CREATE_DEADLINE_MS=210000;
  /* Seconde reprise m-b : masquer une base prend ~0,7 s par Mo sur ce poste (62 Mo : 43 s) ; l'échéance de création
     grandit avec la taille des bases annoncée par l'aperçu (1,5 s par Mo au-delà du socle : rapport IA et collecte). */
  const CREATE_MS_PER_DB_MB=1500;
  const SEND_DEADLINE_MS=50000;
  const SAVE_DEADLINE_MS=30000;
  const HOST_ID='jvSupport';
  const DESCRIPTION_MAX=4000;
  /* Issue du rapport IA (`support_report.AI_STATUS_TEXT`), en mots de produit. */
  const AI_STATUS=Object.freeze({failed:'échec du modèle',timeout:'délai dépassé',invalid:'réponse écartée',unavailable:'indisponible'});

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
  const text=v=>v===undefined||v===null?'':String(v);

  /* ------------------------------------------------ logique pure */

  function parsePreview(payload){
    if(!isObject(payload)||typeof payload.destination!=='string'||!Array.isArray(payload.included)||!Array.isArray(payload.excluded))
      return {ok:false,code:'support_preview_invalid'};
    const row=r=>Object.freeze({id:text(r.id),label:text(r.label),masked:r.masked===true,
      bytes:Number.isFinite(r.bytes)?r.bytes:null,state:text(r.state)});
    const transport=isObject(payload.transport)?payload.transport:{};
    const board=isObject(payload.active_board)?payload.active_board:null;
    return {ok:true,preview:Object.freeze({destination:payload.destination,defaultDestination:text(payload.default_destination),
      transport:Object.freeze({name:text(transport.name),available:transport.available===true,label:text(transport.label)}),
      board:board?Object.freeze({id:text(board.board_id),title:text(board.title),kind:text(board.board_kind)}):null,
      included:Object.freeze(payload.included.filter(isObject).map(row)),excluded:Object.freeze(payload.excluded.filter(isObject).map(row)),
      approxBytes:Number.isFinite(payload.approx_bytes)?payload.approx_bytes:null,sendInProgress:payload.send_in_progress===true,
      sendLimit:Number.isFinite(payload.send_limit_bytes)?payload.send_limit_bytes:null,
      retention:isObject(payload.retention)?Object.freeze({...payload.retention}):null,
      recent:Array.isArray(payload.recent)?payload.recent.filter(isObject).map(r=>Object.freeze({name:text(r.name),bytes:Number(r.bytes)||0})):[]})};
  }

  function formatBytes(n){
    const v=Number(n);
    if(!Number.isFinite(v)||v<0)return '—';
    if(v<1024)return `${v} o`;
    if(v<1024*1024)return `${Math.max(1,Math.round(v/1024))} Ko`;
    return `${(v/(1024*1024)).toFixed(1).replace('.',',')} Mo`;
  }

  function elapsed(seconds){
    const s=Math.max(0,Math.floor(Number(seconds)||0));
    return s<60?`${s} s`:`${Math.floor(s/60)} min ${String(s%60).padStart(2,'0')} s`;
  }

  /* Échéance de création pour cet aperçu : jamais sous `CREATE_DEADLINE_MS`. */
  function createDeadline(preview){
    const db=preview&&preview.included?preview.included.find(i=>i.id==='state_databases'):null;
    const mb=db&&Number.isFinite(db.bytes)?db.bytes/(1024*1024):0;
    return Math.max(CREATE_DEADLINE_MS,150000+Math.round(mb*CREATE_MS_PER_DB_MB));
  }

  /* Pourquoi un acte est refusé avant tout appel (ou `null`). */
  function blockedReason(state,act){
    if(state.busy)return 'Une action est déjà en cours.';
    /* QA S07 m3 : une messagerie qui n'a pas rendu la main n'ouvre jamais un second brouillon. */
    if(act==='send'&&state.waiting)return 'Un envoi attend encore votre messagerie : terminez-le dans sa fenêtre de rédaction.';
    if(!state.consent)return 'Cochez d’abord la case de consentement.';
    if(act==='send'&&state.preview&&!state.preview.transport.available)
      return `Envoi impossible : ${state.preview.transport.label||'aucun moyen d’envoi'}. Utilisez « Enregistrer… ».`;
    return null;
  }

  const pure={PREVIEW_ROUTE,CREATE_ROUTE,CREATE_DEADLINE_MS,SEND_DEADLINE_MS,parsePreview,formatBytes,elapsed,blockedReason,
    createDeadline};

  /* ------------------------------------------------ page */

  const CSS=`
#${HOST_ID}{position:fixed;inset:0;z-index:63;display:grid;place-items:center;padding:24px;background:radial-gradient(110% 80% at 50% 0%,rgba(14,44,58,.42),transparent 62%),rgba(2,6,10,.72);backdrop-filter:blur(8px) saturate(.9);font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--text,#d8edf7)}
#${HOST_ID}[hidden]{display:none}
#${HOST_ID} .sp-card{width:min(720px,100%);max-height:calc(100vh - 48px);display:grid;grid-template-rows:auto minmax(0,1fr) auto auto;background:linear-gradient(180deg,rgba(9,19,27,.97),rgba(5,11,17,.97));border:1px solid var(--shell-stroke,rgba(174,205,220,.12));border-radius:16px;box-shadow:0 24px 70px rgba(0,0,0,.55),0 2px 0 rgba(255,255,255,.03) inset;overflow:hidden;animation:sp-in 260ms cubic-bezier(.2,.7,.2,1)}
@keyframes sp-in{from{opacity:0;transform:translateY(10px) scale(.985);filter:blur(3px)}to{opacity:1;transform:none;filter:none}}
@media(prefers-reduced-motion:reduce){#${HOST_ID} .sp-card{animation:none}#${HOST_ID} .sp-spin{animation:none}}
#${HOST_ID} header{display:flex;gap:16px;align-items:flex-start;justify-content:space-between;padding:22px 26px 16px;border-bottom:1px solid rgba(174,205,220,.08)}
#${HOST_ID} h2{margin:0;font-size:21px;line-height:1.25;font-weight:650;letter-spacing:-.01em}
#${HOST_ID} .sp-lede{margin:6px 0 0;color:var(--muted,#7190a0);max-width:60ch}
#${HOST_ID} .sp-close{flex:none;padding:6px 12px;border:1px solid rgba(174,205,220,.18);border-radius:999px;background:none;color:var(--muted,#7190a0);font:inherit;font-size:12.5px;cursor:pointer}
#${HOST_ID} .sp-close:hover{color:var(--text,#d8edf7);border-color:rgba(174,205,220,.4)}
#${HOST_ID} .sp-body{overflow:auto;padding:14px 26px 16px;display:grid;gap:16px;align-content:start;scrollbar-gutter:stable}
#${HOST_ID} label.sp-field{display:grid;gap:6px;font-weight:600}
#${HOST_ID} label.sp-field small{font-weight:400;color:var(--muted,#7190a0)}
#${HOST_ID} textarea{min-height:84px;resize:vertical;padding:10px 12px;border-radius:10px;border:1px solid rgba(174,205,220,.2);background:rgba(3,8,12,.6);color:var(--text,#d8edf7);font:inherit;font-weight:400}
#${HOST_ID} textarea:focus,#${HOST_ID} input[type=email]:focus{outline:none;border-color:var(--accent,#6ee7ff)}
#${HOST_ID} h3{margin:0 0 8px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted,#7190a0)}
#${HOST_ID} .sp-meta{margin:0 0 10px;color:#b7cfdb}
#${HOST_ID} ul{list-style:none;margin:0;padding:0;display:grid;gap:2px}
#${HOST_ID} li{display:grid;grid-template-columns:18px minmax(0,1fr) auto;gap:10px;align-items:center;padding:6px 8px;border-radius:8px}
#${HOST_ID} li:hover{background:rgba(174,205,220,.04)}
#${HOST_ID} li svg{width:16px;height:16px;color:var(--ok,#68e0a0)}
#${HOST_ID} ul.sp-out{display:flex;flex-wrap:wrap;gap:6px}
#${HOST_ID} ul.sp-out li{display:inline-flex;gap:6px;padding:3px 10px 3px 7px;border-radius:999px;border:1px solid rgba(174,205,220,.14);font-size:12px;color:#b7cfdb}
#${HOST_ID} ul.sp-out li:hover{background:none}
#${HOST_ID} ul.sp-out li svg{width:13px;height:13px;color:var(--muted,#7190a0)}
#${HOST_ID} h3.sp-gap{margin-top:16px}
#${HOST_ID} .sp-commit{display:grid;gap:10px;padding:12px 26px 14px;border-top:1px solid rgba(174,205,220,.08)}
#${HOST_ID} .sp-chip{font-size:11.5px;padding:1px 8px;border-radius:999px;border:1px solid rgba(174,205,220,.16);color:var(--muted,#7190a0);white-space:nowrap;font-variant-numeric:tabular-nums}
#${HOST_ID} .sp-dest{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;padding:10px 12px;border-radius:10px;background:rgba(174,205,220,.04);border:1px solid rgba(174,205,220,.1)}
#${HOST_ID} .sp-dest p{margin:0;flex:1 1 280px}
#${HOST_ID} .sp-dest b{font-weight:600}
#${HOST_ID} .sp-dest input{flex:1 1 220px;padding:6px 10px;border-radius:8px;border:1px solid rgba(174,205,220,.25);background:rgba(3,8,12,.6);color:var(--text,#d8edf7);font:inherit}
#${HOST_ID} label.sp-consent{display:grid;grid-template-columns:20px minmax(0,1fr);gap:10px;align-items:start;padding:12px;border-radius:10px;border:1px solid rgba(255,159,67,.35);background:rgba(255,159,67,.06);cursor:pointer}
#${HOST_ID} label.sp-consent[data-checked=true]{border-color:rgba(104,224,160,.35);background:rgba(104,224,160,.05)}
#${HOST_ID} label.sp-consent input{width:18px;height:18px;margin:2px 0 0;accent-color:var(--ok,#68e0a0)}
#${HOST_ID} .sp-result{display:grid;gap:8px;padding:12px;border-radius:10px;border:1px solid rgba(174,205,220,.14)}
#${HOST_ID} .sp-result[hidden]{display:none}
#${HOST_ID} .sp-result p{margin:0}
#${HOST_ID} .sp-said{font-size:12.5px;color:var(--sem-working,#4da3ff)}
#${HOST_ID} .sp-said[data-kind=failed]{color:var(--danger,#ff6577)}
#${HOST_ID} .sp-said[data-kind=ok]{color:var(--ok,#68e0a0)}
#${HOST_ID} details{font-size:12px;color:var(--muted,#7190a0)}
#${HOST_ID} details code{display:block;margin-top:4px;white-space:pre-wrap;word-break:break-word;color:#9fb8c5}
#${HOST_ID} .sp-row{display:flex;flex-wrap:wrap;gap:8px}
#${HOST_ID} button.sp-act,#${HOST_ID} a.sp-act{padding:6px 13px;border-radius:8px;border:1px solid rgba(174,205,220,.22);background:rgba(174,205,220,.05);color:var(--text,#d8edf7);font:inherit;font-size:12.5px;cursor:pointer;text-decoration:none}
#${HOST_ID} button.sp-act:hover,#${HOST_ID} a.sp-act:hover{border-color:var(--accent,#6ee7ff)}
#${HOST_ID} button[aria-disabled=true]{opacity:.55;cursor:not-allowed}
#${HOST_ID} button[aria-busy=true]{cursor:progress}
#${HOST_ID} button:focus-visible,#${HOST_ID} a:focus-visible,#${HOST_ID} input:focus-visible,#${HOST_ID} summary:focus-visible{outline:var(--shell-focus-w,2px) solid var(--shell-focus,#6ee7ff);outline-offset:var(--shell-focus-offset,2px)}
#${HOST_ID} footer{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;justify-content:space-between;padding:14px 26px;border-top:1px solid rgba(174,205,220,.08);background:rgba(3,8,12,.6)}
#${HOST_ID} .sp-status{margin:0;font-size:12.5px;color:var(--muted,#7190a0);min-height:1.5em;display:flex;gap:8px;align-items:center;flex:1 1 260px}
#${HOST_ID} .sp-status[data-kind=failed]{color:var(--danger,#ff6577)}
#${HOST_ID} .sp-status[data-kind=ok]{color:var(--ok,#68e0a0)}
#${HOST_ID} .sp-spin{width:14px;height:14px;flex:none;border-radius:50%;border:2px solid rgba(77,163,255,.25);border-top-color:var(--sem-working,#4da3ff);animation:sp-turn 1s linear infinite}
@keyframes sp-turn{to{transform:rotate(360deg)}}
#${HOST_ID} .sp-foot{display:flex;gap:10px;align-items:center;margin-left:auto}
#${HOST_ID} .sp-save{padding:9px 16px;border-radius:10px;border:1px solid rgba(174,205,220,.25);background:none;color:var(--text,#d8edf7);font:inherit;cursor:pointer}
#${HOST_ID} .sp-send{padding:9px 20px;border-radius:10px;border:1px solid color-mix(in srgb,var(--accent,#6ee7ff) 60%,transparent);background:color-mix(in srgb,var(--accent,#6ee7ff) 16%,transparent);color:var(--text,#d8edf7);font:inherit;font-weight:600;cursor:pointer}
@media(max-width:600px){#${HOST_ID}{padding:10px}#${HOST_ID} header,#${HOST_ID} .sp-body,#${HOST_ID} .sp-commit,#${HOST_ID} footer{padding-left:16px;padding-right:16px}#${HOST_ID} textarea{min-height:60px}}
@media(forced-colors:active){#${HOST_ID} .sp-card{border-color:CanvasText}#${HOST_ID} button{border-color:ButtonText}}
`;

  function createView(deps){
    const d=deps||{};
    const doc=d.document,win=d.window||root;
    const fetchImpl=d.fetch;
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms)),cancel=d.clearTimeout||(id=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms)),stopEvery=d.clearInterval||(id=>clearInterval(id));
    const now=d.now||(()=>Date.now());
    const sink=d.console||null;
    const S={open:false,preview:null,previewError:null,loading:false,consent:false,description:'',busy:null,bundle:null,
      said:null,status:null,editing:false,tick:0,returnFocus:null,pending:null,saveOffered:false,sent:false,waiting:false};
    let host=null,ui=null;

    function log(level,key,data){
      const line=`[support] support.${key} ${JSON.stringify(data||{})}`;
      try{if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}}
      catch(_e){/* intentional: a broken console must not break the page */}
      try{const obs=d.obsClientLog||win.obsClientLog;if(level!=='info'&&typeof obs==='function')obs(level,level==='error'?'ERROR':'WARN',`support_${key}`,data||{})}
      catch(_e){/* intentional: the journal is optional on this page */}
    }

    /* Requête bornée : la réponse ET son corps tiennent dans l'échéance ; un refus rend `{code, message, detail}`. */
    async function call(method,path,deadline,body){
      let timer=0;
      const controller=typeof win.AbortController==='function'?new win.AbortController():null;
      const expiry=new Promise((_,reject)=>{timer=later(()=>{if(controller)controller.abort();
        reject(Object.assign(new Error(`pas de réponse après ${Math.round(deadline/1000)} s`),{code:'timeout'}))},deadline)});
      const read=(async()=>{
        if(!fetchImpl)throw Object.assign(new Error('la porte réseau de la page manque'),{code:'network'});
        const init={method,cache:'no-store',signal:controller?controller.signal:undefined};
        if(method==='POST'){init.headers={'Content-Type':'application/json'};init.body=JSON.stringify(body||{})}
        const response=await fetchImpl(path,init);
        let payload=null;try{payload=await response.json()}catch(_e){payload=null /* intentional: reported below */}
        if(!response.ok){
          const e=isObject(payload)&&isObject(payload.error)?payload.error:{};
          throw Object.assign(new Error(text(e.message)||`HTTP ${response.status}`),{code:text(e.code)||`http_${response.status}`,detail:text(e.detail)});
        }
        if(!isObject(payload))throw Object.assign(new Error('réponse illisible'),{code:'support_payload_invalid'});
        return payload;
      })();
      expiry.catch(()=>{/* intentional: the race reports it */});read.catch(()=>{/* intentional: the race reports it */});
      try{return await Promise.race([read,expiry])}finally{if(timer)cancel(timer)}
    }

    async function loadPreview(){
      S.loading=true;render();
      try{
        const parsed=parsePreview(await call('GET',PREVIEW_ROUTE,PREVIEW_DEADLINE_MS));
        if(!parsed.ok)throw Object.assign(new Error('aperçu illisible'),{code:parsed.code});
        S.preview=parsed.preview;S.previewError=null;
        /* Seconde reprise m-d : un envoi encore en attente (même ouvert d'une autre fois) bloque « Envoyer ». */
        if(S.preview.sendInProgress)S.waiting=true;
        log('info','preview',{board:!!S.preview.board,approx_bytes:S.preview.approxBytes,transport:S.preview.transport.name});
      }catch(error){
        S.previewError={code:text(error&&error.code)||'network',message:text(error&&error.message)};
        log('warn','preview_failed',S.previewError);
      }finally{S.loading=false;render()}
    }

    function fail(error,prefix){
      const code=text(error&&error.code)||'network';
      S.said={kind:'failed',text:`${prefix} ${text(error&&error.message)||'L’action n’a pas abouti.'}`,detail:[code,text(error&&error.detail)].filter(Boolean).join(' : ')};
      return code;
    }

    async function ensureBundle(){
      if(S.bundle)return S.bundle;
      const limit=createDeadline(S.preview);
      S.busy={kind:'create',since:now(),label:'Préparation du paquet et du rapport',limit};render();
      const answer=await call('POST',CREATE_ROUTE,limit,{consent:true,description:S.description.slice(0,DESCRIPTION_MAX)});
      const b=isObject(answer.bundle)?answer.bundle:null;
      if(!b||typeof b.name!=='string')throw Object.assign(new Error('réponse sans paquet'),{code:'support_payload_invalid'});
      S.bundle={name:b.name,bytes:Number(b.bytes)||0,reportKind:text(b.report_kind),aiStatus:text(b.ai_status),aiDetail:text(b.ai_detail),
        sendable:b.sendable!==false,omitted:Array.isArray(b.omitted)?b.omitted.length:0};
      log('info','created',{name:S.bundle.name,bytes:S.bundle.bytes,report_kind:S.bundle.reportKind});
      return S.bundle;
    }

    async function act(kind){
      if(kind==='send'&&S.sent){close('done');return}
      const reason=blockedReason(S,kind);
      if(reason){S.status={kind:'failed',text:reason};render();log('info','blocked',{act:kind,reason});return}
      S.said=null;S.status=null;S.pending=kind; /* l'acte qui demande la création : son bouton est marqué occupé */
      try{
        await ensureBundle();
        if(kind==='send'){
          S.busy={kind:'send',since:now(),label:'Remise à votre messagerie',limit:SEND_DEADLINE_MS};render();
          const outcome=await call('POST',`${CREATE_ROUTE}/${encodeURIComponent(S.bundle.name)}/send`,SEND_DEADLINE_MS,{});
          S.said={kind:outcome.status==='waiting'?'info':'ok',text:text(outcome.message)};
          /* Remis : le bouton principal devient « Fermer » (jamais un second envoi du même paquet par réflexe). */
          S.sent=outcome.status!=='waiting';S.waiting=outcome.status==='waiting';
          log('info','sent',{name:S.bundle.name,status:text(outcome.status)});
        }else{
          S.said={kind:'ok',text:'Paquet prêt. Choisissez où l’enregistrer.'};S.saveOffered=true;
        }
      }catch(error){
        const code=fail(error,kind==='send'&&S.bundle?'Envoi impossible :':'Paquet non créé :');
        if(kind==='send'&&S.bundle)S.saveOffered=true;
        log('error',kind==='send'&&S.bundle?'send_failed':'create_failed',{code,message:text(error&&error.message),detail:text(error&&error.detail)});
      }finally{S.busy=null;S.pending=null;render()}
    }

    async function saveToDocuments(button){
      if(!S.bundle||S.busy)return;
      S.busy={kind:'save',since:now(),label:'Copie dans Documents\\Jarvis',limit:SAVE_DEADLINE_MS};render();
      try{
        const outcome=await call('POST',`${CREATE_ROUTE}/${encodeURIComponent(S.bundle.name)}/save`,SAVE_DEADLINE_MS,{});
        S.said={kind:'ok',text:text(outcome.message)};log('info','saved',{name:S.bundle.name});
      }catch(error){
        const code=fail(error,'Enregistrement impossible :');
        log('error','save_failed',{code,message:text(error&&error.message),detail:text(error&&error.detail)});
      }finally{S.busy=null;render();if(button&&button.isConnected)button.focus({preventScroll:true})}
    }

    async function saveDestination(value){
      if(S.busy)return;
      S.busy={kind:'destination',since:now(),label:'Enregistrement de la destination',limit:PREVIEW_DEADLINE_MS};render();
      try{
        const answer=await call('POST',DESTINATION_ROUTE,PREVIEW_DEADLINE_MS,{support_email:value});
        if(S.preview)S.preview=Object.freeze({...S.preview,destination:text(answer.destination)});
        S.editing=false;S.status={kind:'ok',text:`Destination : ${text(answer.destination)}.`};
        log('info','destination_changed',{default:value.trim()===''});
      }catch(error){
        S.status={kind:'failed',text:`Destination non modifiée : ${text(error&&error.message)} (${text(error&&error.code)||'network'})`};
        log('error','destination_failed',{code:text(error&&error.code),message:text(error&&error.message)});
      }finally{S.busy=null;render()}
    }

    /* ---------------- rendu */

    function el(tag,cls,content){const n=doc.createElement(tag);if(cls)n.className=cls;if(content!==undefined)n.textContent=content;return n}
    function mark(kind){
      const ns='http://www.w3.org/2000/svg',svg=doc.createElementNS(ns,'svg');
      svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
      svg.setAttribute('stroke-width','2');svg.setAttribute('stroke-linecap','round');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
      const p=doc.createElementNS(ns,'path');p.setAttribute('d',kind==='in'?'M5 12.5l4.2 4.2L19 7':'M7 7l10 10M17 7L7 17');svg.appendChild(p);
      return svg;
    }
    function ensureStyle(){
      if(!doc||!doc.head||doc.getElementById('jvSupportStyle'))return;
      const style=el('style');style.id='jvSupportStyle';style.textContent=CSS;doc.head.appendChild(style);
    }
    function install(){
      if(host)return;
      ensureStyle();
      host=el('div');host.id=HOST_ID;host.hidden=true;host.setAttribute('role','dialog');host.setAttribute('aria-modal','true');
      host.setAttribute('aria-labelledby','jvSupportTitle');host.setAttribute('aria-describedby','jvSupportLede');
      const card=el('section','sp-card');
      const header=el('header');const titles=el('div');
      const title=el('h2','','Signaler un problème');title.id='jvSupportTitle';
      const lede=el('p','sp-lede','JARVIS prépare un paquet de diagnostic pour l’équipe de support : un rapport, les journaux et le contexte de votre projet, sans aucune clé ni mot de passe.');
      lede.id='jvSupportLede';titles.append(title,lede);
      const closeBtn=el('button','sp-close','Fermer');closeBtn.type='button';closeBtn.addEventListener('click',()=>close('close'));
      header.append(titles,closeBtn);
      const body=el('div','sp-body');
      const field=el('label','sp-field');field.append(el('span','','Que s’est-il passé ?'));
      const area=el('textarea');area.id='jvSupportDescription';area.maxLength=DESCRIPTION_MAX;area.rows=3;
      area.placeholder='Ce que vous faisiez, ce que vous attendiez, ce qui s’est passé.';
      area.addEventListener('input',()=>{S.description=area.value;if(S.bundle){S.bundle=null;S.saveOffered=false;S.said=null;S.sent=false;render()}});
      field.append(area,el('small','','Facultatif. Évitez d’y écrire un mot de passe.'));
      const content=el('section','sp-content');content.setAttribute('aria-label','Contenu du paquet');
      const dest=el('div','sp-dest');
      const consent=el('label','sp-consent');const box=el('input');box.type='checkbox';box.id='jvSupportConsent';
      box.addEventListener('change',()=>{S.consent=box.checked;if(S.consent&&S.status&&S.status.kind==='failed')S.status=null;render()});
      consent.append(box,el('span','','J’ai compris que ce paquet contient, masqués, mes conversations récentes avec JARVIS, la mémoire du Board actif et les journaux, et j’accepte de le transmettre au support.'));
      const result=el('div','sp-result');result.hidden=true;result.setAttribute('aria-live','polite');
      body.append(field,content);
      /* Hors du défilement : la destination, le consentement et l'issue restent visibles au-dessus des boutons. */
      const commit=el('div','sp-commit');commit.append(dest,consent,result);
      const footer=el('footer');const status=el('p','sp-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
      const foot=el('div','sp-foot');
      const save=el('button','sp-save','Enregistrer…');save.type='button';save.addEventListener('click',()=>act('save'));
      const send=el('button','sp-send','Envoyer');send.type='button';send.addEventListener('click',()=>act('send'));
      foot.append(save,send);footer.append(status,foot);
      card.append(header,body,commit,footer);host.append(card);
      host.addEventListener('keydown',event=>{
        if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(S.editing){S.editing=false;render();return}close('escape');return}
        if(event.key==='Tab'){
          const focusable=[...host.querySelectorAll('button,textarea,input,a[href],summary')].filter(n=>!n.hidden&&n.offsetParent!==null);
          if(!focusable.length)return;
          const first=focusable[0],last=focusable[focusable.length-1];
          if(event.shiftKey&&doc.activeElement===first){event.preventDefault();last.focus()}
          else if(!event.shiftKey&&doc.activeElement===last){event.preventDefault();first.focus()}
        }
      });
      doc.body.appendChild(host);
      ui={area,content,dest,consent,box,result,status,save,send,closeBtn};
    }

    function renderContent(){
      const c=ui.content;c.textContent='';
      const p=S.preview;
      if(!p){
        const line=el('p','sp-said',S.previewError?`Aperçu indisponible : ${S.previewError.message} (${S.previewError.code}). Le paquet peut quand même être créé.`:'Lecture du contenu du paquet…');
        if(S.previewError){line.dataset.kind='failed';line.setAttribute('role','alert');const retry=el('button','sp-act','Réessayer');retry.type='button';retry.addEventListener('click',loadPreview);c.append(line,retry)}
        else c.append(line);
        return;
      }
      c.append(el('h3','','Contenu du paquet'));
      const board=p.board?`Board actif : ${p.board.title||p.board.id}`:'Aucun Board actif connu';
      c.append(el('p','sp-meta',`${board} · environ ${formatBytes(p.approxBytes)} avant compression.`));
      const inList=el('ul','sp-in');
      for(const item of p.included){
        const li=el('li');li.dataset.category=item.id;li.append(mark('in'),el('span','',item.label));
        li.append(el('span','sp-chip',item.bytes?`masqué · ${formatBytes(item.bytes)}`:'masqué'));inList.append(li);
      }
      const outList=el('ul','sp-out');
      for(const item of p.excluded){const li=el('li');li.dataset.category=item.id;li.append(mark('out'),el('span','',item.label));outList.append(li)}
      c.append(inList,el('h3','sp-gap','Jamais inclus'),outList);
    }

    function renderDestination(){
      const box=ui.dest;box.textContent='';
      const p=S.preview;
      if(!p){box.hidden=true;return}
      box.hidden=false;
      if(S.editing){
        const input=el('input');input.type='email';input.id='jvSupportDestination';input.value=p.destination;input.setAttribute('aria-label','Adresse du support');
        const ok=el('button','sp-act','Enregistrer');ok.type='button';ok.addEventListener('click',()=>saveDestination(input.value));
        const reset=el('button','sp-act','Adresse par défaut');reset.type='button';reset.addEventListener('click',()=>saveDestination(''));
        input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveDestination(input.value)}});
        box.append(input,ok,reset);
        later(()=>{if(input.isConnected&&doc.activeElement!==input)input.focus()},0);
        return;
      }
      const line=el('p');line.append('Destinataire : ',el('b','',p.destination),` — ${p.transport.label||'moyen d’envoi inconnu'}.`);
      const edit=el('button','sp-act','Modifier');edit.type='button';edit.dataset.role='edit-destination';edit.addEventListener('click',()=>{S.editing=true;render()});
      box.append(line,edit);
    }

    function renderResult(){
      const r=ui.result;r.textContent='';
      const b=S.bundle;
      if(!b&&!S.said){r.hidden=true;return}
      r.hidden=false;
      if(b){
        const report=b.reportKind==='ai'?'rapport IA écrit':`rapport factuel (IA : ${AI_STATUS[b.aiStatus]||'indisponible'})`;
        r.append(el('p','',`Paquet ${b.name} · ${formatBytes(b.bytes)} · ${report}${b.omitted?` · ${b.omitted} élément(s) omis, voir manifest.json`:''}.`));
      }
      if(S.said){
        const p=el('p','sp-said',S.said.text);p.dataset.kind=S.said.kind;p.setAttribute('role',S.said.kind==='failed'?'alert':'status');r.append(p);
        if(S.said.detail){const det=el('details');det.append(el('summary','','Détails'),el('code','',S.said.detail));r.append(det)}
      }
      if(b&&S.saveOffered){
        const row=el('div','sp-row');
        const docs=el('button','sp-act','Enregistrer dans Documents\\Jarvis');docs.type='button';docs.dataset.role='save-documents';
        docs.addEventListener('click',()=>saveToDocuments(docs));
        const dl=el('a','sp-act','Télécharger…');dl.href=`${CREATE_ROUTE}/${encodeURIComponent(b.name)}/download`;dl.setAttribute('download',b.name);
        dl.dataset.role='download';dl.addEventListener('click',()=>log('info','download',{name:b.name}));
        row.append(docs,dl);
        if(S.said&&S.said.kind==='failed'&&b){const retry=el('button','sp-act','Réessayer l’envoi');retry.type='button';retry.dataset.role='retry-send';retry.addEventListener('click',()=>act('send'));row.append(retry)}
        r.append(row);
      }
    }

    function render(){
      if(!host||!S.open)return;
      renderContent();renderDestination();renderResult();
      ui.consent.dataset.checked=String(S.consent);ui.box.checked=S.consent;
      const busy=S.busy;
      for(const [button,kind] of [[ui.save,'save'],[ui.send,'send']]){
        const blocked=!!(busy||!S.consent||(kind==='send'&&S.waiting));
        if(blocked)button.setAttribute('aria-disabled','true');else button.removeAttribute('aria-disabled');
        if(busy&&((busy.kind==='create'&&S.pending===kind)||busy.kind===kind))button.setAttribute('aria-busy','true');else button.removeAttribute('aria-busy');
      }
      ui.send.textContent=busy&&busy.kind==='send'?'Envoi…':S.waiting?'En attente de la messagerie…':S.sent?'Fermer':S.bundle&&S.said&&S.said.kind==='failed'?'Réessayer l’envoi':'Envoyer';
      ui.status.textContent='';ui.status.dataset.kind='';
      if(busy){
        const secs=(now()-busy.since)/1000;
        ui.status.append(el('span','sp-spin'),el('span','',`${busy.label}… ${elapsed(secs)} (au plus ${elapsed(busy.limit/1000)}). Fermer la fenêtre n’arrête rien.`));
      }else if(S.status){ui.status.textContent=S.status.text;ui.status.dataset.kind=S.status.kind}
      else if(S.loading)ui.status.textContent='Lecture de l’aperçu…';
      else if(!S.consent)ui.status.textContent='Cochez la case de consentement pour envoyer ou enregistrer.';
    }

    function open(options){
      install();
      if(!S.open){S.returnFocus=doc.activeElement;S.open=true;host.hidden=false;S.status=null}
      if(!S.tick)S.tick=every(()=>{if(S.busy)render()},1000);
      render();
      log('info','opened',{reason:options&&options.reason||'request'});
      const read=loadPreview();
      if(!(options&&options.noFocus))ui.area.focus({preventScroll:true});
      return read;
    }
    function close(reason){
      if(!S.open)return;
      S.open=false;if(host)host.hidden=true;
      if(S.tick){stopEvery(S.tick);S.tick=0}
      /* Un paquet déjà créé reste au dossier de support (rétention) ; la prochaine ouverture repart d'un formulaire neuf. */
      if(!S.busy){S.bundle=null;S.said=null;S.saveOffered=false;S.consent=false;S.editing=false;S.sent=false;S.waiting=false}
      log('info','closed',{reason,busy:!!S.busy});
      const back=S.returnFocus;S.returnFocus=null;
      if(back&&back.isConnected&&typeof back.focus==='function')back.focus({preventScroll:true});
    }

    return {open,close,state:()=>({open:S.open,busy:S.busy,bundle:S.bundle,said:S.said,consent:S.consent,preview:S.preview})};
  }

  const api=Object.assign({createView,instance:null},pure);
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root&&root.document&&typeof root.fetch==='function'){
    try{
      api.instance=createView({document:root.document,window:root,fetch:(p,i)=>root.fetch(p,i),console:root.console,
        toast:typeof root.toast==='function'?root.toast:null});
      api.open=o=>api.instance.open(o);
    }catch(error){
      try{root.console.error('[support] support.install_failed '+JSON.stringify({error:text(error&&error.message)}))}catch(_e){/* intentional */}
    }
  }
  if(root)root.JarvisSupportReport=api;
})(typeof window!=='undefined'?window:globalThis);
