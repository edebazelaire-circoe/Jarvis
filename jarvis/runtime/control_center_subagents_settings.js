/* Réglages des sous-agents (jarvis-organic-agent-orchestration, Slice 10 ; sections depuis
   jarvis-settings-ui-reorganization Slice 04).

   Deux vues (`options.view`) : `roles` (défaut, onglet Architecture & Agents › Sous-agents) et
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
   Point de montage : `#subagentSettingsMount` (créé par la section). Contrat : `docs/subagent-roles.md` § 8.

   Modèles du rôle (jarvis-architecture-agents-settings-editor, Slice 06) : quand la page passe un adaptateur
   `options.routing` (`JarvisSubagentRouting.createHttpAdapter()`, monté par la Slice 07), la fiche porte la
   liste ordonnée des candidats harness + modèle du rôle, le repli automatique (`allow_general_fallback`), la
   provenance (hérité du profil / réglé pour ce rôle), la restauration de l'héritage et l'aperçu servi ; une vue
   d'ensemble en lecture seule projette le même instantané. Chaque écriture ne vise qu'UN rôle ; l'écran affiche
   l'instantané renvoyé, garde le brouillon sur un refus, relit sur un 409 ou une issue inconnue. Sans adaptateur,
   la vue renvoie vers Avancé › Runtime & CLI (profils hérités). Le style propre à cette composition est
   injecté une fois (`#jarvisSubagentSettingsStyle`), jetons du thème seulement. */
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
  /* Transport et lecture de la politique par rôle (Slice 06). Absent de la page : la fiche n'a pas de section
     Modèles, rien d'autre ne change. */
  const Routing=root.JarvisSubagentRouting||(typeof require==='function'?require('./control_center_subagent_routing.js'):null);
  const STYLE_ID='jarvisSubagentSettingsStyle';
  /* Pictogrammes des commandes (trait 1,8, grille 24), dessinés ici : ce ne sont pas des identités de rôle. */
  const OPS={
    up:'<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',down:'<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
    remove:'<path d="M6 6l12 12M18 6 6 18"/>',add:'<path d="M12 5v14M5 12h14"/>',
    ok:'<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/>',
    warn:'<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.2M12 17h.01"/>',
    lock:'<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/>',
    route:'<circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="18" r="2.4"/><path d="M8.4 6H15a3 3 0 0 1 0 6H9a3 3 0 0 0 0 6h6.6"/>',
    inherit:'<path d="M6 4v9a4 4 0 0 0 4 4h8"/><path d="m14 13 4 4-4 4"/>',pin:'<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    grid:'<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>',
  };
  const op=(name,cls)=>`<svg class="sar-op-g${cls?' '+cls:''}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${OPS[name]||''}</svg>`;
  const PREVIEW_REASON={preferred:'premier choix de la liste',fallback:'repli dans la liste du rôle',general_fallback:'repli sur la liste générale'};

  function logError(code,error,context){try{root.console&&root.console.error(code,error,context||{})}catch(_e){/* intentionnel : la console absente (test node sans console) ne doit pas masquer l'erreur déjà affichée */}}
  function logInfo(code,data){try{root.console&&root.console.info(code,data||{})}catch(_e){/* intentionnel : même argument que logError */}}

  function create(host,options){
    const opts=options||{};
    /* La promotion d'une approche observée est un outil d'opérateur (Avancé), pas une configuration de rôle. */
    const view=opts.view==='work_methods'?'work_methods':'roles';
    /* Adaptateur de la politique par rôle (`JarvisSubagentRouting`) ; la vue Work Methods n'en a pas l'usage. */
    const routing=view==='roles'&&Routing&&opts.routing&&typeof opts.routing.load==='function'?opts.routing:null;
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
      /* Slice 06 : politique de routage par rôle (lecture indépendante du registre). `routeDrafts` : brouillon
         par rôle `{candidates:[{agent,model}], allow_general_fallback}`, partageable avec la page comme `drafts`. */
      route:{phase:routing?'loading':'off',error:null,snap:null,stale:null,startedAt:now()},
      routeDrafts:opts.routeDrafts&&typeof opts.routeDrafts==='object'?opts.routeDrafts:{},
      routeSave:null,routeNotice:{},routeConfirmRestore:null,routeAdd:{},overview:false,
      startedAt:now(),destroyed:false,
    };
    let ticker=null,routePromise=null;
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
    /* Ligne « candidat préféré » d'un rôle dans la liste : projection de l'instantané (ou du brouillon), lecture seule. */
    function preferredLine(role){
      if(st.route.phase==='off'||!snap())return '';
      const r=routeOf(role.id);if(!r)return '';
      const d=routeEffective(role.id),first=d.candidates[0];
      if(!first)return `<span class="sar-item-route bad">${op('warn')}liste vide</span>`;
      const v=candView(role.id,first),more=d.candidates.length-1;
      return `<span class="sar-item-route${v.available?'':' bad'}">${v.available?op('route'):op('warn')}<span class="sar-item-route-l">${esc(v.label)}${v.available?'':' (indisponible)'}</span>${more>0?`<span class="sar-item-more">+${more}</span>`:''}<span class="sar-item-prov">${r.explicit?'réglé':'hérité'}</span></span>`;
    }
    function listItem(role){
      const sel=role.id===st.selected&&!st.overview;
      const tags=[availability(role),role.modified?chip('modifié','warn'):'',isDirty(role)?chip('non enregistré','warn'):'',routeDirty(role.id)?chip('routage non enregistré','warn'):'',role.conflict?chip('surcharge écartée','bad'):''].join('');
      return `<li><button type="button" class="sar-item${sel?' selected':''}${role.enabled?'':' off'}" data-sar-role="${esc(role.id)}" aria-current="${sel?'true':'false'}" tabindex="${sel||(st.overview&&role.id===st.selected)?'0':'-1'}" style="${accentStyle(accentOf(role))}">
        ${identity(role,'sm')}<span class="sar-item-text"><span class="sar-item-name">${esc(role.name)}</span><span class="sar-item-meta"><code>[${esc(role.marker||role.id)}]</code>${tags}</span>${preferredLine(role)}</span></button></li>`;
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

    /* --- Modèles du rôle (Slice 06) ------------------------------------------------------------------------
       Tout vient de l'instantané servi : harnesses, modèles, libellés, disponibilité, « lançable », aperçu. Le
       brouillon n'est qu'une liste ordonnée de couples {agent, model} et le repli ; rien d'autre n'est supposé. */
    const snap=()=>st.route.snap;
    const routeOf=id=>(snap()&&snap().roles.find(r=>r.role_id===id))||null;
    const refsOf=list=>list.map(c=>({agent:c.agent,model:c.model}));
    function routeEffective(id){
      if(own(st.routeDrafts,id))return st.routeDrafts[id];
      const r=routeOf(id);return r?{candidates:refsOf(r.candidates),allow_general_fallback:r.allow_general_fallback}:null;
    }
    function routeDirty(id){
      const r=routeOf(id);if(!r||!own(st.routeDrafts,id))return false;
      const d=st.routeDrafts[id];return !Routing.sameList(d.candidates,r.candidates)||d.allow_general_fallback!==r.allow_general_fallback;
    }
    /* Vue d'un candidat du brouillon : celle du serveur quand il la connaît, sinon le catalogue servi (un ajout
       pas encore enregistré : « lançable » sera dit par le serveur à l'enregistrement). */
    function candView(id,ref){
      const r=routeOf(id),known=r&&r.candidates.find(c=>Routing.sameRef(c,ref));
      if(known)return {...known,label:known.label||Routing.describeRef(snap(),ref).label};
      const d=Routing.describeRef(snap(),ref);return {...ref,label:d.label,available:d.available,unavailable_reason:d.unavailable_reason,selectable:null,selectable_reason:''};
    }
    const refLabel=ref=>Routing.describeRef(snap(),ref).label;
    function routeWritable(){
      const s=snap();
      if(!s||st.route.phase!=='ready'||st.routeSave)return false;
      return !st.route.stale&&s.store.status==='ok';
    }
    function availabilityHtml(v){
      if(!v.available)return `<span class="sar-av bad">${op('warn')}Indisponible : ${esc(v.unavailable_reason||'raison non donnée')}</span>`;
      if(v.selectable===false)return `<span class="sar-av ok">${op('ok')}Disponible</span><span class="sar-av muted">${op('lock')}Non lançable comme sous-agent : ${esc(v.selectable_reason||'raison non donnée')}</span>`;
      if(v.selectable===null)return `<span class="sar-av ok">${op('ok')}Disponible</span><span class="sar-av muted">Lançable : vérifié par le serveur à l’enregistrement</span>`;
      return `<span class="sar-av ok">${op('ok')}Disponible</span>`;
    }
    /* Un ancien réglage par identifiant complet est servi par sa famille : l'écran dit d'où il vient,
       sans le réécrire (HV-ARCH-007 : la famille tourne dans sa version courante du CLI). */
    function savedModelHtml(v){
      return v.saved_model?`<span class="sar-av muted" data-sar-saved-model>Enregistré sous <code>${esc(v.saved_model)}</code> : le CLI lance la version courante de cette famille ; il sera enregistré par famille à la prochaine modification de ce rôle.</span>`:'';
    }
    function provenanceChip(r){
      if(!r)return '';
      return r.explicit?`<span class="sar-prov explicit">${op('pin')}Réglé pour ce rôle</span>`
        :`<span class="sar-prov inherited">${op('inherit')}Hérité du profil « ${esc(r.inherited_profile||r.default_profile||'?')} »</span>`;
    }
    function previewHtml(r,dirty){
      const p=r.preview;
      /* Le libellé servi pour ce candidat quand il est dans la liste du rôle ; sinon celui du catalogue. */
      const refLabel=ref=>{const known=r.candidates.concat(r.fallback.candidates).find(c=>Routing.sameRef(c,ref));return known&&known.label||Routing.describeRef(snap(),ref).label};
      let body;
      if(!p)body='<span class="hint">Aucun aperçu servi.</span>';
      else if(p.outcome==='selected'){
        const skipped=(Array.isArray(p.considered)?p.considered:[]).filter(c=>c&&c.eligible===false);
        body=`<strong>${esc(refLabel({agent:String(p.agent||''),model:String(p.model||'')}))}</strong> <span class="hint">(${esc(PREVIEW_REASON[p.reason]||p.reason||'raison non donnée')})</span>`
          +(skipped.length?`<ul class="sar-skip">${skipped.map(c=>`<li>Écarté : ${esc(refLabel({agent:String(c.agent||''),model:String(c.model||'')}))} — ${esc(c.detail||c.code||'')}</li>`).join('')}</ul>`:'');
      }else if(p.outcome==='cli_default')body=`Le CLI garde son propre modèle. <span class="hint">${esc(p.detail||'')}</span>`;
      else if(p.outcome==='refused')body=`<span class="sar-av bad">${op('warn')}Lancement refusé</span> <span class="hint">${esc(p.detail||p.reason||'')}</span>`;
      else body=`<code>${esc(p.outcome)}</code> <span class="hint">${esc(p.detail||'')}</span>`;
      return `<div class="sar-preview" data-sar-preview><span class="sar-preview-k">Prochain lancement</span><div>${body}</div>
        ${dirty?'<p class="hint">Aperçu de la politique enregistrée : vos changements seront évalués par le serveur à l’enregistrement.</p>':''}</div>`;
    }
    function compatHtml(){
      const c=snap()&&snap().compatibility;
      if(!c||!c.note)return '';
      const link=opts.openTab?'<button type="button" class="sar-link" data-settings-open="runtime_cli">Avancé &amp; diagnostic › Runtime &amp; CLI</button>':'Avancé &amp; diagnostic › Runtime &amp; CLI';
      return `<p class="hint sar-compat" data-sar-compat>Compatibilité : ${esc(c.note)} Réglage historique : ${link}.</p>`;
    }
    function routeNoticeHtml(id){
      const n=st.routeNotice[id];if(!n)return '';
      const again=n.reread?`<div class="sar-actions"><button type="button" class="action" data-sar-route-reread="${esc(id)}"${st.routeSave?' disabled':''}>Relire la politique</button></div>`:'';
      return `<div class="notice ${n.tone==='bad'?'bad':n.tone==='ok'?'ok':''}" data-sar-route-notice>${esc(n.text)}${n.hint?`<div class="hint">${esc(n.hint)}</div>`:''}${codeLine(n.code)}${again}</div>`;
    }
    function snapshotStateHtml(){
      const s=snap();if(!s)return '';
      const parts=[];
      if(st.route.phase==='loading')parts.push(waitingHtml('Relecture de la politique des rôles…',st.route.startedAt||st.startedAt));
      if(st.route.phase==='error')parts.push(`<div class="notice bad">Dernière lecture de la politique en échec : ${esc(st.route.error&&st.route.error.message)} L’écran montre la version lue avant.${codeLine(st.route.error&&st.route.error.code)}<div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Réessayer</button></div></div>`);
      if(s.store.status!=='ok')parts.push(`<div class="notice bad">Fichier de la politique des rôles illisible : ${esc(s.store.reason||s.store.status)} Aucune écriture n’est possible tant qu’il n’est pas corrigé ; tous les rôles héritent de leur profil.${codeLine(s.store.code)}</div>`);
      if(s.catalog.status!=='ok')parts.push(`<div class="notice">Catalogue des modèles incomplet : ${esc(s.catalog.reason||s.catalog.status)}</div>`);
      if(st.route.stale)parts.push(`<div class="notice bad">L’écran ne montre peut-être plus la politique enregistrée : ${esc(st.route.stale.reason||'')} Relisez-la avant toute autre modification.${codeLine(st.route.stale.code)}<div class="sar-actions"><button type="button" class="action" data-sar-route-reread="*"${st.routeSave?' disabled':''}>Relire la politique</button></div></div>`);
      return parts.join('');
    }
    function candidateRow(id,ref,i,count,writable){
      const v=candView(id,ref),name=v.label||refLabel(ref),off=writable?'':' disabled';
      const btn=(kind,glyph,label,dis)=>`<button type="button" class="sar-op" data-sar-cand-op="${kind}" data-sar-cand-role="${esc(id)}" data-sar-cand-i="${i}" aria-label="${esc(label)}" title="${esc(label)}"${dis||!writable?' disabled':''}>${op(glyph)}</button>`;
      return `<li class="sar-cand${v.available?'':' unavailable'}${v.selectable===false?' blocked':''}" data-sar-cand="${i}">
        <span class="sar-cand-pos" aria-hidden="true">${i+1}</span>
        <span class="sar-cand-main"><span class="sar-cand-name"><span class="sar-sr">Position ${i+1} sur ${count} : </span>${esc(name)}</span><span class="sar-cand-state">${availabilityHtml(v)}${savedModelHtml(v)}</span></span>
        <span class="sar-cand-ops" role="group" aria-label="Déplacer ou retirer ${esc(name)}"${off?' aria-disabled="true"':''}>
          ${btn('up','up',`Monter ${name}`,i===0)}${btn('down','down',`Descendre ${name}`,i===count-1)}${btn('remove','remove',`Retirer ${name}`,false)}</span></li>`;
    }
    function addRowHtml(id,draft,writable){
      const s=snap(),harnesses=s.harnesses;
      if(!harnesses.length)return '<p class="hint">Aucun harness servi par le catalogue : rien à ajouter.</p>';
      const inList=ref=>draft.candidates.some(c=>Routing.sameRef(c,ref));
      const pickFor=h=>(h.models.find(m=>m.available&&!inList({agent:h.id,model:m.model}))||null);
      let sel=st.routeAdd[id]||null;
      if(!sel||!harnesses.some(h=>h.id===sel.agent)){const h=harnesses.find(x=>pickFor(x))||harnesses[0],m=pickFor(h);sel={agent:h.id,model:m?m.model:null}}
      const h=harnesses.find(x=>x.id===sel.agent);
      if(sel.model==null||!h.models.some(m=>m.model===sel.model&&m.available&&!inList({agent:h.id,model:m.model}))){const m=pickFor(h);sel={agent:h.id,model:m?m.model:null}}
      st.routeAdd[id]=sel;
      const hOpts=harnesses.map(x=>`<option value="${esc(x.id)}"${x.id===sel.agent?' selected':''}>${esc(x.label)}${x.available?'':' (indisponible)'}</option>`).join('');
      const mOpts=h.models.map(m=>{const dup=inList({agent:h.id,model:m.model}),dis=!m.available||dup;
        const why=dup?' — déjà dans la liste':!m.available?` — indisponible : ${m.unavailable_reason||'raison non donnée'}`:'';
        return `<option value="${esc(m.model)}"${m.model===sel.model?' selected':''}${dis?' disabled':''}>${esc(m.label)}${esc(why)}</option>`}).join('');
      const none=sel.model==null;
      return `<div class="sar-add" data-sar-add-row="${esc(id)}">
        <label class="sar-field"><span>Harness</span><select data-sar-add-agent="${esc(id)}"${writable?'':' disabled'}>${hOpts}</select></label>
        <label class="sar-field"><span>Modèle</span><select data-sar-add-model="${esc(id)}"${writable&&!none?'':' disabled'}>${none?'<option value="__none__" selected disabled>Aucun modèle disponible à ajouter</option>':''}${mOpts}</select></label>
        <button type="button" class="action sar-add-btn" data-sar-add="${esc(id)}"${writable&&!none?'':' disabled'}>${op('add')}Ajouter en dernier</button>
        ${!h.available?`<p class="hint sar-add-why">${esc(h.label)} est indisponible : ${esc(h.unavailable_reason||'raison non donnée')}</p>`:''}</div>`;
    }
    /* Une erreur de rendu de la section Modèles reste dans la section : la fiche et l'éditeur d'instructions restent. */
    function safeModelsHtml(role){
      try{return modelsHtml(role)}
      catch(e){
        logError('subagent_settings_routing_render_failed',e,{role_id:role.id});
        return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(role.id)}"><h4 id="sar-models-${esc(role.id)}" tabindex="-1">${op('route','sar-h-g')}Modèles du rôle</h4>
          <div class="notice bad" role="alert">Cette section n’a pas pu afficher la politique servie : ${esc(e&&e.message||e)}<div class="hint">Le reste de la fiche et les instructions restent utilisables. Relisez la politique ; si l’erreur revient, signalez-la avec le code ci-dessous.</div>${codeLine('subagent_settings_routing_render_failed')}</div>
          <div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Relire la politique</button></div></section>`;
      }
    }
    function modelsHtml(role){
      const id=role.id,head=`<h4 id="sar-models-${esc(id)}" tabindex="-1">${op('route','sar-h-g')}Modèles du rôle`;
      if(st.route.phase==='off')return '';
      if(st.route.phase==='loading'&&!snap())return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}">${head}</h4>${waitingHtml('Lecture de la politique des rôles…',st.route.startedAt||st.startedAt)}</section>`;
      if(st.route.phase==='error'&&!snap())return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}">${head}</h4>
        <div class="notice bad">Politique des rôles illisible : ${esc(st.route.error&&st.route.error.message)}<div class="hint">La fiche et les instructions restent utilisables.</div>${codeLine(st.route.error&&st.route.error.code)}</div>
        <div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Réessayer</button></div></section>`;
      const r=routeOf(id);
      if(!r)return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}">${head}</h4><p class="hint">Aucune politique servie pour ce rôle : seuls les rôles actifs sont routés.</p></section>`;
      const draft=routeEffective(id),dirty=routeDirty(id),writable=routeWritable(),saving=st.routeSave&&st.routeSave.id===id;
      const count=draft.candidates.length;
      const fb=r.fallback,fbInapplicable=!r.explicit&&r.inherited_profile===fb.profile&&!dirty;
      const fbList=fb.candidates.length?fb.candidates.map(c=>esc(c.label||refLabel(c))).join(', '):'liste générale vide';
      const confirming=st.routeConfirmRestore===id;
      const missing=r.missing.length?`<div class="notice">Politique incomplète : la réponse ne donne pas ${r.missing.map(k=>`<code>${esc(k)}</code>`).join(', ')}.</div>`:'';
      const waitLabel=saving?(st.routeSave.action==='restore'?'Restauration de l’héritage…':st.routeSave.action==='reread'?'Relecture de la politique…':'Enregistrement de la politique du rôle…'):'';
      return `<section class="sar-block sar-route" aria-labelledby="sar-models-${esc(id)}" data-sar-route="${esc(id)}">
        ${head} ${provenanceChip(r)}${dirty?chip('non enregistré','warn'):''}</h4>
        <p class="sar-route-why">${esc(r.binding_reason||'')}${r.explicit?'':' Modifier cette liste la règle pour ce rôle seul ; les autres rôles et le profil ne changent pas.'}</p>
        ${snapshotStateHtml()}${missing}
        <ol class="sar-cands" aria-label="Candidats de ${esc(role.name)}, par ordre de préférence" data-sar-cands="${esc(id)}">
          ${count?draft.candidates.map((c,i)=>candidateRow(id,c,i,count,writable)).join(''):'<li class="sar-cand empty"><span class="hint">Liste vide : le serveur la refuserait. Ajoutez un candidat, ou restaurez l’héritage.</span></li>'}
        </ol>
        <p class="hint sar-cand-help">L’ordre est la préférence : le premier candidat lançable sert le rôle. Boutons ou Alt + flèches haut et bas pour réordonner.</p>
        ${addRowHtml(id,draft,writable)}
        <div class="sar-fallback">
          <label class="sar-switch"><input type="checkbox" role="switch" data-sar-fallback="${esc(id)}"${draft.allow_general_fallback?' checked':''}${writable?'':' disabled'} aria-describedby="sar-fb-${esc(id)}">
            <span class="sar-switch-track" aria-hidden="true"><span class="sar-switch-knob"></span></span><span>Repli automatique sur la liste générale</span></label>
          <p class="hint" id="sar-fb-${esc(id)}">${fbInapplicable?'Ce rôle hérite déjà de la liste générale : le repli n’ajoute rien tant qu’il n’est pas réglé pour lui.'
            :draft.allow_general_fallback?`Activé : liste épuisée, JARVIS tente la liste du profil « ${esc(fb.profile)} » (${fbList}).`:'Désactivé : liste épuisée, rien d’autre n’est tenté.'}</p></div>
        ${previewHtml(r,dirty)}
        ${saving?waitingHtml(waitLabel,st.routeSave.startedAt):''}
        ${routeNoticeHtml(id)}
        <div class="sar-actions">
          <button type="button" class="action primary" data-sar-route-save="${esc(id)}"${dirty&&count&&writable?'':' disabled'}>${saving&&st.routeSave.action==='put'?'Enregistrement…':'Enregistrer pour ce rôle'}</button>
          <button type="button" class="action" data-sar-route-discard="${esc(id)}"${dirty&&!st.routeSave?'':' disabled'}>Annuler mes changements</button>
          <button type="button" class="action danger" data-sar-route-restore="${esc(id)}"${r.restorable&&writable?'':' disabled'}${confirming?` aria-describedby="sar-restore-h-${esc(id)}"`:''}>${confirming?'Confirmer la restauration':'Restaurer l’héritage'}</button>
          ${confirming?`<span class="hint" id="sar-restore-h-${esc(id)}">La liste réglée pour ce rôle sera retirée : il suivra de nouveau le profil « ${esc(r.inherited_profile||r.default_profile)} ».</span>`:''}
        </div>
        <p class="hint">${r.explicit||dirty?'S’applique au prochain sous-agent lancé avec ce rôle ; aucun agent en cours n’est modifié.':''}</p>
        ${compatHtml()}</section>`;
    }
    /* Vue d'ensemble : projection en lecture seule du même instantané (rôle -> candidats dans l'ordre). Aucun
       contrôle d'édition : « Régler » ouvre la fiche du rôle sur sa section Modèles. */
    function overviewHtml(){
      let body;
      if(st.route.phase==='loading'&&!snap())body=waitingHtml('Lecture de la politique des rôles…',st.route.startedAt||st.startedAt);
      else if(!snap())body=`<div class="notice bad">Politique des rôles illisible : ${esc(st.route.error&&st.route.error.message)}${codeLine(st.route.error&&st.route.error.code)}</div><div class="sar-actions"><button type="button" class="action" data-sar-route-retry>Réessayer</button></div>`;
      else{
        const rows=roles().map(role=>{
          const r=routeOf(role.id);
          if(!r)return `<li class="sar-ov-row" style="${accentStyle(accentOf(role))}">${identity(role,'sm')}<span class="sar-ov-name">${esc(role.name)}</span><span class="hint sar-ov-chain">Aucune politique servie (rôle inactif).</span></li>`;
          const d=routeEffective(role.id),dirty=routeDirty(role.id);
          const chain=d.candidates.map((c,i)=>{const v=candView(role.id,c);return `<li class="sar-ov-c${v.available?'':' unavailable'}">${v.available?op('ok'):op('warn')}<span>${i+1}. ${esc(v.label)}</span>${v.available?'':`<span class="sar-sr"> (indisponible)</span>`}</li>`}).join('');
          return `<li class="sar-ov-row" style="${accentStyle(accentOf(role))}" data-sar-ov-role="${esc(role.id)}">${identity(role,'sm')}
            <span class="sar-ov-name">${esc(role.name)}<span class="sar-ov-prov">${provenanceChip(r)}${dirty?chip('non enregistré','warn'):''}</span></span>
            <ol class="sar-ov-chain" aria-label="Candidats de ${esc(role.name)}">${chain||'<li class="hint">liste vide</li>'}</ol>
            <span class="sar-ov-fb">${d.allow_general_fallback?op('ok'):op('remove')}Repli général ${d.allow_general_fallback?'activé':'désactivé'}</span>
            <button type="button" class="action small" data-sar-route-goto="${esc(role.id)}">Régler<span class="sar-sr"> ${esc(role.name)}</span></button></li>`;
        }).join('');
        body=`${snapshotStateHtml()}<ul class="sar-ov-list" aria-label="Routage des rôles">${rows}</ul>${compatHtml()}`;
      }
      return `<article class="sar-detail sar-ov" aria-labelledby="sar-title">
        <button type="button" class="action sar-back" data-sar-back>Revenir à la liste des rôles</button>
        <header class="sar-head"><span class="sar-ident sar-lg" style="${accentStyle('slate')}"><span class="sar-tile">${op('grid','sar-glyph')}</span></span><div>
          <h3 id="sar-title" class="sar-title" tabindex="-1">Vue d’ensemble du routage</h3>
          <p class="sar-desc">Pour chaque rôle, les candidats harness + modèle dans l’ordre de préférence, tels que le serveur les sert. Lecture seule : chaque rôle se règle dans sa fiche.</p></div></header>
        ${body}</article>`;
    }

    function detailHtml(role){
      if(st.overview)return overviewHtml();
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
        ${safeModelsHtml(role)}
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
          ${st.route.phase==='off'?'':`<button type="button" class="sar-ov-toggle${st.overview?' selected':''}" data-sar-overview aria-pressed="${st.overview?'true':'false'}">${op('grid')}<span>Vue d’ensemble du routage</span></button>`}
          <ul class="sar-list" role="list" aria-label="Rôles de sous-agent" data-sar-list>${roles().map(listItem).join('')}</ul>
          <p class="hint">Flèches haut et bas pour parcourir les rôles.</p>
          ${instancesHtml()}
          ${st.route.phase==='off'?`<p class="hint sar-models">Les modèles des sous-agents se règlent dans ${opts.openTab?'<button type="button" class="sar-link" data-sar-open-models>Avancé &amp; diagnostic › Runtime &amp; CLI</button>':'Avancé &amp; diagnostic › Runtime &amp; CLI'}.</p>`:''}</div>
        <div class="sar-detail-pane" role="region" aria-label="Fiche du rôle">${detailHtml(roleById(st.selected))}</div></div>`;
      const pane=host.querySelector('.sar-detail-pane');if(pane&&scroll)pane.scrollTop=scroll;
      bind();tick();
    }

    /* Compteur vivant des attentes : un seul minuteur, arrêté dès qu'aucune attente n'est affichée. */
    function tick(){
      const waiting=!st.destroyed&&(st.phase==='loading'||(view==='roles'?st.tasks.phase==='loading'||!!st.save||st.route.phase==='loading'||!!st.routeSave:st.learned.phase==='loading'||!!st.promote));
      if(waiting&&ticker==null)ticker=setTimer(()=>{
        if(!host.querySelectorAll)return;
        host.querySelectorAll('[data-sar-since]').forEach(el=>{el.textContent=elapsed(Number(el.dataset.sarSince))+' s'});
      },1000);
      if(!waiting&&ticker!=null){clearTimer(ticker);ticker=null}
    }

    const oneColumn=()=>!!(root.matchMedia&&root.matchMedia('(max-width: 900px)').matches);
    function select(id,focus){
      if(!roleById(id))return;
      st.selected=id;st.overview=false;st.confirmReset=null;st.confirmPromote=null;st.routeConfirmRestore=null;render();
      if(focus==='detail'&&oneColumn()){
        const title=host.querySelector('#sar-title'),card=host.querySelector('.sar-detail');
        if(card&&card.scrollIntoView)card.scrollIntoView({block:'start'});
        if(title&&title.focus)title.focus({preventScroll:true});
        return;
      }
      if(focus){const b=host.querySelector(`[data-sar-role="${cssId(id)}"]`);if(b&&b.focus)b.focus()}
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
        const save=host.querySelector(`[data-sar-save="${cssId(role.id)}"]`),discard=host.querySelector(`[data-sar-discard="${cssId(role.id)}"]`);
        if(save)save.disabled=!dirty||busy||!canSave(role,area.value);if(discard)discard.disabled=!dirty||busy;
      }));
      host.querySelectorAll('[data-sar-save]').forEach(b=>b.addEventListener('click',()=>save(b.dataset.sarSave)));
      host.querySelectorAll('[data-sar-discard]').forEach(b=>b.addEventListener('click',()=>{delete st.drafts[b.dataset.sarDiscard];delete st.notice[b.dataset.sarDiscard];render()}));
      host.querySelectorAll('[data-sar-reset]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarReset;
        if(st.confirmReset!==id){st.confirmReset=id;render();const again=host.querySelector(`[data-sar-reset="${cssId(id)}"]`);if(again&&again.focus)again.focus();return}
        reset(id);
      }));
      const refresh=host.querySelector('[data-sar-tasks-refresh]');if(refresh)refresh.addEventListener('click',()=>loadTasks());
      const inst=host.querySelector('[data-sar-instances]');if(inst)inst.addEventListener('toggle',()=>{st.instancesOpen=inst.open});
      host.querySelectorAll('[data-sar-reread]').forEach(b=>b.addEventListener('click',()=>reread(b.dataset.sarReread)));
      bindRouting();
      const back=host.querySelector('[data-sar-back]');if(back)back.addEventListener('click',()=>{const b=host.querySelector(`[data-sar-role="${cssId(st.selected)}"]`);if(b){if(b.scrollIntoView)b.scrollIntoView({block:'center'});b.focus()}});
      const models=host.querySelector('[data-sar-open-models]');if(models)models.addEventListener('click',()=>opts.openTab('runtime_cli'));
      const learned=host.querySelector('[data-sar-open-learned]');if(learned)learned.addEventListener('click',()=>opts.openTab('work_methods'));
      const learnedRetry=host.querySelector('[data-sar-learned-retry]');if(learnedRetry)learnedRetry.addEventListener('click',()=>loadCandidates());
      host.querySelectorAll('[data-sar-promote]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarPromote;
        if(st.confirmPromote!==id){st.confirmPromote=id;st.promoteNotice=null;render();const again=host.querySelector(`[data-sar-promote="${cssId(id)}"]`);if(again&&again.focus)again.focus();return}
        promote(id);
      }));
      const cancel=host.querySelector('[data-sar-promote-cancel]');if(cancel)cancel.addEventListener('click',()=>{
        const id=st.confirmPromote;st.confirmPromote=null;render();
        /* Le focus revient au bouton de promotion, jamais perdu en haut de page. */
        const back=id&&host.querySelector(`[data-sar-promote="${cssId(id)}"]`);if(back&&back.focus)back.focus();
      });
    }


    /* --- Modèles du rôle : liaisons ------------------------------------------------------------------------ */
    /* Un id de rôle vient du serveur : échappé avant d'entrer dans un sélecteur. */
    const cssId=v=>root.CSS&&typeof root.CSS.escape==='function'?root.CSS.escape(String(v)):String(v).replace(/[^a-zA-Z0-9_-]/g,c=>'\\'+c);
    function focusSel(sel){const el=host.querySelector&&host.querySelector(sel);if(el&&el.focus){el.focus();return true}return false}
    /* Après un déplacement, le focus suit le candidat déplacé (même commande, sinon une autre de sa ligne). */
    function focusCandidate(id,i,prefer){
      const at=k=>`[data-sar-cand-role="${cssId(id)}"][data-sar-cand-i="${i}"][data-sar-cand-op="${k}"]:not(:disabled)`;
      for(const k of [prefer,'up','down','remove'])if(k&&focusSel(at(k)))return;
      focusSel(`[data-sar-add-agent="${cssId(id)}"]`);
    }
    function bindRouting(){
      if(!host.querySelectorAll)return;
      host.querySelectorAll('[data-sar-cand-op]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarCandRole,i=Number(b.dataset.sarCandI),kind=b.dataset.sarCandOp;
        if(kind==='remove')removeCandidate(id,i,true);else moveCandidate(id,i,kind==='up'?-1:1,true);
      }));
      /* Réordonner au clavier sans viser un bouton : Alt + flèche sur n'importe quelle commande de la ligne. */
      host.querySelectorAll('.sar-cand[data-sar-cand]').forEach(li=>li.addEventListener('keydown',ev=>{
        if(!ev.altKey||(ev.key!=='ArrowUp'&&ev.key!=='ArrowDown'))return;
        const b=li.querySelector('[data-sar-cand-op]');if(!b)return;
        ev.preventDefault();moveCandidate(b.dataset.sarCandRole,Number(b.dataset.sarCandI),ev.key==='ArrowUp'?-1:1,true);
      }));
      host.querySelectorAll('[data-sar-add-agent]').forEach(el=>el.addEventListener('change',()=>{
        const id=el.dataset.sarAddAgent;st.routeAdd[id]={agent:el.value,model:null};render();focusSel(`[data-sar-add-agent="${cssId(id)}"]`);
      }));
      host.querySelectorAll('[data-sar-add-model]').forEach(el=>el.addEventListener('change',()=>{
        const id=el.dataset.sarAddModel;if(el.value==='__none__')return;st.routeAdd[id]={...(st.routeAdd[id]||{}),model:el.value};
      }));
      host.querySelectorAll('[data-sar-add]').forEach(b=>b.addEventListener('click',()=>addCandidate(b.dataset.sarAdd,null,true)));
      host.querySelectorAll('[data-sar-fallback]').forEach(el=>el.addEventListener('change',()=>{
        const id=el.dataset.sarFallback;setFallback(id,el.checked);focusSel(`[data-sar-fallback="${cssId(id)}"]`);
      }));
      host.querySelectorAll('[data-sar-route-save]').forEach(b=>b.addEventListener('click',()=>saveRoute(b.dataset.sarRouteSave)));
      host.querySelectorAll('[data-sar-route-discard]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarRouteDiscard;discardRoute(id);focusSel(`#sar-models-${cssId(id)}`);
      }));
      host.querySelectorAll('[data-sar-route-restore]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarRouteRestore;
        if(st.routeConfirmRestore!==id){st.routeConfirmRestore=id;render();focusSel(`[data-sar-route-restore="${cssId(id)}"]`);return}
        restoreRoute(id);
      }));
      host.querySelectorAll('[data-sar-route-reread]').forEach(b=>b.addEventListener('click',()=>rereadRouting(b.dataset.sarRouteReread==='*'?st.selected:b.dataset.sarRouteReread)));
      host.querySelectorAll('[data-sar-route-retry]').forEach(b=>b.addEventListener('click',()=>{routePromise=loadRouting()}));
      const ov=host.querySelector('[data-sar-overview]');if(ov)ov.addEventListener('click',()=>showOverview(!st.overview,true));
      host.querySelectorAll('[data-sar-route-goto]').forEach(b=>b.addEventListener('click',()=>{
        const id=b.dataset.sarRouteGoto;select(id);
        const h=host.querySelector(`#sar-models-${cssId(id)}`);if(h){if(h.scrollIntoView)h.scrollIntoView({block:'start'});if(h.focus)h.focus({preventScroll:true})}
      }));
      host.querySelectorAll('[data-settings-open]').forEach(b=>b.addEventListener('click',()=>{if(opts.openTab)opts.openTab(b.dataset.settingsOpen)}));
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
      if(st.phase==='ready'){if(view==='work_methods')loadCandidates();else{loadTasks();if(routing&&!snap())routePromise=loadRouting()}}
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


    /* --- Modèles du rôle : brouillon et écritures ------------------------------------------------------------
       Le brouillon d'un rôle ne touche que ce rôle ; une écriture n'envoie que lui (PUT ou DELETE de son id). */
    function editRoute(id,fn){
      const base=routeEffective(id);if(!base||!routeWritable())return false;
      const d={candidates:base.candidates.map(c=>({...c})),allow_general_fallback:base.allow_general_fallback};
      if(fn(d)===false)return false;
      st.routeDrafts[id]=d;if(!routeDirty(id))delete st.routeDrafts[id];
      delete st.routeNotice[id];st.routeConfirmRestore=null;render();return true;
    }
    function moveCandidate(id,i,delta,focus){
      const to=i+delta;let name='';
      const ok=editRoute(id,d=>{if(i<0||to<0||to>=d.candidates.length)return false;const [c]=d.candidates.splice(i,1);d.candidates.splice(to,0,c);name=refLabel(c)});
      if(!ok)return false;
      announce(`${name} : position ${to+1} sur ${routeEffective(id).candidates.length}.`);
      if(focus)focusCandidate(id,to,delta<0?'up':'down');
      return true;
    }
    function removeCandidate(id,i,focus){
      let name='';
      const ok=editRoute(id,d=>{if(i<0||i>=d.candidates.length)return false;name=refLabel(d.candidates.splice(i,1)[0])});
      if(!ok)return false;
      const n=routeEffective(id).candidates.length;announce(`${name} retiré de la liste${n?'':' : la liste est vide'}.`);
      if(focus){if(n)focusCandidate(id,Math.min(i,n-1),'remove');else focusSel(`[data-sar-add-agent="${cssId(id)}"]`)}
      return true;
    }
    function addCandidate(id,ref,focus){
      const pick=ref||st.routeAdd[id];
      if(!pick||pick.model==null)return false;
      const r={agent:String(pick.agent),model:String(pick.model)};
      const ok=editRoute(id,d=>{if(d.candidates.some(c=>Routing.sameRef(c,r)))return false;d.candidates.push(r)});
      if(!ok)return false;
      delete st.routeAdd[id];render();
      const n=routeEffective(id).candidates.length;announce(`${refLabel(r)} ajouté en position ${n} sur ${n}.`);
      if(focus)focusSel(`[data-sar-add="${cssId(id)}"]:not(:disabled)`)||focusCandidate(id,n-1,'up');
      return true;
    }
    function setFallback(id,on){return editRoute(id,d=>{d.allow_general_fallback=!!on})}
    function discardRoute(id){delete st.routeDrafts[id];delete st.routeNotice[id];st.routeConfirmRestore=null;render()}
    function showOverview(on,focus){
      st.overview=!!on;render();
      if(focus&&st.overview){if(oneColumn()){const c=host.querySelector('.sar-detail');if(c&&c.scrollIntoView)c.scrollIntoView({block:'start'})}focusSel('#sar-title')}
      else if(focus)focusSel('[data-sar-overview]');
    }
    function setRouteNotice(id,n){st.routeNotice[id]=n;announce(n.text)}
    /* Seul un instantané complet remplace l'écran ; un instantané dégradé ou vide ne l'efface jamais. */
    function applySnapshot(raw){
      if(!raw||typeof raw!=='object'||raw.degraded||!Array.isArray(raw.roles)||!raw.roles.length)return false;
      try{st.route.snap=Routing.normalizeSnapshot(raw);st.route.stale=null;return true}
      catch(e){logError('subagent_settings_routing_payload_invalid',e,{});return false}
    }
    async function loadRouting(){
      if(!routing)return null;
      st.route={...st.route,phase:'loading',error:null,startedAt:now()};render();
      try{
        const data=await routing.load();
        if(st.destroyed)return null;
        const next=Routing.normalizeSnapshot(data);
        st.route={...st.route,phase:'ready',error:null,snap:next,stale:null};
        logInfo('subagent_settings.routing_loaded',{revision:next.revision,roles:next.roles.length,explicit:next.roles.filter(r=>r.explicit).map(r=>r.role_id)});
      }catch(e){
        if(st.destroyed)return null;
        st.route={...st.route,phase:'error',error:e};logError('subagent_settings_routing_failed',e,{code:e&&e.code||null});
      }finally{render()}
      return st.route.snap;
    }
    const sameWrite=(r,action,draft)=>action==='restore'?!!r&&!r.explicit
      :!!r&&r.explicit&&Routing.sameList(r.candidates,draft.candidates)&&r.allow_general_fallback===draft.allow_general_fallback;
    async function refreshRouting(){st.route.snap=Routing.normalizeSnapshot(await routing.load());st.route.stale=null;st.route.phase='ready';st.route.error=null}
    async function writeRoute(id,action){
      const r=routeOf(id);if(!r||!routeWritable())return;
      const draft=routeEffective(id),base=snap().revision;
      const body={base_revision:base,candidates:refsOf(draft.candidates),allow_general_fallback:draft.allow_general_fallback};
      st.routeSave={id,action,startedAt:now()};st.routeConfirmRestore=null;delete st.routeNotice[id];render();
      const failCode=action==='restore'?'subagent_settings_routing_restore_failed':'subagent_settings_routing_save_failed';
      try{
        let res;
        try{res=action==='restore'?await routing.restore(id,{base_revision:base}):await routing.put(id,body)}
        catch(e){
          logError(failCode,e,{role_id:id,code:e&&e.code||null});
          if(!Routing.UNKNOWN_OUTCOME.has(e&&e.code)){
            setRouteNotice(id,{tone:'bad',code:e&&e.code||'',text:`${action==='restore'?'Restauration':'Enregistrement'} impossible : « ${e&&e.message||e} ». Rien n’a été écrit par cet écran.`});return;
          }
          /* Pas de réponse : le serveur a peut-être écrit. Relecture forcée, puis on dit ce qu'elle montre. */
          st.routeSave={id,action:'reread',startedAt:now()};render();
          try{await refreshRouting()}
          catch(again){
            logError('subagent_settings_routing_refresh_failed',again,{role_id:id,code:again&&again.code||null});
            st.route.stale={code:again&&again.code||'',reason:'la relecture après une écriture sans réponse a échoué.'};
            setRouteNotice(id,{tone:'bad',code:e.code,reread:true,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')} La relecture a échoué aussi : « ${again&&again.message||again} ».`,
              hint:'Votre liste reste à l’écran. Relisez la politique avant de réenregistrer.'});
            return;
          }
          const written=sameWrite(routeOf(id),action,draft);
          if(written)delete st.routeDrafts[id];
          setRouteNotice(id,{tone:'bad',code:e.code,text:`Résultat inconnu : ${String(e.message||'').replace(/\.?$/,'.')} La politique a été relue.`,
            hint:written?'La relecture montre que la modification a bien été enregistrée.':'La relecture montre la version précédente : la modification n’a pas été enregistrée. Votre liste reste à l’écran.'});
          return;
        }
        if(res&&res.ok){
          delete st.routeDrafts[id];
          logInfo('subagent_settings.routing_'+(action==='restore'?'restored':'saved'),{role_id:id,base_revision:base});
          if(applySnapshot(res.snapshot)){
            const after=routeOf(id);
            setRouteNotice(id,{tone:'ok',text:action==='restore'?`Héritage restauré : le rôle suit de nouveau le profil « ${after?after.inherited_profile:''} ».`
              :'Politique enregistrée pour ce rôle seul. Elle s’applique au prochain sous-agent lancé avec ce rôle.'});
          }else{
            const d=res.snapshot&&res.snapshot.degraded;
            st.route.stale={code:d&&d.code||'subagent_settings_routing_snapshot_missing',reason:d&&d.reason||'la réponse ne porte pas d’instantané lisible.'};
            logError('subagent_settings_routing_degraded',new Error(st.route.stale.reason),{role_id:id,code:st.route.stale.code});
            setRouteNotice(id,{tone:'bad',reread:true,code:st.route.stale.code,text:`${action==='restore'?'Restauré':'Enregistré'}, mais la relecture de la politique a échoué : « ${st.route.stale.reason} »`,
              hint:'L’écran montre peut-être l’ancienne politique. Relisez-la avant toute autre modification.'});
          }
          return;
        }
        const code=res&&res.code||'subagent_routing_refused',status=res&&res.status||0,reason=res&&res.reason||'refus sans raison';
        const err=new Error(reason);err.code=code;err.status=status;
        logError(failCode,err,{role_id:id,code,status});
        /* L'instantané renvoyé avec le refus fait foi ; sans lui, un 409 relit de force. */
        if(!applySnapshot(res&&res.snapshot)&&status===409){try{await refreshRouting()}catch(again){logError('subagent_settings_routing_refresh_failed',again,{role_id:id})}}
        if(code==='role_routing_revision_stale'){
          setRouteNotice(id,{tone:'bad',code,text:'La politique des rôles a changé ailleurs depuis l’ouverture de l’écran. Votre liste est conservée.',
            hint:`Refus du serveur : « ${reason} ». La version enregistrée a été relue : relisez votre liste, puis enregistrez à nouveau pour la remplacer, ou annulez vos changements.`});
        }else{
          setRouteNotice(id,{tone:'bad',code,text:`${action==='restore'?'Restauration refusée':'Enregistrement refusé'}. Refus du serveur : « ${reason} ». Rien n’a été écrit.`,
            hint:action==='restore'?'':'Votre liste reste à l’écran : corrigez-la, puis enregistrez à nouveau.'});
        }
      }finally{
        st.routeSave=null;render();
        const n=host.querySelector&&host.querySelector('[data-sar-route-notice]');if(n&&n.focus){n.tabIndex=-1;n.focus()}
      }
    }
    async function rereadRouting(id){
      if(!routing||st.routeSave)return;
      st.routeSave={id,action:'reread',startedAt:now()};render();
      try{await refreshRouting();setRouteNotice(id,{tone:'ok',text:'Politique des rôles relue.'})}
      catch(e){logError('subagent_settings_routing_refresh_failed',e,{role_id:id,code:e&&e.code||null});
        setRouteNotice(id,{tone:'bad',reread:true,code:e&&e.code||'',text:`Relecture impossible : « ${e&&e.message||e} ».`})}
      finally{st.routeSave=null;render()}
    }
    const saveRoute=id=>writeRoute(id,'put');
    const restoreRoute=id=>writeRoute(id,'restore');
    function ensureStyle(){
      const doc=host.ownerDocument;
      if(!doc||!doc.head||!doc.getElementById||doc.getElementById(STYLE_ID))return;
      const el=doc.createElement('style');el.id=STYLE_ID;el.textContent=STYLE;doc.head.appendChild(el);
    }

    function destroy(){st.destroyed=true;if(ticker!=null){clearTimer(ticker);ticker=null}}
    function hasUnsaved(){return roles().some(isDirty)||roles().some(r=>routeDirty(r.id))}

    host.setAttribute&&host.setAttribute('data-subagent-settings-host','1');
    render();
    ensureStyle();
    return {view,load,loadTasks,loadCandidates,promote,render,save,reset,reread,select,destroy,hasUnsaved,resolveMarker,
      loadRouting,moveCandidate,removeCandidate,addCandidate,setFallback,discardRoute,saveRoute,restoreRoute,rereadRouting,showOverview,routeReady:()=>routePromise||Promise.resolve(),state:st};
  }


  /* Composition néon/verre de la Slice 06, posée par-dessus les règles `.sar-*` de `control_center.html` (qui
     restent la base : liste, fiche, éditeur). Jetons du thème seulement (`--set-*`, `--shell-*`, `--accent`,
     `--ok`, `--warn`, `--danger`, `--role-accent-*`) : aucune couleur écrite ici (test). */
  const STYLE=`
.sar{--sar-ink:var(--set-ink,var(--text));--sar-ink-2:var(--set-ink-2,var(--muted));--sar-hair:var(--set-hair-2,var(--line));
  --sar-glass:var(--shell-glass-strong,var(--solid));--sar-r:12px;grid-template-columns:minmax(250px,320px) minmax(0,1fr);gap:22px}
.sar *{box-sizing:border-box}
.sar-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}
.sar-op-g{width:15px;height:15px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.sar-glyph.sar-op-g{width:26px;height:26px}
.sar-h-g{width:15px;height:15px;color:var(--sar-accent)}
.sar-side{gap:8px;padding-right:4px}
.sar-list{gap:6px}
.sar-item{position:relative;align-items:flex-start;padding:10px 12px;border:1px solid var(--sar-hair);border-radius:var(--sar-r);
  background:linear-gradient(105deg,color-mix(in srgb,var(--sar-accent) 7%,transparent),transparent 62%),var(--sar-glass);
  box-shadow:inset 0 1px 0 color-mix(in srgb,var(--sar-ink) 5%,transparent)}
.sar-item:hover{background:linear-gradient(105deg,color-mix(in srgb,var(--sar-accent) 13%,transparent),transparent 70%),var(--sar-glass);border-color:color-mix(in srgb,var(--sar-accent) 30%,var(--sar-hair))}
.sar-item.selected{background:linear-gradient(105deg,color-mix(in srgb,var(--sar-accent) 20%,transparent),color-mix(in srgb,var(--sar-accent) 4%,transparent) 75%),var(--sar-glass);
  border-color:color-mix(in srgb,var(--sar-accent) 62%,transparent);
  box-shadow:0 10px 26px -16px color-mix(in srgb,var(--sar-accent) 70%,transparent),inset 0 1px 0 color-mix(in srgb,var(--sar-accent) 28%,transparent)}
.sar-item-name{font-weight:600}
.sar-item-route{display:flex;align-items:center;gap:6px;min-width:0;margin-top:2px;font-size:11.5px;color:var(--sar-ink)}
.sar-item-route .sar-op-g{width:13px;height:13px;color:var(--sar-accent)}
.sar-item-route.bad,.sar-item-route.bad .sar-op-g{color:var(--warn)}
.sar-item-route-l{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sar-item-more{flex:none;font-size:10.5px;color:var(--sar-ink-2);border:1px solid var(--sar-hair);border-radius:999px;padding:0 6px}
.sar-item-prov{flex:none;margin-left:auto;font-size:10.5px;color:var(--sar-ink-2)}
.sar-ov-toggle{display:flex;align-items:center;gap:9px;width:100%;min-height:38px;padding:8px 12px;border-radius:var(--sar-r);border:1px dashed color-mix(in srgb,var(--accent) 38%,var(--sar-hair));
  background:color-mix(in srgb,var(--accent) 5%,transparent);color:var(--sar-ink);font:inherit;font-size:13px;cursor:pointer;text-align:left}
.sar-ov-toggle .sar-op-g{color:var(--accent)}
.sar-ov-toggle:hover{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.sar-ov-toggle.selected{border-style:solid;border-color:color-mix(in srgb,var(--accent) 62%,transparent);background:color-mix(in srgb,var(--accent) 13%,transparent)}
.sar-detail{max-width:860px}
.sar-head{padding:16px 18px;margin-bottom:4px;border:1px solid color-mix(in srgb,var(--sar-accent) 32%,var(--sar-hair));border-radius:calc(var(--sar-r) + 2px);
  background:radial-gradient(120% 140% at 0% 0%,color-mix(in srgb,var(--sar-accent) 16%,transparent),transparent 58%),var(--sar-glass);
  box-shadow:0 18px 40px -28px color-mix(in srgb,var(--sar-accent) 60%,transparent)}
.sar-lg .sar-tile{box-shadow:0 0 0 4px color-mix(in srgb,var(--sar-accent) 7%,transparent)}
.sar-block{padding:20px 2px 4px;border-bottom:1px solid color-mix(in srgb,var(--sar-hair) 70%,transparent)}
.sar-block:last-of-type{border-bottom:0}
.sar-block h4{flex-wrap:wrap}
.sar-route{margin:16px 0 4px;padding:16px 18px 14px;border:1px solid color-mix(in srgb,var(--sar-accent) 28%,var(--sar-hair));border-radius:calc(var(--sar-r) + 2px);
  background:linear-gradient(180deg,color-mix(in srgb,var(--sar-accent) 6%,transparent),transparent 40%),var(--sar-glass)}
.sar-route h4{font-size:12px;color:var(--sar-ink);letter-spacing:.12em}
.sar-route h4:focus{outline:none}.sar-route h4:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.sar-route-why{margin:0 0 12px;font-size:12.5px;line-height:1.55;color:var(--sar-ink-2);max-width:72ch}
.sar-prov{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;font-size:11px;letter-spacing:0;text-transform:none;border:1px solid var(--sar-hair);color:var(--sar-ink)}
.sar-prov .sar-op-g{width:13px;height:13px}
.sar-prov.explicit{border-color:color-mix(in srgb,var(--sar-accent) 60%,transparent);background:color-mix(in srgb,var(--sar-accent) 12%,transparent)}
.sar-prov.explicit .sar-op-g{color:var(--sar-accent)}
.sar-prov.inherited{border-style:dashed;color:var(--sar-ink-2)}
.sar-cands{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.sar-cand{display:grid;grid-template-columns:28px minmax(0,1fr) auto;align-items:center;gap:10px;padding:8px 8px 8px 10px;border:1px solid var(--sar-hair);border-radius:10px;
  background:color-mix(in srgb,var(--sar-ink) 3%,transparent)}
.sar-cand:first-child:not(.empty){border-color:color-mix(in srgb,var(--sar-accent) 45%,var(--sar-hair))}
.sar-cand.unavailable{border-style:dashed}
.sar-cand.empty{display:block;padding:12px}
.sar-cand-pos{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;font-size:11px;font-variant-numeric:tabular-nums;border:1px solid var(--sar-hair);color:var(--sar-ink-2)}
.sar-cand:first-child .sar-cand-pos{color:var(--sar-accent);border-color:color-mix(in srgb,var(--sar-accent) 60%,transparent);background:color-mix(in srgb,var(--sar-accent) 10%,transparent)}
.sar-cand-main{display:grid;gap:3px;min-width:0}
.sar-cand-name{font-size:13px;font-weight:600;overflow-wrap:anywhere}
.sar-cand-state{display:flex;flex-wrap:wrap;gap:4px 12px}
.sar-av{display:inline-flex;align-items:flex-start;gap:5px;font-size:11.5px;line-height:1.4;color:var(--sar-ink-2)}
.sar-av .sar-op-g{width:13px;height:13px;margin-top:1px}
.sar-av.ok .sar-op-g{color:var(--ok)}
.sar-av.bad{color:var(--warn)}
.sar-av.muted .sar-op-g{color:var(--sar-ink-2)}
.sar-cand-ops{display:flex;gap:4px}
.sar-op{display:grid;place-items:center;width:32px;height:32px;padding:0;border-radius:8px;border:1px solid var(--sar-hair);background:transparent;color:var(--sar-ink-2);cursor:pointer;transition:color .15s,border-color .15s,background-color .15s}
.sar-op:hover:not(:disabled){color:var(--sar-ink);border-color:color-mix(in srgb,var(--accent) 55%,transparent);background:color-mix(in srgb,var(--accent) 8%,transparent)}
.sar-op[data-sar-cand-op="remove"]:hover:not(:disabled){color:var(--danger);border-color:color-mix(in srgb,var(--danger) 55%,transparent);background:color-mix(in srgb,var(--danger) 8%,transparent)}
.sar .sar-op:disabled{opacity:1;cursor:not-allowed;color:color-mix(in srgb,var(--sar-ink-2) 55%,transparent);border-style:dashed;border-color:color-mix(in srgb,var(--sar-hair) 80%,transparent);background:transparent}
.sar-cand-help{margin:8px 0 0}
.sar-add{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr) auto;align-items:end;gap:10px;margin-top:12px;padding-top:12px;border-top:1px dashed var(--sar-hair)}
.sar-field{display:grid;gap:4px;min-width:0;font-size:11.5px;color:var(--sar-ink-2)}
.sar-field select{width:100%;min-width:0;min-height:34px;padding:6px 8px;border-radius:8px;border:1px solid var(--sar-hair);background:var(--solid);color:var(--sar-ink);font:inherit;font-size:12.5px}
.sar-add-btn{display:inline-flex;align-items:center;gap:6px;min-height:34px;white-space:nowrap}
.sar-add-why{grid-column:1/-1;margin:0}
.sar-fallback{margin-top:14px;padding-top:12px;border-top:1px dashed var(--sar-hair)}
.sar-fallback .hint{margin:6px 0 0 52px}
.sar-switch{display:inline-flex;align-items:center;gap:12px;cursor:pointer;font-size:13px;color:var(--sar-ink)}
.sar-switch input{position:absolute;opacity:0;width:1px;height:1px}
.sar-switch-track{position:relative;width:40px;height:22px;flex:none;border-radius:11px;border:1.5px solid var(--sar-ink-2);transition:background-color .18s,border-color .18s}
.sar-switch-knob{position:absolute;top:3px;left:3px;width:13px;height:13px;border-radius:50%;background:var(--sar-ink-2);transition:transform .18s,background-color .18s}
.sar-switch input:checked+.sar-switch-track{background:color-mix(in srgb,var(--accent) 32%,transparent);border-color:var(--accent)}
.sar-switch input:checked+.sar-switch-track .sar-switch-knob{transform:translateX(18px);background:var(--accent)}
.sar-switch input:focus-visible+.sar-switch-track{outline:2px solid var(--accent);outline-offset:3px}
.sar-switch input:disabled+.sar-switch-track{opacity:.45}
.sar-switch:has(input:disabled){cursor:not-allowed}
.sar-preview{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;align-items:baseline;margin-top:14px;padding:10px 12px;border-radius:10px;
  background:color-mix(in srgb,var(--accent) 6%,transparent);border:1px solid color-mix(in srgb,var(--accent) 22%,transparent);font-size:12.5px}
.sar-preview-k{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--sar-ink-2)}
.sar-preview .hint{grid-column:1/-1;margin:2px 0 0}
.sar-skip{margin:4px 0 0;padding-left:16px;font-size:11.5px;color:var(--sar-ink-2)}
.sar-compat{margin:14px 0 0;padding-top:10px;border-top:1px dashed var(--sar-hair)}
.sar-ov-list{list-style:none;margin:14px 0 0;padding:0;display:grid;gap:6px}
.sar-ov-row{display:grid;grid-template-columns:auto minmax(150px,.8fr) minmax(0,1.6fr) auto auto;align-items:center;gap:8px 14px;padding:10px 12px;border:1px solid var(--sar-hair);border-radius:var(--sar-r);
  background:linear-gradient(105deg,color-mix(in srgb,var(--sar-accent) 9%,transparent),transparent 55%),var(--sar-glass)}
.sar-ov-name{display:grid;gap:4px;font-size:13px;font-weight:600;min-width:0}
.sar-ov-prov{display:flex;flex-wrap:wrap;gap:4px;font-weight:400}
.sar-ov-chain{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:5px;min-width:0}
.sar-ov-c{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;border:1px solid var(--sar-hair);font-size:11.5px;max-width:100%}
.sar-ov-c span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sar-ov-c .sar-op-g{width:12px;height:12px;color:var(--ok)}
.sar-ov-c:first-child{border-color:color-mix(in srgb,var(--sar-accent) 55%,transparent);color:var(--sar-ink)}
.sar-ov-c.unavailable{border-style:dashed;color:var(--warn)}.sar-ov-c.unavailable .sar-op-g{color:var(--warn)}
.sar-ov-fb{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--sar-ink-2);white-space:nowrap}
.sar-ov-fb .sar-op-g{width:12px;height:12px}
@container sarpane (max-width:620px){
  .sar-add{grid-template-columns:minmax(0,1fr)}
  .sar-ov-row{grid-template-columns:auto minmax(0,1fr)}
  .sar-ov-chain,.sar-ov-fb{grid-column:1/-1}
  .sar-ov-row .action{grid-column:1/-1;justify-self:start}
  .sar-cand{grid-template-columns:24px minmax(0,1fr)}
  .sar-cand-ops{grid-column:2;justify-content:flex-start}
  .sar-fallback .hint{margin-left:0}
}
.sar-detail-pane{container:sarpane/inline-size}
@media(max-width:900px){.sar{grid-template-columns:minmax(0,1fr);gap:16px}}
@media(prefers-reduced-motion:reduce){.sar *{transition:none!important}}
@media(forced-colors:active){
  .sar-switch-track,.sar-switch-knob{forced-color-adjust:none;border-color:CanvasText}.sar-switch-knob{background:CanvasText}
  .sar-switch input:checked+.sar-switch-track{background:Highlight;border-color:Highlight}
  .sar-ov-toggle.selected{border:3px solid Highlight}
}
`;

  root.JarvisSubagentSettings=Object.freeze({mountId:MOUNT_ID,STYLE_ID,ICONS:Object.freeze(Object.keys(ICONS)),create,
    createRoutingHttpAdapter:o=>Routing.createHttpAdapter(o),createRoutingFixtureAdapter:(s,o)=>Routing.createFixtureAdapter(s,o),
    mount:()=>root.document?root.document.getElementById(MOUNT_ID):null,
    async show(host,options){const view=create(host,options);await view.load();return view}});
})(typeof window!=='undefined'?window:globalThis);
