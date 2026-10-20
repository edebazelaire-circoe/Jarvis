/* Tableau d'une relation d'agent, ouvert depuis le graphe des tâches (jarvis-organic-agent-orchestration, Slice 09).

   Une pastille de relation de la scène (`control_center_scene_roles.js`) ouvre ce panneau latéral : la nature de
   la relation (D09), son objet, son état et son issue, ses participants avec leur rôle (D02) et leur statut vivant,
   la mission (origine, état, « état inconnu » si Core la dit `live_unknown`), le paquet d'un relais (D14) et le fil
   des **messages délibérés** (D13 : messages, propositions, critiques, décisions, synthèses — jamais un
   raisonnement privé, que le contrat de Core refuse déjà à l'écriture).

   Lecture seule, deux routes existantes : `GET /api/missions/relations/{id}?after=&limit=` (Slice 06 : relation,
   messages avec `seq`, participants) et `GET /api/missions/{id}` (Slice 05). Aucune écriture.
   États : chargement (compteur vivant, échéance 15 s, puis l'échec dit combien il a attendu), erreur (mots et code
   du serveur, « Réessayer », `console.error('<code>')`), vide (aucun message), à jour (relu toutes les 5 s tant
   que la relation est ouverte et le panneau visible). Tout texte reçu entre par `textContent`.

   Clavier : le titre prend le focus à l'ouverture ; Flèches haut/bas, Début, Fin parcourent les messages ; Échap
   ferme et rend le focus à la pastille qui a ouvert. Un seul panneau latéral : ouvrir ferme `#panel`, le chat et
   l'inspecteur du Studio ; `closePanel()` le ferme. Contrat : `docs/scene-model.md` › *Interface : rôles et
   relations* et `docs/control-center-shell.md` › Zones (`right`). */
