/* Réglages des sous-agents (jarvis-organic-agent-orchestration, Slice 10 ; sections depuis
   jarvis-settings-ui-reorganization Slice 04).

   Deux vues (`options.view`) : `roles` (défaut, section Agents & modèles › Rôles des sous-agents) et
   `work_methods` (section Avancé & diagnostic › Work Methods apprises : approches observées et promotion).

   Rend le registre des rôles servi par `GET /api/subagent-roles` (`schema_version` 2) : liste des rôles,
   fiche détaillée (mission, capacités, savoirs, Work Methods, ordre de la consigne apposée), et les instances
   en cours lues dans `GET /api/agent/tasks` (champ `role`, le marqueur tel que le hook le lit).

   Écritures : les instructions d'un rôle, par la voie canonique des prompts
   `POST /api/prompts/subagent_role.<id>` (`edit` avec `base_revision` + `expected_effective_revision`,
   ou `reset`) ; et, depuis la Slice 12, la promotion explicite d'un candidat de Work Method
   (`GET /api/work-methods/candidates`, `POST /api/work-methods/promotions`, révision optimiste
   `expected_version`). Tout le reste est en lecture seule et le dit : capacités et méthodes suivent le code.

   Identité visuelle : `visual.icon` / `visual.accent` / `visual.badge` sont des JETONS. L'accent devient la
   variable CSS `--role-accent-<jeton>` (définie dans `control_center.html`, partagée avec le graphe), jamais
   une couleur écrite ici ; l'icône et le badge la doublent toujours, l'identité ne repose pas sur la couleur.

   Échecs : chaque refus est affiché dans la zone concernée (texte et code du serveur) et journalisé en console
   (`console.error('<code>', erreur)`), comme le reste du Control Center ; le serveur journalise de son côté
   `prompt.override.rejected`. Chaque attente porte un compteur et une échéance (`timeoutMs`).
   Point de montage : `#subagentSettingsMount` (créé par la section). Contrat : `docs/subagent-roles.md` § 8. */