(function(root){
  'use strict';
  const Identity=root.JarvisRoleIdentity||(typeof require==='function'?require('./control_center_role_identity.js'):null);
  const PANEL_ID='relationBoard';
  const STYLE_ID='jarvisRelationBoardStyle';
  const PAGE_LIMIT=200;
  const TIMEOUT_MS=15000;
  const REFRESH_MS=5000;
  const RELATION_PATH=(id,after)=>`/api/missions/relations/${encodeURIComponent(id)}?after=${after}&limit=${PAGE_LIMIT}`;
  const MISSION_PATH=id=>`/api/missions/${encodeURIComponent(id)}`;
  const own=(o,k)=>!!o&&Object.prototype.hasOwnProperty.call(o,k);
  const str=v=>typeof v==='string'?v:'';

  /* ----------------------------------------------------------------- modèle pur (testé par node) */

  /* Réponse de la route de relation ramenée à une forme sûre, ou une erreur `relation_board_payload_invalid`. */
  function normalizeRead(body){
    if(!body||typeof body!=='object'||!body.relation||typeof body.relation!=='object'||!Array.isArray(body.messages)){
      const e=new Error('Réponse du tableau hors contrat (relation ou messages absents).');e.code='relation_board_payload_invalid';throw e;
    }
    const r=body.relation;
    const relation={id:str(r.relation_id),kind:str(r.kind),missionId:str(r.mission_id),purpose:str(r.purpose),
      status:r.status==='closed'?'closed':'open',outcome:str(r.outcome),outcomeSummary:str(r.outcome_summary),
      winner:str(r.winner_instance_id),createdAt:str(r.created_at),closedAt:str(r.closed_at),
      participants:Array.isArray(r.participants)?r.participants.filter(p=>p&&typeof p.instance_id==='string')
        .map(p=>({instanceId:p.instance_id,position:str(p.position)})):[],
      handoff:r.handoff&&typeof r.handoff==='object'?r.handoff:null};
    const messages=body.messages.filter(m=>m&&typeof m==='object'&&Number.isInteger(m.seq)).map(m=>({seq:m.seq,
      id:str(m.message_id),author:str(m.author_instance_id),type:str(m.type),text:str(m.text),at:str(m.created_at),
      replyTo:str(m.reply_to_message_id)}));
    const instances=new Map();
    for(const p of Array.isArray(body.participants)?body.participants:[]){
      if(p&&typeof p.instance_id==='string')instances.set(p.instance_id,{instanceId:p.instance_id,roleId:str(p.role_id),
        label:str(p.label),workStatus:p.work_status==null?null:str(p.work_status),owner:p.mission_owner===true});
    }
    return {relation,messages,instances};
  }

  /* Mission lue (`GET /api/missions/{id}`) : la mission de la relation dans l'arbre, et les instances connues. */
  function normalizeMission(body,missionId){
    if(!body||!Array.isArray(body.missions)){const e=new Error('Réponse de mission hors contrat.');e.code='mission_payload_invalid';throw e}
    const m=body.missions.find(item=>item&&item.mission_id===missionId)||null;
    const instances=new Map();
    for(const p of Array.isArray(body.instances)?body.instances:[]){
      if(p&&typeof p.instance_id==='string')instances.set(p.instance_id,{instanceId:p.instance_id,roleId:str(p.role_id),
        label:str(p.label),workStatus:p.work_status==null?null:str(p.work_status),owner:p.mission_owner===true});
    }
    return {mission:m?{id:m.mission_id,objective:str(m.objective),origin:str(m.origin_kind),status:str(m.status),
      liveUnknown:m.live_unknown===true}:null,instances};
  }

  /* Messages : une lecture (`after`) s'ajoute à ce qui est déjà là, sans doublon, dans l'ordre de `seq`. */
  function mergeMessages(known,fresh){
    const bySeq=new Map(known.map(m=>[m.seq,m]));
    for(const m of fresh)bySeq.set(m.seq,m);
    return [...bySeq.values()].sort((a,b)=>a.seq-b.seq);
  }

  /* Mission en mots : « état inconnu » pour `live_unknown`, jamais « en cours ». */
  const MISSION_STATUS=Object.freeze({open:'ouverte',completed:'terminée',cancelled:'annulée',failed:'en échec'});
  function missionStatusLabel(mission){
    if(!mission)return '';
    if(mission.liveUnknown)return 'état inconnu';
    return own(MISSION_STATUS,mission.status)?MISSION_STATUS[mission.status]:mission.status;
  }
  function workStatusLabel(status){
    if(status==null)return 'hors du suivi vivant';
    return Identity.label(Identity.WORK_STATUS_LABELS,status);
  }
  const ORIGIN_WORDS=Object.freeze({code:'code',general:'général',desktop:'poste de travail',fast:'tâche rapide'});
  function originLabel(origin){return own(ORIGIN_WORDS,origin)?ORIGIN_WORDS[origin]:origin}

  /* Heure d'un message : HH:MM aujourd'hui, sinon la date courte. */
  function timeLabel(iso,nowMs){
    const at=Date.parse(iso);
    if(!Number.isFinite(at))return '';
    const d=new Date(at),today=new Date(nowMs);
    const hm=`${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    if(d.toDateString()===today.toDateString())return hm;
    return `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')} ${hm}`;
  }

  /* Conseil adapté à l'erreur réelle. */
  function advice(code){
    if(code==='relation_unknown')return 'Cette relation n’existe pas (ou plus) dans l’historique des missions de Core.';
    if(code==='relation_board_timeout')return 'Le Control Center ou Core ne répond pas : vérifiez qu’ils tournent, puis réessayez.';
    if(code==='relation_board_unreachable')return 'Le Control Center est injoignable : vérifiez qu’il tourne, puis réessayez.';
    if(code==='missions_not_configured'||code==='mission_history_unavailable')return 'L’historique des missions est indisponible sur ce poste : le travail vivant continue, le tableau reviendra avec lui.';
    if(code==='relation_board_payload_invalid')return 'La page et le serveur ne sont peut-être pas de la même version : rechargez la page.';
    return 'Réessayez ; si l’erreur revient, signalez-la avec le code ci-dessous.';
  }

  /* --------------------------------------------------------------------- panneau (navigateur) */

  const STYLE=`
.relation-board{min-width:0}
.relation-board header{gap:10px}
.relation-board header h2{display:flex;align-items:center;gap:9px;min-width:0;outline:none}
.relation-board header h2:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.relation-board header h2 span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rb-glyph{flex:none;display:grid;place-items:center;width:26px;height:26px;border-radius:50%;border:1.5px solid var(--rb-kind);color:var(--rb-kind)}
.rb-glyph svg{width:15px;height:15px}
.relation-board[data-kind="delegation"]{--rb-kind:#a9c3d4}
.relation-board[data-kind="communication"]{--rb-kind:#5fd6e8}
.relation-board[data-kind="adversary"]{--rb-kind:#ff7f63}
.relation-board[data-kind="qa"]{--rb-kind:#c8ea6e}
.relation-board[data-kind="handoff"]{--rb-kind:#c9a6ff}
.relation-board[data-kind="qa"] .rb-glyph{border-radius:6px}
.relation-board[data-kind="adversary"] .rb-glyph{border-style:double;border-width:3px;border-radius:5px}
.relation-board[data-kind="communication"] .rb-glyph{border-radius:13px 13px 13px 3px}
.rb-body{display:flex;flex-direction:column;gap:16px;padding:14px 17px 18px;overflow:auto;min-height:0;flex:1 1 auto;font-size:13px;line-height:1.5}
.rb-state{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:var(--muted)}
.rb-state[data-tone="error"]{color:var(--danger)}
.rb-spin{width:12px;height:12px;border-radius:50%;border:2px solid color-mix(in srgb,var(--accent) 30%,transparent);border-top-color:var(--accent);animation:rb-spin 1s linear infinite}
@keyframes rb-spin{to{transform:rotate(360deg)}}
.rb-error{display:flex;flex-direction:column;gap:8px;padding:12px;border:1px solid color-mix(in srgb,var(--danger) 55%,transparent);border-radius:8px;
  background:color-mix(in srgb,var(--danger) 9%,transparent)}
.rb-error strong{color:var(--danger)}
.rb-code{font-size:11px;color:var(--muted)}
.rb-btn{align-self:flex-start;background:transparent;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 11px;font:inherit;font-size:12px;cursor:pointer}
.rb-btn:hover{border-color:var(--accent)}
.rb-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rb-btn:disabled,.rb-btn[aria-disabled="true"]{opacity:.5;cursor:progress}
.rb-section{display:flex;flex-direction:column;gap:7px}
.rb-section h3{margin:0;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:600}
.rb-purpose{margin:0;font-size:14px;color:var(--text)}
.rb-facts{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 12px;margin:0}
.rb-facts dt{color:var(--muted)}
.rb-facts dd{margin:0;min-width:0;overflow-wrap:anywhere}
.rb-unknown{color:var(--warn)}
.rb-people{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.rb-person{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}
.rb-person-name{min-width:0;overflow-wrap:anywhere}
.rb-person-meta{color:var(--muted);font-size:12px}
.rb-ident{--rb-role:var(--role-accent-slate);display:inline-flex;align-items:center;gap:4px;height:20px;padding:0 6px 0 4px;border-radius:5px;
  border:1px solid color-mix(in srgb,var(--rb-role) 70%,transparent);color:var(--rb-role);font-size:10.5px;font-weight:700;letter-spacing:.05em;flex:none}
.rb-ident svg{width:13px;height:13px}
.rb-ident-owner{background:color-mix(in srgb,var(--rb-role) 20%,transparent);border-width:1.5px}
.rb-thread{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.rb-msg{display:flex;flex-direction:column;gap:5px;padding:10px 12px;border-radius:8px;border:1px solid var(--line);background:rgba(255,255,255,.015);outline:none}
.rb-msg:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.rb-msg-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.rb-msg-type{font-weight:700;color:var(--text);letter-spacing:.02em}
.rb-msg-text{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--text)}
.rb-empty{margin:0;color:var(--muted)}
.rb-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:10px 17px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
.rb-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (prefers-reduced-motion:reduce){.rb-spin{animation:none}}
@media (forced-colors:active){
  .rb-glyph,.rb-ident,.rb-msg,.rb-error,.rb-btn{forced-color-adjust:none;border-color:CanvasText;color:CanvasText;background:Canvas}
  .rb-msg:focus-visible,.rb-btn:focus-visible,.relation-board header h2:focus-visible{outline:3px solid Highlight}
}`;

  function create(options){
    const opts=options||{};
    const doc=opts.document||root.document;
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const timers={set:opts.setTimeout||((f,ms)=>root.setTimeout(f,ms)),clear:opts.clearTimeout||(id=>root.clearTimeout(id)),
      every:opts.setInterval||((f,ms)=>root.setInterval(f,ms)),stop:opts.clearInterval||(id=>root.clearInterval(id))};
    const log=(level,code,data)=>{try{(level==='error'?console.error:level==='warn'?console.warn:console.info)(code,data||{})}catch(_e){/* intentionnel : console absente, l'état est déjà affiché */}};
    const words={identity:id=>(opts.identity&&opts.identity(id))||Identity.fallbackIdentity(id),
      relationLabel:kind=>(opts.relationLabel&&opts.relationLabel(kind))||Identity.label(Identity.RELATION_KINDS,kind,{label:kind}).label,
      accentOf:token=>(opts.accentOf&&opts.accentOf(token))||(Identity.TOKEN.test(String(token||''))?token:'slate')};
    const fetchJson=opts.fetchJson||(async(path)=>{
      const controller=new AbortController();
      const timer=timers.set(()=>controller.abort(),TIMEOUT_MS);
      let response;
      try{response=await root.fetch(path,{cache:'no-store',signal:controller.signal})}
      catch(error){
        const e=new Error(error&&error.name==='AbortError'?`Pas de réponse après ${Math.round(TIMEOUT_MS/1000)} s.`:`Control Center injoignable : ${error&&error.message||error}`);
        e.code=error&&error.name==='AbortError'?'relation_board_timeout':'relation_board_unreachable';throw e;
      }finally{timers.clear(timer)}
      const text=await response.text();
      let body=null;try{body=text?JSON.parse(text):null}catch(_e){body=null}
      if(!response.ok||!body||body.ok===false){
        const env=body&&body.error&&typeof body.error==='object'?body.error:null;
        const e=new Error((env&&env.message)||(body&&typeof body.error==='string'&&body.error)||`HTTP ${response.status}`);
        e.code=(env&&env.code)||`http_${response.status}`;e.status=response.status;throw e;
      }
      return body;
    });

    const st={open:false,relationId:'',kind:'',missionId:'',trigger:null,phase:'idle',startedAt:0,error:null,
      read:null,messages:[],instances:new Map(),mission:null,missionError:null,lastSeq:0,readAt:0,more:false,
      generation:0,inflight:false,focusIndex:0};
    let panel=null,ticker=null,refresher=null;
    const el=(tag,cls,text)=>{const e=doc.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e};
    const svg=markup=>{const holder=doc.createElement('span');holder.innerHTML=markup;return holder.firstChild};  // pictogrammes constants

    function ensurePanel(){
      if(panel&&panel.isConnected)return panel;
      if(!doc.getElementById(STYLE_ID)){const s=doc.createElement('style');s.id=STYLE_ID;s.textContent=STYLE;doc.head.appendChild(s)}
      panel=doc.createElement('section');
      panel.id=PANEL_ID;panel.className='panel relation-board';panel.hidden=true;
      panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','false');panel.setAttribute('aria-labelledby','relationBoardTitle');
      panel.setAttribute('data-shell-control','');
      panel.innerHTML='<header><h2 id="relationBoardTitle" tabindex="-1"></h2><button type="button" class="rb-close" aria-label="Fermer le tableau">×</button></header>'
        +'<div class="rb-body" id="relationBoardBody"></div><div class="rb-foot" id="relationBoardFoot"></div><div class="rb-sr" role="status" aria-live="polite"></div>';
      panel.querySelector('.rb-close').addEventListener('click',()=>close({restoreFocus:true}));
      panel.addEventListener('keydown',onKeyDown);
      (doc.getElementById('app')||doc.body).appendChild(panel);
      return panel;
    }

    function announce(text){const live=panel&&panel.querySelector('.rb-sr');if(live)live.textContent=text}

    function setTrigger(button){
      if(st.trigger&&st.trigger!==button)st.trigger.setAttribute('aria-expanded','false');
      st.trigger=button||null;
      if(st.trigger)st.trigger.setAttribute('aria-expanded','true');
    }

    /* Ouvrir le tableau de `relationId`. Rouvrir la même relation garde ce qui est lu et relit. */
    function open(request){
      const relationId=str(request&&request.relationId);
      if(!relationId){log('warn','relation_board_open_refused',{reason:'relation_id_missing'});return false}
      /* Un seul panneau latéral. `closePanel` nous ferme aussi : la relation ouverte est d'abord oubliée. */
      const same=st.open&&st.relationId===relationId;
      st.open=false;
      try{if(typeof root.closePanel==='function')root.closePanel()}catch(error){log('warn','relation_board_close_panel_failed',{error:String(error)})}
      try{const insp=root.JarvisStudioInspector&&root.JarvisStudioInspector.instance;if(insp&&typeof insp.close==='function')insp.close()}
      catch(error){log('warn','relation_board_close_inspector_failed',{error:String(error)})}
      ensurePanel();
      if(!same){
        st.generation++;bodySig='';
        Object.assign(st,{relationId,kind:str(request.kind),missionId:str(request.missionId),phase:'loading',error:null,read:null,
          messages:[],instances:new Map(),mission:null,missionError:null,lastSeq:0,readAt:0,more:false,focusIndex:0});
      }
      setTrigger(request.trigger||null);
      st.open=true;st.startedAt=now();
      panel.hidden=false;panel.classList.add('open');
      panel.dataset.kind=st.kind;panel.dataset.relationId=relationId;
      render();
      const title=panel.querySelector('#relationBoardTitle');if(title)title.focus({preventScroll:true});
      log('info','relation_board_opened',{relation_id:relationId,kind:st.kind});
      load({full:!same});
      startTicker();
      return true;
    }

    function close(options){
      if(!st.open&&(!panel||panel.hidden))return;
      st.open=false;st.generation++;
      stopTicker();
      if(panel){panel.classList.remove('open');panel.hidden=true}
      const trigger=st.trigger;
      if(trigger)trigger.setAttribute('aria-expanded','false');
      st.trigger=null;
      if(options&&options.restoreFocus){
        if(trigger&&trigger.isConnected)trigger.focus({preventScroll:true});
        else{const scene=doc.getElementById('sceneLayer');if(scene&&scene.focus)scene.focus({preventScroll:true})}
      }
      log('info','relation_board_closed',{relation_id:st.relationId});
    }

    /* Lecture : la relation (tout, ou la suite après `lastSeq`) et, une fois, la mission. Une lecture en vol à la
       fois ; une réponse d'une relation déjà quittée est ignorée (`generation`). */
    async function load(how){
      if(st.inflight&&!(how&&how.force))return;
      const generation=st.generation,full=!!(how&&how.full)||!st.read;
      st.inflight=true;
      if(full){st.phase='loading';st.startedAt=now();st.error=null;render()}
      try{
        const relationRead=fetchJson(RELATION_PATH(st.relationId,full?0:st.lastSeq));
        const missionRead=st.missionId&&(full||!st.mission)?fetchJson(MISSION_PATH(st.missionId)).then(body=>normalizeMission(body,st.missionId),
          error=>{if(generation===st.generation){st.missionError=error;log('warn',error&&error.code||'relation_board_mission_unreadable',{mission_id:st.missionId,error:String(error&&error.message||error)})}return null}):null;
        const read=normalizeRead(await relationRead);
        if(generation!==st.generation)return;
        const before=st.messages.length;
        st.read=read;
        st.messages=full?read.messages:mergeMessages(st.messages,read.messages);
        for(const [id,p] of read.instances)st.instances.set(id,p);
        st.lastSeq=st.messages.length?st.messages[st.messages.length-1].seq:0;
        st.more=read.messages.length>=PAGE_LIMIT;
        st.readAt=now();st.phase='ready';st.error=null;
        if(!st.missionId&&read.relation.missionId)st.missionId=read.relation.missionId;
        const mission=missionRead?await missionRead:null;
        if(generation!==st.generation)return;
        if(mission){st.mission=mission.mission;st.missionError=null;for(const [id,p] of mission.instances)if(!st.instances.has(id))st.instances.set(id,p)}
        const added=st.messages.length-before;
        if(!full&&added>0)announce(added===1?'Un nouveau message.':`${added} nouveaux messages.`);
        log('info','relation_board_read',{relation_id:st.relationId,messages:st.messages.length,added:full?st.messages.length:added});
      }catch(error){
        if(generation!==st.generation)return;
        st.error=error;
        /* Une relecture qui échoue garde le fil déjà lu et dit l'échec ; une première lecture passe en erreur. */
        if(!st.read)st.phase='error';
        log('error',error&&error.code||'relation_board_failed',{relation_id:st.relationId,status:error&&error.status||null,error:String(error&&error.message||error)});
      }finally{
        if(generation===st.generation){st.inflight=false;render()}
        else st.inflight=false;
      }
    }

    /* Compteur de l'attente (1 s) et relecture d'une relation ouverte (5 s), seulement panneau visible. */
    function startTicker(){
      stopTicker();
      ticker=timers.every(()=>{if(st.open&&st.phase==='loading')renderState()},1000);
      refresher=timers.every(()=>{
        if(!st.open||st.inflight||!st.read||doc.visibilityState==='hidden')return;
        if(st.read.relation.status==='open'||(st.mission&&st.mission.status==='open'))load({full:false});
      },REFRESH_MS);
    }
    function stopTicker(){if(ticker!=null){timers.stop(ticker);ticker=null}if(refresher!=null){timers.stop(refresher);refresher=null}}

    /* -------------------------------------------------------------------------------------------- rendu */

    function ident(roleId,owner){
      const who=words.identity(roleId);
      const box=el('span','rb-ident'+(owner?' rb-ident-owner':''));
      box.style.setProperty('--rb-role',`var(--role-accent-${words.accentOf(who.accent)})`);
      box.setAttribute('aria-hidden','true');
      if(owner)box.appendChild(svg(Identity.iconSvg('flag','')));
      box.appendChild(svg(Identity.iconSvg(who.icon,'')));
      box.appendChild(el('b','',who.badge));
      return box;
    }
    function personName(instanceId){
      const p=st.instances.get(instanceId);
      if(!p)return {text:`instance ${instanceId.slice(0,14)}`,roleId:'',owner:false,known:false};
      const who=p.roleId?words.identity(p.roleId):null;
      return {text:[who?who.name:'',p.label?`« ${p.label} »`:''].filter(Boolean).join(' ')||`instance ${instanceId.slice(0,14)}`,
        roleId:p.roleId,owner:p.owner,known:true,workStatus:p.workStatus};
    }

    /* Le corps n'est refait que si ce qu'il montre a changé : une relecture sans nouveauté (toutes les 5 s) ne
       touche à rien, et le focus clavier reste sur le message, le bouton ou le titre où il était. */
    let bodySig='';
    function render(){
      if(!panel)return;
      const title=panel.querySelector('#relationBoardTitle');
      const kindLabel=words.relationLabel(st.kind||(st.read&&st.read.relation.kind)||'');
      const heading=st.kind==='communication'?`Tableau · ${kindLabel}`:kindLabel;
      if(title.dataset.heading!==`${st.kind}|${heading}`){
        const glyph=el('span','rb-glyph');glyph.setAttribute('aria-hidden','true');
        glyph.appendChild(svg(Identity.relationGlyphSvg(st.kind,'')));
        title.replaceChildren(glyph,el('span','',heading));
        title.dataset.heading=`${st.kind}|${heading}`;
      }
      const sig=JSON.stringify([st.relationId,st.phase,st.error?[st.error.code||'',st.error.message||'']:null,st.read&&st.read.relation,
        st.messages.length,st.lastSeq,st.mission,st.missionError?st.missionError.code||'':null,st.more,st.instances.size]);
      if(sig!==bodySig){
        const body=panel.querySelector('#relationBoardBody');
        const keep=focusKey(body);
        body.replaceChildren(...bodyParts());
        bodySig=sig;
        restoreFocus(body,keep);
      }
      renderFoot();
    }
    function focusKey(body){
      const active=doc.activeElement;
      if(!active||!body.contains(active))return null;
      if(active.classList.contains('rb-msg'))return {seq:active.dataset.seq};
      if(active.classList.contains('rb-btn'))return {button:active.dataset.action||''};
      return {other:true};
    }
    function restoreFocus(body,keep){
      if(!keep)return;
      const target=keep.seq?body.querySelector(`.rb-msg[data-seq="${CSS.escape(keep.seq)}"]`)
        :keep.button?body.querySelector(`.rb-btn[data-action="${CSS.escape(keep.button)}"]`):null;
      const fallback=panel.querySelector('#relationBoardTitle');
      if(target){
        for(const item of body.querySelectorAll('.rb-msg'))item.tabIndex=item===target?0:-1;
        target.focus({preventScroll:true});
      }else if(fallback)fallback.focus({preventScroll:true});
    }

    function renderState(){
      const box=panel&&panel.querySelector('[data-rb-state]');
      if(!box||st.phase!=='loading')return;
      const s=Math.max(0,Math.floor((now()-st.startedAt)/1000));
      box.querySelector('.rb-state-text').textContent=`Lecture du tableau… ${s} s (échéance ${Math.round(TIMEOUT_MS/1000)} s)`;
    }

    function bodyParts(){
      if(st.phase==='loading'){
        const box=el('div','rb-state');box.setAttribute('data-rb-state','');
        box.append(el('span','rb-spin'),el('span','rb-state-text',''));
        const parts=[box];
        setTimeout0(renderState);
        return parts;
      }
      if(st.phase==='error')return [errorBox(st.error,true)];
      const r=st.read.relation;
      const parts=[];
      if(st.error)parts.push(errorBox(st.error,false));
      parts.push(summary(r),people(r));
      if(r.kind==='handoff'&&r.handoff)parts.push(packet(r.handoff));
      parts.push(thread(r));
      return parts;
    }
    const setTimeout0=fn=>timers.set(fn,0);

    function errorBox(error,blocking){
      const box=el('div','rb-error');box.setAttribute('role','alert');
      const code=error&&error.code||'relation_board_failed';
      box.append(el('strong','',blocking?'Le tableau n’a pas pu être lu.':'La dernière relecture a échoué ; le fil affiché est celui de la lecture précédente.'),
        el('span','',error&&error.message||String(error)),el('span','',advice(code)),el('span','rb-code',`Code : ${code}`));
      const retry=el('button','rb-btn','Réessayer');retry.type='button';retry.dataset.action='retry';
      retry.addEventListener('click',()=>load({full:!st.read,force:true}));
      box.appendChild(retry);
      return box;
    }

    function summary(r){
      const section=el('section','rb-section');
      section.appendChild(el('h3','','Relation'));
      if(r.purpose)section.appendChild(el('p','rb-purpose',r.purpose));
      const facts=el('dl','rb-facts');
      const add=(term,value,cls)=>{if(!value)return;facts.append(el('dt','',term),el('dd',cls||'',value))};
      add('État',[Identity.label(Identity.STATE_LABELS,r.status),r.outcome?Identity.label(Identity.OUTCOME_LABELS,r.outcome):''].filter(Boolean).join(', '));
      if(r.winner)add('Retenu',personName(r.winner).text);
      add('Conclusion',r.outcomeSummary);
      const m=st.mission;
      if(m){
        add('Mission',m.objective);
        add('Origine',m.origin?originLabel(m.origin):'');
        add('État de la mission',missionStatusLabel(m),m.liveUnknown?'rb-unknown':'');
      }else if(st.missionError){
        add('Mission',`illisible : ${st.missionError.message||st.missionError} (${st.missionError.code||'erreur'})`,'rb-unknown');
      }
      section.appendChild(facts);
      return section;
    }

    function people(r){
      const section=el('section','rb-section');
      section.appendChild(el('h3','',`Participants (${r.participants.length})`));
      const list=el('ul','rb-people');
      for(const part of r.participants){
        const who=personName(part.instanceId);
        const li=el('li','rb-person');
        li.append(ident(who.roleId,who.owner),el('span','rb-person-name',who.text),
          el('span','rb-person-meta',[Identity.label(Identity.POSITION_LABELS,part.position),who.owner?'responsable de la mission':'',
            who.known?workStatusLabel(who.workStatus):''].filter(Boolean).join(' · ')));
        list.appendChild(li);
      }
      section.appendChild(list);
      return section;
    }

    function packet(p){
      const section=el('section','rb-section');
      section.appendChild(el('h3','','Paquet de relais'));
      const facts=el('dl','rb-facts');
      const add=(term,value)=>{const text=Array.isArray(value)?value.filter(v=>typeof v==='string').join(' ; '):str(value);if(text)facts.append(el('dt','',term),el('dd','',text))};
      add('Objectif',p.objective);add('Fait',p.completed_work);add('Prochaine action',p.recommended_next_action);
      add('Décisions',p.key_decisions);add('Points ouverts',p.open_points);add('Artefacts',p.artifact_refs);add('Preuves',p.evidence_refs);
      section.appendChild(facts);
      return section;
    }

    function thread(r){
      const section=el('section','rb-section');
      const heading=el('h3','',`Messages (${st.messages.length})`);heading.id='relationBoardThread';
      section.appendChild(heading);
      if(!st.messages.length){
        section.appendChild(el('p','rb-empty',r.status==='open'
          ?'Aucun message délibéré n’a encore été publié sur cette relation. Le tableau se relit toutes les 5 s.'
          :'Aucun message n’a été publié sur cette relation.'));
        return section;
      }
      const list=el('ol','rb-thread');list.setAttribute('aria-labelledby','relationBoardThread');
      st.focusIndex=Math.min(st.focusIndex,st.messages.length-1);
      st.messages.forEach((m,index)=>{
        const who=personName(m.author);
        const li=el('li','rb-msg');li.tabIndex=index===st.focusIndex?0:-1;li.dataset.seq=String(m.seq);
        const head=el('div','rb-msg-head');
        head.append(ident(who.roleId,who.owner),el('span','rb-msg-type',Identity.label(Identity.MESSAGE_TYPE_LABELS,m.type)),
          el('span','',who.text),el('span','',timeLabel(m.at,now())));
        li.append(head,el('p','rb-msg-text',m.text));
        list.appendChild(li);
      });
      section.appendChild(list);
      if(st.more){
        const more=el('button','rb-btn','Lire les messages suivants');more.type='button';more.dataset.action='more';
        more.addEventListener('click',()=>load({full:false,force:true}));
        section.appendChild(more);
      }
      return section;
    }

    /* Pied posé une fois, mis à jour en place (le bouton garde son focus). */
    function renderFoot(){
      const foot=panel.querySelector('#relationBoardFoot');
      let age=foot.querySelector('.rb-age'),refresh=foot.querySelector('.rb-btn');
      if(!age||!refresh){
        age=el('span','rb-age','');
        refresh=el('button','rb-btn','Actualiser');refresh.type='button';refresh.dataset.action='refresh';
        /* Jamais `disabled` : un bouton désactivé sous le focus le perdrait ; une lecture en vol suffit. */
        refresh.addEventListener('click',()=>{if(!st.inflight)load({full:!st.read,force:true})});
        foot.replaceChildren(age,refresh);
      }
      refresh.setAttribute('aria-disabled',st.inflight?'true':'false');
      age.textContent=st.readAt?`Lu à ${timeLabel(new Date(st.readAt).toISOString(),now())}`
        +(st.read&&st.read.relation.status==='open'?' · relu toutes les 5 s':''):'';
    }

    function onKeyDown(event){
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close({restoreFocus:true});return}
      const item=event.target&&event.target.closest?event.target.closest('.rb-msg'):null;
      if(!item)return;
      const items=[...panel.querySelectorAll('.rb-msg')];
      const index=items.indexOf(item);
      let next=-1;
      if(event.key==='ArrowDown')next=Math.min(items.length-1,index+1);
      else if(event.key==='ArrowUp')next=Math.max(0,index-1);
      else if(event.key==='Home')next=0;
      else if(event.key==='End')next=items.length-1;
      if(next<0)return;
      event.preventDefault();
      items[index].tabIndex=-1;items[next].tabIndex=0;st.focusIndex=next;
      items[next].focus();
    }

    return {open,close,isOpen:()=>st.open,openRelationId:()=>st.open?st.relationId:'',state:st,reload:()=>load({full:true,force:true})};
  }

  let instance=null;
  const api={PANEL_ID,PAGE_LIMIT,TIMEOUT_MS,REFRESH_MS,normalizeRead,normalizeMission,mergeMessages,missionStatusLabel,
    workStatusLabel,timeLabel,advice,create,
    /* Le tableau de la page, créé à la première ouverture. */
    open(request,options){if(!instance)instance=create(options);return instance.open(request)},
    close(options){if(instance)instance.close(options)},
    isOpen:()=>!!instance&&instance.isOpen(),
    openRelationId:()=>instance?instance.openRelationId():'',
    get instance(){return instance}};
  root.JarvisRelationBoard=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