(function(root){
  'use strict';
  const MOUNT_ID='subagentSettingsMount';
  const ROLES_PATH='/api/subagent-roles';
  const TASKS_PATH='/api/agent/tasks';
  const PROMPT_PATH=id=>'/api/prompts/'+encodeURIComponent(id);
  const CANDIDATES_PATH='/api/work-methods/candidates';
  const PROMOTIONS_PATH='/api/work-methods/promotions';
  /* Refus après lesquels les candidats sont relus : la vue de l'écran n'est plus celle du serveur. */
  const STALE_CANDIDATE_CODES=new Set(['work_method_revision_conflict','work_method_version_conflict',
    'work_method_candidate_not_eligible','work_method_candidate_unknown']);
  const CANDIDATE_STATUS={candidate:['Candidate','ok'],observing:['En observation',''],
    insufficient_quality:['Issues insuffisantes','bad'],matches_method:['Déjà décrite par la méthode',''],promoted:['Promue','ok']};
  const DEFAULT_TIMEOUT_MS=15000;
  /* Borne d'une surcharge de prompt : lue sur la route (`instructions_max_chars`), sinon cette valeur, qui est
     `prompt_registry.MAX_OVERRIDE_TEXT`. */
  const DEFAULT_MAX_CHARS=8192;
  const UNKNOWN_OUTCOME=new Set(['subagent_settings_timeout','subagent_settings_unreachable']);
  const fmt=n=>String(n).replace(/\B(?=(\d{3})+(?!\d))/g,' ');
  /* Conseil adapté à l'erreur réelle de lecture du registre. */
  function loadAdvice(code){
    if(/^prompt_/.test(code||''))return 'Le document des surcharges de prompts (clé prompt_overrides des réglages) est illisible : corrigez-le ou retirez-le du fichier de réglages, puis réessayez.';
    if(code==='subagent_settings_payload_invalid')return 'La réponse du Control Center n’a pas la forme attendue : la page et le serveur ne sont peut-être pas de la même version. Rechargez la page, puis réessayez.';
    if(code==='subagent_settings_render_failed')return 'L’écran n’a pas pu afficher cette réponse. Rechargez la page ; si l’erreur revient, signalez-la avec le code ci-dessous.';
    return 'Vérifiez que le Control Center répond, puis réessayez.';
  }
  const CONFLICT_CODES=new Set(['prompt_override_concurrent','prompt_override_stale']);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const TOKEN=/^[a-z][a-z0-9-]{0,31}$/;

  /* Pictogrammes dessinés des jetons `visual.icon` : la table partagée avec le graphe des tâches
     (`control_center_role_identity.js`, `window.JarvisRoleIdentity`, Slice 09), jamais une copie. Un jeton inconnu
     prend la silhouette générique : le badge reste lisible à côté. */
  const Identity=root.JarvisRoleIdentity||(typeof require==='function'?require('./control_center_role_identity.js'):null);
  const ICONS=Identity.ICONS;
  const icon=name=>Identity.iconSvg(name,'sar-glyph');

  function logError(code,error,context){try{root.console&&root.console.error(code,error,context||{})}catch(_e){/* intentionnel : la console absente (test node sans console) ne doit pas masquer l'erreur déjà affichée */}}
  function logInfo(code,data){try{root.console&&root.console.info(code,data||{})}catch(_e){/* intentionnel : même argument que logError */}}

  function create(host,options){
    const opts=options||{};
    /* La promotion d'une approche observée est un outil d'opérateur (Avancé), pas une configuration de rôle. */
    const view=opts.view==='work_methods'?'work_methods':'roles';
    const timeoutMs=Number(opts.timeoutMs)>0?Number(opts.timeoutMs):DEFAULT_TIMEOUT_MS;
    const now=typeof opts.now==='function'?opts.now:()=>Date.now();
    const setTimer=opts.setInterval||((fn,ms)=>root.setInterval?root.setInterval(fn,ms):null);
    const clearTimer=opts.clearInterval||(id=>{if(id!=null&&root.clearInterval)root.clearInterval(id)});
    const fetchJson=opts.fetch||(async(path,init)=>{
      const controller=typeof root.AbortController==='function'?new root.AbortController():null;
      const timer=controller&&root.setTimeout?root.setTimeout(()=>controller.abort(),timeoutMs):null;
      let r;
      try{r=await root.fetch(path,{...(init||{}),signal:controller?controller.signal:undefined})}
      catch(e){
        if(e&&e.name==='AbortError'){const t=new Error(`Pas de réponse du Control Center après ${Math.round(timeoutMs/1000)} s.`);t.code='subagent_settings_timeout';throw t}
        const t=new Error('Control Center injoignable : '+(e&&e.message||e));t.code='subagent_settings_unreachable';throw t;
      }finally{if(timer!=null&&root.clearTimeout)root.clearTimeout(timer)}
      const text=await r.text();let body={};try{body=text?JSON.parse(text):{}}catch{body={error:text}}
      if(!r.ok||body.ok===false){
        const envelope=body&&typeof body.error==='object'&&body.error?body.error:null;
        const e=new Error((envelope&&envelope.message)||(typeof body.error==='string'&&body.error)||body.message||('HTTP '+r.status));
        e.status=r.status;e.code=(r.headers&&r.headers.get&&r.headers.get('X-Jarvis-Error-Code'))||(envelope&&envelope.code)||body.code||'';throw e;
      }
      return body;
    });

    const st={
      phase:'loading',error:null,payload:null,selected:null,
      /* Brouillons partageables avec la page (`options.drafts`) : changer d'onglet ne perd pas un texte non enregistré. */
      drafts:opts.drafts&&typeof opts.drafts==='object'?opts.drafts:{},openEditor:{},confirmReset:null,
      save:null,                 // {id, action, startedAt}
      notice:{},                 // id -> {tone,text,code}
      tasks:{phase:'loading',error:null,items:[]},instancesOpen:false,
      /* Slice 12 : candidats de Work Method (lecture indépendante) et promotion en cours / à confirmer. */
      learned:{phase:'loading',error:null,items:[],thresholds:{},startedAt:now()},
      promote:null,confirmPromote:null,promoteNotice:null,
      startedAt:now(),destroyed:false,
    };
    let ticker=null;
    const warnedAccent=new Set();

    /* --- lecture du registre ------------------------------------------- */
    /* Une charge utile partielle (autre version, champ retiré) ne doit jamais figer l'écran : chaque rôle est
       ramené à une forme sûre, les champs absents s'affichent vides et la fiche dit lesquels manquent. */
    const EXPECTED=['name','marker','description','mission','instructions','default_instructions','default_revision',
      'revision','visual','tools','work_methods','enabled','can_spawn','can_own_mission','offered_to_brain','offered_to_subagents'];
    function normalizeRole(r){
      const str=v=>v==null?'':String(v),list=v=>Array.isArray(v)?v.map(str):[];
      const visual=r.visual&&typeof r.visual==='object'?r.visual:{};
      return {...r,id:str(r.id),name:str(r.name)||str(r.id),marker:str(r.marker)||str(r.id),description:str(r.description),
        mission:str(r.mission),when_relevant:str(r.when_relevant),instructions:str(r.instructions),
        default_profile:str(r.default_profile)||'general',prompt_id:str(r.prompt_id)||'subagent_role.'+str(r.id),
        visual:{icon:str(visual.icon),accent:str(visual.accent),badge:str(visual.badge)},
        tools:list(r.tools),skills:list(r.skills),aliases:list(r.aliases),work_methods:list(r.work_methods),
        default_work_method:r.default_work_method?str(r.default_work_method):null,loadout_role:r.loadout_role?str(r.loadout_role):null,
        enabled:r.enabled!==false,can_spawn:r.can_spawn===true,can_own_mission:r.can_own_mission===true,
        offered_to_brain:r.offered_to_brain===true,offered_to_subagents:r.offered_to_subagents===true,
        constrained_output:r.constrained_output===true,modified:r.modified===true,conflict:r.conflict?str(r.conflict):null,
        missing:EXPECTED.filter(k=>!Object.prototype.hasOwnProperty.call(r,k))};
    }
    function normalizePayload(data){
      const raw=data.roles.filter(r=>r&&typeof r==='object'&&typeof r.id==='string'&&r.id.trim());
      const obj=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:{};
      return {...data,roles:raw.map(normalizeRole),dropped:data.roles.length-raw.length,
        work_methods:Array.isArray(data.work_methods)?data.work_methods.filter(m=>m&&typeof m==='object'):[],
        aliases:obj(data.aliases),relation_labels:obj(data.relation_labels),accents:Array.isArray(data.accents)?data.accents:[],
        instructions_max_chars:Number(data.instructions_max_chars)>0?Number(data.instructions_max_chars):DEFAULT_MAX_CHARS};
    }
    const roles=()=>(st.payload&&st.payload.roles)||[];
    const maxChars=()=>(st.payload&&st.payload.instructions_max_chars)||DEFAULT_MAX_CHARS;
    const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
    const roleById=id=>roles().find(r=>r.id===id)||null;
    const methodById=id=>((st.payload&&st.payload.work_methods)||[]).find(m=>m.method_id===id)||null;
    const relationLabel=k=>((st.payload&&st.payload.relation_labels)||{})[k]||k;
    function accentOf(role){
      const token=role&&role.visual&&role.visual.accent;
      const known=(st.payload&&st.payload.accents)||[];
      if(TOKEN.test(String(token||''))&&known.includes(token))return token;
      if(role&&!warnedAccent.has(role.id)){warnedAccent.add(role.id);logError('subagent_settings_unknown_accent',new Error(`jeton d'accent inconnu : ${token}`),{role_id:role.id})}
      return 'slate';
    }
    const accentStyle=token=>`--sar-accent:var(--role-accent-${token})`;
    const draftOf=role=>Object.prototype.hasOwnProperty.call(st.drafts,role.id)?st.drafts[role.id]:role.instructions;
    const isDirty=role=>Object.prototype.hasOwnProperty.call(st.drafts,role.id)&&st.drafts[role.id]!==role.instructions;

    /* Le marqueur d'une instance (`role` de `/api/agent/tasks`) résolu comme `subagent_roles.resolve_role`. */
    function resolveMarker(marker){
      const m=String(marker??'').trim().toLowerCase();
      if(!m)return {status:'undeclared',role:null,marker:''};
      const aliases=(st.payload&&st.payload.aliases)||{};
      const direct=roles().find(r=>(r.marker||r.id)===m);
      if(direct)return {status:direct.enabled?'declared':'disabled',role:direct,roleId:direct.id,marker:m};
      /* Comme `resolve_role` : un alias reste `alias` même si sa cible manque à la liste servie (la cible fait foi).
         Clé propre seulement : `constructor` n'est pas un alias. */
      if(own(aliases,m)&&typeof aliases[m]==='string')return {status:'alias',role:roleById(aliases[m]),roleId:aliases[m],marker:m};
      return {status:'unknown',role:null,roleId:'unknown',marker:m.slice(0,24)};
    }

    /* --- rendu ----------------------------------------------------------- */
    function elapsed(since){return Math.max(0,Math.floor((now()-since)/1000))}
    function waitingHtml(label,since){
      return `<div class="sar-wait" role="status"><span class="sar-spin" aria-hidden="true"></span><span>${esc(label)}</span>
        <span class="sar-elapsed" data-sar-since="${since}">${elapsed(since)} s</span><span class="hint">abandon après ${Math.round(timeoutMs/1000)} s</span></div>`;
    }
    function codeLine(code){return code?`<div class="hint sar-code">Code : <code>${esc(code)}</code></div>`:''}
    function chip(text,tone,title){return `<span class="tag${tone?' '+tone:''}"${title?` title="${esc(title)}"`:''}>${esc(text)}</span>`}
    function identity(role,size){
      const token=accentOf(role),v=role.visual||{};
      return `<span class="sar-ident sar-${size}" style="${accentStyle(token)}"><span class="sar-tile">${icon(v.icon)}</span><span class="sar-badge">${esc(v.badge||'?')}</span></span>`;
    }
    function availability(role){
      if(!role.enabled)return chip('Désactivé','bad','Le hook ne reconnaît pas ce rôle : son marqueur reste dans le libellé.');
      return '';
    }
    function listItem(role){
      const sel=role.id===st.selected;
      const tags=[availability(role),role.modified?chip('modifié','warn'):'',isDirty(role)?chip('non enregistré','warn'):'',role.conflict?chip('surcharge écartée','bad'):''].join('');
      return `<li><button type="button" class="sar-item${sel?' selected':''}${role.enabled?'':' off'}" data-sar-role="${esc(role.id)}" aria-current="${sel?'true':'false'}" tabindex="${sel?'0':'-1'}">
        ${identity(role,'sm')}<span class="sar-item-text"><span class="sar-item-name">${esc(role.name)}</span><span class="sar-item-meta"><code>[${esc(role.marker||role.id)}]</code>${tags}</span></span></button></li>`;
    }
    function yesNo(value,yes,no){return `<span class="sar-yn ${value?'yes':'no'}">${esc(value?yes:no)}</span>`}
    function facts(rows){return `<dl class="sar-facts">${rows.filter(Boolean).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`}

    function methodHtml(id,isDefault){
      const m=methodById(id);
      if(!m)return `<li class="sar-method missing"><span class="tag bad">méthode introuvable</span> <code>${esc(id)}</code></li>`;
      const list=(title,items)=>Array.isArray(items)&&items.length?`<div class="sar-mlist"><span class="sar-mlabel">${esc(title)}</span><ul>${items.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`:'';
      const rels=Array.isArray(m.useful_relations)?m.useful_relations:[];
      const rel=rels.length?`<div class="sar-mlist"><span class="sar-mlabel">Relations à envisager</span><p>${rels.map(k=>esc(relationLabel(k))).join(', ')}</p></div>`:'';
      return `<li class="sar-method${isDefault?' default':''}"><details><summary><span class="sar-mname">${esc(m.name)}</span>${isDefault?chip('par défaut, apposée','ok'):chip('suggestion')}${m.provenance&&m.provenance.origin==='promoted'?chip('version promue','ok','Promue par une personne depuis un candidat ; c’est la version que JARVIS appose.'):''}<code class="sar-mkey">${esc(m.method_id)}@${esc(m.version)}</code></summary>
        <p class="sar-msummary">${esc(m.summary)}</p>${list('Principes',m.principles)}${list('Critères de qualité',m.quality_checks)}${rel}
        <p class="hint">Des réflexes, pas des étapes : l'agent organise son travail selon ce qu'il découvre.</p></details></li>`;
    }

    /* --- candidats de Work Method (Slice 12) ------------------------------ */
    function candidateReason(c,t){
      const n=v=>Number(v)||0;
      switch(c.reason){
        case 'not_enough_uses':return `Revenue ${n(c.uses)} fois sur ${n(t.min_uses)||3} requises.`;
        case 'not_enough_quality_evidence':return `${n(c.positive)} bonne(s) issue(s) prouvée(s) sur ${n(t.min_positive)||2} requises ; une mission terminée sans verdict QA ne compte pas.`;
        case 'positive_share_below_threshold':return `Trop d’issues mauvaises : ${n(c.positive)} bonne(s) pour ${n(c.negative)} mauvaise(s). Elle ne sera pas proposée.`;
        case 'nothing_beyond_the_method':return 'Elle n’ajoute rien à la méthode apposée : rien à apprendre.';
        case 'thresholds_met':return 'Seuils atteints : la promotion est possible, par vous seulement.';
        case 'already_promoted':return 'Déjà promue : '+(Array.isArray(c.promoted_keys)?c.promoted_keys.join(', '):'');
        default:return String(c.reason||'');
      }
    }
    function candidateHtml(c,t){
      const [label,tone]=CANDIDATE_STATUS[c.status]||[String(c.status||'?'),''];
      const kinds=Array.isArray(c.relation_kinds)&&c.relation_kinds.length?c.relation_kinds.map(k=>esc(relationLabel(k))).join(', '):'aucune relation';
      const draft=c.draft&&typeof c.draft==='object'?c.draft:null;
      const key=draft?`${draft.method_id}@${draft.version}`:'';
      const busy=!!st.promote,mine=st.promote&&st.promote.candidateId===c.candidate_id,confirming=st.confirmPromote===c.candidate_id;
      let action='';
      if(c.status==='candidate'&&draft){
        action=`<div class="sar-actions"><button type="button" class="action${confirming?' primary':''}" data-sar-promote="${esc(c.candidate_id)}"${busy?' disabled':''}>${confirming?'Confirmer la promotion':'Promouvoir en '+esc(key)}</button>
          ${confirming?`<button type="button" class="action" data-sar-promote-cancel>Annuler</button>`:''}</div>
          ${confirming?`<div class="sar-mlist" data-sar-promote-preview><p class="hint">La version <code>${esc(key)}</code> sera publiée telle quelle ; <code>${esc(c.base_method_key||'')}</code> reste, rien n’est réécrit. Elle sera apposée aux prochains sous-agents des rôles qui citent cette méthode.</p>
            <span class="sar-mlabel">Principes publiés</span><ul>${(draft.principles||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>
            ${(draft.quality_checks||[]).length?`<span class="sar-mlabel">Critères de qualité publiés</span><ul>${draft.quality_checks.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:''}
            <span class="sar-mlabel">Relations à envisager publiées</span><p>${esc((draft.useful_relations||[]).map(relationLabel).join(', ')||'aucune')}</p></div>`:''}`;
      }else if(c.status==='candidate'){
        action='<p class="hint">Aucune méthode de base : la promotion demande d’écrire un nom, un résumé et des principes, ce que cet écran ne fait pas encore.</p>';
      }
      return `<li class="sar-method" data-sar-candidate="${esc(c.candidate_id)}"><div><span class="sar-mname">${c.method_id?`Avec <code>${esc(c.method_id)}</code>`:'Sans méthode'} · relations : ${kinds}</span> ${chip(label,tone)}</div>
        <p class="hint">${esc(candidateReason(c,t))}</p>
        <p class="hint">${Number(c.uses)||0} mission(s) close(s) · ${Number(c.positive)||0} bonne(s) · ${Number(c.negative)||0} mauvaise(s) · ${Number(c.unrated)||0} non notée(s) · ${(c.evidence_refs||[]).length} preuve(s)</p>
        ${mine?waitingHtml('Promotion en cours…',st.promote.startedAt):''}${action}</li>`;
    }
    /* Vue `work_methods` : une seule lecture des candidats, un bloc par rôle qui peut porter une mission. */
    function learnedRoleHtml(role){
      const t=st.learned.thresholds||{},mine=st.learned.items.filter(c=>c&&c.role_id===role.id);
      return `<section class="sar-block" style="${accentStyle(accentOf(role))}" aria-labelledby="sar-learned-${esc(role.id)}" data-sar-learned-role="${esc(role.id)}">
        <h4 id="sar-learned-${esc(role.id)}">${identity(role,'sm')}<span>${esc(role.name)}</span></h4>
        ${mine.length?`<ul class="sar-methods">${mine.map(c=>candidateHtml(c,t)).join('')}</ul>`:'<p class="hint">Aucune mission close de ce rôle dans l’historique récent.</p>'}</section>`;
    }
    function learnedHtml(){
      const l=st.learned,t=l.thresholds||{},owners=roles().filter(r=>r.can_own_mission);
      let body;
      if(l.phase==='loading')body=waitingHtml('Lecture des approches observées…',l.startedAt||st.startedAt);
      else if(l.phase==='error')body=`<div class="notice bad">Approches observées illisibles : ${esc(l.error&&l.error.message)}${codeLine(l.error&&l.error.code)}</div><div class="sar-actions"><button type="button" class="action" data-sar-learned-retry>Réessayer</button></div>`;
      else{
        const partial=l.scan&&l.scan.partial?'<div class="notice">Lecture partielle : une partie de l’historique est illisible et a été écartée (voir le journal des erreurs).</div>':'';
        body=partial+(owners.length?owners.map(learnedRoleHtml).join(''):'<p class="hint">Aucun rôle ne peut porter de mission : rien à apprendre.</p>');
      }
      const n=st.promoteNotice;
      const notice=n?`<div class="notice ${n.tone==='bad'?'bad':'ok'}" data-sar-promote-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}</div>`:'';
      return `<div class="sar sar-wm" data-subagent-work-methods="1">
        <p class="hint">Approches observées ${chip('apprentissage explicite')} : tirées des missions closes, une approche qui revient (${Number(t.min_uses)||3} fois) avec de bonnes issues prouvées par un verdict QA devient candidate. Rien n’est promu sans vous.</p>
        ${notice}${body}</div>`;
    }

    function compositionHtml(role){
      const m=role.default_work_method?methodById(role.default_work_method):null;
      return `<ol class="sar-compose" aria-label="Ordre de la consigne apposée par JARVIS">
        <li><span class="sar-step">Vos instructions</span>${chip('modifiable','ok')}<span class="hint">Le texte ci-dessous, ou le défaut du code s'il n'est pas modifié.</span></li>
        <li><span class="sar-step">Capacités du rôle</span>${chip('générées')}<span class="hint">${role.can_spawn?'Peut lancer des agents, avec la liste des rôles qu’il peut demander.':'« Vous ne lancez aucun autre agent », prioritaire sur la charte du chantier.'}</span></li>
        <li><span class="sar-step">Work Method par défaut</span>${m?chip('non modifiable'):chip('aucune')}<span class="hint">${m?`« ${esc(m.name)} » s’ajoute <strong>après</strong> vos instructions et suit le code : la modifier ici est impossible.`:'Ce rôle n’a pas de méthode par défaut : ses instructions sont sa méthode.'}</span></li></ol>`;
    }

    function countText(role,text,dirty){
      const n=text.length,max=maxChars();
      return `(${fmt(n)} / ${fmt(max)} caractères${n>max?', au-delà de la limite':''}${dirty?', non enregistré':''})`;
    }
    function canSave(role,text){return !!(role.default_revision&&role.revision)&&text.length<=maxChars()}
    function noticeHtml(id){
      const n=st.notice[id];if(!n)return '';
      const reread=n.reread?`<div class="sar-actions"><button type="button" class="action" data-sar-reread="${esc(id)}"${st.save?' disabled':''}>Réessayer la relecture</button></div>`:'';
      return `<div class="notice ${n.tone==='bad'?'bad':n.tone==='ok'?'ok':''}" data-sar-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}${reread}</div>`;
    }
    function editorHtml(role){
      const id=role.id,saving=st.save&&st.save.id===id,dirty=isDirty(role),text=String(draftOf(role)??'');
      const conflict=role.conflict?`<div class="notice bad">Votre surcharge enregistrée est écartée (<code>${esc(role.conflict)}</code>) : le défaut du code s'applique. Enregistrez à nouveau pour la reprendre sur le nouveau défaut.</div>`:'';
      const noRevision=!(role.default_revision&&role.revision)?'<div class="notice">Révisions absentes de la réponse : l’enregistrement est désactivé pour ne rien écraser à l’aveugle.</div>':'';
      const confirming=st.confirmReset===id;
      const busy=!!st.save;
      const area=`textarea-${id}`;
      return `<section class="sar-block" aria-labelledby="sar-instr-${esc(id)}"><h4 id="sar-instr-${esc(id)}">Instructions ${role.modified?chip('modifiées','warn'):chip('défaut du code')}</h4>
        ${conflict}
        <details class="rd sar-editor" data-sar-editor="${esc(id)}"${st.openEditor[id]||dirty||st.notice[id]?' open':''}>
          <summary>Afficher et modifier les instructions <span class="hint" data-sar-count>${countText(role,text,dirty)}</span></summary>
          <label class="sar-label" for="${esc(area)}">Instructions du rôle ${esc(role.name)}</label>
          <textarea id="${esc(area)}" data-sar-text="${esc(id)}" spellcheck="true" rows="14" aria-describedby="${esc(area)}-h"${saving?' readonly':''}>${esc(text)}</textarea>
          <div class="hint" id="${esc(area)}-h">Au plus ${fmt(maxChars())} caractères. Enregistré dans la couche de prompt <code>${esc(role.prompt_id)}</code>. S'applique au prochain sous-agent lancé avec ce rôle ; aucun agent en cours n'est modifié.</div>
          ${noRevision}
          ${saving?waitingHtml(st.save.action==='reset'?'Retour au défaut…':st.save.action==='reread'?'Relecture de la version enregistrée…':'Enregistrement des instructions…',st.save.startedAt):''}
          ${noticeHtml(id)}
          <div class="sar-actions">
            <button type="button" class="action primary" data-sar-save="${esc(id)}"${dirty&&!busy&&canSave(role,text)?'':' disabled'}>${saving&&st.save.action==='edit'?'Enregistrement…':'Enregistrer les instructions'}</button>
            <button type="button" class="action" data-sar-discard="${esc(id)}"${dirty&&!busy?'':' disabled'}>Annuler mes changements</button>
            <button type="button" class="action danger" data-sar-reset="${esc(id)}"${role.modified&&!busy?'':' disabled'}${confirming?' aria-describedby="sar-reset-h"':''}>${confirming?'Confirmer le retour au défaut':'Revenir au défaut'}</button>
            ${confirming?'<span class="hint" id="sar-reset-h">Votre texte enregistré sera remplacé par le défaut du code.</span>':''}
          </div>
        </details></section>`;
    }

    function detailHtml(role){
      if(!role)return '<div class="empty">Choisissez un rôle dans la liste.</div>';
      const token=accentOf(role);
      const marker=`[${role.default_profile||'general'}] [${role.marker||role.id}]`;
      const aliases=(role.aliases||[]).length?(role.aliases||[]).map(a=>`<code>[${esc(a)}]</code>`).join(' ')+' <span class="hint">alias historique, lu comme ce rôle</span>':'<span class="hint">aucun</span>';
      const tools=(role.tools||[]).length?(role.tools||[]).map(t=>`<code class="sar-tool">${esc(t)}</code>`).join(' '):'<span class="hint">aucun outil déclaré</span>';
      const skills=(role.skills||[]).length?(role.skills||[]).map(s=>`<code>${esc(s)}</code>`).join(' '):'<span class="hint">aucun skill propre</span>';
      const loadout=role.loadout_role?`loadout <code>${esc(role.loadout_role)}</code>`:'<span class="hint">celui du profil</span>';
      const methods=(role.work_methods||[]);
      const ordered=[...methods].sort((a,b)=>(b===role.default_work_method)-(a===role.default_work_method));
      const state=!role.enabled
        ?`<div class="notice bad"><strong>Rôle désactivé.</strong> Le hook ne le reconnaît pas : un sous-agent qui l'annonce garde le marqueur dans son libellé et suit seulement sa consigne.</div>`
        :(!role.offered_to_brain?`<div class="notice info">Actif pour le hook, mais <strong>pas encore proposé au cerveau</strong> : seul un agent qui lance des agents peut le demander.</div>`:'');
      const missing=role.missing&&role.missing.length?`<div class="notice">Fiche incomplète : la réponse du serveur ne donne pas ${role.missing.map(k=>`<code>${esc(k)}</code>`).join(', ')}. Ces champs s'affichent vides.</div>`:'';
      return `<article class="sar-detail" style="${accentStyle(token)}" aria-labelledby="sar-title">
        <button type="button" class="action sar-back" data-sar-back>Revenir à la liste des rôles</button>
        <header class="sar-head">${identity(role,'lg')}<div><h3 id="sar-title" class="sar-title" tabindex="-1">${esc(role.name)}</h3>
          <p class="sar-desc">${esc(role.description||'')}</p>
          <div class="sar-tags">${role.enabled?chip('Actif','ok'):chip('Désactivé','bad')}${role.offered_to_brain?chip('Proposé au cerveau','ok'):chip('Pas proposé au cerveau')}${role.offered_to_subagents?chip('Proposé aux agents','ok'):chip('Pas proposé aux agents')}</div></div></header>
        ${state}${missing}
        <section class="sar-block" aria-labelledby="sar-mission"><h4 id="sar-mission">Mission</h4><p class="sar-prose">${esc(role.mission||'')}</p>
          ${role.when_relevant?`<p class="hint"><strong>Quand l'employer :</strong> ${esc(role.when_relevant)}</p>`:''}
          ${facts([['Marqueur',`<code>${esc(marker)}</code>`],['Alias',aliases],['Identifiant',`<code>${esc(role.id)}</code>`]])}</section>
        <section class="sar-block" aria-labelledby="sar-caps"><h4 id="sar-caps">Capacités ${chip('lecture seule')}</h4>
          ${facts([
            ['Lance des agents',yesNo(role.can_spawn,'Oui','Non')],
            ['Mission Owner',yesNo(role.can_own_mission,'Peut porter une mission','Ne porte pas de mission')],
            ['Réponse',role.constrained_output?'<span class="sar-yn yes">Forme imposée par ses instructions</span>':'<span class="sar-yn no">Libre</span>'],
            ['Outils',tools],['Savoirs',loadout],['Skills',skills],['Profil par défaut',`<code>${esc(role.default_profile||'general')}</code>`],
          ])}
          <p class="hint">Ces capacités suivent le code du registre ; aucun réglage ne les modifie.</p></section>
        <section class="sar-block" aria-labelledby="sar-methods"><h4 id="sar-methods">Work Methods ${chip('lecture seule')}</h4>
          ${methods.length?`<ul class="sar-methods">${ordered.map(id=>methodHtml(id,id===role.default_work_method)).join('')}</ul>`:'<p class="hint">Aucune Work Method : les instructions du rôle tiennent lieu de méthode.</p>'}
          ${methods.length&&!role.default_work_method?'<p class="hint">Aucune n’est apposée par défaut ; un Mission Owner pourra en choisir une.</p>':''}</section>
        ${role.can_own_mission?`<p class="hint" data-sar-learned-link>Approches observées de ce rôle et promotion en Work Method : ${opts.openTab?'<button type="button" class="sar-link" data-sar-open-learned>Avancé &amp; diagnostic › Work Methods apprises</button>':'Avancé &amp; diagnostic › Work Methods apprises'}.</p>`:''}
        <section class="sar-block" aria-labelledby="sar-compose"><h4 id="sar-compose">Consigne transmise au sous-agent</h4>${compositionHtml(role)}</section>
        ${editorHtml(role)}
      </article>`;
    }

    function instanceRow(task){
      const res=resolveMarker(task.role);
      const title=String(task.description||'').replace(/^(\s*\[[^\]]{1,40}\]\s*)+/,'')||'(sans libellé)';
      let ident,label;
      const generic=(glyph,badge)=>`<span class="sar-ident sar-sm" style="${accentStyle('slate')}"><span class="sar-tile">${icon(glyph)}</span><span class="sar-badge">${badge}</span></span>`;
      if(res.role){ident=identity(res.role,'sm');label=esc(res.role.name)+(res.status==='alias'?` <span class="hint">via l'alias <code>[${esc(res.marker)}]</code></span>`:'')+(res.status==='disabled'?' '+chip('désactivé','bad'):'')}
      else if(res.status==='alias'){ident=generic('agent','?');label=`Alias <code>[${esc(res.marker)}]</code> du rôle <code>${esc(res.roleId)}</code> <span class="hint">absent de la liste servie</span>`}
      else if(res.status==='unknown'){ident=generic('unknown','?');label=`Marqueur hors registre <code>[${esc(res.marker)}]</code>`}
      else{ident=generic('agent','GEN');label='Général, <span class="hint">aucun rôle déclaré</span>'}
      return `<li class="sar-inst">${ident}<span class="sar-item-text"><span class="sar-item-name">${esc(title)}</span><span class="sar-item-meta">${label}${task.ephemeral?chip('éphémère'):''}</span></span></li>`;
    }
    function instancesHtml(){
      const t=st.tasks;
      const running=t.phase==='ready'?t.items.filter(x=>x&&x.status==='running'&&x.kind!=='shell'):[];
      let body,count;
      if(t.phase==='loading'){body=waitingHtml('Lecture des instances…',t.startedAt||st.startedAt);count='lecture…'}
      else if(t.phase==='error'){body=`<div class="notice bad">Instances illisibles : ${esc(t.error.message)}${codeLine(t.error.code)}</div>`;count='illisibles'}
      else{
        count=String(running.length);
        body=running.length?`<ul class="sar-list" aria-label="Instances en cours">${running.map(instanceRow).join('')}</ul>`:'<p class="hint">Aucun sous-agent en cours.</p>';
      }
      return `<details class="sar-instances" data-sar-instances${st.instancesOpen?' open':''}><summary>Instances en cours <span class="tag${t.phase==='error'?' bad':''}">${esc(count)}</span></summary>
        ${body}<div class="sar-actions"><button type="button" class="action" data-sar-tasks-refresh${t.phase==='loading'?' disabled':''}>Actualiser</button></div></details>`;
    }
    function summaryHtml(){
      const all=roles(),active=all.filter(r=>r.enabled).length,brain=all.filter(r=>r.enabled&&r.offered_to_brain).length,mod=all.filter(r=>r.modified).length;
      const schema=st.payload.schema_version!==2?`<div class="notice">Version du registre inattendue (<code>${esc(st.payload.schema_version??'absente')}</code>, cet écran lit la version 2) : les champs absents s'affichent vides.</div>`:'';
      const dropped=st.payload.dropped?`<div class="notice">${st.payload.dropped} entrée(s) sans identifiant ignorée(s).</div>`:'';
      return `${schema}${dropped}<p class="sar-summary">${all.length} rôles · ${active} actifs · ${brain} proposés au cerveau${mod?` · ${mod} aux instructions modifiées`:''}</p>`;
    }

    /* Chaque rendu remplace l'hôte (lecture des instances, compteur, enregistrement) : le contrôle qui avait le focus
       le reprend (`keepFocus` du shell), sinon il tomberait sur `body` — par exemple le lien vers Modèles des
       sous-agents, redessiné quand les instances arrivent (finitions avant la Slice 10). */
    function render(){
      const UI=root.JarvisSettingsUI;
      if(UI&&typeof UI.keepFocus==='function'&&host.ownerDocument)UI.keepFocus(host,draw);else draw();
    }
    function draw(){
      if(st.destroyed)return;
      if(st.phase==='loading'){host.innerHTML=`<div class="sar-state">${waitingHtml('Lecture du registre des rôles…',st.startedAt)}</div>`;tick();return}
      if(st.phase==='error'){
        host.innerHTML=`<div class="sar-state"><div class="notice bad" role="alert"><strong>Registre des rôles illisible.</strong> Réponse : « ${esc(st.error.message)} ».
          <div class="hint">Rien n'a été modifié. ${esc(loadAdvice(st.error.code))}</div>${codeLine(st.error.code)}</div>
          <button type="button" class="action primary" data-sar-retry>Réessayer</button></div>`;
        bind();tick();return;
      }
      try{renderReady()}
      catch(e){
        /* Une réponse que l'écran ne sait pas afficher devient une erreur visible, jamais un écran figé. */
        const err=new Error('affichage impossible : '+(e&&e.message||e));err.code='subagent_settings_render_failed';
        logError('subagent_settings_render_failed',e,{schema_version:st.payload&&st.payload.schema_version});
        st.phase='error';st.error=err;render();
      }
    }
    function renderReady(){
      if(view==='work_methods'){host.innerHTML=learnedHtml();bind();tick();return}
      if(!roles().length){
        host.innerHTML=`<div class="sar-state">${summaryHtml()}<div class="notice bad" role="status"><strong>Aucun rôle dans le registre.</strong> Les sous-agents s'exécutent alors sans rôle, comme agents généraux.</div></div>`;
        tick();return;
      }
      if(!roleById(st.selected))st.selected=roles()[0].id;
      const scrollEl=host.querySelector('.sar-detail-pane'),scroll=scrollEl?scrollEl.scrollTop:0;
      host.innerHTML=`<div class="sar" data-subagent-settings="1">
        <div class="sar-side">${summaryHtml()}
          <ul class="sar-list" role="list" aria-label="Rôles de sous-agent" data-sar-list>${roles().map(listItem).join('')}</ul>
          <p class="hint">Flèches haut et bas pour parcourir les rôles.</p>
          ${instancesHtml()}
          <p class="hint sar-models">Les modèles des sous-agents se règlent dans ${opts.openTab?'<button type="button" class="sar-link" data-sar-open-models>Agents &amp; modèles › Modèles des sous-agents</button>':'Agents &amp; modèles › Modèles des sous-agents'}.</p></div>
        <div class="sar-detail-pane" role="region" aria-label="Fiche du rôle">${detailHtml(roleById(st.selected))}</div></div>`;
      const pane=host.querySelector('.sar-detail-pane');if(pane&&scroll)pane.scrollTop=scroll;
      bind();tick();
    }

    /* Compteur vivant des attentes : un seul minuteur, arrêté dès qu'aucune attente n'est affichée. */
    function tick(){
      const waiting=!st.destroyed&&(st.phase==='loading'||(view==='roles'?st.tasks.phase==='loading'||!!st.save:st.learned.phase==='loading'||!!st.promote));
      if(waiting&&ticker==null)ticker=setTimer(()=>{
        if(!host.querySelectorAll)return;
        host.querySelectorAll('[data-sar-since]').forEach(el=>{el.textContent=elapsed(Number(el.dataset.sarSince))+' s'});
      },1000);
      if(!waiting&&ticker!=null){clearTimer(ticker);ticker=null}
    }

    const oneColumn=()=>!!(root.matchMedia&&root.matchMedia('(max-width: 900px)').matches);
    function select(id,focus){
      if(!roleById(id))return;
      st.selected=id;st.confirmReset=null;st.confirmPromote=null;render();
      if(focus==='detail'&&oneColumn()){
        const title=host.querySelector('#sar-title'),card=host.querySelector('.sar-detail');
        if(card&&card.scrollIntoView)card.scrollIntoView({block:'start'});
        if(title&&title.focus)title.focus({preventScroll:true});
        return;
      }
      if(focus){const b=host.querySelector(`[data-sar-role="${id}"]`);if(b&&b.focus)b.focus()}
    }
    /* Région live courte, hors du rendu : seules les notices y sont annoncées, jamais la fiche entière. */
    const live=(()=>{
      const doc=host.ownerDocument;
      if(!doc||!host.insertAdjacentElement)return null;
      const el=doc.createElement('div');el.className='sar-live';el.setAttribute('aria-live','polite');el.setAttribute('data-sar-live','');
      host.insertAdjacentElement('beforebegin',el);return el;
    })();
    function announce(text){if(live){live.textContent='';live.textContent=text||''}}

    function bind(){
      if(!host.querySelectorAll)return;
      const retry=host.querySelector('[data-sar-retry]');if(retry)retry.addEventListener('click',()=>load());
      host.querySelectorAll('[data-sar-role]').forEach(b=>{
        b.addEventListener('click',()=>select(b.dataset.sarRole,'detail'));
        b.addEventListener('keydown',ev=>{
          const ids=roles().map(r=>r.id),i=ids.indexOf(b.dataset.sarRole);
          const next={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:ids.length-1}[ev.key];
          if(next===undefined)return;
          ev.preventDefault();select(ids[(next+ids.length)%ids.length],true);
        });
      });
      host.querySelectorAll('[data-sar-editor]').forEach(d=>d.addEventListener('toggle',()=>{st.openEditor[d.dataset.sarEditor]=d.open}));
      host.querySelectorAll('[data-sar-text]').forEach(area=>area.addEventListener('input',()=>{
        const role=roleById(area.dataset.sarText);if(!role)return;
        st.drafts[role.id]=area.value;
        const dirty=isDirty(role),busy=!!st.save;
        const count=host.querySelector('[data-sar-count]');if(count)count.textContent=countText(role,area.value,dirty);
        const save=host.querySelector(`[data-sar-save="${role.id}"]`),discard=host.querySelector(`[data-sar-discard="${role.id}"]`);
        if(save)save.disabled=!dirty||busy||!canSave(role,area.value);if(discard)discard.disabled=!dirty||busy;
      }));
      host.querySelectorAll('[data-sar-save]').forEach(b=>b.addEventListener('click',()=>save(b.dataset.sarSave)));
      host.querySelectorAll('[data-sar-discard]').forEach(b=>b.addEventListener('click',()=>{delete st.drafts[b.dataset.sarDiscard];delete st.notice[b.dataset.sarDiscard];render()}));
      host.querySelectorAll('[data-sar-reset]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarReset;
        if(st.confirmReset!==id){st.confirmReset=id;render();const again=host.querySelector(`[data-sar-reset="${id}"]`);if(again&&again.focus)again.focus();return}
        reset(id);
      }));
      const refresh=host.querySelector('[data-sar-tasks-refresh]');if(refresh)refresh.addEventListener('click',()=>loadTasks());
      const inst=host.querySelector('[data-sar-instances]');if(inst)inst.addEventListener('toggle',()=>{st.instancesOpen=inst.open});
      host.querySelectorAll('[data-sar-reread]').forEach(b=>b.addEventListener('click',()=>reread(b.dataset.sarReread)));
      const back=host.querySelector('[data-sar-back]');if(back)back.addEventListener('click',()=>{const b=host.querySelector(`[data-sar-role="${st.selected}"]`);if(b){if(b.scrollIntoView)b.scrollIntoView({block:'center'});b.focus()}});
      const models=host.querySelector('[data-sar-open-models]');if(models)models.addEventListener('click',()=>opts.openTab('subagent_models'));
      const learned=host.querySelector('[data-sar-open-learned]');if(learned)learned.addEventListener('click',()=>opts.openTab('work_methods'));
      const learnedRetry=host.querySelector('[data-sar-learned-retry]');if(learnedRetry)learnedRetry.addEventListener('click',()=>loadCandidates());
      host.querySelectorAll('[data-sar-promote]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarPromote;
        if(st.confirmPromote!==id){st.confirmPromote=id;st.promoteNotice=null;render();const again=host.querySelector(`[data-sar-promote="${id}"]`);if(again&&again.focus)again.focus();return}
        promote(id);
      }));
      const cancel=host.querySelector('[data-sar-promote-cancel]');if(cancel)cancel.addEventListener('click',()=>{
        const id=st.confirmPromote;st.confirmPromote=null;render();
        /* Le focus revient au bouton de promotion, jamais perdu en haut de page. */
        const back=id&&host.querySelector(`[data-sar-promote="${id}"]`);if(back&&back.focus)back.focus();
      });
    }

    /* --- E/S ------------------------------------------------------------- */
    async function load(){
      st.phase='loading';st.error=null;st.startedAt=now();render();
      try{
        const data=await fetchJson(ROLES_PATH);
        if(!data||!Array.isArray(data.roles)){const e=new Error('réponse sans liste de rôles');e.code='subagent_settings_payload_invalid';throw e}
        if(st.destroyed)return data;
        st.payload=normalizePayload(data);st.phase='ready';
        logInfo('subagent_settings.loaded',{roles:data.roles.length,schema_version:data.schema_version});
      }catch(e){
        if(st.destroyed)return null;
        st.phase='error';st.error=e;logError('subagent_settings_load_failed',e,{path:ROLES_PATH});
      }finally{render()}
      /* Chaque vue ne lit que ce qu'elle montre : les instances pour les rôles, les candidats pour les Work Methods. */
      if(st.phase==='ready'){if(view==='work_methods')loadCandidates();else loadTasks()}
      return st.payload;
    }
    async function loadTasks(){
      st.tasks={phase:'loading',error:null,items:st.tasks.items,startedAt:now()};render();
      /* `render` ne lève pas (il passe en état d'erreur) ; la lecture des instances reste indépendante. */
      try{
        const data=await fetchJson(TASKS_PATH);
        if(st.destroyed)return;
        st.tasks={phase:'ready',error:null,items:Array.isArray(data&&data.tasks)?data.tasks:[]};
      }catch(e){
        if(st.destroyed)return;
        st.tasks={phase:'error',error:e,items:[]};logError('subagent_settings_tasks_failed',e,{path:TASKS_PATH});
      }finally{render()}
    }
    async function loadCandidates(){
      st.learned={...st.learned,phase:'loading',error:null,startedAt:now()};render();
      try{
        const data=await fetchJson(CANDIDATES_PATH);
        if(st.destroyed)return;
        if(!data||!Array.isArray(data.candidates)){const e=new Error('réponse sans liste de candidats');e.code='subagent_settings_payload_invalid';throw e}
        st.learned={phase:'ready',error:null,items:data.candidates.filter(c=>c&&typeof c==='object'),
          scan:data.scan&&typeof data.scan==='object'?data.scan:{},
          thresholds:data.thresholds&&typeof data.thresholds==='object'?data.thresholds:{}};
        logInfo('subagent_settings.candidates_loaded',{candidates:data.candidates.length});
      }catch(e){
        if(st.destroyed)return;
        st.learned={phase:'error',error:e,items:[],thresholds:{}};logError('subagent_settings_candidates_failed',e,{path:CANDIDATES_PATH});
      }finally{render()}
    }
    /* Promotion d'un candidat, confirmée en deux temps : le brouillon tel que servi, la révision qu'il suit. */
    async function promote(candidateId){
      if(st.promote)return;
      const c=st.learned.items.find(x=>x&&x.candidate_id===candidateId);
      const draft=c&&c.draft&&typeof c.draft==='object'?c.draft:null;
      if(!c||c.status!=='candidate'||!draft){
        /* Jamais un bouton muet : l'écran dit pourquoi rien ne part, et relit. */
        const e=new Error('candidat introuvable ou plus éligible dans la vue de l’écran');e.code='subagent_settings_candidate_stale';
        logError('subagent_settings_promotion_failed',e,{candidate_id:candidateId});
        st.promoteNotice={tone:'bad',code:e.code,text:'Promotion impossible : cette approche n’est plus candidate dans la vue de l’écran. Rien n’a été écrit.',hint:'Les approches sont relues.'};
        st.confirmPromote=null;announce(st.promoteNotice.text);await loadCandidates();return;
      }
      const key=`${draft.method_id}@${draft.version}`;
      st.promote={candidateId,startedAt:now()};st.confirmPromote=null;st.promoteNotice=null;render();
      try{
        const result=await fetchJson(PROMOTIONS_PATH,{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({candidate_id:candidateId,expected_version:Number(draft.version)-1,method:draft})});
        logInfo('subagent_settings.method_promoted',{candidate_id:candidateId,method:key});
        const snap=result&&result.snapshot;
        st.promoteNotice=snap&&snap.written===false
          ?{tone:'bad',code:snap.code||'',text:`Méthode ${key} publiée, mais pas encore transmise aux sous-agents.`,hint:'Le prochain sous-agent recevra encore l’ancienne version ; la transmission est retentée à la prochaine lecture des Work Methods ou au redémarrage du Control Center.'}
          :{tone:'ok',text:`Méthode ${key} publiée.`,hint:'Elle s’applique au prochain sous-agent lancé avec un rôle qui cite cette méthode.'};
        try{await refreshRoles()}catch(again){logError('subagent_settings_refresh_failed',again,{candidate_id:candidateId})}
      }catch(e){
        logError('subagent_settings_promotion_failed',e,{candidate_id:candidateId,code:e.code||null});
        st.promoteNotice=UNKNOWN_OUTCOME.has(e.code)
          ?{tone:'bad',code:e.code,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')}`,hint:'Les approches sont relues : si elle apparaît « Promue », la promotion a bien été enregistrée.'}
          :{tone:'bad',code:e.code||'',text:`Promotion refusée. Refus du serveur : « ${e.message||'erreur sans message'} ».`,
            hint:STALE_CANDIDATE_CODES.has(e.code)?'Les approches ont changé depuis l’ouverture de l’écran : elles sont relues.':'Rien n’a été écrit.'};
      }finally{
        st.promote=null;announce(st.promoteNotice&&st.promoteNotice.text);
        await loadCandidates();
        /* Le focus va sur la notice qui dit ce qui s'est passé. */
        const n=host.querySelector&&host.querySelector('[data-sar-promote-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    async function refreshRoles(){
      const data=await fetchJson(ROLES_PATH);
      if(!data||!Array.isArray(data.roles)){const e=new Error('réponse sans liste de rôles');e.code='subagent_settings_payload_invalid';throw e}
      st.payload=normalizePayload(data);
    }
    function snapshotNote(body){
      const snap=body&&body.subagent_roles_snapshot;
      if(snap&&snap.written===false)return {tone:'bad',text:'Enregistré, mais pas encore transmis aux sous-agents : le prochain lancé suivra l’ancienne version.',code:snap.code||'',hint:snap.error||''};
      return null;
    }
    function setNotice(id,notice){st.notice[id]=notice;announce(notice.text)}
    /* Relecture après une écriture : son échec ne dit jamais « rien n'a été écrit ». */
    async function rereadAfter(id,ok,failure){
      try{await refreshRoles();setNotice(id,ok());return true}
      catch(e){
        logError('subagent_settings_refresh_failed',e,{role_id:id,code:e.code||null});
        setNotice(id,{tone:'bad',reread:true,code:e.code||'',text:`${failure||'Enregistré'} ; la relecture a échoué : « ${e.message||'erreur sans message'} ».`,
          hint:'La fiche montre peut-être encore l’ancienne version. Réessayez la relecture avant toute autre modification.'});
        return false;
      }
    }
    async function mutate(id,action){
      const role=roleById(id);if(!role||st.save)return;
      const text=String(draftOf(role)??'');
      st.save={id,action,startedAt:now()};st.confirmReset=null;delete st.notice[id];render();
      try{
        const body=action==='reset'?{action:'reset'}
          :{action:'edit',text,base_revision:role.default_revision,expected_effective_revision:role.revision};
        let result;
        try{
          result=await fetchJson(PROMPT_PATH(role.prompt_id||'subagent_role.'+id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        }catch(e){
          logError(action==='reset'?'subagent_settings_reset_failed':'subagent_settings_save_failed',e,{role_id:id,code:e.code||null});
          if(action==='edit')st.drafts[id]=text;
          if(UNKNOWN_OUTCOME.has(e.code)){
            /* Pas de réponse : le serveur a peut-être écrit. On relit, puis on dit ce que montre la relecture. */
            st.save={id,action:'reread',startedAt:now()};render();
            await rereadAfter(id,()=>{
              const saved=roleById(id),same=saved&&(action==='reset'?!saved.modified:saved.instructions===text);
              if(same&&action==='edit')delete st.drafts[id];
              return {tone:'bad',code:e.code,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')} Relisez avant de réenregistrer.`,
                hint:same?'La relecture montre que la modification a bien été enregistrée.':'La relecture montre la version précédente : la modification n’a pas été enregistrée. Votre texte reste dans le champ.'};
            },'Résultat inconnu');
          }else if(CONFLICT_CODES.has(e.code)){
            /* Conflit de révision : la version enregistrée a changé ailleurs. Le texte reste dans le champ ; les
               révisions sont relues pour qu'un second enregistrement, voulu, réussisse. */
            try{await refreshRoles()}catch(again){logError('subagent_settings_refresh_failed',again,{role_id:id})}
            setNotice(id,{tone:'bad',code:e.code,text:e.code==='prompt_override_stale'
              ?'Le défaut de ce rôle a changé depuis l’ouverture de l’écran. Votre texte est conservé dans le champ.'
              :'Ces instructions ont été modifiées ailleurs depuis l’ouverture de l’écran. Votre texte est conservé dans le champ.',
              hint:'La version enregistrée a été relue. Relisez votre texte, puis enregistrez à nouveau pour la remplacer, ou annulez vos changements pour la garder.'});
          }else{
            setNotice(id,{tone:'bad',code:e.code||'',text:`${action==='reset'?'Retour au défaut refusé':'Enregistrement refusé'}. Refus du serveur : « ${e.message||'erreur sans message'} ». Rien n’a été écrit.`});
          }
          return;
        }
        delete st.drafts[id];
        logInfo('subagent_settings.instructions_'+action,{role_id:id,changed:!!(result&&result.mutation&&result.mutation.changed)});
        await rereadAfter(id,()=>snapshotNote(result)||{tone:'ok',text:action==='reset'?'Instructions revenues au défaut du code.':'Instructions enregistrées. Elles s’appliquent au prochain sous-agent lancé avec ce rôle.'});
      }finally{
        st.save=null;st.openEditor[id]=true;render();
        const n=host.querySelector&&host.querySelector('[data-sar-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    async function reread(id){
      if(st.save)return;
      st.save={id,action:'reread',startedAt:now()};render();
      try{await rereadAfter(id,()=>({tone:'ok',text:'Version enregistrée relue.'}))}
      finally{st.save=null;render()}
    }
    const save=id=>mutate(id,'edit');
    const reset=id=>mutate(id,'reset');

    function destroy(){st.destroyed=true;if(ticker!=null){clearTimer(ticker);ticker=null}}
    function hasUnsaved(){return roles().some(isDirty)}

    host.setAttribute&&host.setAttribute('data-subagent-settings-host','1');
    render();
    return {view,load,loadTasks,loadCandidates,promote,render,save,reset,reread,select,destroy,hasUnsaved,resolveMarker,state:st};
  }

  root.JarvisSubagentSettings=Object.freeze({mountId:MOUNT_ID,ICONS:Object.freeze(Object.keys(ICONS)),create,
    mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    async show(host,options){const view=create(host,options);await view.load();return view}});
})(typeof window!=='undefined'?window:globalThis);
